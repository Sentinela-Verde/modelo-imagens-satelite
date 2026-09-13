"""Reproduz a frente de impacto inteira — dos dados brutos ao notebook — com um comando.

    python scripts/reproduzir_impacto.py --etapa analise     # padrão: só o que roda offline
    python scripts/reproduzir_impacto.py --etapa completo    # inclui GEE e Overpass
    python scripts/reproduzir_impacto.py --listar            # mostra o plano sem executar

## Por que existe

Reprodutibilidade é regra do repositório (`CLAUDE.md`), e "rode 23 scripts na ordem certa, alguns
com `--fase`" não é reprodutível na prática: é um convite a rodar na ordem errada e não perceber.
Este runner declara a ordem, o custo e a dependência externa de cada passo em um lugar só.

## As duas etapas, e por que não é tudo junto

Os passos se dividem em dois regimes, com propriedades muito diferentes:

- **`rede`** — depende de Earth Engine (ingestão e classificação) ou do Overpass (footprints do
  OSM). São horas, exigem credencial, e falham por motivos fora do repositório (cota, indisponi-
  bilidade, limite de taxa). São também **idempotentes**: cada um pula o que já está em disco.
- **`analise`** — lê rasters e CSVs já em disco e produz as tabelas, figuras e o notebook. Roda em
  minutos, offline, e é o que alguém precisa executar para conferir os números de um relatório.

O padrão é `analise` justamente porque é o caso de uso de quem está verificando o trabalho. Quem
quiser refazer da estaca zero usa `--etapa completo`, com a ressalva de que os passos de rede
podem levar horas.

## O que este runner NÃO faz

Não treina o classificador nem reprocessa a série do repositório principal (`src/sentinela/`) —
aquela frente tem escopo, prazo e reprodução próprios. Aqui o classificador entra como artefato
pronto (`models/rf_v1.0-tuned.joblib`), que é a relação correta entre as duas frentes.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
PY = sys.executable


@dataclass
class Passo:
    ordem: str
    script: Path
    descricao: str
    regime: str                       # "rede" | "analise"
    args: list[str] = field(default_factory=list)
    # Variáveis de ambiente do passo. Hoje só `SENTINELA_MODELO_IMPACTO`, que manda a cadeia
    # medir com um classificador candidato em vez do de produção — sem ela, os passos 30 e 41
    # reclassificariam por cima dos artefatos do `rf_v1.0-tuned`.
    env: dict[str, str] = field(default_factory=dict)

    @property
    def rotulo(self) -> str:
        extra = f" {' '.join(self.args)}" if self.args else ""
        prefixo = "".join(f"{k}={v} " for k, v in self.env.items())
        return f"{self.ordem} {prefixo}{self.script.name}{extra}"


def _imp(nome: str) -> Path:
    """Um script da frente de IMPACTO — `modelo-impacto/scripts/`."""
    return RAIZ / "modelo-impacto" / "scripts" / nome


def _img(nome: str) -> Path:
    """Um script do lado da IMAGEM — `scripts/`, junto do classificador.

    São poucos e todos geram notebook ou figura do modelo 1. Moravam na pasta do
    impacto-score por acidente de organização (era onde já havia gerador de notebook), o que
    fazia a pasta prometer uma coisa e entregar outra.
    """
    return RAIZ / "scripts" / nome


PLANO: list[Passo] = [
    # ---------------------------------------------------------------- coleta e pareamento
    Passo("01", _imp("impacto_dc_01_reconciliar.py"), "reconcilia a lista de data centers", "analise"),
    Passo("02", _imp("impacto_dc_02_estender_landsat.py"), "estende a ingestão Landsat", "rede"),
    Passo("03", _imp("impacto_dc_03_gerar_controles.py"), "gera os controles pareados", "rede"),
    Passo("04", _imp("impacto_dc_04_painel_features.py"), "painel de área por classe", "rede"),
    Passo("05", _imp("impacto_dc_05_grafico_sanidade.py"), "gráfico de sanidade", "analise"),
    Passo("06", _imp("impacto_dc_06_metodologia.py"), "escreve METODOLOGIA.md", "analise"),
    Passo("07", _imp("impacto_dc_07_figuras_apresentacao.py"), "figuras de apresentação", "analise"),
    # ---------------------------------------------------------------- variáveis externas
    Passo("08", _imp("impacto_dc_08_lst_pontos.py"), "LST MODIS dos 30 pontos", "rede"),
    Passo("09", _imp("impacto_dc_09_socioeconomico_pontos.py"), "socioeconômico municipal", "rede"),
    Passo("10", _imp("impacto_dc_10_consolidar.py"), "consolida o painel 204x51", "analise"),
    # ---------------------------------------------------------------- detecção
    Passo("11", _imp("impacto_dc_11_sensibilidade_buffer.py"), "sensibilidade ao raio", "analise"),
    Passo("12", _imp("impacto_dc_12_trajetoria_pixel.py"), "trajetória de pixel (o achado)", "analise"),
    Passo("13", _imp("impacto_dc_13_footprint_osm.py"), "footprints reais no OSM", "rede"),
    Passo("14", _imp("impacto_dc_14_footprint_vs_anel.py"), "decomposição por anel", "analise"),
    Passo("15", _imp("impacto_dc_15_greenfield_brownfield.py"), "greenfield vs brownfield", "analise"),
    # ---------------------------------------------------------------- eixos ambientais
    Passo("16", _imp("impacto_dc_16_lst_did.py"), "LST MODIS: nulo sem poder", "analise"),
    Passo("17", _imp("impacto_dc_17_planilha_resultados.py"), "planilha de resultados", "analise"),
    # ---------------------------------------------------------------- robustez
    Passo("18", _imp("impacto_dc_18_estudo_evento.py"), "estudo de evento", "analise"),
    Passo("19a", _imp("impacto_dc_19_placebo.py"), "placebo: seleção dos pares", "analise",
          ["--fase", "selecao"]),
    Passo("19b", _imp("impacto_dc_19_placebo.py"), "placebo: classifica os parceiros", "rede",
          ["--fase", "classificar"]),
    Passo("19c", _imp("impacto_dc_19_placebo.py"), "placebo: análise", "analise",
          ["--fase", "analise"]),
    Passo("20a", _imp("impacto_dc_20_janela_estendida.py"), "janela estendida: classifica", "rede",
          ["--fase", "classificar"]),
    Passo("20b", _imp("impacto_dc_20_janela_estendida.py"), "janela estendida: análise", "analise",
          ["--fase", "analise"]),
    Passo("21", _imp("impacto_dc_21_tipo_edificacao.py"), "tipo de edificação (OSM)", "rede"),
    Passo("22", _imp("impacto_dc_22_deltas_por_classe.py"), "delta das 5 classes", "analise"),
    Passo("23a", _imp("impacto_dc_23_lst_landsat.py"), "LST Landsat 30 m: baixa", "rede",
          ["--fase", "baixar"]),
    Passo("23b", _imp("impacto_dc_23_lst_landsat.py"), "LST Landsat 30 m: análise", "analise",
          ["--fase", "analise"]),
    # ---------------------------------------------------------------- validação e expansão
    Passo("24a", _imp("impacto_dc_24_validacao_dynamic_world.py"), "Dynamic World: baixa", "rede",
          ["--fase", "baixar"]),
    Passo("24b", _imp("impacto_dc_24_validacao_dynamic_world.py"),
          "validação cruzada de instrumento", "analise", ["--fase", "analise"]),
    Passo("25a", _imp("impacto_dc_25_expansao_amostra.py"), "expansão: lista de campi novos",
          "rede", ["--fase", "lista"]),
    Passo("25b", _imp("impacto_dc_25_expansao_amostra.py"), "expansão: pareia os controles",
          "rede", ["--fase", "controles"]),
    Passo("25c", _imp("impacto_dc_25_expansao_amostra.py"), "expansão: classifica os pares",
          "rede", ["--fase", "classificar"]),
    Passo("26a", _imp("impacto_dc_26_analise_expandida.py"), "expansão: footprints dos novos",
          "rede", ["--fase", "footprints"]),
    Passo("26b", _imp("impacto_dc_26_analise_expandida.py"),
          "o achado com N=20, em três recortes", "analise", ["--fase", "analise"]),

    # ------------------------------------------------- portão do ADR-006 (expansão EUA)
    Passo("27a", _imp("impacto_dc_27_lista_eua.py"), "lista americana via OSM/Overpass",
          "rede", ["--fase", "lista"]),
    Passo("27b", _imp("impacto_dc_27_lista_eua.py"), "funil EUA: a data é o gargalo",
          "analise", ["--fase", "funil"]),
    Passo("28a", _imp("impacto_dc_28_datar_eua_dw.py"), "footprints EUA com geometria",
          "rede", ["--fase", "geometria"]),
    Passo("28b", _imp("impacto_dc_28_datar_eua_dw.py"),
          "data da obra pelo DW dentro do footprint", "rede", ["--fase", "datar"]),
    Passo("28c", _imp("impacto_dc_28_datar_eua_dw.py"), "funil completo e portão do §6",
          "analise", ["--fase", "funil"]),

    # --------------------------------------- portão do ADR-006 §4 (trocar o classificador)
    # O §4 é o critério que decide adoção de um classificador retreinado: instabilidade
    # temporal nos controles, medida sobre os MESMOS pixels e anos em todos os instrumentos.
    # A ordem aqui não é decorativa — 30 produz os rasters que 29 mede, e 29 sem eles só
    # compara os instrumentos que já estão em disco.
    Passo("30", _imp("impacto_dc_30_reclassificar_controles.py"),
          "reclassifica os controles com o candidato (Earth Engine)", "rede",
          ["--fase", "rodar"], {"SENTINELA_MODELO_IMPACTO": "rf_v2.0-dw"}),
    Passo("29", _imp("impacto_dc_29_estabilidade.py"),
          "instabilidade temporal — o critério §4", "analise", ["--fase", "medir"]),

    # ------------------------------------- portão do ADR-006 §6 (expansão para os EUA)
    Passo("31", _imp("impacto_dc_31_lista_mestra.py"),
          "lista mestra Brasil + EUA, com procedência", "analise", ["--fase", "montar"]),
    Passo("32a", _imp("impacto_dc_32_datar_landsat.py"),
          "série Landsat dentro do footprint", "rede", ["--fase", "serie"]),
    Passo("32b", _imp("impacto_dc_32_datar_landsat.py"),
          "valida a datação contra as datas conhecidas", "analise", ["--fase", "validar"]),
    Passo("32c", _imp("impacto_dc_32_datar_landsat.py"),
          "data da obra por Landsat (alcança antes de 2016)", "analise", ["--fase", "datar"]),
    Passo("33a", _imp("impacto_dc_33_ingerir_eua.py"),
          "ingere o datacentermap americano", "analise", ["--fase", "ingerir"]),
    Passo("33b", _imp("impacto_dc_33_ingerir_eua.py"),
          "funil EUA com greenfield explícito", "analise", ["--fase", "funil"]),
    Passo("34", _imp("impacto_dc_34_parear_eua.py"),
          "pareia controles americanos via Dynamic World", "rede", ["--fase", "parear"]),

    # ---------------------------------------------------------------- robustez e alcance
    Passo("35", _imp("impacto_dc_35_robustez_ruido.py"),
          "superfície de robustez: o achado sobrevive a exigir mais?", "analise",
          ["--fase", "medir"]),
    Passo("36a", _imp("impacto_dc_36_descritivo.py"),
          "descritivo de 612 campi nas Américas (Earth Engine)", "rede", ["--fase", "medir"]),
    Passo("36b", _imp("impacto_dc_36_descritivo.py"),
          "relatório descritivo, sem afirmação causal", "analise", ["--fase", "relatar"]),
    Passo("37a", _imp("impacto_dc_37_gradiente_5km.py"),
          "gradiente de distância até 5 km", "analise", ["--fase", "medir"]),
    Passo("37b", _imp("impacto_dc_37_gradiente_5km.py"),
          "placebo nos mesmos anéis de 5 km", "analise", ["--fase", "placebo"]),

    # ------------------------------------------------- modelo 4 (WIP, não é entregável)
    # Aprovado no critério do handoff e arquivado por decisão do grupo — ver ENTREGAVEIS.md.
    # Fica no plano porque o código existe e precisa continuar reproduzível; quem só quer
    # conferir os números do relatório pode pular (`--ate 37b`).
    Passo("40a", _imp("impacto_dc_40_modelo_conversao.py"),
          "modelo 4: monta o dataset por pixel", "analise", ["--fase", "dataset"]),
    Passo("40b", _imp("impacto_dc_40_modelo_conversao.py"),
          "modelo 4: treina", "analise", ["--fase", "treinar"]),
    Passo("40c", _imp("impacto_dc_40_modelo_conversao.py"),
          "modelo 4: avalia sob leave-one-site-out", "analise", ["--fase", "avaliar"]),
    Passo("40d", _imp("impacto_dc_40_modelo_conversao.py"),
          "modelo 4: ablação de features", "analise", ["--fase", "ablacao"]),

    # ------------------------------------------- cruzamento de classificador (passo 41)
    # Precisa dos rasters de TRATAMENTO do candidato, que `sentinela.predict` gera a partir
    # das features já em disco — sem rede. O passo 26 roda de novo, agora com o candidato,
    # e escreve em `analise_expandida__rf_v2.0-dw.csv`, nunca por cima do publicado.
    Passo("41a", RAIZ / "scripts" / "classificar_com_candidato.py",
          "classifica os tratamentos com o candidato (offline)", "analise"),
    Passo("41b", _imp("impacto_dc_26_analise_expandida.py"),
          "refaz o achado com o candidato", "analise", ["--fase", "analise"],
          {"SENTINELA_MODELO_IMPACTO": "rf_v2.0-dw"}),
    Passo("41c", _imp("impacto_dc_41_cruzar_classificador.py"),
          "o mesmo teste, os mesmos pares, dois classificadores", "analise"),

    # ---------------------------------------------------------------- modelo de score
    Passo("S1", _imp("score_01_boletim.py"), "camada 1 — boletim por eixo", "analise"),
    Passo("S2", _imp("score_02_explicacao.py"), "camada 2 — poder preditivo (LOOCV)", "analise"),
    Passo("S3", _imp("score_03_projecao.py"), "camada 3 — projeção por classe", "analise"),
    Passo("S4", _imp("nb_02_impacto_score.py"), "notebook 02 — demo do impacto", "analise"),
    Passo("S5", _img("figuras_demo_visual.py"), "figuras visuais do classificador", "analise"),
    Passo("S6", _img("nb_04_demo_visual.py"), "notebook 04 — demo visual", "analise"),
    Passo("S7", _imp("nb_03_status.py"), "notebook 03 — status", "analise"),
    # Estes três nunca tinham entrado no plano, e por isso os notebooks 05, 06, 07 e 08 eram os
    # únicos do repositório que ninguém reproduzia com um comando — justamente os que o grupo
    # combinou entregar como "construção" e "demo" de cada modelo.
    Passo("S8", _imp("nb_05_descritivo.py"), "notebook 05 — descritivo de 612 campi", "analise"),
    Passo("S9", _imp("nb_07_08_modelo2.py"),
          "notebooks 07 e 08 — construção e demo do modelo 2", "analise"),
    Passo("S10", _img("nb_06_modelo1_construcao.py"),
          "notebook 06 — construção do modelo 1", "analise"),
]


def listar(passos: list[Passo]) -> None:
    print(f"{'':4s} {'regime':8s} passo")
    for p in passos:
        marca = "REDE" if p.regime == "rede" else "    "
        print(f"{marca:4s} {p.regime:8s} {p.rotulo:52s} {p.descricao}")
    n_rede = sum(1 for p in passos if p.regime == "rede")
    print(f"\n{len(passos)} passos ({n_rede} dependem de rede/credencial)")


def executar(passos: list[Passo], parar_no_erro: bool) -> int:
    falhas: list[tuple[Passo, int]] = []
    inicio_geral = time.time()
    for i, p in enumerate(passos, 1):
        if not p.script.exists():
            print(f"[{i}/{len(passos)}] {p.rotulo} — SCRIPT NAO ENCONTRADO, pulando")
            falhas.append((p, -1))
            continue
        print(f"\n[{i}/{len(passos)}] {p.rotulo} — {p.descricao}")
        t0 = time.time()
        ambiente = {**os.environ, **p.env} if p.env else None
        r = subprocess.run([PY, str(p.script), *p.args], cwd=RAIZ, env=ambiente)
        dt = time.time() - t0
        if r.returncode == 0:
            print(f"    OK ({dt:.0f}s)")
        else:
            print(f"    FALHOU (codigo {r.returncode}, {dt:.0f}s)")
            falhas.append((p, r.returncode))
            if parar_no_erro:
                break

    total = time.time() - inicio_geral
    print(f"\n{'=' * 70}")
    print(f"{len(passos) - len(falhas)}/{len(passos)} passos OK em {total / 60:.1f} min")
    if falhas:
        print("\nfalhas:")
        for p, c in falhas:
            print(f"  {p.rotulo}  (codigo {c})")
    return 1 if falhas else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--etapa", choices=["analise", "completo"], default="analise",
                    help="analise (padrão): só o que roda offline · completo: inclui GEE/Overpass")
    ap.add_argument("--listar", action="store_true", help="mostra o plano e sai")
    ap.add_argument("--continuar-no-erro", action="store_true",
                    help="não para no primeiro passo que falhar")
    args = ap.parse_args()

    passos = PLANO if args.etapa == "completo" else [p for p in PLANO if p.regime == "analise"]

    if args.listar:
        listar(passos)
        return 0

    print(f"etapa: {args.etapa} · {len(passos)} passos · python: {PY}")
    if args.etapa == "completo":
        print("ATENCAO: os passos de rede podem levar horas e exigem credencial do Earth Engine.")
        print("Todos sao idempotentes — o que ja estiver em disco e pulado.\n")
    return executar(passos, parar_no_erro=not args.continuar_no_erro)


if __name__ == "__main__":
    raise SystemExit(main())

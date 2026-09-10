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

    @property
    def rotulo(self) -> str:
        extra = f" {' '.join(self.args)}" if self.args else ""
        return f"{self.ordem} {self.script.name}{extra}"


def _dmi(nome: str) -> Path:
    return RAIZ / "dados-modelo-impacto" / "scripts" / nome


def _mis(nome: str) -> Path:
    return RAIZ / "modelo-impacto-score" / "scripts" / nome


PLANO: list[Passo] = [
    # ---------------------------------------------------------------- coleta e pareamento
    Passo("01", _dmi("impacto_dc_01_reconciliar.py"), "reconcilia a lista de data centers", "analise"),
    Passo("02", _dmi("impacto_dc_02_estender_landsat.py"), "estende a ingestão Landsat", "rede"),
    Passo("03", _dmi("impacto_dc_03_gerar_controles.py"), "gera os controles pareados", "rede"),
    Passo("04", _dmi("impacto_dc_04_painel_features.py"), "painel de área por classe", "rede"),
    Passo("05", _dmi("impacto_dc_05_grafico_sanidade.py"), "gráfico de sanidade", "analise"),
    Passo("06", _dmi("impacto_dc_06_metodologia.py"), "escreve METODOLOGIA.md", "analise"),
    Passo("07", _dmi("impacto_dc_07_figuras_apresentacao.py"), "figuras de apresentação", "analise"),
    # ---------------------------------------------------------------- variáveis externas
    Passo("08", _dmi("impacto_dc_08_lst_pontos.py"), "LST MODIS dos 30 pontos", "rede"),
    Passo("09", _dmi("impacto_dc_09_socioeconomico_pontos.py"), "socioeconômico municipal", "rede"),
    Passo("10", _dmi("impacto_dc_10_consolidar.py"), "consolida o painel 204x51", "analise"),
    # ---------------------------------------------------------------- detecção
    Passo("11", _dmi("impacto_dc_11_sensibilidade_buffer.py"), "sensibilidade ao raio", "analise"),
    Passo("12", _dmi("impacto_dc_12_trajetoria_pixel.py"), "trajetória de pixel (o achado)", "analise"),
    Passo("13", _dmi("impacto_dc_13_footprint_osm.py"), "footprints reais no OSM", "rede"),
    Passo("14", _dmi("impacto_dc_14_footprint_vs_anel.py"), "decomposição por anel", "analise"),
    Passo("15", _dmi("impacto_dc_15_greenfield_brownfield.py"), "greenfield vs brownfield", "analise"),
    # ---------------------------------------------------------------- eixos ambientais
    Passo("16", _dmi("impacto_dc_16_lst_did.py"), "LST MODIS: nulo sem poder", "analise"),
    Passo("17", _dmi("impacto_dc_17_planilha_resultados.py"), "planilha de resultados", "analise"),
    # ---------------------------------------------------------------- robustez
    Passo("18", _dmi("impacto_dc_18_estudo_evento.py"), "estudo de evento", "analise"),
    Passo("19a", _dmi("impacto_dc_19_placebo.py"), "placebo: seleção dos pares", "analise",
          ["--fase", "selecao"]),
    Passo("19b", _dmi("impacto_dc_19_placebo.py"), "placebo: classifica os parceiros", "rede",
          ["--fase", "classificar"]),
    Passo("19c", _dmi("impacto_dc_19_placebo.py"), "placebo: análise", "analise",
          ["--fase", "analise"]),
    Passo("20a", _dmi("impacto_dc_20_janela_estendida.py"), "janela estendida: classifica", "rede",
          ["--fase", "classificar"]),
    Passo("20b", _dmi("impacto_dc_20_janela_estendida.py"), "janela estendida: análise", "analise",
          ["--fase", "analise"]),
    Passo("21", _dmi("impacto_dc_21_tipo_edificacao.py"), "tipo de edificação (OSM)", "rede"),
    Passo("22", _dmi("impacto_dc_22_deltas_por_classe.py"), "delta das 5 classes", "analise"),
    Passo("23a", _dmi("impacto_dc_23_lst_landsat.py"), "LST Landsat 30 m: baixa", "rede",
          ["--fase", "baixar"]),
    Passo("23b", _dmi("impacto_dc_23_lst_landsat.py"), "LST Landsat 30 m: análise", "analise",
          ["--fase", "analise"]),
    # ---------------------------------------------------------------- modelo de score
    Passo("S1", _mis("01_boletim.py"), "camada 1 — boletim por eixo", "analise"),
    Passo("S2", _mis("02_explicacao.py"), "camada 2 — poder preditivo (LOOCV)", "analise"),
    Passo("S3", _mis("03_projecao.py"), "camada 3 — projeção por classe", "analise"),
    Passo("S4", _mis("04_gerar_notebook.py"), "notebook de demo (gera e executa)", "analise"),
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
        r = subprocess.run([PY, str(p.script), *p.args], cwd=RAIZ)
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

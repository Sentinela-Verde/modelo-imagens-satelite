"""Passo 29 — instabilidade temporal nos controles: o critério §4 do ADR-006.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_29_estabilidade.py --fase medir

## Por que este passo existe

O ADR-006 §4 define o critério que decide se um classificador retreinado substitui o
atual, e ele **não é acurácia**:

  > Acurácia contra o DW mede só quão bem destilamos o DW. A pergunta que importa para
  > esta frente é outra: **o modelo é temporalmente estável?** A estatística de trajetória
  > exige que um pixel mantenha a classe por anos; um classificador que oscila destrói o
  > sinal antes de qualquer análise.
  >
  > O modelo global só substitui o atual se ficar **abaixo de 7,3%** de instabilidade nos
  > controles — ou seja, se for mais estável que o próprio rótulo que o treinou. Se não
  > for, usar o Dynamic World direto é a decisão certa.

O número existia no ADR mas **não existia como código**: 16,8% e 7,3% foram calculados de
forma avulsa em 2026-09-10. Um criterio de aceite que nao se reproduz nao e criterio. Este
passo torna a medicao executavel e versionada, e serve para avaliar qualquer classificador
novo contra o mesmo padrao.

## A medida

Fração de pixels que **trocam de classe entre anos consecutivos** nos pontos de
**controle**. A escolha dos controles é o que dá sentido à métrica: por construção nenhum
data center foi construído ali, então a paisagem é aproximadamente estável e **toda troca
de classe é ruído do instrumento**, não mudança real.

Não é zero o ideal — floresta vira pasto, lavoura roda, rio seca. Mas é uma medida
comparável entre instrumentos sobre exatamente os mesmos pixels e os mesmos anos.

## O que fica de fora, e por quê

  - Pixels com nodata em qualquer dos dois anos do par — a troca seria artefato de borda.
  - Pares de anos não consecutivos.
  - Pontos de tratamento — ali a mudança é real e contaminaria a medida de ruído.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402

DIR_DW = C.DIR_SAIDA / "dynamic_world"
SAIDA = C.DIR_SAIDA / "estabilidade_controles.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "estabilidade_resumo.csv"

# DW label -> nossas 5 classes (mesma tabela do passo 24 e de config/classes.yml)
REMAP_DW = {0: 5, 1: 1, 2: 2, 3: 5, 4: 2, 5: 2, 6: 4, 7: 3, 8: 5}


def _ler(caminho: Path) -> np.ndarray | None:
    if not caminho.exists():
        return None
    with rasterio.open(caminho) as src:
        return src.read(1)


def _remapear_dw(arr: np.ndarray) -> np.ndarray:
    out = np.zeros_like(arr, dtype=np.uint8)
    for origem, destino in REMAP_DW.items():
        out[arr == origem] = destino
    return out


def _trocas(a: np.ndarray, b: np.ndarray) -> tuple[int, int]:
    """(pixels que trocaram, pixels validos nos dois anos). 0 = nodata."""
    valido = (a > 0) & (b > 0)
    n = int(valido.sum())
    return int((valido & (a != b)).sum()), n


def _controles() -> pd.DataFrame:
    par = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv")
    par = par[par.site_id_controle.notna() & (par.site_id_controle != "")]
    cols = ["site_id", "site_id_controle", "ano_inicio_obra", "sensor"]
    return par[cols].copy()


def fase_medir() -> None:
    controles = _controles()
    registros = []

    for _, r in controles.iterrows():
        ctrl = r.site_id_controle
        anos = C.janela_anos(int(r.ano_inicio_obra))

        # --- nosso classificador (rf_v1.0-tuned), na grade de 30 m -------------------
        pilha_rf = {}
        for ano in anos:
            arr = _ler(Path(C.caminho_classificado(r.sensor, ctrl, ano)))
            if arr is not None:
                pilha_rf[ano] = arr

        # --- Dynamic World, na grade nativa de 10 m ---------------------------------
        pilha_dw = {}
        for ano in anos:
            arr = _ler(DIR_DW / ctrl / f"{ano}.tif")
            if arr is not None:
                pilha_dw[ano] = _remapear_dw(arr)

        for nome, pilha in (("rf_v1.0-tuned", pilha_rf), ("dynamic_world", pilha_dw)):
            disponiveis = sorted(pilha)
            for a0, a1 in zip(disponiveis, disponiveis[1:]):
                if a1 - a0 != 1:
                    continue
                trocou, validos = _trocas(pilha[a0], pilha[a1])
                if not validos:
                    continue
                registros.append({
                    "controle": ctrl, "instrumento": nome,
                    "ano_de": a0, "ano_para": a1,
                    "px_trocaram": trocou, "px_validos": validos,
                    "pct_trocaram": 100.0 * trocou / validos,
                })
        print(f"  {ctrl} ok")

    df = pd.DataFrame(registros)
    if df.empty:
        sys.exit("nenhum par de anos consecutivos encontrado")

    # Comparacao so vale sobre os MESMOS pixels e os MESMOS anos. O DW cobre menos
    # controles que o nosso RF (a serie comeca em jun/2015), e comparar 15 controles
    # nossos contra 10 deles mediria dois conjuntos diferentes, nao dois instrumentos.
    chave = ["controle", "ano_de", "ano_para"]
    comuns = set.intersection(*(
        set(map(tuple, g[chave].values)) for _, g in df.groupby("instrumento")
    ))
    df["par_comum"] = [tuple(x) in comuns for x in df[chave].values]
    C.salvar_csv(df, SAIDA)
    print(f"\n  {len(comuns)} pares (controle, ano->ano) cobertos pelos DOIS instrumentos")
    df = df[df.par_comum]

    # agregado ponderado por pixel: um controle grande nao vale o mesmo que um pequeno,
    # e a media de porcentagens esconderia isso
    linhas = []
    for nome, g in df.groupby("instrumento"):
        linhas.append({
            "instrumento": nome,
            "n_controles": g.controle.nunique(),
            "n_pares_de_anos": len(g),
            "px_validos": int(g.px_validos.sum()),
            "pct_instabilidade": 100.0 * g.px_trocaram.sum() / g.px_validos.sum(),
            "pct_mediano_por_par": float(g.pct_trocaram.median()),
        })
    resumo = pd.DataFrame(linhas).sort_values("pct_instabilidade")
    C.salvar_csv(resumo, SAIDA_RESUMO)

    print()
    print("--- instabilidade nos controles (troca de classe entre anos consecutivos) ---")
    for _, r0 in resumo.iterrows():
        print(f"  {r0.instrumento:<18}{r0.pct_instabilidade:>7.1f}%   "
              f"({r0.n_controles} controles, {r0.n_pares_de_anos} pares de anos, "
              f"{r0.px_validos:,} px)")

    dw = resumo[resumo.instrumento == "dynamic_world"]
    if not dw.empty:
        limiar = float(dw.pct_instabilidade.iloc[0])
        print()
        print(f"  CRITERIO §4: um classificador nosso so substitui o atual se ficar")
        print(f"  ABAIXO de {limiar:.1f}% -- a instabilidade do proprio rotulo que o treina.")
        for _, r0 in resumo[resumo.instrumento != "dynamic_world"].iterrows():
            veredito = "PASSA" if r0.pct_instabilidade < limiar else "REPROVA"
            print(f"    {r0.instrumento:<18}{r0.pct_instabilidade:>7.1f}%  -> {veredito}")

    print()
    print(f"  -> {SAIDA_RESUMO.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("medir",), required=True)
    ap.parse_args()
    fase_medir()


if __name__ == "__main__":
    main()

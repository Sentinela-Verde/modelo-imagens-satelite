"""Classifica os sites de TRATAMENTO com um modelo candidato, em diretório próprio.

    python scripts/classificar_com_candidato.py                     # usa rf_v2.0-dw
    SENTINELA_MODELO_IMPACTO=rf_v3.0 python scripts/classificar_com_candidato.py

## Por que isto é um script e não uma linha de comando no README

Chamar `sentinela.predict` com o `.joblib` errado e sem `--saida-token` grava por cima dos
rasters de produção — os mesmos de que dependem o achado de 18/20 pares, o placebo e toda a
tabela do relatório. O apagão seria silencioso: o `.tif` novo tem exatamente o mesmo nome do
antigo, e só o `gerado_em` da tag mudaria.

Este wrapper existe para que o par (modelo, diretório de saída) nunca seja digitado em
separado. O token de saída é **derivado** do nome do modelo, e o de produção é recusado.

O lado de CONTROLE não é feito aqui: os intermediários dos controles são descartados de
propósito depois de classificados, então reclassificá-los custa reingerir do Earth Engine —
é o passo 30. Os tratamentos são baratos porque as features deles ficam em disco.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "src"))

from sentinela import predict  # noqa: E402

MODELO_PRODUCAO = "rf_v1.0-tuned"
PADRAO = "rf_v2.0-dw"


def main(argv: list[str] | None = None) -> int:
    # Um parser mesmo sem opções nenhuma, de propósito: sem ele, qualquer argumento — um
    # `--help` incluído — era silenciosamente ignorado e o script saía classificando. O modelo
    # vem de `SENTINELA_MODELO_IMPACTO` e o diretório é derivado dele; não há o que passar aqui.
    argparse.ArgumentParser(
        description=("Classifica os sites de tratamento com um modelo candidato, em diretório "
                     "próprio. O modelo vem da variável de ambiente SENTINELA_MODELO_IMPACTO "
                     f"(padrão: {PADRAO}); o diretório de saída é derivado do nome dele."),
    ).parse_args(argv)

    versao = os.environ.get("SENTINELA_MODELO_IMPACTO", PADRAO)
    if versao == MODELO_PRODUCAO:
        print(f"ERRO: {versao} é o modelo de PRODUÇÃO.\n"
              f"Para regerar os rasters de produção use `python -m sentinela.predict` direto e "
              f"de propósito — este wrapper só serve para avaliar um candidato sem tocar neles.",
              file=sys.stderr)
        return 2

    modelo = RAIZ / "models" / f"{versao}.joblib"
    if not modelo.exists():
        print(f"ERRO: {modelo} não existe.", file=sys.stderr)
        return 1

    token = f"classificado-{versao}"
    print(f"modelo   : {modelo.name}")
    print(f"saída    : data/processed/{token}/")
    print(f"produção : data/processed/{predict.TOKEN_SAIDA_PADRAO}/ (intacta)\n")

    return predict.main([
        "--modelo", str(modelo),
        "--sensor", "all",
        "--site", "all",
        "--saida-token", token,
    ])


if __name__ == "__main__":
    raise SystemExit(main())

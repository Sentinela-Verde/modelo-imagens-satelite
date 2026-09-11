"""Passo 2 — estender a ingestão Landsat dos sites de TRATAMENTO até 2024.

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_02_estender_landsat.py [--force] [--sites a,b]

Por que isto existe: o repositório ingeriu Landsat só até 2021 (`config/params.yml`, faixa_a usa
Sentinel-2 de 2019 em diante; a sobreposição 2019-2021 existia para SV-20 medir o viés entre
sensores). Com a janela deste estudo sendo `obra-3 .. obra+3`, quatro campi
(`ascenty-jundiai`, `ascenty-osasco`, `ascenty-paulinia`, `equinix-santana-parnaiba`) e mais dois
que entraram na amostra ampliada (`ascenty-vinhedo`, `everest-goiania`, `scala-tambore`)
precisariam atravessar a fronteira 2018/2019 — e SV-20 (`reports/validacao_sensores.md`) mediu que,
em 48 de 48 pares, o degrau da classe "solo exposto/obras" nessa fronteira é indistinguível do
artefato de troca de instrumento. Ingerir Landsat 2022-2024 deixa a janela desses campi inteira num
sensor só.

Efeito colateral esperado e aprovado: estes anos passam a existir em
`data/processed/classificado/landsat/`, então a próxima execução de
`python -m sentinela.export_indicadores` acrescenta linhas a
`outputs/indicadores/area_por_classe.csv`. Isso muda o output consumido pela etapa de Indicadores
e por isso foi sinalizado antes de implementar, como pede o `CLAUDE.md` da raiz.

Não toca em nada dos anos já ingeridos: cada etapa do pipeline pula o que já existe e confere o
sha256 (use `--force` para regerar).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import impacto_dc_comum as C


def itens_faltando(sites_filtro: set[str] | None) -> list[tuple[dict, int, str]]:
    """(campus, ano, sensor) que a janela exige e ainda não tem raster classificado."""
    faltando = []
    for campus in C.carregar_campi():
        if sites_filtro and campus["site_id"] not in sites_filtro:
            continue
        anos = C.janela_anos(campus["ano_inicio_obra"])
        sensor = C.sensor_da_janela(anos)
        for ano in anos:
            if not C.caminho_classificado(sensor, campus["site_id"], ano).exists():
                faltando.append((campus, ano, sensor))
    return faltando


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Estende a ingestão Landsat dos tratamentos (passo 2).")
    parser.add_argument("--force", action="store_true", help="regera mesmo se já existir")
    parser.add_argument("--sites", default=None, help="lista de site_id separada por vírgula")
    args = parser.parse_args(argv)

    sites_filtro = set(args.sites.split(",")) if args.sites else None
    itens = itens_faltando(sites_filtro)
    if not itens:
        print("Nada a fazer — todos os site-anos da janela já estão classificados.")
        return 0

    print(f"Passo 2 — {len(itens)} site-ano(s) de tratamento a processar:")
    for campus, ano, sensor in itens:
        print(f"    {campus['site_id']} {ano} ({sensor})")

    C.iniciar_ee()
    pacote = C.carregar_modelo()
    checkpoint = C.Checkpoint(C.DIR_SAIDA / "_checkpoint_passo2.json")
    falhas = []

    for i, (campus, ano, sensor) in enumerate(itens, 1):
        chave = f"{sensor}/{campus['site_id']}/{ano}"
        if not args.force and checkpoint.get(chave) == "ok":
            print(f"[{i}/{len(itens)}] {chave} — já feito (checkpoint), pulando")
            continue
        t0 = time.time()
        print(f"[{i}/{len(itens)}] {chave} ...")
        try:
            C.rodar_ponto(campus, ano, sensor, pacote, force=args.force)
            checkpoint.set(chave, "ok")
            print(f"[{i}/{len(itens)}] {chave} OK em {time.time() - t0:.0f}s")
        except Exception as exc:  # noqa: BLE001 — uma falha de rede não pode matar o lote
            # Mesma política de `sentinela.gee.executar_lote`: falha em um item é registrada e o
            # lote segue. Rodar o script de novo retoma só o que faltou.
            falhas.append((chave, repr(exc)))
            checkpoint.set(chave, f"erro: {exc!r}")
            print(f"[{i}/{len(itens)}] {chave} FALHOU: {exc!r}")

    print()
    print(f"Concluído: {len(itens) - len(falhas)} ok, {len(falhas)} falha(s).")
    for chave, erro in falhas:
        print(f"  FALHA {chave}: {erro}")
    if falhas:
        print("Rode o script de novo para retomar só os que falharam (checkpoint).")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())

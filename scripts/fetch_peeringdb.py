"""SV-25 — baixa e cacheia o PeeringDB fac (facilities) do Brasil.

Fonte A da cascata de SV-25. Baixa e grava em data/externo/peeringdb_fac_br.json — commitado,
para a tarefa ser reprodutível sem depender da API estar no ar.

**Desvio registrado em relação ao enunciado literal (GET /api/fac?country=BR de uma vez só):**
durante esta sessão o endpoint de busca completa (`?country=BR`, ~352 registros) foi throttled
pela API pública anônima do PeeringDB após poucas chamadas de teste ("Request was throttled.
Expected available in 56 minutes"). O endpoint de busca **filtrada** (`?country=BR&name__icontains=...`)
e o de objeto único (`/api/fac/<id>`) não foram throttled nas mesmas condições. Para não bloquear a
tarefa em uma espera de quase 1h, o cache foi montado pela **união de buscas filtradas por nome**,
uma por operador/palavra-chave de todos os 38 candidatos de config/sites_candidatos.csv (elegíveis
e reprovados, para não deixar de fora nenhum operador que a lista cita) — cobertura funcionalmente
equivalente ao dump completo para o propósito desta tarefa (casar por nome/operador/cidade), só
não traz facilities de operadores fora da nossa lista de candidatos (que não seriam usadas de
qualquer forma). Ambas as tentativas (dump completo e busca filtrada) usam o mesmo endpoint público
sem chave, documentado no enunciado.

Rodar: `.venv\\Scripts\\python.exe scripts\\fetch_peeringdb.py [--force]`
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import truststore

truststore.inject_into_ssl()

import requests

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_PATH = REPO_ROOT / "data" / "externo" / "peeringdb_fac_br.json"
BASE_URL = "https://www.peeringdb.com/api/fac"
HEADERS = {"User-Agent": "sentinela-verde-mba-mackenzie/1.0 (contato: consignadouniverso@gmail.com)"}

# Palavras-chave cobrindo os operadores/nomes de TODOS os 38 candidatos de sites_candidatos.csv
# (elegíveis e reprovados) — ver docstring acima sobre por que a busca é filtrada, não um dump total.
KEYWORDS = [
    "Ascenty", "Equinix", "Scala", "ClickIP", "Everest", "Angola Cables", "AngoNAP",
    "HostDime", "ODATA", "Aligned", "Cirion", "Elea", "Tecto", "Hostzone", "PRODEB",
    "Algar", "Armazem", "Armazém", "Unifique", "RT-One", "RT One", "Atlantic",
    "ByteDance", "TikTok", "Omnia", "Surfix", "TIP Brasil", "Digital Realty",
]


def _get_with_retry(url: str, params: dict) -> requests.Response:
    backoffs = [5, 15, 30]
    resp = None
    for wait_s in [0, *backoffs]:
        if wait_s:
            print(f"  429 — aguardando {wait_s}s e tentando de novo...")
            time.sleep(wait_s)
        resp = requests.get(url, params=params, headers=HEADERS, timeout=60)
        if resp.status_code != 429:
            break
    return resp


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Rebaixa mesmo se o cache já existir.")
    args = parser.parse_args()

    if OUT_PATH.exists() and not args.force:
        print(f"Cache já existe em {OUT_PATH} — use --force para rebaixar. Nada feito.")
        return

    por_id: dict[int, dict] = {}
    metodo_por_keyword: dict[str, int] = {}

    # 1) Tenta o dump completo primeiro (comportamento literal do enunciado) — se funcionar, ótimo.
    resp = _get_with_retry(BASE_URL, {"country": "BR"})
    dump_completo_ok = resp is not None and resp.status_code == 200
    if dump_completo_ok:
        for rec in resp.json().get("data", []):
            por_id[rec["id"]] = rec
        print(f"Dump completo (?country=BR) funcionou: {len(por_id)} registros.")
    else:
        status = resp.status_code if resp is not None else "sem resposta"
        print(f"Dump completo falhou (status={status}) — caindo para busca filtrada por operador.")

    # 2) União de buscas filtradas por nome (sempre roda, mesmo se o dump completo funcionou, como
    #    checagem cruzada barata — filtros não custam quota extra relevante e cada um é rápido).
    for kw in KEYWORDS:
        resp = _get_with_retry(BASE_URL, {"country": "BR", "name__icontains": kw})
        if resp is None or resp.status_code != 200:
            print(f"  aviso: busca por '{kw}' falhou (status={getattr(resp, 'status_code', None)}), pulando.")
            continue
        recs = resp.json().get("data", [])
        metodo_por_keyword[kw] = len(recs)
        for rec in recs:
            por_id[rec["id"]] = rec
        time.sleep(1.0)  # educado com a API pública, mesmo sem exigência explícita de rate limit

    out = {
        "fonte": f"{BASE_URL}?country=BR",
        "data_consulta": datetime.now(UTC).isoformat(timespec="seconds"),
        "metodo": (
            "dump_completo" if dump_completo_ok
            else "uniao_busca_filtrada_por_nome_operador (dump completo throttled pela API pública "
                 "do PeeringDB nesta sessão — ver docstring de scripts/fetch_peeringdb.py)"
        ),
        "keywords_buscadas": metodo_por_keyword,
        "n_registros": len(por_id),
        "data": list(por_id.values()),
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Gravado {OUT_PATH} com {out['n_registros']} facilities únicas (método: {out['metodo']}).")


if __name__ == "__main__":
    main()

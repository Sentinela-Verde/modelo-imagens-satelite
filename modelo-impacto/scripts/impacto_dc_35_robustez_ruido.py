"""Passo 35 — o achado sobrevive a exigências mais estritas contra ruído?

Rode com:

    python modelo-impacto/scripts/impacto_dc_35_robustez_ruido.py --fase medir

## A objeção que este passo existe para responder

O passo 24 mostrou que o achado de destaque **não replica** sob o Dynamic World
(9/14, p=0,212 contra 14/14, p=0,0001 do nosso RF). O passo 29 mediu por quê é
difícil defender o nosso lado: `rf_v1.0-tuned` troca a classe de **17,5%** dos pixels
entre anos consecutivos nos controles, contra **7,2%** do DW. Somos 2,4x mais
ruidosos, e o retreino (13,1%) não fechou a diferença.

A objeção que sobra é direta: **"o efeito de vocês é ruído do classificador."**

Ela não se responde com argumento. Se responde medindo o quanto o achado depende da
tolerância a ruído — e é isso aqui.

## Os dois eixos, e por que são estes

**Anos de ponta (`n_ponta`).** A assinatura exige não-construída nos N primeiros anos
E construída nos N últimos. N=1 aceita uma troca isolada; N=3 exige que a mudança se
sustente por três anos de cada lado. Ruído aleatório quase nunca produz três anos
consecutivos coerentes dos dois lados — então exigir mais é um filtro de ruído direto,
que custa amostra.

**Confiança do classificador.** Cada raster classificado tem um `_confianca.tif` de 0
a 100 que nunca foi usado nesta frente. Restringir a pixels de alta confiança remove
justamente onde o modelo está inseguro, que é onde o ruído mora.

Os dois são independentes: o primeiro filtra no tempo, o segundo no espaço.

## Como ler o resultado

Se o excesso e o p-valor **sobrevivem** à diagonal mais estrita (n_ponta=3 e confiança
alta), o ruído não explica o achado — e isso é medido, não argumentado. Se **colapsam**,
o achado depende da tolerância a ruído e precisa ser reportado assim.

As duas respostas são publicáveis. A que não é publicável é não ter medido.
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_12_trajetoria_pixel as P12  # noqa: E402
import impacto_dc_26_analise_expandida as P26  # noqa: E402

SAIDA = C.DIR_SAIDA / "robustez_ruido.csv"
SAIDA_SUP = C.DIR_SAIDA / "robustez_superficie.csv"

ZONA = ("0.5-1km", 0.5, 1.0)   # o recorte de destaque do relatório
CONSTRUIDA = P12.CONSTRUIDA
N_PONTAS = [1, 2, 3]
LIMIARES_CONF = [0, 70, 85, 95]


def _empilhar_confianca(site_id: str, sensor: str, anos: list[int]) -> np.ndarray | None:
    camadas = []
    for ano in sorted(anos):
        p = Path(C.caminho_classificado(sensor, site_id, ano))
        pc = p.with_name(f"{p.stem}_confianca{p.suffix}")
        if not pc.exists():
            return None
        with rasterio.open(pc) as src:
            camadas.append(src.read(1))
    return np.stack(camadas)


def _virou_construida(pilha: np.ndarray, conf: np.ndarray | None,
                      mascara: np.ndarray, n_ponta: int, conf_min: int) -> tuple[int, int]:
    """(pixels que viraram construída, pixels válidos) sob os dois critérios."""
    if pilha.shape[0] < 2 * n_ponta:
        return 0, 0
    valido = np.all(pilha > 0, axis=0) & mascara
    if conf_min > 0:
        if conf is None:
            return 0, 0
        # Confiança é exigida SÓ NAS PONTAS, não em todos os anos.
        #
        # A primeira versão deste passo exigia em todos, e o resultado foi um artefato:
        # a conf>=95 sobravam 16 pixels de 2.620 (0,6%) e o efeito "sumia". Dois motivos
        # se somavam. O óbvio: exigir 7 anos de confiança alta é 7 filtros em série.
        # O grave: um pixel EM OBRA passa por solo exposto e construção parcial, que é
        # exatamente quando o classificador fica inseguro — então o filtro removia
        # preferencialmente os pixels que carregam o sinal.
        #
        # A assinatura lê as pontas: não-construída no início, construída no fim. É aí
        # que a classe precisa ser confiável. O meio pode ser ambíguo à vontade — é
        # esperado que seja.
        conf_ini = np.all(conf[:n_ponta] >= conf_min, axis=0)
        conf_fim = np.all(conf[-n_ponta:] >= conf_min, axis=0)
        valido &= conf_ini & conf_fim

    inicio, fim = pilha[:n_ponta], pilha[-n_ponta:]
    virou = (np.all(inicio != CONSTRUIDA, axis=0)
             & np.all(fim == CONSTRUIDA, axis=0) & valido)
    return int(virou.sum()), int(valido.sum())


def fase_medir() -> None:
    pares = P26.pares_unificados()
    nome_zona, r_int, r_ext = ZONA
    print(f"{len(pares)} pares, zona {nome_zona}")

    registros = []
    for _, r in pares.iterrows():
        anos = C.janela_anos(int(r.ano_inicio_obra))
        dados = {}
        falta = False
        for tipo, pid, lat, lon in (("tratamento", r.site_id, r.lat, r.lon),
                                    ("controle", r.site_id_controle, r.lat_controle, r.lon_controle)):
            if any(not Path(C.caminho_classificado(r.sensor, pid, a)).exists() for a in anos):
                falta = True
                break
            ref = Path(C.caminho_classificado(r.sensor, pid, anos[0]))
            pilha = P12.empilhar(pid, r.sensor, anos)
            conf = _empilhar_confianca(pid, r.sensor, anos)
            raios = P11.mascaras_por_raio(ref, float(lat), float(lon))
            dados[tipo] = (pilha, conf, raios[r_ext] & ~raios[r_int])
        if falta:
            continue

        for n_ponta in N_PONTAS:
            for conf_min in LIMIARES_CONF:
                linha = {"campus": r.site_id, "n_ponta": n_ponta, "conf_min": conf_min}
                for tipo in ("tratamento", "controle"):
                    pilha, conf, masc = dados[tipo]
                    v, n = _virou_construida(pilha, conf, masc, n_ponta, conf_min)
                    linha[f"pct_{tipo}"] = 100.0 * v / n if n else np.nan
                    linha[f"px_{tipo}"] = n
                linha["excesso_pp"] = linha["pct_tratamento"] - linha["pct_controle"]
                registros.append(linha)
        print(f"  {r.site_id} ok")

    df = pd.DataFrame(registros)
    C.salvar_csv(df, SAIDA)

    # --- superfície: teste de sinal em cada célula ---------------------------------
    linhas = []
    for (n_ponta, conf_min), g in df.groupby(["n_ponta", "conf_min"]):
        d = g.excesso_pp.dropna().to_numpy()
        if len(d) == 0:
            continue
        n, k = len(d), int((d > 0).sum())
        p = sum(math.comb(n, i) * 0.5 ** n for i in range(k, n + 1))
        linhas.append({
            "n_ponta": n_ponta, "conf_min": conf_min, "n_pares": n, "n_positivo": k,
            "p_unilateral": round(p, 5), "excesso_mediano_pp": round(float(np.median(d)), 4),
            "px_medianos": int(g.px_tratamento.median()),
        })
    sup = pd.DataFrame(linhas)
    C.salvar_csv(sup, SAIDA_SUP)

    print(f"\n--- superfície de robustez, anel {nome_zona}, assinatura virou_construida ---")
    print(f"{'anos de ponta':<15}{'conf. mín':>10}{'pares':>8}{'positivos':>11}"
          f"{'p':>10}{'mediana':>10}")
    for _, x in sup.iterrows():
        marca = "  <-- publicado" if (x.n_ponta == 2 and x.conf_min == 0) else ""
        print(f"{int(x.n_ponta):<15}{int(x.conf_min):>10}{int(x.n_pares):>8}"
              f"{int(x.n_positivo):>11}{x.p_unilateral:>10.4f}"
              f"{x.excesso_mediano_pp:>+10.3f}{marca}")

    forte = sup[(sup.p_unilateral < 0.05) & (sup.excesso_mediano_pp > 0)]
    print(f"\n  {len(forte)} de {len(sup)} células mantêm p<0,05 com efeito positivo.")
    if len(sup):
        estrito = sup[(sup.n_ponta == max(N_PONTAS)) & (sup.conf_min == max(LIMIARES_CONF))]
        if len(estrito):
            e = estrito.iloc[0]
            print(f"  Célula mais estrita (n_ponta={int(e.n_ponta)}, conf>={int(e.conf_min)}): "
                  f"{int(e.n_positivo)}/{int(e.n_pares)}, p={e.p_unilateral:.4f}, "
                  f"{e.excesso_mediano_pp:+.3f} pp")
    print(f"\n  -> {SAIDA_SUP.relative_to(C.REPO_ROOT)}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("medir",), required=True)
    ap.parse_args()
    fase_medir()


if __name__ == "__main__":
    main()

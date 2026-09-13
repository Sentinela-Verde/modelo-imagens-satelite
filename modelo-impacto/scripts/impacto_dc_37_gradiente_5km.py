"""Passo 37 — o gradiente de distância até 5 km, na MESMA métrica do achado.

Rode com:

    python modelo-impacto/scripts/impacto_dc_37_gradiente_5km.py --fase medir

## A pergunta

"O data center impactou a cidade, ou só o terreno ao lado?" O relatório afirma que o
efeito é local e some, mas o gradiente publicado vai só até **2 km** (passo 26, três
zonas). Este passo o estende até **5 km**, que é o limite físico do dado: a AOI ingerida
tem buffer de 5 km (`BUFFER_KM`, ADR-001) e não existe pixel além disso.

## Por que não reusar o passo 11, que já vai a 5 km

Porque ele mede **outra coisa**. O passo 11 calcula DiD sobre a **proporção** de cada
classe em **discos**; o achado deste relatório usa a **assinatura de trajetória por
pixel** — não-construída nos N primeiros anos E construída nos N últimos, no **anel**.

As duas medidas respondem perguntas diferentes e não são comparáveis lado a lado. O
gradiente do passo 11 é majoritariamente nulo em todos os raios, inclusive a 500 m, onde
a trajetória dá 12/16 (p=0,038) — não é contradição, é métrica diferente. Misturar as duas
numa mesma figura seria erro de leitura grave.

Este passo usa a assinatura de trajetória, que é a do achado, em cinco anéis concêntricos.

## O que esperar, e por que o resultado importa dos dois jeitos

Se o efeito morrer com a distância, isso **sustenta** a afirmação de que é adensamento
local induzido, e não a região urbanizando por inteiro — porque urbanização de fundo
apareceria em todos os anéis.

Se NÃO morrer — se 3-5 km mostrar o mesmo excesso —, a leitura muda: seria crescimento
regional que o controle pareado não está absorvendo, e o achado de 0,5-1 km perderia a
interpretação de "induzido pelo empreendimento".
"""

from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_12_trajetoria_pixel as P12  # noqa: E402
import impacto_dc_26_analise_expandida as P26  # noqa: E402

SAIDA = C.DIR_SAIDA / "gradiente_5km.csv"
SAIDA_RESUMO = C.DIR_SAIDA / "gradiente_5km_resumo.csv"

# Os tres primeiros sao os do passo 26 (para conferencia cruzada); os dois ultimos sao
# novos e vao ate o limite do buffer ingerido.
ZONAS = [
    ("0-0.5km", 0.0, 0.5),
    ("0.5-1km", 0.5, 1.0),
    ("1-2km", 1.0, 2.0),
    ("2-3km", 2.0, 3.0),
    ("3-5km", 3.0, 5.0),
]


def fase_medir() -> None:
    pares = P26.pares_unificados()
    print(f"{len(pares)} pares, {len(ZONAS)} anéis até 5 km")

    registros = []
    for _, r in pares.iterrows():
        anos = C.janela_anos(int(r.ano_inicio_obra))
        if any(not Path(C.caminho_classificado(r.sensor, pid, a)).exists()
               for pid in (r.site_id, r.site_id_controle) for a in anos):
            continue

        for tipo, pid, lat, lon in (("tratamento", r.site_id, r.lat, r.lon),
                                    ("controle", r.site_id_controle, r.lat_controle, r.lon_controle)):
            ref = Path(C.caminho_classificado(r.sensor, pid, anos[0]))
            pilha = P12.empilhar(pid, r.sensor, anos)
            raios = P11.mascaras_por_raio(ref, float(lat), float(lon))

            for nome, r_int, r_ext in ZONAS:
                if r_ext not in raios or (r_int and r_int not in raios):
                    continue
                base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
                cont = P12.contar_assinaturas(pilha, base)
                n = cont["pixels_validos_mascara"]
                registros.append({
                    "campus": r.site_id, "site_id": pid, "tipo": tipo, "zona": nome,
                    "r_int": r_int, "r_ext": r_ext,
                    "pixels_validos": n,
                    "pct_virou_construida": (100.0 * cont["virou_construida"] / n
                                             if n else np.nan),
                })
        print(f"  {r.site_id} ok")

    df = pd.DataFrame(registros)
    C.salvar_csv(df, SAIDA)

    linhas = []
    for nome, r_int, r_ext in ZONAS:
        g = df[df.zona == nome]
        difs = []
        for _, par in g.groupby("campus"):
            t = par[par.tipo == "tratamento"].pct_virou_construida
            c = par[par.tipo == "controle"].pct_virou_construida
            if t.empty or c.empty or t.isna().all() or c.isna().all():
                continue
            difs.append(float(t.iloc[0] - c.iloc[0]))
        if not difs:
            continue
        d = np.asarray(difs)
        n, k = len(d), int((d > 0).sum())
        p = sum(math.comb(n, i) * 0.5 ** n for i in range(k, n + 1))
        area = math.pi * (r_ext ** 2 - r_int ** 2) * 100  # ha
        linhas.append({
            "zona": nome, "area_ha": round(area), "n_pares": n, "n_positivo": k,
            "p_unilateral": round(p, 5), "excesso_mediano_pp": round(float(np.median(d)), 4),
        })
    res = pd.DataFrame(linhas)
    C.salvar_csv(res, SAIDA_RESUMO)

    print("\n--- gradiente de distância, assinatura virou_construida ---")
    print(f"{'anel':<12}{'área ha':>9}{'positivos':>12}{'p':>10}{'mediana':>10}")
    for _, x in res.iterrows():
        print(f"{x.zona:<12}{int(x.area_ha):>9}{int(x.n_positivo):>5}/{int(x.n_pares):<6}"
              f"{x.p_unilateral:>10.4f}{x.excesso_mediano_pp:>+10.3f}")

    forte = res[res.p_unilateral < 0.05]
    print(f"\n  {len(forte)} de {len(res)} anéis com p<0,05: "
          f"{', '.join(forte.zona) if len(forte) else 'nenhum'}")
    if len(res) >= 2:
        print(f"\n  Leitura: se o efeito morre com a distância, é adensamento LOCAL induzido.")
        print(f"  Se persistisse a 3-5 km, seria crescimento regional que o controle não")
        print(f"  absorve — e o achado de 0,5-1 km perderia a interpretação de 'induzido'.")
    print(f"\n  -> {SAIDA_RESUMO.relative_to(C.REPO_ROOT)}")



def fase_placebo() -> None:
    """O mesmo gradiente, em pares controle-contra-controle.

    O placebo do passo 19 roda em DISCOS de 0,5 / 1 / 2 km. Esta fase o repete nos anéis
    deste passo, porque o excesso persistente a 3-5 km so tem leitura depois de saber se o
    metodo produz excesso nessa escala onde nada foi construido.

    Resultado (2026-09-12): nao produz. A 3-5 km o placebo da 9/15, p=0,30, +0,056 p.p.
    contra +0,381 dos pares reais. O halo remanescente nao e artefato de escala.
    """
    pares = pd.read_csv(C.DIR_SAIDA / "placebo_pares.csv")
    # as coordenadas do placebo_a vivem no pareamento original (ele e o controle do campus)
    par_orig = pd.read_csv(C.DIR_SAIDA / "pareamento_controle_rf.csv").set_index("site_id_controle")

    print(f"{len(pares)} pares de placebo")

    regs = []
    for r in pares.itertuples():
        anos = C.janela_anos(int(r.ano_obra_ficticio))
        if r.placebo_a not in par_orig.index:
            print(f"  ! {r.placebo_a}: sem coordenada no pareamento original")
            continue
        lat_a = float(par_orig.loc[r.placebo_a, "lat_controle"])
        lon_a = float(par_orig.loc[r.placebo_a, "lon_controle"])

        alvos = (("A", r.placebo_a, lat_a, lon_a), ("B", r.placebo_b, float(r.lat_b), float(r.lon_b)))
        if any(not Path(C.caminho_classificado(r.sensor, p, y)).exists()
               for _, p, _, _ in alvos for y in anos):
            print(f"  ! {r.campus_de_origem}: rasters incompletos")
            continue

        for papel, pid, lat, lon in alvos:
            ref = Path(C.caminho_classificado(r.sensor, pid, anos[0]))
            pilha = P12.empilhar(pid, r.sensor, anos)
            raios = P11.mascaras_por_raio(ref, lat, lon)
            for nome, r_int, r_ext in ZONAS:
                if r_ext not in raios or (r_int and r_int not in raios):
                    continue
                base = raios[r_ext] if r_int == 0 else (raios[r_ext] & ~raios[r_int])
                cont = P12.contar_assinaturas(pilha, base)
                n = cont["pixels_validos_mascara"]
                regs.append({"par": r.campus_de_origem, "papel": papel, "zona": nome,
                             "pct": 100.0 * cont["virou_construida"] / n if n else np.nan})
        print(f"  {r.campus_de_origem} ok")

    df = pd.DataFrame(regs)
    saida = C.DIR_SAIDA / "placebo_gradiente_5km.csv"
    C.salvar_csv(df, saida)

    print("\n--- PLACEBO (controle vs controle) nos mesmos aneis ---")
    print(f"{'anel':<12}{'positivos':>12}{'p':>10}{'mediana':>10}")
    linhas = []
    for nome, _, _ in ZONAS:
        g = df[df.zona == nome]
        difs = []
        for _, p in g.groupby("par"):
            a = p[p.papel == "A"].pct
            b = p[p.papel == "B"].pct
            if a.empty or b.empty or a.isna().all() or b.isna().all():
                continue
            difs.append(float(a.iloc[0] - b.iloc[0]))
        if not difs:
            continue
        d = np.asarray(difs)
        n, k = len(d), int((d > 0).sum())
        pv = sum(math.comb(n, i) * 0.5 ** n for i in range(k, n + 1))
        linhas.append({"zona": nome, "n": n, "k": k, "p": round(pv, 4),
                       "mediana": round(float(np.median(d)), 4)})
        print(f"{nome:<12}{k:>5}/{n:<6}{pv:>10.4f}{np.median(d):>+10.3f}")

    C.salvar_csv(pd.DataFrame(linhas), C.DIR_SAIDA / "placebo_gradiente_5km_resumo.csv")
    print(f"\n  -> {saida.name} e placebo_gradiente_5km_resumo.csv")

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", choices=("medir", "placebo"), required=True)
    args = ap.parse_args()
    {"medir": fase_medir, "placebo": fase_placebo}[args.fase]()


if __name__ == "__main__":
    main()

"""Passo 40 — classificador de conversão POR PIXEL: ONDE, dentro do sítio, a conversão acontece?

Rode com:

    python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase dataset
    python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase treinar
    python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase avaliar
    python dados-modelo-impacto/scripts/impacto_dc_40_modelo_conversao.py --fase ablacao

## A pergunta, e por que ela é diferente da que já falhou

A camada 2 do modelo de impacto (`modelo-impacto-score/scripts/02_explicacao.py`) pergunta
*"quanto este SÍTIO vai converter?"* e não se sustentou: 13 modelos, todos com R² LOOCV negativo
(`modelo-impacto-score/outputs/explicacao_modelos.csv`), permutação p=0,77. O N de lá é 13 campi.

Aqui a pergunta é outra: *"ONDE, DENTRO do sítio, vai converter?"* — probabilidade por pixel. A
aposta é que a variação **dentro** de um sítio (perto de via, perto do que já é construído, borda
de mancha urbana) seja aprendível mesmo que a variação **entre** sítios não seja. São coisas
independentes: nada impede que a distribuição espacial seja previsível e o total, não.

## As três regras que definem se o número vale alguma coisa

1. **Toda feature sai do PRÉ-PERÍODO** (os 2 primeiros anos da janela). Uma única feature que
   toque um ano do pós-período faz o modelo enxergar a resposta, e aí o resultado inteiro é lixo.
   `FEATURES` é montada só a partir de `pilha[0]` e `pilha[1]` e a fase `dataset` é a única que
   toca raster — depois dela não há como um ano do fim vazar para dentro de uma coluna.
2. **Validação leave-one-site-out.** Split aleatório por pixel é proibido: pixels vizinhos são
   quase idênticos, então o vizinho do pixel de teste cai no treino e o PR-AUC vira ficção. O N
   efetivo aqui é **20 sítios**, não 6,8 milhões de pixels. O controle de um campus sai junto com
   o tratamento dele — nunca separados entre treino e teste.
3. **Nada de accuracy.** A classe positiva é 2,7% dos pixels elegíveis; chutar "não converte" para
   todo mundo dá 97,3%. A métrica é **PR-AUC** (average precision), e ela só significa alguma
   coisa contra os dois baselines de §"Os dois baselines".

## O conjunto de risco: só pixels que PODEM converter

O rótulo de §3 do handoff exige "não era construída nos 2 primeiros anos". Um pixel que já era
construída no pré-período é, por definição do rótulo, negativo garantido. Manter esses pixels na
avaliação não é neutro: ele **destrói** o baseline de distância, porque um pixel já construído tem
`dist_construida_m = 0` — o baseline é obrigado a colocá-lo no topo do ranking, onde ele é sempre
um erro. O modelo, que vê `pre_classe`, aprenderia a peneirar esses pixels em uma feature e
"ganharia" do baseline por uma tautologia da definição do alvo, não por saber onde a obra vem.

Por isso o dataset guarda apenas o **conjunto de risco** — pixels não construídos nos 2 primeiros
anos, dentro do disco de 5 km, válidos em todos os anos e fora do footprint do próprio prédio. A
prevalência resultante é **2,675%**, que é exatamente a faixa de "~2-3% (~1:40)" e o baseline de
prevalência de "PR-AUC ~ 0,025" que o handoff previu — os dois batem no conjunto de risco, não no
disco inteiro (onde a prevalência cairia para 1,7%). O rótulo em si é idêntico ao de
`P12.contar_assinaturas`, sem uma vírgula de diferença; o que muda é só quem entra no denominador.

## Os dois baselines

Um modelo que não bate os dois não adiciona nada e é reportado como **reprovado**:

1. **Prevalência** — prever a taxa base para todo mundo. PR-AUC = a própria prevalência.
2. **Distância ao construído mais próximo, sozinha** — uma feature, sem modelo, score `-dist`. Se
   o classificador completo não bate isso, ele só redescobriu "converte perto do que já é
   construído", que o passo 12 já sabia.

**Critério de aceite:** PR-AUC agregado supera o baseline de distância em **>=20% relativo** E o
ganho é positivo em **>=14 dos 20** sítios retidos. Ganho médio puxado por 3 sítios não é modelo.

## Duas decisões de desenho que o handoff deixou em aberto

- **Vizinhança em METROS, não em pixels.** 15 pares são Landsat (30 m) e 5 são Sentinel-2 (10 m).
  Uma janela "3x3" significaria 90 m num sensor e 30 m no outro, e a mesma coluna carregaria duas
  escalas físicas diferentes. As frações de vizinhança são calculadas em 90 m, 150 m e 330 m
  (= 3x3, 5x5 e 11x11 em Landsat) e convertidas para a janela de pixels de cada sensor.
- **Treino subamostrado, avaliação completa.** Um ponto Sentinel-2 tem ~1 milhão de pixels contra
  ~111 mil de um Landsat; treinar no bruto deixaria 5 pares decidirem o modelo. O treino usa todos
  os positivos e um teto de negativos **por ponto** (`TETO_NEGATIVOS_POR_PONTO`), o que equaliza a
  contribuição de cada ponto. A **avaliação nunca é subamostrada**: cada campus retido é predito em
  todos os seus pixels, com a prevalência de verdade, que é o que o PR-AUC precisa para significar
  alguma coisa.

## O que este passo deliberadamente NÃO faz

Não tuna hiperparâmetro. Escolher `max_depth` olhando o placar LOSO é vazamento — o LOSO deixaria
de ser fora-da-amostra. Os parâmetros são fixos, declarados em `RF_PARAMS`, e herdados do que o
classificador principal já usa (`sentinela.train.RF_PARAMS_BASE`), com folhas maiores por causa do
volume. Se um dia valer tunar, o loop de busca tem que ficar **dentro** de cada treino de 19.

Saídas:
  - `raw/controles-rf/conversao_dataset.parquet`      — conjunto de risco, features e rótulo
  - `raw/controles-rf/conversao_loso_predicoes.parquet` — score fora-da-amostra de cada pixel
  - `raw/controles-rf/conversao_loso_resultado.csv`   — PR-AUC por sítio retido, modelo e baselines
  - `raw/controles-rf/conversao_importancias.csv`     — importância de feature (impureza e permutação)
  - `raw/controles-rf/conversao_ablacao.csv`          — o LOSO refeito sem as features suspeitas
  - `raw/controles-rf/figuras/fig_20_conversao_loso.png`
  - `models/conversao_v1.joblib`                      — SÓ se passar no critério de aceite
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import rasterio
from scipy.ndimage import distance_transform_edt, uniform_filter
from sklearn.ensemble import RandomForestClassifier
from sklearn.inspection import permutation_importance
from sklearn.metrics import average_precision_score, precision_recall_curve, roc_auc_score

sys.path.insert(0, str(Path(__file__).resolve().parent))
import impacto_dc_comum as C  # noqa: E402
import impacto_dc_11_sensibilidade_buffer as P11  # noqa: E402
import impacto_dc_12_trajetoria_pixel as P12  # noqa: E402
import impacto_dc_26_analise_expandida as P26  # noqa: E402

# --------------------------------------------------------------------------------------------
# Escopo
# --------------------------------------------------------------------------------------------

RAIO_MAX_KM = 5.0
N_PONTA = P12.ANOS_BORDA          # 2 anos em cada ponta, igual ao passo 12
CONSTRUIDA = P12.CONSTRUIDA       # 4
VEGETACAO_DENSA = 1
SOLO_EXPOSTO = P12.SOLO_EXPOSTO   # 3

# Raios de vizinhança em METROS — ver "Duas decisões de desenho" no topo. 90/150/330 m são
# exatamente 3x3, 5x5 e 11x11 na grade Landsat de 30 m.
ESCALAS_VIZINHANCA_M = (90, 150, 330)
CLASSES_VIZINHANCA = {
    VEGETACAO_DENSA: "veg_densa",
    SOLO_EXPOSTO: "solo_exposto",
    CONSTRUIDA: "construida",
}
ESCALA_DELTA_M = 150              # escala em que se mede o adensamento do pré-período
DIST_MAX_M = 20_000.0             # teto de `dist_construida_m` (ponto sem nenhuma construída perto)

SAIDA_DATASET = C.DIR_SAIDA / "conversao_dataset.parquet"
SAIDA_PREDICOES = C.DIR_SAIDA / "conversao_loso_predicoes.parquet"
SAIDA_RESULTADO = C.DIR_SAIDA / "conversao_loso_resultado.csv"
SAIDA_IMPORTANCIAS = C.DIR_SAIDA / "conversao_importancias.csv"
SAIDA_ABLACAO = C.DIR_SAIDA / "conversao_ablacao.csv"
SAIDA_FIGURA = C.DIR_FIGURAS / "fig_20_conversao_loso.png"
SAIDA_MODELO = C.REPO_ROOT / "models" / "conversao_v1.joblib"

# --------------------------------------------------------------------------------------------
# Features
# --------------------------------------------------------------------------------------------

# `pre_classe` é nominal (1-5) e vira one-hot em `matriz_features`; as demais entram como estão.
FEATURE_CATEGORICA = "pre_classe"
FEATURES_NUMERICAS: list[str] = [
    *[f"frac_{nome}_{m}m" for m in ESCALAS_VIZINHANCA_M for nome in CLASSES_VIZINHANCA.values()],
    f"delta_frac_construida_{ESCALA_DELTA_M}m",
    "dist_construida_m",
    "dist_centro_m",
    "confianca_media_pre",
    "estavel_pre",
    "sensor_landsat",
]
FEATURES = [FEATURE_CATEGORICA, *FEATURES_NUMERICAS]

# Colunas de METADADO — existem no parquet para permitir o split, a reconstrução do mapa de
# probabilidade e a análise separada de tratamento e controle, e NUNCA podem virar feature. Mesma
# regra de `sentinela.train.COLUNAS_PROIBIDAS_COMO_FEATURE` e da nota de revisão de SV-12:
# aprender geografia (qual sítio, qual linha/coluna) em vez de padrão espacial quebra na primeira
# AOI nova. `bioma`/`uf`/`municipio` nem são materializados aqui, pelo mesmo motivo — identificam
# o sítio.
COLUNAS_PROIBIDAS_COMO_FEATURE = {
    "campus", "site_id", "tipo", "procedencia", "sensor", "linha", "coluna", "y",
    "footprint_excluido", "ano", "x", "municipio", "uf", "regiao", "bioma", "tier",
}
METADADOS = ["campus", "site_id", "tipo", "procedencia", "sensor", "footprint_excluido",
             "linha", "coluna"]

# --------------------------------------------------------------------------------------------
# Modelo e protocolo
# --------------------------------------------------------------------------------------------

# Herdado de `sentinela.train.RF_PARAMS_BASE`, com `min_samples_leaf` maior: lá o dataset tem
# dezenas de milhares de linhas, aqui o pool de treino tem ~1 milhão, e folha de 5 produziria
# árvores gigantes sem ganho. NÃO é tunado — ver "O que este passo deliberadamente NÃO faz".
RF_PARAMS: dict[str, Any] = {
    "n_estimators": 200,
    "min_samples_leaf": 50,
    "max_features": "sqrt",
    "class_weight": "balanced",
    "n_jobs": -1,
    "random_state": C.SEED,
}

TETO_NEGATIVOS_POR_PONTO = 20_000
# Permutação fora-da-amostra: medida no campus RETIDO de cada fold, que é a única forma honesta —
# permutar no treino mede o quanto o modelo decorou. Subamostrada e com poucas repetições porque
# são 20 folds x 19 colunas; o que interessa é a ordem das features, não o dígito.
PERM_N_AMOSTRA = 30_000
PERM_N_REPETICOES = 2

GANHO_RELATIVO_MINIMO = 0.20      # PR-AUC do modelo >= 1,20 x PR-AUC do baseline de distância
SITIOS_COM_GANHO_MINIMO = 14      # de 20

# Ablações: refazem o LOSO inteiro sem uma feature, para separar "o modelo aprendeu onde a obra
# vem" de duas explicações alternativas que o placar sozinho não distingue.
ABLACOES: dict[str, list[str]] = {
    # `confianca_media_pre` é a 2a feature mais importante, e isso merece desconfiança: o rótulo
    # `y` sai do MESMO classificador que produz a confiança. Um pixel onde o classificador é
    # inseguro no pré-período tende a continuar inseguro depois, e uma troca espúria para classe 4
    # que dure 2 anos vira positivo. Parte do ganho poderia ser "prever a instabilidade do
    # classificador" em vez de "prever conversão". Sem ela, o quanto sobra?
    "sem_confianca": ["confianca_media_pre"],
    # `dist_centro_m` mede distância ao data center no tratamento e a um ponto arbitrário no
    # controle. Se o modelo depender dela, ele está reaprendendo o achado do passo 26 ("converte
    # perto do campus") em vez de ler o terreno — e não serviria para um sítio sem centro definido.
    "sem_dist_centro": ["dist_centro_m"],
}


# --------------------------------------------------------------------------------------------
# Fase 1 — dataset
# --------------------------------------------------------------------------------------------


def _janela_em_pixels(escala_m: int, resolucao_m: float) -> int:
    """Janela quadrada ÍMPAR que cobre `escala_m` na grade daquele sensor (90 m -> 3 px em
    Landsat, 9 px em Sentinel-2). Ímpar para a janela ficar centrada no próprio pixel."""
    k = round(escala_m / resolucao_m)
    return max(1, k if k % 2 == 1 else k + 1)


def _fracao_vizinhanca(alvo: np.ndarray, valido: np.ndarray, janela: int) -> np.ndarray:
    """Fração de pixels VÁLIDOS da vizinhança que satisfazem `alvo`.

    Normalizar pelo número de vizinhos válidos, e não pela janela inteira, importa na borda do
    raster e em buracos de nuvem: contar um pixel sem dado como "não é construída" inventaria
    vizinhança vazia onde só houve dado faltante — a mesma razão de `contar_assinaturas` exigir
    classe válida em todos os anos.
    """
    num = uniform_filter(np.where(valido, alvo, False).astype(np.float32), size=janela,
                         mode="nearest")
    den = uniform_filter(valido.astype(np.float32), size=janela, mode="nearest")
    return np.divide(num, den, out=np.zeros_like(num), where=den > 1e-6)


def _confianca_media_pre(sensor: str, site_id: str, anos: list[int]) -> np.ndarray:
    """Média da confiança do classificador (0-100) nos anos do pré-período."""
    camadas = []
    for ano in anos[:N_PONTA]:
        caminho = C.caminho_classificado(sensor, site_id, ano).with_name(f"{ano}_confianca.tif")
        with rasterio.open(caminho) as src:
            camadas.append(src.read(1).astype(np.float32))
    return np.mean(camadas, axis=0)


def montar_ponto(campus: str, procedencia: str, sensor: str, tipo: str, site_id: str,
                 lat: float, lon: float, anos: list[int]) -> pd.DataFrame:
    """Conjunto de risco de UM ponto (tratamento ou controle), com features do pré-período.

    Tudo que entra em coluna de feature vem de `pilha[0]` e `pilha[1]`. O resto da pilha só é
    usado para montar o rótulo e a máscara de validade — nunca para uma feature.
    """
    resolucao = 30.0 if sensor == "landsat" else 10.0
    pilha = P12.empilhar(site_id, sensor, anos)
    ref = C.caminho_classificado(sensor, site_id, anos[0])

    inicio, fim = pilha[:N_PONTA], pilha[-N_PONTA:]
    valido = np.all(pilha > 0, axis=0)

    # ---- rótulo: idêntico a `P12.contar_assinaturas`, assinatura `virou_construida`
    nao_construida_inicio = np.all(inicio != CONSTRUIDA, axis=0)
    y = nao_construida_inicio & np.all(fim == CONSTRUIDA, axis=0) & valido

    # ---- conjunto de risco
    dist_km = P11.grade_distancia_km(ref, lat, lon)
    risco = nao_construida_inicio & valido & (dist_km <= RAIO_MAX_KM)

    # O prédio converte por construção, não por impacto no entorno — mesma exclusão do passo 26.
    # `footprint_excluido` registra se a máscara de fato removeu pixels: dois campi têm polígono
    # OSM fora do disco, e ali tratar como "prédio excluído" seria falso.
    footprint_excluido = False
    if tipo == "tratamento":
        m_fp = P26.mascara_footprint_do_campus(campus, ref)
        if m_fp is not None and bool((m_fp & risco).any()):
            risco &= ~m_fp
            footprint_excluido = True

    # ---- features, todas do pré-período
    valido_ano0 = pilha[0] > 0
    colunas: dict[str, np.ndarray] = {FEATURE_CATEGORICA: pilha[0]}
    for escala in ESCALAS_VIZINHANCA_M:
        janela = _janela_em_pixels(escala, resolucao)
        for cid, nome in CLASSES_VIZINHANCA.items():
            colunas[f"frac_{nome}_{escala}m"] = _fracao_vizinhanca(
                pilha[0] == cid, valido_ano0, janela
            )

    janela_delta = _janela_em_pixels(ESCALA_DELTA_M, resolucao)
    frac_constr_ano1 = _fracao_vizinhanca(pilha[1] == CONSTRUIDA, pilha[1] > 0, janela_delta)
    colunas[f"delta_frac_construida_{ESCALA_DELTA_M}m"] = (
        frac_constr_ano1 - colunas[f"frac_construida_{ESCALA_DELTA_M}m"]
    )

    # distância euclidiana ao construído mais próximo do ano inicial, em metros. `sampling` faz a
    # conta sair em metros direto, sem depender de o pixel ser quadrado por acaso.
    colunas["dist_construida_m"] = np.minimum(
        distance_transform_edt(pilha[0] != CONSTRUIDA, sampling=resolucao), DIST_MAX_M
    )
    colunas["dist_centro_m"] = dist_km * 1000.0
    colunas["confianca_media_pre"] = _confianca_media_pre(sensor, site_id, anos)
    colunas["estavel_pre"] = (pilha[0] == pilha[1])
    colunas["sensor_landsat"] = np.full(pilha[0].shape, sensor == "landsat")

    linhas_idx, colunas_idx = np.nonzero(risco)
    dados: dict[str, np.ndarray] = {
        "campus": np.full(linhas_idx.size, campus),
        "site_id": np.full(linhas_idx.size, site_id),
        "tipo": np.full(linhas_idx.size, tipo),
        "procedencia": np.full(linhas_idx.size, procedencia),
        "sensor": np.full(linhas_idx.size, sensor),
        "footprint_excluido": np.full(linhas_idx.size, footprint_excluido),
        "linha": linhas_idx.astype(np.uint16),
        "coluna": colunas_idx.astype(np.uint16),
        "y": y[risco],
        FEATURE_CATEGORICA: pilha[0][risco].astype(np.uint8),
    }
    for nome in FEATURES_NUMERICAS:
        dados[nome] = colunas[nome][risco].astype(np.float32)
    return pd.DataFrame(dados)


def fase_dataset() -> None:
    pares = P26.pares_unificados()
    print(f"Passo 40 — dataset de conversão por pixel, {len(pares)} pares, sem rede")
    _conferir_features_permitidas()

    escritor: pq.ParquetWriter | None = None
    resumo: list[dict[str, Any]] = []
    try:
        for _, r in pares.iterrows():
            anos = C.janela_anos(int(r.ano_inicio_obra))
            if len(anos) < 2 * N_PONTA + 1:
                print(f"  ! {r.site_id}: janela de {len(anos)} anos, precisa de "
                      f"{2 * N_PONTA + 1} — par fora")
                continue
            faltam = [
                (pid, a)
                for pid in (r.site_id, r.site_id_controle)
                for a in anos
                if not C.caminho_classificado(r.sensor, pid, a).exists()
            ]
            if faltam:
                print(f"  ! {r.site_id}: {len(faltam)} rasters ausentes — par fora")
                continue

            for tipo, pid, lat, lon in (
                ("tratamento", r.site_id, r.lat, r.lon),
                ("controle", r.site_id_controle, r.lat_controle, r.lon_controle),
            ):
                t0 = time.time()
                df = montar_ponto(r.site_id, r.procedencia, r.sensor, tipo, pid,
                                  float(lat), float(lon), anos)
                tabela = pa.Table.from_pandas(df, preserve_index=False)
                if escritor is None:
                    escritor = pq.ParquetWriter(SAIDA_DATASET, tabela.schema,
                                                compression="zstd")
                # um row group por ponto: a fase `treinar` lê um campus de cada vez e o
                # filtro por estatística de row group consegue pular os outros 38.
                escritor.write_table(tabela)
                n, k = len(df), int(df["y"].sum())
                resumo.append({"site_id": pid, "tipo": tipo, "n": n, "pos": k})
                print(f"  {pid:45s} {tipo:10s} risco={n:8d} pos={k:6d} "
                      f"prev={100 * k / max(n, 1):6.3f}%  ({time.time() - t0:4.1f}s)")
    finally:
        if escritor is not None:
            escritor.close()

    res = pd.DataFrame(resumo)
    n, k = int(res["n"].sum()), int(res["pos"].sum())
    print(f"\n  -> {SAIDA_DATASET.relative_to(C.REPO_ROOT)} "
          f"({SAIDA_DATASET.stat().st_size / 1e6:.0f} MB)")
    print(f"  {len(res)} pontos · {n:,} pixels no conjunto de risco · {k:,} positivos "
          f"({100 * k / n:.3f}% — 1:{n / k:.0f})")
    print("  Prevalência é a PR-AUC do baseline 1. Accuracy aqui seria "
          f"{100 * (1 - k / n):.1f}% chutando tudo negativo — por isso ela não é reportada.")


# --------------------------------------------------------------------------------------------
# Fase 2 — LOSO
# --------------------------------------------------------------------------------------------


def _conferir_features_permitidas() -> None:
    """Falha alto se alguma feature colidir com a lista de colunas proibidas."""
    proibidas = sorted(set(FEATURES) & COLUNAS_PROIBIDAS_COMO_FEATURE)
    if proibidas:
        raise RuntimeError(
            f"features proibidas na lista de treino: {proibidas} — ver §4 do handoff e "
            "`sentinela.train.COLUNAS_PROIBIDAS_COMO_FEATURE`."
        )


def matriz_features(df: pd.DataFrame,
                    numericas: list[str] | None = None) -> tuple[np.ndarray, list[str]]:
    """Matriz float32 pronta para o RF, com `pre_classe` expandida em one-hot.

    A expansão acontece aqui, e não no parquet, porque o parquet guarda 6,8 milhões de linhas e
    cinco colunas booleanas a mais custariam disco sem informação nova. O treino trabalha em
    ~1 milhão de linhas e a avaliação em um campus de cada vez, então expandir na hora é barato.

    `numericas` existe para a fase `ablacao` poder remover uma coluna sem tocar no parquet.
    """
    numericas = list(FEATURES_NUMERICAS if numericas is None else numericas)
    nomes = list(numericas)
    blocos = [df[numericas].to_numpy(dtype=np.float32)]
    classe = df[FEATURE_CATEGORICA].to_numpy()
    for cid in C.CLASS_IDS:
        blocos.append((classe == cid).astype(np.float32).reshape(-1, 1))
        nomes.append(f"{FEATURE_CATEGORICA}_{C.CLASSE_NOME[cid]}")
    return np.hstack(blocos), nomes


def _ler_campus(campus: str, colunas: list[str] | None = None) -> pd.DataFrame:
    return pq.read_table(
        SAIDA_DATASET, columns=colunas, filters=[("campus", "==", campus)]
    ).to_pandas()


def _subamostrar(df: pd.DataFrame) -> pd.DataFrame:
    """Todos os positivos + teto de negativos POR PONTO, com sorteio determinístico por site.

    O teto por ponto (e não global) é o que equaliza a contribuição: sem ele, os 10 pontos
    Sentinel-2 entrariam com ~1 milhão de pixels cada contra ~111 mil dos Landsat e decidiriam
    o modelo sozinhos. `C.rng_do_site` dá um gerador independente por site, então reprocessar um
    subconjunto de campi produz exatamente as mesmas linhas — mesma convenção do passo 3.
    """
    partes = []
    for site_id, g in df.groupby("site_id", sort=True):
        pos = g[g["y"]]
        neg = g[~g["y"]]
        if len(neg) > TETO_NEGATIVOS_POR_PONTO:
            rng = C.rng_do_site(site_id)
            idx = rng.choice(len(neg), size=TETO_NEGATIVOS_POR_PONTO, replace=False)
            neg = neg.iloc[np.sort(idx)]
        partes.append(pd.concat([pos, neg]))
    return pd.concat(partes, ignore_index=True)


def _campi_do_dataset() -> list[str]:
    if not SAIDA_DATASET.exists():
        raise FileNotFoundError(f"dataset ausente: {SAIDA_DATASET} — rode --fase dataset antes")
    return sorted(
        set(pq.read_table(SAIDA_DATASET, columns=["campus"]).column("campus").to_pylist())
    )


def _pool_de_treino(campi: list[str], *, verboso: bool = True) -> dict[str, pd.DataFrame]:
    """Um DataFrame subamostrado por campus, pronto para virar treino de qualquer fold."""
    colunas = ["campus", "site_id", "y", *FEATURES]
    pool: dict[str, pd.DataFrame] = {}
    for campus in campi:
        pool[campus] = _subamostrar(_ler_campus(campus, colunas))
        if verboso:
            print(f"    {campus:38s} {len(pool[campus]):8,} linhas "
                  f"({int(pool[campus]['y'].sum()):6,} positivos)")
    return pool


def _rodar_loso(campi: list[str], pool: dict[str, pd.DataFrame], numericas: list[str],
                *, com_importancias: bool,
                rotulo: str = "") -> tuple[pd.DataFrame, pd.DataFrame | None]:
    """O loop leave-one-site-out: treina nos 19, prevê no retido, repete 20 vezes.

    Devolve as predições fora-da-amostra de TODOS os pixels dos 20 campi (nunca subamostradas) e,
    opcionalmente, a importância de feature por fold.
    """
    predicoes: list[pd.DataFrame] = []
    importancias: list[pd.DataFrame] = []
    for i, campus in enumerate(campi, 1):
        t0 = time.time()
        treino = pd.concat([d for c, d in pool.items() if c != campus], ignore_index=True)
        X_tr, nomes_x = matriz_features(treino, numericas)
        modelo = RandomForestClassifier(**RF_PARAMS).fit(X_tr, treino["y"].to_numpy())
        t_fit = time.time() - t0

        teste = _ler_campus(campus, ["campus", "site_id", "tipo", "y", *FEATURES])
        X_te, _ = matriz_features(teste, numericas)
        y_te = teste["y"].to_numpy()
        score = modelo.predict_proba(X_te)[:, 1].astype(np.float32)
        dist = teste["dist_construida_m"].to_numpy(np.float32)
        predicoes.append(pd.DataFrame({
            "campus": teste["campus"].to_numpy(),
            "site_id": teste["site_id"].to_numpy(),
            "tipo": teste["tipo"].to_numpy(),
            "y": y_te,
            "score_modelo": score,
            "dist_construida_m": dist,
        }))

        if com_importancias:
            importancias.append(pd.DataFrame({
                "campus_retido": campus,
                "feature": nomes_x,
                "importancia_impureza": modelo.feature_importances_,
                "importancia_permutacao_ap": _permutacao_fora_da_amostra(modelo, X_te, y_te),
            }))
        ap_m = average_precision_score(y_te, score)
        ap_d = average_precision_score(y_te, -dist)
        print(f"  {rotulo}[{i:2d}/{len(campi)}] {campus:38s} n={len(teste):8,} "
              f"prev={100 * y_te.mean():5.2f}%  PR-AUC modelo={ap_m:.4f} dist={ap_d:.4f} "
              f"({t_fit:4.0f}s fit, {time.time() - t0:4.0f}s total)")

    imp = pd.concat(importancias, ignore_index=True) if com_importancias else None
    return pd.concat(predicoes, ignore_index=True), imp


def fase_treinar() -> None:
    _conferir_features_permitidas()
    campi = _campi_do_dataset()
    print(f"Passo 40 — leave-one-site-out, {len(campi)} campi retidos, um por vez")
    print(f"  RF fixo (sem tuning): {RF_PARAMS}")

    print("\n  montando o pool de treino (todos os positivos + "
          f"{TETO_NEGATIVOS_POR_PONTO:,} negativos por ponto)")
    pool = _pool_de_treino(campi)
    print(f"  pool: {sum(len(d) for d in pool.values()):,} linhas")

    pred, imp = _rodar_loso(campi, pool, FEATURES_NUMERICAS, com_importancias=True)
    pred.to_parquet(SAIDA_PREDICOES, index=False, compression="zstd")
    print(f"\n  -> {SAIDA_PREDICOES.relative_to(C.REPO_ROOT)} ({len(pred):,} predições "
          "fora-da-amostra)")

    agregada = (
        imp.groupby("feature")
        .agg(importancia_impureza_media=("importancia_impureza", "mean"),
             importancia_impureza_dp=("importancia_impureza", "std"),
             permutacao_ap_media=("importancia_permutacao_ap", "mean"),
             permutacao_ap_dp=("importancia_permutacao_ap", "std"),
             n_folds_com_ganho=("importancia_permutacao_ap", lambda s: int((s > 0).sum())))
        .reset_index()
        .sort_values("permutacao_ap_media", ascending=False)
    )
    C.salvar_csv(agregada.round(6), SAIDA_IMPORTANCIAS)
    print("\n  top features por permutação fora-da-amostra (queda de PR-AUC ao embaralhar):")
    for _, r in agregada.head(8).iterrows():
        print(f"    {r.feature:34s} {r.permutacao_ap_media:+.4f} "
              f"(±{r.permutacao_ap_dp:.4f}, positiva em {int(r.n_folds_com_ganho)}/{len(campi)})")


def _permutacao_fora_da_amostra(modelo: RandomForestClassifier, X: np.ndarray,
                                y: np.ndarray) -> np.ndarray:
    """Queda de PR-AUC ao embaralhar cada coluna, medida no campus RETIDO.

    Subamostra estratificada: todos os positivos (são poucos e carregam a métrica) mais negativos
    até `PERM_N_AMOSTRA`. Permutar em milhões de linhas x 19 colunas x 20 folds não caberia no
    tempo, e a ORDEM das features — que é o que se lê daqui — estabiliza muito antes disso.
    """
    if y.sum() == 0:
        return np.full(X.shape[1], np.nan)
    pos = np.flatnonzero(y)
    neg = np.flatnonzero(~y)
    rng = np.random.default_rng(C.SEED)
    if len(neg) > PERM_N_AMOSTRA:
        neg = rng.choice(neg, size=PERM_N_AMOSTRA, replace=False)
    idx = np.concatenate([pos, neg])
    r = permutation_importance(
        modelo, X[idx], y[idx], scoring="average_precision",
        n_repeats=PERM_N_REPETICOES, random_state=C.SEED, n_jobs=1,
    )
    return r.importances_mean


# --------------------------------------------------------------------------------------------
# Fase 3 — avaliação e veredito
# --------------------------------------------------------------------------------------------


def _metricas(y: np.ndarray, score_modelo: np.ndarray, dist: np.ndarray) -> dict[str, float]:
    """PR-AUC do modelo e dos dois baselines sobre o MESMO conjunto de pixels.

    O baseline de prevalência é a taxa base: com todos os scores empatados, a curva PR tem um
    ponto só (recall 1, precisão = prevalência) e a average precision é exatamente ela. Fica
    escrito assim, e não via `average_precision_score` com um vetor constante, para o número não
    depender de como a implementação resolve empate.
    """
    prev = float(y.mean())
    return {
        "n_pixels": int(y.size),
        "n_positivos": int(y.sum()),
        "prevalencia": prev,
        "pr_auc_modelo": float(average_precision_score(y, score_modelo)),
        "pr_auc_dist": float(average_precision_score(y, -dist)),
        "pr_auc_prevalencia": prev,
        "roc_auc_modelo": float(roc_auc_score(y, score_modelo)),
    }


def fase_avaliar() -> None:
    if not SAIDA_PREDICOES.exists():
        raise FileNotFoundError(f"predições ausentes: {SAIDA_PREDICOES} — rode --fase treinar")
    pred = pd.read_parquet(SAIDA_PREDICOES)
    campi = sorted(pred["campus"].unique())
    print(f"Passo 40 — avaliação LOSO, {len(campi)} campi, "
          f"{len(pred):,} predições fora-da-amostra")

    linhas = []
    for campus in campi:
        g = pred[pred["campus"] == campus]
        m = _metricas(g["y"].to_numpy(), g["score_modelo"].to_numpy(),
                      g["dist_construida_m"].to_numpy())
        m["campus"] = campus
        m["ganho_relativo_vs_dist"] = m["pr_auc_modelo"] / m["pr_auc_dist"] - 1.0
        m["ganho_relativo_vs_prevalencia"] = m["pr_auc_modelo"] / m["prevalencia"] - 1.0
        linhas.append(m)

    agregado = _metricas(pred["y"].to_numpy(), pred["score_modelo"].to_numpy(),
                         pred["dist_construida_m"].to_numpy())
    agregado["campus"] = "AGREGADO"
    agregado["ganho_relativo_vs_dist"] = agregado["pr_auc_modelo"] / agregado["pr_auc_dist"] - 1.0
    agregado["ganho_relativo_vs_prevalencia"] = (
        agregado["pr_auc_modelo"] / agregado["prevalencia"] - 1.0
    )

    colunas = ["campus", "n_pixels", "n_positivos", "prevalencia", "pr_auc_modelo",
               "pr_auc_dist", "pr_auc_prevalencia", "ganho_relativo_vs_dist",
               "ganho_relativo_vs_prevalencia", "roc_auc_modelo"]
    por_sitio = pd.DataFrame(linhas)[colunas]
    resultado = pd.concat([por_sitio, pd.DataFrame([agregado])[colunas]], ignore_index=True)
    C.salvar_csv(resultado.round(6), SAIDA_RESULTADO)

    # -------------------------------------------------------------------------- o veredito
    ganho = float(agregado["ganho_relativo_vs_dist"])
    n_positivos = int((por_sitio["ganho_relativo_vs_dist"] > 0).sum())
    passou_ganho = ganho >= GANHO_RELATIVO_MINIMO
    passou_consistencia = n_positivos >= SITIOS_COM_GANHO_MINIMO
    aprovado = passou_ganho and passou_consistencia

    print(f"\n{'campus':38s} {'n':>9s} {'prev':>7s} {'modelo':>8s} {'dist':>8s} {'ganho':>8s}")
    for _, r in por_sitio.sort_values("ganho_relativo_vs_dist", ascending=False).iterrows():
        print(f"{r.campus:38s} {int(r.n_pixels):9,} {100 * r.prevalencia:6.2f}% "
              f"{r.pr_auc_modelo:8.4f} {r.pr_auc_dist:8.4f} {100 * r.ganho_relativo_vs_dist:+7.1f}%")
    print(f"{'AGREGADO':38s} {int(agregado['n_pixels']):9,} "
          f"{100 * agregado['prevalencia']:6.2f}% {agregado['pr_auc_modelo']:8.4f} "
          f"{agregado['pr_auc_dist']:8.4f} {100 * ganho:+7.1f}%")

    print("\n=== CRITÉRIO DE ACEITE ===")
    print(f"  ganho agregado sobre o baseline de distância: {100 * ganho:+.1f}% "
          f"(exigido >= +{100 * GANHO_RELATIVO_MINIMO:.0f}%) -> "
          f"{'PASSA' if passou_ganho else 'REPROVA'}")
    print(f"  sítios com ganho positivo: {n_positivos}/{len(campi)} "
          f"(exigido >= {SITIOS_COM_GANHO_MINIMO}) -> "
          f"{'PASSA' if passou_consistencia else 'REPROVA'}")
    print(f"  baseline de prevalência (PR-AUC {agregado['prevalencia']:.4f}): "
          f"{'batido' if agregado['pr_auc_modelo'] > agregado['prevalencia'] else 'NÃO batido'}")
    print(f"\n  VEREDITO: modelo {'APROVADO' if aprovado else 'REPROVADO'}")
    if not aprovado:
        print("  Reprovado é resultado, não falha. O modelo NÃO é salvo em models/ e não deve ser")
        print("  apresentado como modelo — ver §8 do handoff.")

    desenhar(por_sitio, agregado, pred, aprovado)

    if aprovado:
        _salvar_modelo_final(campi)
    elif SAIDA_MODELO.exists():
        print(f"  ! {SAIDA_MODELO.relative_to(C.REPO_ROOT)} existe de uma rodada anterior e o "
              "critério agora reprova — apague antes de publicar qualquer coisa.")


def _salvar_modelo_final(campi: list[str]) -> None:
    """Refit nos 20 campi. Só roda se o critério passou — é o único caminho para `models/`."""
    import joblib

    colunas = ["campus", "site_id", "y", *FEATURES]
    treino = pd.concat([_subamostrar(_ler_campus(c, colunas)) for c in campi], ignore_index=True)
    X, nomes = matriz_features(treino)
    modelo = RandomForestClassifier(**RF_PARAMS).fit(X, treino["y"].to_numpy())
    SAIDA_MODELO.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"modelo": modelo, "features": nomes, "features_parquet": FEATURES,
         "rf_params": RF_PARAMS, "seed": C.SEED, "campi_treino": campi,
         "protocolo": "leave-one-site-out, conjunto de risco (não construída no pré-período)"},
        SAIDA_MODELO,
    )
    print(f"  -> {SAIDA_MODELO.relative_to(C.REPO_ROOT)} (refit nos {len(campi)} campi)")


def desenhar(por_sitio: pd.DataFrame, agregado: dict[str, Any], pred: pd.DataFrame,
             aprovado: bool) -> None:
    ordem = por_sitio.sort_values("pr_auc_modelo")
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 7.6))

    ax = axes[0]
    yy = np.arange(len(ordem))
    ax.barh(yy + 0.22, ordem["pr_auc_modelo"], height=0.42, color="#1A5276", label="modelo (RF)")
    ax.barh(yy - 0.22, ordem["pr_auc_dist"], height=0.42, color="#E67E22",
            label="baseline: distância ao construído")
    ax.plot(ordem["prevalencia"], yy, "k.", markersize=6, label="baseline: prevalência")
    ax.set_yticks(yy)
    ax.set_yticklabels(ordem["campus"], fontsize=7.5)
    ax.set_xlabel("PR-AUC fora-da-amostra (average precision)")
    ax.set_title("PR-AUC por sítio retido\ncada linha é um campus que o modelo nunca viu",
                 fontsize=11)
    ax.legend(fontsize=8, loc="lower right")
    ax.grid(axis="x", alpha=0.25)

    ax2 = axes[1]
    g = por_sitio.sort_values("ganho_relativo_vs_dist")
    cores = ["#C0392B" if v <= 0 else "#27AE60" for v in g["ganho_relativo_vs_dist"]]
    ax2.barh(np.arange(len(g)), 100 * g["ganho_relativo_vs_dist"], color=cores)
    ax2.axvline(0, color="#333", lw=1)
    ax2.axvline(100 * GANHO_RELATIVO_MINIMO, color="#1A5276", ls="--", lw=1.4,
                label=f"critério: +{100 * GANHO_RELATIVO_MINIMO:.0f}% no agregado")
    ax2.set_yticks(np.arange(len(g)))
    ax2.set_yticklabels(g["campus"], fontsize=7.5)
    ax2.set_xlabel("ganho relativo do modelo sobre o baseline de distância (%)")
    n_pos = int((por_sitio["ganho_relativo_vs_dist"] > 0).sum())
    ax2.set_title(f"Ganho sobre o baseline, sítio a sítio\npositivo em {n_pos}/{len(por_sitio)} "
                  f"(exigido {SITIOS_COM_GANHO_MINIMO}/{len(por_sitio)})", fontsize=11)
    ax2.legend(fontsize=8, loc="lower right")
    ax2.grid(axis="x", alpha=0.25)

    ax3 = axes[2]
    y = pred["y"].to_numpy()
    for nome, score, cor in (("modelo (RF)", pred["score_modelo"].to_numpy(), "#1A5276"),
                             ("distância ao construído",
                              -pred["dist_construida_m"].to_numpy(), "#E67E22")):
        p, r, _ = precision_recall_curve(y, score)
        ax3.plot(r, p, color=cor, lw=2.0, label=nome)
    ax3.axhline(agregado["prevalencia"], color="#5D6D7E", ls="--", lw=1.4,
                label=f"prevalência ({agregado['prevalencia']:.3f})")
    ax3.set_xlabel("recall\n"
                   "curva interpolada entre limiares; o baseline de\n"
                   "distância tem muitos empates e aparece otimista\n"
                   "em recall baixo — a PR-AUC do veredito não interpola",
                   fontsize=7.5)
    ax3.set_ylabel("precisão")
    ax3.set_ylim(0, min(1.0, max(0.2, 3 * agregado["pr_auc_modelo"])))
    ax3.set_title("Curva PR agregada (20 sítios retidos)\n"
                  f"PR-AUC modelo {agregado['pr_auc_modelo']:.4f} · "
                  f"distância {agregado['pr_auc_dist']:.4f}", fontsize=11)
    ax3.legend(fontsize=8)
    ax3.grid(alpha=0.25)
    # O baseline de distância só assume os valores discretos que a transformada de distância
    # produz numa grade (30 m, 42,4 m, 60 m, ...), então cada limiar carrega um bloco enorme de
    # empates. `precision_recall_curve` liga dois limiares consecutivos por uma RETA, e essa reta
    # não é atingível — dentro de um bloco empatado não há como escolher os positivos primeiro.
    # A average precision, que é o número do veredito, soma por degrau e não interpola. Ou seja: o
    # trecho de recall baixo da curva laranja é otimista para o baseline, não para o modelo.

    veredito = "APROVADO" if aprovado else "REPROVADO"
    fig.suptitle(
        f"Passo 40 — modelo de conversão por pixel, leave-one-site-out · veredito: {veredito} "
        f"({100 * (agregado['pr_auc_modelo'] / agregado['pr_auc_dist'] - 1):+.1f}% sobre o "
        "baseline de distância)",
        fontsize=12, y=0.99,
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    C.DIR_FIGURAS.mkdir(parents=True, exist_ok=True)
    fig.savefig(SAIDA_FIGURA, dpi=140)
    plt.close(fig)
    print(f"  -> {SAIDA_FIGURA.relative_to(C.REPO_ROOT)}")


def fase_ablacao() -> None:
    """Refaz o LOSO inteiro sem cada feature de `ABLACOES` e compara com o modelo completo.

    Não é busca de variante nem tuning — as ablações são declaradas ANTES de olhar o placar, e o
    modelo adotado continua sendo o completo. O que se mede aqui é se o resultado sobrevive a
    remover a feature que teria a explicação alternativa mais incômoda.
    """
    _conferir_features_permitidas()
    if not SAIDA_PREDICOES.exists():
        raise FileNotFoundError(f"predições ausentes: {SAIDA_PREDICOES} — rode --fase treinar")

    campi = _campi_do_dataset()
    print(f"Passo 40 — ablações, {len(ABLACOES)} variantes x {len(campi)} folds")
    pool = _pool_de_treino(campi, verboso=False)

    completo = pd.read_parquet(SAIDA_PREDICOES)
    variantes = {"completo": (completo, list(FEATURES_NUMERICAS))}
    for nome, removidas in ABLACOES.items():
        faltando = [f for f in removidas if f not in FEATURES_NUMERICAS]
        if faltando:
            raise RuntimeError(f"ablação '{nome}' remove feature inexistente: {faltando}")
        numericas = [f for f in FEATURES_NUMERICAS if f not in removidas]
        print(f"\n  === {nome} (sem {', '.join(removidas)}) ===")
        pred, _ = _rodar_loso(campi, pool, numericas, com_importancias=False,
                              rotulo=f"{nome} ")
        variantes[nome] = (pred, numericas)

    linhas = []
    for nome, (pred, numericas) in variantes.items():
        agregado = _metricas(pred["y"].to_numpy(), pred["score_modelo"].to_numpy(),
                             pred["dist_construida_m"].to_numpy())
        por_sitio = [
            _metricas(g["y"].to_numpy(), g["score_modelo"].to_numpy(),
                      g["dist_construida_m"].to_numpy())
            for _, g in pred.groupby("campus")
        ]
        n_pos = sum(1 for m in por_sitio if m["pr_auc_modelo"] > m["pr_auc_dist"])
        ganho = agregado["pr_auc_modelo"] / agregado["pr_auc_dist"] - 1.0
        linhas.append({
            "variante": nome,
            "features_removidas": ",".join(ABLACOES.get(nome, [])) or "-",
            "n_features": len(numericas) + len(C.CLASS_IDS),
            "pr_auc_modelo": agregado["pr_auc_modelo"],
            "pr_auc_dist": agregado["pr_auc_dist"],
            "ganho_relativo_vs_dist": ganho,
            "sitios_com_ganho": n_pos,
            "passa_criterio": bool(ganho >= GANHO_RELATIVO_MINIMO
                                   and n_pos >= SITIOS_COM_GANHO_MINIMO),
        })
    tabela = pd.DataFrame(linhas)
    C.salvar_csv(tabela.round(6), SAIDA_ABLACAO)

    base = float(tabela.loc[tabela.variante == "completo", "pr_auc_modelo"].iloc[0])
    print(f"\n{'variante':18s} {'PR-AUC':>8s} {'vs completo':>12s} {'ganho/dist':>11s} "
          f"{'sítios':>8s}  critério")
    for _, r in tabela.iterrows():
        rel = r.pr_auc_modelo / base - 1.0
        print(f"{r.variante:18s} {r.pr_auc_modelo:8.4f} {100 * rel:+11.1f}% "
              f"{100 * r.ganho_relativo_vs_dist:+10.1f}% "
              f"{int(r.sitios_com_ganho):5d}/{len(campi):<2d} "
              f"{'PASSA' if r.passa_criterio else 'REPROVA'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fase", required=True,
                    choices=["dataset", "treinar", "avaliar", "ablacao"])
    args = ap.parse_args()
    {"dataset": fase_dataset, "treinar": fase_treinar, "avaliar": fase_avaliar,
     "ablacao": fase_ablacao}[args.fase]()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

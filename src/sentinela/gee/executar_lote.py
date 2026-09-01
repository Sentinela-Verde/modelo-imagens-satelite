"""Execução em lote do pipeline de dados no conjunto expandido de AOIs (SV-26).

**Isto não é uma nova etapa de ingestão.** SV-06 (Sentinel-2), SV-06b (Landsat), SV-07 (labels) e
SV-08 (features) já existem, já têm CLI própria com `--site all`, e já são idempotentes. Este
módulo só **orquestra** essas CLIs por AOI/ano/etapa, em lote, sobre as ~16 AOIs ativas de
`config/sites.geojson` — sem reimplementar nada de máscara de nuvem, harmonização ou fonte de
label (ver ADR-003/ADR-004, fora de escopo aqui).

Rode com:

    python -m sentinela.gee.executar_lote --etapa <ingestao|labels|features> --tier <1|2|all>

Flags adicionais:
    --site <site_id>   restringe a uma única AOI (ignora --tier) — útil para validar o wrapper em
                        escala pequena antes de disparar o lote completo (item 2 do escopo de
                        SV-26).
    --force             repassa --force para os módulos subjacentes (regera mesmo se já existir).
    --relatorio          gera reports/qualidade_ingestao.csv + .md a partir dos manifests já
                          existentes e sai (não roda nenhuma etapa).
    --inspecionar A:B:C  gera um PNG RGB de inspeção visual (percentil 2-98) para
                          site_id:sensor:ano (sensor = landsat|s2), pode repetir separado por
                          vírgula, e sai.

## Ordem (item 3 do escopo de SV-26, não é escolha deste módulo)

Landsat (SV-06b) -> Sentinel-2 (SV-06) -> labels (SV-07) -> features (SV-08). Landsat primeiro
porque SV-06 exige que a grade de 10 m seja refinamento exato da grade de 30 m — mais barato achar
um problema de origem de grade nos rasters de 1 MB do que nos de 7,8 MB. Dentro da etapa de
ingestão isso vira: Landsat inteiro (todos os tiers selecionados) primeiro, Sentinel-2 inteiro
depois. Dentro de labels/features (que não têm essa dependência de grade entre si) a prioridade é
por tier: tier 1 inteiro (as duas grades, landsat e s2) antes de tier 2 — se o relógio estourar,
o que fica incompleto é tier 2, que não entra em rotulagem manual nem em treino.

## Retomada e backoff

Nunca inventa controle de estado paralelo: cada item (site/sensor/ano) é reprocessado chamando a
função já idempotente do módulo correspondente (`ingerir_site_ano`, `processar_site_ano`,
`gerar_label_site_ano`) — que confere sha256 e pula rápido se já existir. O que este módulo
acrescenta é (a) um manifest de execução agregado (`data/manifests/execucao_lote_{etapa}.json`,
por AOI/ano/sensor, com status/duração/tentativas) e (b) uma segunda camada de backoff exponencial
por cima da que cada módulo já tem internamente: se mesmo assim a chamada falhar (ex.: quota do
Earth Engine esgotada mesmo depois das tentativas internas do módulo), este wrapper tenta de novo
até 3 vezes com espera exponencial e, falhando ainda, **registra a falha e segue para o próximo
item** em vez de abortar o lote inteiro.

## Controle de disco

Antes de iniciar cada etapa (e periodicamente durante ela), confere espaço livre em disco; aborta
com mensagem clara se cair abaixo de `LIMIAR_DISCO_LIVRE_GB` (12 GB, item 4 do escopo de SV-26).
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..config import REPO_ROOT, SETTINGS, ConfigError
from ..features import indices as features_mod
from . import labels as labels_mod
from . import landsat, sentinel2
from .auth import init_ee

LIMIAR_DISCO_LIVRE_GB = 12.0
LIMIAR_DISCO_CHECAGEM_PERIODICA = 15  # confere disco a cada N itens processados, além do início
TENTATIVAS_LOTE = 3
ESPERA_INICIAL_S = 10.0
PCT_VALIDOS_MINIMO = 90.0  # mesmo limiar já usado em SV-06/SV-06b

_PREFIXO_RAW = {"landsat": "landsat", "sentinel2": "s2"}
_SENSORES_LABELS_FEATURES = ("landsat", "s2")  # tokens usados por SV-07/SV-08 (diferente de "sentinel2" da ingestão)


# --------------------------------------------------------------------------------------------
# Disco
# --------------------------------------------------------------------------------------------


def espaco_livre_gb() -> float:
    return shutil.disk_usage(REPO_ROOT).free / (1024**3)


def _checar_disco(etapa: str, *, contexto: str = "") -> float:
    livre_gb = espaco_livre_gb()
    if livre_gb < LIMIAR_DISCO_LIVRE_GB:
        raise SystemExit(
            f"ABORTADO{' (' + contexto + ')' if contexto else ''}: espaço livre em disco "
            f"({livre_gb:.2f} GB) abaixo do limiar mínimo de {LIMIAR_DISCO_LIVRE_GB} GB para a "
            f"etapa '{etapa}'. Nada mais é escrito nesta chamada — libere espaço e rode de novo "
            f"(o lote retoma do que já está pronto)."
        )
    return livre_gb


# --------------------------------------------------------------------------------------------
# Sites / tiers
# --------------------------------------------------------------------------------------------


def _sites_ativos() -> list[dict[str, Any]]:
    import geopandas as gpd

    gdf = gpd.read_file(REPO_ROOT / "config" / "sites.geojson")
    gdf = gdf[gdf["ativo"] == True]
    out = [
        {
            "site_id": r["site_id"],
            "lat": float(r["lat"]),
            "lon": float(r["lon"]),
            "buffer_km": float(r["buffer_km"]),
            "tier": int(r["tier"]),
            "regiao": r.get("regiao"),
            "bioma": r.get("bioma"),
        }
        for _, r in gdf.iterrows()
    ]
    return sorted(out, key=lambda s: s["site_id"])


def _grupos_por_tier(sites: list[dict], tier_arg: str, site_arg: str | None) -> list[list[dict]]:
    """Lista de grupos de sites, na ordem em que devem ser processados.

    `--site` restringe a uma única AOI (1 grupo). Sem `--site`, `--tier all` produz DOIS grupos —
    tier 1 inteiro primeiro, tier 2 depois — nunca um grupo misto, para que a prioridade
    (item 3 do escopo de SV-26) seja respeitada mesmo que o lote seja interrompido no meio.
    """
    if site_arg:
        alvo = [s for s in sites if s["site_id"] == site_arg]
        if not alvo:
            disponiveis = sorted(s["site_id"] for s in sites)
            raise SystemExit(f"site_id '{site_arg}' não encontrado entre as AOIs ativas. Disponíveis: {disponiveis}")
        return [alvo]
    if tier_arg == "1":
        return [[s for s in sites if s["tier"] == 1]]
    if tier_arg == "2":
        return [[s for s in sites if s["tier"] == 2]]
    if tier_arg == "all":
        return [[s for s in sites if s["tier"] == 1], [s for s in sites if s["tier"] == 2]]
    raise SystemExit(f"--tier inválido: {tier_arg!r}")


# --------------------------------------------------------------------------------------------
# Manifest de execução do lote (data/manifests/execucao_lote_{etapa}.json)
# --------------------------------------------------------------------------------------------


def _manifest_lote_path(etapa: str) -> Path:
    return SETTINGS.manifests_dir / f"execucao_lote_{etapa}.json"


def _carregar_manifest_lote(etapa: str) -> dict[str, Any]:
    path = _manifest_lote_path(etapa)
    if path.exists():
        try:
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest.setdefault("itens", {})
            return manifest
        except (json.JSONDecodeError, OSError):
            pass
    return {"etapa": etapa, "iniciado_em": datetime.now(UTC).isoformat(), "itens": {}}


def _salvar_manifest_lote(etapa: str, manifest: dict[str, Any]) -> None:
    manifest["atualizado_em"] = datetime.now(UTC).isoformat()
    path = _manifest_lote_path(etapa)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------------------------
# Retry com backoff exponencial (item 2 do escopo — camada acima do retry interno de cada módulo)
# --------------------------------------------------------------------------------------------


def _com_retry_lote(fn, *, descricao: str, tentativas: int = TENTATIVAS_LOTE, espera_inicial: float = ESPERA_INICIAL_S):
    """Retorna (resultado, n_tentativas, mensagem_erro). Nunca levanta — quem chama decide seguir."""
    ultimo_erro: str | None = None
    for tentativa in range(1, tentativas + 1):
        try:
            resultado = fn()
            return resultado, tentativa, None
        except Exception as e:  # noqa: BLE001 - lote não pode abortar por um item; captura tudo
            ultimo_erro = f"{type(e).__name__}: {e}"
            if tentativa == tentativas:
                print(f"ERRO [lote] {descricao}: falhou após {tentativa} tentativas: {ultimo_erro}", file=sys.stderr)
                return None, tentativa, ultimo_erro
            msg = str(e).lower()
            eh_quota = any(t in msg for t in ("quota", "rate limit", "429", "too many requests"))
            espera = espera_inicial * (2 ** (tentativa - 1)) if eh_quota else espera_inicial
            print(
                f"AVISO [lote] {descricao}: tentativa {tentativa}/{tentativas} falhou "
                f"({'quota/rate-limit' if eh_quota else 'erro'}: {e}); esperando {espera:.0f}s...",
                file=sys.stderr,
            )
            time.sleep(espera)
    return None, tentativas, ultimo_erro  # pragma: no cover - inatingível


# --------------------------------------------------------------------------------------------
# Contador / progresso
# --------------------------------------------------------------------------------------------


class _Contador:
    def __init__(self, etapa: str, total_estimado: int) -> None:
        self.etapa = etapa
        self.total_estimado = total_estimado
        self.visto = 0
        self.ok = 0
        self.pulado = 0
        self.falha = 0
        self.inicio = time.time()

    def registrar(self, status: str) -> None:
        self.visto += 1
        if status == "ok":
            self.ok += 1
        elif status == "pulado":
            self.pulado += 1
        else:
            self.falha += 1

    def resumo(self) -> str:
        decorrido = time.time() - self.inicio
        return (
            f"[lote/{self.etapa}] progresso {self.visto}/{self.total_estimado} "
            f"(ok={self.ok} pulado={self.pulado} falha={self.falha}) — {decorrido / 60:.1f} min decorridos"
        )


# --------------------------------------------------------------------------------------------
# Etapa: ingestão (Landsat inteiro, depois Sentinel-2 inteiro)
# --------------------------------------------------------------------------------------------


def _ja_existe_raster_ingestao(sensor_token: str, site_id: str, ano: int) -> bool:
    prefixo = _PREFIXO_RAW[sensor_token]
    tif = SETTINGS.raw_dir / prefixo / site_id / f"{ano}.tif"
    manifest_path = SETTINGS.manifests_dir / f"{prefixo}_{site_id}_{ano}.json"
    return tif.exists() and manifest_path.exists()


def _executar_item_ingestao(
    site: dict, ano: int, sensor_token: str, mes_ini: int, mes_fim: int, *, force: bool,
    manifest: dict, contador: _Contador,
) -> None:
    site_id = site["site_id"]
    chave = f"{site_id}|{sensor_token}|{ano}"
    ja_existia = _ja_existe_raster_ingestao(sensor_token, site_id, ano) and not force

    if contador.visto and contador.visto % LIMIAR_DISCO_CHECAGEM_PERIODICA == 0:
        _checar_disco(contador.etapa, contexto=f"checagem periódica em {chave}")

    inicio = time.time()

    def _chamar():
        if sensor_token == "landsat":
            return landsat.ingerir_site_ano(site, ano, mes_ini, mes_fim, force=force, gerar_png=False)
        return sentinel2.processar_site_ano(site, ano, force=force)

    resultado, tentativas, erro = _com_retry_lote(_chamar, descricao=chave)
    duracao = time.time() - inicio

    status = "falha" if erro else ("pulado" if ja_existia else "ok")
    manifest["itens"][chave] = {
        "site_id": site_id,
        "tier": site["tier"],
        "regiao": site.get("regiao"),
        "bioma": site.get("bioma"),
        "sensor": sensor_token,
        "ano": ano,
        "status": status,
        "tentativas": tentativas,
        "duracao_s": round(duracao, 2),
        "mensagem_erro": erro,
        "pct_pixels_validos": (resultado or {}).get("pct_pixels_validos"),
        "n_imagens_usadas": (resultado or {}).get("n_imagens_usadas"),
        "atualizado_em": datetime.now(UTC).isoformat(),
    }
    _salvar_manifest_lote(contador.etapa, manifest)
    contador.registrar(status)
    print(f"{contador.resumo()} | último: {chave} -> {status} (tentativas={tentativas}, {duracao:.1f}s)"
          + (f" ERRO={erro}" if erro else ""))


def _rodar_ingestao(grupos_tier: list[list[dict]], *, force: bool, manifest: dict, contador: _Contador) -> None:
    try:
        init_ee()
    except ConfigError as e:
        raise SystemExit(f"ERRO DE CONFIGURAÇÃO (Earth Engine):\n{e}") from e

    params = SETTINGS.params()
    mes_ini, mes_fim = params["mes_inicio"], params["mes_fim"]
    anos_landsat = landsat._anos_alvo()
    anos_s2 = sentinel2._anos_sentinel2()

    # Landsat inteiro (todos os grupos/tiers selecionados) ANTES de Sentinel-2 inteiro — "ordem
    # obrigatória" do item 3 do escopo de SV-26 (grade de 10m tem que refinar a de 30m).
    for grupo in grupos_tier:
        for site in grupo:
            for ano in anos_landsat:
                _executar_item_ingestao(site, ano, "landsat", mes_ini, mes_fim, force=force, manifest=manifest, contador=contador)
    for grupo in grupos_tier:
        for site in grupo:
            for ano in anos_s2:
                _executar_item_ingestao(site, ano, "sentinel2", mes_ini, mes_fim, force=force, manifest=manifest, contador=contador)


# --------------------------------------------------------------------------------------------
# Etapa: labels (SV-07) — tier inteiro (as duas grades) antes do próximo tier
# --------------------------------------------------------------------------------------------


def _ja_existe_label(sensor_token: str, site_id: str, ano: int) -> bool:
    tif = SETTINGS.raw_dir / "labels" / sensor_token / site_id / f"{ano}.tif"
    manifest_path = SETTINGS.manifests_dir / f"labels_{sensor_token}_{site_id}_{ano}.json"
    return tif.exists() and manifest_path.exists()


def _executar_item_labels(site: dict, sensor_token: str, ano: int, *, force: bool, manifest: dict, contador: _Contador) -> None:
    site_id = site["site_id"]
    chave = f"{site_id}|labels_{sensor_token}|{ano}"
    ja_existia = _ja_existe_label(sensor_token, site_id, ano) and not force

    if contador.visto and contador.visto % LIMIAR_DISCO_CHECAGEM_PERIODICA == 0:
        _checar_disco(contador.etapa, contexto=f"checagem periódica em {chave}")

    inicio = time.time()
    resultado, tentativas, erro = _com_retry_lote(
        lambda: labels_mod.gerar_label_site_ano(site, sensor_token, ano, force=force, gerar_png=False),
        descricao=chave,
    )
    duracao = time.time() - inicio

    if erro:
        status = "falha"
    elif resultado is None:
        # gerar_label_site_ano devolve None (sem levantar exceção) quando o manifest de imagem
        # (SV-06/SV-06b) correspondente ainda não existe — não é um bug deste lote, é pré-requisito
        # faltando (ingestão daquele site/ano/sensor falhou ou ainda não rodou).
        status = "pulado_sem_imagem"
    elif ja_existia:
        status = "pulado"
    else:
        status = "ok"

    manifest["itens"][chave] = {
        "site_id": site_id,
        "tier": site["tier"],
        "regiao": site.get("regiao"),
        "bioma": site.get("bioma"),
        "sensor": sensor_token,
        "ano": ano,
        "status": status,
        "tentativas": tentativas,
        "duracao_s": round(duracao, 2),
        "mensagem_erro": erro,
        "distribuicao_classes": (resultado or {}).get("distribuicao_classes"),
        "atualizado_em": datetime.now(UTC).isoformat(),
    }
    _salvar_manifest_lote(contador.etapa, manifest)
    contador.registrar("falha" if status == "falha" else ("pulado" if status.startswith("pulado") else "ok"))
    print(f"{contador.resumo()} | último: {chave} -> {status} (tentativas={tentativas}, {duracao:.1f}s)"
          + (f" ERRO={erro}" if erro else ""))


def _rodar_labels(grupos_tier: list[list[dict]], *, force: bool, manifest: dict, contador: _Contador) -> None:
    try:
        init_ee()
    except ConfigError as e:
        raise SystemExit(f"ERRO DE CONFIGURAÇÃO (Earth Engine):\n{e}") from e

    for grupo in grupos_tier:
        for site in grupo:
            for sensor_token in _SENSORES_LABELS_FEATURES:
                anos = labels_mod._anos_disponiveis(sensor_token, site["site_id"])
                for ano in anos:
                    _executar_item_labels(site, sensor_token, ano, force=force, manifest=manifest, contador=contador)


# --------------------------------------------------------------------------------------------
# Etapa: features (SV-08) — 100% local, sem Earth Engine
# --------------------------------------------------------------------------------------------


def _ja_existe_features(sensor_token: str, site_id: str, ano: int) -> bool:
    tif = SETTINGS.interim_dir / "features" / sensor_token / site_id / f"{ano}.tif"
    manifest_path = SETTINGS.manifests_dir / f"features_{sensor_token}_{site_id}_{ano}.json"
    return tif.exists() and manifest_path.exists()


def _executar_item_features(site: dict, sensor_token: str, ano: int, *, force: bool, manifest: dict, contador: _Contador) -> None:
    site_id = site["site_id"]
    chave = f"{site_id}|features_{sensor_token}|{ano}"
    ja_existia = _ja_existe_features(sensor_token, site_id, ano) and not force

    if contador.visto and contador.visto % LIMIAR_DISCO_CHECAGEM_PERIODICA == 0:
        _checar_disco(contador.etapa, contexto=f"checagem periódica em {chave}")

    inicio = time.time()
    resultado, tentativas, erro = _com_retry_lote(
        lambda: features_mod.processar_site_ano(sensor_token, site_id, ano, force=force),
        descricao=chave,
    )
    duracao = time.time() - inicio

    status = "falha" if erro else ("pulado" if ja_existia else "ok")
    manifest["itens"][chave] = {
        "site_id": site_id,
        "tier": site["tier"],
        "regiao": site.get("regiao"),
        "bioma": site.get("bioma"),
        "sensor": sensor_token,
        "ano": ano,
        "status": status,
        "tentativas": tentativas,
        "duracao_s": round(duracao, 2),
        "mensagem_erro": erro,
        "pct_pixels_validos": (resultado or {}).get("pct_pixels_validos"),
        "atualizado_em": datetime.now(UTC).isoformat(),
    }
    _salvar_manifest_lote(contador.etapa, manifest)
    contador.registrar(status)
    print(f"{contador.resumo()} | último: {chave} -> {status} (tentativas={tentativas}, {duracao:.1f}s)"
          + (f" ERRO={erro}" if erro else ""))


def _rodar_features(grupos_tier: list[list[dict]], *, force: bool, manifest: dict, contador: _Contador) -> None:
    for grupo in grupos_tier:
        for site in grupo:
            for sensor_token in ("s2", "landsat"):
                anos = features_mod._anos_disponiveis(sensor_token, site["site_id"])
                for ano in anos:
                    _executar_item_features(site, sensor_token, ano, force=force, manifest=manifest, contador=contador)


# --------------------------------------------------------------------------------------------
# Estimativa de total (só para a barra de progresso — não precisa ser exata)
# --------------------------------------------------------------------------------------------


def _estimar_total(etapa: str, grupos_tier: list[list[dict]]) -> int:
    sites = [s for grupo in grupos_tier for s in grupo]
    if etapa == "ingestao":
        n_landsat = len(landsat._anos_alvo())
        n_s2 = len(sentinel2._anos_sentinel2())
        return len(sites) * (n_landsat + n_s2)
    if etapa == "labels":
        total = 0
        for site in sites:
            for sensor_token in _SENSORES_LABELS_FEATURES:
                total += len(labels_mod._anos_disponiveis(sensor_token, site["site_id"]))
        return total
    if etapa == "features":
        total = 0
        for site in sites:
            for sensor_token in ("s2", "landsat"):
                total += len(features_mod._anos_disponiveis(sensor_token, site["site_id"]))
        return total
    return 0


# --------------------------------------------------------------------------------------------
# Inspeção visual (item 6 do escopo) — PNG RGB percentil 2-98 a partir de um raw .tif já ingerido.
# --------------------------------------------------------------------------------------------


def gerar_png_inspecao(sensor_token: str, site_id: str, ano: int) -> Path:
    import matplotlib
    import numpy as np
    import rasterio

    from .harmonizacao import bandas_harmonizadas

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    prefixo = _PREFIXO_RAW.get(sensor_token, sensor_token)  # aceita "landsat"/"s2"/"sentinel2"
    tif_path = SETTINGS.raw_dir / prefixo / site_id / f"{ano}.tif"
    manifest_path = SETTINGS.manifests_dir / f"{prefixo}_{site_id}_{ano}.json"
    if not tif_path.exists():
        raise FileNotFoundError(f"{tif_path} não existe — rode a ingestão antes de inspecionar.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    nodata = manifest.get("nodata", -9999)
    fator_escala = manifest.get("fator_escala", 10000)

    with rasterio.open(tif_path) as ds:
        arr = ds.read()
        descricoes = list(ds.descriptions)

    bandas = descricoes if all(descricoes) else bandas_harmonizadas()
    idx = {b: i for i, b in enumerate(bandas)}
    rgb = np.stack([arr[idx["red"]], arr[idx["green"]], arr[idx["blue"]]], axis=-1).astype(np.float64)
    valido = arr[idx["red"]] != nodata
    rgb_refl = rgb / fator_escala
    for c in range(3):
        canal = rgb_refl[..., c]
        amostra = canal[valido]
        if amostra.size == 0:
            continue
        lo, hi = np.percentile(amostra, [2, 98])
        hi = max(hi, lo + 1e-6)
        rgb_refl[..., c] = np.clip((canal - lo) / (hi - lo), 0, 1)
    rgb_refl[~valido] = 1.0

    pct_validos = 100.0 * float(valido.sum()) / valido.size if valido.size else 0.0

    out_dir = REPO_ROOT / "reports" / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"inspecao_visual_{prefixo}_{site_id}_{ano}.png"
    fig, ax = plt.subplots(figsize=(7, 7))
    ax.imshow(rgb_refl)
    ax.set_title(f"Inspeção visual SV-26 — {site_id} ({prefixo}, {ano}) — {pct_validos:.1f}% pixels válidos")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)
    print(f"[inspecao] {site_id}/{prefixo}/{ano}: {out_path} (pct_pixels_validos={pct_validos:.1f}%)")
    return out_path


# --------------------------------------------------------------------------------------------
# Relatório de qualidade agregado (item 5 do escopo) — reports/qualidade_ingestao.csv + .md
# --------------------------------------------------------------------------------------------


def _linhas_qualidade() -> list[dict[str, Any]]:
    """Uma linha por AOI x ano x sensor de ingestão (SV-06/SV-06b), lida diretamente dos manifests
    de imagem — fonte de verdade de pct_pixels_validos/n_imagens_usadas/tamanho, não do manifest
    de execução do lote (que só registra status/duração da chamada)."""
    sites = {s["site_id"]: s for s in _sites_ativos()}
    linhas: list[dict[str, Any]] = []
    for prefixo, sensor_nome in (("landsat", "landsat"), ("s2", "sentinel2")):
        for manifest_path in sorted(SETTINGS.manifests_dir.glob(f"{prefixo}_*.json")):
            stem = manifest_path.stem  # "{prefixo}_{site_id}_{ano}"
            resto = stem[len(prefixo) + 1 :]
            if "_" not in resto:
                continue
            site_id, _, ano_str = resto.rpartition("_")
            if site_id not in sites or not ano_str.isdigit():
                continue
            try:
                m = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            tif_path = SETTINGS.raw_dir / prefixo / site_id / f"{ano_str}.tif"
            tamanho_mb = round(tif_path.stat().st_size / (1024 * 1024), 3) if tif_path.exists() else None
            pct = m.get("pct_pixels_validos")
            linhas.append(
                {
                    "site_id": site_id,
                    "tier": sites[site_id]["tier"],
                    "regiao": sites[site_id].get("regiao"),
                    "bioma": sites[site_id].get("bioma"),
                    "sensor": sensor_nome,
                    "ano": int(ano_str),
                    "n_imagens_usadas": m.get("n_imagens_usadas"),
                    "pct_pixels_validos": pct,
                    "tamanho_mb": tamanho_mb if tamanho_mb is not None else m.get("tamanho_mb"),
                    "status": "ok" if (pct is None or pct >= PCT_VALIDOS_MINIMO) else "abaixo_limiar",
                }
            )
    return sorted(linhas, key=lambda r: (r["tier"], r["site_id"], r["sensor"], r["ano"]))


def _series_incompletas(linhas: list[dict[str, Any]]) -> dict[str, dict[str, list[int]]]:
    """AOI -> sensor -> anos esperados que NÃO têm manifest de imagem (nem sucesso nem falha
    registrada — simplesmente não existe raster). Usa as mesmas listas de anos-alvo dos módulos
    de ingestão, não uma faixa hardcoded aqui."""
    anos_esperados = {"landsat": set(landsat._anos_alvo()), "sentinel2": set(sentinel2._anos_sentinel2())}
    presentes: dict[str, dict[str, set[int]]] = {}
    for linha in linhas:
        presentes.setdefault(linha["site_id"], {}).setdefault(linha["sensor"], set()).add(linha["ano"])

    faltando: dict[str, dict[str, list[int]]] = {}
    for site in _sites_ativos():
        site_id = site["site_id"]
        for sensor, anos in anos_esperados.items():
            tem = presentes.get(site_id, {}).get(sensor, set())
            falta = sorted(anos - tem)
            if falta:
                faltando.setdefault(site_id, {})[sensor] = falta
    return faltando


def gerar_relatorio_qualidade() -> tuple[Path, Path]:
    linhas = _linhas_qualidade()
    out_dir = REPO_ROOT / "reports"
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "qualidade_ingestao.csv"
    campos = ["site_id", "tier", "regiao", "bioma", "sensor", "ano", "n_imagens_usadas", "pct_pixels_validos", "tamanho_mb", "status"]
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for linha in linhas:
            writer.writerow(linha)

    abaixo_limiar = [l for l in linhas if l["status"] == "abaixo_limiar"]
    faltando = _series_incompletas(linhas)

    n_total = len(linhas)
    n_abaixo = len(abaixo_limiar)
    pcts = [l["pct_pixels_validos"] for l in linhas if l["pct_pixels_validos"] is not None]
    pct_medio = sum(pcts) / len(pcts) if pcts else None
    pct_minimo = min(pcts) if pcts else None

    md_lines = [
        "# Relatório de qualidade da ingestão (SV-26)",
        "",
        f"Gerado em {datetime.now(UTC).isoformat()} a partir dos manifests em `data/manifests/`.",
        "",
        f"- Pares AOI x ano x sensor com manifest de imagem: **{n_total}**",
        f"- `pct_pixels_validos` médio: **{pct_medio:.2f}%**" if pct_medio is not None else "- `pct_pixels_validos` médio: sem dados",
        f"- `pct_pixels_validos` mínimo: **{pct_minimo:.2f}%**" if pct_minimo is not None else "- `pct_pixels_validos` mínimo: sem dados",
        f"- Pares abaixo do limiar de {PCT_VALIDOS_MINIMO}%: **{n_abaixo}** ({100 * n_abaixo / n_total:.1f}% do total)" if n_total else f"- Pares abaixo do limiar de {PCT_VALIDOS_MINIMO}%: 0",
        f"- Critério de aceite (>= 95% dos pares acima do limiar): {'OK' if n_total and (1 - n_abaixo / n_total) >= 0.95 else 'NÃO OK' if n_total else 'sem dados'}",
        "",
        "## AOI x ano com pct_pixels_validos < 90%",
        "",
    ]
    if abaixo_limiar:
        md_lines.append("| site_id | tier | sensor | ano | pct_pixels_validos |")
        md_lines.append("|---|---|---|---|---|")
        for l in abaixo_limiar:
            md_lines.append(f"| {l['site_id']} | {l['tier']} | {l['sensor']} | {l['ano']} | {l['pct_pixels_validos']} |")
    else:
        md_lines.append("Nenhum par abaixo do limiar (ou nenhum manifest ainda gerado).")

    md_lines += ["", "## AOIs com série incompleta (anos-alvo sem manifest de imagem)", ""]
    if faltando:
        md_lines.append("| site_id | sensor | anos faltando | decisão |")
        md_lines.append("|---|---|---|---|")
        for site_id, por_sensor in sorted(faltando.items()):
            for sensor, anos in por_sensor.items():
                md_lines.append(
                    f"| {site_id} | {sensor} | {anos} | **PENDENTE — decidir: entra com lacuna documentada ou `ativo: false`** |"
                )
    else:
        md_lines.append("Nenhuma AOI com lacuna detectada (ou lote ainda não rodou o suficiente para saber).")

    md_lines += ["", "## Detalhe por AOI x ano x sensor", ""]
    md_lines.append("| site_id | tier | regiao | bioma | sensor | ano | n_imagens | pct_validos | tamanho_mb | status |")
    md_lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for l in linhas:
        md_lines.append(
            f"| {l['site_id']} | {l['tier']} | {l['regiao']} | {l['bioma']} | {l['sensor']} | {l['ano']} | "
            f"{l['n_imagens_usadas']} | {l['pct_pixels_validos']} | {l['tamanho_mb']} | {l['status']} |"
        )

    md_path = out_dir / "qualidade_ingestao.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(f"Relatório de qualidade: {csv_path} + {md_path} ({n_total} linhas, {n_abaixo} abaixo do limiar)")
    return csv_path, md_path


# --------------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Execução em lote do pipeline expandido (SV-26).")
    parser.add_argument("--etapa", choices=["ingestao", "labels", "features"], default=None)
    parser.add_argument("--tier", choices=["1", "2", "all"], default="all")
    parser.add_argument("--site", default=None, help="restringe a uma única AOI (ignora --tier) — validação em escala pequena")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--relatorio", action="store_true", help="gera reports/qualidade_ingestao.csv/.md e sai")
    parser.add_argument("--inspecionar", default=None, help="site_id:sensor:ano[,site_id:sensor:ano,...] — gera PNG(s) de inspeção e sai")
    args = parser.parse_args(argv)

    if args.relatorio:
        gerar_relatorio_qualidade()
        return 0

    if args.inspecionar:
        for item in args.inspecionar.split(","):
            site_id, sensor_token, ano_str = item.strip().split(":")
            gerar_png_inspecao(sensor_token, site_id, int(ano_str))
        return 0

    if not args.etapa:
        parser.error("--etapa é obrigatório (a menos que --relatorio ou --inspecionar seja usado)")

    livre_gb = _checar_disco(args.etapa, contexto="início da etapa")
    print(f"[lote] disco livre no início da etapa '{args.etapa}': {livre_gb:.2f} GB (limiar mínimo {LIMIAR_DISCO_LIVRE_GB} GB)")

    sites = _sites_ativos()
    grupos_tier = _grupos_por_tier(sites, args.tier, args.site)
    n_sites = sum(len(g) for g in grupos_tier)
    print(f"[lote] etapa={args.etapa} tier={args.tier} site={args.site or 'todos'} -> {n_sites} AOI(s)")

    total_estimado = _estimar_total(args.etapa, grupos_tier)
    contador = _Contador(args.etapa, total_estimado)
    manifest = _carregar_manifest_lote(args.etapa)

    if args.etapa == "ingestao":
        _rodar_ingestao(grupos_tier, force=args.force, manifest=manifest, contador=contador)
    elif args.etapa == "labels":
        _rodar_labels(grupos_tier, force=args.force, manifest=manifest, contador=contador)
    elif args.etapa == "features":
        _rodar_features(grupos_tier, force=args.force, manifest=manifest, contador=contador)

    livre_gb_fim = espaco_livre_gb()
    print()
    print(f"[lote/{args.etapa}] CONCLUÍDO — {contador.resumo()}")
    print(f"[lote/{args.etapa}] disco livre ao final: {livre_gb_fim:.2f} GB")

    return 1 if contador.falha else 0


if __name__ == "__main__":
    sys.exit(main())

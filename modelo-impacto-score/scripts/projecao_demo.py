"""Helper fino para a demo de projeção do notebook `02_impacto_score.ipynb`.

Existe só para que a célula do notebook seja uma linha (`projetar_e_mostrar(15)`) em vez de dez —
toda a lógica de projeção vive em `03_projecao.py`, que é a fonte única. Este módulo não decide
nada; só formata.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_AQUI = Path(__file__).resolve().parent
if str(_AQUI) not in sys.path:
    sys.path.insert(0, str(_AQUI))

import comum as K  # noqa: E402

# `03_projecao.py` começa com dígito, então não é importável por `import 03_projecao` —
# carrega por spec, que é o caminho normal para isso.
_spec = importlib.util.spec_from_file_location("_projecao", _AQUI / "03_projecao.py")
_proj = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_proj)

_MESTRA = None


def _analogos():
    global _MESTRA
    if _MESTRA is None:
        m = K.tabela_mestra()
        _MESTRA = m.dropna(
            subset=[_proj.ALVO, "x_pct_ja_construida", "x_tipo_sitio"]
        ).reset_index(drop=True)
    return _MESTRA


def projetar_e_mostrar(pct_ja_construida: float) -> dict:
    """Imprime a projeção para um site com este % de terreno já construído, e devolve os números.

    Separa de propósito as duas coisas que têm qualidade de evidência diferente:
      - DIREÇÃO   — taxa-base da classe do sítio (é onde o achado direcional de fato está)
      - MAGNITUDE — faixa da amostra completa (é a única com cobertura calibrada; ver
                    outputs/projecao_validacao.csv)
    """
    d = _analogos()
    cls = _proj.classe_de(pct_ja_construida)
    direcao = _proj.projetar(d, pct_ja_construida, usar_classe=True)
    magnitude = _proj.projetar(d, pct_ja_construida, usar_classe=False)

    print(f"site com {pct_ja_construida:.0f}% do terreno já construído  ->  {cls}")
    print(f"  direção   : {direcao['n_positivo']}/{direcao['n']} dos análogos "
          f"{direcao['classe_referencia']} converteram MAIS que seu controle "
          f"({direcao['frac_positivo']:.0%})")
    print(f"  magnitude : faixa 15–85% de {magnitude['p15_pp']:+.2f} a "
          f"{magnitude['p85_pp']:+.2f} p.p.  ·  mediana {magnitude['mediana_pp']:+.2f} p.p.")
    return {"classe": cls, "direcao": direcao, "magnitude": magnitude}

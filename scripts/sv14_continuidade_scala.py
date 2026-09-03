import json

import rasterio

from sentinela.config import SETTINGS
from sentinela.predict import checar_continuidade_eras

tif_2018 = SETTINGS.processed_dir / "classificado" / "landsat" / "scala-tambore" / "2018.tif"
tif_2019 = SETTINGS.processed_dir / "classificado" / "s2" / "scala-tambore" / "2019.tif"
with rasterio.open(tif_2018) as ds:
    arr_2018 = ds.read(1)
    crs_2018, tr_2018 = ds.crs, ds.transform
with rasterio.open(tif_2019) as ds:
    arr_2019 = ds.read(1)
    crs_2019, tr_2019 = ds.crs, ds.transform
r = checar_continuidade_eras(arr_2018, crs_2018, tr_2018, arr_2019, crs_2019, tr_2019)
print(json.dumps(r, indent=2, ensure_ascii=False))

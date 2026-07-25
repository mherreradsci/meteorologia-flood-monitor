"""Fixtures compartidas.

Los tests importan `flood_monitor` / `list_s1_items` por nombre; `src/` entra
en sys.path vía la opción `pythonpath` de pytest.ini.
"""

from __future__ import annotations

import pytest
from shapely.geometry import box, mapping

# AOI fijo para los tests de red: el mismo recuadro de 10x10 km sobre Tongoy
# que produce `--place Tongoy --buffer-km 5`, pero literal, para no depender
# de Nominatim (una red menos, y sin rate limits ajenos al pipeline).
TONGOY_BBOX = (-71.5449, -30.3021, -71.4409, -30.2123)
TONGOY_GEOM = mapping(box(*TONGOY_BBOX))


@pytest.fixture
def fake_stac(monkeypatch):
    """Reemplaza `flood_monitor.stac_catalog()` por un catálogo falso.

    Devuelve `install(items) -> registro`: los items que la búsqueda debe
    devolver, y a cambio un dict donde queda guardado (`registro["kwargs"]`)
    con qué argumentos se llamó a `.search()`. Sirve para afirmar sobre la
    ventana de fechas exacta que se le pide a la API, sin tocar la red.
    """
    import flood_monitor

    def install(items):
        registro: dict = {}

        class FakeSearch:
            def item_collection(self):
                return list(items)

        class FakeCatalog:
            def search(self, **kwargs):
                registro["kwargs"] = kwargs
                return FakeSearch()

        monkeypatch.setattr(flood_monitor, "stac_catalog",
                            lambda: FakeCatalog())
        return registro

    return install

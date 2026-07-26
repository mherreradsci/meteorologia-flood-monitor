"""Fixtures compartidas.

Los tests importan `flood_monitor` / `list_s1_items` por nombre; `src/` entra
en sys.path vía la opción `pythonpath` de pytest.ini.
"""

from __future__ import annotations

import time

import pytest
from shapely.geometry import box, mapping

# AOI fijo para los tests de red: el mismo recuadro de 10x10 km sobre Tongoy
# que produce `--place Tongoy --buffer-km 5`, pero literal, para no depender
# de Nominatim (una red menos, y sin rate limits ajenos al pipeline).
TONGOY_BBOX = (-71.5449, -30.3021, -71.4409, -30.2123)
TONGOY_GEOM = mapping(box(*TONGOY_BBOX))


@pytest.fixture
def en_santiago(monkeypatch):
    """Corre el test con la máquina "puesta" en América/Santiago.

    `--local-time` lee la zona del sistema, así que sin fijarla los tests
    pasarían en Chile y fallarían en el runner de CI (que corre en UTC), o
    al revés. Se eligió una zona con horario de verano a propósito: Chile es
    -04 en invierno y -03 en verano, lo que permite verificar que se aplica
    el offset vigente en la fecha pedida y no el de hoy.
    """
    monkeypatch.setenv("TZ", "America/Santiago")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def fake_stac(monkeypatch):
    """Reemplaza `stac_catalog()` por un catálogo falso.

    Devuelve `install(items, modulo=flood_monitor) -> registro`: los items que
    la búsqueda debe devolver, y a cambio un dict donde queda guardado
    (`registro["kwargs"]`) con qué argumentos se llamó a `.search()`. Sirve
    para afirmar sobre la ventana de fechas exacta que se le pide a la API,
    sin tocar la red.

    El parámetro `modulo` importa: `list_s1_items` hace
    `from flood_monitor import stac_catalog`, o sea que se queda con su propia
    referencia al nombre. Parchear solo `flood_monitor` no lo alcanzaría.
    """
    import flood_monitor

    def install(items, modulo=None):
        registro: dict = {}

        class FakeSearch:
            # `search_latest_s1` usa item_collection(); el hermano usa items().
            def item_collection(self):
                return list(items)

            def items(self):
                return list(items)

        class FakeCatalog:
            def search(self, **kwargs):
                registro["kwargs"] = kwargs
                return FakeSearch()

        monkeypatch.setattr(modulo or flood_monitor, "stac_catalog",
                            lambda: FakeCatalog())
        return registro

    return install

"""Dobles de prueba compartidos por la suite."""

from __future__ import annotations

from datetime import datetime, timezone


def utc(y: int, m: int, d: int, hh: int = 0, mm: int = 0,
        ss: int = 0) -> datetime:
    """Atajo para construir un datetime aware en UTC."""
    return datetime(y, m, d, hh, mm, ss, tzinfo=timezone.utc)


class FakeItem:
    """Sustituto mínimo de pystac.Item: solo los atributos que toca el
    pipeline (`datetime`, `id` y las properties de órbita)."""

    def __init__(self, dt: datetime, item_id: str | None = None,
                 orbit: int = 156, state: str = "descending"):
        self.datetime = dt
        self.id = item_id or f"FAKE_{dt:%Y%m%dT%H%M%S}_rtc"
        self.properties = {"sat:relative_orbit": orbit,
                           "sat:orbit_state": state}

    def __repr__(self) -> str:  # mensajes de fallo legibles
        return f"FakeItem({self.datetime:%Y-%m-%d %H:%M})"

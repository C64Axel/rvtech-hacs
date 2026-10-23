"""Telegramm-Protokoll der Dachhaube (ASCII über BLE-UART, Characteristic FFE1).

Senden:    ``P_d=NNN\\r\\n``  (NNN = Zielposition, 3 Ziffern)
Empfangen: ``P_a=NNN\\r\\n``  (NNN = gemeldete Position, 3 Ziffern)
"""

from __future__ import annotations

import logging
import re

_LOGGER = logging.getLogger(__name__)

CHARACTERISTIC_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"

# Höchster gültiger Wert: 102 ist der Code des Presets "Lüften".
MAX_POSITION = 102

_POSITION_RE = re.compile(rb"P_a=(\d{3})\r\n")
# Ein Telegramm ist 9 Byte lang; ein unvollständiger Anfang ist höchstens 8 Byte.
_MAX_PARTIAL = 8

# Schaltflächen: (key, Name, Wert). Die Werte entsprechen exakt den bisherigen
# Telegrammen (Auf=100, Zu=000, Regen=012, Lüften=102).
PRESETS: tuple[tuple[str, str, int], ...] = (
    ("auf", "Auf", 100),
    ("zu", "Zu", 0),
    ("regen", "Regen", 12),
    ("lueften", "Lüften", 102),
)


def build_command(value: int) -> bytes:
    """Erzeugt das Sende-Telegramm für einen Zielwert."""
    if not 0 <= value <= MAX_POSITION:
        raise ValueError(f"Wert außerhalb von 0..{MAX_POSITION}: {value}")
    return b"P_d=%03d\r\n" % value


class TelegramParser:
    """Setzt Rückmelde-Telegramme aus beliebig zerstückelten BLE-Paketen zusammen.

    BLE-UART-Brücken (z. B. HM-10) teilen Telegramme auf mehrere Pakete auf oder
    bündeln mehrere Telegramme in einem Paket. Der Puffer fängt beides ab.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def reset(self) -> None:
        self._buffer.clear()

    def feed(self, data: bytes) -> list[int]:
        """Nimmt ein Paket entgegen und liefert alle darin vollständigen, gültigen Positionen."""
        self._buffer.extend(data)
        positions: list[int] = []
        while match := _POSITION_RE.search(self._buffer):
            value = int(match.group(1))
            del self._buffer[: match.end()]
            if value <= MAX_POSITION:
                positions.append(value)
            else:
                _LOGGER.debug("Ungültige Position verworfen: %s", value)
        if len(self._buffer) > _MAX_PARTIAL:
            del self._buffer[:-_MAX_PARTIAL]
        return positions

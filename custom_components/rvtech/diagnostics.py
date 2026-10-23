"""Diagnosedaten für Home Assistant (Einstellungen -> Gerät -> Diagnose herunterladen)."""

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .coordinator import DachhaubeConfigEntry

TO_REDACT = {"address", "unique_id", "title"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DachhaubeConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(
            {
                "title": entry.title,
                "unique_id": entry.unique_id,
                "data": dict(entry.data),
            },
            TO_REDACT,
        ),
        "state": {
            "connected": coordinator.connected,
            "position": coordinator.position,
            "target": coordinator.target,
            "rssi": coordinator.rssi,
        },
    }

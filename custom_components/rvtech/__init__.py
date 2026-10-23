from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS
from .coordinator import DachhaubeBluetoothCoordinator, DachhaubeConfigEntry

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.COVER,
    Platform.SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: DachhaubeConfigEntry) -> bool:
    """Set up Dachhaube from a config entry."""
    coordinator = DachhaubeBluetoothCoordinator(hass, entry, entry.data[CONF_ADDRESS])
    await coordinator.async_start()

    entry.runtime_data = coordinator

    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        # Sonst bliebe die Verbindung im Hintergrund offen.
        await coordinator.async_stop()
        raise
    return True


async def async_unload_entry(hass: HomeAssistant, entry: DachhaubeConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.async_stop()

    return unload_ok

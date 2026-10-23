from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DachhaubeBluetoothCoordinator, DachhaubeConfigEntry
from .entity import DachhaubeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachhaubeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Dachhaube diagnostic sensors."""
    async_add_entities([DachhaubeRssiSensor(entry.runtime_data)])


class DachhaubeRssiSensor(DachhaubeEntity, SensorEntity):
    """Signalstärke (RSSI) der Haube - Diagnose, standardmäßig deaktiviert."""

    _attr_name = "Signalstärke"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: DachhaubeBluetoothCoordinator):
        super().__init__(coordinator, "rssi")

    @property
    def available(self) -> bool:
        return True  # auch ohne Verbindung sinnvoll (Advertisements)

    @property
    def native_value(self) -> int | None:
        return self._coordinator.rssi

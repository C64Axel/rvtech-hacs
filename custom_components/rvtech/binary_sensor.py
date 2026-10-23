from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DachhaubeBluetoothCoordinator, DachhaubeConfigEntry
from .entity import DachhaubeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachhaubeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DachhaubeConnectedSensor(entry.runtime_data)])


class DachhaubeConnectedSensor(DachhaubeEntity, BinarySensorEntity):
    """Zeigt, ob die Bluetooth-Verbindung zur Haube aktuell steht."""

    _attr_name = "Verbindung"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DachhaubeBluetoothCoordinator):
        super().__init__(coordinator, "connected")

    @property
    def available(self) -> bool:
        return True

    @property
    def is_on(self) -> bool:
        return self._coordinator.connected

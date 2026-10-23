from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity import Entity

from .const import DOMAIN
from .coordinator import DachhaubeBluetoothCoordinator


class DachhaubeEntity(Entity):
    """Basisklasse: gemeinsames Gerät, kein Polling, Updates per Coordinator-Listener."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: DachhaubeBluetoothCoordinator, key: str) -> None:
        self._coordinator = coordinator
        address = coordinator.address
        self._attr_unique_id = f"{address}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, address)},
            connections={(CONNECTION_BLUETOOTH, address)},
            name="Dachhaube",
            manufacturer="RVTech",
        )

    @property
    def available(self) -> bool:
        """Steuerelemente sind nur bei bestehender Bluetooth-Verbindung verfügbar."""
        return self._coordinator.connected

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )

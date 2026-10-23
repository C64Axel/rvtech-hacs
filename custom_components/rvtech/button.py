from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DachhaubeBluetoothCoordinator, DachhaubeConfigEntry
from .entity import DachhaubeEntity
from .protocol import PRESETS


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachhaubeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = entry.runtime_data

    async_add_entities(
        DachhaubeButton(coordinator, key, name, value) for key, name, value in PRESETS
    )


class DachhaubeButton(DachhaubeEntity, ButtonEntity):
    def __init__(self, coordinator: DachhaubeBluetoothCoordinator, key: str, name: str, value: int):
        super().__init__(coordinator, key)
        self._value = value
        self._attr_name = name

    async def async_press(self) -> None:
        """Handle button press via permanent BLE connection."""
        await self._coordinator.async_send_value(self._value)

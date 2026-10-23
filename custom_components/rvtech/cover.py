from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .coordinator import DachhaubeBluetoothCoordinator, DachhaubeConfigEntry
from .entity import DachhaubeEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DachhaubeConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([DachhaubeCover(entry.runtime_data)])


class DachhaubeCover(DachhaubeEntity, CoverEntity):
    """Die Dachhaube als Cover (Auf / Zu / Position)."""

    _attr_name = None  # Hauptentität: trägt den Gerätenamen
    _attr_device_class = CoverDeviceClass.WINDOW
    _attr_supported_features = (
        CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
        | CoverEntityFeature.SET_POSITION
    )

    def __init__(self, coordinator: DachhaubeBluetoothCoordinator):
        super().__init__(coordinator, "cover")

    @property
    def current_cover_position(self) -> int | None:
        position = self._coordinator.position
        # "Lüften" meldet 102 -> für die Anzeige auf 100 begrenzen.
        return None if position is None else min(position, 100)

    @property
    def extra_state_attributes(self) -> dict:
        return {"reported_position": self._coordinator.position}

    @property
    def is_closed(self) -> bool | None:
        position = self._coordinator.position
        return None if position is None else position == 0

    @property
    def is_opening(self) -> bool:
        c = self._coordinator
        return c.target is not None and c.position is not None and c.position < c.target

    @property
    def is_closing(self) -> bool:
        c = self._coordinator
        return c.target is not None and c.position is not None and c.position > c.target

    async def async_open_cover(self, **kwargs) -> None:
        await self._coordinator.async_send_value(100)

    async def async_close_cover(self, **kwargs) -> None:
        await self._coordinator.async_send_value(0)

    async def async_set_cover_position(self, **kwargs) -> None:
        await self._coordinator.async_send_value(int(kwargs["position"]))

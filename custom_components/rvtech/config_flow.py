from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)

from .const import CONF_ADDRESS, DOMAIN


def _normalize_address(address: str) -> str:
    """Home Assistant verwendet Bluetooth-Adressen in Großbuchstaben."""
    return address.strip().upper()


class DachhaubeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> config_entries.ConfigFlowResult:
        """Handle the bluetooth discovery step."""
        await self.async_set_unique_id(_normalize_address(discovery_info.address))
        self._abort_if_unique_id_configured()

        self._discovery_info = discovery_info
        self.context["title_placeholders"] = {
            "name": discovery_info.name or "Dachhaube"
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Confirm discovery without asking for a PIN."""
        assert self._discovery_info is not None
        address = _normalize_address(self._discovery_info.address)

        if user_input is not None:
            return self.async_create_entry(
                title=f"Dachhaube ({address})",
                data={CONF_ADDRESS: address},
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            description_placeholders={
                "name": self._discovery_info.name or "Dachhaube"
            },
        )

    async def async_step_user(
        self, user_input=None
    ) -> config_entries.ConfigFlowResult:
        """Handle the user step where only the address/device is selected."""
        if user_input is not None:
            address = _normalize_address(user_input[CONF_ADDRESS])
            await self.async_set_unique_id(address, raise_on_progress=False)
            self._abort_if_unique_id_configured()

            return self.async_create_entry(
                title=f"Dachhaube ({address})",
                data={CONF_ADDRESS: address},
            )

        current_addresses = self._async_current_ids()
        device_options = {
            _normalize_address(info.address): f"{info.name or 'Unbekannt'} ({info.address})"
            for info in async_discovered_service_info(self.hass)
            if _normalize_address(info.address) not in current_addresses
        }

        if not device_options:
            return self.async_abort(reason="no_devices_found")

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_ADDRESS): vol.In(device_options)}),
        )

from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)

from .const import CONF_ADDRESS, DOMAIN
from .pairing import PairingError, async_pair_device

CONF_PIN = "pin"
CONF_SKIP = "skip_pairing"


def _normalize_address(address: str) -> str:
    """Home Assistant verwendet Bluetooth-Adressen in Großbuchstaben."""
    return address.strip().upper()


class DachhaubeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._discovery_info: BluetoothServiceInfoBleak | None = None
        self._address: str | None = None
        self._reconfigure_entry: config_entries.ConfigEntry | None = None

    async def _async_pair_step(self, user_input, *, step_id: str):
        """Gemeinsamer Kopplungsschritt für Einrichtung und Neu-Kopplung."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get(CONF_SKIP):
                entry = self._reconfigure_entry
                if entry is not None:
                    # Die laufende Dauerverbindung freigeben (die Haube erlaubt nur eine).
                    await self.hass.config_entries.async_unload(entry.entry_id)
                try:
                    await async_pair_device(
                        self.hass, self._address, (user_input.get(CONF_PIN) or "").strip() or None
                    )
                except PairingError as err:
                    errors["base"] = err.reason
                finally:
                    if entry is not None:
                        await self.hass.config_entries.async_reload(entry.entry_id)
            if not errors:
                if self._reconfigure_entry is not None:
                    return self.async_abort(reason="reconfigure_successful")
                return self.async_create_entry(
                    title=f"Dachhaube ({self._address})",
                    data={CONF_ADDRESS: self._address},
                )

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema(
                {
                    vol.Optional(CONF_PIN, default=""): str,
                    vol.Optional(CONF_SKIP, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_pair(self, user_input=None) -> config_entries.ConfigFlowResult:
        return await self._async_pair_step(user_input, step_id="pair")

    async def async_step_reconfigure(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Haube erneut koppeln (z. B. nach Wechsel des Bluetooth-Adapters)."""
        self._reconfigure_entry = self._get_reconfigure_entry()
        self._address = self._reconfigure_entry.data[CONF_ADDRESS]
        return await self._async_pair_step(user_input, step_id="reconfigure")

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
        """Erkennung bestätigen; die Kopplung folgt im nächsten Schritt."""
        assert self._discovery_info is not None
        address = _normalize_address(self._discovery_info.address)

        if user_input is not None:
            self._address = address
            return await self.async_step_pair()

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

            self._address = address
            return await self.async_step_pair()

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

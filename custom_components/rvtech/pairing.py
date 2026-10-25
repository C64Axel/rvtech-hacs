"""Kopplung (Bonding) der Dachhaube über BlueZ, optional mit PIN.

Bleak bietet für ``pair()`` keine PIN-Abfrage. Deshalb wird während der Kopplung
ein eigener BlueZ-Agent (``org.bluez.Agent1``) über D-Bus registriert, der die
PIN-Abfrage beantwortet. Das funktioniert nur mit einem lokalen Bluetooth-Adapter
(z. B. USB-Stick) unter Linux/HAOS, nicht über einen ESPHome-Bluetooth-Proxy.

Hinweis: dieses Modul darf kein ``from __future__ import annotations`` enthalten,
weil dbus-fast die D-Bus-Signaturen aus den Annotationen liest.
"""

import asyncio
import logging

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

AGENT_PATH = "/rvtech/agent"
PAIR_TIMEOUT = 40


class PairingError(Exception):
    """Kopplung fehlgeschlagen; ``reason`` ist ein Fehlerschlüssel für den Config-Flow."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(detail or reason)
        self.reason = reason


def _make_agent_class():
    """Erzeugt die Agent-Klasse erst bei Bedarf (dbus-fast nur unter Linux)."""
    from dbus_fast.service import ServiceInterface, method  # noqa: PLC0415

    class PinAgent(ServiceInterface):
        def __init__(self, pin: str) -> None:
            super().__init__("org.bluez.Agent1")
            self._pin = pin

        @method()
        def Release(self):  # noqa: N802
            return

        @method()
        def RequestPinCode(self, device: "o") -> "s":  # noqa: N802, F821
            _LOGGER.debug("BlueZ fragt PIN-Code an (%s)", device)
            return self._pin

        @method()
        def RequestPasskey(self, device: "o") -> "u":  # noqa: N802, F821
            _LOGGER.debug("BlueZ fragt Passkey an (%s)", device)
            return int(self._pin)

        @method()
        def DisplayPinCode(self, device: "o", pincode: "s"):  # noqa: N802, F821
            return

        @method()
        def DisplayPasskey(self, device: "o", passkey: "u", entered: "q"):  # noqa: N802, F821
            return

        @method()
        def RequestConfirmation(self, device: "o", passkey: "u"):  # noqa: N802, F821
            return  # bestätigen

        @method()
        def RequestAuthorization(self, device: "o"):  # noqa: N802, F821
            return

        @method()
        def AuthorizeService(self, device: "o", uuid: "s"):  # noqa: N802, F821
            return

        @method()
        def Cancel(self):  # noqa: N802
            return

    return PinAgent


async def _register_agent(pin: str):
    """Registriert den Agent als Standard-Agent; liefert (bus, agent_manager)."""
    from dbus_fast import BusType  # noqa: PLC0415
    from dbus_fast.aio import MessageBus  # noqa: PLC0415

    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        bus.export(AGENT_PATH, _make_agent_class()(pin))
        introspection = await bus.introspect("org.bluez", "/org/bluez")
        proxy = bus.get_proxy_object("org.bluez", "/org/bluez", introspection)
        manager = proxy.get_interface("org.bluez.AgentManager1")
        await manager.call_register_agent(AGENT_PATH, "KeyboardOnly")
        await manager.call_request_default_agent(AGENT_PATH)
    except Exception:
        bus.disconnect()
        raise
    return bus, manager


async def async_pair_device(hass: HomeAssistant, address: str, pin: str | None) -> None:
    """Koppelt die Haube (mit PIN, falls angegeben). Wirft ``PairingError``."""
    if pin and not (pin.isdigit() and 1 <= len(pin) <= 6):
        raise PairingError("invalid_pin")

    ble_device = bluetooth.async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        raise PairingError("not_in_range")

    details = getattr(ble_device, "details", None)
    if not (isinstance(details, dict) and "path" in details):
        # Gerät wird über einen Proxy (ESPHome) gesehen, nicht über BlueZ.
        raise PairingError("proxy_not_supported")

    client: BleakClient | None = None
    bus = manager = None
    try:
        client = await establish_connection(
            BleakClientWithServiceCache, ble_device, "Dachhaube (Kopplung)", max_attempts=3
        )
        if pin:
            try:
                bus, manager = await _register_agent(pin)
            except Exception as err:  # noqa: BLE001
                raise PairingError("agent_failed", str(err)) from err
        try:
            async with asyncio.timeout(PAIR_TIMEOUT):
                await client.pair()
        except TimeoutError as err:
            raise PairingError("pairing_failed", "Zeitüberschreitung") from err
        except BleakError as err:
            raise PairingError("pairing_failed", str(err)) from err
    except PairingError:
        raise
    except Exception as err:  # noqa: BLE001
        raise PairingError("cannot_connect", str(err)) from err
    finally:
        if manager is not None:
            try:
                await manager.call_unregister_agent(AGENT_PATH)
            except Exception:  # noqa: BLE001
                pass
        if bus is not None:
            bus.disconnect()
        if client is not None:
            try:
                await client.disconnect()
            except Exception:  # noqa: BLE001
                pass
    _LOGGER.info("Dachhaube (%s) erfolgreich gekoppelt.", address)

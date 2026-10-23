import asyncio
import contextlib
import logging

from bleak import BleakClient
from bleak.exc import BleakError
from bleak_retry_connector import BleakClientWithServiceCache, establish_connection

from homeassistant.components import bluetooth
from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_call_later

from .protocol import CHARACTERISTIC_UUID, TelegramParser, build_command

_LOGGER = logging.getLogger(__name__)

# Wartezeit auf ein Advertisement, wenn die Haube nicht in Reichweite ist.
ADVERTISEMENT_WAIT = 60
# Pause nach einer regulären Trennung, bevor neu verbunden wird.
RECONNECT_DELAY = 2
# Exponentielles Backoff nach Fehlern: 5s, 10s, 20s, 40s, dann max. 60s.
BACKOFF_START = 5
BACKOFF_MAX = 60
# So lange wartet ein Kommando auf eine (Wieder-)Verbindung, bevor es fehlschlägt.
SEND_CONNECT_TIMEOUT = 10
# Pause vor dem zweiten Sendeversuch nach einem Schreibfehler.
SEND_RETRY_DELAY = 1
# So lange gilt ein gesendeter Zielwert als "in Bewegung", falls die Haube
# den Zielwert nie zurückmeldet.
TARGET_TIMEOUT = 60

type DachhaubeConfigEntry = ConfigEntry["DachhaubeBluetoothCoordinator"]


class DachhaubeBluetoothCoordinator:
    """Verwaltet eine dauerhafte Bluetooth-Verbindung zur Dachhaube."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, address: str):
        self.hass = hass
        self.entry = entry
        self.address = address
        self.client: BleakClient | None = None
        self.connected = False
        self.position: int | None = None
        self.target: int | None = None
        self.rssi: int | None = None

        self._listeners: list[CALLBACK_TYPE] = []
        self._connected_event = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._parser = TelegramParser()
        self._running = False
        self._task: asyncio.Task | None = None
        self._advertisement_event = asyncio.Event()
        self._disconnected_event = asyncio.Event()
        self._unsub_advertisement: CALLBACK_TYPE | None = None
        self._unsub_target_timer: CALLBACK_TYPE | None = None
        self._out_of_range_logged = False

    # ------------------------------------------------------------------
    # Zustand
    # ------------------------------------------------------------------
    @callback
    def async_add_listener(self, update_callback: CALLBACK_TYPE) -> CALLBACK_TYPE:
        """Registriert einen Listener; gibt die Funktion zum Abmelden zurück."""
        self._listeners.append(update_callback)

        @callback
        def remove_listener() -> None:
            if update_callback in self._listeners:
                self._listeners.remove(update_callback)

        return remove_listener

    @callback
    def _notify(self) -> None:
        """Alle Entitäten zum Neuschreiben ihres Zustands auffordern."""
        for update_callback in list(self._listeners):
            update_callback()

    @callback
    def _set_connected(self, connected: bool) -> None:
        if self.connected != connected:
            self.connected = connected
            if connected:
                self._connected_event.set()
            else:
                self._connected_event.clear()
            self._notify()

    @callback
    def _set_target(self, target: int | None) -> None:
        if self._unsub_target_timer:
            self._unsub_target_timer()
            self._unsub_target_timer = None
        self.target = target
        if target is not None:
            self._unsub_target_timer = async_call_later(
                self.hass, TARGET_TIMEOUT, self._target_expired
            )
        self._notify()

    @callback
    def _target_expired(self, _now) -> None:
        self._unsub_target_timer = None
        self.target = None
        self._notify()

    # ------------------------------------------------------------------
    # Eingehende Daten
    # ------------------------------------------------------------------
    @callback
    def _async_advertisement(
        self, service_info: BluetoothServiceInfoBleak, change: BluetoothChange
    ) -> None:
        """Wird bei jedem Advertisement der Haube aufgerufen."""
        self.rssi = service_info.rssi
        self._advertisement_event.set()
        self._notify()

    def _notification_handler(self, sender, data: bytearray):
        """Wird bei jedem eingehenden Bluetooth-Paket aufgerufen."""
        _LOGGER.debug("Bluetooth Paket empfangen: %s", data.hex())
        for pos in self._parser.feed(bytes(data)):
            self.position = pos
            if self.target is not None and pos == self.target:
                self._set_target(None)  # sendet ebenfalls _notify()
            else:
                self._notify()

    def _on_disconnect(self, client: BleakClient) -> None:
        _LOGGER.debug("Dachhaube (%s) hat die Verbindung getrennt.", self.address)
        self._disconnected_event.set()

    # ------------------------------------------------------------------
    # Lebenszyklus
    # ------------------------------------------------------------------
    async def async_start(self):
        """Startet den Dauer-Verbindungstask."""
        self._running = True
        self._unsub_advertisement = bluetooth.async_register_callback(
            self.hass,
            self._async_advertisement,
            BluetoothCallbackMatcher(address=self.address, connectable=True),
            BluetoothScanningMode.ACTIVE,
        )
        self._task = self.entry.async_create_background_task(
            self.hass, self._maintain_connection(), f"Dachhaube BLE ({self.address})"
        )

    async def async_stop(self):
        """Stoppt die Verbindung sauber."""
        self._running = False
        if self._unsub_advertisement:
            self._unsub_advertisement()
            self._unsub_advertisement = None
        if self._unsub_target_timer:
            self._unsub_target_timer()
            self._unsub_target_timer = None
        # Erst den Task beenden (und abwarten), damit er nicht neu verbindet;
        # das Trennen übernimmt das finally im Task.
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _async_disconnect(self, client: BleakClient) -> None:
        try:
            if client.is_connected:
                await client.disconnect()
        except Exception as err:
            _LOGGER.debug("Fehler beim Trennen der Bluetooth-Verbindung: %s", err)

    async def _maintain_connection(self):
        """Hält die Verbindung dauerhaft aufrecht und lauscht auf Daten."""
        failures = 0
        while self._running:
            client: BleakClient | None = None
            try:
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, self.address, connectable=True
                )

                if not ble_device:
                    if not self._out_of_range_logged:
                        _LOGGER.warning(
                            "Dachhaube (%s) momentan nicht in Reichweite.", self.address
                        )
                        self._out_of_range_logged = True
                    # Auf das nächste Advertisement warten statt zu pollen.
                    self._advertisement_event.clear()
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._advertisement_event.wait(), ADVERTISEMENT_WAIT
                        )
                    continue

                if self._out_of_range_logged:
                    _LOGGER.info("Dachhaube (%s) wieder in Reichweite.", self.address)
                    self._out_of_range_logged = False

                _LOGGER.debug("Versuche stabile Verbindung zur Dachhaube aufzubauen...")

                client = await establish_connection(
                    client_class=BleakClientWithServiceCache,
                    device=ble_device,
                    name="Dachhaube",
                    disconnected_callback=self._on_disconnect,
                    max_attempts=3,
                    ble_device_callback=lambda: bluetooth.async_ble_device_from_address(
                        self.hass, self.address, connectable=True
                    )
                    or ble_device,
                )
                # Erst jetzt zurücksetzen: ein Trenn-Callback eines fehlgeschlagenen
                # Versuchs darf die neue Verbindung nicht sofort wieder beenden.
                self._disconnected_event.clear()
                if not client.is_connected:
                    raise BleakError("Verbindung direkt nach dem Aufbau wieder getrennt")

                _LOGGER.info("Erfolgreich mit Dachhaube (%s) verbunden.", self.address)

                # Notifications abonnieren
                await client.start_notify(CHARACTERISTIC_UUID, self._notification_handler)
                self._parser.reset()
                self.client = client
                self._set_connected(True)
                failures = 0

                # Ohne Polling warten, bis die Haube die Verbindung trennt.
                await self._disconnected_event.wait()
                _LOGGER.info("Verbindung zur Dachhaube (%s) getrennt.", self.address)

            except Exception as err:
                failures += 1
                _LOGGER.log(
                    logging.WARNING if failures == 1 else logging.DEBUG,
                    "Bluetooth-Fehler bei Dachhaube (%s): %s",
                    self.address,
                    err,
                )

            finally:
                # Auch bei Fehlern (z. B. in start_notify) und beim Abbruch:
                # die Verbindung nie offen lassen.
                self.client = None
                self._set_connected(False)
                if client is not None:
                    await self._async_disconnect(client)

            if self._running:
                if failures:
                    delay = min(BACKOFF_START * 2 ** (failures - 1), BACKOFF_MAX)
                else:
                    delay = RECONNECT_DELAY
                await asyncio.sleep(delay)

    # ------------------------------------------------------------------
    # Senden
    # ------------------------------------------------------------------
    async def _async_get_client(self) -> BleakClient:
        """Liefert den verbundenen Client; wartet kurz auf eine laufende (Wieder-)Verbindung."""
        if not self.connected:
            try:
                await asyncio.wait_for(self._connected_event.wait(), SEND_CONNECT_TIMEOUT)
            except TimeoutError:
                raise HomeAssistantError(
                    "Die Dachhaube ist aktuell nicht per Bluetooth verbunden."
                ) from None
        client = self.client
        if client is None or not client.is_connected:
            raise HomeAssistantError("Die Dachhaube ist aktuell nicht per Bluetooth verbunden.")
        return client

    async def async_send_value(self, value: int) -> None:
        """Sendet einen Zielwert über die bestehende Dauerverbindung.

        Schreibzugriffe laufen nacheinander (Lock). Bei einem Schreibfehler wird
        nach kurzer Pause einmal wiederholt (die Verbindung wird ggf. neu aufgebaut).
        """
        data = build_command(value)
        async with self._write_lock:
            for attempt in (1, 2):
                client = await self._async_get_client()
                try:
                    await client.write_gatt_char(CHARACTERISTIC_UUID, data, response=False)
                    break
                except (BleakError, TimeoutError, OSError, EOFError) as err:
                    if attempt == 2:
                        raise HomeAssistantError(
                            f"Senden an die Dachhaube fehlgeschlagen: {err}"
                        ) from err
                    _LOGGER.debug("Senden fehlgeschlagen (%s), neuer Versuch", err)
                    await asyncio.sleep(SEND_RETRY_DELAY)
        # Erst nach erfolgreichem Senden als Ziel übernehmen.
        self._set_target(value)

"""LoRemote Coordinator — orchestrates all components."""
from __future__ import annotations

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_SERIAL_PORT, CONF_SELECTED_ENTITIES
from .device_registry import DeviceRegistry
from .meshtastic_client import MeshtasticClient
from .packet_store import PacketStore
from .protocol import Protocol
from .ha_bridge import HABridge

_LOGGER = logging.getLogger(__name__)


class LoRemoteCoordinator:
    """Central coordinator for LoRemote."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.config = entry.data

        self.registry = DeviceRegistry(hass)
        self.protocol = Protocol()
        self.packet_store = PacketStore()
        self.client: MeshtasticClient | None = None
        self.bridge: HABridge | None = None
        self._running = False
        self._sensor_entities: dict = {}

    def set_sensor_entities(self, entities: dict) -> None:
        self._sensor_entities = entities

    def _update_sensors(self) -> None:
        """Push current state to all sensor entities."""
        if not self._sensor_entities:
            return
        vals = self.packet_store.to_sensor_values()
        vals["status"] = "online" if self.client and self.client._iface else "offline"
        vals["node_id"] = self.config.get("node_id", "")
        vals["devices_count"] = len(self.registry.devices)
        for key, val in vals.items():
            sensor = self._sensor_entities.get(key)
            if sensor:
                sensor.set_value(val)

    async def async_start(self) -> None:
        """Start all components."""
        _LOGGER.info("LoRemote: starting coordinator")

        # Build device registry from selected entities
        selected = self.entry.options.get(
            CONF_SELECTED_ENTITIES,
            self.entry.data.get(CONF_SELECTED_ENTITIES, [])
        )
        await self.hass.async_add_executor_job(
            self.registry.build, selected
        )
        _LOGGER.info(
            "LoRemote: registry built — %d devices, %d areas",
            len(self.registry.devices),
            len(self.registry.areas),
        )

        # Start Meshtastic client
        self.client = MeshtasticClient(
            serial_port=self.entry.options.get(
                CONF_SERIAL_PORT,
                self.entry.data.get(CONF_SERIAL_PORT, "")
            ),
            node_id=self.config.get("node_id"),
            on_message=self._on_message_received,
            on_connected=self._on_client_connected,
            on_lost=self._on_client_disconnected,
        )
        await self.hass.async_add_executor_job(self.client.connect)

        # Start HA bridge (listens to state changes, sends pushes)
        self.bridge = HABridge(
            hass=self.hass,
            registry=self.registry,
            protocol=self.protocol,
            client=self.client,
            config=self.config,
            coordinator=self,
        )
        await self.bridge.async_start()

        self.packet_store.on_connected()
        self._update_sensors()

        self._running = True
        _LOGGER.info("LoRemote: started successfully")

    async def async_stop(self) -> None:
        """Stop all components."""
        self._running = False
        self.packet_store.on_disconnected("integration stopped")
        self._update_sensors()
        if self.bridge:
            await self.bridge.async_stop()
        if self.client:
            await self.hass.async_add_executor_job(self.client.disconnect)
        _LOGGER.info("LoRemote: stopped")

    def _on_client_connected(self) -> None:
        _LOGGER.info("LoRemote: Meshtastic connection established")
        self.packet_store.on_connected()
        self._update_sensors()

    def _on_client_disconnected(self, reason: str = None) -> None:
        _LOGGER.warning("LoRemote: Meshtastic connection lost — will retry")
        self.packet_store.on_disconnected(reason)
        self._update_sensors()
        # Schedule reconnect
        self.hass.loop.call_later(10, lambda: asyncio.ensure_future(
            self._reconnect(), loop=self.hass.loop
        ))

    async def _reconnect(self) -> None:
        """Try to reconnect to T114."""
        if not self._running:
            return
        _LOGGER.info("LoRemote: attempting reconnect to T114...")

        serial_port = self.entry.options.get(
            "serial_port", self.entry.data.get("serial_port", "")
        )

        try:
            await self.hass.async_add_executor_job(self.client.disconnect)
        except Exception:
            pass

        # Ждём появления устройства в /dev/ — до 60 секунд
        appeared = await self.hass.async_add_executor_job(
            self._wait_for_device, serial_port, 60
        )

        if not appeared:
            _LOGGER.warning(
                "LoRemote: device %s did not appear within 60s, retry in 30s",
                serial_port
            )
            if self._running:
                self.hass.loop.call_later(30, lambda: asyncio.ensure_future(
                    self._reconnect(), loop=self.hass.loop
                ))
            return

        try:
            await self.hass.async_add_executor_job(self.client.connect)
            _LOGGER.info("LoRemote: reconnect successful")
        except Exception as e:
            _LOGGER.warning("LoRemote: reconnect failed: %s, retry in 30s", e)
            self.packet_store.on_disconnected(f"reconnect failed: {e}")
            self._update_sensors()
            if self._running:
                self.hass.loop.call_later(30, lambda: asyncio.ensure_future(
                    self._reconnect(), loop=self.hass.loop
                ))

    def _wait_for_device(self, serial_port: str, timeout: int) -> bool:
        """Wait for serial device to appear in /dev/. Runs in executor."""
        import os
        import time

        deadline = time.time() + timeout
        while time.time() < deadline:
            # Проверяем и точный путь и by-id паттерн
            if os.path.exists(serial_port):
                _LOGGER.info("LoRemote: device %s appeared", serial_port)
                time.sleep(1)  # небольшая пауза после появления
                return True
            # Также проверяем by-id директорию если путь там
            if "by-id" in serial_port:
                import glob
                pattern = serial_port.rsplit("-if", 1)[0] + "*"
                if glob.glob(pattern):
                    _LOGGER.info("LoRemote: device appeared (glob match)")
                    time.sleep(1)
                    return True
            time.sleep(2)
        return False

    async def _on_message_received(self, raw: bytes, from_node: str, raw_packet: dict = None) -> None:
        """Handle incoming LoRa message from phone."""
        try:
            packet = self.protocol.decode(raw)
        except Exception as e:
            _LOGGER.warning("LoRemote: failed to decode packet: %s", e)
            return

        # Log received packet
        rssi = raw_packet.get("rxRssi") if raw_packet else None
        snr = raw_packet.get("rxSnr") if raw_packet else None
        self.packet_store.add_rx(from_node, raw, packet, rssi, snr, hop_limit=0)
        self._update_sensors()

        _LOGGER.debug("LoRemote: received packet from %s: %s", from_node, packet)
        await self.bridge.async_handle_packet(packet, from_node)

    def get_export_config(self) -> dict:
        """Generate full config JSON for HTML client export."""
        config = self.registry.build_export_config(
            {**self.entry.data, **self.entry.options}
        )
        config["usr"] = self.entry.options.get(
            "users", self.entry.data.get("users", [])
        )
        return config

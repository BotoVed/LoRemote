"""LoRemote Coordinator — orchestrates all components."""
from __future__ import annotations

import asyncio
import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, CONF_SERIAL_PORT, CONF_SELECTED_ENTITIES
from .device_registry import DeviceRegistry
from .meshtastic_client import MeshtasticClient
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
        self.client: MeshtasticClient | None = None
        self.bridge: HABridge | None = None
        self._running = False

    async def async_start(self) -> None:
        """Start all components."""
        _LOGGER.info("LoRemote: starting coordinator")

        # Build device registry from selected entities
        selected = self.config.get(CONF_SELECTED_ENTITIES, [])
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
            serial_port=self.config[CONF_SERIAL_PORT],
            node_id=self.config.get("node_id"),
            on_message=self._on_message_received,
        )
        await self.hass.async_add_executor_job(self.client.connect)

        # Start HA bridge (listens to state changes, sends pushes)
        self.bridge = HABridge(
            hass=self.hass,
            registry=self.registry,
            protocol=self.protocol,
            client=self.client,
            config=self.config,
        )
        await self.bridge.async_start()

        self._running = True
        _LOGGER.info("LoRemote: started successfully")

    async def async_stop(self) -> None:
        """Stop all components."""
        self._running = False
        if self.bridge:
            await self.bridge.async_stop()
        if self.client:
            await self.hass.async_add_executor_job(self.client.disconnect)
        _LOGGER.info("LoRemote: stopped")

    async def _on_message_received(self, raw: bytes, from_node: str) -> None:
        """Handle incoming LoRa message from phone."""
        try:
            packet = self.protocol.decode(raw)
        except Exception as e:
            _LOGGER.warning("LoRemote: failed to decode packet: %s", e)
            return

        _LOGGER.debug("LoRemote: received packet from %s: %s", from_node, packet)
        await self.bridge.async_handle_packet(packet, from_node)

    def get_export_config(self) -> dict:
        """Generate full config JSON for HTML client export."""
        return self.registry.build_export_config(self.config)

"""HA Bridge — listens to HA state changes, handles incoming commands."""
from __future__ import annotations

import asyncio
import logging
import time
from homeassistant.core import HomeAssistant, Event, callback
from homeassistant.helpers.event import async_track_state_change_event

from .const import (
    PKT_CMD, PKT_PING, PKT_CONFIG,
    SEC_META, SEC_AREAS, SEC_DEVICES, SEC_MAPPING,
    CONF_PUSH_ENABLED, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL,
    RETRY_INTERVAL_SEC, MAX_ATTEMPTS, HOP_LIMIT_DIRECT, HOP_LIMIT_MESH, HOP_SWITCH_AT,
)
from .device_registry import DeviceRegistry
from .protocol import Protocol
from .meshtastic_client import MeshtasticClient

_LOGGER = logging.getLogger(__name__)

# Pages size — max devices per config packet
DEVICES_PER_PAGE = 5
MAPPING_PER_PAGE = 8


class HABridge:
    """Bridge between HA and Meshtastic."""

    def __init__(
        self,
        hass: HomeAssistant,
        registry: DeviceRegistry,
        protocol: Protocol,
        client: MeshtasticClient,
        config: dict,
        coordinator=None,
    ) -> None:
        self.hass = hass
        self.registry = registry
        self.protocol = protocol
        self.client = client
        self.config = config
        self._coordinator = coordinator
        self._unsub = None
        self._push_enabled = config.get(CONF_PUSH_ENABLED, True)
        self._cfgh: str = ""
        self._last_phone_node: str | None = None  # remember who to push to

    async def async_start(self) -> None:
        """Start listening to HA state changes."""
        self.client.set_event_loop(asyncio.get_event_loop())

        if self._push_enabled:
            self._unsub = async_track_state_change_event(
                self.hass,
                list(self.registry._entity_to_hash.keys()),
                self._on_state_changed,
            )
        self._cfgh = self._compute_cfgh()
        _LOGGER.info("LoRemote: HA bridge started, cfgh=%s", self._cfgh)

    async def async_stop(self) -> None:
        """Stop listening."""
        if self._unsub:
            self._unsub()
        _LOGGER.info("LoRemote: HA bridge stopped")

    # ── Incoming packets from phone ───────────────────────────────────────

    async def async_handle_packet(self, packet: dict, from_node: str) -> None:
        """Route incoming packet to the right handler."""
        self._last_phone_node = from_node
        tp = packet.get("tp")

        if tp == PKT_PING:
            await self._handle_ping(packet, from_node)
        elif tp == PKT_CMD:
            if "cfg" in packet:
                await self._handle_config_request(packet, from_node)
            elif packet.get("req") == "all":
                await self._handle_req_all(from_node)
            elif "req" in packet:
                await self._handle_req_one(packet, from_node)
            elif "id" in packet:
                await self._handle_command(packet, from_node)
        else:
            _LOGGER.warning("LoRemote: unknown packet tp=%s", tp)

    async def _handle_ping(self, packet: dict, from_node: str) -> None:
        """Reply to ping with echo + cfgh."""
        pong = self.protocol.make_pong(packet.get("ts", 0), self._cfgh)
        await self._send(pong, from_node)

    async def _handle_config_request(self, packet: dict, from_node: str) -> None:
        """Handle cfg:1 (meta only) or cfg:2 (full config)."""
        cfg_type = packet.get("cfg")

        if cfg_type == 1:
            # Just meta + cfgh
            meta = self.registry.build_export_config(self.config)
            meta_packet = self.protocol.make_config_meta({
                "n": meta["n"], "tz": meta["tz"], "gw": meta["gw"],
                "ch": meta["ch"], "key": meta["key"],
                "upd": meta["upd"], "psh": meta["psh"],
                "cfgh": self._cfgh,
            })
            await self._send(meta_packet, from_node)

        elif cfg_type == 2:
            # Full config — paginated
            sec = packet.get("s")
            pg = packet.get("pg")

            if sec and pg:
                # Re-send specific page
                await self._send_config_section(sec, from_node, only_page=pg)
            else:
                # Send all sections
                await self._send_full_config(from_node)

    async def _send_full_config(self, to_node: str) -> None:
        """Send areas → devices → mapping sequentially."""
        await self._send_config_section(SEC_AREAS, to_node)
        await asyncio.sleep(4)
        await self._send_config_section(SEC_DEVICES, to_node)
        await asyncio.sleep(4)
        await self._send_config_section(SEC_MAPPING, to_node)

    async def _send_config_section(
        self, section: str, to_node: str, only_page: int | None = None
    ) -> None:
        """Send a config section as paginated packets."""
        if section == SEC_AREAS:
            items = list(self.registry.areas.values())
            page_size = 20
        elif section == SEC_DEVICES:
            items = [
                {"id": k, "t": v["t"], "n": v["n"], "a": v["a"], "u": v["u"]}
                for k, v in self.registry.devices.items()
            ]
            page_size = DEVICES_PER_PAGE
        elif section == SEC_MAPPING:
            items = [
                {"id": k, "t": v["t"], "n": v["n"], "a": v["a"], "u": v["u"]}
                for k, v in self.registry.devices.items()
            ]
            page_size = MAPPING_PER_PAGE
        else:
            return

        pages = [items[i:i+page_size] for i in range(0, len(items), page_size)]
        total = len(pages)

        for i, page_data in enumerate(pages, 1):
            if only_page and i != only_page:
                continue
            pkt = self.protocol.make_config_page(section, i, total, page_data)
            await self._send(pkt, to_node)
            if not only_page:
                await asyncio.sleep(4)  # respect duty cycle

    async def _handle_req_all(self, from_node: str) -> None:
        """Send current state of all devices."""
        for short_id, device in self.registry.devices.items():
            entity_id = device["entity_id"]
            state = self.hass.states.get(entity_id)
            state_dict = self.protocol.extract_state(entity_id, state, device["t"])
            pkt = self.protocol.make_status(short_id, state_dict)
            await self._send(pkt, from_node)
            await asyncio.sleep(4)  # duty cycle

    async def _handle_req_one(self, packet: dict, from_node: str) -> None:
        """Send current state of one device."""
        short_id = packet.get("id")
        device = self.registry.get_device(short_id)
        if not device:
            _LOGGER.warning("LoRemote: unknown device id %s", short_id)
            return
        state = self.hass.states.get(device["entity_id"])
        state_dict = self.protocol.extract_state(device["entity_id"], state, device["t"])
        pkt = self.protocol.make_status(short_id, state_dict)
        await self._send(pkt, from_node)

    async def _handle_command(self, packet: dict, from_node: str) -> None:
        """Execute HA service call from phone command."""
        short_id = packet.get("id")
        device = self.registry.get_device(short_id)
        if not device:
            _LOGGER.warning("LoRemote: unknown device id %s", short_id)
            return

        entity_id = device["entity_id"]
        device_type = device["t"]
        domain = entity_id.split(".")[0]

        try:
            await self._call_service(domain, device_type, entity_id, packet)
        except Exception as e:
            _LOGGER.error("LoRemote: service call failed for %s: %s", entity_id, e)

        # Send confirmation with actual current state
        await asyncio.sleep(0.5)
        state = self.hass.states.get(entity_id)
        state_dict = self.protocol.extract_state(entity_id, state, device_type)
        confirm = self.protocol.make_confirm(short_id, state_dict)
        await self._send(confirm, from_node)

    async def _call_service(
        self, domain: str, device_type: str, entity_id: str, packet: dict
    ) -> None:
        """Map packet to HA service call."""
        s = packet.get("s")
        service_data = {"entity_id": entity_id}

        if device_type == "L":
            if s == 0:
                await self.hass.services.async_call("light", "turn_off", service_data)
            else:
                if "bri" in packet:
                    service_data["brightness"] = int(packet["bri"] * 2.55)
                if "ct" in packet:
                    service_data["color_temp"] = packet["ct"]
                await self.hass.services.async_call("light", "turn_on", service_data)

        elif device_type in ("SW", "SI"):
            svc = "turn_on" if s == 1 else "turn_off"
            await self.hass.services.async_call(domain, svc, service_data)

        elif device_type == "C":
            if "s" in packet:
                svc = "turn_on" if s == 1 else "turn_off"
                await self.hass.services.async_call("climate", svc, service_data)
            if "th" in packet:
                service_data["temperature"] = packet["th"]
                await self.hass.services.async_call(
                    "climate", "set_temperature", service_data
                )
            if "md" in packet:
                service_data["hvac_mode"] = packet["md"]
                await self.hass.services.async_call(
                    "climate", "set_hvac_mode", service_data
                )
            if "fn" in packet:
                service_data["fan_mode"] = packet["fn"]
                await self.hass.services.async_call(
                    "climate", "set_fan_mode", service_data
                )

        elif device_type == "WH":
            if "s" in packet:
                svc = "turn_on" if s == 1 else "turn_off"
                await self.hass.services.async_call("water_heater", svc, service_data)
            if "th" in packet:
                service_data["temperature"] = packet["th"]
                await self.hass.services.async_call(
                    "water_heater", "set_temperature", service_data
                )

        elif device_type == "F":
            if "s" in packet:
                svc = "turn_on" if s == 1 else "turn_off"
                await self.hass.services.async_call("fan", svc, service_data)
            if "sp" in packet:
                service_data["percentage"] = packet["sp"]
                await self.hass.services.async_call(
                    "fan", "set_percentage", service_data
                )

        elif device_type == "CV":
            cmd = packet.get("cmd")
            if cmd == "open":
                await self.hass.services.async_call("cover", "open_cover", service_data)
            elif cmd == "close":
                await self.hass.services.async_call("cover", "close_cover", service_data)
            elif cmd == "stop":
                await self.hass.services.async_call("cover", "stop_cover", service_data)
            elif "pos" in packet:
                service_data["position"] = packet["pos"]
                await self.hass.services.async_call(
                    "cover", "set_cover_position", service_data
                )

        elif device_type == "LK":
            cmd = packet.get("cmd")
            svc = "unlock" if cmd == "unlock" else "lock"
            await self.hass.services.async_call("lock", svc, service_data)

        elif device_type == "A":
            cmd = packet.get("cmd", "")
            pin = packet.get("pin")
            if pin:
                service_data["code"] = str(pin)
            svc_map = {
                "arm_home": "alarm_arm_home",
                "arm_away": "alarm_arm_away",
                "arm_night": "alarm_arm_night",
                "disarm": "alarm_disarm",
            }
            svc = svc_map.get(cmd)
            if svc:
                await self.hass.services.async_call("alarm_control_panel", svc, service_data)

        elif device_type == "H":
            if "s" in packet:
                svc = "turn_on" if s == 1 else "turn_off"
                await self.hass.services.async_call("humidifier", svc, service_data)
            if "th" in packet:
                service_data["humidity"] = packet["th"]
                await self.hass.services.async_call(
                    "humidifier", "set_humidity", service_data
                )

        elif device_type == "B":
            await self.hass.services.async_call(domain, "press", service_data)

    # ── HA state change → push to phone ───────────────────────────────────

    @callback
    def _on_state_changed(self, event: Event) -> None:
        """Triggered when a tracked entity changes state in HA."""
        if not self._last_phone_node:
            return  # no phone connected yet

        entity_id = event.data.get("entity_id")
        new_state = event.data.get("new_state")

        short_id = self.registry.get_hash(entity_id)
        if not short_id:
            return

        device = self.registry.get_device(short_id)
        state_dict = self.protocol.extract_state(entity_id, new_state, device["t"])
        pkt = self.protocol.make_push(short_id, state_dict)

        asyncio.ensure_future(self._send(pkt, self._last_phone_node))

    # ── Send helper ───────────────────────────────────────────────────────

    async def _send(self, data: bytes, to_node: str, attempt: int = 0) -> None:
        """Send packet respecting hop_limit strategy."""
        hop_limit = HOP_LIMIT_DIRECT if attempt < HOP_SWITCH_AT else HOP_LIMIT_MESH
        try:
            decoded = self.protocol.decode(data)
            if self._coordinator and self._coordinator.packet_store:
                self._coordinator.packet_store.add_tx(to_node, data, decoded, hop_limit, attempt)
        except Exception:
            pass
        await self.hass.async_add_executor_job(
            self.client.send, data, to_node, hop_limit
        )
        if self._coordinator:
            self._coordinator._update_sensors()

    def _compute_cfgh(self) -> str:
        """Compute config hash for current registry state."""
        import hashlib, json
        mapping = {k: v["t"] for k, v in self.registry.devices.items()}
        payload = json.dumps(
            {"ar": list(self.registry.areas.keys()), "mpg": mapping},
            sort_keys=True
        )
        return hashlib.md5(payload.encode()).hexdigest()[:8]

"""Device registry — hashing, mapping, areas."""
from __future__ import annotations

import hashlib
import json
import logging
from homeassistant.core import HomeAssistant

from .const import (
    DOMAIN_TO_TYPE,
    HASH_LENGTH,
    HASH_LENGTH_FALLBACK,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_KEY,
    CONF_UPDATE_INTERVAL,
    CONF_PUSH_ENABLED,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)

# Material icon names per HA area (fallback to "home")
AREA_ICONS = {
    "salon": "weekend",
    "living": "weekend",
    "bedroom": "bed",
    "kitchen": "kitchen",
    "bathroom": "bathtub",
    "hallway": "door_front",
    "tech": "build",
    "garage": "garage",
    "garden": "yard",
    "office": "computer",
}


def _make_hash(entity_id: str, length: int = HASH_LENGTH) -> str:
    return hashlib.md5(entity_id.encode()).hexdigest()[:length]


class DeviceRegistry:
    """Manages device hashes, mapping and area info."""

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self.devices: dict[str, dict] = {}   # hash → device info
        self.areas: dict[str, dict] = {}      # area_id → area info
        self._entity_to_hash: dict[str, str] = {}

    def build(self, selected_entities: list[str]) -> None:
        """Build registry from list of selected entity IDs."""
        self.devices = {}
        self._entity_to_hash = {}
        seen_hashes: dict[str, str] = {}  # hash → entity_id (for collision check)

        # Load areas from HA area registry
        self._load_areas()

        for raw in selected_entities:
            # selected may be "entity_id (friendly name)" format from config flow
            entity_id = raw.split(" (")[0].strip()

            domain = entity_id.split(".")[0]
            device_type = DOMAIN_TO_TYPE.get(domain)
            if not device_type:
                _LOGGER.warning("LoRemote: unsupported domain %s, skipping", domain)
                continue

            # Generate hash, check for collisions
            length = HASH_LENGTH
            short_id = _make_hash(entity_id, length)
            if short_id in seen_hashes and seen_hashes[short_id] != entity_id:
                _LOGGER.warning(
                    "LoRemote: hash collision %s for %s and %s, using length %d",
                    short_id, entity_id, seen_hashes[short_id], HASH_LENGTH_FALLBACK
                )
                # Re-hash both with longer length
                old_entity = seen_hashes[short_id]
                old_hash = _make_hash(old_entity, HASH_LENGTH_FALLBACK)
                new_hash = _make_hash(entity_id, HASH_LENGTH_FALLBACK)

                # Update existing entry
                if short_id in self.devices:
                    self.devices[old_hash] = self.devices.pop(short_id)
                    self._entity_to_hash[old_entity] = old_hash

                short_id = new_hash
                length = HASH_LENGTH_FALLBACK

            seen_hashes[short_id] = entity_id

            # Get friendly name and area
            state = self.hass.states.get(entity_id)
            friendly_name = (
                state.attributes.get("friendly_name", entity_id)
                if state else entity_id
            )
            unit = (
                state.attributes.get("unit_of_measurement")
                if state else None
            )

            # Find area for this entity
            area_id = self._get_entity_area(entity_id)

            self.devices[short_id] = {
                "entity_id": entity_id,
                "t": device_type,
                "n": friendly_name,
                "a": area_id,
                "u": unit,
            }
            self._entity_to_hash[entity_id] = short_id

        _LOGGER.info(
            "LoRemote: registry built — %d devices", len(self.devices)
        )

    def _load_areas(self) -> None:
        """Load areas from HA area registry."""
        self.areas = {}
        try:
            area_registry = self.hass.helpers.area_registry.async_get(self.hass)
            for area in area_registry.async_list_areas():
                icon = AREA_ICONS.get(area.id, AREA_ICONS.get(area.name.lower(), "home"))
                self.areas[area.id] = {
                    "id": area.id,
                    "n": area.name,
                    "ic": icon,
                    "ord": len(self.areas) + 1,
                }
        except Exception as e:
            _LOGGER.warning("LoRemote: cannot load areas: %s", e)

    def _get_entity_area(self, entity_id: str) -> str | None:
        """Get area ID for entity."""
        try:
            er = self.hass.helpers.entity_registry.async_get(self.hass)
            entry = er.async_get(entity_id)
            if entry and entry.area_id:
                return entry.area_id
            # Fall back to device area
            if entry and entry.device_id:
                dr = self.hass.helpers.device_registry.async_get(self.hass)
                device = dr.async_get(entry.device_id)
                if device and device.area_id:
                    return device.area_id
        except Exception:
            pass
        return None

    def get_hash(self, entity_id: str) -> str | None:
        """Get short hash for entity_id."""
        return self._entity_to_hash.get(entity_id)

    def get_device(self, short_id: str) -> dict | None:
        """Get device info by hash."""
        return self.devices.get(short_id)

    def build_export_config(self, integration_config: dict) -> dict:
        """Build full config JSON for HTML client export."""
        import hashlib, json

        mapping = {
            k: {kk: vv for kk, vv in v.items() if kk != "entity_id"}
            for k, v in self.devices.items()
        }

        areas_list = sorted(self.areas.values(), key=lambda a: a["ord"])

        # Compute config hash (areas + devices + mapping)
        payload = json.dumps(
            {"ar": areas_list, "dev": list(self.devices.keys()), "mpg": mapping},
            sort_keys=True
        )
        cfgh = hashlib.md5(payload.encode()).hexdigest()[:8]

        return {
            "n": integration_config.get("name", "Мой дом"),
            "tz": "Europe/Moscow",
            "gw": integration_config.get("node_id", ""),
            "ch": integration_config.get(CONF_CHANNEL_NAME, "LongFast"),
            "key": integration_config.get(CONF_CHANNEL_KEY, "AQ=="),
            "upd": integration_config.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            "psh": int(integration_config.get(CONF_PUSH_ENABLED, True)),
            "cfgh": cfgh,
            "usr": [],  # populated by user manager
            "ar": areas_list,
            "mpg": mapping,
        }

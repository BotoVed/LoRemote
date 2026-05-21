"""LoRemote sensors — expose integration state to HA."""
from __future__ import annotations

import json
import logging
from datetime import datetime
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

SENSORS = [
    "status",           # online / offline
    "node_id",          # !077ccb09
    "devices_count",    # 11
    "uptime_24h",       # 94 (%)
    "conn_history",     # JSON список событий подключения
    "last_rx",          # JSON последнего входящего пакета
    "last_tx",          # JSON последнего исходящего пакета
    "packet_log",       # JSON последних 50 пакетов
    "sessions",         # JSON последних сессий пользователей
]

async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]
    entities = [LoRemoteSensor(coordinator, entry, key) for key in SENSORS]
    async_add_entities(entities)
    coordinator.set_sensor_entities(
        {s.key: s for s in entities}
    )


class LoRemoteSensor(SensorEntity):
    def __init__(self, coordinator, entry, key):
        self._coordinator = coordinator
        self._entry = entry
        self.key = key
        self._attr_unique_id = f"loremote_{entry.entry_id}_{key}"
        self._attr_name = f"LoRemote {key.replace('_', ' ')}"
        self._attr_native_value = None
        self._attr_should_poll = False

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "LoRemote",
            "manufacturer": "LoRemote",
            "model": "T114 Gateway",
        }

    def set_value(self, value):
        self._attr_native_value = value
        self.schedule_update_ha_state()

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
    # Сенсоры с длинными JSON значениями — хранить в attributes
    JSON_SENSORS = {
        "conn_history", "packet_log", "sessions", "last_rx", "last_tx"
    }

    def __init__(self, coordinator, entry, key):
        self._coordinator = coordinator
        self._entry = entry
        self.key = key
        self._attr_unique_id = f"loremote_{entry.entry_id}_{key}"
        self._attr_name = f"LoRemote {key.replace('_', ' ')}"
        self._native_val = None
        self._json_val = None
        self._attr_should_poll = False

    @property
    def native_value(self):
        if self.key in self.JSON_SENSORS:
            # Для JSON сенсоров показываем количество записей
            if self._json_val:
                try:
                    import json
                    data = json.loads(self._json_val)
                    if isinstance(data, list):
                        return len(data)
                    return "ok"
                except Exception:
                    return "error"
            return 0
        return self._native_val

    @property
    def extra_state_attributes(self):
        if self.key in self.JSON_SENSORS and self._json_val:
            try:
                import json
                return {"data": json.loads(self._json_val)}
            except Exception:
                return {"raw": self._json_val}
        return {}

    @property
    def device_info(self):
        return {
            "identifiers": {(DOMAIN, self._entry.entry_id)},
            "name": "LoRemote",
            "manufacturer": "LoRemote",
            "model": "T114 Gateway",
        }

    def set_value(self, value):
        if self.key in self.JSON_SENSORS:
            if value and len(str(value)) > 15000:
                try:
                    import json as _json
                    data = _json.loads(value)
                    if isinstance(data, list):
                        value = _json.dumps(data[:len(data)//2])
                except Exception:
                    pass
            self._json_val = value
        else:
            self._native_val = value
        self.schedule_update_ha_state()

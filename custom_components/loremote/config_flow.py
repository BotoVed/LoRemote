"""Config flow for LoRemote integration."""
from __future__ import annotations

import glob
import hashlib
import json
import logging

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectOptionDict,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    DOMAIN,
    CONF_SERIAL_PORT,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_KEY,
    CONF_UPDATE_INTERVAL,
    CONF_PUSH_ENABLED,
    CONF_SELECTED_ENTITIES,
    CONF_HOME_NAME,
    SUPPORTED_DOMAINS,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_CHANNEL_KEY,
    MESHTASTIC_PRESETS,
)

_LOGGER = logging.getLogger(__name__)


def _detect_serial_ports() -> list[str]:
    ports = []
    for pattern in ["/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
        ports.extend(glob.glob(pattern))
    return sorted(ports) or ["/dev/ttyUSB0"]


def _flatten_entities(user_input: dict) -> list[str]:
    """Собрать все entity_id из полей entities_* в плоский список."""
    result = []
    for key, value in user_input.items():
        if key.startswith("entities_") and isinstance(value, list):
            result.extend(value)
    return result


def _group_by_domain(entity_ids: list[str]) -> dict[str, list[str]]:
    """Разбить плоский список entity_id по доменам."""
    result = {}
    for eid in entity_ids:
        domain = eid.split(".")[0]
        result.setdefault(domain, []).append(eid)
    return result


def _make_devices_schema(current_by_domain: dict) -> vol.Schema:
    """Схема выбора устройств — отдельный EntitySelector на каждый домен."""
    domain_labels = {
        "light": "💡 Освещение",
        "switch": "🔌 Переключатели",
        "climate": "❄️ Климат",
        "water_heater": "🚿 Водонагреватели",
        "fan": "💨 Вентиляторы",
        "cover": "🪟 Жалюзи и шторы",
        "lock": "🔒 Замки",
        "binary_sensor": "🔔 Двоичные датчики",
        "sensor": "🌡️ Датчики",
        "siren": "🚨 Сирены",
        "button": "🔘 Кнопки",
        "scene": "🎭 Сцены",
        "alarm_control_panel": "🛡️ Сигнализация",
        "humidifier": "💧 Увлажнители",
    }
    fields = {}
    for domain in SUPPORTED_DOMAINS:
        fields[vol.Optional(
            f"entities_{domain}",
            default=current_by_domain.get(domain, []),
            description={"suggested_value": current_by_domain.get(domain, [])},
        )] = EntitySelector(EntitySelectorConfig(domain=domain, multiple=True))
    return vol.Schema(fields)


class LoRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle LoRemote config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Шаг 1: основные настройки + порт."""
        errors = {}

        if user_input is not None:
            try:
                from .meshtastic_client import test_connection
                node_id = await self.hass.async_add_executor_job(
                    test_connection, user_input[CONF_SERIAL_PORT]
                )
                user_input["node_id"] = node_id
                self._config = user_input
                return await self.async_step_devices()
            except Exception as e:
                _LOGGER.error("Cannot connect to T114: %s", e)
                errors["base"] = "cannot_connect"

        ports = await self.hass.async_add_executor_job(_detect_serial_ports)

        schema = vol.Schema({
            vol.Optional(CONF_HOME_NAME, default="Мой дом"): str,
            vol.Required(CONF_SERIAL_PORT, default=ports[0]): vol.In(ports),
            vol.Required(CONF_CHANNEL_NAME, default="LongFast"): SelectSelector(
                SelectSelectorConfig(options=[
                    SelectOptionDict(value=p, label=p)
                    for p in MESHTASTIC_PRESETS
                ])
            ),
            vol.Required(CONF_CHANNEL_KEY, default=DEFAULT_CHANNEL_KEY): str,
            vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): int,
            vol.Optional(CONF_PUSH_ENABLED, default=True): bool,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Шаг 2: выбор устройств по доменам."""
        if user_input is not None:
            self._config[CONF_SELECTED_ENTITIES] = _flatten_entities(user_input)
            return self.async_create_entry(
                title=self._config.get(CONF_HOME_NAME, "LoRemote"),
                data=self._config,
            )

        schema = _make_devices_schema({})
        return self.async_show_form(step_id="devices", data_schema=schema)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LoRemoteOptionsFlow()


class LoRemoteOptionsFlow(config_entries.OptionsFlow):
    """Handle LoRemote options."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "general": "🏠 Основные настройки",
                "channel": "📡 Канал",
                "devices": "💡 Устройства",
                "users_menu": "👥 Пользователи",
                "export": "📋 Экспорт конфига",
            },
        )

    # ── Основные настройки ────────────────────────────────────────────────

    async def async_step_general(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def _get(key, default):
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        schema = vol.Schema({
            vol.Optional(CONF_HOME_NAME, default=_get(CONF_HOME_NAME, "Мой дом")): str,
            vol.Optional(CONF_UPDATE_INTERVAL,
                default=_get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): int,
            vol.Optional(CONF_PUSH_ENABLED,
                default=_get(CONF_PUSH_ENABLED, True)): bool,
        })
        return self.async_show_form(step_id="general", data_schema=schema)

    # ── Канал ─────────────────────────────────────────────────────────────

    async def async_step_channel(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def _get(key, default):
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        schema = vol.Schema({
            vol.Required(CONF_CHANNEL_NAME,
                default=_get(CONF_CHANNEL_NAME, "LongFast")): SelectSelector(
                SelectSelectorConfig(options=[
                    SelectOptionDict(value=p, label=p)
                    for p in MESHTASTIC_PRESETS
                ])
            ),
            vol.Required(CONF_CHANNEL_KEY,
                default=_get(CONF_CHANNEL_KEY, DEFAULT_CHANNEL_KEY)): str,
        })
        return self.async_show_form(step_id="channel", data_schema=schema)

    # ── Устройства ────────────────────────────────────────────────────────

    async def async_step_devices(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_SELECTED_ENTITIES: _flatten_entities(user_input)},
            )

        raw_current = self.config_entry.options.get(
            CONF_SELECTED_ENTITIES,
            self.config_entry.data.get(CONF_SELECTED_ENTITIES, [])
        )
        current_by_domain = _group_by_domain(raw_current)
        schema = _make_devices_schema(current_by_domain)
        return self.async_show_form(step_id="devices", data_schema=schema)

    # ── Пользователи — меню ───────────────────────────────────────────────

    async def async_step_users_menu(self, user_input=None) -> FlowResult:
        return self.async_show_menu(
            step_id="users_menu",
            menu_options={
                "users_add": "➕ Добавить пользователя",
                "users_edit": "✏️ Редактировать пользователя",
                "users_delete": "🗑️ Удалить пользователей",
            },
        )

    def _get_users(self) -> list[dict]:
        return list(self.config_entry.options.get(
            "users", self.config_entry.data.get("users", [])
        ))

    def _save_users(self, users: list[dict]) -> FlowResult:
        return self.async_create_entry(title="", data={"users": users})

    async def async_step_users_add(self, user_input=None) -> FlowResult:
        if user_input is not None:
            users = self._get_users()
            new_user = {
                "id": f"u{len(users) + 1}",
                "n": user_input["username"],
                "h": hashlib.sha256(
                    user_input["password"].encode()
                ).hexdigest()[:8],
                "rol": user_input["role"],
            }
            users.append(new_user)
            return self._save_users(users)

        users = self._get_users()
        users_text = "\n".join(
            f"• {u['n']} ({u['rol']})" for u in users
        ) or "Нет пользователей"

        schema = vol.Schema({
            vol.Required("username"): str,
            vol.Required("password"): str,
            vol.Required("role", default="adm"): SelectSelector(
                SelectSelectorConfig(options=[
                    SelectOptionDict(value="adm", label="Администратор"),
                    SelectOptionDict(value="viw", label="Только просмотр"),
                ])
            ),
        })
        return self.async_show_form(
            step_id="users_add",
            data_schema=schema,
            description_placeholders={"users_list": users_text},
        )

    async def async_step_users_delete(self, user_input=None) -> FlowResult:
        users = self._get_users()
        if not users:
            return self.async_abort(reason="no_users")

        if user_input is not None:
            ids_to_delete = user_input.get("user_ids", [])
            users = [u for u in users if u["id"] not in ids_to_delete]
            return self._save_users(users)

        options = [
            SelectOptionDict(value=u["id"], label=f"{u['n']} ({u['rol']})")
            for u in users
        ]
        schema = vol.Schema({
            vol.Required("user_ids"): SelectSelector(
                SelectSelectorConfig(options=options, multiple=True)
            ),
        })
        return self.async_show_form(step_id="users_delete", data_schema=schema)

    async def async_step_users_edit(self, user_input=None) -> FlowResult:
        users = self._get_users()
        if not users:
            return self.async_abort(reason="no_users")

        # Шаг 1 — выбрать пользователя
        if not hasattr(self, "_edit_user_id"):
            if user_input is not None:
                self._edit_user_id = user_input["user_id"]
                return await self.async_step_users_edit()

            options = [
                SelectOptionDict(value=u["id"], label=f"{u['n']} ({u['rol']})")
                for u in users
            ]
            schema = vol.Schema({
                vol.Required("user_id"): SelectSelector(
                    SelectSelectorConfig(options=options)
                ),
            })
            return self.async_show_form(
                step_id="users_edit", data_schema=schema
            )

        # Шаг 2 — редактировать выбранного
        user = next((u for u in users if u["id"] == self._edit_user_id), None)
        if not user:
            return self.async_abort(reason="user_not_found")

        if user_input is not None:
            for u in users:
                if u["id"] == self._edit_user_id:
                    u["n"] = user_input["username"]
                    u["rol"] = user_input["role"]
                    if user_input.get("password"):
                        u["h"] = hashlib.sha256(
                            user_input["password"].encode()
                        ).hexdigest()[:8]
            del self._edit_user_id
            return self._save_users(users)

        schema = vol.Schema({
            vol.Required("username", default=user["n"]): str,
            vol.Optional("password", default=""): str,
            vol.Required("role", default=user["rol"]): SelectSelector(
                SelectSelectorConfig(options=[
                    SelectOptionDict(value="adm", label="Администратор"),
                    SelectOptionDict(value="viw", label="Только просмотр"),
                ])
            ),
        })
        return self.async_show_form(
            step_id="users_edit",
            data_schema=schema,
            description_placeholders={"username": user["n"]},
        )

    # ── Экспорт конфига ───────────────────────────────────────────────────

    async def async_step_export(self, user_input=None) -> FlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data={})

        coordinator = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id
        )
        if coordinator:
            config = coordinator.get_export_config()
            config_json = json.dumps(config, ensure_ascii=False, indent=2)
            export_text = f"window.LORA_CONFIG = {config_json};"
        else:
            export_text = "Ошибка: интеграция не запущена"

        schema = vol.Schema({
            vol.Optional("config_export", default=export_text): TextSelector(
                TextSelectorConfig(
                    multiline=True,
                    type=TextSelectorType.TEXT,
                )
            ),
        })
        return self.async_show_form(
            step_id="export",
            data_schema=schema,
        )

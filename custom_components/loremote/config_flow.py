"""Config flow for LoRemote integration."""
from __future__ import annotations

import glob
import hashlib
import logging

import voluptuous as vol
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.selector import (
    EntitySelectorConfig,
    EntitySelector,
    SelectSelector,
    SelectSelectorConfig,
    SelectOptionDict,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    CONF_SERIAL_PORT,
    CONF_CHANNEL_NAME,
    CONF_CHANNEL_KEY,
    CONF_UPDATE_INTERVAL,
    CONF_PUSH_ENABLED,
    CONF_SELECTED_ENTITIES,
    SUPPORTED_DOMAINS,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _detect_serial_ports() -> list[str]:
    ports = []
    for pattern in ["/dev/serial/by-id/*", "/dev/ttyUSB*", "/dev/ttyACM*"]:
        ports.extend(glob.glob(pattern))
    return sorted(ports) or ["/dev/ttyUSB0"]


def _flatten_entities(user_input: dict) -> list[str]:
    result = []
    for key, value in user_input.items():
        if key.startswith("entities_") and isinstance(value, list):
            result.extend(value)
    return result


def _group_by_domain(entity_ids: list[str]) -> dict[str, list[str]]:
    result = {}
    for eid in entity_ids:
        domain = eid.split(".")[0]
        result.setdefault(domain, []).append(eid)
    return result


def _get_domain_schema(defaults: dict[str, list[str]]) -> vol.Schema:
    """Build schema with entity selector per domain."""
    fields = {}
    for domain in SUPPORTED_DOMAINS:
        key = f"entities_{domain}"
        fields[vol.Optional(key, default=defaults.get(domain, []))] = EntitySelector(
            EntitySelectorConfig(domain=domain, multiple=True),
        )
    return vol.Schema(fields)


class LoRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle LoRemote config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Serial port + channel settings."""
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
            vol.Required(CONF_SERIAL_PORT, default=ports[0]): vol.In(ports),
            vol.Required(CONF_CHANNEL_NAME, default="LongFast"): str,
            vol.Required(CONF_CHANNEL_KEY, default="AQ=="): str,
            vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): int,
            vol.Optional(CONF_PUSH_ENABLED, default=True): bool,
            vol.Optional("name", default="Мой дом"): str,
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Step 2: Select entities."""
        if user_input is not None:
            self._config[CONF_SELECTED_ENTITIES] = _flatten_entities(user_input)
            return self.async_create_entry(
                title=f"LoRemote ({self._config[CONF_SERIAL_PORT].split('/')[-1]})",
                data=self._config,
            )

        schema = _get_domain_schema({})

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return options flow."""
        return LoRemoteOptionsFlow()


class LoRemoteOptionsFlow(config_entries.OptionsFlow):
    """Handle LoRemote options."""

    async def async_step_init(self, user_input=None) -> FlowResult:
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options={
                "devices": "Управление устройствами",
                "channel": "Настройки канала",
                "users": "Пользователи",
                "export": "Экспорт конфига",
            },
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Manage selected devices."""
        if user_input is not None:
            return self.async_create_entry(
                title="",
                data={CONF_SELECTED_ENTITIES: _flatten_entities(user_input)},
            )
        raw_current = self.config_entry.options.get(
            CONF_SELECTED_ENTITIES,
            self.config_entry.data.get(CONF_SELECTED_ENTITIES, [])
        )
        defaults = _group_by_domain(raw_current)
        schema = _get_domain_schema(defaults)

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
        )

    async def async_step_channel(self, user_input=None) -> FlowResult:
        """Edit channel settings."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        def _get(key, default):
            return self.config_entry.options.get(
                key, self.config_entry.data.get(key, default)
            )

        schema = vol.Schema({
            vol.Required(
                CONF_CHANNEL_NAME,
                default=_get(CONF_CHANNEL_NAME, "LongFast"),
            ): str,
            vol.Required(
                CONF_CHANNEL_KEY,
                default=_get(CONF_CHANNEL_KEY, "AQ=="),
            ): str,
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=_get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): int,
            vol.Optional(
                CONF_PUSH_ENABLED,
                default=_get(CONF_PUSH_ENABLED, True),
            ): bool,
        })

        return self.async_show_form(
            step_id="channel",
            data_schema=schema,
        )

    async def async_step_users(self, user_input=None) -> FlowResult:
        """Manage users."""
        if user_input is not None:
            users = self.config_entry.options.get("users",
                    self.config_entry.data.get("users", []))
            new_user = {
                "id": f"u{len(users)+1}",
                "n": user_input["username"],
                "h": hashlib.sha256(
                    user_input["password"].encode()
                ).hexdigest()[:8],
                "rol": user_input["role"],
            }
            users = list(users) + [new_user]
            return self.async_create_entry(title="", data={"users": users})

        from homeassistant.helpers.selector import (
            SelectSelector, SelectSelectorConfig, SelectOptionDict
        )

        current_users = self.config_entry.options.get("users",
                        self.config_entry.data.get("users", []))

        users_list = "\n".join(
            f"• {u['n']} ({u['rol']})" for u in current_users
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
            step_id="users",
            data_schema=schema,
            description_placeholders={"users_list": users_list},
        )

    async def async_step_export(self, user_input=None) -> FlowResult:
        """Export config for HTML client."""
        import json

        coordinator = self.hass.data[DOMAIN].get(self.config_entry.entry_id)
        if coordinator:
            config = coordinator.get_export_config()
            config_json = json.dumps(config, ensure_ascii=False, indent=2)
            export_text = f"window.LORA_CONFIG = {config_json};"
        else:
            export_text = "Ошибка: интеграция не запущена"

        if user_input is not None:
            return self.async_create_entry(title="", data={})

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
            description_placeholders={},
        )

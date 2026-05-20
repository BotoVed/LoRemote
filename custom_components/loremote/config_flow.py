"""Config flow for LoRemote integration."""
from __future__ import annotations

import glob
import logging

import voluptuous as vol
import homeassistant.helpers.config_validation as cv

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


def _get_all_entities(hass) -> dict[str, str]:
    """Return dict of {entity_id: label} for all supported entities."""
    result = {}
    for state in hass.states.async_all():
        domain = state.entity_id.split(".")[0]
        if domain in SUPPORTED_DOMAINS:
            friendly = state.attributes.get("friendly_name", state.entity_id)
            label = f"[{domain}] {friendly}"
            result[state.entity_id] = label
    return result


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
        })

        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Step 2: Select entities."""
        if user_input is not None:
            self._config[CONF_SELECTED_ENTITIES] = user_input.get("entities", [])
            return self.async_create_entry(
                title=f"LoRemote ({self._config[CONF_SERIAL_PORT].split('/')[-1]})",
                data=self._config,
            )

        all_entities = _get_all_entities(self.hass)

        schema = vol.Schema({
            vol.Optional("entities", default=[]): cv.multi_select(all_entities),
        })

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
            },
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Manage selected devices."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data,
                      CONF_SELECTED_ENTITIES: user_input.get("entities", [])},
            )
            return self.async_create_entry(title="", data={})

        all_entities = _get_all_entities(self.hass)
        raw_current = self.config_entry.data.get(CONF_SELECTED_ENTITIES, [])
        current = [e for e in raw_current if e in all_entities]

        schema = vol.Schema({
            vol.Optional("entities", default=current): cv.multi_select(all_entities),
        })

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
        )

    async def async_step_channel(self, user_input=None) -> FlowResult:
        """Edit channel settings."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry,
                data={**self.config_entry.data, **user_input},
            )
            return self.async_create_entry(title="", data={})

        data = self.config_entry.data
        schema = vol.Schema({
            vol.Required(
                CONF_CHANNEL_NAME,
                default=data.get(CONF_CHANNEL_NAME, "LongFast"),
            ): str,
            vol.Required(
                CONF_CHANNEL_KEY,
                default=data.get(CONF_CHANNEL_KEY, "AQ=="),
            ): str,
            vol.Optional(
                CONF_UPDATE_INTERVAL,
                default=data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            ): int,
            vol.Optional(
                CONF_PUSH_ENABLED,
                default=data.get(CONF_PUSH_ENABLED, True),
            ): bool,
        })

        return self.async_show_form(
            step_id="channel",
            data_schema=schema,
        )

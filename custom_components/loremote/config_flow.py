"""Config flow for LoRemote integration."""
from __future__ import annotations

import logging
import glob
import voluptuous as vol

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
    CONF_ENTITY_NAMES,
    SUPPORTED_DOMAINS,
    DEFAULT_UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def _detect_serial_ports() -> list[str]:
    """Detect available serial ports."""
    ports = []
    for pattern in ["/dev/ttyUSB*", "/dev/ttyACM*", "/dev/serial/by-id/*"]:
        ports.extend(glob.glob(pattern))
    return sorted(ports) or ["/dev/ttyUSB0"]


class LoRemoteConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle LoRemote config flow."""

    VERSION = 1

    async def async_step_user(self, user_input=None) -> FlowResult:
        """Step 1: Serial port + channel settings."""
        errors = {}

        if user_input is not None:
            # Try to connect to T114
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
            description_placeholders={
                "detected_ports": ", ".join(ports)
            }
        )

    async def async_step_devices(self, user_input=None) -> FlowResult:
        """Step 2: Select entities to expose via LoRa."""
        if user_input is not None:
            self._config[CONF_SELECTED_ENTITIES] = user_input.get("entities", [])
            self._config[CONF_ENTITY_NAMES] = {}
            return self.async_create_entry(
                title=f"LoRemote ({self._config[CONF_SERIAL_PORT]})",
                data=self._config,
            )

        # Build entity list grouped by domain
        all_states = self.hass.states.async_all()
        entities_by_domain = {}
        for state in all_states:
            domain = state.entity_id.split(".")[0]
            if domain in SUPPORTED_DOMAINS:
                entities_by_domain.setdefault(domain, [])
                friendly = state.attributes.get("friendly_name", state.entity_id)
                entities_by_domain[domain].append(
                    f"{state.entity_id} ({friendly})"
                )

        # Flatten for multi-select
        all_entities = []
        for domain in SUPPORTED_DOMAINS:
            all_entities.extend(entities_by_domain.get(domain, []))

        schema = vol.Schema({
            vol.Optional("entities", default=[]): vol.All(
                vol.In(all_entities), [str]
            )
        })

        return self.async_show_form(
            step_id="devices",
            data_schema=schema,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return LoRemoteOptionsFlow(config_entry)


class LoRemoteOptionsFlow(config_entries.OptionsFlow):
    """Handle LoRemote options (reconfigure after setup)."""

    def __init__(self, config_entry):
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Show options menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["devices", "channel", "users", "export"],
        )

    async def async_step_devices(self, user_input=None):
        """Manage selected devices."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(CONF_SELECTED_ENTITIES, [])
        all_states = self.hass.states.async_all()
        all_entities = []
        for state in all_states:
            domain = state.entity_id.split(".")[0]
            if domain in SUPPORTED_DOMAINS:
                friendly = state.attributes.get("friendly_name", state.entity_id)
                all_entities.append(f"{state.entity_id} ({friendly})")

        schema = vol.Schema({
            vol.Optional("entities", default=current): cv.multi_select(
                {e: e for e in all_entities}
            )
        })
        return self.async_show_form(step_id="devices", data_schema=schema)

    async def async_step_channel(self, user_input=None):
        """Edit channel settings."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        schema = vol.Schema({
            vol.Required(CONF_CHANNEL_NAME,
                default=self.config_entry.data.get(CONF_CHANNEL_NAME, "LongFast")): str,
            vol.Required(CONF_CHANNEL_KEY,
                default=self.config_entry.data.get(CONF_CHANNEL_KEY, "AQ==")): str,
            vol.Optional(CONF_UPDATE_INTERVAL,
                default=self.config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)): int,
            vol.Optional(CONF_PUSH_ENABLED,
                default=self.config_entry.data.get(CONF_PUSH_ENABLED, True)): bool,
        })
        return self.async_show_form(step_id="channel", data_schema=schema)

    async def async_step_users(self, user_input=None):
        """Manage users — placeholder, shown as info panel."""
        # User management via separate service call in full implementation
        return self.async_abort(reason="users_not_implemented_yet")

    async def async_step_export(self, user_input=None):
        """Export config for HTML client — handled by coordinator."""
        return self.async_abort(reason="use_export_panel")

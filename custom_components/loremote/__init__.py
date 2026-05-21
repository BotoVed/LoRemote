"""LoRemote — Home Assistant over LoRa/Meshtastic."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import LoRemoteCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up LoRemote from a config entry."""
    import logging as _logging
    _logging.getLogger("custom_components.loremote").setLevel(_logging.DEBUG)
    _LOGGER.info("Setting up LoRemote integration")

    coordinator = LoRemoteCoordinator(hass, entry)
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    await coordinator.async_start()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload LoRemote config entry."""
    await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: LoRemoteCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
    await coordinator.async_stop()
    return True


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload LoRemote when config changes."""
    await async_unload_entry(hass, entry)
    await async_setup_entry(hass, entry)

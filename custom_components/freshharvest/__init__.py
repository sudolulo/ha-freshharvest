"""The Fresh Harvest integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_create_clientsession

from .api import FreshHarvestClient
from .coordinator import FreshHarvestCoordinator

PLATFORMS: list[Platform] = [Platform.SENSOR]

type FreshHarvestConfigEntry = ConfigEntry[FreshHarvestCoordinator]


async def async_setup_entry(
    hass: HomeAssistant, entry: FreshHarvestConfigEntry
) -> bool:
    """Set up Fresh Harvest from a config entry."""
    # Dedicated session: the login tokens are bound to its cookie jar.
    session = async_create_clientsession(hass)
    client = FreshHarvestClient(
        session, entry.data[CONF_EMAIL], entry.data[CONF_PASSWORD]
    )

    coordinator = FreshHarvestCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: FreshHarvestConfigEntry
) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

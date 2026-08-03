"""Polling coordinator for Fresh Harvest."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AccountSnapshot,
    FreshHarvestAuthError,
    FreshHarvestClient,
    FreshHarvestError,
)
from .const import DOMAIN, UPDATE_INTERVAL

_LOGGER = logging.getLogger(__name__)


class FreshHarvestCoordinator(DataUpdateCoordinator[AccountSnapshot]):
    """Fetch the account dashboard on a slow interval."""

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, client: FreshHarvestClient
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=UPDATE_INTERVAL,
            config_entry=entry,
        )
        self.client = client

    async def _async_update_data(self) -> AccountSnapshot:
        try:
            return await self.client.async_get_snapshot()
        except FreshHarvestAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FreshHarvestError as err:
            raise UpdateFailed(str(err)) from err

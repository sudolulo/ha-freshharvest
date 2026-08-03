"""Polling coordinator for Fresh Harvest."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .actions import FreshHarvestActions
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
        self.actions = FreshHarvestActions(client)

    async def _async_update_data(self) -> AccountSnapshot:
        try:
            snapshot = await self.client.async_get_snapshot()
            # Two extra pages per refresh, so three requests every six hours.
            snapshot.subscriptions = await self.actions.async_list_subscriptions()
            snapshot.vacation_holds = await self.actions.async_list_vacation_holds()
            return snapshot
        except FreshHarvestAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except FreshHarvestError as err:
            raise UpdateFailed(str(err)) from err

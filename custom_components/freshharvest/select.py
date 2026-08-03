"""Produce box selection.

Switching box is not adding an add-on: you change WHICH box arrives, not what
is inside it. A select fits that — one choice from a fixed set — where the
to-do list fits add-ons.

Selecting here changes the next delivery only. Changing the standing order is a
different, stickier operation and is left to the portal rather than being one
mis-click away from every future box.
"""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .api import FreshHarvestError
from .const import DOMAIN, EVENT_ACTION
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity

_LOGGER = logging.getLogger(__name__)

DESCRIPTION = SelectEntityDescription(
    key="produce_box",
    translation_key="produce_box",
    icon="mdi:package-variant-closed",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the select platform."""
    async_add_entities([FreshHarvestBoxSelect(entry.runtime_data, entry)])


class FreshHarvestBoxSelect(FreshHarvestEntity, SelectEntity):
    """Which produce box arrives next."""

    entity_description = DESCRIPTION

    def __init__(
        self, coordinator: FreshHarvestCoordinator, entry: FreshHarvestConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)
        self._entry = entry
        self._options: list[str] = []

    @property
    def current_option(self) -> str | None:
        """The subscribed box.

        Read from the subscription rather than the switch popups: the box you
        are on is the one the site offers no switch control for, so it has no
        name there.
        """
        subs = self.coordinator.data.subscriptions
        return subs[0].name if subs else None

    @property
    def options(self) -> list[str]:
        """Boxes on offer, plus whatever is current so the state is valid."""
        current = self.current_option
        opts = list(self._options)
        if current and current not in opts:
            opts.insert(0, current)
        return opts

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        # Listing costs a fetch per box popup, so it happens once on setup
        # rather than on every coordinator refresh.
        try:
            baskets = await self.coordinator.actions.async_list_baskets()
            self._options = [b.name for b in baskets]
        except FreshHarvestError as err:
            _LOGGER.warning("could not list produce boxes: %s", err)

    async def async_select_option(self, option: str) -> None:
        """Switch the next delivery to this box."""
        if option == self.current_option:
            return
        try:
            result = await self.coordinator.actions.async_change_basket(
                option, all_future=False, dry_run=False
            )
        except FreshHarvestError as err:
            self._fire(False, option, str(err))
            raise HomeAssistantError(f"could not switch to {option}: {err}") from err
        self._fire(True, option, result.detail)
        await self.coordinator.async_request_refresh()

    def _fire(self, ok: bool, target: str, detail: str) -> None:
        self.hass.bus.async_fire(
            EVENT_ACTION,
            {"domain": DOMAIN, "entry_id": self._entry.entry_id,
             "action": "change_basket", "success": ok, "target": target,
             "detail": detail},
        )

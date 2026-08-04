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
from .const import DOMAIN
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
        self._options: list[str] = []

    @property
    def current_option(self) -> str | None:
        """The box actually arriving in the changeable delivery.

        NOT the subscription. A one-off switch changes the delivery while the
        standing order keeps naming the old box — verified live: after
        switching the next delivery to Medium, the subscription still read
        Small. Reporting the subscription here would show the wrong box for
        exactly the week someone had changed it.
        """
        order = self.coordinator.data.open_order or self.coordinator.data.next_order
        if order is not None and order.box_name:
            return order.box_name
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
        # Listing the boxes on offer costs one fetch per box popup. Doing it
        # here inline blocked entity setup: on a slower connection those fetches
        # ran past Home Assistant's SLOW_SETUP_MAX_WAIT and the whole config
        # entry was cancelled into "setup_error", leaving every entity
        # unavailable despite valid credentials. It now runs once, in the
        # background — the entity comes up immediately with the current box as
        # its only option and the rest appear when the listing returns.
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self._async_load_options(), f"{DOMAIN}_list_baskets"
        )

    async def _async_load_options(self) -> None:
        """Fetch the switchable boxes once and publish them as options."""
        try:
            baskets = await self.coordinator.actions.async_list_baskets()
        except FreshHarvestError as err:
            _LOGGER.warning("could not list produce boxes: %s", err)
            return
        self._options = [b.name for b in baskets]
        self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Switch the next delivery to this box."""
        if option == self.current_option:
            return
        try:
            result = await self.coordinator.actions.async_change_basket(
                option, all_future=False, dry_run=False
            )
        except FreshHarvestError as err:
            self.fire_action("change_basket", False, option, str(err))
            raise HomeAssistantError(f"could not switch to {option}: {err}") from err
        self.fire_action("change_basket", True, option, result.detail)
        await self.coordinator.async_request_refresh()


"""Skip control for the upcoming delivery.

A switch rather than a button: skipped/not-skipped is state the conversation
agent can read back and reverse, where a button would be fire-and-forget.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .api import FreshHarvestError
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity

_LOGGER = logging.getLogger(__name__)

DESCRIPTION = SwitchEntityDescription(
    key="skip_open_order",
    translation_key="skip_open_order",
    icon="mdi:calendar-remove",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    async_add_entities([FreshHarvestSkip(entry.runtime_data, entry)])


class FreshHarvestSkip(FreshHarvestEntity, SwitchEntity):
    """On means the next changeable delivery is skipped."""

    entity_description = DESCRIPTION

    def __init__(
        self, coordinator: FreshHarvestCoordinator, entry: FreshHarvestConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)

    @property
    def available(self) -> bool:
        """Only meaningful while there is an order that can still be changed."""
        return super().available and self.coordinator.data.open_order is not None

    @property
    def is_on(self) -> bool:
        """A skipped order stops offering a shopping window."""
        order = self.coordinator.data.open_order
        return order is not None and not order.is_open

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Skip the next changeable delivery."""
        order = self.coordinator.data.open_order
        if order is None or order.delivery_date is None:
            raise HomeAssistantError("no delivery is currently skippable")
        try:
            result = await self.coordinator.actions.async_skip(
                order.delivery_date, dry_run=False
            )
        except FreshHarvestError as err:
            self.fire_action("skip", False, str(order.delivery_date), str(err))
            raise HomeAssistantError(f"could not skip: {err}") from err
        self.fire_action("skip", True, str(order.delivery_date), result.detail)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Un-skip the delivery."""
        order = self.coordinator.data.open_order
        if order is None or order.delivery_date is None:
            raise HomeAssistantError("no delivery to restore")
        try:
            result = await self.coordinator.actions.async_restore(
                order.delivery_date, dry_run=False
            )
        except FreshHarvestError as err:
            self.fire_action("restore", False, str(order.delivery_date), str(err))
            raise HomeAssistantError(f"could not restore: {err}") from err
        self.fire_action("restore", True, str(order.delivery_date), result.detail)
        await self.coordinator.async_request_refresh()


"""Binary sensors for Fresh Harvest."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity

DESCRIPTION = BinarySensorEntityDescription(
    key="order_open",
    translation_key="order_open",
    icon="mdi:cart-arrow-right",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the binary sensor platform."""
    async_add_entities([FreshHarvestOrderOpen(entry.runtime_data, entry)])


class FreshHarvestOrderOpen(FreshHarvestEntity, BinarySensorEntity):
    """Whether any upcoming order can still be changed.

    The single most useful thing to automate on: it goes off when the cutoff
    passes, which is the last moment to add something to the box.
    """

    entity_description = DESCRIPTION

    def __init__(
        self, coordinator: FreshHarvestCoordinator, entry: FreshHarvestConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)

    @property
    def is_on(self) -> bool:
        """Return true while an order is still customizable."""
        return self.target("open_order") is not None

    @property
    def extra_state_attributes(self) -> dict[str, str | None] | None:
        """Surface which order is open and until when."""
        order = self.target("open_order")
        if order is None:
            return None
        return {
            "delivery_date": order.delivery_date.isoformat()
            if order.delivery_date
            else None,
            "shop_window": order.shop_window,
        }

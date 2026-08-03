"""Sensors for Fresh Harvest.

Every part of an order is its own entity — box price, add-ons, tax, delivery
fee, subtotal and total — so an automation or dashboard can read any one of
them directly rather than digging through attributes.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .api import DeliveryOrder, OrderItem
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity, Scope

CURRENCY = "USD"


def format_item(item: OrderItem, with_price: bool = False) -> str:
    """Render one line, e.g. '4 Complete Recovery Smoothie 15.2 fl oz — $17.96'."""
    line = " ".join(
        part for part in (str(item.quantity or ""), item.name, item.unit) if part
    )
    if with_price and item.price is not None:
        line = f"{line} — ${item.price:,.2f}"
    return line


def _contents_attrs(order: DeliveryOrder) -> dict[str, Any]:
    return {
        "box": order.box_name,
        "produce": [format_item(i) for i in order.items],
        "add_ons": [format_item(a, with_price=True) for a in order.addons],
        "produce_count": len(order.items),
        "add_ons_count": len(order.addons),
    }


def _total_attrs(order: DeliveryOrder) -> dict[str, Any]:
    """Charges that are not worth their own entity: optional or promotional."""
    return {
        "driver_tip": order.driver_tip,
        "bounty_savings": order.bounty_savings,
    }


@dataclass(frozen=True, kw_only=True)
class FreshHarvestSensorDescription(SensorEntityDescription):
    """Describes a Fresh Harvest sensor."""

    scope: Scope = "next_order"
    value_fn: Callable[[Any], Any]
    attrs_fn: Callable[[Any], dict[str, Any]] | None = None


def _money(**kwargs) -> FreshHarvestSensorDescription:
    """A dollar amount. A helper because there are eight of them.

    Callers pass `translation_key` explicitly rather than deriving it from
    `key`, so the name of every entity stays greppable in this file — which is
    what `tests/test_translations.py` checks.
    """
    return FreshHarvestSensorDescription(
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement=CURRENCY,
        **kwargs,
    )


SENSORS: tuple[FreshHarvestSensorDescription, ...] = (
    # --- the account itself -------------------------------------------------
    FreshHarvestSensorDescription(
        key="next_delivery",
        translation_key="next_delivery",
        scope="account",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: s.next_delivery,
        attrs_fn=lambda s: {
            "delivery_day": s.delivery_day,
            "free_delivery_threshold": s.free_delivery_threshold,
        },
    ),
    FreshHarvestSensorDescription(
        key="delivery_day",
        translation_key="delivery_day",
        scope="account",
        icon="mdi:calendar-week",
        value_fn=lambda s: s.delivery_day,
    ),
    # --- the order arriving next --------------------------------------------
    _money(
        key="next_delivery_total",
        translation_key="next_delivery_total",
        value_fn=lambda o: o.total,
        attrs_fn=_total_attrs,
    ),
    _money(
        key="next_delivery_subtotal",
        translation_key="next_delivery_subtotal",
        value_fn=lambda o: o.subtotal,
    ),
    _money(
        key="next_delivery_box_price",
        translation_key="next_delivery_box_price",
        value_fn=lambda o: o.box_price,
    ),
    _money(
        key="next_delivery_add_ons",
        translation_key="next_delivery_add_ons",
        value_fn=lambda o: o.addons_total,
    ),
    _money(
        key="next_delivery_tax",
        translation_key="next_delivery_tax",
        value_fn=lambda o: o.tax,
    ),
    _money(
        key="next_delivery_delivery_fee",
        translation_key="next_delivery_delivery_fee",
        value_fn=lambda o: o.delivery_fee,
    ),
    FreshHarvestSensorDescription(
        key="next_delivery_items",
        translation_key="next_delivery_items",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="items",
        icon="mdi:basket-check",
        value_fn=lambda o: len(o.all_items),
        attrs_fn=_contents_attrs,
    ),
    # --- the order that can still be changed --------------------------------
    FreshHarvestSensorDescription(
        key="open_order_delivery",
        translation_key="open_order_delivery",
        scope="open_order",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda o: o.delivery_date,
        attrs_fn=lambda o: {"box": o.box_name},
    ),
    _money(
        key="open_order_total",
        translation_key="open_order_total",
        scope="open_order",
        value_fn=lambda o: o.total,
        attrs_fn=_total_attrs,
    ),
    _money(
        key="open_order_free_delivery_remaining",
        translation_key="open_order_free_delivery_remaining",
        scope="open_order",
        value_fn=lambda o: o.free_delivery_remaining,
    ),
    FreshHarvestSensorDescription(
        key="shop_window",
        translation_key="shop_window",
        scope="open_order",
        icon="mdi:clock-alert-outline",
        # Distinct from unknown: there genuinely is no changeable order.
        value_fn=lambda o: o.shop_window or "closed",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the sensor platform."""
    coordinator = entry.runtime_data
    async_add_entities(
        FreshHarvestSensor(coordinator, entry, description) for description in SENSORS
    )


class FreshHarvestSensor(FreshHarvestEntity, SensorEntity):
    """A value read off the Fresh Harvest dashboard."""

    entity_description: FreshHarvestSensorDescription

    def __init__(
        self,
        coordinator: FreshHarvestCoordinator,
        entry: FreshHarvestConfigEntry,
        description: FreshHarvestSensorDescription,
    ) -> None:
        super().__init__(coordinator, entry, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        """Return the sensor value, or None when its order does not exist."""
        target = self.target(self.entity_description.scope)
        if target is None:
            return None
        return self.entity_description.value_fn(target)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sensor's extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        target = self.target(self.entity_description.scope)
        if target is None:
            return None
        return self.entity_description.attrs_fn(target)

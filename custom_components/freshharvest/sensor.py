"""Sensors for Fresh Harvest."""

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
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FreshHarvestConfigEntry
from .api import AccountSnapshot, DeliveryOrder
from .const import DOMAIN
from .coordinator import FreshHarvestCoordinator


def _items_attrs(order: DeliveryOrder | None) -> dict[str, Any] | None:
    if order is None:
        return None
    return {
        "box": order.box_name,
        "produce": [
            " ".join(part for part in (str(i.quantity or ""), i.name, i.unit) if part)
            for i in order.items
        ],
        "add_ons": [a.name for a in order.addons],
    }


@dataclass(frozen=True, kw_only=True)
class FreshHarvestSensorDescription(SensorEntityDescription):
    """Describes a Fresh Harvest sensor."""

    value_fn: Callable[[AccountSnapshot], Any]
    attrs_fn: Callable[[AccountSnapshot], dict[str, Any] | None] | None = None


SENSORS: tuple[FreshHarvestSensorDescription, ...] = (
    FreshHarvestSensorDescription(
        key="next_delivery",
        translation_key="next_delivery",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: s.next_delivery,
        attrs_fn=lambda s: {
            "delivery_day": s.delivery_day,
            "box": s.next_order.box_name if s.next_order else None,
        },
    ),
    FreshHarvestSensorDescription(
        key="next_delivery_total",
        translation_key="next_delivery_total",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="USD",
        value_fn=lambda s: s.next_order.total if s.next_order else None,
        attrs_fn=lambda s: None
        if s.next_order is None
        else {
            "subtotal": s.next_order.subtotal,
            "tax": s.next_order.tax,
            "delivery_fee": s.next_order.delivery_fee,
        },
    ),
    FreshHarvestSensorDescription(
        key="next_delivery_items",
        translation_key="next_delivery_items",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="items",
        value_fn=lambda s: len(s.next_order.all_items) if s.next_order else None,
        attrs_fn=lambda s: _items_attrs(s.next_order),
    ),
    FreshHarvestSensorDescription(
        key="open_order_delivery",
        translation_key="open_order_delivery",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda s: s.open_order.delivery_date if s.open_order else None,
        attrs_fn=lambda s: None
        if s.open_order is None
        else {
            "total": s.open_order.total,
            "box": s.open_order.box_name,
        },
    ),
    FreshHarvestSensorDescription(
        key="shop_window",
        translation_key="shop_window",
        value_fn=lambda s: (s.open_order.shop_window if s.open_order else None)
        or "closed",
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


class FreshHarvestSensor(CoordinatorEntity[FreshHarvestCoordinator], SensorEntity):
    """A value read off the Fresh Harvest dashboard."""

    _attr_has_entity_name = True
    entity_description: FreshHarvestSensorDescription

    def __init__(
        self,
        coordinator: FreshHarvestCoordinator,
        entry: FreshHarvestConfigEntry,
        description: FreshHarvestSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fresh Harvest",
            manufacturer="Fresh Harvest",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://freshharvest.com/p/dashboard/details",
        )

    @property
    def native_value(self) -> Any:
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Return the sensor's extra attributes."""
        if self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data)

"""Sensors for Fresh Harvest."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import FreshHarvestConfigEntry
from .api import Delivery
from .const import DOMAIN
from .coordinator import FreshHarvestCoordinator


@dataclass(frozen=True, kw_only=True)
class FreshHarvestSensorDescription(SensorEntityDescription):
    """Describes a Fresh Harvest sensor."""

    value_fn: Callable[[Delivery], object]


SENSORS: tuple[FreshHarvestSensorDescription, ...] = (
    FreshHarvestSensorDescription(
        key="next_delivery",
        translation_key="next_delivery",
        device_class=SensorDeviceClass.DATE,
        value_fn=lambda d: d.delivery_date,
    ),
    FreshHarvestSensorDescription(
        key="order_total",
        translation_key="order_total",
        device_class=SensorDeviceClass.MONETARY,
        native_unit_of_measurement="USD",
        value_fn=lambda d: d.total,
    ),
    FreshHarvestSensorDescription(
        key="status",
        translation_key="status",
        value_fn=lambda d: d.status,
    ),
    FreshHarvestSensorDescription(
        key="item_count",
        translation_key="item_count",
        value_fn=lambda d: len(d.items) if d.items else None,
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
    """A value read off the Fresh Harvest portal."""

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
            configuration_url="https://freshharvest.com/",
        )

    @property
    def native_value(self):
        """Return the sensor value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, object] | None:
        """Expose box contents on the item-count sensor."""
        if self.entity_description.key != "item_count":
            return None
        return {"items": self.coordinator.data.items}

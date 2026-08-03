"""Shared entity plumbing for Fresh Harvest.

Entities read one of three things: the account as a whole, the order arriving
next, or the order that can still be changed. Declaring that as a `scope` keeps
each entity's `value_fn` down to the field it actually cares about, instead of
every one of them repeating the same None checks.
"""

from __future__ import annotations

from typing import Literal

from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import AccountSnapshot, DeliveryOrder
from .const import DOMAIN
from .coordinator import FreshHarvestCoordinator

Scope = Literal["account", "next_order", "open_order"]


def resolve_scope(
    snapshot: AccountSnapshot, scope: Scope
) -> AccountSnapshot | DeliveryOrder | None:
    """Return the object a scope points at, or None when there is no such order."""
    if scope == "account":
        return snapshot
    return getattr(snapshot, scope)


class FreshHarvestEntity(CoordinatorEntity[FreshHarvestCoordinator]):
    """Base for every Fresh Harvest entity."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: FreshHarvestCoordinator,
        entry: ConfigEntry,
        key: str,
    ) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Fresh Harvest",
            manufacturer="Fresh Harvest",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://freshharvest.com/p/dashboard/details",
        )

    def target(self, scope: Scope) -> AccountSnapshot | DeliveryOrder | None:
        """Resolve this entity's scope against the latest snapshot."""
        return resolve_scope(self.coordinator.data, scope)

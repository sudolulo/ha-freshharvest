"""One-way delivery actions.

Donating is a button rather than a switch because it genuinely cannot be undone
from the portal — there is no state to toggle back.
"""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .api import FreshHarvestError
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity

DESCRIPTION = ButtonEntityDescription(
    key="donate_open_order",
    translation_key="donate_open_order",
    icon="mdi:hand-heart",
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the button platform."""
    async_add_entities([FreshHarvestDonate(entry.runtime_data, entry)])


class FreshHarvestDonate(FreshHarvestEntity, ButtonEntity):
    """Donate the upcoming box to Share the Harvest."""

    entity_description = DESCRIPTION

    def __init__(
        self, coordinator: FreshHarvestCoordinator, entry: FreshHarvestConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, DESCRIPTION.key)

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.open_order is not None

    async def async_press(self) -> None:
        """Donate. Not reversible."""
        try:
            result = await self.coordinator.actions.async_donate(dry_run=False)
        except FreshHarvestError as err:
            self.fire_action("donate", False, "open order", str(err))
            raise HomeAssistantError(f"could not donate: {err}") from err
        self.fire_action("donate", True, "open order", result.detail)
        await self.coordinator.async_request_refresh()


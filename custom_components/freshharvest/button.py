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
from .const import DOMAIN, EVENT_ACTION
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
        self._entry = entry

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.data.open_order is not None

    async def async_press(self) -> None:
        """Donate. Not reversible."""
        try:
            result = await self.coordinator.actions.async_donate(dry_run=False)
        except FreshHarvestError as err:
            self._fire(False, str(err))
            raise HomeAssistantError(f"could not donate: {err}") from err
        self._fire(True, result.detail)
        await self.coordinator.async_request_refresh()

    def _fire(self, ok: bool, detail: str) -> None:
        self.hass.bus.async_fire(
            EVENT_ACTION,
            {"domain": DOMAIN, "entry_id": self._entry.entry_id,
             "action": "donate", "success": ok, "target": "open order",
             "detail": detail},
        )

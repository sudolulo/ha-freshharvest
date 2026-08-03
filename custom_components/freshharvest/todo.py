"""The order's ADD-ONS as a to-do list.

Two different things arrive in a delivery and only one of them is a list you
can edit:

* The **produce box** — the Georgia Grown Small Box and its contents. Fresh
  Harvest fills it; you pick the box, not the carrots in it. Swapping it is
  "Change Basket" on the portal, and its contents are read-only here, exposed
  as the `produce` attribute of `sensor.*_next_delivery_items`.
* The **add-ons** — everything you chose individually. These are genuinely
  addable and removable, one endpoint each way.

This entity is the add-ons, because those are the ones where "add X" and
"remove X" mean something. Listing box produce here would invite a delete that
has no endpoint behind it, and the failure would surface as a confusing error
rather than "that is not a thing you can do".

It exists so Home Assistant's own conversation agent can manage the order with
no bespoke voice work: the built-in assistant already knows how to add and
remove to-do items, so "add bananas to my Fresh Harvest add-ons" routes through
`HassListAddItem` and lands here.
"""

from __future__ import annotations

import json
import logging
import re
import urllib.parse

from homeassistant.components.todo import (
    TodoItem,
    TodoItemStatus,
    TodoListEntity,
    TodoListEntityFeature,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import FreshHarvestConfigEntry
from .api import FreshHarvestError
from .const import DOMAIN, EVENT_ACTION
from .coordinator import FreshHarvestCoordinator
from .entity import FreshHarvestEntity

_LOGGER = logging.getLogger(__name__)

ALGOLIA_JS = "/_home/JavaScript/search_algolia.js"
_CREDS_RE = re.compile(r'algoliasearch\(\s*"([^"]+)"\s*,\s*"([^"]+)"', re.S)
_INDEX_RE = re.compile(r'indexName:\s*"([^"]+)"')


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FreshHarvestConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the to-do platform."""
    async_add_entities([FreshHarvestBox(entry.runtime_data, entry)])


class FreshHarvestBox(FreshHarvestEntity, TodoListEntity):
    """Everything in the upcoming delivery, as a list."""

    _attr_translation_key = "add_ons"
    _attr_supported_features = (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )

    def __init__(
        self, coordinator: FreshHarvestCoordinator, entry: FreshHarvestConfigEntry
    ) -> None:
        super().__init__(coordinator, entry, "add_ons")
        self._entry = entry

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """The open order's add-ons — the part of a delivery you control.

        Scoped to the *open* order rather than the next arriving one, because a
        delete has to act on the order actually being shown; the next delivery
        is usually already locked for packing.
        """
        snapshot = self.coordinator.data
        order = snapshot.open_order
        if order is None:
            return None
        items: list[TodoItem] = []
        for item in order.addons:
            label = " ".join(
                p for p in (str(item.quantity or ""), item.name, item.unit) if p
            )
            if item.price is not None:
                label = f"{label} — ${item.price:,.2f}"
            items.append(
                TodoItem(
                    summary=label,
                    uid=item.name,
                    # Not a checklist: nothing here is ever "done", an add-on
                    # either is or is not in the delivery.
                    status=TodoItemStatus.NEEDS_ACTION,
                )
            )
        return items

    async def _algolia_lookup(self, query: str) -> tuple[str, str]:
        """Resolve a spoken name to (item_id, item_name) via the site's index.

        Credentials are read from the site's own JS rather than hardcoded, so a
        key rotation fixes itself and a third party's key never enters this repo.
        """
        client = self.coordinator.client
        js = await client.async_fetch(ALGOLIA_JS)
        creds, index = _CREDS_RE.search(js), _INDEX_RE.search(js)
        if not (creds and index):
            raise HomeAssistantError(
                "could not read the catalogue configuration from the site"
            )
        app, key = creds.groups()
        payload = json.dumps(
            {"params": urllib.parse.urlencode({"query": query, "hitsPerPage": 5})}
        ).encode()
        session = client._session  # noqa: SLF001 — same package
        async with session.post(
            f"https://{app}-dsn.algolia.net/1/indexes/{index.group(1)}/query",
            data=payload,
            headers={
                "X-Algolia-API-Key": key,
                "X-Algolia-Application-Id": app,
                "Content-Type": "application/json",
            },
        ) as resp:
            resp.raise_for_status()
            hits = (await resp.json()).get("hits") or []
        if not hits:
            raise HomeAssistantError(f"nothing in the catalogue matches {query!r}")
        return str(hits[0]["ID"]), str(hits[0].get("Name") or query)

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Add an item to the order.

        The site only renders an add control for something orderable right now,
        so an out-of-stock item fails here rather than silently doing nothing.
        """
        query = (item.summary or "").strip()
        if not query:
            raise HomeAssistantError("no item name given")

        item_id, name = await self._algolia_lookup(query)
        try:
            result = await self.coordinator.actions.async_add_item(
                item_id, dry_run=False, name=name
            )
        except FreshHarvestError as err:
            self._fire(EVENT_ACTION, "add_item", False, query, str(err))
            raise HomeAssistantError(f"could not add {name}: {err}") from err

        self._fire(EVENT_ACTION, "add_item", True, name, result.detail)
        await self.coordinator.async_request_refresh()

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Take items back out of the order."""
        for uid in uids:
            item_id, name = await self._algolia_lookup(uid)
            try:
                await self.coordinator.actions.async_remove_item(
                    item_id, dry_run=False, name=name
                )
            except FreshHarvestError as err:
                self._fire(EVENT_ACTION, "remove_item", False, uid, str(err))
                raise HomeAssistantError(f"could not remove {name}: {err}") from err
            self._fire(EVENT_ACTION, "remove_item", True, name, "removed")
        await self.coordinator.async_request_refresh()

    def _fire(self, event: str, action: str, ok: bool, target: str, detail: str) -> None:
        """Announce the outcome so automations can notify on it."""
        self.hass.bus.async_fire(
            event,
            {
                "domain": DOMAIN,
                "entry_id": self._entry.entry_id,
                "action": action,
                "success": ok,
                "target": target,
                "detail": detail,
            },
        )

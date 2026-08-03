"""Write actions against the Fresh Harvest portal.

Every mutating endpoint on this site is guarded by rotating per-render tokens —
an item's add hash, a skip reason, a subscribe form's ClientID/ItemID. None of
them can be constructed offline, so each action here follows the same shape:

    fetch the page that offers the action
        -> read the fresh tokens out of it
        -> check the tokens describe the thing we meant to act on
        -> submit

That last step matters. The portal states which delivery a skip applies to in
the confirmation text, so we compare it against the date we were asked to skip
and refuse on a mismatch rather than trusting our own bookkeeping.

Actions default to `dry_run=True`: they do all the work and report exactly what
they would submit, without submitting. Callers must opt in to the real thing.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import date

from bs4 import BeautifulSoup

from yarl import URL

from .api import BASE, USER_AGENT, FreshHarvestClient, FreshHarvestError

_LOGGER = logging.getLogger(__name__)

DASHBOARD_ORDERS = "/p/dashboard/manage-orders"
DASHBOARD_SUBS = "/p/dashboard/manage-subscriptions"
DASHBOARD_PAUSE = "/p/dashboard/pause-deliveries"
SHOP_ITEM = "/p/shop/item/{item_id}/x"

SUBMIT_SKIP = "/s/submit/pause-delivery"
SUBMIT_DONATE = "/s/submit/donate-basket"
SUBMIT_SUBSCRIBE = "/s/submit/item-frequency"
SUBMIT_HOLD = "/s/submit/pause-range-add"
AJAX_ORDER_MANAGE = "/p/Ajax/order-manage/{mode}/{hash}/-/false/{ts}"

# id='FrequencyID' but name='popup-toggle' — the id is a decoy, the POST field
# is popup-toggle. Submitting FrequencyID silently does nothing.
FREQUENCY_FIELD = "popup-toggle"
FREQUENCIES = {"weekly": "1", "2 weeks": "4", "3 weeks": "3", "4 weeks": "5"}

_MONTHS = (
    "January February March April May June July August September October "
    "November December"
).split()


class FreshHarvestActionError(FreshHarvestError):
    """An action could not be performed safely."""


@dataclass
class Subscription:
    """A standing order: this item, this often."""

    name: str
    quantity: int | None = None
    frequency: str | None = None
    partner: str | None = None
    arriving: str | None = None


@dataclass
class VacationHold:
    """A paused date range."""

    start: str
    end: str
    raw: str = ""


@dataclass
class ActionResult:
    """What an action did, or would have done."""

    action: str
    ok: bool
    detail: str
    dry_run: bool = False
    target: str | None = None
    submitted: dict[str, str] = field(default_factory=dict)

    def redacted(self) -> dict[str, str]:
        """Field names and value lengths only — the values are auth tokens."""
        return {k: f"<{len(v)} chars>" if len(v) > 24 else v
                for k, v in self.submitted.items()}


def _hidden_fields(form) -> dict[str, str]:
    return {
        i.get("name"): i.get("value", "")
        for i in form.select("input[type=hidden]")
        if i.get("name")
    }


def _find_form(soup: BeautifulSoup, action: str):
    for form in soup.select("form"):
        if (form.get("action") or "").endswith(action):
            return form
    return None


def parse_subscriptions(html: str) -> list[Subscription]:
    """Read /p/dashboard/manage-subscriptions."""
    soup = BeautifulSoup(html, "html.parser")
    account = soup.select_one(".account")
    if account is None:
        return []
    subs: list[Subscription] = []
    for row in account.select(".account-item-multi-fields"):
        cells = [c.get_text(" ", strip=True) for c in row.select(".account-item-text")]
        cells = [c for c in cells if c]
        if len(cells) < 2:
            continue
        qty = cells[0]
        subs.append(
            Subscription(
                name=cells[1],
                quantity=int(qty) if qty.isdigit() else None,
                arriving=cells[2] if len(cells) > 2 else None,
                partner=cells[3] if len(cells) > 3 else None,
                frequency=cells[4] if len(cells) > 4 else None,
            )
        )
    return subs


def parse_vacation_holds(html: str) -> list[VacationHold]:
    """Read the scheduled pauses off /p/dashboard/pause-deliveries."""
    soup = BeautifulSoup(html, "html.parser")
    holds: list[VacationHold] = []
    for row in soup.select(".account-item-multi-fields, .account-item-container"):
        text = row.get_text(" ", strip=True)
        found = re.findall(r"\d{4}-\d{2}-\d{2}", text)
        if len(found) >= 2:
            holds.append(VacationHold(start=found[0], end=found[1], raw=text))
    return holds


def _confirmation_date(text: str) -> date | None:
    """Pull 'scheduled for August 11' out of the skip confirmation."""
    m = re.search(r"scheduled for\s+([A-Za-z]+)\s+(\d{1,2})", text)
    if not m or m.group(1) not in _MONTHS:
        return None
    month = _MONTHS.index(m.group(1)) + 1
    day = int(m.group(2))
    today = date.today()
    year = today.year + (1 if month < today.month - 6 else 0)
    try:
        return date(year, month, day)
    except ValueError:
        return None


class FreshHarvestActions:
    """Mutating operations, each re-deriving its tokens from a live page."""

    def __init__(self, client: FreshHarvestClient) -> None:
        self._client = client

    async def _post(self, path: str, payload: dict[str, str]) -> str:
        session = self._client._session  # noqa: SLF001 — same package
        async with session.post(
            BASE.join(URL(path)),
            data=payload,
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    # ------------------------------------------------------------------ skip

    async def async_skip(
        self, delivery_date: date, reason: str = "", dry_run: bool = True
    ) -> ActionResult:
        """Skip one delivery.

        The portal only renders a skip token for deliveries that are still
        changeable, so a locked order simply has no token — there is nothing to
        submit and this raises rather than inventing one.
        """
        page = await self._client.async_fetch(DASHBOARD_ORDERS)
        tokens = re.findall(r'openPopup\("pause-delivery","([^"]+)"', page)
        if not tokens:
            raise FreshHarvestActionError("no skippable delivery on this account")

        for token in dict.fromkeys(tokens):
            popup = await self._client.async_fetch(f"/x/popup/pause-delivery/{token}")
            form = _find_form(BeautifulSoup(popup, "html.parser"), SUBMIT_SKIP)
            if form is None:
                # Several tokens on the page are for other popups and fall
                # through to the shop page; skip them rather than guessing.
                continue
            soup = BeautifulSoup(popup, "html.parser")
            stated = _confirmation_date(soup.get_text(" ", strip=True))
            if stated != delivery_date:
                continue

            payload = _hidden_fields(form)
            options = [
                (o.get("value"), o.get_text(strip=True))
                for o in form.select("option")
                if o.get("value")
            ]
            if not options:
                raise FreshHarvestActionError("skip form has no reasons")
            chosen = next(
                (v for v, label in options if reason.lower() in label.lower()),
                options[0][0],
            ) if reason else options[0][0]
            payload["SkipReason"] = chosen
            payload["Continue"] = "Confirm"

            result = ActionResult(
                action="skip",
                ok=True,
                target=delivery_date.isoformat(),
                submitted=payload,
                dry_run=dry_run,
                detail=f"skip {delivery_date} (server confirmed this date)",
            )
            if dry_run:
                return result
            await self._post(SUBMIT_SKIP, payload)
            return result

        raise FreshHarvestActionError(
            f"no skip token matched {delivery_date} — it is probably past its "
            "cutoff and locked for packing"
        )

    # ---------------------------------------------------------------- donate

    async def async_donate(self, dry_run: bool = True) -> ActionResult:
        """Donate the upcoming box. One-way — there is no undo in the UI."""
        page = await self._client.async_fetch(DASHBOARD_ORDERS)
        m = re.search(r'openPopup\("donate-delivery","([^"]+)"', page)
        if not m:
            raise FreshHarvestActionError("no donatable delivery")
        popup = await self._client.async_fetch(f"/x/popup/donate-delivery/{m.group(1)}")
        form = _find_form(BeautifulSoup(popup, "html.parser"), SUBMIT_DONATE)
        if form is None:
            raise FreshHarvestActionError("donate form not found")
        payload = _hidden_fields(form) | {"Continue": "Confirm"}
        result = ActionResult(
            action="donate", ok=True, submitted=payload, dry_run=dry_run,
            detail="donate the upcoming box (not reversible)",
        )
        if not dry_run:
            await self._post(SUBMIT_DONATE, payload)
        return result

    # ------------------------------------------------------------ cart items

    async def _item_page(self, item_id: int | str) -> str:
        return await self._client.async_fetch(SHOP_ITEM.format(item_id=item_id))

    async def async_add_item(
        self, item_id: int | str, dry_run: bool = True
    ) -> ActionResult:
        """Add one of an item to the open order.

        The add hash only exists when the item is actually orderable, so its
        absence *is* the out-of-stock signal — no separate stock lookup can go
        stale behind our back.
        """
        return await self._cart_action("add", item_id, dry_run)

    async def async_remove_item(
        self, item_id: int | str, dry_run: bool = True
    ) -> ActionResult:
        return await self._cart_action("remove", item_id, dry_run)

    async def _cart_action(self, mode: str, item_id, dry_run: bool) -> ActionResult:
        page = await self._item_page(item_id)
        m = re.search(r'orderManage\("%s","([^"]+)"' % mode, page)
        if not m:
            raise FreshHarvestActionError(
                f"item {item_id} cannot be {mode}ed right now — the page offers "
                "no control for it, which usually means it is out of stock"
            )
        name = BeautifulSoup(page, "html.parser").select_one(".item-name")
        url = AJAX_ORDER_MANAGE.format(
            mode=mode, hash=m.group(1), ts=int(time.time() * 1000)
        )
        result = ActionResult(
            action=f"{mode}_item",
            ok=True,
            target=name.get_text(" ", strip=True) if name else str(item_id),
            submitted={"url": url},
            dry_run=dry_run,
            detail=f"{mode} item {item_id}",
        )
        if not dry_run:
            # A fragment, not a page: no Sign Out control to detect, so bypass
            # the signed-in check. The item fetch above already renewed the session.
            await self._client._get(url)  # noqa: SLF001 — same package
        return result

    # --------------------------------------------------------- subscriptions

    async def async_subscribe(
        self,
        item_id: int | str,
        frequency: str = "weekly",
        quantity: int = 1,
        dry_run: bool = True,
    ) -> ActionResult:
        """Subscribe to an item, or change its quantity/frequency.

        Quantity 0 unsubscribes — the same endpoint serves all three.
        """
        freq = FREQUENCIES.get(frequency.lower().strip())
        if freq is None:
            raise FreshHarvestActionError(
                f"unknown frequency {frequency!r}; expected one of "
                + ", ".join(FREQUENCIES)
            )
        page = await self._item_page(item_id)
        form = _find_form(BeautifulSoup(page, "html.parser"), SUBMIT_SUBSCRIBE)
        if form is None:
            raise FreshHarvestActionError(f"item {item_id} is not subscribable")
        payload = _hidden_fields(form)
        payload["Quantity"] = str(quantity)
        payload[FREQUENCY_FIELD] = freq
        payload["Submit"] = "Confirm"
        result = ActionResult(
            action="unsubscribe" if quantity == 0 else "subscribe",
            ok=True,
            target=str(item_id),
            submitted=payload,
            dry_run=dry_run,
            detail=f"{quantity} x item {item_id} every {frequency}",
        )
        if not dry_run:
            await self._post(SUBMIT_SUBSCRIBE, payload)
        return result

    async def async_list_subscriptions(self) -> list[Subscription]:
        return parse_subscriptions(await self._client.async_fetch(DASHBOARD_SUBS))

    # -------------------------------------------------------- vacation holds

    async def async_add_vacation_hold(
        self, start: date, end: date, dry_run: bool = True
    ) -> ActionResult:
        """Pause every delivery in a date range.

        Distinct from skipping: three weeks away is one hold, not three skips.
        """
        if end < start:
            raise FreshHarvestActionError("end date is before start date")
        page = await self._client.async_fetch(DASHBOARD_PAUSE)
        form = _find_form(BeautifulSoup(page, "html.parser"), SUBMIT_HOLD)
        if form is None:
            raise FreshHarvestActionError("vacation hold form not found")
        payload = _hidden_fields(form)
        payload["StartDate"] = start.isoformat()
        payload["EndDate"] = end.isoformat()
        result = ActionResult(
            action="vacation_hold",
            ok=True,
            target=f"{start.isoformat()}..{end.isoformat()}",
            submitted=payload,
            dry_run=dry_run,
            detail=f"pause deliveries {start} to {end}",
        )
        if not dry_run:
            await self._post(SUBMIT_HOLD, payload)
        return result

    async def async_list_vacation_holds(self) -> list[VacationHold]:
        return parse_vacation_holds(await self._client.async_fetch(DASHBOARD_PAUSE))

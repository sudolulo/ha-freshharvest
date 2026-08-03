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
SUBMIT_RESTORE = "/s/submit/restore-delivery"
SUBMIT_DONATE = "/s/submit/donate-basket"
SUBMIT_SUBSCRIBE = "/s/submit/item-frequency"
SUBMIT_HOLD = "/s/submit/pause-range-add"
SUBMIT_BASKET = "/s/submit/select-basket"
SUBMIT_HOLD_REMOVE = "/s/submit/pause-range-remove"
BASKET_TYPES = "/p/shop/basket-types"
BASKET_GROUPS = (
    "georgia-grown-baskets",
    "mixed-fruit-and-veggie-baskets",
    "fruit-basket",
)
# The two submit buttons set this before posting: "do" = this delivery only,
# "so" = the standing order, i.e. every future box.
SCOPE_ONCE, SCOPE_STANDING = "do", "so"
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
    """Read /p/dashboard/manage-subscriptions.

    Cells are picked by their semantic class rather than column position:
    `.account-item-multi-fields` is the HEADING row, and matching on it
    silently yields zero subscriptions on an account that has some.
    """
    soup = BeautifulSoup(html, "html.parser")
    account = soup.select_one(".account")
    if account is None:
        return []

    def cell(row, *classes) -> str | None:
        for cls in classes:
            found = row.select_one(f".account-item-text.{cls}")
            if found is not None:
                text = found.get_text(" ", strip=True)
                if text:
                    return text
        return None

    subs: list[Subscription] = []
    for row in account.select(".account-item-container"):
        name = cell(row, "account-item-description")
        if not name:
            continue
        qty = cell(row, "account-item-history-qty")
        subs.append(
            Subscription(
                name=name,
                quantity=int(qty) if (qty or "").isdigit() else None,
                arriving=cell(row, "account-item-history"),
                partner=cell(row, "account-item-history-vendor"),
                frequency=cell(row, "center"),
            )
        )
    return subs


def parse_vacation_holds(html: str) -> list[VacationHold]:
    """Read the scheduled pauses off /p/dashboard/pause-deliveries.

    The page renders a hold as "Tuesday, Dec 1 - Monday, Dec 7" — day names and
    abbreviated months, never ISO. An earlier version looked for YYYY-MM-DD and
    so reported no holds on an account that had one, which is indistinguishable
    from having none.
    """
    soup = BeautifulSoup(html, "html.parser")
    account = soup.select_one(".account")
    if account is None:
        return []
    text = re.sub(r"\s+", " ", account.get_text(" ", strip=True))
    holds: list[VacationHold] = []
    pattern = re.compile(
        r"[A-Z][a-z]+,\s*([A-Z][a-z]{2})\s+(\d{1,2})\s*-\s*"
        r"[A-Z][a-z]+,\s*([A-Z][a-z]{2})\s+(\d{1,2})"
    )
    for m in pattern.finditer(text):
        start = f"{m.group(1)} {m.group(2)}"
        end = f"{m.group(3)} {m.group(4)}"
        holds.append(VacationHold(start=start, end=end, raw=m.group(0)))
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
        tokens = re.findall(r'openPopup\("pause-delivery",\s*"([^"]+)"', page)
        if not tokens:
            raise FreshHarvestActionError("no skippable delivery on this account")

        for token in dict.fromkeys(tokens):
            popup = await self._client.async_fetch(
                f"/x/popup/pause-delivery/{token}", is_page=False
            )
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

    async def async_restore(
        self, delivery_date: date, dry_run: bool = True
    ) -> ActionResult:
        """Un-skip a delivery.

        The restore popup only exists once an order is actually skipped — it is
        not on the page beforehand — so this is the exact inverse of a skip and
        raises when there is nothing to restore.
        """
        page = await self._client.async_fetch(DASHBOARD_ORDERS)
        tokens = re.findall(r'openPopup\("restore-delivery",\s*"([^"]+)"', page)
        if not tokens:
            raise FreshHarvestActionError("no skipped delivery to restore")

        for token in dict.fromkeys(tokens):
            popup = await self._client.async_fetch(
                f"/x/popup/restore-delivery/{token}", is_page=False
            )
            soup = BeautifulSoup(popup, "html.parser")
            form = _find_form(soup, SUBMIT_RESTORE)
            if form is None:
                continue
            stated = _confirmation_date(soup.get_text(" ", strip=True))
            if stated is not None and stated != delivery_date:
                continue
            payload = _hidden_fields(form) | {"Continue": "Confirm"}
            result = ActionResult(
                action="restore", ok=True, target=delivery_date.isoformat(),
                submitted=payload, dry_run=dry_run,
                detail=f"restore {delivery_date}",
            )
            if not dry_run:
                await self._post(SUBMIT_RESTORE, payload)
            return result

        raise FreshHarvestActionError(f"no restore token matched {delivery_date}")

    # ---------------------------------------------------------------- donate

    async def async_donate(self, dry_run: bool = True) -> ActionResult:
        """Donate the upcoming box. One-way — there is no undo in the UI."""
        page = await self._client.async_fetch(DASHBOARD_ORDERS)
        m = re.search(r'openPopup\("donate-delivery",\s*"([^"]+)"', page)
        if not m:
            raise FreshHarvestActionError("no donatable delivery")
        popup = await self._client.async_fetch(
            f"/x/popup/donate-delivery/{m.group(1)}", is_page=False
        )
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
        self, item_id: int | str, dry_run: bool = True, name: str | None = None
    ) -> ActionResult:
        """Add one of an item to the open order.

        The add hash only exists when the item is actually orderable, so its
        absence *is* the out-of-stock signal — no separate stock lookup can go
        stale behind our back.
        """
        return await self._cart_action("add", item_id, dry_run, name)

    async def async_remove_item(
        self, item_id: int | str, dry_run: bool = True, name: str | None = None
    ) -> ActionResult:
        return await self._cart_action("remove", item_id, dry_run, name)

    async def _cart_action(
        self, mode: str, item_id, dry_run: bool, name: str | None = None
    ) -> ActionResult:
        page = await self._item_page(item_id)
        m = re.search(r'orderManage\("%s","([^"]+)"' % mode, page)
        if not m:
            raise FreshHarvestActionError(
                f"item {item_id} cannot be {mode}ed right now — the page offers "
                "no control for it, which usually means it is out of stock"
            )
        # Do NOT scrape a name off this page: the first `.item-name` belongs to
        # whatever is in the mini-cart, not the item being acted on, so an add
        # would announce someone else's groceries. Callers know the real name.
        url = AJAX_ORDER_MANAGE.format(
            mode=mode, hash=m.group(1), ts=int(time.time() * 1000)
        )
        result = ActionResult(
            action=f"{mode}_item",
            ok=True,
            target=name or str(item_id),
            submitted={"url": url},
            dry_run=dry_run,
            detail=f"{mode} item {item_id}",
        )
        if not dry_run:
            # A fragment, not a page — see async_fetch(is_page=...).
            await self._client.async_fetch(url, is_page=False)
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

    async def async_remove_vacation_hold(self, dry_run: bool = True) -> ActionResult:
        """Lift the first scheduled hold.

        Its popup only exists while a hold does, so this raises when there is
        nothing to lift rather than posting into the void.
        """
        page = await self._client.async_fetch(DASHBOARD_PAUSE)
        tok = re.search(r'openPopup\("pause-range-remove",\s*"([^"]+)"', page)
        if not tok:
            raise FreshHarvestActionError("no scheduled hold to remove")
        popup = await self._client.async_fetch(
            f"/x/popup/pause-range-remove/{tok.group(1)}", is_page=False
        )
        soup = BeautifulSoup(popup, "html.parser")
        form = _find_form(soup, SUBMIT_HOLD_REMOVE)
        if form is None:
            raise FreshHarvestActionError("hold-removal form not found")
        payload = _hidden_fields(form) | {"Continue": "Confirm"}
        result = ActionResult(
            action="remove_vacation_hold", ok=True,
            target=re.sub(r"\s+", " ", soup.get_text(" ", strip=True))[:80],
            submitted=payload, dry_run=dry_run, detail="lift the scheduled hold",
        )
        if not dry_run:
            await self._post(SUBMIT_HOLD_REMOVE, payload)
        return result


@dataclass
class Basket:
    """A produce box you can switch to."""

    item_id: str
    name: str
    is_current: bool = False
    token: str = ""


class BasketMixin:
    """Produce-box switching, mixed into FreshHarvestActions below.

    A box is not an add-on: you swap which box arrives, you do not add or
    remove the produce inside it. The switch also has a scope the add-on
    endpoints do not — one delivery, or every future one.
    """

    async def async_list_baskets(self) -> list[Basket]:
        """Every box you could switch TO.

        Each option's real name lives in its own popup rather than the grid
        (the grid calls them all "Georgia Box"), so this reads them there.

        The box you are already on is deliberately absent: the site offers no
        "switch to this" control for it, so there is no popup and no name. Its
        id shows up as every popup's `ReplaceItemID`, which is what
        `current_basket_id` returns; its NAME comes from the subscription list.
        """
        baskets: list[Basket] = []
        seen: set[str] = set()
        for group in BASKET_GROUPS:
            page = await self._client.async_fetch(f"{BASKET_TYPES}/{group}")
            tokens = dict.fromkeys(
                re.findall(r'openPopup\("select-basket",\s*"([^"]+)"', page)
            )
            for token in tokens:
                popup = await self._client.async_fetch(
                    f"/x/popup/select-basket/{token}", is_page=False
                )
                soup = BeautifulSoup(popup, "html.parser")
                form = _find_form(soup, SUBMIT_BASKET)
                if form is None:
                    continue  # a catch-all page, not a real popup
                fields = _hidden_fields(form)
                item_id = fields.get("ItemID", "")
                if not item_id or item_id in seen:
                    continue
                seen.add(item_id)
                heading = soup.select_one("h4, h5, h6")
                baskets.append(
                    Basket(
                        item_id=item_id,
                        name=(heading.get_text(" ", strip=True) if heading else item_id),
                        is_current=False,  # see the docstring: never offered
                        token=token,
                    )
                )
        return baskets

    async def async_current_basket_id(self) -> str | None:
        """The id of the box currently subscribed, read off any switch popup."""
        for group in BASKET_GROUPS:
            page = await self._client.async_fetch(f"{BASKET_TYPES}/{group}")
            for token in dict.fromkeys(
                re.findall(r'openPopup\("select-basket",\s*"([^"]+)"', page)
            ):
                popup = await self._client.async_fetch(
                    f"/x/popup/select-basket/{token}", is_page=False
                )
                form = _find_form(BeautifulSoup(popup, "html.parser"), SUBMIT_BASKET)
                if form is not None:
                    return _hidden_fields(form).get("ReplaceItemID")
        return None

    async def async_change_basket(
        self, name_or_id: str, all_future: bool = False, dry_run: bool = True
    ) -> ActionResult:
        """Switch to a different produce box.

        `all_future=False` changes only the next delivery; True changes the
        standing order. Defaulting to the one-off is deliberate — a mistaken
        permanent change is the more annoying of the two to undo.
        """
        wanted = str(name_or_id).strip().lower()
        for basket in await self.async_list_baskets():
            if wanted not in (basket.item_id.lower(), basket.name.lower()):
                continue
            popup = await self._client.async_fetch(
                f"/x/popup/select-basket/{basket.token}", is_page=False
            )
            form = _find_form(BeautifulSoup(popup, "html.parser"), SUBMIT_BASKET)
            if form is None:
                raise FreshHarvestActionError("basket form disappeared mid-flight")
            payload = _hidden_fields(form)
            payload["popup-toggle"] = SCOPE_STANDING if all_future else SCOPE_ONCE
            scope = "all future orders" if all_future else "the next delivery only"
            result = ActionResult(
                action="change_basket", ok=True, target=basket.name,
                submitted=payload, dry_run=dry_run,
                detail=f"switch to {basket.name} for {scope}",
            )
            if not dry_run:
                await self._post(SUBMIT_BASKET, payload)
            return result

        raise FreshHarvestActionError(f"no box matches {name_or_id!r}")


class FreshHarvestActions(FreshHarvestActions, BasketMixin):  # noqa: F811
    """Actions plus basket switching."""

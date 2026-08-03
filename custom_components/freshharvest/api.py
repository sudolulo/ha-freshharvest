"""HTTP client and HTML parser for the freshharvest.com customer portal.

The site is server-rendered with no JSON API, so this client drives the same
form flow a browser does and parses the dashboard markup.

Everything the integration needs lives on a single page,
``/p/dashboard/details``: the account's delivery day and next arrival date, the
upcoming carts with their contents, and the order totals. Keeping this to one
request per refresh is deliberate — the portal is a small business's website.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

import aiohttp
from bs4 import BeautifulSoup
from yarl import URL

_LOGGER = logging.getLogger(__name__)

BASE = URL("https://freshharvest.com")
LOGIN_FORM = "/s/popup/login"
LOGIN_SUBMIT = "/s/submit/login"
DASHBOARD = "/p/dashboard/details"

# The portal serves a reduced page to obviously-scripted clients.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

# Hidden anti-replay fields, minted per session on each GET of the login form.
_HIDDEN_RE = re.compile(
    r"name='(?P<name>LoginSecurity|SubmitToken)'[^>]*value='(?P<value>[^']*)'"
)
_NEXT_ARRIVING_RE = re.compile(
    r"Your deliveries are\s*(?P<day>[A-Za-z]+)\.\s*"
    r"Next Arriving:\s*(?P<date>[A-Za-z]+\s+\d+(?:st|nd|rd|th)?,\s*\d{4})",
    re.IGNORECASE,
)
_TAB_DATE_RE = re.compile(r"(?P<month>\d{1,2})/(?P<day>\d{1,2})")
_ORDINAL_RE = re.compile(r"(\d+)(?:st|nd|rd|th)", re.IGNORECASE)
_MONEY_RE = re.compile(r"-?\$\s*([\d,]+\.\d{2})")


class FreshHarvestError(Exception):
    """Base error."""


class FreshHarvestAuthError(FreshHarvestError):
    """Credentials rejected, or the session expired and could not be renewed."""


def _money(text: str | None) -> float | None:
    """Pull a dollar amount out of a label. Non-amounts (e.g. 'Add Tip') -> None."""
    if not text:
        return None
    match = _MONEY_RE.search(text)
    if not match:
        return None
    return float(match.group(1).replace(",", ""))


def _text(node, selector: str) -> str | None:
    found = node.select_one(selector)
    if found is None:
        return None
    value = found.get_text(" ", strip=True)
    return value or None


@dataclass
class OrderItem:
    """One line in a cart: a produce-box component or a paid add-on."""

    name: str
    quantity: int | None = None
    unit: str | None = None
    price: float | None = None


@dataclass
class DeliveryOrder:
    """A single upcoming delivery."""

    delivery_id: str
    delivery_date: date | None = None
    box_name: str | None = None
    box_price: float | None = None
    items: list[OrderItem] = field(default_factory=list)
    addons: list[OrderItem] = field(default_factory=list)
    subtotal: float | None = None
    tax: float | None = None
    delivery_fee: float | None = None
    driver_tip: float | None = None
    total: float | None = None
    # What a Bounty membership would knock off this order. Marketing, not a charge.
    bounty_savings: float | None = None
    # How much more this order needs to qualify for free delivery, 0.0 once it does.
    free_delivery_remaining: float | None = None
    # Non-empty only while the order can still be changed, e.g. "Shop tomorrow"
    # or "Shop thru Sunday 8/9". Empty once the order is locked for packing.
    shop_window: str | None = None

    @property
    def is_open(self) -> bool:
        """Whether the order can still be customized."""
        return bool(self.shop_window)

    @property
    def all_items(self) -> list[OrderItem]:
        return [*self.items, *self.addons]

    @property
    def addons_total(self) -> float:
        """Combined cost of the add-ons, excluding the produce box itself.

        Add-on prices are already extended (4 smoothies bill as one $17.96
        line), so this is a plain sum. It should equal `subtotal - box_price`.
        """
        return round(sum(a.price for a in self.addons if a.price is not None), 2)


@dataclass
class AccountSnapshot:
    """Everything read from one dashboard fetch."""

    next_delivery: date | None = None
    delivery_day: str | None = None
    # Account-wide spend needed for free delivery. Only rendered on carts that
    # have not reached it, so it is read once and applied to every order.
    free_delivery_threshold: float | None = None
    orders: list[DeliveryOrder] = field(default_factory=list)
    # Populated by the coordinator from separate pages. Typed loosely because
    # actions.py imports this module, so it cannot be imported back from here.
    subscriptions: list = field(default_factory=list)
    vacation_holds: list = field(default_factory=list)

    @property
    def next_order(self) -> DeliveryOrder | None:
        """The cart for the next arriving delivery.

        Matched against the account's stated next-arrival date. Note that this
        order is usually already locked: the *open* cart is the one after it.
        """
        if self.next_delivery is not None:
            for order in self.orders:
                if order.delivery_date == self.next_delivery:
                    return order
        dated = [o for o in self.orders if o.delivery_date]
        return min(dated, key=lambda o: o.delivery_date) if dated else None

    @property
    def open_order(self) -> DeliveryOrder | None:
        """The earliest cart that can still be customized."""
        candidates = [o for o in self.orders if o.is_open and o.delivery_date]
        return min(candidates, key=lambda o: o.delivery_date) if candidates else None


def _parse_full_date(raw: str) -> date | None:
    """Parse 'August 4th, 2026'."""
    from datetime import datetime

    cleaned = _ORDINAL_RE.sub(r"\1", raw).replace(",", " ")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    try:
        return datetime.strptime(cleaned, "%B %d %Y").date()
    except ValueError:
        _LOGGER.debug("could not parse date %r", raw)
        return None


def _parse_tab_date(raw: str, anchor: date | None) -> date | None:
    """Parse a cart tab label like 'Tue 8/11', which carries no year.

    The year is taken from ``anchor`` (the account's next-arrival date), rolling
    forward when the tab falls far enough behind it to be a December/January
    boundary rather than a genuinely earlier delivery.
    """
    match = _TAB_DATE_RE.search(raw or "")
    if not match:
        return None
    month, day = int(match["month"]), int(match["day"])
    year = anchor.year if anchor else date.today().year
    try:
        candidate = date(year, month, day)
    except ValueError:
        return None
    if anchor and (anchor - candidate).days > 180:
        try:
            candidate = date(year + 1, month, day)
        except ValueError:
            return None
    return candidate


def parse_dashboard(html: str) -> AccountSnapshot:
    """Parse ``/p/dashboard/details`` into a snapshot."""
    soup = BeautifulSoup(html, "html.parser")
    snapshot = AccountSnapshot()

    account = soup.select_one(".account")
    if account is not None:
        match = _NEXT_ARRIVING_RE.search(account.get_text(" ", strip=True))
        if match:
            snapshot.delivery_day = match["day"]
            snapshot.next_delivery = _parse_full_date(match["date"])

    # Tab labels carry the delivery dates; the cart bodies carry everything else.
    tab_dates = {
        node.get("data-cart-select"): node.get_text(strip=True)
        for node in soup.select(".cart-selector-options-wrapper > div[data-cart-select]")
    }

    for cart in soup.select("div.cart-contents[data-cart-select]"):
        delivery_id = cart.get("data-cart-select")
        order = DeliveryOrder(
            delivery_id=delivery_id,
            delivery_date=_parse_tab_date(
                tab_dates.get(delivery_id, ""), snapshot.next_delivery
            ),
            box_name=_text(cart, ".cart-basket-columns h6"),
            box_price=_money(_text(cart, ".cart-basket-columns .item-total")),
            shop_window=_text(cart, ".cart-customize-wrapper"),
        )

        for row in cart.select(".basket-item"):
            name = _text(row, ".basket-item-name")
            if not name:
                continue
            quantity = _text(row, ".basket-item-quantity")
            order.items.append(
                OrderItem(
                    name=name,
                    quantity=int(quantity) if (quantity or "").isdigit() else None,
                    unit=_text(row, ".basket-item-uom"),
                )
            )

        for row in cart.select(".cart-item"):
            classes = row.get("class") or []
            if "basket-item" in classes:
                continue
            name = _text(row, ".item-name")
            if not name:
                continue
            quantity = _text(row, ".item-order-quantity")
            order.addons.append(
                OrderItem(
                    name=name,
                    # .item-total is the extended price: 4 muffins -> $17.96.
                    price=_money(_text(row, ".item-total")),
                    quantity=int(quantity) if (quantity or "").isdigit() else None,
                    unit=_text(row, ".item-uom"),
                )
            )

        totals = soup.select_one(f"#OrderTotals-{delivery_id}")
        if totals is not None:
            labels = totals.select(".summary-item.label")
            values = totals.select(".summary-item.value")
            for label, value in zip(labels, values):
                key = label.get_text(" ", strip=True).lower()
                amount = _money(value.get_text(" ", strip=True))
                if key.startswith("order total"):
                    order.total = amount
                elif key.startswith("subtotal"):
                    order.subtotal = amount
                elif key.startswith("tax"):
                    order.tax = amount
                elif key.startswith("delivery"):
                    order.delivery_fee = amount
                elif key.startswith("driver tip"):
                    # Reads "Add Tip" until one is set, which is not an amount.
                    order.driver_tip = amount
                elif "bounty savings" in key:
                    order.bounty_savings = amount

        progress = soup.select_one(f"#DeliveryProgressBar-{delivery_id} progress")
        if progress is not None and snapshot.free_delivery_threshold is None:
            try:
                snapshot.free_delivery_threshold = float(progress.get("max"))
            except (TypeError, ValueError):
                _LOGGER.debug("unparsable free-delivery threshold on %s", delivery_id)

        snapshot.orders.append(order)

    # Applied after the loop: the threshold is only rendered on carts that have
    # not met it, so an order that already qualifies would otherwise miss it.
    if snapshot.free_delivery_threshold is not None:
        for order in snapshot.orders:
            if order.subtotal is not None:
                order.free_delivery_remaining = round(
                    max(0.0, snapshot.free_delivery_threshold - order.subtotal), 2
                )

    if not snapshot.orders and snapshot.next_delivery is None:
        raise FreshHarvestError("dashboard markup not recognised")
    return snapshot


class FreshHarvestClient:
    """Session-holding client for one portal account."""

    def __init__(
        self, session: aiohttp.ClientSession, email: str, password: str
    ) -> None:
        self._session = session
        self._email = email
        self._password = password
        self._authenticated = False

    async def _get(self, path: str) -> str:
        async with self._session.get(
            BASE.join(URL(path)), headers={"User-Agent": USER_AGENT}
        ) as resp:
            resp.raise_for_status()
            return await resp.text()

    async def async_login(self) -> None:
        """Run the two-step handshake: fetch tokens, then post credentials.

        The tokens are bound to the session cookie issued by the same GET, so
        the fetch and the post must share a cookie jar.
        """
        form = await self._get(LOGIN_FORM)
        hidden = {m["name"]: m["value"] for m in _HIDDEN_RE.finditer(form)}
        if len(hidden) != 2:
            raise FreshHarvestError(
                f"login form missing anti-replay tokens (got {sorted(hidden)}); "
                "the portal markup likely changed"
            )

        payload = {
            "LoginEmail": self._email,
            "LoginPassword": self._password,
            "LoginSecurity": hidden["LoginSecurity"],
            "SubmitToken": hidden["SubmitToken"],
            "Redirect": "",
        }
        try:
            async with self._session.post(
                BASE.join(URL(LOGIN_SUBMIT)),
                data=payload,
                headers={"User-Agent": USER_AGENT},
            ) as resp:
                resp.raise_for_status()
                body = await resp.text()
        except aiohttp.ClientError as err:
            raise FreshHarvestError(f"login request failed: {err}") from err

        if not self._signed_in(body):
            raise FreshHarvestAuthError("login rejected")
        self._authenticated = True

    @staticmethod
    def _signed_in(body: str) -> bool:
        """A signed-in page carries a Sign Out control; a signed-out one does not.

        HTTP status is useless here — the portal answers 200 for every /p/ path,
        including invented ones.
        """
        return "sign out" in body.lower()

    async def async_fetch(self, path: str, *, is_page: bool = True) -> str:
        """Fetch from the portal, re-authenticating once if the session lapsed.

        The shared primitive for reads and for the token-scraping that every
        write action in `actions.py` has to do first.

        Set ``is_page=False`` for popup bodies and AJAX replies. Those are HTML
        *fragments* with no navigation, so they never contain a Sign Out control
        and the signed-in heuristic would read every one of them as logged out —
        re-authenticating pointlessly and then failing.
        """
        if not self._authenticated:
            await self.async_login()

        try:
            body = await self._get(path)
            if is_page and not self._signed_in(body):
                self._authenticated = False
                await self.async_login()
                body = await self._get(path)
                if not self._signed_in(body):
                    raise FreshHarvestAuthError("could not hold a signed-in session")
        except aiohttp.ClientError as err:
            raise FreshHarvestError(f"request for {path} failed: {err}") from err
        return body

    async def async_get_snapshot(self) -> AccountSnapshot:
        """Fetch and parse the dashboard."""
        return parse_dashboard(await self.async_fetch(DASHBOARD))

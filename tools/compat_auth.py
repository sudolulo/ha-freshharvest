#!/usr/bin/env python3
"""Check the markup behind the freshharvest.com login that this integration parses.

tools/compat.py covers what anyone can see: the sign-in form, the catalogue and
the endpoint shapes. Everything that has actually broken so far sat behind the
login, and every one of those breaks was SILENT:

  * subscription rows moved      -> reported 0 subscriptions
  * hold dates were not ISO      -> reported 0 holds
  * a popup gained a space       -> matched nothing at all

A sensor reading 0 looks the same as an account with nothing in it, so nobody
notices. This signs in and asserts each of those assumptions, naming the
symptom when one breaks.

Read-only: it signs in and reads pages, and never posts to a write endpoint.

CREDENTIALS come from the environment, FH_EMAIL and FH_PASSWORD. It refuses to
run without both.

THE OUTPUT IS FOR A PUBLIC LOG (.github/workflows/compat-auth.yml). It prints
one pass/fail label per assumption and nothing read from the account: no
email, no page content, and no hint of the account's state. A check with
nothing to assert against (the hold-date format when no hold is scheduled)
prints as passing, because "no hold scheduled" in a public log would announce
when deliveries are paused.

Exit codes:
   5  every assumption holds (ran, nothing to report)
  10  at least one assumption no longer holds: drift
   2  FH_EMAIL or FH_PASSWORD is missing
   1  the check could not run (portal unreachable, timeout, unexpected error)
"""

from __future__ import annotations

import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from http.cookiejar import CookieJar

BASE = "https://freshharvest.com"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)
TIMEOUT = 45

QUIET = 5  # ran, every assumption holds
FINDING = 10  # ran, and something moved
CANNOT_RUN = 1
MISCONFIGURED = 2

# A check with nothing to assert against. Rendered as a pass; see the docstring.
SKIP = "skip"

Row = tuple[str, object, str]  # (assumption, True | False | SKIP, symptom)


class ConfigError(Exception):
    """The credentials are missing from the environment."""


def credentials(env: Mapping[str, str]) -> tuple[str, str]:
    """Return (email, password) from FH_EMAIL / FH_PASSWORD, or raise ConfigError."""
    email = env.get("FH_EMAIL", "").strip()
    password = env.get("FH_PASSWORD", "").strip()
    missing = [
        name
        for name, value in (("FH_EMAIL", email), ("FH_PASSWORD", password))
        if not value
    ]
    if missing:
        verb = "is" if len(missing) == 1 else "are"
        raise ConfigError(f"{' and '.join(missing)} {verb} not set or empty")
    return email, password


class Portal:
    """A cookie-carrying session on freshharvest.com. The only network code here."""

    def __init__(self) -> None:
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(CookieJar())
        )

    def _open(self, path: str, data: bytes | None = None) -> str:
        req = urllib.request.Request(
            BASE + path, data=data, headers={"User-Agent": UA}
        )
        with self._opener.open(req, timeout=TIMEOUT) as resp:
            return resp.read().decode("utf-8", "replace")

    def get(self, path: str) -> str:
        return self._open(path)

    def post(self, path: str, fields: Mapping[str, str]) -> str:
        return self._open(path, urllib.parse.urlencode(fields).encode())


def sign_in(portal: Portal, email: str, password: str, rows: list[Row]) -> bool:
    form = portal.get("/s/popup/login")
    hidden = dict(
        re.findall(r"name='(LoginSecurity|SubmitToken)'[^>]*value='([^']*)'", form)
    )
    if len(hidden) != 2:
        rows.append(("login form mints both anti-replay tokens", False,
                     "sign-in breaks entirely"))
        return False
    rows.append(("login form mints both anti-replay tokens", True, ""))
    body = portal.post("/s/submit/login", {
        "LoginEmail": email,
        "LoginPassword": password,
        "LoginSecurity": urllib.parse.unquote(hidden["LoginSecurity"]),
        "SubmitToken": urllib.parse.unquote(hidden["SubmitToken"]),
        "Redirect": "",
    })
    ok = "sign out" in body.lower()
    rows.append(("credentials accepted", ok, "every entity goes unavailable"))
    return ok


def run_checks(portal: Portal, email: str, password: str) -> list[Row]:
    rows: list[Row] = []

    def check(assumption: str, ok: object, symptom: str = "") -> None:
        rows.append((assumption, ok, symptom))

    if not sign_in(portal, email, password, rows):
        return rows

    # --- the dashboard the sensors are built on --------------------------
    dash = portal.get("/p/dashboard/details")
    check("dashboard states the delivery day and next arrival",
          bool(re.search(r"Your deliveries are\s*\w+\.\s*Next Arriving:", dash)),
          "next-delivery date goes unknown")
    check("carts render as div.cart-contents[data-cart-select]",
          "cart-contents" in dash and "data-cart-select" in dash,
          "no orders parsed: every order sensor goes unknown")
    check("order totals render as #OrderTotals-<id>",
          "OrderTotals-" in dash,
          "totals go unknown while dates still work")
    check("the shopping window lives in .cart-customize-wrapper",
          "cart-customize-wrapper" in dash,
          "every order looks locked; skip and add refuse")
    check("free-delivery progress carries a max",
          bool(re.search(r"<progress[^>]+max='[\d.]+'", dash)),
          "free-delivery-remaining goes unknown")

    # --- subscriptions: the row selector that silently returned zero -----
    subs = portal.get("/p/dashboard/manage-subscriptions")
    check("subscription rows are .account-item-container",
          "account-item-container" in subs,
          "reports 0 subscriptions, which looks like having none")
    check("subscription cells keep their semantic classes",
          "account-item-description" in subs and "account-item-history-qty" in subs,
          "subscription names/quantities go blank")

    # --- vacation holds: the date format that silently returned zero -----
    pause = portal.get("/p/dashboard/pause-deliveries")
    check("the vacation hold form still posts to pause-range-add",
          "/s/submit/pause-range-add" in pause,
          "cannot schedule a hold")
    # Only assertable while a hold exists. With none scheduled there is no date
    # to inspect, and an unbounded search past "Upcoming Pauses" matches an ISO
    # date from anywhere else on the page: a check that fails on a healthy
    # account is worse than no check, because it trains you to ignore it.
    section = re.search(
        r"Upcoming Pauses(.{0,400}?)(?:Close Account|</section)", pause, re.DOTALL
    )
    body = section.group(1) if section else ""
    entries = re.findall(
        r"[A-Z][a-z]+,\s*[A-Z][a-z]{2}\s+\d{1,2}\s*-\s*[A-Z][a-z]+,\s*[A-Z][a-z]{2}\s+\d{1,2}",
        body,
    )
    check("hold ranges are day-name + abbreviated month, not ISO",
          SKIP if not entries else not re.search(r"\d{4}-\d{2}-\d{2}", body),
          "hold parsing silently reports none")

    # --- popups behind every write action --------------------------------
    orders = portal.get("/p/dashboard/manage-orders")
    for kind, symptom in (
        ("pause-delivery", "skip switch cannot find a delivery"),
        ("donate-delivery", "donate button fails"),
    ):
        check(f"{kind} popup is still offered",
              bool(re.search(rf'openPopup\("{kind}"', orders)),
              symptom)

    # --- basket switching -------------------------------------------------
    baskets = portal.get("/p/shop/basket-types/georgia-grown-baskets")
    check("basket options offer a select-basket popup",
          bool(re.search(r'openPopup\("select-basket",\s*"', baskets)),
          "produce-box select shows no options")
    check("basket ids are exposed as data-title='basket-<id>'",
          "data-title='basket-" in baskets,
          "cannot identify which box is which")

    # --- add-to-cart hash -------------------------------------------------
    item = portal.get("/p/shop/item/6744/bananas")
    check("orderable items expose an orderManage add hash",
          bool(re.search(r'orderManage\("add","', item)),
          "adding any item fails as though out of stock")
    check("subscribe form posts to item-frequency with popup-toggle",
          "/s/submit/item-frequency" in item and "popup-toggle" in item,
          "subscribing silently does nothing")
    return rows


def exit_code(rows: list[Row]) -> int:
    """A count of broken assumptions is not an exit code: 10 is drift, 5 is all clear."""
    return FINDING if any(ok is False for _, ok, _ in rows) else QUIET


def render(rows: list[Row]) -> str:
    """Pass/fail labels only. SKIP renders exactly like a pass (see the docstring)."""
    signed_in = any(a == "credentials accepted" and ok is True for a, ok, _ in rows)
    width = max(len(a) for a, _, _ in rows)
    lines = ["Fresh Harvest signed-in markup check", ""]
    for assumption, ok, symptom in rows:
        lines.append(f"  [{'FAIL' if ok is False else 'ok  '}] {assumption.ljust(width)}")
        if ok is False and symptom:
            lines.append(f"         -> {symptom}")
    passed = sum(1 for _, ok, _ in rows if ok is not False)
    lines += ["", f"{passed}/{len(rows)} assumptions hold"]
    if not signed_in:
        lines.append("Sign-in failed, so nothing behind the login was checked.")
    elif exit_code(rows) == FINDING:
        lines.append("ha-freshharvest is probably reporting wrong values, not erroring.")
    return "\n".join(lines)


def redact(text: str, *secrets: str) -> str:
    """Belt and braces for a public log: no credential survives into any output."""
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    return text


def main(
    env: Mapping[str, str] | None = None,
    portal_factory: Callable[[], Portal] = Portal,
) -> int:
    try:
        email, password = credentials(os.environ if env is None else env)
    except ConfigError as err:
        print(f"cannot run: {err}")
        return MISCONFIGURED

    try:
        rows = run_checks(portal_factory(), email, password)
    except OSError as err:  # URLError, HTTPError, timeouts, resets
        print(redact(f"could not reach the portal: {err}", email, password))
        return CANNOT_RUN
    except Exception as err:  # noqa: BLE001 -- public log: name it, never dump state
        print(f"the check itself failed: {type(err).__name__}")
        return CANNOT_RUN

    print(redact(render(rows), email, password))
    return exit_code(rows)


if __name__ == "__main__":
    sys.exit(main())

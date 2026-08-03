#!/usr/bin/env python3
"""Check what this integration assumes about freshharvest.com against the live site.

There is no API and no stability contract here — the integration reads HTML and
posts to form endpoints, and any redesign can silently change the meaning of a
value rather than breaking loudly. A sensor that quietly reports last week's
total is worse than one that goes unavailable, so this asserts the contract on a
schedule and fails when the site moves.

WHAT THIS CAN AND CANNOT SEE
----------------------------
Only the *unauthenticated* surface is checked here: the login handshake and the
Algolia catalogue. The authenticated contract — dashboard markup, cart add
hashes, skip popups, subscribe forms — needs a real session, and the only way to
give public CI one is to put a personal grocery account's password in repo
secrets. That is not worth it for a drift check. Those assumptions belong in a
fleet job on a host that already has credential access; see README.

Exit code is the number of FAILED checks, so CI fails loudly on drift.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

BASE = "https://freshharvest.com"
UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

OK, FAIL, WARN = "ok", "FAIL", "warn"


def fetch(url: str, data: bytes | None = None, headers: dict | None = None) -> str:
    req = urllib.request.Request(
        url, data=data, headers={"User-Agent": UA, **(headers or {})}
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return resp.read().decode("utf-8", "replace")


class Checks:
    """Each check returns (status, detail). Assumption text mirrors the code."""

    def __init__(self) -> None:
        self.results: list[tuple[str, str, str, str]] = []

    def record(self, area, assumption, status, detail):
        self.results.append((area, assumption, status, detail))

    # -- login handshake ----------------------------------------------------

    def login_form(self):
        area = "Login"
        try:
            html = fetch(f"{BASE}/s/popup/login")
        except urllib.error.URLError as err:
            self.record(area, "login popup reachable", FAIL, str(err))
            return
        self.record(area, "`/s/popup/login` serves the form", OK, f"{len(html)} bytes")

        for field in ("LoginSecurity", "SubmitToken"):
            found = re.search(rf"name='{field}'[^>]*value='([^']+)'", html)
            self.record(
                area,
                f"hidden `{field}` is minted",
                OK if found else FAIL,
                f"{len(found.group(1))} chars" if found else "absent — login will break",
            )
        act = re.search(r"action='([^']*submit/login)'", html)
        self.record(
            area,
            "posts to `/s/submit/login`",
            OK if act else FAIL,
            act.group(1) if act else "form action changed",
        )
        for field in ("LoginEmail", "LoginPassword"):
            self.record(
                area,
                f"field `{field}` present",
                OK if f"name='{field}'" in html else FAIL,
                "",
            )

    # -- catalogue ----------------------------------------------------------

    def algolia(self):
        area = "Catalogue"
        try:
            js = fetch(f"{BASE}/_home/JavaScript/search_algolia.js")
        except urllib.error.URLError as err:
            self.record(area, "search_algolia.js reachable", FAIL, str(err))
            return

        creds = re.search(
            r'algoliasearch\(\s*"([^"]+)"\s*,\s*"([^"]+)"', js, re.S
        )
        index = re.search(r'indexName:\s*"([^"]+)"', js)
        self.record(
            area,
            "Algolia credentials readable from site JS",
            OK if creds else FAIL,
            "app id + search key found" if creds else "pattern changed",
        )
        self.record(
            area,
            "index name readable",
            OK if index else FAIL,
            index.group(1) if index else "not found",
        )
        if not (creds and index):
            return

        app, key = creds.groups()
        try:
            body = fetch(
                f"https://{app}-dsn.algolia.net/1/indexes/{index.group(1)}/query",
                data=json.dumps({"params": "query=&hitsPerPage=1"}).encode(),
                headers={
                    "X-Algolia-API-Key": key,
                    "X-Algolia-Application-Id": app,
                    "Content-Type": "application/json",
                },
            )
        except urllib.error.URLError as err:
            self.record(area, "index queryable", FAIL, str(err))
            return

        data = json.loads(body)
        total = data.get("nbHits", 0)
        # A collapse to near-zero means the index moved or emptied; the exact
        # count drifts constantly as stock changes, so only the floor is checked.
        self.record(
            area,
            "index returns a plausible catalogue",
            OK if total > 100 else FAIL,
            f"{total} records",
        )
        hit = (data.get("hits") or [{}])[0]
        for fieldname in ("ID", "Name", "Price", "Measurement", "Categories"):
            self.record(
                area,
                f"record field `{fieldname}`",
                OK if fieldname in hit else FAIL,
                "present" if fieldname in hit else "MISSING — parser reads this",
            )

    # -- action endpoints ---------------------------------------------------

    def endpoints(self):
        """The write endpoints must still exist; they are never *called* here."""
        area = "Endpoints"
        try:
            js = fetch(f"{BASE}/_home/Ajax/order-manage.js")
        except urllib.error.URLError as err:
            self.record(area, "order-manage.js reachable", FAIL, str(err))
            return
        pattern = "/p/Ajax/order-manage/"
        self.record(
            area,
            "cart add/remove URL shape unchanged",
            OK if pattern in js else FAIL,
            pattern if pattern in js else "URL construction changed",
        )
        try:
            popups = fetch(f"{BASE}/_home/JavaScript/popups.js")
        except urllib.error.URLError as err:
            self.record(area, "popups.js reachable", FAIL, str(err))
            return
        self.record(
            area,
            "popup route is `/x/popup/{type}/{token}`",
            OK if "/x/popup/" in popups else FAIL,
            "found" if "/x/popup/" in popups else "route changed",
        )

    def run(self):
        self.login_form()
        self.algolia()
        self.endpoints()
        return self.results


def render(results) -> str:
    lines = [
        "| Area | Assumption | Status | Detail |",
        "| --- | --- | --- | --- |",
    ]
    icon = {OK: "✅", FAIL: "❌", WARN: "⚠️"}
    for area, assumption, status, detail in results:
        lines.append(f"| {area} | {assumption} | {icon[status]} | {detail} |")
    return "\n".join(lines)


def main(argv):
    results = Checks().run()
    table = render(results)
    failed = [r for r in results if r[2] == FAIL]

    if "--markdown" in argv:
        print(table)
    else:
        print(table)
        print()
        print(f"{len(results) - len(failed)}/{len(results)} checks passed")
        for area, assumption, _, detail in failed:
            print(f"  FAIL {area}: {assumption} — {detail}")
    return len(failed)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

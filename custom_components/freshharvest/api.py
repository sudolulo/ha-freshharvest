"""HTTP client for the freshharvest.com customer portal.

The site is server-rendered (no JSON API), so this client drives the same form
flow a browser does and parses HTML out the other side.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import date

import aiohttp
from yarl import URL

_LOGGER = logging.getLogger(__name__)

BASE = URL("https://freshharvest.com")
LOGIN_FORM = "/s/popup/login"
LOGIN_SUBMIT = "/s/submit/login"

# Browser UA: the portal serves a reduced/blocked page to obvious scripts.
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0 Safari/537.36"
)

# Hidden anti-replay fields, minted fresh on every GET of the login form and
# only valid for the session cookie they were issued against.
_HIDDEN_RE = re.compile(
    r"name='(?P<name>LoginSecurity|SubmitToken)'[^>]*value='(?P<value>[^']*)'"
)


class FreshHarvestError(Exception):
    """Base error."""


class FreshHarvestAuthError(FreshHarvestError):
    """Credentials rejected, or the session expired and could not be renewed."""


@dataclass
class Delivery:
    """A scheduled delivery."""

    delivery_date: date | None = None
    window: str | None = None
    status: str | None = None
    total: float | None = None
    items: list[str] = field(default_factory=list)
    cutoff: str | None = None


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
        the fetch and the post cannot be split across sessions or cached.
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
        async with self._session.post(
            BASE.join(URL(LOGIN_SUBMIT)),
            data=payload,
            headers={"User-Agent": USER_AGENT},
        ) as resp:
            resp.raise_for_status()
            body = await resp.text()

        if not self._looks_authenticated(body):
            raise FreshHarvestAuthError("login rejected")
        self._authenticated = True

    @staticmethod
    def _looks_authenticated(body: str) -> bool:
        """Distinguish a good login from a rejected one.

        NOTE: provisional. Every /p/* path returns 200 even for nonsense URLs,
        so an HTTP status is not a signal here. Needs confirming against a real
        authenticated response before this integration can be trusted.
        """
        lowered = body.lower()
        if "invalid" in lowered or "incorrect" in lowered:
            return False
        return "sign out" in lowered or "log out" in lowered

    async def async_get_next_delivery(self) -> Delivery:
        """Return the account's next scheduled delivery.

        UNIMPLEMENTED. The portal serves a catch-all 200 for every /p/* path
        when signed out, so the real account pages could not be located or
        parsed without an authenticated session. Fill this in against a live
        session rather than guessing at selectors.
        """
        raise FreshHarvestError(
            "delivery parsing is not implemented yet: the portal HTML has not "
            "been mapped against a signed-in session"
        )

    async def async_fetch(self, path: str) -> str:
        """Fetch a portal page, re-authenticating once if the session lapsed."""
        if not self._authenticated:
            await self.async_login()
        body = await self._get(path)
        if not self._looks_authenticated(body):
            self._authenticated = False
            await self.async_login()
            body = await self._get(path)
            if not self._looks_authenticated(body):
                raise FreshHarvestAuthError(f"could not hold a session for {path}")
        return body

"""Tests for tools/compat_auth.py, the signed-in drift check, with no network.

Its log is public, so besides the exit codes these pin down what it must never
print: the credentials, and anything that reveals the account's state.
"""

from __future__ import annotations

import importlib.util
import re
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "compat-auth.yml"
SCRIPT = ROOT / "tools" / "compat_auth.py"

_spec = importlib.util.spec_from_file_location("compat_auth", SCRIPT)
compat_auth = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(compat_auth)

EMAIL = "account-under-test"
PASSWORD = "correct horse battery staple"
ENV = {"FH_EMAIL": EMAIL, "FH_PASSWORD": PASSWORD}

HEALTHY = {
    "/s/popup/login": (
        "<input type='hidden' name='LoginSecurity' value='sec%3D%3D'>"
        "<input type='hidden' name='SubmitToken' value='tok'>"
    ),
    "/p/dashboard/details": (
        "Your deliveries are Tuesdays. Next Arriving: Tue, Aug 4"
        "<div class='cart-contents' data-cart-select='1'>"
        "<span id='OrderTotals-123'>$66.16</span>"
        "<div class='cart-customize-wrapper'>Shop tomorrow</div>"
        "<progress value='38.42' max='50.00'></progress></div>"
    ),
    "/p/dashboard/manage-subscriptions": (
        "<div class='account-item-container'>"
        "<span class='account-item-description'>Bananas</span>"
        "<span class='account-item-history-qty'>1</span></div>"
    ),
    "/p/dashboard/pause-deliveries": (
        "<form action='/s/submit/pause-range-add'></form>"
        "<h3>Upcoming Pauses</h3><p>None scheduled</p></section>"
    ),
    "/p/dashboard/manage-orders": (
        'openPopup("pause-delivery", "a") openPopup("donate-delivery", "b")'
    ),
    "/p/shop/basket-types/georgia-grown-baskets": (
        "<div data-title='basket-12'>"
        "<a onclick='openPopup(\"select-basket\", \"c\")'>Choose</a></div>"
    ),
    "/p/shop/item/6744/bananas": (
        'orderManage("add","d")'
        "<form action='/s/submit/item-frequency' class='popup-toggle'></form>"
    ),
}
SIGNED_IN = "<a href='/logout'>Sign Out</a>"


class FakePortal:
    """Serves canned pages and records every form post."""

    def __init__(self, pages=None, login_reply=SIGNED_IN, raise_on=None):
        self.pages = {**HEALTHY, **(pages or {})}
        self.login_reply = login_reply
        self.raise_on = raise_on or {}
        self.posts: list[tuple[str, dict]] = []

    def get(self, path):
        if path in self.raise_on:
            raise self.raise_on[path]
        return self.pages[path]

    def post(self, path, fields):
        self.posts.append((path, dict(fields)))
        return self.login_reply


def run(capsys, portal=None, env=ENV):
    portal = portal or FakePortal()
    code = compat_auth.main(env=env, portal_factory=lambda: portal)
    out = capsys.readouterr().out
    assert EMAIL not in out and PASSWORD not in out
    return code, out, portal


# --- environment -------------------------------------------------------------


@pytest.mark.parametrize(
    ("env", "named"),
    [
        ({}, ["FH_EMAIL", "FH_PASSWORD"]),
        ({"FH_EMAIL": EMAIL}, ["FH_PASSWORD"]),
        ({"FH_PASSWORD": PASSWORD}, ["FH_EMAIL"]),
        ({"FH_EMAIL": "  ", "FH_PASSWORD": "\n"}, ["FH_EMAIL", "FH_PASSWORD"]),
    ],
)
def test_missing_credentials_exit_2_without_touching_the_network(capsys, env, named):
    def no_network():
        raise AssertionError("must not open a session without credentials")

    code = compat_auth.main(env=env, portal_factory=no_network)
    out = capsys.readouterr().out
    assert code == compat_auth.MISCONFIGURED == 2
    for name in named:
        assert name in out
    assert EMAIL not in out and PASSWORD not in out


def test_reads_the_process_environment_by_default(capsys, monkeypatch):
    monkeypatch.delenv("FH_EMAIL", raising=False)
    monkeypatch.delenv("FH_PASSWORD", raising=False)
    assert compat_auth.main() == 2


def test_credentials_are_stripped():
    assert compat_auth.credentials(
        {"FH_EMAIL": f" {EMAIL}\n", "FH_PASSWORD": f"{PASSWORD}\n"}
    ) == (EMAIL, PASSWORD)


# --- exit-code mapping ---------------------------------------------------------


def test_all_seventeen_assumptions_hold_exit_5(capsys):
    code, out, portal = run(capsys)
    assert code == compat_auth.QUIET == 5
    assert "17/17 assumptions hold" in out
    assert "FAIL" not in out
    # The credentials went to the login POST, with the tokens unquoted.
    [(path, fields)] = portal.posts
    assert path == "/s/submit/login"
    assert fields["LoginEmail"] == EMAIL
    assert fields["LoginPassword"] == PASSWORD
    assert fields["LoginSecurity"] == "sec=="


def test_drift_exit_10_names_the_assumption_and_symptom(capsys):
    portal = FakePortal(pages={"/p/dashboard/manage-subscriptions": "<table></table>"})
    code, out, _ = run(capsys, portal)
    assert code == compat_auth.FINDING == 10
    assert "[FAIL] subscription rows are .account-item-container" in out
    assert "reports 0 subscriptions" in out
    assert "15/17 assumptions hold" in out  # rows and cells both went


def test_rejected_sign_in_is_drift_and_still_prints_the_report(capsys):
    code, out, _ = run(capsys, FakePortal(login_reply="<p>Invalid login</p>"))
    assert code == 10
    assert "[FAIL] credentials accepted" in out
    assert "Sign-in failed" in out


def test_login_form_without_tokens_is_drift(capsys):
    portal = FakePortal(pages={"/s/popup/login": "<form></form>"})
    code, out, _ = run(capsys, portal)
    assert code == 10
    assert "[FAIL] login form mints both anti-replay tokens" in out
    assert portal.posts == []


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("Name or service not known"),
        urllib.error.HTTPError(compat_auth.BASE, 503, "Service Unavailable", None, None),
        TimeoutError("timed out"),
        ConnectionResetError("reset by peer"),
    ],
)
def test_unreachable_portal_exit_1(capsys, error):
    portal = FakePortal(raise_on={"/p/dashboard/details": error})
    code, out, _ = run(capsys, portal)
    assert code == compat_auth.CANNOT_RUN == 1
    assert "could not reach the portal" in out


def test_network_error_text_is_redacted(capsys):
    error = OSError(f"refused for {EMAIL}")
    code, out, _ = run(capsys, FakePortal(raise_on={"/s/popup/login": error}))
    assert code == 1
    assert "***" in out


def test_unexpected_error_exit_1_names_only_the_type(capsys):
    error = ValueError(f"state dump {EMAIL} {PASSWORD}")
    code, out, _ = run(capsys, FakePortal(raise_on={"/p/dashboard/details": error}))
    assert code == 1
    assert "ValueError" in out
    assert "state dump" not in out


def test_exit_code_ignores_checks_with_nothing_to_assert():
    assert compat_auth.exit_code([("a", True, ""), ("b", compat_auth.SKIP, "")]) == 5
    assert compat_auth.exit_code([("a", True, ""), ("b", False, "x")]) == 10


# --- what a public log may reveal ---------------------------------------------


def test_a_scheduled_hold_is_indistinguishable_from_none(capsys):
    none = run(capsys)[1]
    hold = run(capsys, FakePortal(pages={"/p/dashboard/pause-deliveries": (
        "<form action='/s/submit/pause-range-add'></form>"
        "<h3>Upcoming Pauses</h3><p>Tuesday, Sep 8 - Tuesday, Sep 15</p></section>"
    )}))[1]
    assert none == hold
    assert "n/a" not in none and "not applicable" not in none


def test_iso_hold_dates_are_drift(capsys):
    code, out, _ = run(capsys, FakePortal(pages={"/p/dashboard/pause-deliveries": (
        "<form action='/s/submit/pause-range-add'></form><h3>Upcoming Pauses</h3>"
        "<p>Tuesday, Sep 8 - Tuesday, Sep 15 (2026-09-08)</p></section>"
    )}))
    assert code == 10
    assert "[FAIL] hold ranges are day-name + abbreviated month, not ISO" in out


def test_portal_posts_urlencoded_to_the_site():
    sent = []

    class StubResponse:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def read(self):
            return b"Sign Out"

    class StubOpener:
        def open(self, req, timeout):
            sent.append((req, timeout))
            return StubResponse()

    portal = compat_auth.Portal()
    portal._opener = StubOpener()
    assert portal.post("/s/submit/login", {"LoginEmail": EMAIL}) == "Sign Out"
    req, timeout = sent[0]
    assert req.full_url == "https://freshharvest.com/s/submit/login"
    assert urllib.parse.parse_qs(req.data.decode()) == {"LoginEmail": [EMAIL]}
    assert timeout == compat_auth.TIMEOUT


# --- the workflow -------------------------------------------------------------


def test_workflow_lives_where_gitea_reads_it():
    # Gitea reads only the FIRST of .gitea/workflows and .github/workflows that
    # exists; creating .gitea/workflows would silently stop every workflow here.
    assert WORKFLOW.is_file()
    assert not (ROOT / ".gitea" / "workflows").exists()


def test_workflow_shape():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    triggers = doc.get("on", doc.get(True))  # YAML 1.1 reads a bare `on` as True
    assert set(triggers) == {"schedule", "workflow_dispatch"}
    assert triggers["schedule"] == [{"cron": "41 11 * * *"}]
    assert doc["permissions"] == {"contents": "read"}
    [job] = doc["jobs"].values()
    assert job["timeout-minutes"] == 10
    assert "github.server_url" in job["if"]


def test_workflow_and_script_keep_private_details_out():
    text = WORKFLOW.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    assert "set -x" not in code and "xtrace" not in code
    assert set(re.findall(r"secrets\.(\w+)", text)) == {
        "FRESHHARVEST_EMAIL", "FRESHHARVEST_PASSWORD", "NTFY_URL", "NTFY_TOKEN",
    }
    for source in (text, SCRIPT.read_text(encoding="utf-8")):
        assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", source), "an email address"
        assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", source), "an IP address"
        hosts = set(re.findall(r"https?://([^/\s'\"]+)", source))
        assert hosts <= {"freshharvest.com", "github.com"}, hosts

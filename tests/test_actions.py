"""Tests for the subscription and vacation-hold parsers.

Written after a real bug: the first version matched `.account-item-multi-fields`,
which is the HEADING row, so an account with a live subscription reported zero.
A count of nothing looks exactly like an account with nothing.
"""

from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components"


def _load():
    if "aiohttp" not in sys.modules:
        stub = types.ModuleType("aiohttp")
        stub.ClientSession = object
        stub.ClientError = Exception
        sys.modules["aiohttp"] = stub
    sys.path.insert(0, str(COMPONENT))
    pkg = types.ModuleType("fh_pkg")
    pkg.__path__ = [str(COMPONENT / "freshharvest")]
    sys.modules["fh_pkg"] = pkg
    return importlib.import_module("fh_pkg.actions")


actions = _load()

SUBS_HTML = """
<div class='account'>
  <div class='account-item'>
    <div class='account-item-multi-fields'>
      <div class='account-item-heading account-item-history-qty'>Qty</div>
      <div class='account-item-heading account-item-description'>Item</div>
      <div class='account-item-heading account-item-history'>Arriving</div>
      <div class='account-item-heading account-item-history-vendor'>Partner</div>
      <div class='account-item-heading account-item-history center'>Frequency</div>
    </div>
  </div>
  <div class='account-item'>
    <div class='account-item-container'>
      <div class='account-item-text account-item-history-qty'><div class='center'>2</div></div>
      <div class='account-item-text account-item-description'>Georgia Grown Small Box</div>
      <div class='account-item-text account-item-history'>tomorrow</div>
      <div class='account-item-text account-item-history-vendor'>Various Partners</div>
      <div class='account-item-text account-item-history center'>Weekly</div>
      <div class='account-item-action account-item-history-action right'>Change Basket</div>
    </div>
  </div>
</div>
"""


def test_heading_row_is_not_a_subscription():
    """The regression: the header row must not be counted, and must not hide the real one."""
    subs = actions.parse_subscriptions(SUBS_HTML)
    assert len(subs) == 1
    assert subs[0].name == "Georgia Grown Small Box"


def test_subscription_fields():
    sub = actions.parse_subscriptions(SUBS_HTML)[0]
    assert (sub.quantity, sub.frequency) == (2, "Weekly")
    assert sub.partner == "Various Partners"
    assert sub.arriving == "tomorrow"


def test_no_subscriptions_is_empty_not_an_error():
    assert actions.parse_subscriptions("<html><body>nothing</body></html>") == []


def test_vacation_hold_uses_the_sites_own_date_format():
    """The page writes "Tuesday, Dec 1 - Monday, Dec 7", never ISO.

    The first version of this test asserted ISO dates, so it passed against a
    format the site does not produce while the parser reported zero holds on an
    account that had one.
    """
    html = (
        "<div class='account'><div class='account-item'>Upcoming Pauses"
        "<div class='account-item-container'>Tuesday, Dec 1 - Monday, Dec 7"
        "<a>Remove</a></div></div></div>"
    )
    holds = actions.parse_vacation_holds(html)
    assert len(holds) == 1
    assert (holds[0].start, holds[0].end) == ("Dec 1", "Dec 7")


def test_no_holds_parses_empty():
    assert actions.parse_vacation_holds("<div class='account'>none</div>") == []


def test_frequency_names_map_to_site_values():
    assert actions.FREQUENCIES["weekly"] == "1"
    # id='FrequencyID' but the POST field is popup-toggle; posting the id does nothing.
    assert actions.FREQUENCY_FIELD == "popup-toggle"

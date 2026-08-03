"""Tests for the dashboard parser.

The parser is import-isolated from Home Assistant so these run without a HA
install; only beautifulsoup4 is needed.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from datetime import date
from pathlib import Path

import pytest

FIXTURE = Path(__file__).parent / "fixtures" / "dashboard.html"
API_PATH = (
    Path(__file__).parent.parent / "custom_components" / "freshharvest" / "api.py"
)


def _load_api():
    """Import api.py with aiohttp/yarl stubbed out."""
    if "aiohttp" not in sys.modules:
        stub = types.ModuleType("aiohttp")
        stub.ClientSession = object
        stub.ClientError = Exception
        sys.modules["aiohttp"] = stub
    if "yarl" not in sys.modules:
        try:
            import yarl  # noqa: F401
        except ImportError:
            stub = types.ModuleType("yarl")
            stub.URL = lambda value="": value
            sys.modules["yarl"] = stub
    spec = importlib.util.spec_from_file_location("fh_api", API_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["fh_api"] = module
    spec.loader.exec_module(module)
    return module


api = _load_api()


@pytest.fixture(name="snapshot")
def snapshot_fixture():
    return api.parse_dashboard(FIXTURE.read_text(encoding="utf-8"))


def test_account_level_fields(snapshot):
    assert snapshot.delivery_day == "Tuesdays"
    assert snapshot.next_delivery == date(2026, 8, 4)
    assert len(snapshot.orders) == 2


def test_next_order_is_the_locked_one(snapshot):
    """The next arrival is past its cutoff; the open cart is the one after it.

    Guards the trap that sank the first attempt: the locked cart carries the
    class `cart-contents-skipped`, which does not mean the user skipped it.
    """
    order = snapshot.next_order
    assert order.delivery_id == "2772590"
    assert order.delivery_date == date(2026, 8, 4)
    assert order.is_open is False


def test_next_order_totals_and_contents(snapshot):
    order = snapshot.next_order
    assert order.box_name == "Georgia Grown Small Box"
    assert (order.subtotal, order.tax, order.delivery_fee) == (105.88, 3.18, 0.0)
    assert order.total == 109.06
    assert [(i.quantity, i.name, i.unit) for i in order.items] == [
        (1, "Bolero Carrots", ".5 lb"),
        (2, "Georgia Peaches", "6 count"),
    ]
    assert [
        (a.name, a.price, a.quantity, a.unit) for a in order.addons
    ] == [("Black Mission Figs", 7.99, 1, "1 pint")]
    assert len(order.all_items) == 3


def test_open_order(snapshot):
    order = snapshot.open_order
    assert order.delivery_id == "2778336"
    assert order.delivery_date == date(2026, 8, 11)
    assert order.is_open is True
    assert order.shop_window == "Shop tomorrow"
    assert order.total == 39.98


def test_driver_tip_placeholder_is_not_money(snapshot):
    """'Add Tip' sits in a value slot but is not an amount."""
    assert api._money("Add Tip") is None
    assert api._money("$1,234.50") == 1234.50
    assert api._money("$0.00") == 0.0


def test_tab_date_rolls_over_the_year():
    """A January tab against a December anchor belongs to the next year."""
    assert api._parse_tab_date("Tue 1/5", date(2026, 12, 29)) == date(2027, 1, 5)
    assert api._parse_tab_date("Tue 8/11", date(2026, 8, 4)) == date(2026, 8, 11)
    assert api._parse_tab_date("no date here", date(2026, 8, 4)) is None


def test_unrecognised_markup_raises():
    with pytest.raises(api.FreshHarvestError):
        api.parse_dashboard("<html><body>signed out</body></html>")

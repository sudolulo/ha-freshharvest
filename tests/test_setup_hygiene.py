"""No entity may block its own setup on a portal round-trip.

Written after a real bug: the produce-box select listed the boxes on offer from
inside `async_added_to_hass`, one fetch per popup. On a slower connection those
fetches ran past Home Assistant's SLOW_SETUP_MAX_WAIT, the platform setup was
cancelled, and the whole config entry landed in `setup_error` — every entity
unavailable despite valid credentials.

Every portal call an entity makes goes through `self.coordinator.actions` or
`self.coordinator.client`, so awaiting either inside `async_added_to_hass` is
the shape of that bug. These parse the sources with `ast` rather than importing
them, so the suite still runs without Home Assistant installed.
"""

from __future__ import annotations

import ast
from pathlib import Path

COMPONENT = Path(__file__).parent.parent / "custom_components" / "freshharvest"
# Attribute names that only exist to reach the freshharvest.com portal.
NETWORK_ATTRS = {"actions", "client"}


def _attr_chain(node: ast.AST) -> set[str]:
    """Every attribute/name along a call's dotted func, e.g. a.b.c() -> {a,b,c}."""
    names: set[str] = set()
    while isinstance(node, ast.Attribute):
        names.add(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        names.add(node.id)
    return names


def _added_to_hass(filename: str) -> ast.AsyncFunctionDef | None:
    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "async_added_to_hass"
        ):
            return node
    return None


PLATFORMS = ["sensor.py", "binary_sensor.py", "switch.py", "button.py",
             "select.py", "todo.py"]


def test_no_platform_awaits_the_portal_during_setup():
    """`async_added_to_hass` must not await a coordinator.actions/client call."""
    offenders = []
    for filename in PLATFORMS:
        func = _added_to_hass(filename)
        if func is None:
            continue
        for node in ast.walk(func):
            if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
                if _attr_chain(node.value.func) & NETWORK_ATTRS:
                    offenders.append(f"{filename}:{node.lineno}")
    assert not offenders, (
        "portal round-trip awaited during entity setup (blocks setup, can "
        f"exceed SLOW_SETUP_MAX_WAIT): {offenders}"
    )


def test_select_still_loads_its_options_off_the_setup_path():
    """The fix must defer the listing, not delete it: the select still fetches
    its options, just in a background task rather than inline in setup."""
    source = (COMPONENT / "select.py").read_text(encoding="utf-8")
    assert "async_create_background_task" in source
    assert "async_list_baskets" in source

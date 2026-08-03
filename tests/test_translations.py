"""Every entity's translation_key must exist, and nothing may be orphaned.

These parse the platform sources with `ast` rather than importing them, so the
suite still runs without Home Assistant installed.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

COMPONENT = Path(__file__).parent.parent / "custom_components" / "freshharvest"
PLATFORMS = {
    "sensor": "sensor.py",
    "binary_sensor": "binary_sensor.py",
    "switch": "switch.py",
    "button": "button.py",
    "select": "select.py",
}


def declared_keys(filename: str) -> set[str]:
    """Collect every `translation_key="..."` literal in a module."""
    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    return {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.keyword)
        and node.arg == "translation_key"
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }


def attr_keys(filename: str) -> set[str]:
    """Collect `_attr_translation_key = "..."` assignments (entities without a
    description object declare their name this way)."""
    tree = ast.parse((COMPONENT / filename).read_text(encoding="utf-8"))
    return {
        node.value.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(
            getattr(t, "id", getattr(t, "attr", None)) == "_attr_translation_key"
            for t in node.targets
        )
        and isinstance(node.value, ast.Constant)
    }


@pytest.fixture(name="strings")
def strings_fixture() -> dict:
    return json.loads((COMPONENT / "strings.json").read_text(encoding="utf-8"))


def test_en_matches_strings(strings):
    """Custom integrations read translations/en.json; it must not drift."""
    english = json.loads(
        (COMPONENT / "translations" / "en.json").read_text(encoding="utf-8")
    )
    assert english == strings


@pytest.mark.parametrize("platform,filename", PLATFORMS.items())
def test_every_entity_has_a_name(strings, platform, filename):
    missing = declared_keys(filename) - set(strings["entity"][platform])
    assert not missing, f"{platform} keys with no translation: {sorted(missing)}"


@pytest.mark.parametrize("platform,filename", PLATFORMS.items())
def test_no_orphaned_translations(strings, platform, filename):
    orphans = set(strings["entity"][platform]) - declared_keys(filename)
    assert not orphans, f"{platform} translations with no entity: {sorted(orphans)}"


def test_manifest_is_well_formed():
    manifest = json.loads((COMPONENT / "manifest.json").read_text(encoding="utf-8"))
    for key in ("domain", "name", "version", "documentation", "issue_tracker"):
        assert manifest.get(key), f"manifest missing {key}"
    assert manifest["domain"] == "freshharvest"
    # A private forge URL would be unreachable for anyone installing this.
    for key in ("documentation", "issue_tracker"):
        assert manifest[key].startswith("https://github.com/"), (
            f"{key} must be a public URL, got {manifest[key]}"
        )


def test_todo_entity_is_named(strings):
    """todo.py declares its name via _attr_translation_key, not a description."""
    assert attr_keys("todo.py") == set(strings["entity"]["todo"])


def test_fire_action_call_sites_are_well_formed():
    """Every fire_action call passes (action, ok, target, detail).

    A refactor that moved this helper onto the base entity rewrote the call
    sites mechanically and left one with three arguments — a TypeError that
    only fires when a user presses the button, which no unit test reaches.
    """
    bad = []
    for path in COMPONENT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and getattr(node.func, "attr", None) == "fire_action"
                and len(node.args) != 4
            ):
                bad.append(f"{path.name}:{node.lineno} takes {len(node.args)}")
    assert not bad, f"malformed fire_action calls: {bad}"


def test_no_class_inherits_from_itself():
    """`class X(X, Mixin)` is legal Python and a maintenance trap; it was here."""
    for path in COMPONENT.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                names = {getattr(b, "id", None) for b in node.bases}
                assert node.name not in names, f"{path.name}: {node.name} inherits itself"

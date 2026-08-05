"""Permanent MRO guard for the canonical theme color resolver."""

from __future__ import annotations

import importlib
import inspect
import pkgutil

import kin.tui
from kin.tui.widgets.lifecycle import LifecycleWidgetMixin


def _lifecycle_widget_classes() -> list[type[LifecycleWidgetMixin]]:
    """Import and return every concrete TUI class using the lifecycle mixin."""
    classes: dict[str, type[LifecycleWidgetMixin]] = {}

    for module_info in pkgutil.walk_packages(
        kin.tui.__path__,
        prefix=f"{kin.tui.__name__}.",
    ):
        module = importlib.import_module(module_info.name)
        for candidate in vars(module).values():
            if not inspect.isclass(candidate):
                continue
            if candidate is LifecycleWidgetMixin:
                continue
            if candidate.__module__ != module.__name__:
                continue
            if not issubclass(candidate, LifecycleWidgetMixin):
                continue
            qualified_name = f"{candidate.__module__}.{candidate.__qualname__}"
            classes[qualified_name] = candidate

    assert classes, "No LifecycleWidgetMixin subclasses were discovered under kin.tui"
    return [classes[name] for name in sorted(classes)]


def test_lifecycle_widgets_never_shadow_canonical_c() -> None:
    """Every lifecycle widget must inherit ``_c`` instead of redefining it."""
    offenders = [
        f"{cls.__module__}.{cls.__qualname__}"
        for cls in _lifecycle_widget_classes()
        if "_c" in cls.__dict__
    ]

    assert not offenders, (
        "LifecycleWidgetMixin._c must be the one canonical color resolver; "
        "remove local '_c' definitions from: " + ", ".join(offenders)
    )

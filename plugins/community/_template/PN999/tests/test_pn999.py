# SPDX-License-Identifier: apache-2.0
"""Scaffolded test for community patch PN999.

The validator's R-5 rule requires at least one test file per `tests_required`
glob. This is the minimal coverage — replace with real assertions when the
patch logic lands.
"""
from __future__ import annotations


def test_patch_module_imports():
    """The apply hook must import cleanly (mirrors validator R-4)."""
    from plugins.community.sandermage.PN999 import patch
    assert callable(patch.apply)


def test_apply_returns_none_on_stub():
    """Default scaffold returns None. When you replace the body,
    update this assertion to match the real contract."""
    from plugins.community.sandermage.PN999 import patch
    assert patch.apply(target=None) is None

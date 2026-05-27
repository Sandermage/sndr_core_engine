# SPDX-License-Identifier: Apache-2.0
"""M.1.1.T3.A scaffolding tests for retired-patch declarative path.

Covers the empty-skeleton state of ``_RETIRED_PATCHES`` +
``_retired_patch_handler`` + ``_register_retired_patches`` without
touching the live :data:`apply._state.PATCH_REGISTRY` (the
``tests/unit/dispatcher/fixtures/apply_registry.json`` snapshot is
the byte-identity guard for the live registry).

T3.A invariants
───────────────
  * ``_RETIRED_PATCHES`` is exposed at module scope as a ``dict``.
  * In T3.A it is empty — no entries migrated yet; T3.B populates.
  * ``_retired_patch_handler(name, reason)`` returns a zero-arg
    callable that produces ``PatchResult(name, "skipped", reason)``.
  * ``_register_retired_patches()`` is callable and idempotent on the
    empty dict (call it twice → no growth in PATCH_REGISTRY).

The synthetic-population scenario (T3.B preview) is exercised via
``monkeypatch.setattr`` on the module-level ``_RETIRED_PATCHES`` so
the live registry is not mutated; the test captures the
pre-population registry length and asserts that exactly one new
entry is appended when a synthetic stub is registered, then
restores state.
"""
from __future__ import annotations

import pytest


def _import_dispatch_module():
    """Lazy import so the apply package's heavy decorator chain is
    only walked once per test session."""
    from vllm.sndr_core.apply import _per_patch_dispatch as mod
    return mod


# ─── Schema invariants (T3.A empty-skeleton) ──────────────────────────────


class TestRetiredPatchesScaffolding:
    """The declarative table exists, is the expected shape, and is
    empty until T3.B starts migrating retired stubs."""

    def test_retired_patches_dict_present(self):
        mod = _import_dispatch_module()
        assert hasattr(mod, "_RETIRED_PATCHES"), (
            "_RETIRED_PATCHES scaffolding missing from "
            "vllm.sndr_core.apply._per_patch_dispatch"
        )
        assert isinstance(mod._RETIRED_PATCHES, dict)

    def test_retired_patches_empty_in_t3a(self):
        """T3.A scaffolding ships the skeleton empty. Any entry here
        BEFORE T3.B starts migration would mean a stale leftover —
        fail loudly so the schema decision (sibling dict / tuple /
        dataclass) gets made deliberately."""
        mod = _import_dispatch_module()
        assert mod._RETIRED_PATCHES == {}, (
            "_RETIRED_PATCHES is non-empty in T3.A scaffolding — "
            "if T3.B has started migration, also update the snapshot "
            "fixture and this assertion in the same commit"
        )


# ─── _retired_patch_handler shape (callable, returns PatchResult) ─────────


class TestRetiredPatchHandler:
    """The handler factory builds a no-op apply() callable that
    matches the byte-identical behaviour of the hand-written retired
    stubs in this file."""

    def test_returns_callable(self):
        mod = _import_dispatch_module()
        handler = mod._retired_patch_handler("X", "Y")
        assert callable(handler)

    def test_callable_returns_patch_result(self):
        mod = _import_dispatch_module()
        from vllm.sndr_core.apply._state import PatchResult

        handler = mod._retired_patch_handler(
            "TEST-PATCH name (synthetic)",
            "retired 2026-05-27 (synthetic test)",
        )
        result = handler()
        assert isinstance(result, PatchResult)
        assert result.name == "TEST-PATCH name (synthetic)"
        assert result.status == "skipped"
        assert result.reason == "retired 2026-05-27 (synthetic test)"

    def test_callable_emits_skipped_each_call(self):
        """Stateless: invoking twice produces the same shape both
        times. Catches a future bug where someone caches the
        PatchResult object or mutates it on the first call."""
        mod = _import_dispatch_module()
        handler = mod._retired_patch_handler("A", "B")
        first = handler()
        second = handler()
        assert first.status == "skipped"
        assert second.status == "skipped"
        assert first.name == second.name == "A"
        assert first.reason == second.reason == "B"


# ─── _register_retired_patches behaviour ─────────────────────────────────


class TestRegisterRetiredPatches:
    """The registration loop iterates ``_RETIRED_PATCHES`` and routes
    each entry through ``register_patch``. T3.A: empty dict → no-op.
    Synthetic-population test below uses monkeypatch so the live
    registry stays clean."""

    def test_idempotent_on_empty_dict(self):
        mod = _import_dispatch_module()
        from vllm.sndr_core.apply import _state

        before_len = len(_state.PATCH_REGISTRY)
        mod._register_retired_patches()
        mod._register_retired_patches()
        after_len = len(_state.PATCH_REGISTRY)
        assert before_len == after_len, (
            "_register_retired_patches() must be a no-op on the empty "
            f"_RETIRED_PATCHES dict, got delta "
            f"{after_len - before_len}"
        )

    def test_synthetic_entry_registers_one_pair(self, monkeypatch):
        """T3.B preview: when ``_RETIRED_PATCHES`` carries entries,
        ``_register_retired_patches()`` appends one ``(name, callable)``
        tuple per entry to ``PATCH_REGISTRY``.

        Uses monkeypatch on the module-level dict so the live
        registry list is mutated only inside this test; the appended
        tuple is removed before the test exits so subsequent test
        modules + the snapshot fixture see the canonical state.
        """
        mod = _import_dispatch_module()
        from vllm.sndr_core.apply import _state

        synthetic_name = "M.1.1.T3.A.synthetic test patch"
        synthetic_reason = "retired (synthetic test only)"
        before_len = len(_state.PATCH_REGISTRY)

        monkeypatch.setitem(
            mod._RETIRED_PATCHES, synthetic_name, synthetic_reason,
        )
        try:
            mod._register_retired_patches()
            # The decorator appended exactly one tuple to
            # _state.PATCH_REGISTRY; verify shape + content.
            assert len(_state.PATCH_REGISTRY) == before_len + 1
            name, fn = _state.PATCH_REGISTRY[-1]
            assert name == synthetic_name
            assert callable(fn)
            # Invoking the registered callable still produces the
            # _skipped() result the handler factory wired in.
            result = fn()
            assert result.status == "skipped"
            assert result.name == synthetic_name
            assert result.reason == synthetic_reason
        finally:
            # Always restore registry length so other tests +
            # snapshot fixtures see byte-identical state.
            if len(_state.PATCH_REGISTRY) > before_len:
                del _state.PATCH_REGISTRY[before_len:]

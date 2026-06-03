# SPDX-License-Identifier: Apache-2.0
"""Unit tests for SNDR_EAGLE3_AUX_HIDDEN_001 — model-side preparation
for EAGLE-3 (arXiv 2503.01840) speculative decoding.

These tests run WITHOUT GPU and without vLLM target-model imports.
A minimal fake model class with a `.model.layers` attribute is used
to exercise the hook lifecycle, layer-id parsing, and pop semantics.
"""
from __future__ import annotations

import pytest

try:
    import torch
    HAS_TORCH = True
except ImportError:
    HAS_TORCH = False


# ──────────────────────────────────────────────────────────────────────
# Minimal fake target model — mimics vLLM's `model.model.layers` path
# ──────────────────────────────────────────────────────────────────────


class _FakeLayer:
    """Mimics a single transformer decoder layer's nn.Module interface
    enough to register forward hooks against."""

    def __init__(self, idx: int, hidden_dim: int):
        self.idx = idx
        self.hidden_dim = hidden_dim
        self._forward_hooks: list = []

    def register_forward_hook(self, hook):
        """Returns a RemovableHandle-like object."""
        handle = _FakeHandle(self, hook)
        self._forward_hooks.append((handle, hook))
        return handle

    def __call__(self, x):
        """Run the layer + fire hooks."""
        # Trivial transform — just identity for the test
        output = (x,)  # tuple shape matches real decoder
        for _h, hook in list(self._forward_hooks):
            result = hook(self, (x,), output)
            if result is not None:
                output = result
        return output


class _FakeHandle:
    def __init__(self, layer: _FakeLayer, hook):
        self._layer = layer
        self._hook = hook

    def remove(self):
        self._layer._forward_hooks = [
            (h, fn) for (h, fn) in self._layer._forward_hooks
            if h is not self
        ]


class _FakeInner:
    """Mimics `model.model` — exposes `.layers`."""

    def __init__(self, n_layers: int, hidden_dim: int):
        self.layers = [_FakeLayer(i, hidden_dim) for i in range(n_layers)]


class _FakeModel:
    """Mimics a vLLM target model — has `.model.layers`."""

    def __init__(self, n_layers: int = 32, hidden_dim: int = 128):
        self.model = _FakeInner(n_layers, hidden_dim)
        self.hidden_dim = hidden_dim


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────


def test_module_imports_without_torch():
    """Module-level import never explodes."""
    from vllm.sndr_core.integrations.spec_decode import sndr_eagle3_aux_hidden_001  # noqa: F401


def test_is_enabled_env_gate(monkeypatch):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        is_enabled,
    )
    monkeypatch.delenv("GENESIS_ENABLE_SNDR_EAGLE3_AUX_HIDDEN_001", raising=False)
    assert is_enabled() is False
    monkeypatch.setenv("GENESIS_ENABLE_SNDR_EAGLE3_AUX_HIDDEN_001", "1")
    assert is_enabled() is True
    monkeypatch.setenv("GENESIS_ENABLE_SNDR_EAGLE3_AUX_HIDDEN_001", "")
    assert is_enabled() is False


def test_parse_layer_ids_from_env_empty(monkeypatch):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        parse_layer_ids_from_env,
    )
    monkeypatch.delenv("GENESIS_SNDR_EAGLE3_AUX_LAYER_IDS", raising=False)
    assert parse_layer_ids_from_env() == []


def test_parse_layer_ids_from_env_canonical(monkeypatch):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        parse_layer_ids_from_env,
    )
    monkeypatch.setenv("GENESIS_SNDR_EAGLE3_AUX_LAYER_IDS", "0,4,8,12,31")
    assert parse_layer_ids_from_env() == [0, 4, 8, 12, 31]


def test_parse_layer_ids_skips_invalid(monkeypatch):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        parse_layer_ids_from_env,
    )
    # Mix of valid + non-int + negative + empty tokens
    monkeypatch.setenv("GENESIS_SNDR_EAGLE3_AUX_LAYER_IDS", "0,abc,-5, 4,,8")
    # Result skips "abc" and -5; whitespace tolerated
    assert parse_layer_ids_from_env() == [0, 4, 8]


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_register_hooks_returns_zero_with_empty_layer_ids():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=16, hidden_dim=64)
    count = register_aux_hidden_state_hooks(model, layer_ids=[])
    assert count == 0


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_register_hooks_attaches_to_requested_layers():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=16, hidden_dim=64)
    count = register_aux_hidden_state_hooks(model, layer_ids=[0, 7, 15])
    assert count == 3
    # The hooks land on the right layers
    assert len(model.model.layers[0]._forward_hooks) == 1
    assert len(model.model.layers[7]._forward_hooks) == 1
    assert len(model.model.layers[15]._forward_hooks) == 1
    # Non-targeted layers have no hooks
    assert len(model.model.layers[1]._forward_hooks) == 0
    assert len(model.model.layers[8]._forward_hooks) == 0


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_register_hooks_idempotent_on_double_call():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=16, hidden_dim=64)
    n1 = register_aux_hidden_state_hooks(model, layer_ids=[0, 7])
    n2 = register_aux_hidden_state_hooks(model, layer_ids=[0, 7])
    assert n1 == 2 and n2 == 2
    # Hooks attached only once per layer
    assert len(model.model.layers[0]._forward_hooks) == 1
    assert len(model.model.layers[7]._forward_hooks) == 1


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_register_hooks_skips_out_of_range_indices(caplog):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=8, hidden_dim=32)
    # 99 is out of range
    count = register_aux_hidden_state_hooks(model, layer_ids=[0, 3, 99])
    assert count == 2  # 0 + 3 land, 99 skipped


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_register_hooks_uses_env_layer_ids_when_none_passed(monkeypatch):
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    monkeypatch.setenv("GENESIS_SNDR_EAGLE3_AUX_LAYER_IDS", "1,5,9")
    model = _FakeModel(n_layers=16, hidden_dim=64)
    count = register_aux_hidden_state_hooks(model, layer_ids=None)
    assert count == 3


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_capture_appends_to_aux_buffer_on_forward():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=8, hidden_dim=32)
    register_aux_hidden_state_hooks(model, layer_ids=[0, 4, 7])
    # Fire the hooked layers
    x = torch.randn(2, 5, 32)
    model.model.layers[0](x)
    model.model.layers[4](x)
    model.model.layers[7](x)
    # Buffer holds 3 captures
    states = model._sndr_eagle3_aux_hidden_states
    assert len(states) == 3
    for s in states:
        assert s.shape == (2, 5, 32)


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_pop_aux_hidden_states_returns_stacked_and_clears():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
        pop_aux_hidden_states,
    )
    model = _FakeModel(n_layers=8, hidden_dim=32)
    register_aux_hidden_state_hooks(model, layer_ids=[0, 4, 7])
    x = torch.randn(2, 5, 32)
    model.model.layers[0](x)
    model.model.layers[4](x)
    model.model.layers[7](x)
    stacked = pop_aux_hidden_states(model)
    # Shape (num_layers_hooked, B, S, D)
    assert stacked.shape == (3, 2, 5, 32)
    # Buffer cleared
    assert model._sndr_eagle3_aux_hidden_states == []


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_pop_returns_none_on_empty_buffer():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        pop_aux_hidden_states,
    )
    model = _FakeModel(n_layers=4, hidden_dim=16)
    assert pop_aux_hidden_states(model) is None


@pytest.mark.skipif(not HAS_TORCH, reason="torch required")
def test_clear_removes_all_handles():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        register_aux_hidden_state_hooks,
        clear_aux_hidden_state_hooks,
    )
    model = _FakeModel(n_layers=8, hidden_dim=32)
    register_aux_hidden_state_hooks(model, layer_ids=[0, 4, 7])
    n = clear_aux_hidden_state_hooks(model)
    assert n == 3
    # All hook lists empty
    for i in (0, 4, 7):
        assert len(model.model.layers[i]._forward_hooks) == 0
    # Idempotent second call
    assert clear_aux_hidden_state_hooks(model) == 0


def test_apply_returns_idempotent_marker():
    """apply() returns (status, reason) tuple — compatible with both
    the legacy @register_patch wrapper AND the spec-driven orchestrator
    that unpacks as `status, reason = mod.apply()`."""
    from vllm.sndr_core.integrations.spec_decode import (
        sndr_eagle3_aux_hidden_001 as mod,
    )
    # Reset marker for isolation
    mod.__dict__.pop("_genesis_sndr_eagle3_001_applied", None)
    r1 = mod.apply()
    # Verify it's a 2-tuple (not a dict — that was the v11.3.0 bug)
    assert isinstance(r1, tuple), (
        f"apply() must return tuple, got {type(r1).__name__}. "
        f"Dict return broke spec-driven orchestrator's "
        f"`status, reason = mod.apply()` unpack."
    )
    assert len(r1) == 2
    status1, reason1 = r1
    assert status1 == "applied"
    r2 = mod.apply()
    assert isinstance(r2, tuple) and len(r2) == 2
    status2, reason2 = r2
    assert status2 == "skipped"
    assert "already applied" in reason2


def test_apply_unpacks_in_spec_driven_orchestrator_pattern():
    """Verify the spec-driven orchestrator's `status, reason = mod.apply()`
    works without TypeError — the unpack pattern that was broken by the
    pre-v11.3.0 dict return."""
    from vllm.sndr_core.integrations.spec_decode import (
        sndr_eagle3_aux_hidden_001 as mod,
    )
    mod.__dict__.pop("_genesis_sndr_eagle3_001_applied", None)
    # This unpack would TypeError with the buggy dict return
    status, reason = mod.apply()
    assert status in ("applied", "skipped", "failed")
    assert isinstance(reason, str)


def test_resolve_layers_finds_canonical_path():
    """The _resolve_layers helper finds .model.layers."""
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        _resolve_layers,
    )
    model = _FakeModel(n_layers=4, hidden_dim=16)
    layers = _resolve_layers(model)
    assert layers is not None
    assert len(layers) == 4


def test_resolve_layers_returns_none_on_unknown_shape():
    from vllm.sndr_core.integrations.spec_decode.sndr_eagle3_aux_hidden_001 import (
        _resolve_layers,
    )

    class _Empty:
        pass

    assert _resolve_layers(_Empty()) is None

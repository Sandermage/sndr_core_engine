# SPDX-License-Identifier: Apache-2.0
"""PN282 / PN248 forward-proof wrapper regression test (dev491 drift).

dev491 grew rejection_sample()'s signature with use_fp64_gumbel (after the
earlier synthetic_mode / synthetic_conditional_rates), and RejectionSampler.
forward passes it UNCONDITIONALLY (rejection_sampler.py:182-184). The PN282
metric + PN248 trace wrappers must forward ANY signature transparently
(*args/**kwargs) so the next kwarg can never crash a spec-decode step — and
the side-channel must still recover max_spec_len via signature binding.

Guards commit "forward-proof PN282/PN248 wrappers" (2026-06-16). Self-mocks
vllm so it runs without a GPU / real vllm install.
"""
import sys
import types


class _FakeTensor:
    def __init__(self, rows):
        self._rows = rows
        self.shape = (len(rows), len(rows[0]) if rows else 0)

    def detach(self):
        return self

    def cpu(self):
        return self

    def tolist(self):
        return self._rows

    def argmax(self, dim=-1):
        return _FakeTensor([[max(range(len(r)), key=lambda i: r[i])] for r in self._rows])


def _install_fake_rejection_sampler(received):
    """Inject a fake vllm rejection_sampler whose rejection_sample carries a
    FUTURE-style signature (use_fp64_gumbel + a hypothetical extra kwarg)."""
    for name in ("vllm", "vllm.v1", "vllm.v1.sample"):
        sys.modules.setdefault(name, types.ModuleType(name))
    mod = types.ModuleType("vllm.v1.sample.rejection_sampler")

    def rejection_sample(draft_token_ids, num_draft_tokens, max_spec_len,
                         cu_num_draft_tokens, draft_probs, target_logits,
                         bonus_token_ids, sampling_metadata,
                         synthetic_mode=False, synthetic_conditional_rates=None,
                         use_fp64_gumbel=False, future_kwarg=None):
        received["use_fp64_gumbel"] = use_fp64_gumbel
        received["future_kwarg"] = future_kwarg
        received["max_spec_len"] = max_spec_len
        return _FakeTensor([[5, 1, 2, -1]])  # bonus + 2 accepted + 1 reject

    mod.rejection_sample = rejection_sample
    mod.PLACEHOLDER_TOKEN_ID = -1
    sys.modules["vllm.v1.sample.rejection_sampler"] = mod
    sys.modules["vllm.v1.sample"].rejection_sampler = mod
    return mod


def _call_args():
    return ([1], [2], 3, [0, 1], None, _FakeTensor([[0.1, 0.9, 0.0, 0.0]]), [5], object())


def test_pn282_forwards_future_kwargs_transparently(monkeypatch):
    received = {}
    mod = _install_fake_rejection_sampler(received)
    rec = {}
    import sndr.observability.spec_decode_metrics as metrics
    monkeypatch.setattr(metrics, "is_enabled", lambda: True)
    monkeypatch.setattr(
        metrics, "record_acceptance",
        lambda accepted, k: rec.update(accepted=accepted, k=k),
    )

    from sndr.engines.vllm.patches.observability import (
        pn282_spec_decode_acceptance_metric as pn282,
    )
    monkeypatch.setattr(pn282, "_placeholder_token_id", lambda: -1, raising=False)
    pn282._APPLIED = False
    pn282._ORIGINAL_REJECTION_SAMPLE = None

    assert pn282.apply()[0] == "applied"
    # the NEW use_fp64_gumbel kwarg + a hypothetical future kwarg must forward
    mod.rejection_sample(*_call_args(), use_fp64_gumbel=True, future_kwarg="x")
    assert received["use_fp64_gumbel"] is True   # forwarded, no TypeError
    assert received["future_kwarg"] == "x"        # forward-proof against the NEXT drift
    assert rec.get("accepted") == [2]             # side-channel still records (2 accepted)
    assert rec.get("k") == 3                       # max_spec_len recovered via signature bind
    pn282.revert()


def test_pn248_forwards_future_kwargs_transparently(monkeypatch, tmp_path):
    import pytest
    pytest.importorskip("torch")  # PN248 imports torch at module level
    received = {}
    mod = _install_fake_rejection_sampler(received)

    from sndr.engines.vllm.patches.spec_decode.probes import (
        pn248_acceptance_trace as pn248,
    )
    monkeypatch.setattr(pn248, "_LOG_PATH", str(tmp_path / "pn248.log"), raising=False)
    pn248._APPLIED = False
    pn248._ORIGINAL_REJECTION_SAMPLE = None
    pn248._CALL_IDX[0] = 0

    assert pn248.apply()[0] == "applied"
    out = mod.rejection_sample(*_call_args(), use_fp64_gumbel=True, future_kwarg="x")
    assert received["use_fp64_gumbel"] is True
    assert received["future_kwarg"] == "x"
    assert out.tolist() == [[5, 1, 2, -1]]        # result returned unchanged
    pn248.revert()

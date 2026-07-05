# SPDX-License-Identifier: Apache-2.0
"""TDD for P107 — MTP truncation detector (vllm#41467)."""
from __future__ import annotations

from tests.unit.anchor_sot._pin_manifest_assert import (
    assert_anchor_recorded,
    assert_variant_inactive,
)


def _wiring():
    from sndr.engines.vllm.patches.serving import p107_mtp_truncation_detector as M
    return M


def test_anchor_targets_finish_reason_block():
    M = _wiring()
    # v2 anchor (2026-06-08): upstream dropped the ``auto_tools_called``
    # OR-clause from the if-head — the anchor now keys on the
    # ``tools_streamed[i]`` / ``use_harmony`` conditional instead.
    assert "tools_streamed[i]" in M.ANCHOR_OLD
    assert "self.use_harmony" in M.ANCHOR_OLD
    assert "tool_choice_function_name" in M.ANCHOR_OLD
    assert "finish_reason_ = \"tool_calls\"" in M.ANCHOR_OLD
    assert "ChatCompletionResponseStreamChoice" in M.ANCHOR_OLD


def test_replacement_adds_p107_guard():
    M = _wiring()
    assert "P107" in M.ANCHOR_NEW
    assert "vllm#41467" in M.ANCHOR_NEW
    assert "MTP truncation detected" in M.ANCHOR_NEW
    assert "MTP speculative decoding truncated" in M.ANCHOR_NEW
    # All AND conditions must be present
    assert "finish_reason_ == \"stop\"" in M.ANCHOR_NEW
    assert "and request.tools" in M.ANCHOR_NEW
    assert "and not tools_streamed[i]" in M.ANCHOR_NEW
    assert "and reasoning_parser is not None" in M.ANCHOR_NEW
    assert "and not delta_message.content" in M.ANCHOR_NEW
    assert "and not delta_message.tool_calls" in M.ANCHOR_NEW
    # v3 (2026-06-11): ``auto_tools_called`` does NOT exist in the
    # streaming generator on pin 0.22.1rc1.dev259 — v2's injected
    # ``and not auto_tools_called`` clause was a latent NameError at
    # stream end (caught by fleet validation 2026-06-11). The clause
    # must stay OUT of the replacement.
    assert "auto_tools_called" not in M.ANCHOR_NEW


# ─── dev491 anchor variant (pin bump dev259 → dev491, vllm#45171) ────────


def test_dev491_anchor_targets_single_line_if_head():
    """vllm#45171 dropped the harmony OR-clause from the if-head — the
    dev491 streaming finish_reason block is the single-line
    ``if tools_streamed[i] and not tool_choice_function_name:`` form."""
    M = _wiring()
    assert (
        "if tools_streamed[i] and not tool_choice_function_name:\n"
        in M.ANCHOR_DEV491_OLD
    )
    # The dropped harmony OR-clause must NOT be in the dev491 anchor.
    assert "self.use_harmony" not in M.ANCHOR_DEV491_OLD
    assert "harmony_tools_streamed" not in M.ANCHOR_DEV491_OLD
    assert "finish_reason_ = \"tool_calls\"" in M.ANCHOR_DEV491_OLD
    assert "ChatCompletionResponseStreamChoice" in M.ANCHOR_DEV491_OLD


def test_dev491_replacement_uses_unified_parser_not_reasoning_parser():
    """dev491 unified the parser: ``reasoning_parser`` is no longer a local
    in the stream generator (referencing it would raise NameError at stream
    end — the dev259-v2 bug class). The guard keys on ``parser is not
    None`` instead."""
    M = _wiring()
    assert "and parser is not None" in M.ANCHOR_DEV491_NEW
    # The CODE must not reference the removed ``reasoning_parser`` local
    # (the explanatory comment may name it; the guard expression must not).
    assert "reasoning_parser is not None" not in M.ANCHOR_DEV491_NEW
    assert "and reasoning_parser" not in M.ANCHOR_DEV491_NEW
    # ``auto_tools_called`` does not exist in the dev491 stream generator.
    assert "auto_tools_called" not in M.ANCHOR_DEV491_NEW


def test_dev491_replacement_raises_module_level_generation_error():
    """dev491 already imports GenerationError at module level and wraps the
    generator in ``except GenerationError`` — raise it directly. No fragile
    local import (the dev259 variant's ``chat_completion.protocol`` import
    path does not export GenerationError)."""
    M = _wiring()
    assert "raise GenerationError(" in M.ANCHOR_DEV491_NEW
    # No local import in the dev491 variant.
    assert "import GenerationError" not in M.ANCHOR_DEV491_NEW
    assert "_P107_GenError" not in M.ANCHOR_DEV491_NEW


def test_dev491_emitted_text_stable_for_pn288_chain():
    """PN288 chains on P107's output (CHAINED_ANCHOR). The dev491 variant's
    emitted warning + raise message must be IDENTICAL to the dev259 variant
    so the PN288 chain resolves unchanged across the pin bump."""
    M = _wiring()
    for needle in (
        "[Genesis P107 vllm#41467] MTP truncation detector.",
        "[Genesis P107] MTP truncation detected for request %s: ",
        "MTP speculative decoding truncated tool call ",
        "generation. Please retry.",
    ):
        assert needle in M.ANCHOR_NEW, needle
        assert needle in M.ANCHOR_DEV491_NEW, needle


def test_dev491_replacement_preserves_bare_block_for_pn288():
    """P107's dev491 ANCHOR_NEW must keep the bare finish_reason block
    (PN288's future dev491 streaming anchor) verbatim exactly once, so the
    P107-then-PN288 chain still composes."""
    M = _wiring()
    bare_block = (
        "                        if tools_streamed[i] and not tool_choice_function_name:\n"
        "                            finish_reason_ = \"tool_calls\"\n"
        "                        else:\n"
        "                            finish_reason_ = (\n"
        "                                output.finish_reason if output.finish_reason else \"stop\"\n"
        "                            )\n"
    )
    assert M.ANCHOR_DEV491_OLD.startswith(bare_block)
    assert M.ANCHOR_DEV491_NEW.count(bare_block) == 1


def test_dev491_variant_registered_required_at_least_one():
    """Both pin variants are required=False (PN351 convention); apply()
    asserts at least one fired. The dev491 variant name is registered."""
    M = _wiring()
    assert "p107_mtp_truncation_dev491" in M._VARIANT_NAMES
    assert "p107_mtp_truncation" in M._VARIANT_NAMES


def test_dev259_variant_no_self_collision():
    """The dev259 ANCHOR_OLD must NOT appear in ANCHOR_DEV491_NEW (or a
    marker-less re-apply could mis-target across variants)."""
    M = _wiring()
    assert M.ANCHOR_OLD not in M.ANCHOR_DEV491_NEW
    assert M.ANCHOR_DEV491_OLD not in M.ANCHOR_NEW


def test_anchors_byte_exact_mutually_exclusive_per_pin():
    """Iron rule #11: exactly one variant fires per pin. MIGRATED (audit #14)
    from a byte-check against two stale-pin trees (dev259 + dev491, absent on
    every CI host -> green-by-skip) to the COMMITTED per-pin manifest. On the
    current pin the DEV491 variant is recorded active and the DEV259 variant
    is recorded under no sub — the CI-runnable form of
    ``dev491.count(DEV491_OLD)==1`` + ``count(DEV259_OLD)==0``. Ties the LIVE
    variant CONSTANTS to the recorded pristine bytes."""
    M = _wiring()
    assert_anchor_recorded(
        "P107", "p107_mtp_truncation_dev491", M.ANCHOR_DEV491_OLD
    )
    assert_variant_inactive("P107", M.ANCHOR_OLD)


def test_idempotent_on_synthetic(tmp_path):
    from sndr.kernel.text_patch import (
        TextPatch, TextPatcher, TextPatchResult,
    )
    M = _wiring()
    target = tmp_path / "serving.py"
    target.write_text("# header\n" + M.ANCHOR_OLD + "\n# tail\n")
    patcher = TextPatcher(
        patch_name="P107 test",
        target_file=str(target),
        marker=M.GENESIS_P107_MARKER,
        sub_patches=[TextPatch(name="p107", anchor=M.ANCHOR_OLD,
                                replacement=M.ANCHOR_NEW, required=True)],
    )
    r1, _ = patcher.apply()
    assert r1 == TextPatchResult.APPLIED
    body1 = target.read_text()
    assert "P107" in body1
    r2, _ = patcher.apply()
    assert r2 == TextPatchResult.IDEMPOTENT


def test_env_flag_default_off(monkeypatch):
    from sndr.dispatcher import should_apply
    monkeypatch.delenv("GENESIS_ENABLE_P107_MTP_TRUNCATION_DETECTOR", raising=False)
    decision, _ = should_apply("P107")
    assert decision is False


def test_env_flag_engages(monkeypatch):
    from sndr.dispatcher import should_apply
    monkeypatch.setenv("GENESIS_ENABLE_P107_MTP_TRUNCATION_DETECTOR", "1")
    decision, _ = should_apply("P107")
    assert decision is True


def test_registry_entry_complete():
    from sndr.dispatcher import PATCH_REGISTRY
    assert "P107" in PATCH_REGISTRY
    meta = PATCH_REGISTRY["P107"]
    assert meta["upstream_pr"] == 41467


def test_apply_all_registers_p107():
    from sndr.apply import apply_all
    assert hasattr(apply_all, "apply_patch_107_mtp_truncation_detector")

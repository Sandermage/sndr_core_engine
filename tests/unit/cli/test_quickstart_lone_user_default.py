# SPDX-License-Identifier: Apache-2.0
"""Zero-decision default must be lone-user-SAFE, not peak-throughput.

Fast-follow to the UX wizard: the fit ranking sorts by measured metric
desc, so `-multiconc` presets (aggregate TPS, ~100% per-card VRAM at
max_num_seqs=8) outrank the single-stream `balanced` preset. A newcomer
running `sndr quickstart` with no flags gets no benefit from multiconc but
takes its OOM risk — the auto-default must prefer the balanced/single-conc
preset (matching what the README documents as the lone-user default).
"""
from __future__ import annotations

from sndr.cli.commands.quickstart import _lone_user_first


def test_non_multiconc_preset_ranks_first_for_the_auto_default():
    fitting = [
        "prod-qwen3.6-35b-multiconc",
        "prod-qwen3.6-35b-balanced",
    ]
    assert _lone_user_first(fitting)[0] == "prod-qwen3.6-35b-balanced"


def test_unchanged_when_top_is_not_multiconc():
    fitting = ["prod-gemma4-26b-default", "prod-qwen3.6-27b-tq-k8v4"]
    assert _lone_user_first(fitting) == fitting


def test_cross_model_order_untouched_no_same_model_sibling():
    # a-multiconc leads but has no same-model non-multiconc sibling -> stays
    # (surgical: only swaps for its OWN sibling, never changes the model)
    fitting = ["prod-a-multiconc", "prod-b-balanced"]
    assert _lone_user_first(fitting) == fitting


def test_multiconc_leader_swapped_for_same_model_sibling_only():
    fitting = ["prod-qwen3.6-35b-multiconc", "prod-gemma4-31b-chat",
               "prod-qwen3.6-35b-balanced"]
    out = _lone_user_first(fitting)
    assert out[0] == "prod-qwen3.6-35b-balanced"  # same-model sibling promoted
    assert set(out) == set(fitting)  # nothing dropped
    assert "prod-gemma4-31b-chat" in out  # cross-model entry preserved

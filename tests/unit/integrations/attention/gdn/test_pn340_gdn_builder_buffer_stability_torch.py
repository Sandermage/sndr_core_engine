# SPDX-License-Identifier: Apache-2.0
"""Buffer-stability tests for the PN340-patched GDN metadata builder —
port of the vllm#44880 test SHAPE (torch group).

Upstream PR #44880 (Bailing MTP + LINEAR_ATTN spec-decode) is NOT
vendored — the pin's gdn_attn.py already carries the design its
linear_attn.py changes introduce (roadmap chunk-4 verdict). What we DO
take is its test discipline
(tests/v1/attention/test_linear_attention_metadata_builder.py):

  1. ``..._full_graph_metadata_uses_stable_decode_buffers`` —
     consecutive ``build()`` calls in FULL-cudagraph decode mode must
     hand out views of the SAME persistent buffers (``data_ptr``
     identity). A fresh tensor between builds means a captured graph
     replays against a stale address — the silent state-corruption
     class on the PROD full-CG MTP K=3 path.
  2. ``..._spec_decode_full_graph_metadata_pads_cache_slots`` — rows
     beyond the live spec-decode count must be deterministically
     padded, never ``torch.empty`` garbage.

GDN adaptation of the pad constants (upstream's linear_attn builder
pads state slots with ``PAD_SLOT_ID == -1``; the GDN builder pads
with):
  - ``NULL_BLOCK_ID`` (0)  for ``spec_state_indices_tensor`` rows
  - ``False``              for ``spec_sequence_masks``
  - ``1``                  for ``num_accepted_tokens``
  - the last cumulative    for ``spec_query_start_loc``
    token count

Why against the PN340-PATCHED builder: PN340 (vendor of vllm#43955)
rewrites exactly this buffer story — ``spec_token_indx`` becomes a
slice of the preallocated ``spec_token_arange`` buffer and the
redundant ``copy_`` is skipped. These tests pin down that the patched
builder still returns CG-stable, correctly-padded views (the
regression shield #44880's suite gives upstream's linear_attn, applied
to OUR hot path). Fixtures use non-zero garbage block ids in padded
rows so a missing NULL fill cannot pass by accident.

This file imports torch at module level and is auto-skipped on
torch-less hosts by the tests/conftest.py AST scan; run it inside the
vLLM container (or any torch+vllm-capable host — CUDA NOT required):

  python3 -m pytest \
      tests/unit/integrations/attention/gdn/test_pn340_gdn_builder_buffer_stability_torch.py -v

Requires the pristine pin tree at /private/tmp/candidate_pin_current
(same contract as tools/pin_preflight.py) — skipped when absent.

NOTE on scope: PN370's gdn sub-fix (``batch_size = m.num_reqs``) is a
SEPARATE patch (default OFF) — these tests exercise the
pristine-shaped sizing (``m.num_actual_tokens``) with PN340 applied,
i.e. today's default-ON overlay state. Composition with PN370 is
covered by test_pn370_async_accepted_counts_race.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

torch = pytest.importorskip(
    "torch", reason="buffer-stability test exercises real torch tensor identity"
)
pytest.importorskip(
    "vllm", reason="requires an installed vllm matching the candidate pin"
)

PIN_TREE = Path("/private/tmp/candidate_pin_current/vllm")
PIN_GDN = PIN_TREE / "v1" / "attention" / "backends" / "gdn_attn.py"

pytestmark = pytest.mark.skipif(
    not PIN_GDN.is_file(),
    reason="pristine pin tree not present on this machine",
)

DEVICE = torch.device("cpu")
BLOCK_SIZE = 16


def _pn340_patcher(target: Path):
    """PN340's three sub-patches rebuilt from its module constants
    (PN340.apply() builds its patcher inline — no _make seam; same
    technique as the PN341 probe in
    test_pn370_async_accepted_counts_race.py)."""
    from sndr.engines.vllm.patches.attention.gdn import (
        pn340_mtp_decode_bubbles_gdn_attn as pn340,
    )
    from sndr.kernel import TextPatch, TextPatcher

    return TextPatcher(
        patch_name="pn340-buffer-stability-probe",
        target_file=str(target),
        marker=pn340.GENESIS_PN340_MARKER,
        sub_patches=[
            TextPatch(
                name="pn340_init_spec_token_arange",
                anchor=pn340.PN340_INIT_OLD,
                replacement=pn340.PN340_INIT_NEW,
                required=False,
            ),
            TextPatch(
                name="pn340_build_slice_instead_of_mask",
                anchor=pn340.PN340_BUILD_OLD,
                replacement=pn340.PN340_BUILD_NEW,
                required=False,
            ),
            TextPatch(
                name="pn340_build_conditional_copy",
                anchor=pn340.PN340_COPY_OLD,
                replacement=pn340.PN340_COPY_NEW,
                required=False,
            ),
        ],
        upstream_drift_markers=[
            "[Genesis PN340",
        ],
    )


@pytest.fixture(scope="module")
def gdn_module(tmp_path_factory):
    """The pin's gdn_attn.py with PN340 applied (ALL three sub-patches
    must fire — a partial apply is exactly the half-vendored state the
    buffer assertions below would mis-certify), loaded standalone."""
    from sndr.kernel import TextPatchResult

    tmp_dir = tmp_path_factory.mktemp("pn340_gdn")
    target = tmp_dir / "gdn_attn.py"
    target.write_text(PIN_GDN.read_text(encoding="utf-8"), encoding="utf-8")

    patcher = _pn340_patcher(target)
    result, failure = patcher.apply()
    assert result == TextPatchResult.APPLIED, failure
    assert sorted(patcher.applied_sub_patches) == [
        "pn340_build_conditional_copy",
        "pn340_build_slice_instead_of_mask",
        "pn340_init_spec_token_arange",
    ], patcher.applied_sub_patches

    spec = importlib.util.spec_from_file_location(
        "genesis_pn340_patched_gdn_attn", str(target)
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _make_builder(gdn_module, monkeypatch, num_spec: int, max_num_seqs: int = 4):
    """GDNAttentionMetadataBuilder on CPU with a minimal config carrying
    ONLY the fields the builder reads (compilation/speculative/
    scheduler/cache/parallel). The prefill-backend resolver is pinned to
    'triton' — it inspects model_config + CUDA capability, both
    irrelevant for the decode-only FULL-CG path under test."""
    import vllm.model_executor.layers.mamba.gdn.qwen_gdn_linear_attn as qwen_gdn
    from vllm.config import CUDAGraphMode
    from vllm.v1.kv_cache_interface import MambaSpec

    monkeypatch.setattr(
        qwen_gdn,
        "_resolve_gdn_prefill_backend",
        lambda vllm_config: ("auto", "triton"),
    )

    vllm_config = SimpleNamespace(
        compilation_config=SimpleNamespace(
            cudagraph_mode=CUDAGraphMode.FULL_DECODE_ONLY,
            max_cudagraph_capture_size=None,
        ),
        speculative_config=SimpleNamespace(
            num_speculative_tokens=num_spec,
            parallel_drafting=False,
        ),
        scheduler_config=SimpleNamespace(max_num_seqs=max_num_seqs),
        cache_config=SimpleNamespace(mamba_cache_mode="none"),
        parallel_config=SimpleNamespace(decode_context_parallel_size=1),
        additional_config={},
    )
    kv_cache_spec = MambaSpec(
        block_size=BLOCK_SIZE,
        shapes=((16, 64),),
        dtypes=(torch.float16,),
        num_speculative_blocks=num_spec,
    )
    return gdn_module.GDNAttentionMetadataBuilder(
        kv_cache_spec=kv_cache_spec,
        layer_names=["model.layers.0.linear_attn"],
        vllm_config=vllm_config,
        device=DEVICE,
    )


def _common_metadata(
    query_lens: list[int],
    seq_lens: list[int],
    block_table: list[list[int]],
    num_actual_tokens: int,
):
    """CPU CommonAttentionMetadata for a FULL-CG decode batch. Padded
    (zero-length) rows sit at the back, exactly as the runner's
    spec-decode compaction guarantees."""
    from vllm.v1.attention.backend import CommonAttentionMetadata

    qsl = torch.zeros(len(query_lens) + 1, dtype=torch.int32)
    torch.cumsum(torch.tensor(query_lens, dtype=torch.int32), 0, out=qsl[1:])
    return CommonAttentionMetadata(
        query_start_loc=qsl,
        query_start_loc_cpu=qsl.clone(),
        seq_lens=torch.tensor(seq_lens, dtype=torch.int32),
        num_reqs=len(query_lens),
        num_actual_tokens=num_actual_tokens,
        max_query_len=max(query_lens),
        max_seq_len=max(seq_lens),
        block_table_tensor=torch.tensor(block_table, dtype=torch.int32),
        slot_mapping=torch.zeros(num_actual_tokens, dtype=torch.int64),
    )


def _build_spec_batch(
    builder,
    query_lens,
    seq_lens,
    block_table,
    num_actual_tokens,
    accepted,
    draft_per_req,
):
    common = _common_metadata(query_lens, seq_lens, block_table, num_actual_tokens)
    return builder.build(
        common_prefix_len=0,
        common_attn_metadata=common,
        num_accepted_tokens=torch.tensor(accepted, dtype=torch.int32),
        num_decode_draft_tokens_cpu=torch.tensor(draft_per_req, dtype=torch.int32),
    )


# ─────────────────────────────────────────────────────────────────────
# 1. Pad semantics — port of #44880's "pads_cache_slots" test
# ─────────────────────────────────────────────────────────────────────


def test_gdn_spec_decode_full_graph_metadata_pads_cache_slots(
    gdn_module, monkeypatch
):
    """2 live spec decodes + 1 padded row (K=1, the upstream test
    shape): every per-request view must pad the dead rows with the
    builder's deterministic constants — never empty()-garbage. Padded
    row carries non-zero garbage block ids on purpose."""
    builder = _make_builder(gdn_module, monkeypatch, num_spec=1)
    md = _build_spec_batch(
        builder,
        query_lens=[2, 2, 0],
        seq_lens=[20, 20, 0],
        block_table=[[10, 11], [12, 13], [7, 8]],
        num_actual_tokens=6,
        accepted=[1, 2, 1],
        draft_per_req=[1, 1, -1],
    )
    NULL_BLOCK_ID = gdn_module.NULL_BLOCK_ID

    assert md.num_spec_decodes == 2
    assert md.num_prefills == 0
    assert md.num_decodes == 0
    assert md.num_spec_decode_tokens == 4

    # Live rows: faithful copies of the block table front rows.
    assert md.spec_state_indices_tensor is not None
    assert md.spec_state_indices_tensor[:2].tolist() == [[10, 11], [12, 13]]
    # Pad rows (>= num_spec_decodes): NULL_BLOCK_ID, not garbage.
    assert torch.equal(
        md.spec_state_indices_tensor[2:],
        torch.full_like(md.spec_state_indices_tensor[2:], NULL_BLOCK_ID),
    )

    assert md.spec_sequence_masks is not None
    assert md.spec_sequence_masks[:2].tolist() == [True, True]
    assert not md.spec_sequence_masks[2:].any()

    assert md.num_accepted_tokens is not None
    assert md.num_accepted_tokens[:2].tolist() == [1, 2]
    assert torch.equal(
        md.num_accepted_tokens[2:],
        torch.ones_like(md.num_accepted_tokens[2:]),
    )

    assert md.spec_query_start_loc is not None
    assert md.spec_query_start_loc.tolist() == [0, 2, 4, 4, 4, 4, 4]

    # PN340 contract: spec_token_indx is the arange-buffer slice
    # (identity indices — spec rows are compacted to the front).
    assert md.spec_token_indx is not None
    assert md.spec_token_indx.tolist() == [0, 1, 2, 3]
    assert md.spec_token_indx.data_ptr() == builder.spec_token_arange.data_ptr()


# ─────────────────────────────────────────────────────────────────────
# 2. data_ptr identity — port of #44880's "stable_decode_buffers" test
# ─────────────────────────────────────────────────────────────────────


def test_gdn_full_graph_metadata_uses_stable_decode_buffers(
    gdn_module, monkeypatch
):
    """Two consecutive builds (different live batches, same captured
    token budget) must return views of the SAME persistent buffers,
    with the second build's contents fully refreshed."""
    builder = _make_builder(gdn_module, monkeypatch, num_spec=1)

    first = _build_spec_batch(
        builder,
        query_lens=[2, 2, 0],
        seq_lens=[20, 20, 0],
        block_table=[[10, 11], [12, 13], [7, 8]],
        num_actual_tokens=6,
        accepted=[1, 2, 1],
        draft_per_req=[1, 1, -1],
    )
    ptrs = {
        "state": first.spec_state_indices_tensor.data_ptr(),
        "masks": first.spec_sequence_masks.data_ptr(),
        "qsl": first.spec_query_start_loc.data_ptr(),
        "accepted": first.num_accepted_tokens.data_ptr(),
        "token_indx": first.spec_token_indx.data_ptr(),
    }

    second = _build_spec_batch(
        builder,
        query_lens=[2, 0, 0],
        seq_lens=[36, 0, 0],
        block_table=[[20, 21], [5, 6], [7, 8]],
        num_actual_tokens=6,
        accepted=[2, 1, 1],
        draft_per_req=[1, -1, -1],
    )
    NULL_BLOCK_ID = gdn_module.NULL_BLOCK_ID

    # data_ptr identity — the CUDA-graph stability contract.
    assert second.spec_state_indices_tensor.data_ptr() == ptrs["state"]
    assert second.spec_sequence_masks.data_ptr() == ptrs["masks"]
    assert second.spec_query_start_loc.data_ptr() == ptrs["qsl"]
    assert second.num_accepted_tokens.data_ptr() == ptrs["accepted"]
    assert second.spec_token_indx.data_ptr() == ptrs["token_indx"]

    # Contents fully refreshed for the new batch (1 live spec decode).
    assert second.num_spec_decodes == 1
    assert second.spec_state_indices_tensor[0].tolist() == [20, 21]
    assert torch.equal(
        second.spec_state_indices_tensor[1:],
        torch.full_like(second.spec_state_indices_tensor[1:], NULL_BLOCK_ID),
    )
    assert second.spec_sequence_masks[:1].tolist() == [True]
    assert not second.spec_sequence_masks[1:].any()
    assert second.spec_query_start_loc.tolist() == [0, 2, 2, 2, 2, 2, 2]
    assert second.num_accepted_tokens.tolist() == [2, 1, 1, 1, 1, 1]
    assert second.spec_token_indx.tolist() == [0, 1]


def test_gdn_buffer_stability_at_prod_mtp_k3_shape(gdn_module, monkeypatch):
    """The same two invariants at the PROD shape (MTP K=3, hybrid GDN):
    query_len K+1 = 4 per live row, token budget padded to
    num_reqs * (K+1)."""
    builder = _make_builder(gdn_module, monkeypatch, num_spec=3)

    first = _build_spec_batch(
        builder,
        query_lens=[4, 4, 0],
        seq_lens=[40, 40, 0],
        block_table=[[10, 11, 12, 13], [14, 15, 16, 17], [7, 8, 9, 6]],
        num_actual_tokens=12,
        accepted=[2, 4, 1],
        draft_per_req=[3, 3, -1],
    )
    NULL_BLOCK_ID = gdn_module.NULL_BLOCK_ID

    assert first.num_spec_decodes == 2
    assert first.num_spec_decode_tokens == 8
    assert first.spec_state_indices_tensor[:2].tolist() == [
        [10, 11, 12, 13],
        [14, 15, 16, 17],
    ]
    assert torch.equal(
        first.spec_state_indices_tensor[2:],
        torch.full_like(first.spec_state_indices_tensor[2:], NULL_BLOCK_ID),
    )
    assert first.num_accepted_tokens[:2].tolist() == [2, 4]
    assert torch.equal(
        first.num_accepted_tokens[2:],
        torch.ones_like(first.num_accepted_tokens[2:]),
    )
    assert first.spec_token_indx.tolist() == list(range(8))
    assert first.spec_token_indx.data_ptr() == builder.spec_token_arange.data_ptr()

    ptrs = {
        "state": first.spec_state_indices_tensor.data_ptr(),
        "masks": first.spec_sequence_masks.data_ptr(),
        "qsl": first.spec_query_start_loc.data_ptr(),
        "accepted": first.num_accepted_tokens.data_ptr(),
        "token_indx": first.spec_token_indx.data_ptr(),
    }
    second = _build_spec_batch(
        builder,
        query_lens=[4, 0, 0],
        seq_lens=[80, 0, 0],
        block_table=[[20, 21, 22, 23], [5, 6, 4, 3], [7, 8, 9, 2]],
        num_actual_tokens=12,
        accepted=[3, 1, 1],
        draft_per_req=[3, -1, -1],
    )
    assert second.spec_state_indices_tensor.data_ptr() == ptrs["state"]
    assert second.spec_sequence_masks.data_ptr() == ptrs["masks"]
    assert second.spec_query_start_loc.data_ptr() == ptrs["qsl"]
    assert second.num_accepted_tokens.data_ptr() == ptrs["accepted"]
    assert second.spec_token_indx.data_ptr() == ptrs["token_indx"]
    assert second.spec_state_indices_tensor[0].tolist() == [20, 21, 22, 23]
    assert second.num_accepted_tokens[:1].tolist() == [3]

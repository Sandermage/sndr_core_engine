# SPDX-License-Identifier: Apache-2.0
"""G4_78-A v1 — target[58] -> drafter[0..2] K/V bridge for prompt prefill.

================================================================
SCOPE — v1 (strict)
================================================================

- K=1, single request
- Prompt prefill only (skip decode steps in v1)
- Drafter layers 0, 1, 2 only (sliding window, head=8x256)
- NO drafter[3] (shape mismatch 8x256 vs target[59] 2x512)
- NO TPS optimization claims; this is a correctness probe

================================================================
WHY THIS WORKS
================================================================

PN269 A0 verdict (2026-05-19): proved that for every logical position
P in drafter forward,

  target_slot = target_block_table[seq=0, P // 32] * 32 + (P % 32)

resolves to the SAME slot as target's slot_mapping for P. Empirically
confirmed for both prompt prefill and decode steps; layers [58] and
[59] both byte-identical to direct slot.

Furthermore: drafter[0..2] share num_kv_heads=8 and head_size=256
with target[58]. The substitution is a same-shape memcopy from
target's NHD kv_cache to a temp key/value tensor:

  new_key[i]   = target_kv[block_id, 0, b_off, :, :]
  new_value[i] = target_kv[block_id, 1, b_off, :, :]

  target_kv shape: (num_blocks, 2, block_size, num_kv_heads, head_size)
  new_key shape:   (num_tokens, num_kv_heads, head_size)

================================================================
HOOK DESIGN
================================================================

Two wraps share module-global _STATE:

(1) TritonAttentionImpl.forward — captures target_58 state on EVERY
    target[58] call:
      _STATE.target_58_kv_cache    = args[4]              (ref)
      _STATE.target_58_block_table = attn_metadata.block_table.clone()

    Capture, do NOT modify. Passthrough.

(2) FlashAttentionImpl.forward — for drafter[0..2] only:
      a. Identify layer index from prefix "draft_model.layers.N..."
      b. Confirm is_prefill_like (query_len > 1 for first seq)
      c. Run safety checks against captured target state
      d. Build new_key, new_value by indexing target_58_kv_cache
      e. Replace args[2]=new_key, args[3]=new_value
      f. Call original with substituted args

Drafter[3] (Triton) and decode steps fall through untouched.

================================================================
SAFETY
================================================================

If ANY pre-substitution check fails (no target state, shape mismatch,
positions count mismatch, exception during indexing), log a warning
and pass through unmodified. NEVER crash — this is gate #1.

================================================================
ENV
================================================================

  GENESIS_ENABLE_G4_78_DRAFTER_TARGET_KV_BRIDGE=1

================================================================

Author: Sandermage (Sander) Barzov Aleksandr, Ukraine, Odessa.
"""
from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("genesis.gemma4.g4_78_drafter_target_kv_bridge")

GENESIS_G4_78_MARKER = (
    "Genesis G4_78-A v1 drafter[0..2] <- target[58] K/V bridge (prefill)"
)

_ENV_ENABLE = "GENESIS_ENABLE_G4_78_DRAFTER_TARGET_KV_BRIDGE"

DRAFTER_PREFIX = "draft_model."
TARGET_58_SUFFIX = ".layers.58.self_attn.attn"
TARGET_58_BLOCK_SIZE = 32

_APPLIED = False
_ORIGINAL_FA_FORWARD = None
_ORIGINAL_TRITON_FORWARD = None


class _State:
    target_58_kv_cache: Any = None
    target_58_block_table: Any = None  # cloned per-call
    target_58_seq_lens: Any = None
    target_58_query_start_loc: Any = None
    target_58_capture_count: int = 0
    bridge_apply_count: int = 0
    bridge_skip_count: int = 0


_STATE = _State()


def _env_enabled() -> bool:
    return os.environ.get(_ENV_ENABLE, "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _identify_drafter_layer_idx(layer: Any) -> int | None:
    """Return layer index N if prefix is 'draft_model.layers.N...', else None."""
    prefix = getattr(layer, "prefix", None) or getattr(layer, "layer_name", None)
    if not isinstance(prefix, str) or not prefix.startswith(DRAFTER_PREFIX):
        return None
    parts = prefix.split(".")
    # "draft_model" "layers" "N" "self_attn" "attn"
    if len(parts) < 3 or parts[1] != "layers":
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def _is_target_58(layer: Any) -> bool:
    prefix = getattr(layer, "prefix", None) or getattr(layer, "layer_name", None)
    return isinstance(prefix, str) and prefix.endswith(TARGET_58_SUFFIX)


def _reconstruct_positions(query_start_loc: Any, seq_lens: Any) -> list[int]:
    try:
        qsl = query_start_loc.tolist() if hasattr(query_start_loc, "tolist") else list(query_start_loc)
        sl = seq_lens.tolist() if hasattr(seq_lens, "tolist") else list(seq_lens)
        positions: list[int] = []
        num_seqs = len(sl)
        for i in range(num_seqs):
            qs = qsl[i]
            qe = qsl[i + 1]
            seq_total = sl[i]
            query_len = qe - qs
            for j in range(query_len):
                positions.append(seq_total - query_len + j)
        return positions
    except Exception as _e:  # noqa: BLE001
        log.warning("[G4_78] position reconstruction failed: %s", _e)
        return []


def apply() -> tuple[str, str]:
    global _APPLIED, _ORIGINAL_FA_FORWARD, _ORIGINAL_TRITON_FORWARD

    if not _env_enabled():
        return "skipped", f"G4_78 disabled (set {_ENV_ENABLE}=1)"
    if _APPLIED:
        return "applied", "G4_78 already installed"

    log.warning("[G4_78] apply() entered")

    # --- Wrap TritonAttentionImpl.forward (target_58 capture) ---
    try:
        from vllm.v1.attention.backends.triton_attn import TritonAttentionImpl
    except Exception as e:  # noqa: BLE001
        log.warning("[G4_78] SKIP: TritonAttentionImpl import failed: %s", e)
        return "skipped", f"TritonAttentionImpl import failed: {e!r}"

    try:
        from vllm.v1.attention.backends.flash_attn import FlashAttentionImpl
    except Exception as e:  # noqa: BLE001
        log.warning("[G4_78] SKIP: FlashAttentionImpl import failed: %s", e)
        return "skipped", f"FlashAttentionImpl import failed: {e!r}"

    if getattr(TritonAttentionImpl.forward, "_genesis_g4_78_wrapped", False):
        _APPLIED = True
        return "applied", "Triton.forward already wrapped"

    _ORIGINAL_TRITON_FORWARD = TritonAttentionImpl.forward
    _ORIGINAL_FA_FORWARD = FlashAttentionImpl.forward

    def _triton_wrapped(self, *args, **kwargs):
        # Capture target_58 state. Passthrough behavior.
        if len(args) >= 1 and _is_target_58(args[0]):
            attn_md = args[5] if len(args) >= 6 else kwargs.get("attn_metadata")
            kv_cache = args[4] if len(args) >= 5 else kwargs.get("kv_cache")
            if attn_md is not None and kv_cache is not None:
                try:
                    bt = getattr(attn_md, "block_table", None)
                    qsl = getattr(attn_md, "query_start_loc", None)
                    sl = getattr(attn_md, "seq_lens", None)
                    _STATE.target_58_kv_cache = kv_cache  # reference
                    _STATE.target_58_block_table = (
                        bt.clone() if (bt is not None and hasattr(bt, "clone")) else None
                    )
                    _STATE.target_58_query_start_loc = (
                        qsl.clone() if (qsl is not None and hasattr(qsl, "clone")) else None
                    )
                    _STATE.target_58_seq_lens = (
                        sl.clone() if (sl is not None and hasattr(sl, "clone")) else None
                    )
                    _STATE.target_58_capture_count += 1
                except Exception as _e:  # noqa: BLE001
                    log.warning("[G4_78] target_58 capture failed: %s", _e)
        return _ORIGINAL_TRITON_FORWARD(self, *args, **kwargs)

    _triton_wrapped._genesis_g4_78_wrapped = True  # type: ignore[attr-defined]
    TritonAttentionImpl.forward = _triton_wrapped  # type: ignore[method-assign]

    # --- Wrap FlashAttentionImpl.forward (drafter[0..2] bridge) ---
    import torch  # local import; torch is guaranteed at this point

    def _fa_wrapped(self, *args, **kwargs):
        if len(args) < 6:
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        layer = args[0]
        layer_idx = _identify_drafter_layer_idx(layer)
        if layer_idx not in (0, 1, 2):
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        attn_md = args[5] if len(args) >= 6 else kwargs.get("attn_metadata")
        if attn_md is None:
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        # Prompt-prefill gate: query_len of first seq must be > 1.
        qsl = getattr(attn_md, "query_start_loc", None)
        sl = getattr(attn_md, "seq_lens", None)
        if qsl is None or sl is None:
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        try:
            qsl_list = qsl.tolist()
            sl_list = sl.tolist()
        except Exception:
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        if len(qsl_list) < 2 or (qsl_list[1] - qsl_list[0]) <= 1:
            # Decode step (or empty) — v1 skips
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        # Target state must be present and fresh
        target_kv = _STATE.target_58_kv_cache
        target_bt = _STATE.target_58_block_table
        if target_kv is None or target_bt is None:
            _STATE.bridge_skip_count += 1
            log.warning(
                "[G4_78] layer=%d no target_58 state captured yet — no-op "
                "(captures=%d)", layer_idx, _STATE.target_58_capture_count,
            )
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        key = args[2]
        value = args[3]
        if key is None or value is None:
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        # Safety checks (no-op on any mismatch)
        try:
            if target_kv.ndim != 5:
                raise ValueError(f"target_kv.ndim={target_kv.ndim} != 5")
            if int(target_kv.shape[1]) != 2:
                raise ValueError(f"target_kv.shape[1]={target_kv.shape[1]} != 2")
            if tuple(target_kv.shape[3:]) != tuple(key.shape[1:]):
                raise ValueError(
                    f"shape mismatch target_kv.shape[3:]={tuple(target_kv.shape[3:])} "
                    f"vs key.shape[1:]={tuple(key.shape[1:])}"
                )
            if key.shape != value.shape:
                raise ValueError(
                    f"key.shape={tuple(key.shape)} != value.shape={tuple(value.shape)}"
                )
        except Exception as _e:  # noqa: BLE001
            _STATE.bridge_skip_count += 1
            log.warning("[G4_78] layer=%d safety check fail: %s — no-op",
                        layer_idx, _e)
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        positions = _reconstruct_positions(qsl, sl)
        if len(positions) != int(key.shape[0]):
            _STATE.bridge_skip_count += 1
            log.warning(
                "[G4_78] layer=%d positions(%d) != key.shape[0](%d) — no-op",
                layer_idx, len(positions), int(key.shape[0]),
            )
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        # Build new_key, new_value (vectorized index)
        try:
            block_ids: list[int] = []
            offsets: list[int] = []
            for P in positions:
                b_idx = P // TARGET_58_BLOCK_SIZE
                b_off = P % TARGET_58_BLOCK_SIZE
                # block_table layout: (num_seqs, max_blocks); seq=0 (batch=1 in v1)
                block_id = int(target_bt[0, b_idx].item())
                block_ids.append(block_id)
                offsets.append(b_off)

            bid_t = torch.tensor(block_ids, dtype=torch.long, device=target_kv.device)
            off_t = torch.tensor(offsets, dtype=torch.long, device=target_kv.device)
            # target_kv layout: (num_blocks, 2, block_size, num_kv_heads, head_size)
            new_key = target_kv[bid_t, 0, off_t].to(key.dtype)
            new_value = target_kv[bid_t, 1, off_t].to(value.dtype)
        except Exception as _e:  # noqa: BLE001
            _STATE.bridge_skip_count += 1
            log.warning("[G4_78] layer=%d index/substitution failed: %s — no-op",
                        layer_idx, _e)
            return _ORIGINAL_FA_FORWARD(self, *args, **kwargs)

        # Logging (only on layer 0 to avoid 3x noise per step)
        _STATE.bridge_apply_count += 1
        if layer_idx == 0:
            try:
                target_slots = [
                    block_ids[i] * TARGET_58_BLOCK_SIZE + offsets[i]
                    for i in range(min(8, len(positions)))
                ]
                k_b = key.float()
                k_a = new_key.float()
                v_b = value.float()
                v_a = new_value.float()
                log.warning(
                    "[G4_78] layer=0 prefill bridge tokens=%d replaced=True "
                    "positions[:8]=%s target_slots[:8]=%s",
                    int(key.shape[0]), positions[:8], target_slots,
                )
                log.warning(
                    "[G4_78] layer=0 key mean/std before=%.4e/%.4e -> "
                    "after=%.4e/%.4e",
                    k_b.mean().item(), k_b.std().item(),
                    k_a.mean().item(), k_a.std().item(),
                )
                log.warning(
                    "[G4_78] layer=0 value mean/std before=%.4e/%.4e -> "
                    "after=%.4e/%.4e",
                    v_b.mean().item(), v_b.std().item(),
                    v_a.mean().item(), v_a.std().item(),
                )
            except Exception as _e:  # noqa: BLE001
                log.warning("[G4_78] layer=0 stats log failed: %s", _e)

        # Replace key/value in args
        new_args = list(args)
        new_args[2] = new_key
        new_args[3] = new_value
        return _ORIGINAL_FA_FORWARD(self, *tuple(new_args), **kwargs)

    _fa_wrapped._genesis_g4_78_wrapped = True  # type: ignore[attr-defined]
    FlashAttentionImpl.forward = _fa_wrapped  # type: ignore[method-assign]

    _APPLIED = True
    log.warning(
        "[G4_78] INSTALLED: target_58 capture (Triton) + drafter[0..2] "
        "K/V bridge (FlashAttn) for prompt prefill."
    )
    return "applied", "G4_78 v1 installed"


def is_applied() -> bool:
    return _APPLIED


def revert() -> bool:
    global _APPLIED, _ORIGINAL_FA_FORWARD, _ORIGINAL_TRITON_FORWARD
    if not _APPLIED:
        return False
    try:
        from vllm.v1.attention.backends.triton_attn import TritonAttentionImpl
        if _ORIGINAL_TRITON_FORWARD is not None:
            TritonAttentionImpl.forward = _ORIGINAL_TRITON_FORWARD
    except ImportError:
        pass
    try:
        from vllm.v1.attention.backends.flash_attn import FlashAttentionImpl
        if _ORIGINAL_FA_FORWARD is not None:
            FlashAttentionImpl.forward = _ORIGINAL_FA_FORWARD
    except ImportError:
        pass
    _APPLIED = False
    _ORIGINAL_FA_FORWARD = None
    _ORIGINAL_TRITON_FORWARD = None
    return True


__all__ = ["GENESIS_G4_78_MARKER", "apply", "is_applied", "revert"]

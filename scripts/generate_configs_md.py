#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""generate_configs_md.py — auto-generate model config inventory from builtin YAMLs.

Companion to scripts/generate_patches_md.py: this generates docs/CONFIGS_AUTO.md
from `sndr/model_configs/builtin/*.yaml` files. Operator-facing
config inventory with reference_metrics, lifecycle, target hardware.

Background: docs/CONFIGS.md was identified in 2026-05-11 audit as lacking
per-config TPS comparison table (Agent A). Manual updates lag behind YAML
changes. Auto-generation eliminates drift.

No torch/pyyaml dependency — uses simple regex parsing of top-level YAML
fields. Sufficient because builtin configs have canonical formatting.

Usage:
    python3 scripts/generate_configs_md.py             # writes docs/CONFIGS_AUTO.md
    python3 scripts/generate_configs_md.py --check     # CI gate, exit 1 on divergence
    python3 scripts/generate_configs_md.py --stdout    # print, no write
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BUILTIN_DIR = REPO_ROOT / "sndr" / "model_configs" / "builtin"
OUTPUT_PATH = REPO_ROOT / "docs" / "CONFIGS_AUTO.md"


# The V2 layered config lives in tier subdirs; each is scanned recursively.
# `_archive/` subtrees are retired (mirrored in docs/PRESETS.md's archived
# section) and deliberately excluded from the advertised inventory.
TIER_DIRS = ["model", "hardware", "profile", "presets"]
ARCHIVE_MARKER = "_archive"

# Top-level fields to extract from each YAML. `id` (V2) and `key` (V1) are both
# accepted — the display key resolves key -> id -> filename stem. `status` is the
# V2 spelling of `lifecycle`. `model`/`hardware`/`profile` are the binder refs a
# preset alias composes.
TOP_FIELDS = [
    "key", "id", "kind", "title", "description", "lifecycle", "status",
    "workload_tag", "role", "parent_model", "model", "hardware", "profile",
    "last_validated", "genesis_pin", "vllm_pin_required",
    "model_path", "served_model_name", "kv_cache_dtype",
    "max_model_len", "gpu_memory_utilization", "max_num_seqs",
    "max_num_batched_tokens",
]

# Reference metrics fields
METRIC_FIELDS = [
    "long_gen_sustained_tps", "decode_tpot_ms", "ttft_ms",
    "tool_call_score", "stability_cv_pct",
]


def parse_yaml_top_level(yaml_path: Path, tier: str | None = None) -> dict:  # noqa: PLR0912  # flat regex field-extractor; branch-per-field-shape is inherent
    """Parse top-level scalar fields from YAML.

    Limitations: doesn't handle nested structures or multi-line scalars
    (>- folded text). Sufficient for our flat top-level fields.

    ``tier`` tags which V2 subdir (model/hardware/profile/presets) the file
    came from, so the renderer can group the inventory by layer.
    """
    text = yaml_path.read_text()
    result: dict = {"_file": yaml_path.name, "_tier": tier}

    # Extract top-level scalar fields (key: value at indent 0)
    for field in TOP_FIELDS:
        # Match `field: value` at start of line, capture value up to newline or comment
        # Handle quoted strings
        m = re.search(rf'^{field}:\s*(.+?)(?:\s+#.*)?$', text, flags=re.M)
        if m:
            val = m.group(1).strip()
            # Strip surrounding quotes
            if (val.startswith("'") and val.endswith("'")) or \
               (val.startswith('"') and val.endswith('"')):
                val = val[1:-1]
            # Skip multi-line markers
            if val in (">-", "|-", ">", "|"):
                # Try to capture first line of next block
                m2 = re.search(rf'^{field}:\s*>-?\s*\n((?:\s+\S.*\n)+)', text, flags=re.M)
                if m2:
                    val = m2.group(1).strip().replace("\n", " ").replace("  ", " ")
                else:
                    val = None
            result[field] = val
        else:
            result[field] = None

    # Extract reference_metrics block
    metrics_match = re.search(r'^reference_metrics:\s*\n((?:\s+.*\n)+?)(?=^\S|\Z)', text, flags=re.M)
    if metrics_match:
        metrics_block = metrics_match.group(1)
        for field in METRIC_FIELDS:
            m = re.search(rf'^\s+{field}:\s*(.+?)(?:\s+#.*)?$', metrics_block, flags=re.M)
            if m:
                val = m.group(1).strip()
                if (val.startswith("'") and val.endswith("'")) or \
                   (val.startswith('"') and val.endswith('"')):
                    val = val[1:-1]
                result[f"metric_{field}"] = val
            else:
                result[f"metric_{field}"] = None
    else:
        for field in METRIC_FIELDS:
            result[f"metric_{field}"] = None

    # Extract MTP K (spec_decode.num_speculative_tokens)
    mtp_match = re.search(r'spec_decode:\s*\n\s+method:\s*mtp\s*\n\s+num_speculative_tokens:\s*(\d+)', text, flags=re.M)
    if mtp_match:
        result["mtp_k"] = mtp_match.group(1)
    else:
        ngram_match = re.search(r'spec_decode:\s*\n\s+method:\s*ngram', text, flags=re.M)
        result["mtp_k"] = "ngram" if ngram_match else None

    # Count enabled patches in genesis_env
    enable_count = len(re.findall(r"^\s+GENESIS_ENABLE_\w+:\s*'1'", text, flags=re.M))
    result["enabled_patches"] = enable_count

    return result


def _display_key(c: dict) -> str:
    """V1 used ``key``; V2 uses ``id``; preset aliases carry neither and are
    identified by filename. Resolve in that order."""
    return c.get("key") or c.get("id") or c.get("_file", "").replace(".yaml", "")


def _display_status(c: dict) -> str:
    """``lifecycle`` (V1) and ``status`` (V2) name the same maturity axis."""
    return c.get("lifecycle") or c.get("status") or "?"


_LIFECYCLE_ORDER = {
    "stable": 0, "tested": 1, "experimental": 2, "community-test": 3,
    "deprecated": 4, "retired": 5,
}


def _sort_configs(configs: list[dict]) -> list[dict]:
    return sorted(
        configs,
        key=lambda c: (_LIFECYCLE_ORDER.get(_display_status(c), 9), _display_key(c)),
    )


def _render_model_section(lines: list[str], configs: list[dict]) -> None:
    """Rich engine-config table + per-config details for the model tier."""
    sorted_configs = _sort_configs(configs)

    lines.append("| Key | Status | Model | KV dtype | Spec | Max ctx | TPS | TPOT | Tool | Last validated |")
    lines.append("|---|:---:|---|---|:---:|---:|---:|---:|:---:|---|")
    for c in sorted_configs:
        mtp = c.get("mtp_k") or "—"
        mtp_str = f"MTP K={mtp}" if mtp not in (None, "ngram", "—") else (mtp or "—")
        lines.append(
            f"| `{_display_key(c)}` | `{_display_status(c)}` | "
            f"{c.get('served_model_name') or '?'} | `{c.get('kv_cache_dtype') or 'default'}` | "
            f"{mtp_str} | {c.get('max_model_len') or '?'} | "
            f"{c.get('metric_long_gen_sustained_tps') or '—'} | "
            f"{c.get('metric_decode_tpot_ms') or '—'} | "
            f"{c.get('metric_tool_call_score') or '—'} | {c.get('last_validated') or '—'} |"
        )
    lines.append("")

    lines.append("#### Per-config details")
    lines.append("")
    for c in sorted_configs:
        lines.append(f"##### `{_display_key(c)}`")
        lines.append("")
        if c.get("title"):
            lines.append(f"**Title**: {c['title']}")
            lines.append("")
        if c.get("description"):
            lines.append(f"> {c['description'][:200].strip()}")
            lines.append("")
        lines.append("**Engine config:**")
        lines.append("")
        lines.append("| Field | Value |")
        lines.append("|---|---|")
        for field in ["lifecycle", "workload_tag", "genesis_pin", "vllm_pin_required",
                      "model_path", "kv_cache_dtype", "max_model_len",
                      "gpu_memory_utilization", "max_num_seqs", "max_num_batched_tokens"]:
            lines.append(f"| `{field}` | `{c.get(field) or '—'}` |")
        lines.append(f"| `mtp_k` | {c.get('mtp_k') or '—'} |")
        lines.append(f"| `enabled_patches` (genesis_env) | {c.get('enabled_patches')} |")
        lines.append("")
        if any(c.get(f"metric_{f}") for f in METRIC_FIELDS):
            lines.append("**Reference metrics (`genesis_bench_suite.py --quick`):**")
            lines.append("")
            lines.append("| Metric | Value |")
            lines.append("|---|---|")
            for f in METRIC_FIELDS:
                lines.append(f"| `{f}` | `{c.get(f'metric_{f}') or '—'}` |")
            lines.append("")
        lines.append("")


def _render_preset_section(lines: list[str], configs: list[dict]) -> None:
    """Operator-facing aliases: which model×hardware×profile they compose."""
    lines.append("| Alias | Status | Model | Hardware | Profile | Title |")
    lines.append("|---|:---:|---|---|---|---|")
    for c in _sort_configs(configs):
        lines.append(
            f"| `{_display_key(c)}` | `{_display_status(c)}` | "
            f"{c.get('model') or '—'} | {c.get('hardware') or '—'} | "
            f"{c.get('profile') or '—'} | {c.get('title') or '—'} |"
        )
    lines.append("")


def _render_generic_section(lines: list[str], configs: list[dict]) -> None:
    """Profile / hardware fragments: id, role/parent, status, title."""
    lines.append("| Id | Status | Parent / role | Title |")
    lines.append("|---|:---:|---|---|")
    for c in _sort_configs(configs):
        parent = c.get("parent_model") or c.get("role") or "—"
        lines.append(
            f"| `{_display_key(c)}` | `{_display_status(c)}` | "
            f"{parent} | {c.get('title') or '—'} |"
        )
    lines.append("")


_TIER_ORDER = ["model", "presets", "profile", "hardware"]
_TIER_HEADINGS = {
    "model": "Model configs (`builtin/model/`) — per-model engine defaults",
    "presets": "Presets (`builtin/presets/`) — operator-facing aliases",
    "profile": "Profiles (`builtin/profile/`) — workload roles",
    "hardware": "Hardware (`builtin/hardware/`) — per-rig host envelopes",
}


def render_markdown(configs: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []

    lines.append("# Genesis vLLM Patches — Model Config Inventory (auto-generated)")
    lines.append("")
    lines.append("> ⚠ **Auto-generated by `scripts/generate_configs_md.py` — DO NOT EDIT MANUALLY.**")
    lines.append("> Source: `sndr/model_configs/builtin/{model,presets,profile,hardware}/*.yaml`")
    lines.append("> Companion to curated [CONFIGS.md](CONFIGS.md) (narrative) and")
    lines.append("> [PRESETS.md](PRESETS.md) (operator preset guide). Archived (`_archive/`)")
    lines.append("> configs are retired and excluded — see PRESETS.md for their record.")
    lines.append("")
    lines.append(f"Generated: {now}")
    lines.append(f"Total configs: **{len(configs)}**")
    lines.append("")

    if not configs:
        lines.append("> ℹ No builtin config YAMLs found under the V2 layered subdirs "
                     "(`builtin/model|hardware|profile|presets/`). Discover live via "
                     "`sndr preset list` / `sndr preset recommend`.")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("Regenerate: `python3 scripts/generate_configs_md.py`")
        lines.append("Verify: `python3 scripts/generate_configs_md.py --check`")
        return "\n".join(lines)

    # Group by tier. Configs from the unit-test path carry no `_tier`; treat
    # them as the (rich) model tier so the legacy render contract is preserved.
    by_tier: dict[str, list[dict]] = {}
    for c in configs:
        by_tier.setdefault(c.get("_tier") or "model", []).append(c)

    lines.append("## By tier")
    lines.append("")
    for tier in _TIER_ORDER + sorted(set(by_tier) - set(_TIER_ORDER)):
        if tier in by_tier:
            lines.append(f"- `{tier}`: {len(by_tier[tier])}")
    lines.append("")

    for tier in _TIER_ORDER + sorted(set(by_tier) - set(_TIER_ORDER)):
        group = by_tier.get(tier)
        if not group:
            continue
        lines.append(f"## {_TIER_HEADINGS.get(tier, tier)}")
        lines.append("")
        if tier == "model":
            _render_model_section(lines, group)
        elif tier == "presets":
            _render_preset_section(lines, group)
        else:
            _render_generic_section(lines, group)

    lines.append("---")
    lines.append("")
    lines.append("Regenerate: `python3 scripts/generate_configs_md.py`")
    lines.append("Verify: `python3 scripts/generate_configs_md.py --check`")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stdout", action="store_true")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    if not BUILTIN_DIR.is_dir():
        print(f"ERROR: builtin dir not found: {BUILTIN_DIR}", file=sys.stderr)
        return 2

    # The V2 reorg moved every builtin config into a tier subdir; recurse each
    # (skipping retired `_archive/` trees). A top-level `*.yaml` glob — the pre-
    # 2026-07 discovery — matched zero files here and produced an inventory that
    # read "Total configs: 0" while 45 live configs existed.
    configs: list[dict] = []
    for tier in TIER_DIRS:
        tier_dir = BUILTIN_DIR / tier
        if not tier_dir.is_dir():
            continue
        for p in sorted(tier_dir.rglob("*.yaml")):
            if ARCHIVE_MARKER in p.parts:
                continue
            configs.append(parse_yaml_top_level(p, tier=tier))
    content = render_markdown(configs)

    if args.stdout:
        print(content)
        return 0

    if args.check:
        if not OUTPUT_PATH.is_file():
            print(f"FAIL: {OUTPUT_PATH.relative_to(REPO_ROOT)} doesn't exist", file=sys.stderr)
            return 1
        committed = OUTPUT_PATH.read_text()
        gen_norm = re.sub(r"Generated: \S+", "Generated: <TS>", content)
        com_norm = re.sub(r"Generated: \S+", "Generated: <TS>", committed)
        if gen_norm == com_norm:
            print(f"✓ {OUTPUT_PATH.relative_to(REPO_ROOT)} in sync ({len(configs)} configs)")
            return 0
        print(f"✗ {OUTPUT_PATH.relative_to(REPO_ROOT)} OUT OF SYNC", file=sys.stderr)
        return 1

    OUTPUT_PATH.write_text(content)
    print(f"✓ Wrote {OUTPUT_PATH.relative_to(REPO_ROOT)} ({len(configs)} configs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

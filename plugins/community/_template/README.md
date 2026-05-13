# `_template/` — community patch reference example

**Excluded from release registry** by:

- directory name prefix `_` (validator skips per §6.6 no-stub boundary),
- manifest `publish_state: draft` (release-tier rule).

## Purpose

This directory shows the canonical layout `sndr community new-patch`
generates. Reading it teaches you what a working manifest looks like
without rummaging through validator code.

## Layout

```text
plugins/community/<author>/<patch-id>/
├── manifest.yaml             # PatchManifest (schema_v2 §4.5)
├── __init__.py               # marks the directory as a Python package
├── patch.py                  # apply() hook — the actual patch logic
└── tests/
    ├── __init__.py
    └── test_<patch-id>.py    # pytest harness (validator rule R-5)
```

## Recommended workflow

```bash
# 1. Scaffold a new patch from the template
sndr community new-patch \
    --id PN999 \
    --author your_handle \
    --family spec_decode \
    --title "PN999 — short description"

# 2. Implement the apply() logic
$EDITOR plugins/community/your_handle/PN999/patch.py

# 3. Validate before pushing
sndr community validate

# 4. Flip publish_state to `review` when ready
sed -i 's/publish_state: draft/publish_state: review/' \
    plugins/community/your_handle/PN999/manifest.yaml

# 5. Open a PR — release gate enforces R-1..R-7 rules
```

## Validator rules a manifest must satisfy

| Rule | What it checks |
|---|---|
| schema | PatchManifest.validate() — semver, kind, default_on requires env_flag |
| R-1 | text_patch context_md5 matches its pristine_fixture |
| R-2 | requires_patches reference known patch ids |
| R-3 | conflicts_with reference known patch ids (typo catch) |
| R-4 | runtime_hook entry_points.apply is importable |
| R-5 | every tests_required glob matches ≥1 file |
| R-6 | (namespace, id) pair is unique across the registry |
| R-7 | default_on=True requires implementation_status=stable AND publish_state=published |

See `vllm/sndr_core/community/validator.py` for exact predicates.

# SNDR Core / Engine — Test Suite (Top-Level)

**Per Sander decision Q7 (2026-05-07)**: tests live at the **repository root**,
NOT inside `vllm/sndr_core/` or `vllm/sndr_engine/`. They are **internal** —
not part of pip-installed package, not shipped to community.

## Structure (final, after Stage 9 migration)

```
tests/
├── README.md                       # this file
├── conftest.py                     # global pytest fixtures
│
├── unit/                           # pure-logic tests (no vllm import)
│   ├── core/
│   │   ├── test_text_patch.py
│   │   ├── test_multi_file.py
│   │   ├── test_sub_patch_drift.py
│   │   ├── test_file_cache.py
│   │   └── test_manifest.py
│   ├── dispatcher/
│   │   ├── test_registry_validation.py
│   │   ├── test_decision.py
│   │   ├── test_pins.py
│   │   └── test_audit.py
│   ├── env/
│   │   ├── test_flags.py
│   │   └── test_aliasing.py
│   ├── paths/
│   │   ├── test_vllm_targets.py
│   │   └── test_resolver.py
│   └── runtime/
│       └── (mirror runtime/)
│
├── patches/                        # per-subsystem patch tests (mirror)
│   ├── tool_parsing/
│   │   ├── test_p15.py
│   │   ├── test_p61c.py
│   │   ├── test_p64.py
│   │   ├── test_pn56.py
│   │   └── fixtures/
│   ├── reasoning/
│   ├── serving/
│   ├── attention/
│   │   ├── gdn/
│   │   ├── turboquant/
│   │   └── flash/
│   ├── spec_decode/
│   ├── scheduler/
│   ├── worker/
│   ├── kv_cache/
│   ├── moe/
│   ├── quantization/
│   ├── kernels/
│   ├── compile_safety/
│   ├── loader/
│   ├── middleware/
│   ├── memory/
│   ├── lora/                       # PN80 + future LoRA patches
│   ├── multimodal/                 # PN62 text-only VIT skip
│   └── model_specific/             # truly model-tied (rare)
│
├── bundles/                        # bundle integration tests
│   ├── test_tool_parsing_qwen3coder_bundle.py
│   ├── test_attention_gdn_spec_bundle.py
│   ├── test_attention_tq_multi_query_bundle.py    # tier=engine
│   └── test_spec_decode_async_cleanup_bundle.py
│
├── integration/                    # full apply boot + smoke
│   ├── test_boot_apply_all.py
│   ├── test_pin_upgrade_drift.py
│   ├── test_tier_separation.py     # community-only mode works without sndr_engine
│   └── test_genesis_alias_compat.py
│
└── installer/                      # CLI installer tests (dry-run mode)
    ├── test_install_dry_run.py
    ├── test_first_run_launch.py
    └── test_uninstall.py
```

## Migration plan

- **Stage 1 (current)**: this README only. Existing tests continue to live
  at `vllm/sndr_core/tests/` and run via `PYTHONPATH=. pytest vllm/sndr_core/tests/`.
- **Stage 9**: physically move tests from `vllm/sndr_core/tests/` into this
  top-level directory. Update `pytest.ini` → `testpaths = tests/`.
  Update CI workflows.
- **After Stage 9**: any new test goes here, mirroring source-tree layout.

## Running tests during migration

```bash
# Until Stage 9 — old location works
PYTHONPATH=. pytest vllm/sndr_core/tests/

# After Stage 9 — new location
PYTHONPATH=. pytest tests/
```

## Why top-level (not co-located)

Sander 2026-05-07: "тесты нужны больше для меня их нет смысла кидать в общий доступ".
- Tests are internal artifacts. pip-installed `sndr_core` should not include them.
- Sander uses tests for development; community doesn't need to see them.
- Standard layout for many production Python projects (numpy, pandas, etc.).

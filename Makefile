# Genesis vLLM Patches — operator shortcuts.
#
# Quick reference: `make help` lists every target with one-line description.
#
# Most common workflows:
#   make test          — run full test suite locally
#   make gates         — run the 4 CI gates (pin-gate, iron-rule, family, audit)
#   make audit         — run all 6 maintenance audit tools
#   make docs          — regenerate auto-docs (PATCHES_AUTO.md, CONFIGS_AUTO.md)
#   make precommit     — install + run pre-commit hooks on all files
#   make paths-env     — render canonical paths env file

.PHONY: help test gates audit docs precommit paths-env clean \
        test-pin-gate test-iron-rule test-family test-doc-sync \
        audit-upstream audit-yaml docs-check docs-write doctor

# Default target — show help.
.DEFAULT_GOAL := help

PYTHON ?= python3
PYTEST ?= $(PYTHON) -m pytest

help: ## Show this help message
	@echo "Genesis vLLM Patches — operator shortcuts"
	@echo ""
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
	@echo ""
	@echo "  See docs/CONTRIBUTING.md + Genesis_internal_docs/OPERATOR_RUNBOOK_*.md"

# ─── Tests ─────────────────────────────────────────────────────────────

test: ## Full pytest suite (all 1598+ tests)
	$(PYTEST) tests/ -q

test-pin-gate: ## Pin-gate adoption test (KNOWN_GOOD_VLLM_PINS drift)
	$(PYTEST) tests/unit/dispatcher/test_pin_gate.py -v

test-iron-rule: ## Iron-rule-#11 retire provenance meta-test
	$(PYTEST) tests/unit/dispatcher/test_iron_rule_11_enforcement.py -v

test-family: ## All 17 family contracts (~700 tests, covers 18/18 families)
	$(PYTEST) tests/unit/integrations/ -q

test-doc-sync: ## Doc-sync (patch counts consistent across 5 docs)
	$(PYTHON) scripts/check_doc_sync.py --strict

gates: test-pin-gate test-iron-rule test-family test-doc-sync ## Run all 4 CI gates fast-fail

# ─── Audits ────────────────────────────────────────────────────────────

audit-upstream: ## Audit PATCH_REGISTRY vs GitHub PR merge state (live)
	$(PYTHON) scripts/audit_upstream_status.py

audit-upstream-offline: ## Audit registry sanity offline (no gh API)
	$(PYTHON) scripts/audit_upstream_status.py --skip-network

audit-yaml: ## YAML genesis_env vs docker inspect drift (env: YAML CONTAINER SSH_HOST)
	@echo "Usage: tools/audit_yaml_vs_runtime.sh <yaml> <container> [ssh_host]"
	@bash tools/audit_yaml_vs_runtime.sh \
		$${YAML:-vllm/sndr_core/model_configs/builtin/a5000-2x-27b-int4-tq-k8v4.yaml} \
		$${CONTAINER:-vllm-pn95-2xa5000} \
		$${SSH_HOST:-}

audit-legacy-imports: ## Forbid vllm.sndr_core.patches / vllm._genesis active imports
	@bash scripts/check_no_legacy_imports.sh

audit: audit-upstream-offline test-doc-sync audit-legacy-imports ## Run audit suite (offline-safe subset)
	@echo "✓ Audit suite complete. Run 'make audit-upstream' for live gh check."

# ─── Docs ──────────────────────────────────────────────────────────────

docs-check: ## Verify PATCHES_AUTO.md + CONFIGS_AUTO.md in sync (CI gate)
	$(PYTHON) scripts/generate_patches_md.py --check
	$(PYTHON) scripts/generate_configs_md.py --check
	$(PYTHON) scripts/check_doc_sync.py --strict

docs-write: ## Regenerate auto-docs from registry + builtin YAMLs
	$(PYTHON) scripts/generate_patches_md.py
	$(PYTHON) scripts/generate_configs_md.py
	@echo "✓ Regenerated docs/PATCHES_AUTO.md + docs/CONFIGS_AUTO.md"

docs: docs-write docs-check ## Regenerate + verify auto-docs

# ─── Pre-commit ────────────────────────────────────────────────────────

precommit-install: ## Install pre-commit hooks (one-time per clone)
	$(PYTHON) -m pip install pre-commit
	pre-commit install

precommit: ## Run pre-commit hooks on all files
	pre-commit run --all-files

# ─── Paths / env file ──────────────────────────────────────────────────

paths-env: ## Render canonical paths to ~/.genesis_paths.env
	$(PYTHON) scripts/emit_paths_env.py > ~/.genesis_paths.env
	@echo "✓ Wrote ~/.genesis_paths.env (source it in start-scripts)"

paths-print: ## Pretty-print all Genesis paths (debug)
	$(PYTHON) scripts/emit_paths_env.py --print

# ─── Maintenance ───────────────────────────────────────────────────────

clean: ## Remove __pycache__, .pytest_cache, .bak files
	find . -name "__pycache__" -type d -not -path "*/.git/*" -exec rm -rf {} + 2>/dev/null || true
	find . -name "*.pyc" -delete 2>/dev/null || true
	find . -name "*.bak" -not -path "*/.git/*" -delete 2>/dev/null || true
	rm -rf .pytest_cache .mypy_cache .ruff_cache 2>/dev/null || true
	@echo "✓ Cleaned"

doctor: ## Run sndr doctor (genesis CLI health check)
	$(PYTHON) -m vllm.sndr_core.cli doctor

# ─── Integration (gated on GENESIS_INTEGRATION_ENDPOINT) ─────────────
#
# Все таргеты по умолчанию идут в localhost (порт 8101 для 27B, 8000
# для 35B). Для remote rig задавайте `HOST=http://<host>:<port>`.
# Жёстко вшитый LAN IP убран — operator-specific endpoint лежит только
# в `~/.sndr/host.yaml` (используйте `sndr host init`).

integration-27b: ## Run regression bounds against 27B PROD (env: HOST=<url>)
	@echo "Running integration regression bench against 27B PROD..."
	GENESIS_INTEGRATION_ENDPOINT=$${HOST:-http://127.0.0.1:8101/v1} \
	GENESIS_INTEGRATION_API_KEY=$${API_KEY:-genesis-local} \
	GENESIS_INTEGRATION_MODEL=$${MODEL:-qwen3.6-27b} \
	GENESIS_INTEGRATION_BASELINE=tests/integration/baselines/27b_v11_wave9.json \
	$(PYTEST) tests/integration/test_patch_regression_bounds.py -v

integration-35b: ## Run regression bounds against 35B PROD (env: HOST=<url>)
	@echo "Running integration regression bench against 35B PROD..."
	GENESIS_INTEGRATION_ENDPOINT=$${HOST:-http://127.0.0.1:8000/v1} \
	GENESIS_INTEGRATION_API_KEY=$${API_KEY:-genesis-local} \
	GENESIS_INTEGRATION_MODEL=$${MODEL:-qwen3.6-35b-a3b} \
	GENESIS_INTEGRATION_BASELINE=tests/integration/baselines/35b_v11_wave9.json \
	$(PYTEST) tests/integration/test_patch_regression_bounds.py -v

long-ctx-27b: ## Long-context smoke against 27B PROD (env: HOST, MAX_CTX)
	HOST=$${HOST:-http://127.0.0.1:8101} \
	MODEL=$${MODEL:-qwen3.6-27b} \
	START_CTX=$${START_CTX:-4096} \
	MAX_CTX=$${MAX_CTX:-131072} \
	bash tools/long_ctx_smoke.sh

long-ctx-35b: ## Long-context smoke against 35B PROD (env: HOST, MAX_CTX)
	HOST=$${HOST:-http://127.0.0.1:8000} \
	MODEL=$${MODEL:-qwen3.6-35b-a3b} \
	START_CTX=$${START_CTX:-4096} \
	MAX_CTX=$${MAX_CTX:-262144} \
	bash tools/long_ctx_smoke.sh

soak-1h-27b: ## 1h soak against 27B PROD (env: HOST)
	HOST=$${HOST:-http://127.0.0.1:8101} \
	MODEL=$${MODEL:-qwen3.6-27b} \
	DURATION_S=3600 \
	bash tools/soak.sh

soak-8h-27b: ## 8h soak against 27B PROD overnight (env: HOST)
	HOST=$${HOST:-http://127.0.0.1:8101} \
	MODEL=$${MODEL:-qwen3.6-27b} \
	DURATION_S=28800 \
	bash tools/soak.sh

smoke-content: ## OpenAI smoke — assert message.content not null (P0-3 audit gate)
	$(PYTHON) tools/openai_smoke.py \
		--host $${HOST:-http://127.0.0.1:8101} \
		--api-key $${API_KEY:-genesis-local} \
		--model $${MODEL:-qwen3.6-27b} \
		--max-tokens $${MAX_TOKENS:-128} \
		--enable-thinking $${ENABLE_THINKING:-false} \
		--assert-content

# ─── Aggregate ─────────────────────────────────────────────────────────

ci: gates docs-check audit-upstream-offline ## Run everything CI runs (no gh API call)
	@echo ""
	@echo "✓ All CI gates passed locally. Safe to push."

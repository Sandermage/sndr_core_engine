#!/usr/bin/env bash
# CI-gate: запрещает легаси-импорты в активном коде.
#
# Что ловим:
#   1. `vllm.sndr_core.patches.*` — пре-v10 namespace, переименован в
#      `vllm.sndr_core.integrations` (см. PROJECT_STATE_AUDIT 2026-05-12,
#      P0-1). Должно быть нулевое количество в tests/, vllm/sndr_core/,
#      scripts/, tools/.
#   2. `vllm._genesis.*` — пре-v11 namespace, удалён. Допускается только
#      в `docs/_internal/`, `docs/archive/`, `docs/reference/` (historical
#      provenance), `vllm/sndr_core/__init__.py` (back-compat alias),
#      и в комментариях/docstring'ах активных модулей (т.е. references
#      в строках, не реальных импортах).
#
# Output: список нарушений; exit 1 при наличии. Используется в pre-commit
# и make ci.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# Где искать. Whitelist эксклюзивный — анти-паттерн "найти везде кроме".
SEARCH_DIRS=(tests vllm/sndr_core scripts tools)
EXCLUDE_DIRS=(__pycache__ .git .ruff_cache .mypy_cache .pytest_cache)

# Allowlist путей: тут references на legacy namespace ОК (документация
# про back-compat, single-line docstring примеры, schema description'ы,
# READMEs с historical "Path corrected" annotations).
ALLOWLIST_PATTERNS=(
    "vllm/sndr_core/__init__.py"                                   # `if name == 'patches'` alias
    "vllm/sndr_core/schemas/patch_entry.schema.json"               # description example
    "vllm/sndr_core/compat/categories.py"                           # docstring examples
    "vllm/sndr_core/version.py"                                     # back-compat doc
    "vllm/sndr_core/locations/project_paths.py"                     # legacy fallback chain doc
    "vllm/sndr_core/integrations/upstream_compat.py"                # PR_40572 file_moved_from snapshot
    "vllm/sndr_core/apply/"                                         # provenance docstrings
    "vllm/sndr_core/compat/migrate.py"                              # historical compat
    "tools/genesis_vllm_plugin/README.md"                           # historical annotation
    "scripts/check_no_legacy_imports.sh"                            # gate описывает что ловит
)

declare -a EXC_FIND
for d in "${EXCLUDE_DIRS[@]}"; do
    EXC_FIND+=(-not -path "*/$d/*")
done

# Сборка списка всех python-файлов в search dirs.
# Используем POSIX-совместимый цикл (mapfile не во всех bash на macOS).
FILES=()
while IFS= read -r line; do
    FILES+=("$line")
done < <(
    find "${SEARCH_DIRS[@]}" -type f \( -name "*.py" -o -name "*.sh" -o -name "*.md" \) "${EXC_FIND[@]}" 2>/dev/null
)

violations=0
echo "=== check_no_legacy_imports.sh ==="
echo "scanning ${#FILES[@]} files in ${SEARCH_DIRS[*]}..."

is_allowlisted() {
    local file="$1"
    for pat in "${ALLOWLIST_PATTERNS[@]}"; do
        case "$file" in
            *"$pat"*) return 0 ;;
        esac
    done
    return 1
}

# 1. vllm.sndr_core.patches (пре-v10) — только в whitelisted descriptions
echo ""
echo "[1/2] forbidden: vllm.sndr_core.patches.*"
for f in "${FILES[@]}"; do
    if is_allowlisted "$f"; then
        continue
    fi
    matches=$(grep -Hn "vllm\.sndr_core\.patches\." "$f" 2>/dev/null || true)
    if [ -n "$matches" ]; then
        echo "$matches"
        violations=$(( violations + 1 ))
    fi
done

# 2. vllm._genesis as ACTIVE import (not just docstring/comment)
# Ловим только `import vllm._genesis.X` или `from vllm._genesis.X import`.
echo ""
echo "[2/2] forbidden: active vllm._genesis.* imports"
for f in "${FILES[@]}"; do
    matches=$(grep -Hn -E "^(from|import)[[:space:]]+vllm\._genesis(\.|[[:space:]])" "$f" 2>/dev/null || true)
    if [ -n "$matches" ]; then
        if ! is_allowlisted "$f"; then
            echo "$matches"
            violations=$(( violations + 1 ))
        fi
    fi
done

echo ""
if [ $violations -eq 0 ]; then
    echo "✓ legacy-import gate: clean ($violations violations)"
    exit 0
fi
echo "✗ legacy-import gate: $violations violation(s)"
echo ""
echo "Fix: переименуйте импорты:"
echo "  vllm.sndr_core.patches.<X>  →  vllm.sndr_core.integrations.<X>"
echo "  vllm._genesis.<X>           →  vllm.sndr_core.<X>"
echo "Если references реально historical — добавьте файл в ALLOWLIST_PATTERNS."
exit 1

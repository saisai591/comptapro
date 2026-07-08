#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
# ComptaPro — Runner de tests anti-régression (VPS / Linux)
# Usage: ./test.sh           # Quick check (no server)
#        ./test.sh --full    # Full check (needs server running)
#        ./test.sh --ci      # CI mode (JSON output)
# ═══════════════════════════════════════════════════════════
set -e

cd "$(dirname "$0")"
export PYTHONIOENCODING=utf-8

MODE="${1:---quick}"

echo "=== ComptaPro Regression Tests ==="
echo "Mode: $MODE"
echo

python3 regression_tests.py $MODE
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo "✅ All regression tests passed"
else
    echo ""
    echo "❌ REGRESSION DETECTED — do not deploy!"
fi

exit $EXIT_CODE

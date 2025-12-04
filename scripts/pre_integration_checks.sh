#!/bin/bash
#
# Pre-Integration Checks for Koku
#
# Run this script BEFORE integrating POC into koku to identify potential issues.
#
# Usage:
#   ./scripts/pre_integration_checks.sh /path/to/koku
#

set -e

KOKU_PATH="${1:-../koku}"
POC_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║           POC → Koku Pre-Integration Checks                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "POC Path:  $POC_PATH"
echo "Koku Path: $KOKU_PATH"
echo ""

PASS_COUNT=0
FAIL_COUNT=0
WARN_COUNT=0

check_pass() {
    echo "  ✅ $1"
    PASS_COUNT=$((PASS_COUNT + 1))
}

check_fail() {
    echo "  ❌ $1"
    FAIL_COUNT=$((FAIL_COUNT + 1))
}

check_warn() {
    echo "  ⚠️  $1"
    WARN_COUNT=$((WARN_COUNT + 1))
}

# ═══════════════════════════════════════════════════════════════════
# Check 1: Koku project exists
# ═══════════════════════════════════════════════════════════════════
echo "1️⃣  Checking koku project..."
if [ -d "$KOKU_PATH/koku" ]; then
    check_pass "Koku project found"
else
    check_fail "Koku project not found at $KOKU_PATH"
    echo "    → Provide correct path: ./scripts/pre_integration_checks.sh /path/to/koku"
    exit 1
fi

# ═══════════════════════════════════════════════════════════════════
# Check 2: Dependency compatibility
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "2️⃣  Checking dependency compatibility..."

# PyArrow
POC_PYARROW=$(grep "pyarrow" "$POC_PATH/requirements.txt" | head -1)
KOKU_PYARROW=$(grep "pyarrow" "$KOKU_PATH/Pipfile" 2>/dev/null | head -1 || echo "not found")
if [ -n "$KOKU_PYARROW" ] && [ "$KOKU_PYARROW" != "not found" ]; then
    check_pass "pyarrow: POC ($POC_PYARROW) ↔ Koku ($KOKU_PYARROW)"
else
    check_warn "pyarrow not explicitly in Koku Pipfile (may be transitive)"
fi

# psycopg2
POC_PSYCOPG=$(grep "psycopg2" "$POC_PATH/requirements.txt" | head -1)
KOKU_PSYCOPG=$(grep "psycopg2" "$KOKU_PATH/Pipfile" 2>/dev/null | head -1 || echo "not found")
if [ -n "$KOKU_PSYCOPG" ]; then
    check_pass "psycopg2: POC ($POC_PSYCOPG) ↔ Koku ($KOKU_PSYCOPG)"
else
    check_fail "psycopg2 not found in Koku Pipfile"
fi

# pandas
POC_PANDAS=$(grep "pandas" "$POC_PATH/requirements.txt" | head -1)
KOKU_PANDAS=$(grep "pandas" "$KOKU_PATH/Pipfile" 2>/dev/null | head -1 || echo "via pyarrow")
check_pass "pandas: POC ($POC_PANDAS) ↔ Koku ($KOKU_PANDAS)"

# s3fs (may need to be added)
if grep -q "s3fs" "$KOKU_PATH/Pipfile" 2>/dev/null; then
    check_pass "s3fs already in Koku Pipfile"
else
    check_warn "s3fs NOT in Koku Pipfile - will need to add"
fi

# ═══════════════════════════════════════════════════════════════════
# Check 3: Target directory structure
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "3️⃣  Checking target directory structure..."

TARGET_DIR="$KOKU_PATH/koku/masu/processor/parquet"
if [ -d "$TARGET_DIR" ]; then
    check_pass "Target directory exists: koku/masu/processor/parquet/"
else
    check_fail "Target directory missing: $TARGET_DIR"
fi

if [ -d "$TARGET_DIR/poc_aggregator" ]; then
    check_warn "poc_aggregator/ already exists - will be overwritten"
else
    check_pass "poc_aggregator/ does not exist (clean install)"
fi

# ═══════════════════════════════════════════════════════════════════
# Check 4: POC module syntax check
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "4️⃣  Checking POC module syntax..."

SYNTAX_ERRORS=0
for file in "$POC_PATH/src/"*.py; do
    if python3 -m py_compile "$file" 2>/dev/null; then
        : # pass
    else
        check_fail "Syntax error in $(basename $file)"
        SYNTAX_ERRORS=$((SYNTAX_ERRORS + 1))
    fi
done

if [ $SYNTAX_ERRORS -eq 0 ]; then
    check_pass "All POC modules have valid syntax"
fi

# ═══════════════════════════════════════════════════════════════════
# Check 5: Import analysis
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "5️⃣  Checking for problematic imports..."

# Check for absolute imports that would break
PROBLEM_IMPORTS=$(grep -rh "^from src\." "$POC_PATH/src/"*.py 2>/dev/null | wc -l)
if [ "$PROBLEM_IMPORTS" -gt 0 ]; then
    check_fail "Found $PROBLEM_IMPORTS 'from src.' imports that need fixing"
else
    check_pass "No 'from src.' imports found"
fi

# Check for relative imports (these are OK but note them)
RELATIVE_IMPORTS=$(grep -rh "^from \." "$POC_PATH/src/"*.py 2>/dev/null | wc -l)
if [ "$RELATIVE_IMPORTS" -gt 0 ]; then
    check_pass "Found $RELATIVE_IMPORTS relative imports (should work in package)"
fi

# ═══════════════════════════════════════════════════════════════════
# Check 6: Database table compatibility
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "6️⃣  Checking database tables referenced..."

# Extract table names from db_writer.py
echo "   Tables referenced in POC:"
grep -oE "reporting_[a-z_]+" "$POC_PATH/src/db_writer.py" | sort -u | while read table; do
    echo "     • $table"
done

check_warn "Verify these tables exist in koku with matching schemas"

# ═══════════════════════════════════════════════════════════════════
# Check 7: Environment variables
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "7️⃣  Checking environment variables used..."

echo "   Environment variables in POC:"
grep -rohE "os\.getenv\(['\"][A-Z_]+['\"]" "$POC_PATH/src/"*.py | \
    sed "s/os.getenv(['\"]//g" | sed "s/['\"]//g" | sort -u | while read var; do
    echo "     • $var"
done

check_warn "Ensure these are set in koku's environment"

# ═══════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "                        SUMMARY                                  "
echo "════════════════════════════════════════════════════════════════"
echo ""
echo "  ✅ Passed:   $PASS_COUNT"
echo "  ⚠️  Warnings: $WARN_COUNT"
echo "  ❌ Failed:   $FAIL_COUNT"
echo ""

if [ $FAIL_COUNT -gt 0 ]; then
    echo "❌ Pre-integration checks FAILED"
    echo "   Please fix the issues above before proceeding."
    exit 1
elif [ $WARN_COUNT -gt 0 ]; then
    echo "⚠️  Pre-integration checks PASSED with warnings"
    echo "   Review warnings before proceeding."
    exit 0
else
    echo "✅ Pre-integration checks PASSED"
    echo "   Ready to proceed with integration!"
    exit 0
fi



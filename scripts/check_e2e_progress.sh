#!/bin/bash
# Quick E2E Test Progress Checker

LOG_FILE="/tmp/e2e_full_suite_varied_costs.log"

echo "=================================================================================="
echo "E2E Test Suite Progress"
echo "=================================================================================="
echo ""

if [ ! -f "$LOG_FILE" ]; then
    echo "❌ Log file not found: $LOG_FILE"
    echo "Tests may not have started yet."
    exit 1
fi

# Check if tests are still running
if ps aux | grep -E "run_ocp_aws_scenario_tests" | grep -v grep > /dev/null; then
    echo "✅ Tests are RUNNING"
else
    echo "⏸️  Tests have COMPLETED or STOPPED"
fi

echo ""
echo "=== Test Results ==="
grep -E "Test [0-9]+/12:" "$LOG_FILE" | tail -5

echo ""
echo "=== Latest Status ==="
grep -E "✅ Scenario|❌ Scenario" "$LOG_FILE" | tail -5

echo ""
echo "=== Summary ==="
PASSED=$(grep -c "✅ Scenario passed" "$LOG_FILE" 2>/dev/null || echo "0")
FAILED=$(grep -c "❌ Scenario failed" "$LOG_FILE" 2>/dev/null || echo "0")
echo "Passed: $PASSED"
echo "Failed: $FAILED"

echo ""
echo "=== Full Log ==="
echo "View: tail -f $LOG_FILE"
echo "Last 20 lines:"
tail -20 "$LOG_FILE"


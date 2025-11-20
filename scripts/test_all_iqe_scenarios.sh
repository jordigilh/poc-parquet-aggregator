#!/bin/bash
# Test all IQE scenarios

set -e

export IQE_PLUGIN_DIR=/Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin

SCENARIOS=(
    "ocp_report_1.yml:Simple scenario"
    "ocp_report_advanced.yml:Comprehensive scenario"
    "ocp_report_missing_items.yml:Edge cases"
    "ocp_report_2.yml:Alternative scenario"
)

PASSED=0
FAILED=0
RESULTS=()

echo "================================================================================"
echo "Testing All IQE Scenarios"
echo "================================================================================"
echo ""

for scenario_info in "${SCENARIOS[@]}"; do
    IFS=':' read -r yaml_file description <<< "$scenario_info"

    echo "--------------------------------------------------------------------------------"
    echo "Testing: $description ($yaml_file)"
    echo "--------------------------------------------------------------------------------"

    if IQE_YAML="$yaml_file" timeout 180 ./scripts/run_iqe_validation.sh > /tmp/iqe_test_${yaml_file}.log 2>&1; then
        echo "✅ PASSED: $description"
        RESULTS+=("✅ $description ($yaml_file)")
        ((PASSED++))
    else
        echo "❌ FAILED: $description"
        echo "   Log: /tmp/iqe_test_${yaml_file}.log"
        RESULTS+=("❌ $description ($yaml_file)")
        ((FAILED++))
    fi
    echo ""
done

echo "================================================================================"
echo "Test Summary"
echo "================================================================================"
echo "Total: $((PASSED + FAILED))"
echo "Passed: $PASSED ✅"
echo "Failed: $FAILED ❌"
echo ""
echo "Results:"
for result in "${RESULTS[@]}"; do
    echo "  $result"
done
echo "================================================================================"

if [ $FAILED -eq 0 ]; then
    echo "🎉 ALL TESTS PASSED!"
    exit 0
else
    echo "❌ SOME TESTS FAILED"
    exit 1
fi


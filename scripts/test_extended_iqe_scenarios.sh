#!/bin/bash
# Test extended set of IQE scenarios

set -e

export IQE_PLUGIN_DIR=/Users/jgil/go/src/github.com/insights-onprem/iqe-cost-management-plugin

# Extended test scenarios (excluding templates with variables)
# NOTE: today_ocp_report_multiple_nodes_projects.yml is excluded due to nise bug
# (nise doesn't generate pod_2 on node_1/project_2, only generates 3 of 4 pods)
# This YAML is not used by any IQE test, so it's a known nise limitation
SCENARIOS=(
    "ocp_report_1.yml:Simple single-node scenario"
    "ocp_report_2.yml:Alternative single-node scenario"
    "ocp_report_7.yml:Scenario 7"
    "ocp_report_advanced.yml:Comprehensive multi-node scenario"
    "ocp_report_advanced_daily.yml:Advanced daily aggregation"
    "ocp_report_distro.yml:Distribution scenario"
    "ocp_report_forecast_const.yml:Forecast with constant data"
    "ocp_report_forecast_outlier.yml:Forecast with outliers"
    "ocp_report_missing_items.yml:Edge cases with missing data"
    "ocp_report_ros_0.yml:ROS scenario"
    "today_ocp_report_0.yml:Today report scenario 0"
    "today_ocp_report_1.yml:Today report scenario 1"
    "today_ocp_report_2.yml:Today report scenario 2"
    "today_ocp_report_multiple_nodes.yml:Multiple nodes scenario"
    "today_ocp_report_multiple_projects.yml:Multiple projects scenario"
    # "today_ocp_report_multiple_nodes_projects.yml:Multiple nodes and projects" # SKIPPED - nise bug
    "today_ocp_report_node.yml:Node-focused scenario"
    "today_ocp_report_tiers_0.yml:Tiered scenario 0"
    "today_ocp_report_tiers_1.yml:Tiered scenario 1"
)

PASSED=0
FAILED=0
SKIPPED=0
RESULTS=()

echo "================================================================================"
echo "Extended IQE Test Suite - ${#SCENARIOS[@]} Scenarios"
echo "================================================================================"
echo ""

for scenario_info in "${SCENARIOS[@]}"; do
    IFS=':' read -r yaml_file description <<< "$scenario_info"

    echo "--------------------------------------------------------------------------------"
    echo "Testing: $description ($yaml_file)"
    echo "--------------------------------------------------------------------------------"

    # Check if YAML exists
    if [ ! -f "${IQE_PLUGIN_DIR}/iqe_cost_management/data/openshift/${yaml_file}" ]; then
        echo "⚠️  SKIPPED: YAML file not found"
        RESULTS+=("⚠️  $description ($yaml_file) - FILE NOT FOUND")
        ((SKIPPED++))
        echo ""
        continue
    fi

    if IQE_YAML="$yaml_file" timeout 300 ./scripts/run_iqe_validation.sh > /tmp/iqe_test_${yaml_file}.log 2>&1; then
        echo "✅ PASSED: $description"
        RESULTS+=("✅ $description ($yaml_file)")
        ((PASSED++))
    else
        EXIT_CODE=$?
        if [ $EXIT_CODE -eq 124 ]; then
            echo "⏱️  TIMEOUT: $description (exceeded 5 minutes)"
            RESULTS+=("⏱️  $description ($yaml_file) - TIMEOUT")
            ((FAILED++))
        else
            echo "❌ FAILED: $description"
            echo "   Log: /tmp/iqe_test_${yaml_file}.log"
            RESULTS+=("❌ $description ($yaml_file)")
            ((FAILED++))
        fi
    fi
    echo ""
done

echo "================================================================================"
echo "Extended Test Suite Summary"
echo "================================================================================"
echo "Total: $((PASSED + FAILED + SKIPPED))"
echo "Passed: $PASSED ✅"
echo "Failed: $FAILED ❌"
echo "Skipped: $SKIPPED ⚠️"
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
    echo ""
    echo "Failed test logs:"
    for result in "${RESULTS[@]}"; do
        if [[ $result == ❌* ]]; then
            yaml=$(echo "$result" | sed 's/.*(\(.*\))/\1/')
            echo "  /tmp/iqe_test_${yaml}.log"
        fi
    done
    exit 1
fi


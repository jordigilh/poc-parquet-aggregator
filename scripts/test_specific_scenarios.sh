#!/bin/bash
#
# Quick script to test specific scenarios
# Usage: ./test_specific_scenarios.sh 20 21 23
#

set -e

POC_ROOT="/Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator"
cd "$POC_ROOT"

# Parse scenario numbers from arguments
SCENARIOS=("$@")

if [ ${#SCENARIOS[@]} -eq 0 ]; then
    echo "Usage: $0 <scenario_num> [scenario_num...]"
    echo "Example: $0 20 21 23"
    exit 1
fi

# Source the main test harness to get helper functions
source scripts/run_ocp_aws_scenario_tests.sh

# Run specified scenarios
for scenario_num in "${SCENARIOS[@]}"; do
    # Find the scenario file
    scenario_file=$(ls test-manifests/ocp-on-aws/ocp_aws_scenario_${scenario_num}_*.yml 2>/dev/null | head -1)

    if [ -z "$scenario_file" ]; then
        echo "❌ Scenario $scenario_num not found"
        continue
    fi

    scenario_name=$(basename "$scenario_file" .yml)
    echo ""
    echo "→ Testing $scenario_name..."

    # Run the scenario using the main test harness function
    # (This assumes the test harness exports its functions)
    bash -c "source scripts/run_ocp_aws_scenario_tests.sh && run_scenario '$scenario_name'"
done


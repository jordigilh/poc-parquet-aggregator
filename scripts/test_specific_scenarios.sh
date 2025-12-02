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
    # Find the scenario directory (new structure: XX-name/manifest.yml)
    scenario_dir=$(ls -d test-manifests/ocp-on-aws/${scenario_num}-* 2>/dev/null | head -1)
    
    if [ -z "$scenario_dir" ]; then
        echo "❌ Scenario $scenario_num not found"
        continue
    fi
    
    scenario_file="$scenario_dir/manifest.yml"
    if [ ! -f "$scenario_file" ]; then
        echo "❌ Manifest not found: $scenario_file"
        continue
    fi

    scenario_name=$(basename "$scenario_dir")
    echo ""
    echo "→ Testing $scenario_name..."

    # Run the scenario using the main test harness function
    # (This assumes the test harness exports its functions)
    bash -c "source scripts/run_ocp_aws_scenario_tests.sh && run_scenario '$scenario_name'"
done


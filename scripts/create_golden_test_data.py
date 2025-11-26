#!/usr/bin/env python3
"""
Create a GOLDEN TEST with 100% controlled data.

Bypasses nise entirely - we create the exact CSV data we need
to prove financial correctness.

Golden Test Scenario:
- 1 OCP node (i-golden001) with 4 CPU cores, 16GB memory
- 1 AWS EC2 instance (i-golden001) costing $4.608/day  
- 1 namespace "backend" using 37.5% of node resources
- Expected cost: $4.608 × 37.5% = $1.728

This proves the POC calculates costs correctly!


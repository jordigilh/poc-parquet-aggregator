# Work In Progress - Streaming Benchmarks + Storage Implementation

**Started**: November 21, 2024
**Status**: 🟡 IN PROGRESS

---

## User Decision Made ✅

**Storage/PV Aggregation**: ✅ **MANDATORY**
- Must implement complete Trino functionality
- Required for true 1:1 comparison
- Includes PVC/PV capacity and usage tracking
- Needed for OCP on AWS/Azure/GCP cost attribution

---

## Current Phase: Streaming Benchmarks

### Objective
Compare streaming vs in-memory performance to determine optimal `streaming_threshold_rows` configuration.

### Plan
1. **Phase 1** (15 min): Small-scale validation (small, medium, large)
2. **Phase 2** (1 hour): Crossover detection (large, xlarge, xxlarge)
3. **Phase 3** (2-4 hours): Production scale (production-small, production-medium)

### Progress

#### ✅ Completed
- [x] Created streaming benchmark plan (`STREAMING_BENCHMARK_PLAN.md`)
- [x] Created streaming comparison script (`scripts/run_streaming_comparison.sh`)
- [x] Script is executable and ready to run
- [x] Environment variables configured

#### 🟡 In Progress
- [ ] Phase 1: Running benchmarks for small, medium, large scales
- [ ] Analyzing results
- [ ] Generating comparison report

#### ⏳ Pending
- [ ] Phase 2: Crossover detection benchmarks
- [ ] Phase 3: Production scale benchmarks (if time permits)
- [ ] Document optimal streaming threshold

---

## Next Phase: Storage Implementation

### After Benchmarks Complete

#### 1. Check Storage Data Availability (30 min)
- [ ] Verify nise generates storage data
- [ ] Inspect storage Parquet schema
- [ ] Identify differences from pod aggregation

#### 2. Implement Storage Aggregator (4-6 hours)
- [ ] Create `src/aggregator_storage.py`
- [ ] Implement PVC/PV aggregation logic
- [ ] Add storage Parquet reader methods
- [ ] Integrate with `src/main.py`
- [ ] Handle label processing for volumes

#### 3. Test Storage Aggregation (2-3 hours)
- [ ] Create storage test scenarios
- [ ] Validate against expected outputs
- [ ] Test with IQE data (if storage data exists)
- [ ] Verify correctness of aggregations

#### 4. Combined Testing (1-2 hours)
- [ ] Test pod + storage together
- [ ] Verify both data_source types in output
- [ ] Test streaming mode with storage
- [ ] Run final IQE validation

#### 5. Final Benchmarks (1-2 hours)
- [ ] Pod-only vs Pod+Storage
- [ ] In-memory vs Streaming (both modes)
- [ ] Document performance impact

**Total Estimated Time**: ~10-15 hours

---

## Timeline

| Task | Duration | Status |
|------|----------|--------|
| **Streaming Benchmarks** |  |  |
| └─ Phase 1 (small, medium, large) | 15 min | 🟡 Starting |
| └─ Phase 2 (crossover detection) | 1 hour | ⏳ Pending |
| └─ Analysis & Documentation | 30 min | ⏳ Pending |
| **Storage Implementation** |  |  |
| └─ Check nise storage data | 30 min | ⏳ Pending |
| └─ Implement aggregator_storage.py | 4-6 hours | ⏳ Pending |
| └─ Test & validate | 2-3 hours | ⏳ Pending |
| └─ Combined testing | 1-2 hours | ⏳ Pending |
| └─ Final benchmarks | 1-2 hours | ⏳ Pending |
| **Total** | **10-15 hours** | 🟡 In Progress |

---

## Commands Reference

### Run Phase 1 Benchmarks (Start Now)
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
source venv/bin/activate

# Start Phase 1 (small, medium, large)
./scripts/run_streaming_comparison.sh small medium large
```

### Run Phase 2 Benchmarks (After Phase 1)
```bash
# Crossover detection
./scripts/run_streaming_comparison.sh large xlarge xxlarge
```

### Run Phase 3 Benchmarks (If Needed)
```bash
# Production scale (streaming only, will likely fail in-memory)
./scripts/run_streaming_comparison.sh production-small production-medium
```

### Check Storage Data Availability
```bash
# Generate small dataset and check for storage files
./scripts/generate_nise_benchmark_data.sh small /tmp/nise-storage-check

# Look for storage CSV files
ls -la /tmp/nise-storage-check/*storage*

# Check if nise generates storage data
grep -r "storage" /tmp/nise-storage-check/
```

---

## Expected Deliverables

### From Streaming Benchmarks
1. ✅ `benchmark_results/streaming_comparison_*/SUMMARY.csv` - Raw metrics
2. ✅ `benchmark_results/streaming_comparison_*/COMPARISON_REPORT.md` - Analysis
3. ✅ Updated `config.yaml` with optimal `streaming_threshold_rows`
4. ✅ Documentation in README about when to use streaming

### From Storage Implementation
1. ✅ `src/aggregator_storage.py` - Storage aggregator module
2. ✅ Updated `src/main.py` - Integration with pod aggregator
3. ✅ Test scenarios for storage validation
4. ✅ IQE validation passing with both pod + storage
5. ✅ Final benchmark report comparing:
   - Pod-only vs Pod+Storage
   - In-memory vs Streaming
   - Performance impact analysis

---

## Success Criteria

### Streaming Benchmarks
- [ ] Both modes complete successfully at all tested scales
- [ ] Identify optimal `streaming_threshold_rows` value (expected: 100K-250K)
- [ ] Document memory vs speed trade-off with data
- [ ] Clear guidance on when to enable streaming

### Storage Implementation
- [ ] Storage aggregator implements all Trino functionality
- [ ] Both `data_source='Pod'` and `data_source='Storage'` rows in output
- [ ] All IQE tests pass (if storage test data available)
- [ ] 1:1 functional parity with Trino for OCP aggregation

---

## Risks & Mitigations

### Risk 1: Nise May Not Generate Storage Data
**Likelihood**: Medium
**Impact**: High (blocks storage implementation)
**Mitigation**:
- Check immediately after Phase 1 benchmarks
- If no storage data, create synthetic test files
- Or implement based on Trino SQL schema inference

### Risk 2: Large Benchmarks May Timeout/Fail
**Likelihood**: Medium (for xxlarge, production-*)
**Impact**: Low (still validates concept)
**Mitigation**:
- Use timeout command (600s = 10 min)
- Focus on Phase 1 & 2 for decision-making
- Phase 3 is "nice to have" validation

### Risk 3: Storage Implementation More Complex Than Expected
**Likelihood**: Low (simpler than pod aggregation)
**Impact**: Medium (takes longer)
**Mitigation**:
- Storage aggregation has fewer joins
- No capacity calculation needed
- Can copy structure from aggregator_pod.py

---

## Current Status Summary

```
✅ Overnight Work Complete:
   - NaN regression fixed
   - Bulk COPY working
   - 18/18 IQE tests passing
   - Phase 2 enhancements complete

🟡 Current Task:
   - Streaming benchmarks Phase 1 (15 min)

⏳ Next Up:
   - Storage/PV aggregation implementation
   - Full Trino parity validation
```

---

*Last Updated: November 21, 2024*
*Ready to proceed with Phase 1 benchmarks!*


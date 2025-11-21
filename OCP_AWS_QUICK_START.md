# OCP on AWS - Quick Start Guide

## 📋 TL;DR

**What**: Replace Trino+Hive aggregation for OCP on AWS provider with custom Python aggregator

**Complexity**: HIGH (3.3x more complex than standalone OCP)

**Effort**: 3-4 weeks

**Status**: ✅ Triage complete, ready to implement

---

## 📚 Documentation

| Document | Purpose | Size |
|----------|---------|------|
| **OCP_AWS_SUMMARY.md** | Executive summary, start here | 8K lines |
| **OCP_AWS_TRIAGE.md** | Detailed technical analysis | 18K lines |
| **OCP_AWS_QUICK_START.md** | This file - quick reference | - |

---

## 🎯 Key Differences from OCP POC

| Aspect | OCP POC | OCP+AWS POC |
|--------|---------|-------------|
| Data Sources | 1 | 2 |
| Matching Logic | None | Resource ID + Tag |
| Cost Types | Simple | 4 types |
| Aggregation Tables | 1 | 9 |
| Complexity | LOW | HIGH |
| Effort | 2 weeks | 3-4 weeks |

---

## 🔑 Core Algorithms

### 1. Resource ID Matching (Complexity: 8/10)

**What**: Match AWS resources to OCP by instance/volume IDs

**Example**:
```
AWS: i-0123456789abcdef0 (EC2)
OCP: ip-10-0-1-100 (node with resource_id: i-0123456789abcdef0)
→ MATCH ✅
```

### 2. Tag Matching (Complexity: 7/10)

**What**: Match by special OpenShift tags on AWS resources

**Tags**:
- `openshift_cluster`
- `openshift_node`
- `openshift_project`

### 3. Disk Capacity Calculation (Complexity: 9/10) ⭐

**What**: Calculate EBS volume capacity for cost attribution

**Formula**:
```
Capacity (GB) = Total Cost / (Hourly Rate / Hours in Month)
```

**Note**: This is the MOST COMPLEX algorithm

### 4. Network Cost Attribution (Complexity: 7/10)

**What**: Handle node-level network costs

**Solution**: Assign to namespace "Network unattributed"

### 5. Cost Attribution (Complexity: 6/10)

**What**: Attribute AWS costs to OCP namespaces

**Logic**: Cost per pod = AWS cost × (pod CPU / node CPU)

---

## 📁 Trino SQL Files to Replace

### Phase 1: Daily Summary (4 files)

```
populate_daily_summary/
├── 0_prepare_daily_summary_tables.sql      (LOW complexity)
├── 1_resource_matching_by_cluster.sql      (HIGH - CRITICAL)
├── 2_summarize_data_by_cluster.sql         (VERY HIGH - CRITICAL)
└── 3_reporting_ocpawscostlineitem_...sql   (LOW complexity)
```

### Phase 2: PostgreSQL Aggregations (9 files)

```
├── reporting_ocpawscostlineitem_project_daily_summary_p.sql  (detailed)
├── reporting_ocpaws_cost_summary_p.sql                       (cluster totals)
├── reporting_ocpaws_cost_summary_by_account_p.sql            (by account)
├── reporting_ocpaws_cost_summary_by_service_p.sql            (by service)
├── reporting_ocpaws_cost_summary_by_region_p.sql             (by region)
├── reporting_ocpaws_compute_summary_p.sql                    (EC2 only)
├── reporting_ocpaws_storage_summary_p.sql                    (storage only)
├── reporting_ocpaws_database_summary_p.sql                   (RDS, etc.)
└── reporting_ocpaws_network_summary_p.sql                    (VPC, etc.)
```

---

## 🗓️ Implementation Timeline

### Week 1: Core Infrastructure + Tag Matching

**Days 1-2**: AWS data loading
- Read AWS CUR Parquet files
- Filter by date range and source UUID

**Days 3-4**: Resource ID matching
- Implement suffix matching for nodes
- Implement matching for volumes (CSI handles)

**Days 5-7**: Tag matching
- Query PostgreSQL for enabled keys
- Filter AWS tags
- Implement tag matching logic

**Deliverables**:
- `src/aws_data_loader.py`
- `src/resource_matcher.py`
- `src/tag_matcher.py`

### Week 2: Cost Attribution + Special Cases

**Days 8-10**: Basic cost join
- Join OCP usage with AWS costs
- Calculate pod-level attribution

**Days 11-12**: Disk capacity
- Implement capacity calculation
- Read hourly AWS data

**Days 13-15**: Storage + Network
- Storage cost attribution
- Network cost handling
- Special line item types

**Deliverables**:
- `src/cost_attributor.py`
- `src/disk_capacity_calculator.py`
- `src/network_cost_handler.py`

### Week 3: Aggregation + Integration

**Days 16-20**: Aggregations
- Implement 9 aggregation tables
- Test each aggregation

**Days 21-25**: Integration
- Main pipeline
- Error handling
- Logging

**Deliverables**:
- `src/aggregator_ocpaws.py`
- `src/main_ocpaws.py`

### Week 4: Testing + Documentation

**Days 26-30**: Testing
- Unit tests
- Integration tests
- IQE validation

**Days 31-33**: Documentation
- Technical architecture
- Validation results
- Performance analysis

**Deliverables**:
- Test suite
- Documentation

---

## 🚀 Quick Commands

### Run OCP POC (for reference)
```bash
cd /Users/jgil/go/src/github.com/insights-onprem/poc-parquet-aggregator
source venv/bin/activate
python src/main.py
```

### Run Tests
```bash
./scripts/test_iqe_production_scenarios.sh
```

### Run Benchmarks
```bash
./scripts/run_empirical_benchmarks.sh
```

---

## 📊 Data Flow

```
┌─────────────┐         ┌─────────────┐
│  OCP Data   │         │  AWS Data   │
│  (Parquet)  │         │  (Parquet)  │
└──────┬──────┘         └──────┬──────┘
       │                       │
       │  ┌────────────────────┘
       │  │
       ▼  ▼
┌─────────────────────────────────┐
│  Resource ID + Tag Matching     │
│  (1_resource_matching...)       │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Cost Attribution               │
│  (2_summarize_data...)          │
│  - Join OCP usage with AWS cost │
│  - Apply label precedence       │
│  - Calculate disk capacities    │
│  - Handle network costs         │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  Combined Daily Summary         │
│  (Hive Parquet Table)           │
└────────────┬────────────────────┘
             │
             ▼
┌─────────────────────────────────┐
│  9 PostgreSQL Aggregations      │
│  - Detailed line items          │
│  - Cluster totals               │
│  - By account/service/region    │
│  - By resource type             │
└─────────────────────────────────┘
```

---

## 🎯 Success Criteria

### Must Have ✅

- [ ] Cluster totals match Trino (within 0.01%)
- [ ] Namespace totals match Trino (within 0.1%)
- [ ] All 9 aggregation tables match Trino
- [ ] Resource ID matching > 99% accurate
- [ ] Tag matching > 99% accurate
- [ ] All IQE tests pass

### Should Have 🎯

- [ ] Memory < 2x Trino
- [ ] Processing time < 3x Trino
- [ ] Handles 100K AWS line items
- [ ] Streaming mode works

---

## ⚠️ Risk Mitigation

### 🔴 HIGH: Disk Capacity Accuracy

**Risk**: Formula may not match Trino exactly

**Mitigation**:
1. Validate with real data early
2. Compare intermediate results with Trino
3. Document any differences

### 🔴 HIGH: Resource Matching Edge Cases

**Risk**: Some resources may not match

**Mitigation**:
1. Comprehensive test coverage
2. Fallback to tag matching
3. Log unmatched resources

### 🔴 HIGH: Performance

**Risk**: AWS data can be massive

**Mitigation**:
1. Use streaming mode from day 1
2. Implement chunking
3. Monitor memory continuously

---

## 🔧 Reusable from OCP POC

✅ **Parquet Reader** - Streaming, parallel, columnar filtering
✅ **Label Precedence** - Already in OCP aggregation
✅ **Memory Optimization** - Categorical types, GC
✅ **PostgreSQL Writer** - Bulk inserts
✅ **Config Management** - YAML config
✅ **Benchmarking** - Performance profiling
✅ **Utils** - Logging, error handling

**Estimated Reuse**: 30-40%

---

## 🆕 New Components to Build

❌ **AWS Data Loader** - Read AWS CUR
❌ **Resource Matcher** - Match by resource ID
❌ **Tag Matcher** - Match by tags
❌ **Cost Attributor** - Join OCP + AWS
❌ **Disk Capacity Calculator** - Calculate capacities
❌ **Network Cost Handler** - Handle network costs
❌ **OCP+AWS Aggregator** - 9 aggregations
❌ **Main Pipeline** - Orchestrate
❌ **IQE Validator** - Validate results

**Estimated New**: 60-70%

---

## 📈 Performance Expectations (With Optimizations)

### Memory Usage

| Scale | AWS Rows | OCP Rows | Memory (Standard) | Memory (Streaming) |
|-------|----------|----------|-------------------|-------------------|
| Small | 1K | 1K | 100-200 MB | N/A |
| Medium | 10K | 10K | 500-800 MB | N/A |
| Large | 100K | 100K | 2-3 GB | N/A |
| XL | 1M | 1M | 10-15 GB | 3-4 GB |
| XXL | 10M | 10M | ❌ Not feasible | 3-4 GB |

### Processing Time

**Expected**: **2-3x FASTER** than Trino (with parallel reading)

### Performance Optimizations Applied

From OCP POC (proven results):

1. **Streaming Mode** - 80-90% memory savings
2. **Parallel Reading** - 2-4x speedup
3. **Column Filtering** - 30-40% memory savings
4. **Categorical Types** - 50-70% string memory savings
5. **Memory Cleanup** - 10-20% peak reduction
6. **Batch Writes** - 10-50x database speedup

**Result**: Can handle 10M+ rows with 8 GB container

---

## 🤔 Questions to Resolve

### 1. Data Generation

**Q**: Can nise generate OCP+AWS scenarios?

**Options**:
- A) Use nise if supported
- B) Build synthetic generator
- C) Use production sample

**Action**: Investigate nise first

### 2. Hourly vs Daily Data

**Q**: Do we need hourly AWS data for capacity calculation?

**Impact**: Affects accuracy

**Action**: Confirm with Trino SQL

### 3. Enabled Tag Keys

**Q**: Which tags should be enabled by default?

**Impact**: Affects matching coverage

**Action**: Query `reporting_enabledtagkeys`

---

## 📞 Next Steps

1. **Review triage** with technical lead
2. **Investigate nise** capabilities for OCP+AWS
3. **Set up dev environment** (reuse OCP POC)
4. **Start Phase 1** (AWS data loading)
5. **Validate matching** against Trino early

---

## 📖 Related Documents

- **OCP_AWS_SUMMARY.md** - Executive summary (read first)
- **OCP_AWS_TRIAGE.md** - Detailed technical analysis
- **TECHNICAL_ARCHITECTURE.md** - OCP POC architecture (for reference)
- **FINAL_POC_RESULTS.md** - OCP POC results (for reference)

---

## 🎓 Key Learnings from OCP POC

1. **Validate early and often** - Catch issues before they compound
2. **Performance from day 1** - Use streaming mode from start
3. **Comprehensive testing** - Unit + integration + IQE
4. **Document as you go** - Capture decisions immediately
5. **Incremental complexity** - Start simple, add gradually

---

**Status**: ✅ Ready to proceed

**Confidence**: HIGH (85%)

**Recommendation**: Start with Phase 1 implementation

---

**Document**: OCP_AWS_QUICK_START.md  
**Date**: November 21, 2025  
**Next Update**: After Phase 1 completion


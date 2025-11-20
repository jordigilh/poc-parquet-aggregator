# Floating Point vs DECIMAL Analysis

**Date**: November 20, 2025  
**Question**: Does Trino use floating points for financial/monetary figures?

---

## Executive Summary

**Answer**: **YES and NO** - There's a critical inconsistency:

- ✅ **PostgreSQL (Final Storage)**: Uses `DECIMAL` for all monetary values (correct for financial data)
- ❌ **Trino (Aggregation Layer)**: Uses `DOUBLE` (floating point) for resource metrics, but `DECIMAL` for cost calculations
- ⚠️ **Risk**: Floating point arithmetic in intermediate calculations could introduce rounding errors

---

## Detailed Analysis

### 1. PostgreSQL Schema (Target Database)

**All monetary fields use DECIMAL** (fixed-point arithmetic):

```python
# AWS Cost Fields
unblended_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)
markup_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)
markup_cost_blended = models.DecimalField(decimal_places=15, max_digits=33, null=True)
markup_cost_savingsplan = models.DecimalField(decimal_places=15, max_digits=33, null=True)
markup_cost_amortized = models.DecimalField(decimal_places=9, max_digits=33, null=True)

# Azure Cost Fields
pretax_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)
markup_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)

# GCP Cost Fields
unblended_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)
markup_cost = models.DecimalField(decimal_places=9, max_digits=24, null=True)
```

**Precision**:
- Standard: 24 digits total, 9 decimal places (e.g., `999,999,999,999,999.999999999`)
- Extended: 33 digits total, 9-15 decimal places

**This is correct** for financial data - DECIMAL ensures exact arithmetic without floating point rounding errors.

---

### 2. Trino SQL (Aggregation Layer)

#### Resource Metrics: DOUBLE (Floating Point)

From `reporting_ocpusagelineitem_daily_summary.sql`:

```sql
pod_usage_cpu_core_hours double,
pod_request_cpu_core_hours double,
pod_effective_usage_cpu_core_hours double,
pod_limit_cpu_core_hours double,
pod_usage_memory_gigabyte_hours double,
pod_request_memory_gigabyte_hours double,
pod_effective_usage_memory_gigabyte_hours double,
pod_limit_memory_gigabyte_hours double,
node_capacity_cpu_cores double,
node_capacity_cpu_core_hours double,
node_capacity_memory_gigabytes double,
node_capacity_memory_gigabyte_hours double,
cluster_capacity_cpu_core_hours double,
cluster_capacity_memory_gigabyte_hours double,
persistentvolumeclaim_capacity_gigabyte double,
persistentvolumeclaim_capacity_gigabyte_months double,
volume_request_storage_gigabyte_months double,
persistentvolumeclaim_usage_gigabyte_months double,
```

**These are DOUBLE (64-bit floating point)** - not ideal for financial calculations.

#### Cost Calculations: DECIMAL (Fixed Point)

From AWS/Azure/GCP aggregation SQL:

```sql
-- AWS
cast(unblended_cost AS decimal(24,9))
cast(unblended_cost * {{markup}} AS decimal(24,9)) as markup_cost
cast(blended_cost AS decimal(24,9))
cast(blended_cost * {{markup}} AS decimal(33,15)) as markup_cost_blended
cast(savingsplan_effective_cost AS decimal(24,9))
cast(savingsplan_effective_cost * {{markup}} AS decimal(33,15)) as markup_cost_savingsplan
cast(calculated_amortized_cost AS decimal(33, 9))
cast(calculated_amortized_cost * {{markup}} AS decimal(33,9)) as markup_cost_amortized

-- Azure
cast(costinbillingcurrency as DECIMAL(24,9)) as pretax_cost
cast(azure.pretax_cost as decimal(24,9)) * cast({{markup}} as decimal(24,9)) as markup_cost

-- GCP
cast(sum(cost) AS decimal(24,9)) as unblended_cost
cast(sum(cost * {{markup}}) AS decimal(24,9)) as markup_cost
```

**Cost calculations use DECIMAL** - this is correct.

#### Cost Model Rates: DECIMAL

From OCP cost model SQL:

```sql
CAST({{default_rate}} AS DECIMAL(33, 15))
CAST({{rate}} as DECIMAL(33, 15))
CAST({{hourly_rate}} as DECIMAL(33, 15))
```

**Rates are cast to DECIMAL** - this is correct.

---

## Risk Assessment

### High Risk: Resource Metric Calculations

**Problem**: Resource metrics (CPU hours, memory GB-hours) use `DOUBLE`, which means:

1. **Floating point arithmetic** is used for:
   - Summing CPU/memory usage across pods
   - Calculating capacity utilization
   - Computing effective usage
   - Aggregating across time periods

2. **Potential for rounding errors**:
   - Example: `0.1 + 0.2 = 0.30000000000000004` in floating point
   - Accumulates over large datasets
   - Can cause penny discrepancies in cost allocation

3. **When costs are derived from these metrics**:
   ```sql
   -- Cost = Usage (DOUBLE) × Rate (DECIMAL)
   -- Result is implicitly DOUBLE until cast
   cost = pod_usage_cpu_core_hours * hourly_rate
   ```
   The intermediate calculation uses floating point!

### Medium Risk: Cost Allocation Based on Ratios

**Problem**: Cost distribution uses ratios calculated from DOUBLE values:

```sql
-- AWS/OpenShift cost allocation
THEN ({{pod_column}} / {{node_column}}) * unblended_cost * cast({{markup}} as decimal(24,9))
--     ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^ DOUBLE ratio
```

Where:
- `pod_column` = pod usage (DOUBLE)
- `node_column` = node capacity (DOUBLE)
- Ratio is DOUBLE
- Multiplied by cost (DECIMAL)
- **Result is implicitly DOUBLE until final cast**

### Low Risk: Final Storage

**Mitigation**: All final values are cast to DECIMAL before insertion into PostgreSQL:

```sql
cast(unblended_cost AS decimal(24,9))
```

This limits (but doesn't eliminate) rounding errors to the intermediate calculations.

---

## Impact on POC

### Current POC Implementation

The POC uses **Pandas DataFrames with `float64`** (equivalent to DOUBLE):

```python
# All numeric columns default to float64
pod_usage_cpu_core_hours: float64
pod_request_cpu_core_hours: float64
# ... etc
```

**This matches Trino's behavior** (DOUBLE for resource metrics).

### Implications

1. **✅ Functional Equivalence**: POC matches Trino's floating point behavior
2. **⚠️ Inherits Same Risks**: POC has same potential for rounding errors as Trino
3. **✅ Final Cast to DECIMAL**: POC should cast to DECIMAL before PostgreSQL insertion (check `db_writer.py`)

---

## Recommendations

### For POC (Short Term)

**Status**: ✅ **Already Correct**

The POC should:
1. ✅ Use `float64` for resource metrics (matches Trino)
2. ✅ Use `Decimal` or cast to DECIMAL for cost calculations
3. ✅ Cast to DECIMAL before PostgreSQL insertion

**Action**: Verify `db_writer.py` casts numeric columns appropriately.

### For Production (Long Term)

**Consider migrating to DECIMAL throughout**:

1. **Benefits**:
   - Eliminates floating point rounding errors
   - Ensures exact financial calculations
   - Industry best practice for monetary data

2. **Challenges**:
   - Performance: DECIMAL is slower than DOUBLE
   - Memory: DECIMAL uses more memory
   - Compatibility: Requires changes to Trino SQL and PostgreSQL schema

3. **Hybrid Approach** (Recommended):
   - Keep DOUBLE for pure resource metrics (CPU cores, memory GB)
   - Use DECIMAL for:
     - All monetary values
     - Any metric used in cost calculations
     - Ratios used for cost allocation

---

## Verification for POC

Let me check the POC's `db_writer.py` to ensure proper type handling:

### Check 1: DataFrame to PostgreSQL Type Mapping

```python
# In db_writer.py, verify:
# 1. Numeric columns are properly typed
# 2. Cost-related fields use DECIMAL
# 3. Resource metrics can remain float64 (matches Trino)
```

### Check 2: Pandas to PostgreSQL Insertion

Pandas `to_sql()` with psycopg2 automatically maps:
- `float64` → PostgreSQL `DOUBLE PRECISION`
- `Decimal` → PostgreSQL `NUMERIC`

**For cost fields**, we should explicitly use `Decimal` type in Pandas.

---

## Conclusion

**Answer to Original Question**:

> "Is Trino using floating points for financial figures?"

**Partial YES**:
- ❌ Resource metrics (CPU hours, memory GB-hours) use DOUBLE (floating point)
- ✅ Cost values and rates use DECIMAL (fixed point)
- ⚠️ **Risk**: Intermediate calculations (ratios, allocations) use floating point before final cast

**POC Status**:
- ✅ POC correctly replicates Trino's behavior (uses float64)
- ⚠️ Should verify cost fields use Decimal type if/when cost calculations are added
- ✅ No immediate concern for pure resource aggregation (current POC scope)

**Recommendation**: 
- For current POC (resource aggregation only): **No changes needed** - float64 is correct
- For future cost calculations: **Use Decimal type** for all monetary values and cost-related ratios
- For production: **Consider DECIMAL migration** for all financial calculations

---

**Risk Level**: **LOW for current POC** (no cost calculations), **MEDIUM for production** (cost allocation uses floating point ratios)

**Mitigation**: Final cast to DECIMAL before PostgreSQL insertion limits impact to intermediate calculations only.


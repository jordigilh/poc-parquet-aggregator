"""
Disk Capacity Calculator for OCP-on-AWS

Calculates EBS volume capacities from AWS billing data for storage cost attribution.

Formula:
    Capacity (GB) = Total Cost / (Hourly Rate / Hours in Month)

Example:
    - EBS volume costs $10/month
    - Hourly rate: $0.0134/GB-hour
    - Hours in month: 744 (31 days × 24 hours)
    - Capacity = $10 / ($0.0134 / 744) = 10 / 0.000018 = 556 GB

Key Logic:
1. Group AWS line items by resource_id and usage_start
2. Only process EBS volumes matched to OCP PVs (via CSI volume handles)
3. Calculate MAX(cost) and MAX(rate) per group
4. Apply formula: capacity = cost / (rate / hours_in_month)
5. Round to nearest integer
6. Filter to positive capacities

Complexity: VERY HIGH (9/10) - MOST COMPLEX ALGORITHM
"""

import pandas as pd
import numpy as np
import calendar
from datetime import datetime
from typing import Dict, Set
from .utils import get_logger, PerformanceTimer


class DiskCapacityCalculator:
    """
    Calculate EBS volume capacities from AWS billing data.

    This class implements the most complex algorithm in the OCP-AWS integration:
    deriving physical disk capacity from AWS billing data to properly attribute
    storage costs to OCP persistent volumes.
    """

    def __init__(self, config: Dict):
        """
        Initialize disk capacity calculator.

        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = get_logger("disk_capacity_calculator")

        self.logger.info("Initialized disk capacity calculator")

    def calculate_hours_in_month(self, year: int, month: int) -> int:
        """
        Calculate total hours in a given month.

        Args:
            year: Year (e.g., 2025)
            month: Month (1-12)

        Returns:
            Total hours in the month
        """
        days_in_month = calendar.monthrange(year, month)[1]
        hours = days_in_month * 24

        self.logger.debug(
            f"Calculated hours in month",
            year=year,
            month=month,
            days=days_in_month,
            hours=hours
        )

        return hours

    def extract_matched_volumes(
        self,
        ocp_storage_usage_df: pd.DataFrame
    ) -> Set[str]:
        """
        Extract CSI volume handles AND PV names from OCP storage usage.

        Trino SQL (line 76-77 in 1_resource_matching_by_cluster.sql):
            substr(resource_id, -length(persistentvolume)) = persistentvolume
            OR substr(resource_id, -length(csi_volume_handle)) = csi_volume_handle

        This supports BOTH:
        - CSI volume handles (e.g., vol-0123...)
        - PV names (e.g., pv-database-001)

        Args:
            ocp_storage_usage_df: OCP storage usage DataFrame

        Returns:
            Set of volume identifiers (CSI handles OR PV names)
        """
        if ocp_storage_usage_df.empty:
            self.logger.warning("OCP storage usage DataFrame is empty")
            return set()

        volume_set = set()

        # Extract CSI volume handles
        if 'csi_volume_handle' in ocp_storage_usage_df.columns:
            csi_handles = ocp_storage_usage_df[
                ocp_storage_usage_df['csi_volume_handle'].notna() &
                (ocp_storage_usage_df['csi_volume_handle'] != '')
            ]['csi_volume_handle'].unique()
            volume_set.update(csi_handles)

        # Extract PV names (for non-CSI storage)
        if 'persistentvolume' in ocp_storage_usage_df.columns:
            pv_names = ocp_storage_usage_df[
                ocp_storage_usage_df['persistentvolume'].notna() &
                (ocp_storage_usage_df['persistentvolume'] != '')
            ]['persistentvolume'].unique()
            volume_set.update(pv_names)

        self.logger.info(
            f"Extracted {len(volume_set)} unique CSI volume handles from OCP storage"
        )

        return volume_set

    def calculate_disk_capacities(
        self,
        aws_line_items_df: pd.DataFrame,
        ocp_storage_usage_df: pd.DataFrame,
        year: int,
        month: int
    ) -> pd.DataFrame:
        """
        Calculate disk capacities for matched EBS volumes.

        This is the core disk capacity calculation algorithm that implements:

        Trino SQL:
            ROUND(
                MAX(aws.lineitem_unblendedcost) /
                (MAX(aws.lineitem_unblendedrate) / MAX(hours.in_month))
            ) AS capacity

        Formula:
            Capacity (GB) = Total Cost / (Hourly Rate / Hours in Month)

        Steps:
        1. Extract matched volumes from OCP storage
        2. Filter AWS line items to matched EBS volumes
        3. Group by resource_id and usage_date
        4. Calculate MAX(cost) and MAX(rate) per group
        5. Apply capacity formula
        6. Filter to positive capacities

        Args:
            aws_line_items_df: AWS line items DataFrame
            ocp_storage_usage_df: OCP storage usage DataFrame
            year: Year for hours calculation
            month: Month for hours calculation

        Returns:
            DataFrame with columns: resource_id, capacity, usage_start
        """
        with PerformanceTimer("Calculate disk capacities", self.logger):
            if aws_line_items_df.empty:
                self.logger.warning("AWS line items DataFrame is empty")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            if ocp_storage_usage_df.empty:
                self.logger.warning("OCP storage usage DataFrame is empty")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            # Step 1: Extract matched volumes (CSI handles)
            matched_volumes = self.extract_matched_volumes(ocp_storage_usage_df)

            if not matched_volumes:
                self.logger.warning("No matched volumes found, returning empty DataFrame")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            # Step 2: Filter AWS to matched EBS volumes only
            # Use matched_resource_id (set by resource matcher) for filtering
            # This handles cases where nise adds prefixes (e.g., "vol-vol-test0001" vs "vol-test0001")
            # Koku uses suffix matching: substr(resourceid, -length(csi_handle)) = csi_handle

            # Check if 'lineitem_resourceid' exists (required for fallback)
            if 'lineitem_resourceid' not in aws_line_items_df.columns:
                self.logger.error("Missing 'lineitem_resourceid' column in AWS data")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            # Define suffix matching function (used as fallback)
            def matches_volume_suffix(resource_id):
                """Check if resource_id ends with any of the matched volume handles."""
                if pd.isna(resource_id):
                    return False
                resource_id_str = str(resource_id)
                for volume_handle in matched_volumes:
                    if resource_id_str.endswith(volume_handle):
                        return True
                return False

            # Try matched_resource_id first (for EC2-attached EBS volumes matched by resource matcher)
            # Fall back to suffix matching for EBS volumes not matched by resource matcher
            if 'matched_resource_id' in aws_line_items_df.columns:
                # Filter by matched_resource_id (for resource matcher matched volumes)
                matched_by_id = aws_line_items_df['matched_resource_id'].isin(matched_volumes)

                # Also try suffix matching on lineitem_resourceid (for non-matched EBS volumes)
                matched_by_suffix = aws_line_items_df['lineitem_resourceid'].apply(matches_volume_suffix)

                # Combine both filters with OR
                aws_filtered = aws_line_items_df[matched_by_id | matched_by_suffix].copy()

                self.logger.debug(
                    f"Filtering by matched_resource_id OR suffix matching",
                    matched_by_id=matched_by_id.sum(),
                    matched_by_suffix=matched_by_suffix.sum(),
                    total_filtered=len(aws_filtered)
                )
            else:
                # No matched_resource_id column - use suffix matching only
                aws_filtered = aws_line_items_df[
                    aws_line_items_df['lineitem_resourceid'].apply(matches_volume_suffix)
                ].copy()
                self.logger.debug(
                    f"Filtering by suffix matching on lineitem_resourceid only"
                )

            if aws_filtered.empty:
                self.logger.warning(
                    f"No AWS line items found for {len(matched_volumes)} matched volumes"
                )
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            self.logger.info(
                f"Filtered to {len(aws_filtered)} AWS line items for {len(matched_volumes)} volumes"
            )

            # Step 3: Prepare usage_date for grouping
            if 'lineitem_usagestartdate' in aws_filtered.columns:
                aws_filtered['usage_date'] = pd.to_datetime(
                    aws_filtered['lineitem_usagestartdate']
                ).dt.date
            else:
                self.logger.error("Missing 'lineitem_usagestartdate' column")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            # Step 4: Group by resource_id and usage_date, calculate MAX(cost) and MAX(rate)
            if 'lineitem_unblendedcost' not in aws_filtered.columns:
                self.logger.error("Missing 'lineitem_unblendedcost' column")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            if 'lineitem_unblendedrate' not in aws_filtered.columns:
                self.logger.error("Missing 'lineitem_unblendedrate' column")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            capacity_df = aws_filtered.groupby(
                ['lineitem_resourceid', 'usage_date']
            ).agg({
                'lineitem_unblendedcost': 'max',
                'lineitem_unblendedrate': 'max'
            }).reset_index()

            self.logger.debug(
                f"Grouped to {len(capacity_df)} resource-date combinations"
            )

            # Step 5: Calculate hours in month
            hours_in_month = self.calculate_hours_in_month(year, month)

            # Step 6: Apply capacity formula
            # Capacity = Cost / (Rate / Hours)
            # Handle division by zero gracefully
            capacity_df['rate_per_hour'] = (
                capacity_df['lineitem_unblendedrate'] / hours_in_month
            )

            # Only calculate capacity where rate > 0
            mask = capacity_df['lineitem_unblendedrate'] > 0
            capacity_df['capacity'] = 0.0  # Use float to avoid dtype warning

            capacity_df.loc[mask, 'capacity'] = (
                capacity_df.loc[mask, 'lineitem_unblendedcost'] /
                capacity_df.loc[mask, 'rate_per_hour']
            )

            # Round to nearest integer
            # First drop any NaN/inf values before converting to int
            capacity_df = capacity_df[capacity_df['capacity'].notna()]
            capacity_df = capacity_df[np.isfinite(capacity_df['capacity'])]
            capacity_df['capacity'] = np.round(capacity_df['capacity']).astype(int)

            # Step 7: Filter to positive capacities
            capacity_df = capacity_df[capacity_df['capacity'] > 0]

            if capacity_df.empty:
                self.logger.warning("No positive capacities calculated")
                return pd.DataFrame(columns=['resource_id', 'capacity', 'usage_start'])

            # Step 8: Rename columns to match expected output
            capacity_df = capacity_df.rename(columns={
                'lineitem_resourceid': 'resource_id',
                'usage_date': 'usage_start'
            })[['resource_id', 'capacity', 'usage_start']]

            # Log statistics
            total_capacity = capacity_df['capacity'].sum()
            avg_capacity = capacity_df['capacity'].mean()
            unique_volumes = capacity_df['resource_id'].nunique()

            self.logger.info(
                "✓ Disk capacities calculated",
                volumes=unique_volumes,
                rows=len(capacity_df),
                total_capacity_gb=f"{total_capacity:,.0f}",
                avg_capacity_gb=f"{avg_capacity:,.1f}"
            )

            return capacity_df

    def get_capacity_summary(self, capacity_df: pd.DataFrame) -> Dict:
        """
        Get a summary of calculated capacities.

        Args:
            capacity_df: DataFrame with calculated capacities

        Returns:
            Dictionary with summary statistics
        """
        if capacity_df.empty:
            return {"status": "empty"}

        summary = {
            "total_volumes": capacity_df['resource_id'].nunique(),
            "total_rows": len(capacity_df),
            "total_capacity_gb": int(capacity_df['capacity'].sum()),
            "avg_capacity_gb": float(capacity_df['capacity'].mean()),
            "min_capacity_gb": int(capacity_df['capacity'].min()),
            "max_capacity_gb": int(capacity_df['capacity'].max()),
            "median_capacity_gb": float(capacity_df['capacity'].median())
        }

        # Capacity distribution
        summary["capacity_distribution"] = {
            "< 100 GB": int((capacity_df['capacity'] < 100).sum()),
            "100-500 GB": int(((capacity_df['capacity'] >= 100) & (capacity_df['capacity'] < 500)).sum()),
            "500-1000 GB": int(((capacity_df['capacity'] >= 500) & (capacity_df['capacity'] < 1000)).sum()),
            "> 1000 GB": int((capacity_df['capacity'] >= 1000).sum())
        }

        self.logger.info("Capacity summary", **summary)
        return summary

    def validate_capacities(
        self,
        capacity_df: pd.DataFrame,
        min_capacity_gb: int = 1,
        max_capacity_gb: int = 100000
    ) -> bool:
        """
        Validate that calculated capacities are reasonable.

        Args:
            capacity_df: DataFrame with calculated capacities
            min_capacity_gb: Minimum expected capacity
            max_capacity_gb: Maximum expected capacity

        Returns:
            True if validation passes, raises exception otherwise
        """
        if capacity_df.empty:
            self.logger.warning("Capacity DataFrame is empty")
            return True  # Empty is valid (no volumes to process)

        # Check for required columns
        required_columns = ['resource_id', 'capacity', 'usage_start']
        missing_columns = [col for col in required_columns if col not in capacity_df.columns]

        if missing_columns:
            error_msg = f"Missing required columns: {missing_columns}"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Check for negative or zero capacities
        invalid_capacity_count = (capacity_df['capacity'] <= 0).sum()
        if invalid_capacity_count > 0:
            error_msg = f"Found {invalid_capacity_count} invalid (≤0) capacities"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        # Check for unreasonably large capacities
        too_large = (capacity_df['capacity'] > max_capacity_gb).sum()
        if too_large > 0:
            self.logger.warning(
                f"Found {too_large} capacities > {max_capacity_gb} GB (may be valid for large volumes)"
            )

        # Check for unreasonably small capacities
        too_small = (capacity_df['capacity'] < min_capacity_gb).sum()
        if too_small > 0:
            self.logger.warning(
                f"Found {too_small} capacities < {min_capacity_gb} GB (may be valid for small volumes)"
            )

        self.logger.debug("✓ Capacity validation passed")
        return True


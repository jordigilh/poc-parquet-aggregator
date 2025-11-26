"""PostgreSQL database writer for aggregated OCP data."""

import psycopg2
import psycopg2.extensions
from psycopg2.extras import execute_values
from typing import Dict, List, Optional
import pandas as pd

from .utils import get_logger, PerformanceTimer


class DatabaseWriter:
    """Write aggregated OCP data to PostgreSQL."""

    def __init__(self, config: Dict):
        """Initialize database writer.

        Args:
            config: Configuration dictionary with postgresql section
        """
        self.config = config
        self.logger = get_logger("db_writer")

        # PostgreSQL configuration
        pg_config = config['postgresql']
        self.host = pg_config['host']
        self.port = pg_config['port']
        self.database = pg_config['database']
        self.user = pg_config['user']
        self.password = pg_config['password']
        self.schema = pg_config['schema']

        self.connection = None
        self.logger.info(
            "Initialized database writer",
            host=self.host,
            database=self.database,
            schema=self.schema
        )

    def connect(self):
        """Establish database connection."""
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                database=self.database,
                user=self.user,
                password=self.password
            )
            self.logger.info("Database connection established")
        except Exception as e:
            self.logger.error("Failed to connect to database", error=str(e))
            raise

    def disconnect(self):
        """Close database connection.

        Note: Ensures any pending transaction is committed before closing.
        In psycopg2, close() without commit() will rollback!
        """
        if self.connection:
            # Commit any pending transaction before closing
            if self.connection.status == psycopg2.extensions.STATUS_IN_TRANSACTION:
                self.logger.info("Committing pending transaction before disconnect...")
                self.connection.commit()
            self.connection.close()
            self.logger.info("Database connection closed")

    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()

    def get_enabled_tag_keys(self) -> List[str]:
        """Get enabled tag keys from PostgreSQL.

        This replicates the CTE cte_pg_enabled_keys in Trino SQL.

        Returns:
            List of enabled tag keys
        """
        with PerformanceTimer("Fetch enabled tag keys", self.logger):
            query = f"""
                SELECT key
                FROM {self.schema}.reporting_ocpenabledtagkeys
                WHERE enabled = true
                ORDER BY key
            """

            try:
                with self.connection.cursor() as cursor:
                    cursor.execute(query)
                    keys = [row[0] for row in cursor.fetchall()]

                    # Always include 'vm_kubevirt_io_name' (from Trino SQL line 96)
                    keys = ['vm_kubevirt_io_name'] + keys

                    self.logger.info(
                        "Fetched enabled tag keys",
                        count=len(keys),
                        keys=keys[:5]  # Log first 5
                    )

                    return keys
            except Exception as e:
                self.logger.error("Failed to fetch enabled tag keys", error=str(e))
                raise

    def get_cost_category_namespaces(self) -> pd.DataFrame:
        """Get cost category namespace mappings.

        Returns:
            DataFrame with namespace and cost_category_id columns
        """
        with PerformanceTimer("Fetch cost category namespaces", self.logger):
            query = f"""
                SELECT namespace, cost_category_id
                FROM {self.schema}.reporting_ocp_cost_category_namespace
            """

            try:
                df = pd.read_sql(query, self.connection)
                self.logger.info(
                    "Fetched cost category namespaces",
                    count=len(df)
                )
                return df
            except Exception as e:
                self.logger.error("Failed to fetch cost category namespaces", error=str(e))
                # Non-critical, return empty DataFrame
                return pd.DataFrame()

    def get_node_roles(self) -> pd.DataFrame:
        """Get node roles from reporting_ocp_nodes table.

        Implements Trino SQL lines 491-498:
        SELECT max(node_role) AS node_role, node, resource_id
        FROM postgres.reporting_ocp_nodes
        GROUP BY node, resource_id

        Returns:
            DataFrame with node, resource_id, node_role columns
        """
        with PerformanceTimer("Fetch node roles", self.logger):
            query = f"""
                SELECT node, resource_id, MAX(node_role) as node_role
                FROM {self.schema}.reporting_ocp_nodes
                GROUP BY node, resource_id
            """

            try:
                df = pd.read_sql(query, self.connection)
                self.logger.info(
                    "Fetched node roles",
                    count=len(df),
                    roles=df['node_role'].value_counts().to_dict() if not df.empty else {}
                )
                return df
            except Exception as e:
                self.logger.error("Failed to fetch node roles", error=str(e))
                # Non-critical, return empty DataFrame
                return pd.DataFrame()

    def write_summary_data_bulk_copy(
        self,
        df: pd.DataFrame,
        truncate: bool = False
    ) -> int:
        """
        Write aggregated summary data using PostgreSQL COPY (10-50x faster).

        This uses the COPY command which is much faster than INSERT for bulk data.

        Args:
            df: DataFrame with aggregated data
            truncate: Whether to truncate table first (for testing)

        Returns:
            Number of rows inserted
        """
        import io

        table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        with PerformanceTimer(f"Bulk COPY {len(df)} rows to PostgreSQL", self.logger):
            try:
                # Optionally truncate
                if truncate:
                    self._truncate_table(table_name)

                # Prepare data for COPY (exclude uuid - PostgreSQL generates it)
                columns = [col for col in df.columns.tolist() if col != 'uuid']
                df_insert = df[columns].copy()

                # CRITICAL: Replace all NaN values with None for PostgreSQL
                import numpy as np
                # Convert object columns and replace NaN with None
                df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

                # Create CSV buffer in memory
                buffer = io.StringIO()
                df_insert.to_csv(
                    buffer,
                    index=False,
                    header=False,
                    sep='\t',
                    na_rep='\\N'  # PostgreSQL NULL representation
                )
                buffer.seek(0)

                # Use COPY command for bulk insert
                column_names = ', '.join(columns)
                copy_sql = f"""
                    COPY {table_name} ({column_names})
                    FROM STDIN
                    WITH (FORMAT CSV, DELIMITER E'\\t', NULL '\\N')
                """

                with self.connection.cursor() as cursor:
                    cursor.copy_expert(copy_sql, buffer)
                    self.connection.commit()

                rows_inserted = len(df_insert)
                self.logger.info(
                    "Successfully bulk copied data",
                    rows_inserted=rows_inserted,
                    method="COPY"
                )

                return rows_inserted

            except Exception as e:
                self.connection.rollback()
                self.logger.error(f"Bulk COPY failed: {e}")
                # Fallback to regular insert
                self.logger.warning("Falling back to batch INSERT")
                return self.write_summary_data(df, batch_size=1000, truncate=False)

    def write_summary_data(
        self,
        df: pd.DataFrame,
        batch_size: int = 1000,
        truncate: bool = False
    ) -> int:
        """Write aggregated summary data to PostgreSQL using batch INSERT.

        Args:
            df: DataFrame with aggregated data
            batch_size: Number of rows per batch insert
            truncate: Whether to truncate table first (for testing)

        Returns:
            Number of rows inserted
        """
        table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        with PerformanceTimer(f"Write {len(df)} rows to PostgreSQL", self.logger):
            try:
                # Optionally truncate
                if truncate:
                    self._truncate_table(table_name)

                # Prepare data for insert (exclude uuid - PostgreSQL generates it)
                columns = [col for col in df.columns.tolist() if col != 'uuid']
                df_insert = df[columns].copy()

                # CRITICAL: Replace all NaN values with None for PostgreSQL
                import numpy as np
                # Convert object columns and replace NaN with None
                df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

                # Build INSERT query
                column_names = ', '.join(columns)
                placeholders = ', '.join(['%s'] * len(columns))

                insert_query = f"""
                    INSERT INTO {table_name} ({column_names})
                    VALUES %s
                """

                # Convert DataFrame to list of tuples
                data = [tuple(row) for row in df_insert.values]

                # Batch insert
                total_inserted = 0
                with self.connection.cursor() as cursor:
                    for i in range(0, len(data), batch_size):
                        batch = data[i:i + batch_size]
                        execute_values(cursor, insert_query, batch, page_size=batch_size)
                        total_inserted += len(batch)

                        if (i // batch_size + 1) % 10 == 0:
                            self.logger.debug(
                                f"Inserted {total_inserted}/{len(data)} rows"
                            )

                self.connection.commit()

                self.logger.info(
                    "Successfully wrote summary data",
                    rows_inserted=total_inserted,
                    batches=len(data) // batch_size + 1
                )

                return total_inserted

            except Exception as e:
                self.connection.rollback()
                self.logger.error(
                    "Failed to write summary data",
                    error=str(e),
                    rows=len(df)
                )
                raise

    def write_ocp_aws_summary_data(
        self,
        df: pd.DataFrame,
        batch_size: int = 1000,
        truncate: bool = False
    ) -> int:
        """Write OCP-AWS aggregated summary data to PostgreSQL.

        Args:
            df: DataFrame with OCP-AWS aggregated data
            batch_size: Number of rows per batch insert
            truncate: Whether to truncate table first (for testing)

        Returns:
            Number of rows inserted
        """
        table_name = f"{self.schema}.reporting_ocpawscostlineitem_project_daily_summary_p"

        with PerformanceTimer(f"Write {len(df)} OCP-AWS rows to PostgreSQL", self.logger):
            try:
                if truncate:
                    self._truncate_table(table_name)

                # Prepare data (exclude uuid)
                columns = [col for col in df.columns.tolist() if col != 'uuid']
                df_insert = df[columns].copy()

                # Convert dict/JSON columns to JSON strings for JSONB columns
                import json
                json_columns = ['pod_labels', 'tags', 'aws_cost_category']
                for col in json_columns:
                    if col in df_insert.columns:
                        def to_json(x):
                            if pd.isna(x) or x is None:
                                return None
                            if isinstance(x, dict):
                                return json.dumps(x)
                            if isinstance(x, str):
                                # Try to parse as JSON first, if it fails, treat as empty JSON
                                try:
                                    json.loads(x)  # Validate it's valid JSON
                                    return x
                                except:
                                    # Not valid JSON (e.g., "label_app=value"), return empty JSON
                                    return '{}'
                            return '{}'
                        df_insert[col] = df_insert[col].apply(to_json)

                # Replace NaN with None for PostgreSQL
                import numpy as np
                df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

                # Build INSERT query
                column_names = ', '.join(columns)
                insert_query = f"INSERT INTO {table_name} ({column_names}) VALUES %s"

                # Convert to tuples
                data = [tuple(row) for row in df_insert.values]

                # Batch insert
                total_inserted = 0
                self.logger.info(f"Starting batch insert: {len(data)} rows in batches of {batch_size}")
                self.logger.info(f"Connection status before insert: {self.connection.status}")

                with self.connection.cursor() as cursor:
                    for i in range(0, len(data), batch_size):
                        batch = data[i:i + batch_size]
                        from psycopg2.extras import execute_values
                        execute_values(cursor, insert_query, batch, page_size=batch_size)
                        total_inserted += len(batch)
                        if (i + batch_size) % 10000 == 0:  # Log every 10K rows
                            self.logger.info(f"Progress: {total_inserted}/{len(data)} rows")

                self.logger.info(f"All rows sent to database: {total_inserted}")
                self.logger.info(f"Connection status before commit: {self.connection.status}")
                self.logger.info(f"About to commit transaction...")

                self.connection.commit()

                self.logger.info(f"✓ Commit successful")
                self.logger.info(f"Connection status after commit: {self.connection.status}")

                # Verify data was actually written
                with self.connection.cursor() as verify_cursor:
                    verify_cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                    actual_count = verify_cursor.fetchone()[0]
                    self.logger.info(f"Verification query: {actual_count} rows in table")
                    if actual_count != total_inserted:
                        self.logger.warning(f"MISMATCH: Inserted {total_inserted} but table has {actual_count}")

                self.logger.info(f"✓ Inserted {total_inserted} OCP-AWS rows")
                return total_inserted

            except Exception as e:
                self.connection.rollback()
                self.logger.error("Failed to write OCP-AWS data", error=str(e), rows=len(df))
                raise

    def _truncate_table(self, table_name: str):
        """Truncate a table (for testing).

        Args:
            table_name: Full table name (schema.table)
        """
        self.logger.warning(f"Truncating table: {table_name}")

        try:
            with self.connection.cursor() as cursor:
                cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE")
            self.connection.commit()
            self.logger.info(f"Truncated table: {table_name}")
        except Exception as e:
            self.connection.rollback()
            self.logger.error(f"Failed to truncate table: {table_name}", error=str(e))
            raise

    def validate_summary_data(
        self,
        provider_uuid: str,
        year: str,
        month: str
    ) -> Dict:
        """Validate summary data by querying aggregates.

        Args:
            provider_uuid: Provider UUID
            year: Year (e.g., '2025')
            month: Month (e.g., '11' or '01' - will be zero-padded)

        Returns:
            Dictionary with validation metrics
        """
        table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        # Zero-pad month (Trino SQL line 665: lpad(lids.month, 2, '0'))
        month_padded = str(month).zfill(2)

        with PerformanceTimer("Validate summary data", self.logger):
            query = f"""
                SELECT
                    COUNT(*) as row_count,
                    COUNT(DISTINCT namespace) as namespace_count,
                    COUNT(DISTINCT node) as node_count,
                    COUNT(DISTINCT usage_start) as day_count,
                    SUM(pod_usage_cpu_core_hours) as total_cpu_hours,
                    SUM(pod_usage_memory_gigabyte_hours) as total_memory_gb_hours,
                    SUM(pod_request_cpu_core_hours) as total_request_cpu_hours,
                    SUM(pod_request_memory_gigabyte_hours) as total_request_memory_gb_hours
                FROM {table_name}
                WHERE source_uuid::text = %s
                  AND EXTRACT(YEAR FROM usage_start) = %s
                  AND EXTRACT(MONTH FROM usage_start) = %s
            """

            try:
                with self.connection.cursor() as cursor:
                    cursor.execute(query, (provider_uuid, year, month_padded))
                    row = cursor.fetchone()

                    result = {
                        'row_count': row[0],
                        'namespace_count': row[1],
                        'node_count': row[2],
                        'day_count': row[3],
                        'total_cpu_hours': float(row[4]) if row[4] else 0.0,
                        'total_memory_gb_hours': float(row[5]) if row[5] else 0.0,
                        'total_request_cpu_hours': float(row[6]) if row[6] else 0.0,
                        'total_request_memory_gb_hours': float(row[7]) if row[7] else 0.0,
                    }

                    self.logger.info(
                        "Summary data validation",
                        **result
                    )

                    return result
            except Exception as e:
                self.logger.error("Failed to validate summary data", error=str(e))
                raise

    def test_connectivity(self) -> bool:
        """Test database connectivity.

        Returns:
            True if connection successful
        """
        try:
            with self.connection.cursor() as cursor:
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                if result and result[0] == 1:
                    self.logger.info("Database connectivity test: SUCCESS")
                    return True
        except Exception as e:
            self.logger.error("Database connectivity test: FAILED", error=str(e))
            return False
        return False

    def create_streaming_writer(self, table_type: str = "ocp_aws") -> 'StreamingDBWriter':
        """Create a streaming writer for incremental chunk writes.

        Args:
            table_type: Type of table ("ocp_aws" or "ocp")

        Returns:
            StreamingDBWriter context manager
        """
        if table_type == "ocp_aws":
            table_name = f"{self.schema}.reporting_ocpawscostlineitem_project_daily_summary_p"
        else:
            table_name = f"{self.schema}.reporting_ocpusagelineitem_daily_summary"

        return StreamingDBWriter(self, table_name)


class StreamingDBWriter:
    """
    Context manager for streaming (incremental) database writes.

    Writes each chunk immediately to the database within a single transaction.
    Memory is bounded because chunks are written and freed, not collected.

    Usage:
        with db_writer.create_streaming_writer("ocp_aws") as streaming:
            for chunk in chunks:
                processed = process(chunk)
                streaming.write_chunk(processed)
            # Auto-commits on exit, rolls back on exception
    """

    def __init__(self, db_writer: DatabaseWriter, table_name: str):
        self.db_writer = db_writer
        self.table_name = table_name
        self.logger = db_writer.logger
        self.total_rows = 0
        self.chunk_count = 0
        self._cursor = None
        self._columns = None
        self._insert_query = None

    def __enter__(self):
        """Start transaction and prepare for writes."""
        self.logger.info(f"Starting streaming write to {self.table_name}")

        # Truncate table first (start fresh)
        with self.db_writer.connection.cursor() as cursor:
            cursor.execute(f"TRUNCATE TABLE {self.table_name} CASCADE")
        # Don't commit yet - part of the same transaction

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Commit or rollback based on success."""
        if exc_type is not None:
            # Exception occurred - rollback
            self.db_writer.connection.rollback()
            self.logger.error(
                f"Streaming write failed, rolled back",
                error=str(exc_val),
                chunks_written=self.chunk_count,
                rows_written=self.total_rows
            )
            return False  # Re-raise exception
        else:
            # Success - commit
            self.db_writer.connection.commit()
            self.logger.info(
                f"✓ Streaming write complete",
                chunks=self.chunk_count,
                total_rows=self.total_rows
            )
            return True

    def write_chunk(self, df: pd.DataFrame, batch_size: int = 1000) -> int:
        """
        Write a single chunk to the database.

        Args:
            df: DataFrame chunk to write
            batch_size: Rows per batch insert

        Returns:
            Number of rows written
        """
        import json
        import numpy as np

        if df is None or df.empty:
            return 0

        self.chunk_count += 1
        chunk_rows = len(df)

        # Prepare columns (first time only)
        if self._columns is None:
            self._columns = [col for col in df.columns.tolist() if col != 'uuid']
            column_names = ', '.join(self._columns)
            self._insert_query = f"INSERT INTO {self.table_name} ({column_names}) VALUES %s"

        # Prepare data
        df_insert = df[self._columns].copy()

        # Convert JSON columns
        json_columns = ['pod_labels', 'tags', 'aws_cost_category']
        for col in json_columns:
            if col in df_insert.columns:
                def to_json(x):
                    if pd.isna(x) or x is None:
                        return None
                    if isinstance(x, dict):
                        return json.dumps(x)
                    if isinstance(x, str):
                        try:
                            json.loads(x)
                            return x
                        except:
                            return '{}'
                    return '{}'
                df_insert[col] = df_insert[col].apply(to_json)

        # Replace NaN with None
        df_insert = df_insert.astype(object).where(pd.notna(df_insert), None)

        # Convert to tuples
        data = [tuple(row) for row in df_insert.values]

        # Write in batches (within the same transaction)
        with self.db_writer.connection.cursor() as cursor:
            for i in range(0, len(data), batch_size):
                batch = data[i:i + batch_size]
                execute_values(cursor, self._insert_query, batch, page_size=batch_size)

        self.total_rows += chunk_rows

        self.logger.debug(
            f"Chunk {self.chunk_count} written",
            rows=chunk_rows,
            total=self.total_rows
        )

        # Free memory immediately
        del df_insert, data

        return chunk_rows


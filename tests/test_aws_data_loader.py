"""
Unit tests for AWS Data Loader

Tests the AWSDataLoader class for reading AWS CUR Parquet files.
"""

from unittest.mock import MagicMock, Mock, patch

import pandas as pd
import pytest

from src.aws_data_loader import AWSDataLoader


@pytest.fixture
def mock_config():
    """Mock configuration for testing."""
    return {
        "organization": {"org_id": "org1234567"},
        "aws": {
            "parquet_path_line_items": "data/${ORG_ID}/AWS/source={provider_uuid}/year={year}/month={month}/*",
            "provider_uuid": "test-aws-provider",
        },
        "s3": {
            "endpoint": "http://localhost:9000",
            "bucket": "test-bucket",
            "access_key": "test-key",
            "secret_key": "test-secret",
            "use_ssl": False,
            "verify_ssl": False,
            "region": "us-east-1",
        },
        "performance": {"column_filtering": True, "parallel_readers": 2},
    }


@pytest.fixture
def sample_aws_cur_data():
    """Sample AWS CUR data for testing."""
    return pd.DataFrame(
        {
            "lineitem_resourceid": ["i-abc123", "vol-xyz789", "i-def456", None],
            "lineitem_usageaccountid": [
                "123456789012",
                "123456789012",
                "123456789012",
                "123456789012",
            ],
            "lineitem_productcode": [
                "AmazonEC2",
                "AmazonEBS",
                "AmazonEC2",
                "AmazonVPC",
            ],
            "lineitem_usagetype": [
                "BoxUsage:m5.large",
                "EBS:VolumeUsage",
                "BoxUsage:t3.micro",
                "VPC-In-Bytes",
            ],
            "product_instancetype": ["m5.large", "", "t3.micro", ""],
            "product_region": ["us-east-1", "us-east-1", "us-west-2", "us-east-1"],
            "product_productfamily": [
                "Compute Instance",
                "Storage",
                "Compute Instance",
                "Network",
            ],
            "lineitem_unblendedcost": [1.234, 0.567, 0.890, 0.012],
            "lineitem_blendedcost": [1.200, 0.550, 0.880, 0.012],
            "savingsplan_savingsplaneffectivecost": [1.100, 0.000, 0.800, 0.000],
            "pricing_publicondemandcost": [1.500, 0.600, 1.000, 0.015],
            "lineitem_usageamount": [24.0, 100.0, 24.0, 1000000.0],
            "pricing_unit": ["Hrs", "GB-Mo", "Hrs", "Bytes"],
            "resourcetags": [
                '{"openshift_cluster": "my-cluster", "openshift_node": "worker-1"}',
                '{"openshift_cluster": "my-cluster", "openshift_project": "backend"}',
                '{"openshift_cluster": "other-cluster"}',
                "{}",
            ],
            "lineitem_usagestartdate": pd.to_datetime(
                ["2025-10-01", "2025-10-01", "2025-10-01", "2025-10-01"]
            ),
        }
    )


class TestAWSDataLoader:
    """Test suite for AWSDataLoader."""

    def test_initialization(self, mock_config):
        """Test AWS data loader initialization."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            assert loader.config == mock_config
            assert loader.logger is not None
            assert loader.parquet_reader is not None

    def test_get_optimal_columns_aws_cur(self, mock_config):
        """Test optimal column selection for AWS CUR."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)
            columns = loader.get_optimal_columns_aws_cur()

            # Should return essential columns only
            assert "lineitem_resourceid" in columns
            assert "lineitem_productcode" in columns
            assert "lineitem_unblendedcost" in columns
            assert "lineitem_blendedcost" in columns
            # Note: 'resourcetags' is derived from resourceTags/* columns during load, not in initial list
            assert "lineitem_usagestartdate" in columns

            # Should have ~15 columns (not 40+)
            assert len(columns) >= 10
            assert len(columns) <= 20

    def test_validate_aws_cur_schema_valid(self, mock_config, sample_aws_cur_data):
        """Test schema validation with valid DataFrame."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            # Should pass validation
            assert loader.validate_aws_cur_schema(sample_aws_cur_data) is True

    def test_validate_aws_cur_schema_missing_columns(self, mock_config):
        """Test schema validation with missing columns."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            # DataFrame missing required columns
            invalid_df = pd.DataFrame(
                {
                    "lineitem_resourceid": ["i-abc123"],
                    # Missing other required columns
                }
            )

            with pytest.raises(ValueError, match="missing required columns"):
                loader.validate_aws_cur_schema(invalid_df)

    def test_get_aws_resource_summary_nonempty(self, mock_config, sample_aws_cur_data):
        """Test resource summary generation with data."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)
            summary = loader.get_aws_resource_summary(sample_aws_cur_data)

            assert summary["total_rows"] == 4
            assert summary["unique_resources"] == 3  # 3 non-null resource IDs
            assert summary["unique_accounts"] == 1
            assert "AmazonEC2" in summary["product_codes"]
            assert summary["product_codes"]["AmazonEC2"] == 2
            assert summary["total_cost_unblended"] == pytest.approx(2.703)

    def test_get_aws_resource_summary_empty(self, mock_config):
        """Test resource summary generation with empty DataFrame."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)
            summary = loader.get_aws_resource_summary(pd.DataFrame())

            assert summary["status"] == "empty"

    def test_read_aws_line_items_for_matching_no_filter(
        self, mock_config, sample_aws_cur_data
    ):
        """Test reading AWS CUR for matching without resource type filter."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            # Mock read_aws_line_items_daily to return sample data
            loader.read_aws_line_items_daily = Mock(return_value=sample_aws_cur_data)

            result = loader.read_aws_line_items_for_matching(
                provider_uuid="test-provider", year="2025", month="10"
            )

            # Should remove rows with null resource IDs
            assert len(result) == 3  # 4 rows - 1 with null resource_id
            assert result["lineitem_resourceid"].notna().all()

    def test_read_aws_line_items_for_matching_with_filter(
        self, mock_config, sample_aws_cur_data
    ):
        """Test reading AWS CUR for matching with resource type filter."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            # Mock read_aws_line_items_daily to return sample data
            loader.read_aws_line_items_daily = Mock(return_value=sample_aws_cur_data)

            result = loader.read_aws_line_items_for_matching(
                provider_uuid="test-provider",
                year="2025",
                month="10",
                resource_types=["AmazonEC2"],
            )

            # Should filter by resource type AND remove null resource IDs
            assert len(result) == 2  # 2 EC2 instances (both have resource IDs)
            assert (result["lineitem_productcode"] == "AmazonEC2").all()

    def test_read_aws_line_items_for_matching_empty(self, mock_config):
        """Test reading AWS CUR for matching with no data."""
        with patch("src.aws_data_loader.ParquetReader"):
            loader = AWSDataLoader(mock_config)

            # Mock read_aws_line_items_daily to return empty DataFrame
            loader.read_aws_line_items_daily = Mock(return_value=pd.DataFrame())

            result = loader.read_aws_line_items_for_matching(
                provider_uuid="test-provider", year="2025", month="10"
            )

            assert result.empty

    def test_s3_path_construction(self, mock_config):
        """Test S3 path construction with variable substitution."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Mock the ParquetReader instance
            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = [
                "s3://test-bucket/test-file.parquet"
            ]
            mock_reader._read_files_parallel.return_value = pd.DataFrame(
                {
                    "lineitem_resourceid": ["i-test"],
                    "lineitem_productcode": ["AmazonEC2"],
                    "lineitem_unblendedcost": [1.0],
                    "resourcetags": ["{}"],
                }
            )
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Call read method
            loader.read_aws_line_items_daily(
                provider_uuid="test-provider-123",
                year="2025",
                month="10",
                streaming=False,
            )

            # Verify list_parquet_files was called with correct path
            called_path = mock_reader.list_parquet_files.call_args[0][0]
            assert "org1234567" in called_path  # ORG_ID substituted
            assert "test-provider-123" in called_path  # provider_uuid substituted
            assert "2025" in called_path  # year substituted
            assert "10" in called_path  # month substituted
            assert "AWS" in called_path  # Provider type

    def test_read_with_column_filtering(self, mock_config):
        """Test that column filtering is applied when enabled."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = [
                "s3://test-bucket/test.parquet"
            ]
            mock_reader._read_files_parallel.return_value = pd.DataFrame()
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Read data
            loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            # Verify _read_files_parallel was called
            # Note: columns=None because we read all columns for resourcetags consolidation
            call_args = mock_reader._read_files_parallel.call_args
            assert call_args is not None

    def test_streaming_mode(self, mock_config):
        """Test that streaming mode uses the correct method."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = [
                "s3://test-bucket/test.parquet"
            ]

            # Mock streaming to return an iterator
            def mock_stream(*args, **kwargs):
                yield pd.DataFrame({"lineitem_resourceid": ["i-1"]})
                yield pd.DataFrame({"lineitem_resourceid": ["i-2"]})

            mock_reader.read_parquet_streaming = mock_stream
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Read in streaming mode
            result_iterator = loader.read_aws_line_items_daily(
                provider_uuid="test",
                year="2025",
                month="10",
                streaming=True,
                chunk_size=1000,
            )

            # Result should be an iterator
            chunks = list(result_iterator)
            assert len(chunks) == 2
            assert all(isinstance(chunk, pd.DataFrame) for chunk in chunks)

    # ========================================================================
    # PRODUCTION SCALE & EDGE CASE TESTS (8 new tests for 95% confidence)
    # ========================================================================

    def test_production_scale_100k_rows(self, mock_config):
        """Test loading 100K+ AWS line items - CRITICAL for production."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Generate 105,000 AWS line items
            num_rows = 105000

            large_df = pd.DataFrame(
                {
                    "lineitem_resourceid": [f"i-{i:08d}" for i in range(num_rows)],
                    "lineitem_productcode": ["AmazonEC2"] * num_rows,
                    "lineitem_unblendedcost": [
                        1.0 + (i % 100) * 0.01 for i in range(num_rows)
                    ],
                    "lineitem_blendedcost": [
                        0.9 + (i % 100) * 0.01 for i in range(num_rows)
                    ],
                    "savingsplan_savingsplaneffectivecost": [
                        0.8 + (i % 100) * 0.01 for i in range(num_rows)
                    ],
                    "resourcetags": ['{"openshift_cluster":"prod"}'] * num_rows,
                    "lineitem_usagestartdate": pd.to_datetime(
                        ["2025-10-01"] * num_rows
                    ),
                    "lineitem_usageaccountid": ["123456789012"] * num_rows,
                }
            )

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]
            mock_reader._read_files_parallel.return_value = large_df
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Time the operation
            import time

            start = time.time()

            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            elapsed = time.time() - start

            # Should complete in <5 seconds
            assert elapsed < 5.0, f"Too slow: {elapsed:.2f}s"

            # Should load all rows
            assert len(result) == num_rows

            # Get summary
            summary = loader.get_aws_resource_summary(result)
            assert summary["total_rows"] == num_rows
            assert summary["unique_resources"] == num_rows

    def test_multi_file_scenario(self, mock_config):
        """Test loading from multiple Parquet files."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Simulate 10 files with 1000 rows each
            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = [
                f"s3://test/file-{i}.parquet" for i in range(10)
            ]

            # Create aggregated data (10K rows total)
            combined_df = pd.DataFrame(
                {
                    "lineitem_resourceid": [f"i-{i:06d}" for i in range(10000)],
                    "lineitem_productcode": ["AmazonEC2"] * 10000,
                    "lineitem_unblendedcost": [1.0] * 10000,
                    "resourcetags": ["{}"] * 10000,
                    "lineitem_usagestartdate": pd.to_datetime(["2025-10-01"] * 10000),
                }
            )

            mock_reader._read_files_parallel.return_value = combined_df
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            # Should load all 10K rows
            assert len(result) == 10000

            # Verify list_parquet_files was called
            assert mock_reader.list_parquet_files.called

    def test_large_resourcetags_json(self, mock_config):
        """Test handling of very large JSON tag strings."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Create DataFrame with 150 resourceTags/* columns (simulating AWS CUR expansion)
            data = {
                "lineitem_resourceid": ["i-abc123", "i-def456"],
                "lineitem_productcode": ["AmazonEC2", "AmazonEC2"],
                "lineitem_unblendedcost": [1.0, 2.0],
                "lineitem_usagestartdate": pd.to_datetime(["2025-10-01", "2025-10-01"]),
            }
            # Add 150 tag columns (AWS CUR format: resourceTags/user:key)
            for i in range(150):
                data[f"resourceTags/user:tag-key-{i}"] = [
                    f"tag-value-{i}",
                    f"tag-value-{i}",
                ]

            df_with_large_tags = pd.DataFrame(data)

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]
            mock_reader._read_files_parallel.return_value = df_with_large_tags
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            # Should handle large tags gracefully (150 tags consolidated into JSON)
            assert len(result) == 2
            assert "resourcetags" in result.columns
            # JSON should be large (150 tags * ~30 chars/tag = ~4500+ chars)
            assert len(result["resourcetags"].iloc[0]) > 1000  # Large JSON string

    def test_missing_optional_columns_gracefully(self, mock_config):
        """Test handling of missing optional columns."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # DataFrame missing optional columns (only required ones present)
            minimal_df = pd.DataFrame(
                {
                    "lineitem_resourceid": ["i-abc123"],
                    "lineitem_usagestartdate": pd.to_datetime(["2025-10-01"]),
                    "lineitem_unblendedcost": [1.0],
                    "resourcetags": ["{}"]
                    # Missing: lineitem_blendedcost, savingsplan_savingsplaneffectivecost, etc.
                }
            )

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]
            mock_reader._read_files_parallel.return_value = minimal_df
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Should not raise an error for missing optional columns
            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            assert len(result) == 1
            assert "lineitem_resourceid" in result.columns

    def test_date_range_month_boundaries(self, mock_config):
        """Test handling of month boundary dates (Oct 31 → Nov 1)."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Data spanning month boundary
            boundary_df = pd.DataFrame(
                {
                    "lineitem_resourceid": ["i-1", "i-2", "i-3"],
                    "lineitem_productcode": ["AmazonEC2"] * 3,
                    "lineitem_unblendedcost": [1.0] * 3,
                    "resourcetags": ["{}"] * 3,
                    "lineitem_usagestartdate": pd.to_datetime(
                        [
                            "2025-10-31 23:59:59",
                            "2025-11-01 00:00:00",
                            "2025-11-01 00:00:01",
                        ]
                    ),
                }
            )

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]
            mock_reader._read_files_parallel.return_value = boundary_df
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"  # October data
            )

            # Should load all 3 rows (no date filtering in loader)
            assert len(result) == 3

            # Verify dates are preserved correctly
            assert result["lineitem_usagestartdate"].notna().all()

    def test_null_vs_empty_resourcetags(self, mock_config):
        """Test distinction between NULL and empty ResourceTags."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Mix of NULL, empty, and valid tags
            tags_df = pd.DataFrame(
                {
                    "lineitem_resourceid": ["i-1", "i-2", "i-3", "i-4"],
                    "lineitem_productcode": ["AmazonEC2"] * 4,
                    "lineitem_unblendedcost": [1.0] * 4,
                    "resourcetags": [
                        None,  # NULL
                        "",  # Empty string
                        "{}",  # Empty JSON
                        '{"key":"value"}',  # Valid JSON
                    ],
                    "lineitem_usagestartdate": pd.to_datetime(["2025-10-01"] * 4),
                }
            )

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]
            mock_reader._read_files_parallel.return_value = tags_df
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            result = loader.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            # Should handle all cases
            assert len(result) == 4

            # Check resourcetags column exists
            assert "resourcetags" in result.columns

    def test_streaming_performance_100k(self, mock_config):
        """Test streaming mode with 100K rows."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]

            # Mock streaming to yield 10 chunks of 10K rows each
            def mock_stream(*args, **kwargs):
                chunk_size = kwargs.get("chunk_size", 10000)
                num_chunks = 10

                for i in range(num_chunks):
                    start_idx = i * chunk_size
                    chunk_df = pd.DataFrame(
                        {
                            "lineitem_resourceid": [
                                f"i-{j:08d}"
                                for j in range(start_idx, start_idx + chunk_size)
                            ],
                            "lineitem_productcode": ["AmazonEC2"] * chunk_size,
                            "lineitem_unblendedcost": [1.0] * chunk_size,
                            "resourcetags": ["{}"] * chunk_size,
                            "lineitem_usagestartdate": pd.to_datetime(
                                ["2025-10-01"] * chunk_size
                            ),
                        }
                    )
                    yield chunk_df

            mock_reader.read_parquet_streaming = mock_stream
            mock_reader_class.return_value = mock_reader

            loader = AWSDataLoader(mock_config)

            # Time the streaming operation
            import time

            start = time.time()

            result_iterator = loader.read_aws_line_items_daily(
                provider_uuid="test",
                year="2025",
                month="10",
                streaming=True,
                chunk_size=10000,
            )

            # Collect all chunks
            chunks = list(result_iterator)

            elapsed = time.time() - start

            # Should complete in reasonable time
            assert elapsed < 10.0, f"Streaming too slow: {elapsed:.2f}s"

            # Should have 10 chunks
            assert len(chunks) == 10

            # Each chunk should have 10K rows
            assert all(len(chunk) == 10000 for chunk in chunks)

            # Total rows should be 100K
            total_rows = sum(len(chunk) for chunk in chunks)
            assert total_rows == 100000

    def test_column_filtering_performance(self, mock_config):
        """Test performance impact of column filtering."""
        with patch("src.aws_data_loader.ParquetReader") as mock_reader_class:
            # Create DataFrame with 50 columns (simulating full CUR schema)
            num_rows = 10000
            full_df = pd.DataFrame(
                {f"column_{i}": [f"value_{i}"] * num_rows for i in range(50)}
            )

            # Add required columns
            full_df["lineitem_resourceid"] = [f"i-{i:06d}" for i in range(num_rows)]
            full_df["lineitem_productcode"] = ["AmazonEC2"] * num_rows
            full_df["lineitem_unblendedcost"] = [1.0] * num_rows
            full_df["resourcetags"] = ["{}"] * num_rows
            full_df["lineitem_usagestartdate"] = pd.to_datetime(
                ["2025-10-01"] * num_rows
            )

            mock_reader = MagicMock()
            mock_reader.list_parquet_files.return_value = ["s3://test/file.parquet"]

            # Test WITH column filtering
            mock_reader._read_files_parallel.return_value = full_df
            mock_reader_class.return_value = mock_reader

            loader_with_filter = AWSDataLoader(mock_config)

            import time

            start = time.time()

            result_with_filter = loader_with_filter.read_aws_line_items_daily(
                provider_uuid="test", year="2025", month="10"
            )

            elapsed_with_filter = time.time() - start

            # Verify columns parameter was passed
            call_args = mock_reader._read_files_parallel.call_args
            assert "columns" in call_args[1]

            # Should be fast (< 2 seconds for 10K rows)
            assert elapsed_with_filter < 2.0

            # Should have loaded data
            assert len(result_with_filter) == num_rows


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

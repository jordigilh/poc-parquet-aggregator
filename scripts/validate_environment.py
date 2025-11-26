#!/usr/bin/env python3
"""
Environment Validation Script

Validates that all dependencies are installed and importable.
Run this after setting up your environment to ensure everything works.

Usage:
    python3 scripts/validate_environment.py
"""

import sys
from typing import List, Tuple

def test_import(module_name: str, package_name: str = None) -> Tuple[bool, str]:
    """
    Test if a module can be imported.
    
    Args:
        module_name: Name of the module to import
        package_name: Optional package name if different from module
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    package = package_name or module_name
    try:
        __import__(module_name)
        return True, f"✅ {package}"
    except ImportError as e:
        return False, f"❌ {package} - {str(e)}"
    except Exception as e:
        return False, f"❌ {package} - Unexpected error: {str(e)}"

def main():
    """Run all validation tests."""
    print("=" * 80)
    print("=== POC Environment Validation ===")
    print("=" * 80)
    print()
    
    # Core dependencies
    print("📦 Core Dependencies:")
    core_tests = [
        ("pyarrow", "pyarrow"),
        ("s3fs", "s3fs"),
        ("psycopg2", "psycopg2-binary"),
        ("pandas", "pandas"),
        ("numpy", "numpy"),
    ]
    
    core_results = [test_import(mod, pkg) for mod, pkg in core_tests]
    for success, message in core_results:
        print(f"  {message}")
    print()
    
    # Database/Query engines
    print("🗄️  Database Connectivity:")
    db_tests = [
        ("psycopg2", "psycopg2-binary (PostgreSQL)"),
        ("trino", "trino (Trino validation)"),
    ]
    
    db_results = [test_import(mod, pkg) for mod, pkg in db_tests]
    for success, message in db_results:
        print(f"  {message}")
    print()
    
    # Configuration
    print("⚙️  Configuration:")
    config_tests = [
        ("yaml", "PyYAML"),
        ("dotenv", "python-dotenv"),
        ("dateutil", "python-dateutil"),
    ]
    
    config_results = [test_import(mod, pkg) for mod, pkg in config_tests]
    for success, message in config_results:
        print(f"  {message}")
    print()
    
    # Testing
    print("🧪 Testing Frameworks:")
    test_tests = [
        ("pytest", "pytest"),
        ("pytest_cov", "pytest-cov"),
        ("pytest_mock", "pytest-mock"),
    ]
    
    test_results = [test_import(mod, pkg) for mod, pkg in test_tests]
    for success, message in test_results:
        print(f"  {message}")
    print()
    
    # Monitoring
    print("📊 Monitoring/Profiling:")
    monitor_tests = [
        ("structlog", "structlog"),
        ("psutil", "psutil"),
        ("memory_profiler", "memory-profiler"),
    ]
    
    monitor_results = [test_import(mod, pkg) for mod, pkg in monitor_tests]
    for success, message in monitor_results:
        print(f"  {message}")
    print()
    
    # POC modules
    print("🔧 POC Modules:")
    poc_tests = [
        ("src.config_loader", "config_loader"),
        ("src.utils", "utils"),
        ("src.parquet_reader", "parquet_reader"),
        ("src.aggregator_pod", "aggregator_pod"),
        ("src.aggregator_storage", "aggregator_storage"),
        ("src.db_writer", "db_writer"),
    ]
    
    poc_results = [test_import(mod, pkg) for mod, pkg in poc_tests]
    for success, message in poc_results:
        print(f"  {message}")
    print()
    
    # Collect all results
    all_results = core_results + db_results + config_results + test_results + monitor_results + poc_results
    total = len(all_results)
    passed = sum(1 for success, _ in all_results if success)
    failed = total - passed
    
    # Summary
    print("=" * 80)
    print("=== Summary ===")
    print("=" * 80)
    print(f"Total tests: {total}")
    print(f"✅ Passed: {passed}")
    print(f"❌ Failed: {failed}")
    print()
    
    if failed == 0:
        print("🎉 SUCCESS! All dependencies are installed and working.")
        print()
        print("Next steps:")
        print("  1. Configure environment variables (see env.example)")
        print("  2. Start MinIO and PostgreSQL services")
        print("  3. Run POC: python3 -m src.main")
        print("  4. Run tests: pytest")
        print()
        return 0
    else:
        print("⚠️  FAILED! Some dependencies are missing or broken.")
        print()
        print("To fix:")
        print("  pip install -r requirements.txt")
        print()
        return 1

if __name__ == "__main__":
    sys.exit(main())


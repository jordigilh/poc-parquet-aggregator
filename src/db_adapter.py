"""
Database Adapter for Koku Integration

This module provides database configuration using koku's Django settings
or environment variables for standalone testing.

For standalone POC testing, set environment variables:
    DATABASE_HOST, DATABASE_PORT, DATABASE_NAME, DATABASE_USER, DATABASE_PASSWORD

For koku integration, these come from Django settings.DATABASES.
"""

import os
from typing import Dict

from .utils import get_logger

logger = get_logger("db_adapter")


def get_db_config() -> Dict[str, str]:
    """
    Get database configuration from koku Django settings or environment variables.
    
    Priority:
    1. Django settings (when running in koku)
    2. Environment variables (standalone testing)
    
    Returns:
        Dictionary with host, port, database, user, password, schema
    """
    try:
        from django.conf import settings
        db_settings = settings.DATABASES['default']
        config = {
            'host': db_settings['HOST'],
            'port': str(db_settings['PORT']),
            'database': db_settings['NAME'],
            'user': db_settings['USER'],
            'password': db_settings['PASSWORD'],
            'schema': os.getenv('ORG_ID', 'org1234567'),
        }
        logger.debug("Using Django database settings", host=config['host'])
        return config
    except Exception as e:
        logger.debug("Django settings not available, using environment variables", reason=str(e))
        # Fallback to environment variables for standalone testing
        config = {
            'host': os.getenv('DATABASE_HOST', os.getenv('POSTGRES_HOST', 'localhost')),
            'port': os.getenv('DATABASE_PORT', os.getenv('POSTGRES_PORT', '5432')),
            'database': os.getenv('DATABASE_NAME', os.getenv('POSTGRES_DB', 'koku')),
            'user': os.getenv('DATABASE_USER', os.getenv('POSTGRES_USER', 'koku')),
            'password': os.getenv('DATABASE_PASSWORD', os.getenv('POSTGRES_PASSWORD', '')),
            'schema': os.getenv('ORG_ID', 'org1234567'),
        }
        logger.debug("Using environment database settings", host=config['host'])
        return config


def get_db_connection():
    """
    Get a psycopg2 database connection using koku's configuration.
    
    Returns:
        psycopg2 connection object
    """
    import psycopg2
    
    config = get_db_config()
    
    conn = psycopg2.connect(
        host=config['host'],
        port=config['port'],
        database=config['database'],
        user=config['user'],
        password=config['password'],
    )
    
    logger.debug("Database connection established", host=config['host'], database=config['database'])
    return conn


def check_db_connectivity() -> bool:
    """
    Check if database is accessible.
    
    Returns:
        True if connection successful, False otherwise
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            cursor.execute("SELECT 1")
        conn.close()
        logger.info("Database connectivity check passed")
        return True
    except Exception as e:
        logger.error("Database connectivity check failed", error=str(e))
        return False


def get_schema_name() -> str:
    """
    Get the database schema name (org ID).
    
    Returns:
        Schema name string
    """
    try:
        # Try to get from environment first
        schema = os.getenv('ORG_ID')
        if schema:
            return schema
        
        # Try Django settings
        from django.conf import settings
        return getattr(settings, 'SCHEMA_NAME', 'org1234567')
    except Exception:
        return os.getenv('ORG_ID', 'org1234567')


def verify_table_exists(table_name: str) -> bool:
    """
    Verify that a database table exists.
    
    Args:
        table_name: Full table name including schema (e.g., 'org1234567.reporting_ocpusagelineitem_daily_summary')
        
    Returns:
        True if table exists, False otherwise
    """
    try:
        conn = get_db_connection()
        
        # Parse schema and table
        if '.' in table_name:
            schema, table = table_name.split('.', 1)
        else:
            schema = get_schema_name()
            table = table_name
        
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_schema = %s 
                    AND table_name = %s
                )
            """, (schema, table))
            exists = cursor.fetchone()[0]
        
        conn.close()
        logger.debug("Table existence check", table=table_name, exists=exists)
        return exists
    except Exception as e:
        logger.error("Table existence check failed", table=table_name, error=str(e))
        return False


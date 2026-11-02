"""Database schema migrations (no Alembic - manual migrations on startup)."""

import logging

from sqlalchemy import text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def run_migrations(session: Session, database_url: str) -> None:
    """
    Run all pending schema migrations.
    
    Called once on startup before any data operations.
    Idempotent - safe to run multiple times.
    """
    is_postgres = database_url.startswith("postgresql")
    
    if is_postgres:
        _migrate_postgres_encrypted_columns(session)
    else:
        # SQLite doesn't need migration - TEXT columns already wide enough
        logger.info("SQLite database - no column widening needed")


def _migrate_postgres_encrypted_columns(session: Session) -> None:
    """
    Widen columns that store encrypted values from VARCHAR to TEXT.
    
    Encrypted values are longer than plaintext (base64 overhead + "enc:" prefix).
    This migration is idempotent - safe to run multiple times.
    """
    migrations = [
        # CallRecord.caller_phone: VARCHAR(32) -> TEXT
        ("calls", "caller_phone"),
        
        # VoicemailMessage: caller_name, caller_phone
        ("voicemail_messages", "caller_name"),
        ("voicemail_messages", "caller_phone"),
        
        # DemoRequest: caller_name, business_name, caller_phone, email
        ("demo_requests", "caller_name"),
        ("demo_requests", "business_name"),
        ("demo_requests", "caller_phone"),
        ("demo_requests", "email"),
    ]
    
    for table, column in migrations:
        try:
            # Check if column exists and is not already TEXT
            result = session.execute(text(f"""
                SELECT data_type 
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = '{column}'
            """))
            row = result.fetchone()
            
            if row is None:
                # Column doesn't exist yet (fresh database) - skip
                logger.debug(f"Column {table}.{column} doesn't exist - will be created as TEXT")
                continue
            
            data_type = row[0]
            if data_type.lower() == 'text':
                # Already TEXT - skip
                logger.debug(f"Column {table}.{column} already TEXT - skipping")
                continue
            
            # Widen column to TEXT
            logger.info(f"Migrating {table}.{column} from {data_type} to TEXT")
            session.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE TEXT"))
            session.commit()
            logger.info(f"Successfully migrated {table}.{column} to TEXT")
            
        except Exception as exc:
            logger.error(f"Failed to migrate {table}.{column}: {exc}")
            session.rollback()
            # Continue with other migrations
    
    # Add caller_phone_hash columns if they don't exist
    _add_phone_hash_columns(session)


def _add_phone_hash_columns(session: Session) -> None:
    """Add caller_phone_hash columns for encrypted phone lookups."""
    hash_columns = [
        ("calls", "caller_phone_hash", "VARCHAR(64)"),
        ("demo_requests", "caller_phone_hash", "VARCHAR(64)"),
    ]
    
    for table, column, data_type in hash_columns:
        try:
            # Check if column exists
            result = session.execute(text(f"""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name = '{table}' AND column_name = '{column}'
            """))
            
            if result.fetchone() is not None:
                # Already exists - skip
                logger.debug(f"Column {table}.{column} already exists - skipping")
                continue
            
            # Add column
            logger.info(f"Adding {table}.{column} ({data_type})")
            session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}"))
            session.commit()
            
            # Add index
            index_name = f"ix_{table}_{column}"
            session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"))
            session.commit()
            logger.info(f"Successfully added {table}.{column} with index")
            
        except Exception as exc:
            logger.error(f"Failed to add {table}.{column}: {exc}")
            session.rollback()

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
    
    Raises exception on failure (do not serve traffic with broken schema).
    """
    is_postgres = database_url.startswith("postgresql")
    is_sqlite = database_url.startswith("sqlite")
    
    try:
        if is_postgres:
            _migrate_postgres_encrypted_columns(session)
            _add_new_columns_postgres(session)
        elif is_sqlite:
            _add_new_columns_sqlite(session)
        
        logger.info("All migrations completed successfully")
    except Exception as exc:
        logger.error("Migration FAILED: %s", exc)
        session.rollback()
        raise RuntimeError(f"Database migration failed: {exc}") from exc


def _migrate_postgres_encrypted_columns(session: Session) -> None:
    """
    Widen columns that store encrypted values from VARCHAR to TEXT (Postgres only).
    
    Encrypted values are longer than plaintext (base64 overhead + "enc:" prefix).
    This migration is idempotent - safe to run multiple times.
    
    Raises exception on failure.
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


def _add_new_columns_postgres(session: Session) -> None:
    """
    Add new columns for existing tables (Postgres).
    
    Checks information_schema before adding.
    Raises exception on failure.
    """
    new_columns = [
        # Phone hash columns for encrypted lookups
        ("calls", "caller_phone_hash", "VARCHAR(64)", True),  # indexed
        ("demo_requests", "caller_phone_hash", "VARCHAR(64)", True),  # indexed
        
        # Notes field for dental appointment details
        ("demo_requests", "notes", "TEXT", False),
    ]
    
    for table, column, data_type, needs_index in new_columns:
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
        logger.info(f"Adding column {table}.{column} ({data_type})")
        session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}"))
        session.commit()
        
        # Add index if needed
        if needs_index:
            index_name = f"ix_{table}_{column}"
            session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"))
            session.commit()
            logger.info(f"Successfully added {table}.{column} with index")
        else:
            logger.info(f"Successfully added {table}.{column}")


def _add_new_columns_sqlite(session: Session) -> None:
    """
    Add new columns for existing tables (SQLite).
    
    Uses PRAGMA to check existing columns.
    Raises exception on failure.
    """
    new_columns = [
        # Phone hash columns for encrypted lookups
        ("calls", "caller_phone_hash", "VARCHAR(64)", True),  # indexed
        ("demo_requests", "caller_phone_hash", "VARCHAR(64)", True),  # indexed
        
        # Notes field for dental appointment details
        ("demo_requests", "notes", "TEXT", False),
    ]
    
    for table, column, data_type, needs_index in new_columns:
        # Check if column exists using PRAGMA
        result = session.execute(text(f"PRAGMA table_info({table})"))
        existing_columns = {row[1] for row in result.fetchall()}
        
        if column in existing_columns:
            # Already exists - skip
            logger.debug(f"Column {table}.{column} already exists - skipping")
            continue
        
        # Add column (SQLite doesn't support IF NOT EXISTS in ALTER TABLE ADD COLUMN)
        logger.info(f"Adding column {table}.{column} ({data_type})")
        session.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {data_type}"))
        session.commit()
        
        # Add index if needed
        if needs_index:
            index_name = f"ix_{table}_{column}"
            # SQLite CREATE INDEX has IF NOT EXISTS
            session.execute(text(f"CREATE INDEX IF NOT EXISTS {index_name} ON {table}({column})"))
            session.commit()
            logger.info(f"Successfully added {table}.{column} with index")
        else:
            logger.info(f"Successfully added {table}.{column}")

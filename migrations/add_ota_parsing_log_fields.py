"""
Migration: Add new fields to OTAParsingLog table
Created: 2026-02-04
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.db.session import engine

def upgrade():
    """Add new fields to ota_parsing_logs table"""
    
    with engine.connect() as conn:
        # Add new columns
        conn.execute(text("""
            ALTER TABLE ota_parsing_logs 
            ADD COLUMN IF NOT EXISTS email_message_id VARCHAR(255),
            ADD COLUMN IF NOT EXISTS error_traceback TEXT,
            ADD COLUMN IF NOT EXISTS extracted_data JSONB,
            ADD COLUMN IF NOT EXISTS retry_count INTEGER DEFAULT 0,
            ADD COLUMN IF NOT EXISTS last_retry_at TIMESTAMP WITH TIME ZONE,
            ADD COLUMN IF NOT EXISTS booking_id BIGINT;
        """))
        
        # Add unique constraint and indexes
        conn.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_ota_parsing_logs_email_message_id 
            ON ota_parsing_logs(email_message_id) 
            WHERE email_message_id IS NOT NULL;
        """))
        
        conn.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_ota_parsing_logs_booking_id 
            ON ota_parsing_logs(booking_id);
        """))
        
        # Add foreign key constraint
        conn.execute(text("""
            ALTER TABLE ota_parsing_logs
            ADD CONSTRAINT fk_ota_parsing_logs_booking_id 
            FOREIGN KEY (booking_id) REFERENCES bookings(id) ON DELETE SET NULL;
        """))
        
        conn.commit()
        print("✅ Migration completed: Added new fields to ota_parsing_logs")

def downgrade():
    """Remove new fields from ota_parsing_logs table"""
    
    with engine.connect() as conn:
        # Drop foreign key first
        conn.execute(text("""
            ALTER TABLE ota_parsing_logs
            DROP CONSTRAINT IF EXISTS fk_ota_parsing_logs_booking_id;
        """))
        
        # Drop indexes
        conn.execute(text("""
            DROP INDEX IF EXISTS ix_ota_parsing_logs_email_message_id;
            DROP INDEX IF EXISTS ix_ota_parsing_logs_booking_id;
        """))
        
        # Drop columns
        conn.execute(text("""
            ALTER TABLE ota_parsing_logs 
            DROP COLUMN IF EXISTS email_message_id,
            DROP COLUMN IF EXISTS error_traceback,
            DROP COLUMN IF EXISTS extracted_data,
            DROP COLUMN IF EXISTS retry_count,
            DROP COLUMN IF EXISTS last_retry_at,
            DROP COLUMN IF EXISTS booking_id;
        """))
        
        conn.commit()
        print("✅ Migration rolled back: Removed fields from ota_parsing_logs")

if __name__ == "__main__":
    print("Running migration: Add OTA Parsing Log fields...")
    upgrade()
"""
Database Migration: Add import_images table

Run this migration to add support for image attachments to import receipts.
"""

CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS import_images (
    id BIGSERIAL PRIMARY KEY,
    receipt_id BIGINT NOT NULL REFERENCES inventory_receipts(id) ON DELETE CASCADE,
    
    file_path VARCHAR(500) NOT NULL,
    thumbnail_path VARCHAR(500),
    
    file_size INTEGER,
    width INTEGER,
    height INTEGER,
    
    uploaded_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    display_order INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_import_images_receipt_id ON import_images(receipt_id);
CREATE INDEX IF NOT EXISTS idx_import_images_uploaded_at ON import_images(uploaded_at);
"""

ROLLBACK_SQL = """
DROP TABLE IF EXISTS import_images CASCADE;
"""

if __name__ == "__main__":
    print("Migration SQL for import_images table:")
    print("\n--- CREATE ---")
    print(CREATE_TABLE_SQL)
    print("\n--- ROLLBACK ---")
    print(ROLLBACK_SQL)

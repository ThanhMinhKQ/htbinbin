#!/usr/bin/env python3
"""
Script rebuild CRM data - Chạy để fix dữ liệu cũ
Usage: python scripts/rebuild_crm_data.py
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal
from sqlalchemy import create_engine, func, text
from sqlalchemy.orm import Session

# Database URL - UPDATE THIS
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://user:password@localhost/dbname")

def main():
    engine = create_engine(DATABASE_URL)
    
    with Session(engine) as db:
        print("=== Rebuilding CRM Data ===\n")
        
        # 1. Create guest_stay_mappings table
        print("1. Creating guest_stay_mappings table...")
        db.execute(text("""
            CREATE TABLE IF NOT EXISTS guest_stay_mappings (
                id BIGSERIAL PRIMARY KEY,
                guest_id BIGINT NOT NULL REFERENCES guests(id) ON DELETE CASCADE,
                stay_id BIGINT NOT NULL REFERENCES hotel_stays(id) ON DELETE CASCADE,
                branch_id INTEGER NOT NULL REFERENCES branches(id) ON DELETE RESTRICT,
                room_number VARCHAR(20),
                check_in_at TIMESTAMPTZ,
                check_out_at TIMESTAMPTZ,
                is_primary BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT now()
            )
        """))
        
        # Create indexes
        db.execute(text("""
            CREATE UNIQUE INDEX IF NOT EXISTS ix_guest_stay_mapping_unique 
                ON guest_stay_mappings (guest_id, stay_id)
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_guest_stay_mapping_guest ON guest_stay_mappings (guest_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS ix_guest_stay_mapping_stay ON guest_stay_mappings (stay_id)"))
        print("   ✓ Table created\n")
        
        # 2. Backfill guest_stay_mappings
        print("2. Backfilling guest_stay_mappings...")
        result = db.execute(text("""
            INSERT INTO guest_stay_mappings (guest_id, stay_id, branch_id, room_number, check_in_at, check_out_at, is_primary)
            SELECT 
                hg.guest_id,
                hg.stay_id,
                hs.branch_id,
                hr.room_number,
                hs.check_in_at,
                hs.check_out_at,
                COALESCE(hg.is_primary, FALSE)
            FROM hotel_guests hg
            JOIN hotel_stays hs ON hs.id = hg.stay_id
            LEFT JOIN hotel_rooms hr ON hr.id = hs.room_id
            WHERE hg.guest_id IS NOT NULL
            ON CONFLICT (guest_id, stay_id) DO NOTHING
            RETURNING id
        """))
        inserted = len(result.fetchall())
        print(f"   ✓ Inserted {inserted} mappings\n")
        
        # 3. Update guest_count in guest_stay_summaries
        print("3. Updating guest_count in guest_stay_summaries...")
        db.execute(text("""
            UPDATE guest_stay_summaries gss
            SET guest_count = (
                SELECT COUNT(*) 
                FROM hotel_guests hg 
                WHERE hg.stay_id = gss.stay_id 
                AND hg.guest_id IS NOT NULL
            )
        """))
        print("   ✓ guest_count updated\n")
        
        # 4. Commit
        db.commit()
        
        # 5. Verify
        print("4. Verifying data...")
        result = db.execute(text("""
            SELECT 
                g.full_name,
                gm.tier,
                gm.total_spent,
                gm.loyalty_points,
                gm.points_balance,
                (SELECT COUNT(*) FROM guest_stay_summaries WHERE guest_id = g.id) as stay_count
            FROM guests g
            JOIN guest_memberships gm ON gm.guest_id = g.id
            ORDER BY gm.total_spent DESC
            LIMIT 10
        """))
        print("\n   Top 10 guests by total_spent:")
        print("   " + "-" * 80)
        for row in result:
            print(f"   {row[0]:<20} | {row[1]:<10} | {float(row[2]):>12,.0f}đ | {row[3]:>6} pts | {row[5]:>3} stays")
        
        print("\n=== Done! ===")
        print("\nNext: Call API to recalculate memberships:")
        print("POST /api/pms/crm/admin/rebuild-memberships")

if __name__ == "__main__":
    main()

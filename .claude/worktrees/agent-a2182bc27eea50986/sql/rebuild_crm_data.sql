-- ============================================================
-- REBUILD CRM DATA - Chạy để fix dữ liệu cũ
-- ============================================================

-- Bước 1: Tạo bảng guest_stay_mappings nếu chưa có
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
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_guest_stay_mapping_unique 
    ON guest_stay_mappings (guest_id, stay_id);
CREATE INDEX IF NOT EXISTS ix_guest_stay_mapping_guest 
    ON guest_stay_mappings (guest_id);
CREATE INDEX IF NOT EXISTS ix_guest_stay_mapping_stay 
    ON guest_stay_mappings (stay_id);

-- Bước 2: Backfill guest_stay_mappings từ HotelGuest
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
ON CONFLICT (guest_id, stay_id) DO NOTHING;

-- Bước 3: Update guest_count trong guest_stay_summaries từ HotelGuest
UPDATE guest_stay_summaries gss
SET guest_count = (
    SELECT COUNT(*) 
    FROM hotel_guests hg 
    WHERE hg.stay_id = gss.stay_id 
    AND hg.guest_id IS NOT NULL
);

-- Bước 4: Tạo stay summaries mới nếu thiếu
-- (Chạy qua API: POST /api/pms/crm/admin/rebuild-memberships)

-- Bước 5: Verify dữ liệu
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
LIMIT 20;

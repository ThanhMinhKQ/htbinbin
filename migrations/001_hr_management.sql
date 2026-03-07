-- =============================================================
-- Migration: 001_hr_management
-- Mô tả  : Thêm các cột thông tin cá nhân cho nhân viên
--           phục vụ feature Quản lý Nhân sự
-- Ngày   : 2026-03-08
-- =============================================================

-- Chạy từng lệnh ALTER TABLE, có kiểm tra cột đã tồn tại chưa
-- để tránh lỗi nếu migration bị chạy lại nhiều lần.

-- 1. Số CCCD / CMND
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'cccd'
    ) THEN
        ALTER TABLE users ADD COLUMN cccd VARCHAR(20);
        RAISE NOTICE 'Đã thêm cột: users.cccd';
    ELSE
        RAISE NOTICE 'Cột users.cccd đã tồn tại, bỏ qua.';
    END IF;
END $$;

-- 2. Ngày sinh
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'date_of_birth'
    ) THEN
        ALTER TABLE users ADD COLUMN date_of_birth DATE;
        RAISE NOTICE 'Đã thêm cột: users.date_of_birth';
    ELSE
        RAISE NOTICE 'Cột users.date_of_birth đã tồn tại, bỏ qua.';
    END IF;
END $$;

-- 3. Địa chỉ
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'users' AND column_name = 'address'
    ) THEN
        ALTER TABLE users ADD COLUMN address TEXT;
        RAISE NOTICE 'Đã thêm cột: users.address';
    ELSE
        RAISE NOTICE 'Cột users.address đã tồn tại, bỏ qua.';
    END IF;
END $$;

-- =============================================================
-- Xác nhận kết quả
-- =============================================================
SELECT
    column_name,
    data_type,
    character_maximum_length,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'users'
  AND column_name IN ('cccd', 'date_of_birth', 'address')
ORDER BY column_name;

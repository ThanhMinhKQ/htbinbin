# 🚀 Hướng Dẫn Cấu Hình OTA Agent - Từng Bước

## Bước 1: Lấy Gemini API Key (2 phút)

### Cách lấy:

1. Truy cập: **https://aistudio.google.com/app/apikey**
2. Đăng nhập bằng Google Account
3. Click **"Create API Key"** hoặc **"Get API Key"**
4. Chọn project hoặc tạo project mới
5. Copy API Key (dạng: `AIzaSy...`)

### Cập nhật vào .env:

```bash
GEMINI_API_KEY=AIzaSyXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
```

> ⚠️ **Lưu ý**: Gemini API có quota miễn phí 15 requests/phút, 1500 requests/ngày

---

## Bước 2: Cấu Hình Gmail IMAP (5 phút)

### 2.1. Bật 2-Step Verification

1. Truy cập: **https://myaccount.google.com/security**
2. Tìm mục **"2-Step Verification"**
3. Click **"Get Started"** và làm theo hướng dẫn
4. Verify bằng số điện thoại

### 2.2. Bật IMAP trong Gmail

1. Mở Gmail → Click **Settings** (⚙️) → **See all settings**
2. Tab **"Forwarding and POP/IMAP"**
3. Chọn **"Enable IMAP"**
4. Click **"Save Changes"**

### 2.3. Tạo App Password

1. Truy cập: **https://myaccount.google.com/apppasswords**
2. Trong mục **"Select app"**: Chọn **"Mail"**
3. Trong mục **"Select device"**: Chọn **"Other"** và đặt tên "OTA Agent"
4. Click **"Generate"**
5. Copy mã 16 ký tự (dạng: `abcd efgh ijkl mnop`)

### 2.4. Cập nhật vào .env:

```bash
IMAP_USER=your_hotel_email@gmail.com
IMAP_PASSWORD=abcdefghijklmnop  # 16 ký tự, KHÔNG có khoảng trắng
```

> 💡 **Tip**: Xóa tất cả khoảng trắng trong App Password khi paste vào .env

---

## Bước 3: Cấu Hình OTA Senders

### Danh sách email OTA phổ biến:

```bash
OTA_SENDERS=noreply@booking.com,reservations@agoda.com,no-reply@expedia.com,noreply@traveloka.com,hotels@airbnb.com
```

### Tùy chỉnh theo OTA bạn dùng:

| OTA | Email Sender |
|-----|--------------|
| Booking.com | `noreply@booking.com` |
| Agoda | `reservations@agoda.com` |
| Expedia | `no-reply@expedia.com` |
| Traveloka | `noreply@traveloka.com` |
| Airbnb | `hotels@airbnb.com` |
| Hotels.com | `noreply@hotels.com` |
| Trip.com | `noreply@trip.com` |

> 📧 **Cách kiểm tra**: Mở 1 email đặt phòng từ OTA → Xem địa chỉ "From"

---

## Bước 4: Test Kết Nối

### Chạy script test:

```bash
cd /Users/thanhminh/Desktop/pmsc-main
python test_ota_connection.py
```

### Kết quả mong đợi:

```
╔════════════════════════════════════════════════════════════╗
║         OTA AGENT - KIỂM TRA CẤU HÌNH & KẾT NỐI          ║
╚════════════════════════════════════════════════════════════╝

============================================================
  1. KIỂM TRA BIẾN MÔI TRƯỜNG
============================================================
✅ PASS | GEMINI_API_KEY
     └─ Đã cấu hình
✅ PASS | IMAP_SERVER
     └─ Đã cấu hình
✅ PASS | IMAP_USER
     └─ Đã cấu hình
✅ PASS | IMAP_PASSWORD
     └─ Đã cấu hình
✅ PASS | OTA_SENDERS
     └─ Đã cấu hình

============================================================
  2. KIỂM TRA GEMINI AI API
============================================================
✅ PASS | Gemini Client
     └─ Client đã khởi tạo thành công

📤 Đang test extraction với email mẫu...
✅ PASS | AI Extraction
     └─ Trích xuất dữ liệu thành công

============================================================
  3. KIỂM TRA KẾT NỐI EMAIL (IMAP)
============================================================
📧 Server: imap.gmail.com
📧 User: your_hotel_email@gmail.com
📧 OTA Senders: 5 địa chỉ

🔌 Đang kết nối đến IMAP server...
✅ PASS | IMAP Connection
     └─ Kết nối thành công

============================================================
  4. KIỂM TRA KẾT NỐI DATABASE
============================================================
✅ PASS | Database Connection
     └─ Kết nối thành công

============================================================
  📊 TỔNG KẾT
============================================================
✅ Biến môi trường
✅ Gemini AI
✅ IMAP Email
✅ Database

🎯 Kết quả: 4/4 tests passed

🎉 HOÀN HẢO! Tất cả cấu hình đều OK!
```

---

## Bước 5: Xử Lý Lỗi Thường Gặp

### ❌ Lỗi: "IMAP Connection Failed"

**Nguyên nhân**:
- App Password sai hoặc có khoảng trắng
- IMAP chưa được bật trong Gmail
- 2-Step Verification chưa được bật

**Giải pháp**:
1. Kiểm tra lại App Password (16 ký tự, không khoảng trắng)
2. Verify IMAP đã bật: Gmail Settings → Forwarding and POP/IMAP
3. Thử tạo lại App Password mới

### ❌ Lỗi: "Gemini API Key Missing"

**Nguyên nhân**:
- Chưa cấu hình GEMINI_API_KEY trong .env
- API Key sai format

**Giải pháp**:
1. Kiểm tra .env có dòng `GEMINI_API_KEY=...`
2. Verify API Key bắt đầu bằng `AIza`
3. Thử tạo API Key mới tại https://aistudio.google.com/app/apikey

### ❌ Lỗi: "No emails found"

**Nguyên nhân**:
- Không có email chưa đọc từ OTA
- OTA_SENDERS không khớp với email thực tế

**Giải pháp**:
1. Kiểm tra inbox có email từ OTA chưa đọc không
2. Verify địa chỉ sender trong OTA_SENDERS
3. Thử mark một email OTA là "Unread" để test

---

## Bước 6: Test Thủ Công với Email Thật

### Chuẩn bị:

1. Tìm 1 email đặt phòng thật từ OTA trong inbox
2. Mark email đó là **"Unread"** (chưa đọc)

### Chạy test:

```bash
cd /Users/thanhminh/Desktop/pmsc-main
python -c "
from app.services.ota_agent.integration import ota_agent
ota_agent.run_once()
"
```

### Kiểm tra kết quả:

```sql
-- Kiểm tra booking đã được tạo
SELECT * FROM bookings ORDER BY created_at DESC LIMIT 5;

-- Kiểm tra log
SELECT * FROM ota_parsing_logs ORDER BY received_at DESC LIMIT 5;
```

---

## Bước 7: Bật Tự Động Hóa (Tùy chọn)

Sau khi test thành công, bạn có thể bật scheduler để tự động check email:

```bash
# Sẽ được hướng dẫn ở bước tiếp theo
# Xem file: ota_next_steps.md - Phase 1
```

---

## 📞 Cần Hỗ Trợ?

Nếu gặp vấn đề, cung cấp thông tin sau:

1. **Output của script test**: Copy toàn bộ output của `python test_ota_connection.py`
2. **Log lỗi**: Nếu có error, copy full error message
3. **Môi trường**:
   - Python version: `python --version`
   - OS: macOS/Windows/Linux
   - Gmail account type: Personal/Workspace

---

## ✅ Checklist Hoàn Thành

- [ ] Đã lấy Gemini API Key
- [ ] Đã bật 2-Step Verification trên Gmail
- [ ] Đã bật IMAP trong Gmail Settings
- [ ] Đã tạo App Password
- [ ] Đã cập nhật .env với đầy đủ thông tin
- [ ] Đã chạy `test_ota_connection.py` thành công (4/4 tests pass)
- [ ] Đã test với email OTA thật

**Khi tất cả ✅ → Sẵn sàng triển khai scheduler!** 🚀

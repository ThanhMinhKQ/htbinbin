# 📊 DESIGN.md — Trang "Lịch đặt phòng (Timeline theo phòng)"

---

## 1. Tổng quan

Trang **Lịch đặt phòng dạng Timeline** là màn hình trực quan cao nhất trong PMS, cho phép:

* Theo dõi tình trạng từng phòng theo thời gian
* Hiển thị booking dạng kéo dài theo ngày (timeline bar)
* Nhận biết nhanh:

  * Phòng đang có khách
  * Phòng sắp có khách
  * Khoảng trống giữa các booking
  * Trạng thái đặc biệt (dọn phòng, bảo trì)

👉 Đây là **màn hình vận hành chính của lễ tân**

---

## 2. Layout tổng thể (Full-width)

### Bố cục:

```
[ Sidebar ] [ Header filter ]

[ Timeline Grid (FULL WIDTH) ]

[ Legend trạng thái ]
```

👉 Đặc điểm:

* Chiếm toàn bộ chiều ngang màn hình (quan trọng)
* Scroll ngang mượt như Excel / Notion
* Sticky header + sticky cột phòng

---

## 3. Header & Bộ lọc

### Thành phần:

* Chọn khoảng ngày (date range)
* Nút:

  * ← → (dịch timeline)
  * "Hôm nay"
* Filter:

  * Loại phòng

### UX:

* Khi đổi range → reload dữ liệu
* Giữ trạng thái filter
* Snap về "Today" nếu click nhanh

---

## 4. Timeline Grid (trung tâm)

## 4.1 Cấu trúc bảng

| Phòng | Loại phòng | 01/05 | 02/05 | 03/05 | ... |
| ----- | ---------- | ----- | ----- | ----- | --- |

### Cột:

* **Phòng** (sticky left)
* **Loại phòng** (sticky)
* **Ngày** (scroll ngang)

---

## 4.2 Booking dạng thanh (Timeline Bar)

### Mỗi booking hiển thị:

* Tên khách
* Thời gian (check-in → check-out)
* Thanh kéo dài qua nhiều ngày

### Ví dụ:

```
[ Nguyễn Văn A ]
01/05 ─────────────── 03/05
```

---

## 5. Màu sắc trạng thái (rất quan trọng)

| Trạng thái | Màu           | Ý nghĩa               |
| ---------- | ------------- | --------------------- |
| Đã đặt     | 🔵 Xanh dương | Booking chưa check-in |
| Đang ở     | 🟢 Xanh lá    | Khách đang lưu trú    |
| Trống      | ⚪ Xám nhạt    | Có thể bán            |
| Đang dọn   | 🟡 Vàng       | Housekeeping          |
| Bảo trì    | ⚫ Xám đậm     | Không bán             |

👉 Nguyên tắc:

* Nhìn màu → hiểu ngay trạng thái
* Không cần đọc chữ

---

## 6. Các loại block đặc biệt

### 6.1 Booking block

* Bo góc lớn (rounded-xl)
* Gradient nhẹ (hiện đại)
* Shadow nhẹ
* Text trắng

---

### 6.2 Block "Dọn phòng"

* Màu vàng
* Không kéo dài nhiều ngày (thường 1 slot)
* Icon 🧹

---

### 6.3 Block "Bảo trì"

* Màu xám đậm
* Có thể kéo dài nhiều ngày
* Disabled interaction

---

## 7. UX tương tác nâng cao

### 7.1 Hover

* Hiện tooltip:

  * Tên khách
  * SĐT
  * Giờ check-in/out
  * Ghi chú

---

### 7.2 Click

* Mở popup:

  * Chi tiết booking
  * Edit / check-in / check-out

---

### 7.3 Drag & Drop (nâng cao)

* Kéo booking để đổi ngày
* Kéo sang phòng khác (nếu hợp lệ)

---

### 7.4 Resize

* Kéo dài / rút ngắn booking

---

## 8. Sticky & Scroll

### Sticky:

* Cột "Phòng"
* Header ngày

### Scroll:

* Ngang: timeline
* Dọc: danh sách phòng

👉 Quan trọng:

* Scroll mượt (performance cao)
* Không lag khi nhiều phòng

---

## 9. Highlight thông minh

### 9.1 Ngày hiện tại

* Background vàng nhạt

### 9.2 Ô đang focus

* Border xanh nhẹ

### 9.3 Khoảng trống giữa booking

* Hiển thị rõ để upsell

---

## 10. Legend (chú thích)

Hiển thị dưới cùng:

* 🔵 Đã đặt
* 🟢 Đang ở
* ⚪ Trống
* 🟡 Đang dọn
* ⚫ Bảo trì

👉 Giúp nhân viên mới hiểu nhanh

---

## 11. Use Case thực tế

### Case 1: Khách walk-in

→ Nhìn timeline → tìm khoảng trống ngay

---

### Case 2: Overbooking

→ Nhìn chồng booking → xử lý ngay

---

### Case 3: Dọn phòng

→ Xem block vàng → phân công housekeeping

---

### Case 4: Điều phối phòng

→ Kéo booking sang phòng khác

---

## 12. Tối ưu hiệu năng (quan trọng)

### Backend:

* Query theo range ngày
* Cache theo ngày

### Frontend:

* Virtual scroll (nếu >100 phòng)
* Render lazy

---

## 13. Mobile UX (nếu dùng)

👉 Không dùng table truyền thống

Thay bằng:

* Card dạng timeline ngang
* Swipe trái/phải
* Tap để expand

---

## 14. Nguyên tắc thiết kế 2025

* Ít text – nhiều visual
* Màu sắc có ý nghĩa
* Interaction mượt như app native
* Không reload toàn trang
* Ưu tiên tốc độ phản hồi

---

## 15. Kết luận

Đây là màn hình:

* **Quan trọng nhất trong vận hành khách sạn**
* Ảnh hưởng trực tiếp đến:

  * Doanh thu
  * Trải nghiệm khách
  * Hiệu suất lễ tân

👉 Nếu làm tốt:

* Giảm sai sót vận hành
* Tăng tốc xử lý booking
* Nhân viên mới dùng được ngay

---

## 16. Gợi ý nâng cấp (nếu muốn đi xa hơn)

* Heatmap occupancy
* AI gợi ý đổi phòng tối ưu
* Auto detect overbooking
* Sync realtime nhiều user

---

Nếu bạn cần, tôi có thể:

* Viết luôn HTML + Tailwind chuẩn iOS style
* Thiết kế drag-drop full JS (không lag)
* Hoặc tối ưu backend FastAPI cho timeline này (chuẩn production)

Nói thẳng: màn này nếu làm không tới → dùng cực khó.
Làm chuẩn → nó trở thành “vũ khí” vận hành.

Bạn muốn tôi build luôn bản code chuẩn production không?

# Trình soạn thông báo ca — Thay execCommand bằng Quill 2.0

**Ngày:** 2026-05-30
**File ảnh hưởng:** `app/templates/attendance_notifications.html` (vùng soạn), `app/templates/includes/shift_notifications.html` (vùng hiển thị popup)
**Không đụng:** backend, API upload, schema DB.

## Vấn đề

Trình soạn thông báo hiện xây trên `document.execCommand` (API đã deprecated):
- Không có lựa chọn font-family và cỡ chữ (điểm đau chính).
- Hành vi không nhất quán cross-browser (`hiliteColor`, `formatBlock`).
- Cơ chế đồng bộ dùng hack `setTimeout` (`deferSyncEditor`, `saveSelection`/`savedRange`) mong manh, dễ mất định dạng list/block.
- Sanitize chạy lại mỗi lần sync, dễ phá cấu trúc đang gõ dở.

## Mục tiêu

Trình soạn nội dung chuyên nghiệp, ổn định, có font-family + cỡ chữ, hết bug cross-browser căn bản. Giữ toàn bộ tính năng cũ: định dạng chữ, ảnh (upload + URL), link & file đính kèm, kéo-thả & dán ảnh.

## Kiến trúc

Thay lõi soạn thảo sang **Quill 2.0**, load qua CDN (giống flatpickr/Alpine hiện có). Pin phiên bản cụ thể, không dùng "latest".

Luồng dữ liệu:
```
Quill editor → quill.root.innerHTML → sanitize → form.body → POST (API cũ) → DB (HTML)
DB (HTML) → sanitizeRichHtml (popup) → hiển thị
```

**Quyết định mấu chốt — đồng bộ định dạng:** cấu hình Quill xuất **inline CSS thay vì class** (đăng ký lại attributor của Quill ở chế độ inline-style cho size/font/align). HTML lưu ra dạng `<span style="font-size:...; font-family:...">` — đúng dạng sanitizer popup đã chấp nhận, thay vì class `ql-*` sẽ bị strip. Nhờ đó HTML cũ vẫn đọc được, HTML mới hiển thị đúng ở popup.

## Toolbar, font & cỡ chữ

**Bộ font (5, đều hiển thị tiếng Việt tốt):** Inter (mặc định), Arial, Times New Roman, Roboto, Be Vietnam Pro. Inter/Roboto/Be Vietnam Pro nạp từ Google Fonts (site đã preconnect); Arial/Times là font hệ thống.

**Cỡ chữ:** Nhỏ (12px) / Thường (15px, mặc định) / Lớn (20px) / Rất lớn (28px). Dùng px cụ thể, tách bạch với heading H1-H3.

**Bố cục toolbar (trái→phải):**
1. Font-family + cỡ chữ (2 dropdown mới)
2. Tiêu đề: Đoạn văn / H1 / H2 / H3
3. Đậm / Nghiêng / Gạch chân / Gạch ngang
4. Màu chữ + màu nền
5. Danh sách chấm / danh sách số
6. Canh lề trái/giữa/phải
7. Chèn: link, ảnh (upload + URL), file đính kèm
8. Xóa định dạng

Quill tự render toolbar từ cấu hình → bỏ toàn bộ HTML nút SVG thủ công + ~15 handler `editorCommand`/`editorBlock`.

**Upload ảnh/file:** giữ nguyên API `/attendance/api/shift-notifications/upload` (trả `{status, url, filename, size}`). Nối vào Quill qua custom handler: nút ảnh/file trên toolbar Quill → mở file input → `uploadAndInsert` → chèn vào Quill bằng API của nó (không dùng `insertHTML`). Kéo-thả và dán ảnh nối vào sự kiện Quill.

**Giao diện:** theme `snow`, override CSS khớp tông hiện tại (bo góc, viền, dark mode). Vùng soạn giữ class `sn-rich-content`.

## Sanitize & tương thích

**Giữ 2 lớp sanitize** (bảo mật > tiện lợi):
- Vùng soạn: `quill.root.innerHTML` vẫn chạy qua `sanitizeRichHtml` trước khi gán `form.body` (chống XSS, không tin tuyệt đối output Quill).
- **Nới allowlist style:** sanitizer hiện giữ `text-align`, `color`, `background-color`. Bổ sung `font-size` và `font-family` với **whitelist giá trị chặt**: chỉ chấp nhận 5 font + 4 cỡ đã định (regex chặt, loại mọi giá trị lạ). An toàn vì tập giá trị hữu hạn.
- Tag đã có đủ: P, BR, SPAN, STRONG/B, EM/I, U, S, H1-3, UL/OL/LI, BLOCKQUOTE, A, IMG.

**Tương thích dữ liệu cũ:** thông báo cũ là HTML chuẩn → Quill nạp nguyên vẹn (gán innerHTML / `clipboard.dangerouslyPasteHTML`). Không migrate DB. Thông báo cũ không có font/size hiển thị mặc định Inter 15px, không vỡ.

**Đồng bộ Alpine ↔ Quill:** bỏ `syncEditor`/`deferSyncEditor`/`saveSelection`/`savedRange`. Thay bằng: nghe sự kiện `text-change` của Quill → cập nhật `form.body`. Mở modal sửa → nạp `form.body` vào Quill một lần.

## Dark mode & xử lý lỗi

- **Dark mode:** override biến màu toolbar + vùng soạn theo `html.dark`.
- **Quill load fail (CDN):** fallback `<textarea>` để vẫn soạn text thuần, không kẹt người dùng.
- **Upload lỗi:** giữ nguyên toast hiện có.

## Rủi ro đã lường

- Popup `shift_notifications.html` có **bản sanitizer riêng** → phải sửa allowlist style ở **cả 2 file** cho khớp; lệch sẽ khiến soạn thấy đẹp nhưng hiển thị mất font.
- Pin phiên bản Quill 2.0 cụ thể trên CDN để tránh vỡ bất ngờ khi thư viện cập nhật.

## Ngoài phạm vi

- Không đổi backend, API, schema.
- Không migrate dữ liệu cũ.
- Không thêm font trang trí (chỉ bộ cơ bản 5 font).

## Kiểm thử

- Soạn mới: áp font + cỡ chữ + định dạng → lưu → mở lại sửa → đúng nguyên trạng.
- Hiển thị popup `shift_notifications.html`: font/cỡ/màu/căn lề hiển thị đúng.
- Thông báo cũ (HTML không Quill): mở sửa và hiển thị không vỡ.
- Upload ảnh/file, chèn URL, link, kéo-thả, dán ảnh.
- Dark mode + mobile width.
- Quill load fail → fallback textarea.

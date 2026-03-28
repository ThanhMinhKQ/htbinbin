# Kiến trúc HTML Templates PMS (Giao diện người dùng)

Tài liệu này mô tả chi tiết chức năng và quy hoạch giao diện (View Layer) của toàn bộ các file HTML (Jinja2) nằm trong thư mục `app/templates/pms`.
Hệ thống giao diện được thiết kế để tách biệt rõ ràng giữa các trang chính (Pages) và các cửa sổ con (Modals/Partials) để dễ bảo trì.

---

## 1. Main Pages (Các trang chính)
Các file HTML lớn đóng vai trò là khung xương hiển thị cho từng chức năng chính của Lễ tân và Quản trị viên.

### `dashboard.html` (30KB)
- **Vai trò**: Màn hình làm việc chính của Lễ tân (Reception Desk).
- **Giao diện**:
  - Thanh công cụ (Toolbar) trên cùng để lọc tầng, khu vực.
  - Vùng sơ đồ phòng trực quan dạng lưới (Grid), hiển thị trạng thái Trống, Đang ở, Dọn dẹp, Bảo trì.
  - Include file `detail.html` và `modals.html` để phục vụ các popup phát sinh khi click vào phòng.
- **Logic Jinja2**: Nhận dữ liệu `branches` (chi nhánh) và config hệ thống ban đầu. Gọi tới `pms_dashboard.js` để render danh sách phòng qua AJAX.

### `booking.html` (15KB)
- **Vai trò**: Giao diện Quản lý Đặt phòng (Reservation / Tìm kiếm phòng trống).
- **Giao diện**:
  - Giao diện **Smart Search**: Form cho phép nhập ngày Check-in, Check-out, Loại phòng, Ngân sách.
  - **Calendar View**: Bảng kéo dọc dạng biểu đồ ngantt/calendar xem trước lịch lấp đầy phòng của khách sạn trong tương lai.
  - Popup tạo Check-in nhanh từ giao diện kết quả tìm kiếm.

### `room_setup.html` (39KB)
- **Vai trò**: Màn hình Cài đặt cơ sở vật chất (Dành cho Quản lý / Admin).
- **Giao diện**:
  - Quản lý danh mục **Loại phòng (Room Types)**: Cài đặt giá giờ, giá đêm, giá thêm người, v.v.
  - Quản lý danh sách **Phòng (Rooms)**: Phân bổ số phòng vào các khu vực/tầng, gắn loại hình phòng tương ứng.
  - Giao diện quản lý dịch vụ (Minibar, Giặt ủi) dùng chung cho module PMS.

### `checkin.html` (34KB) & `checkout.html` (3KB)
- **Vai trò**: Đây có thể là các trang hoặc partial lưu trữ form đầy đủ cho tác vụ Check-in và Check-out ngoài dashboard. 
- *Lưu ý*: Tính năng check-out hiện đại thường chủ yếu thực hiện qua popup (modals), do đó file `checkout.html` rất nhẹ (3KB) chỉ chứa form khung cho chức năng thanh toán nhanh. Ngược lại `checkin.html` chứa rất nhiều form logic hiển thị đoàn khách.

---

## 2. Partials & Modals (Thành phần giao diện tái sử dụng)
Các file đại diện cho giao diện cửa sổ nổi (Modal) đè lên `dashboard.html` giúp Lễ tân thao tác nhanh mà không phải tải lại trang.

### `modals.html` và `detail.html`
Hai file này đóng vai trò là "Wrapper" (Vỏ bọc) tích hợp nhiều tính năng được include từ thư mục con `modals/`.
- `modals.html`: Gọi các modal Thêm khách (Add Guest) và Chuyển phòng (Transfer).
- `detail.html`: Gọi modal trung tâm hiển thị Chi tiết một phòng đang có khách (Cùng các popup phụ phí, dịch vụ đi kèm).

### Thư mục `/modals/` (Chứa code HTML chia nhỏ)
- **`ag_modal.html`**: Giao diện form Thêm & Sửa khách hàng (Add Guest) siêu phức tạp với 3 cột (Giấy tờ, Cá nhân, Địa chỉ). Hỗ trợ Datlist gợi ý tìm kiếm.
- **`tf_modal.html`**: Giao diện form Chuyển phòng (Transfer Room), xử lý chuyển sơ đồ thanh toán từ phòng cũ sang phòng mới.
- **`rd_modal.html`**: Giao diện chính hệ thống "Room Detail", chia tab (Danh sách khách, Phụ thu, Dịch vụ dùng thêm, Thông tin ghi chú).
- **`rd_popups.html`**: Chứa hàng loạt các popup cấp 2 (Popup lồng Popup) phục vụ cho `rd_modal.html`, bao gồm Form nhập Surcharge, form nhập Menu Dịch vụ, form Gia hạn thời gian trả phòng (Extension).

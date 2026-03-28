# Kiến trúc JavaScript PMS (Quản lý Khách sạn)

Tài liệu này mô tả chi tiết chức năng và logic hoạt động của toàn bộ các file JavaScript nằm trong thư mục `app/static/js/pms`. 
Hệ thống JS PMS được thiết kế theo hướng **Modular Architecture**, chia nhỏ các luồng nghiệp vụ phức tạp thành nhiều file theo từng miền chức năng (Domain-Driven) nhằm tối ưu hiệu suất tải trang và dễ dàng bảo trì.

---

## 1. Core & Utilities (Tiện ích dùng chung)
Các file này chứa những hàm cốt lõi để gọi API, xử lý dữ liệu chung và định hình giao diện thông báo. Phải được tải (load) đầu tiên trên mọi trang của hệ thống PMS.

### `pms_common.js`
- **Chức năng**: Tiện ích dùng chung (Shared Utilities).
- **Quy trình / Logic**:
  - `pmsApi(endpoint, options)`: Wrapper chuẩn hóa việc fetch API, xử lý lỗi hệ thống (500) và lỗi chưa đăng nhập (401), hỗ trợ kèm Token/Session tự động.
  - `pmsToast(message, isSuccess)`: Hiển thị popup thông báo góc dưới màn hình.
  - `pmsFormatVnd(amount)` / `pmsFormatDate(date)`: Format tiền tệ (VD: 100,000) và ngày tháng chuẩn VN.
  - `pmsEscapeHtml(str)`: Escape các ký tự đặc biệt giúp ngăn chặn lỗ hổng XSS khi render chuỗi ra DOM.

### `pms.js`
- **Chức năng**: File khởi tạo base cho layout PMS.
- **Quy trình / Logic**: Thường quản lý các sự kiện toàn cục như Toggle Sidebar, quản lý Session timeout, hoặc gắn các Global Event Listener không thuộc riêng module nào.

### `nationalities.js`
- **Chức năng**: Kho dữ liệu từ điển danh sách quốc tịch (`VNM - Việt Nam`, `USA - United States`, v.v.).
- **Quy trình / Logic**: Tự động chèn (inject) danh sách các thẻ `<option>` vào `<datalist id="dl-nationality">` khi khởi tạo form dành cho khách quốc tế.

---

## 2. Main Workflows (Các luồng nghiệp vụ chính)
Các file điều phối toàn bộ nghiệp vụ check-in, check-out và quản lý phòng hàng ngày.

### `pms_dashboard.js`
- **Chức năng**: Quản lý Sơ đồ phòng hiện thời (Lễ tân).
- **Quy trình / Logic**:
  - **Fetching**: Gọi API lấy trạng thái (Clean, Dirty, Occupied, Reserved) của toàn bộ các phòng (`pmsLoadRooms()`).
  - **Rendering**: Render sơ đồ phòng dạng lưới (Grid), phân nhóm theo Tầng (Floor) hoặc theo Khu vực.
  - **Quick Actions**: Bắt sự kiện dọn phòng (Đổi phòng từ Dirty -> Clean), xác nhận bảo trì phòng (Maintenance).

### `pms_checkin.js`
- **Chức năng**: Quản lý quy trình Nhận phòng (Check-in).
- **Quy trình / Logic**:
  - Khi thao tác trên một phòng "Trống", mở modal Check-in.
  - Nhận trước thông tin khách (Walk-in hoặc khách từ OTA).
  - Tự động bắt logic thuê phòng qua đêm, tính giá phòng tạm tính (`pmsCalcPrice()`).
  - Luồng quét mã CCCD / Gợi ý thông tin khách cũ tích hợp ngay lúc tạo booking.

### `pms_checkout.js`
- **Chức năng**: Quản lý quy trình Trả phòng (Check-out) & Thanh toán.
- **Quy trình / Logic**:
  - Mở modal tổng kết chi phí thanh toán cho phòng đang ở (`pmsOpenCheckout(stayId)`).
  - Liệt kê tiền phòng gốc, phụ thu (Surcharge), tiền dịch vụ (Service), sau đó tự trừ đi tiền đã cọc (Deposit/Prepayment).
  - Tự động thay đổi trạng thái thẻ phòng sang `Trống & Dơ (DIRTY)`.
  - Hỗ trợ in hóa đơn sau khi check-out thành công.

### `pms_booking.js`
- **Chức năng**: Tìm kiếm & Lọc phòng trống cho tương lai.
- **Quy trình / Logic**:
  - Xử lý form thông minh Smart Search: lọc theo ngày check-in/check-out, loại phòng, số lượng khách và ngân sách.
  - Mở Calendar View (hiển thị Timeline các phòng) xem độ lấp đầy trong tuần.

---

## 3. Sub-Modals (Các modal chức năng phụ trợ)
Các file xử lý nghiệp vụ đi sâu vào cấu hình chi tiết của từng Lượt lưu trú (Stay) hoặc từng Khách hàng cá nhân (Guest).

### `rd_modal.js` (Room Detail Modal)
- **Chức năng**: Giao diện tập trung quản lý chi tiết một phòng Đang có khách. (Chi tiết lưu trú).
- **Quy trình / Logic**:
  - Đây là file có logic DOM phức tạp nhất. Nó chia làm 4 tab chính: `Khách`, `Phụ thu`, `Dịch vụ`, `Thông tin chung`.
  - Hỗ trợ các popup phụ trong lòng nó (Sub-popups) bằng các hàm riêng biệt:
    - Surcharge Popup (`pmsRdOpenSurcharge()`): Màn hình phụ thu check-in sớm, check-out trễ, quá người.
    - Service Popup (`pmsRdOpenService()`): Gọi món ăn, nước uống, đồ sinh hoạt.
    - Extension Popup (`pmsRdOpenExtension()`): Kéo dài thời gian lưu trú để tính lại giá phòng gốc.

### Module Add Guest (`ag_modal.js`, `ag_form.js`, `ag_search.js`)
*Module Thêm & Sửa khách hàng đã được module hóa thành các file nhỏ gọn.*

1. **`ag_modal.js`**
   - **Chức năng**: Lõi của modal Thêm/Sửa Khách.
   - **Logic**: Quản lý state của form (mở form, gắn flag edit `agSetEditMode()`, xử lý danh sách khách nạp sẵn `agRenderGuestList`, đóng gói JSON body đẩy lên API để lưu trữ `submitAG()`).

2. **`ag_form.js`**
   - **Chức năng**: Bộ quy tắc Form.
   - **Logic**: Viết hoa tên khách hàng, tự chèn chuỗi định dạng (capitalization), bắt lỗi thẻ CCCD không đủ số (`agValidateID`), khóa nút sửa khi tuổi quá nhỏ (`agCheckBirth`), format số lượng tài chính/điện thoại (`agFormatBasicNumeric`).

3. **`ag_search.js`**
   - **Chức năng**: Tìm kiếm khách hàng cũ.
   - **Logic**: Lấy Input từ CCCD hoặc Số điện thoại, gọi API ngầm trả về các object JSON của khách cũ (`agSearchOldGuest()`). Render một Popup tìm kiếm ảo (Fake Modal) đè lên giao diện hiện hành, người dùng click vào -> Auto-fill ngược toàn bộ dữ liệu vào form `ag_modal.js` (`agFillGuestFromOld()`).

---

## 4. Địa chỉ (Address Handling & Location Mode)
Việt Nam vừa qua cuộc đại sáp nhập Địa giới hành chính (Có hiệu lực 2025). Hệ thống sử dụng 2 file JS để linh động xử lý dữ liệu Hộ khẩu/Thường trú tùy theo loại CCCD khách mang.

### `vn_address.js` 
- **Chức năng**: Core hệ thống địa chỉ Việt Nam V4 (Global).
- **Quy trình / Logic**: 
  - Khởi tạo chế độ Phân vùng Mới (chỉ Tỉnh/Thành -> Phường/Xã).
  - Khởi tạo chế độ Phân vùng Cũ (Tỉnh/Thành -> Quận/Huyện -> Phường/Xã).
  - Liên kết với API `/api/vn-address/convert` để có mapping tự động giữa địa bàn cũ sang địa bàn mới nếu khách cung cấp mã cũ. Giúp Data Warehouse luôn chuẩn.

### `ag_address.js`
- **Chức năng**: Controller phiên bản Datalist Dropdown gọn nhẹ dành riêng cho Form `ag_modal.js`.
- **Quy trình / Logic**: 
  - Đính kèm thuộc tính `autocomplete="off"` mặc định thông minh để chặn browser override danh sách Dropdown của mình.
  - Áp dụng kỹ thuật tối ưu hóa vòng lặp HTML `innerHTML` để nối chuỗi tĩnh render danh sách Quận Huyện hàng loạt với tốc độ ms thay vì dùng appendChild dom node, đảm bảo dropdown không bị giật lag khi gõ.
  - Sử dụng logic Delay-Update (Không xóa Dropdown cũ trong khi người dùng đang đánh máy giữa chừng, chỉ xóa và gọi Call API mới khi người dùng "blur" hoặc chủ động chọn giá trị), giúp trải nghiệm gõ chữ mượt mà.

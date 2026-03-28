# Kiến trúc Backend API PMS (FastAPI)

Tài liệu này mô tả chi tiết chức năng và quy hoạch phân tầng Backend (Controllers/Routers) của toàn bộ các file Python API nằm trong thư mục `app/api/pms`.
Hệ thống thiết kế theo chuẩn **RESTful API**, chia tách module rõ ràng dựa trên các đối tượng nghiệp vụ (Entities) của một khách sạn.

---

## 1. Giao Tiếp Frontend (Pages & Renders)

### `pms_pages.py`
- **Vai trò**: Cung cấp các Endpoint trả về mã HTML (Sử dụng `Jinja2Templates`).
- **Nhiệm vụ**:
  - Định tuyến các trang giao diện như `/pms/dashboard`, `/pms/booking`, `/pms/setup`.
  - Kiểm tra Authentication (xem user đã đăng nhập chưa) trước khi cho phép vào giao diện PMS.
  - Chuẩn bị dữ liệu mồi (Seed Data) như danh sách chi nhánh (branches) hoặc cài đặt khách sạn đẩy thẳng vào Jinja context.

---

## 2. Core Entities (Quản trị Dữ liệu Gốc)

### `pms_rooms.py`
- **Vai trò**: Quản lý Vòng đời & Dữ liệu của Phòng (Rooms) và Loại phòng (Room Types).
- **Nhiệm vụ (Endpoints)**:
  - `GET /api/pms/rooms`: Lấy danh sách toàn bộ sơ đồ phòng hiện tại (Map status: Trống, Dọn dẹp, Có khách).
  - `POST / PUT / DELETE`: CRUD cho cấu hình phòng ở màn hình Setup (Tạo phòng mới, Thay đổi giá giờ/giá đêm).
  - Cập nhật nhanh trạng thái bảo trì hoặc buồng phòng (Housekeeping: Đổi từ Dirty -> Clean).

### `pms_admin.py`
- **Vai trò**: Các tùy chỉnh cấu hình phân quyền và tham số vĩ mô.
- **Nhiệm vụ (Endpoints)**:
  - Cấu hình chuỗi khách sạn (Nhiều chi nhánh, nhiều tài khoản Quản lý chi nhánh).
  - Quản trị danh mục dịch vụ (Mì ly, Nước suối, Giặt ủi) và cấu hình thuế phí.

---

## 3. Transactional Operations (Các Giao dịch & Luồng khách hàng)

### `pms_checkin.py`
- **Vai trò**: Điểm bắt đầu của một Lượt lưu trú (Stay).
- **Nhiệm vụ (Endpoints)**:
  - `POST /api/pms/checkin`: Khởi tạo đối tượng `Stay`.
  - Sinh mã đặt phòng tự động, tính toán khung giờ nhận phòng (Thuê giờ vs Qua đêm).
  - Gắn danh sách khách ban đầu (ID thẻ, Tên, Cọc tiền) vào database.
  - Cập nhật trạng thái `Room` sang thẻ `Occupied`.

### `pms_checkout.py`
- **Vai trò**: Điểm kết thúc của một Lượt lưu trú.
- **Nhiệm vụ (Endpoints)**:
  - `POST /api/pms/checkout/{stay_id}`: Hàm xử lý đóng kỳ lưu trú.
  - Thu tiền hóa đơn, tự động khớp cấn trừ công nợ (Deposit).
  - Thay đổi trạng thái `Room` sang thẻ `Dirty` (Đợi dọn dẹp).
  - Có thể gọi hệ thống gửi Log Audit hoặc đẩy hóa đơn ra máy in.

### `pms_stays.py`
- **Vai trò**: Trái tim của quá trình Quản lý khách Đang lưu trú. File đồ sộ nhất xử lý mọi biến cố xảy ra trong lúc khách đang ở.
- **Nhiệm vụ (Endpoints)**:
  - **Guests**: Thêm khách (Add Guest), Cập nhật thông tin khách `PUT /guests/{id}`, Xóa khách khỏi phòng. Hỗ trợ tra cứu siêu tốc lịch sử khách cũ bằng CCCD (`/search`).
  - **Surcharges**: CRUD cho Phụ thu (Thêm tiền Check-in sớm, Check-out trễ, quá người, phạt đền bù).
  - **Services**: CRUD cho Order thêm dịch vụ (Gọi menu đồ ăn thức uống).
  - Lắng nghe yêu cầu Đổi phòng (Transfer Room) và di dời vắt chéo các chi phí từ phòng cũ sang lịch sử phòng mới.

---

## 4. Helpers & Integrations (Tiện ích và Tích hợp xử lý)

### `pms_helpers.py`
- **Vai trò**: Thư viện chứa các Business Logic thuần túy, không định nghĩa Router trực tiếp.
- **Nhiệm vụ**:
  - Thuật toán tính toán giá tiền tự động (Dynamic Pricing) theo Block giờ, theo đêm, tùy hệ số giá cuối tuần hay ngày lễ.
  - Các hàm tiện ích parse date, timezone, tính khấu hao hay chuẩn hóa dữ liệu Payload trước khi validate.
  
### `vn_address.py`
- **Vai trò**: Trục xương sống dữ liệu hệ thống Địa phận hành chính Việt Nam.
- **Nhiệm vụ (Endpoints)**:
  - Cung cấp danh sách 63 Tỉnh/Thành, Quận/Huyện, Phường/Xã chuẩn.
  - Hỗ trợ "Phiên bản cũ": Gọi proxy ra API hệ thống cũ để lấy danh sách phường xã quá khứ, dành cho các CCCD cấp trước 2025.
  - Hỗ trợ "Phiên bản mới (V4+)" (chỉ Tỉnh/Thành -> Phường/Xã): Load dữ liệu tinh giản sau khi Cải cách hành chính 1/7/2025.
  - Endpoint `POST /convert`: Thuật toán mapping AI/Tra từ điển để quy đổi Địa bàn cũ của khách thành Địa bàn chính thức theo chuẩn mới ngay trên hệ thống.

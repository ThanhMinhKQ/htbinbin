# employees.py
# File quản lý danh sách nhân viên - Nguồn dữ liệu gốc (Single Source of Truth)
# Đã cập nhật code theo quy tắc mới: [role].[viết_tắt_họ_lót][tên] (VD: ktv.ltphuc)

employees = [
#--------------------------------------- BIN BIN HOTEL 1 --------------------------------------------#
    {
        "employee_id": "NV001", "code": "lt.ptqnhu", "name": "Phạm Thị Quỳnh Như",
        "role": "letan", "branch": "B1", "shift": "CS"
    },
    { 
        "employee_id": "NV002", "code": "lt.ttctu", "name": "Tô Thị Cẩm Tú",
        "role": "letan", "branch": "B1", "shift": "CT"
    },
    {
        "employee_id": "NV003", "code": "bp.dkphuong", "name": "Đỗ Kim Phượng",
        "role": "buongphong", "branch": "B1", "shift": "CS"
    },
#--------------------------------------- BIN BIN HOTEL 2 --------------------------------------------#
    {
        "employee_id": "NV004", "code": "lt.ppthuy", "name": "Phan Phương Thúy",
        "role": "letan", "branch": "B2", "shift": "CS"
    },
    {
        "employee_id": "NV005", "code": "lt.nbtran", "name": "Ngô Bảo Trân",
        "role": "letan", "branch": "B2", "shift": "CT"
    },
    {
        "employee_id": "NV006", "code": "bp.ntktuyen", "name": "Nguyễn Thị Kim Tuyến",
        "role": "buongphong", "branch": "B2", "shift": "CT"
    },
    {
        "employee_id": "NV007", "code": "bp.nvpngoc", "name": "Nguyễn Vũ Phi Ngọc",
        "role": "buongphong", "branch": "B2", "shift": "CS"
    },
#--------------------------------------- BIN BIN HOTEL 3 --------------------------------------------#
    {
        "employee_id": "NV008", "code": "lt.vtntran", "name": "Võ Thị Ngọc Trân",
        "role": "letan", "branch": "B3", "shift": "CS"
    },
    {
        "employee_id": "NV009", "code": "lt.ndkhai", "name": "Nguyễn Đăng Khải",
        "role": "letan", "branch": "B3", "shift": "CT"
    },
    {
        "employee_id": "NV010", "code": "bp.tmchau", "name": "Trần Mỹ Châu",
        "role": "buongphong", "branch": "B3", "shift": "CS"
    },
#--------------------------------------- BIN BIN HOTEL 5 --------------------------------------------#
    {
        "employee_id": "NV011", "code": "lt.ntctu", "name": "Nguyễn Thị Cẩm Tú", 
        "role": "letan", "branch": "B5", "shift": "CS"
    },
    {
        "employee_id": "NV012", "code": "lt.hnhdung", "name": "Huỳnh Nguyễn Hoàng Dung",
        "role": "letan", "branch": "B5", "shift": "CT"
    },
    {
        "employee_id": "NV013", "code": "bp.dtkmai", "name": "Đặng Thị Kim Mai",
        "role": "buongphong", "branch": "B5", "shift": "CS"
    },
    {
        "employee_id": "NV014", "code": "bp.lttruong", "name": "Lê Tấn Trường",
        "role": "buongphong", "branch": "B5", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 6 --------------------------------------------#
    {
        "employee_id": "NV015", "code": "lt.ntmhuynh", "name": "Nguyễn Thị Mai Huỳnh",
        "role": "letan", "branch": "B6", "shift": "CS"
    },
    { 
        "employee_id": "NV016", "code": "lt.ntlinh", "name": "Nguyễn Trúc Linh", 
        "role": "letan", "branch": "B6", "shift": "CT"
    },
    {
        "employee_id": "NV017", "code": "bp.ttphu", "name": "Trần Thanh Phú",
        "role": "buongphong", "branch": "B6", "shift": "CS"
    },
#--------------------------------------- BIN BIN HOTEL 7 --------------------------------------------#
    {
        "employee_id": "NV018", "code": "lt.ntbhuyen", "name": "Nguyễn Thị Băng Huyền",
        "role": "letan", "branch": "B7", "shift": "CS"
    },
    {
        "employee_id": "NV019", "code": "lt.pttri", "name": "Phạm Thành Trí",
        "role": "letan", "branch": "B7", "shift": "CT"
    },
    {
        "employee_id": "NV020", "code": "bp.ttbna", "name": "Thạch Thị Bô Na",
        "role": "buongphong", "branch": "B7", "shift": "CS"
    },
    {
        "employee_id": "NV021", "code": "bp.tttnga", "name": "Trần Thị Tuyết Nga",
        "role": "buongphong", "branch": "B7", "shift": "CS"
    },
    {
        "employee_id": "NV022", "code": "bp.ttyen", "name": "Trần Thị Yến",
        "role": "buongphong", "branch": "B7", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 8 --------------------------------------------#
    {
        "employee_id": "NV023", "code": "lt.tpmai", "name": "Tô Phương Mai",
        "role": "letan", "branch": "B8", "shift": "CS"
    },
    {   
        "employee_id": "NV024", "code": "lt.npqbao", "name": "Nguyễn Phi Quốc Bảo",
        "role": "letan", "branch": "B8", "shift": "CT"
    },
    {
        "employee_id": "NV025", "code": "bp.ntnhi", "name": "Nguyễn Thị Nhi",
        "role": "buongphong", "branch": "B8", "shift": "CS"
    },
    {
        "employee_id": "NV026", "code": "bp.htkngan", "name": "Huỳnh Thị Kim Ngân",
        "role": "buongphong", "branch": "B8", "shift": "CS"
    },
    {
        "employee_id": "NV027", "code": "bp.ttthai", "name": "Trương Thị Thanh Hải",
        "role": "buongphong", "branch": "B8", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 9 --------------------------------------------#
    {
        "employee_id": "NV028", "code": "lt.dtynhi", "name": "Đặng Thụy Yến Nhi",
        "role": "letan", "branch": "B9", "shift": "CS"
    },
    {
        "employee_id": "NV029", "code": "lt.lqhan", "name": "Lê Quang Hoàng An",
        "role": "letan", "branch": "B9", "shift": "CT"
    },
    {
        "employee_id": "NV030", "code": "bp.pbtran", "name": "Phan Bảo Trân",
        "role": "buongphong", "branch": "B9", "shift": "CS"
    },
    {
        "employee_id": "NV031", "code": "bp.dkthanh", "name": "Đinh Kim Thanh",
        "role": "buongphong", "branch": "B9", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 10 --------------------------------------------#
    {
        "employee_id": "NV032", "code": "lt.ltttrinh", "name": "Lê Thị Thanh Trinh",
        "role": "letan", "branch": "B10", "shift": "CS"
    },
    {
        "employee_id": "NV033", "code": "lt.nvhoang", "name": "Nguyễn Văn Hoàng", 
        "role": "letan", "branch": "B10", "shift": "CT"
    },
    {
        "employee_id": "NV034", "code": "bp.nttuyet", "name": "Nguyễn Thị Tuyết",
        "role": "buongphong", "branch": "B10", "shift": "CS"
    },
    {
        "employee_id": "NV035", "code": "bp.ltkdung", "name": "Lê Thị Kim Dung",
        "role": "buongphong", "branch": "B10", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 11 --------------------------------------------#
    {
        "employee_id": "NV036", "code": "lt.btttruc", "name": "Bùi Thị Thanh Trúc",
        "role": "letan", "branch": "B11", "shift": "CS"
    },
    {
        "employee_id": "NV037", "code": "lt.kqchung", "name": "Khổng Quang Chung",
        "role": "letan", "branch": "B11", "shift": "CT"
    },
    {
        "employee_id": "NV038", "code": "bp.pthang", "name": "Phạm Thị Hằng",
        "role": "buongphong", "branch": "B11", "shift": "CS"
    },
    {
        "employee_id": "NV039", "code": "bp.lthyen", "name": "Lê Thị Hồng Yến",
        "role": "buongphong", "branch": "B11", "shift": "CS"
    },
    {
        "employee_id": "NV040", "code": "bp.ptuyen", "name": "Phạm Tố Uyên",
        "role": "buongphong", "branch": "B11", "shift": "CT"
    },
    {
        "employee_id": "NV041", "code": "bv.tvhoang", "name": "Tạ Văn Hoàng",
        "role": "baove", "branch": "B11", "shift": "CS"
    },
    {
        "employee_id": "NV042", "code": "bv.vqthai", "name": "Võ Quốc Thái",
        "role": "baove", "branch": "B11", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 12 --------------------------------------------#
    {
        "employee_id": "NV043", "code": "lt.tttrang", "name": "Tô Thảo Trang",
        "role": "letan", "branch": "B12", "shift": "CS"
    },
    {
        "employee_id": "NV044", "code": "lt.thdang", "name": "Trần Hải Đăng", 
        "role": "letan", "branch": "B12", "shift": "CT"
    },
    {
        "employee_id": "NV045", "code": "bp.ntatuyet", "name": "Nguyễn Thị Ánh Tuyết",
        "role": "buongphong", "branch": "B12", "shift": "CS"
    },
    {
        "employee_id": "NV046", "code": "bp.ntchinh", "name": "Nguyễn Thị Chinh",
        "role": "buongphong", "branch": "B12", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 14 --------------------------------------------#
    {
        "employee_id": "NV047", "code": "lt.ntkvy", "name": "Nguyễn Thị Khánh Vy",
        "role": "letan", "branch": "B14", "shift": "CS"
    },
    {
        "employee_id": "NV048", "code": "lt.nttrang", "name": "Ngô Thanh Trang",
        "role": "letan", "branch": "B14", "shift": "CT"
    },
    {
        "employee_id": "NV049", "code": "bp.tduyen", "name": "Thị Duyên",
        "role": "buongphong", "branch": "B14", "shift": "CS"
    },
    {
        "employee_id": "NV050", "code": "bp.ttgiau", "name": "Trần Thanh Giàu",
        "role": "buongphong", "branch": "B14", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 15 --------------------------------------------#
    {
        "employee_id": "NV051", "code": "lt.ltyoanh", "name": "Lê Thị Yến Oanh",
        "role": "letan", "branch": "B15", "shift": "CS"
    },
    {
        "employee_id": "NV052", "code": "lt.nntuan", "name": "Nguyễn Ngọc Tuấn",
        "role": "letan", "branch": "B15", "shift": "CT"
    },
    {
        "employee_id": "NV053", "code": "bp.ntmtruc", "name": "Nguyễn Thị Mỹ Trúc",
        "role": "buongphong", "branch": "B15", "shift": "CS"
    },
    {
        "employee_id": "NV054", "code": "bp.pttthao", "name": "Phan Thị Thu Thảo",
        "role": "buongphong", "branch": "B15", "shift": "CS"
    },
    {
        "employee_id": "NV055", "code": "bp.tttnhan", "name": "Trần Thị Thanh Nhãn",
        "role": "buongphong", "branch": "B15", "shift": "CT"
    },
    {
        "employee_id": "NV056", "code": "bv.bmnghia", "name": "Bùi Minh Nghĩa",
        "role": "baove", "branch": "B15", "shift": "CT"
    },
#--------------------------------------- BIN BIN HOTEL 16 --------------------------------------------#
    {
        "employee_id": "NV057", "code": "lt.tngan", "name": "Trần Nguyễn Gia Ân",
        "role": "letan", "branch": "B16", "shift": "CS"
    },
    {
        "employee_id": "NV058", "code": "lt.lhnghia", "name": "Lê Hữu Nghĩa",
        "role": "letan", "branch": "B16", "shift": "CT"
    },
    {
        "employee_id": "NV059", "code": "bp.lttam", "name": "Lê Thị Tám",
        "role": "buongphong", "branch": "B16", "shift": "CS"
    },
#--------------------------------------- BIN BIN HOTEL 17 (MỚI) --------------------------------------------#
    {
        "employee_id": "NV060", "code": "lt.ttmdiem", "name": "Trần Thị Mỹ Diễm",
        "role": "letan", "branch": "B17", "shift": "CS"
    },
    {
        "employee_id": "NV061", "code": "lt.nhtminh", "name": "Nguyễn Hoàng Thanh Minh",
        "role": "letan", "branch": "B17", "shift": "CT"
    },
    {
        "employee_id": "NV062", "code": "bp.ntdiep", "name": "Nguyễn Thị Điệp",
        "role": "buongphong", "branch": "B17", "shift": "CS"
    },
#--------------------------------------- LỄ TÂN CHẠY CA & DỰ BỊ --------------------------------------------#
    {
        "employee_id": "NV063", "code": "lt.lmtrung", "name": "Lê Minh Trung",
        "role": "letan", "branch": "DI DONG", "shift": None
    },
    {
        "employee_id": "NV064", "code": "lt.lhphuc", "name": "Lâm Hồng Phúc",
        "role": "letan", "branch": "DI DONG", "shift": None
    },
    {
        "employee_id": "NV065", "code": "lt.ndmluan", "name": "Nguyễn Đỗ Minh Luân",
        "role": "letan", "branch": "DI DONG", "shift": None
    },
    {
        "employee_id": "NV066", "code": "lt.tttin", "name": "Trần Thiện Tín",
        "role": "letan", "branch": "DI DONG", "shift": None
    },

#--------------------------------------- BUỒNG PHÒNG CHẠY CA --------------------------------------------#
    {
        "employee_id": "NV067", "code": "bp.ltphuc", "name": "Lê Trọng Phúc",
        "role": "buongphong", "branch": "DI DONG", "shift": None
    },
    {
        "employee_id": "NV068", "code": "bp.tnanh", "name": "Trần Ngọc Ánh",
        "role": "buongphong", "branch": "DI DONG", "shift": None
    },
    {
        "employee_id": "NV069", "code": "bp.vtdly", "name": "Võ Thị Diệu Lý",
        "role": "buongphong", "branch": "DI DONG", "shift": None
    },
#--------------------------------------- QUẢN LÍ VÀ KTV --------------------------------------------#
    {
        "employee_id": "NV070", "code": "ktv.ltphuc", "name": "Lê Trọng Phúc",
        "role": "ktv", "branch": "KTV", "shift": None
    },
    {
        "employee_id": "NV071", "code": "ktv.dthich", "name": "Danh Thích",
        "role": "ktv", "branch": "KTV", "shift": None
    },
    {
        "employee_id": "NV072", "code": "ql.tpnguyen", "name": "Trần Phát Nguyên",
        "role": "quanly", "branch": "QL", "shift": None
    },
    {
        "employee_id": "NV073", "code": "ql.tnanh", "name": "Trần Ngọc Ánh",
        "role": "quanly", "branch": "QL", "shift": None
    },
    {
        "employee_id": "NV074", "code": "ql.ndmluan", "name": "Nguyễn Đỗ Minh Luân",
        "role": "quanly", "branch": "QL", "shift": None
    },
#--------------------------------------- ADMIN & BAN GIÁM ĐỐC --------------------------------------------#
    {
        "employee_id": "NV999", "code": "ad.vminh", "name": "Vincent Minh",
        "role": "admin", "branch": "ADMIN", "shift": None
    },
    {
        "employee_id": "NV998", "code": "ad.tlinh", "name": "Thùy Linh",
        "role": "admin", "branch": "ADMIN", "shift": None
    },
    {
        "employee_id": "NV997", "code": "boss.sbin", "name": "Sếp Bin",
        "role": "boss", "branch": "BOSS", "shift": None
    },
]
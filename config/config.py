import os
DATABASE_URL = os.getenv("DATABASE_URL")

DATABASE_URL = "postgresql://admin_klo1_user:X0cwp6miJ1lVmcetAGrZpArXDkqxOW2w@dpg-d20e2p95pdvs73cepelg-a.oregon-postgres.render.com/admin_klo1"

# Cấu hình SMTP để gửi email
SMTP_CONFIG = {
    "host": "smtp.gmail.com",  # Truyền trực tiếp giá trị host
    "port": 587,  # Truyền trực tiếp giá trị port
    "username": "minhvincent.karma@gmail.com",  # Truyền trực tiếp giá trị username
    "password": "hfmhkiwuusryjlwr"  # Truyền trực tiếp giá trị mật khẩu (App Password)
}

# Email cảnh báo sẽ là địa chỉ email bạn đã cấu hình trong SMTP_USER
ALERT_EMAIL = "phatnguyencnttk3@gmail.com"  # Truyền trực tiếp email cảnh báo

import os
DATABASE_URL = os.getenv("DATABASE_URL")

DATABASE_URL = "postgresql://htbinbin_user:w9A5jWBBOxJ21x0nkisqNpc43uId29e3@dpg-d2gkraodl3ps73fdvm60-a/htbinbin_db"

# Cấu hình SMTP để gửi email
SMTP_CONFIG = {
    "host": "smtp.gmail.com",  # Truyền trực tiếp giá trị host
    "port": 587,  # Truyền trực tiếp giá trị port
    "username": "minhvincent.karma@gmail.com",  # Truyền trực tiếp giá trị username
    "password": "hfmhkiwuusryjlwr"  # Truyền trực tiếp giá trị mật khẩu (App Password)
}

# Email cảnh báo sẽ là địa chỉ email bạn đã cấu hình trong SMTP_USER
ALERT_EMAIL = "phatnguyencnttk3@gmail.com"  # Truyền trực tiếp email cảnh báo

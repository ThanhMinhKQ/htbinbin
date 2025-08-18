import aiosmtplib
from email.message import EmailMessage
from config import SMTP_CONFIG

async def send_alert_email(to_email, subject, body, html=False):
    """
    Gửi email cảnh báo quá hạn.
    """
    message = EmailMessage()
    message["From"] = SMTP_CONFIG["username"]
    message["To"] = to_email
    message["Subject"] = subject
    if html:
        message.set_content("Bạn cần email client hỗ trợ HTML để xem nội dung này.")
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)
    await aiosmtplib.send(
        message,
        hostname=SMTP_CONFIG["host"],
        port=SMTP_CONFIG["port"],
        username=SMTP_CONFIG["username"],
        password=SMTP_CONFIG["password"],
        use_tls=SMTP_CONFIG.get("use_tls", True),
    )

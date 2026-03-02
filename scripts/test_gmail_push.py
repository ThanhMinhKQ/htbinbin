#!/usr/bin/env python3
"""
Script test end-to-end Gmail Push Notification flow.
Không cần đợi Pub/Sub thật - tự trigger bằng historyId.

Cách dùng:
  1. Gửi email test từ mail cá nhân đến binbinhotel.ota@gmail.com
  2. Chạy script này: python3 scripts/test_gmail_push.py
"""

import sys
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

BASE_URL = "http://localhost:8000"
TOKEN = "binbin_pubsub_secret_2026"  # Phải khớp với PUBSUB_VERIFICATION_TOKEN trong .env

def get_status():
    """Lấy historyId hiện tại từ Gmail."""
    url = f"{BASE_URL}/api/ota/gmail/status"
    with urllib.request.urlopen(url) as r:
        return json.loads(r.read())

def trigger_webhook(history_id: str):
    """Giả lập Pub/Sub gửi notification."""
    import base64

    # Tạo payload giống Pub/Sub thật
    data = json.dumps({
        "emailAddress": "binbinhotel.ota@gmail.com",
        "historyId": history_id
    }).encode()
    data_b64 = base64.b64encode(data).decode()

    payload = json.dumps({
        "message": {
            "data": data_b64,
            "messageId": f"test-{int(time.time())}",
            "publishTime": "2026-03-02T07:00:00Z"
        },
        "subscription": "projects/otadashboard-02032026/subscriptions/ota-email-topic-sub"
    }).encode()

    req = urllib.request.Request(
        f"{BASE_URL}/api/ota/webhook/gmail?token={TOKEN}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

def main():
    print("=" * 55)
    print("  Gmail Push Notification - Test Tool")
    print("=" * 55)

    # Bước 1: Lấy historyId hiện tại (TRƯỚC khi gửi mail)
    print("\n📊 Đang lấy historyId hiện tại từ Gmail...")
    status = get_status()

    if not status.get("credentials_valid"):
        print("❌ Token không hợp lệ. Hãy chạy: python3 scripts/gmail_auth.py")
        sys.exit(1)

    old_history_id = status.get("current_history_id")
    print(f"   historyId hiện tại: {old_history_id}")

    # Bước 2: Đợi user gửi email
    print("\n📧 Bây giờ hãy gửi email test từ mail cá nhân đến:")
    print("   binbinhotel.ota@gmail.com")
    print("\n   📋 Nội dung email mẫu - copy và paste:")
    print("   " + "-" * 45)
    print("   Subject: [TEST] New Booking Confirmation - Booking.com")
    print("   Body:")
    print("     Booking Confirmation")
    print("     Booking ID: TEST-2024-999")
    print("     Guest: Nguyen Van A")
    print("     Hotel: Bin Bin Hotel 11")
    print("     Room: Superior Room")
    print("     Check-in: 2026-03-10")
    print("     Check-out: 2026-03-12")
    print("     Guests: 2 adults")
    print("     Total: 1,200,000 VND")
    print("   " + "-" * 45)

    input("\n⏎  Đã gửi email xong? Nhấn ENTER để tiếp tục...")

    # Bước 3: Lấy historyId mới (sau khi nhận mail)
    print("\n⏳ Đang đợi Gmail cập nhật historyId...")
    time.sleep(3)

    new_status = get_status()
    new_history_id = new_status.get("current_history_id")
    print(f"   historyId mới: {new_history_id}")

    if new_history_id == old_history_id:
        print("⚠️  historyId chưa thay đổi - email chưa đến hoặc hãy đợi thêm vài giây.")
        print("   Dùng historyId cũ để thử...")

    use_history_id = new_history_id or old_history_id

    # Bước 4: Trigger webhook
    print(f"\n🚀 Đang gửi trigger đến webhook (historyId={use_history_id})...")
    result = trigger_webhook(use_history_id)
    print(f"   Kết quả: {result}")

    if result.get("status") == "success":
        print("\n✅ Webhook đã nhận trigger!")
        print("   Background task đang xử lý email...")
        print("\n⏳ Đợi 5 giây rồi kiểm tra kết quả...")
        time.sleep(5)

        # Kiểm tra dashboard
        print("\n📋 Kiểm tra tại: http://localhost:8000/api/ota/dashboard")
        print("   Hoặc xem logs trong terminal uvicorn để thấy quá trình xử lý.")
    else:
        print(f"\n❌ Lỗi: {result}")

    print("\n" + "=" * 55)

if __name__ == "__main__":
    main()

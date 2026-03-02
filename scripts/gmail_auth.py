#!/usr/bin/env python3
"""
Script chạy 1 LẦN DUY NHẤT để xác thực Gmail OAuth2.

Cách dùng:
    1. Download file client_secrets.json từ Google Cloud Console
       (APIs & Services > Credentials > OAuth 2.0 Client > Download JSON)
       Đặt vào thư mục gốc của project (cùng level với file này)

    2. Chạy script:
       python scripts/gmail_auth.py

    3. Browser sẽ mở → Đăng nhập Gmail → Cho phép quyền truy cập
       → File gmail_token.json sẽ được tạo tự động

    4. (Nếu deploy lên server) Copy file gmail_token.json lên server
       đặt vào cùng thư mục gốc project

LƯU Ý QUAN TRỌNG:
    - KHÔNG commit gmail_token.json lên git!
    - Thêm vào .gitignore: gmail_token.json
    - Token sẽ tự động refresh, không cần chạy lại script này
"""

import os
import sys
from pathlib import Path

# Thêm root project vào PATH để import được app
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# Định nghĩa scopes cần thiết
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
]

# Đường dẫn files
CLIENT_SECRETS = ROOT / "client_secrets.json"
TOKEN_FILE = ROOT / "gmail_token.json"


def main():
    print("=" * 60)
    print("  Gmail OAuth2 Setup - BinBin Hotel OTA System")
    print("=" * 60)
    print()

    # Kiểm tra client_secrets.json
    if not CLIENT_SECRETS.exists():
        print(f"❌ Không tìm thấy file: {CLIENT_SECRETS}")
        print()
        print("Hướng dẫn lấy file client_secrets.json:")
        print("  1. Vào https://console.cloud.google.com/apis/credentials")
        print("  2. Tạo OAuth 2.0 Client ID (loại 'Desktop App')")
        print("  3. Download JSON → đặt tên thành 'client_secrets.json'")
        print(f"  4. Đặt vào: {CLIENT_SECRETS}")
        sys.exit(1)

    print(f"✅ Tìm thấy client_secrets.json")
    print(f"📧 Chuẩn bị xác thực Gmail account: binbinhotel.ota@gmail.com")
    print()
    print("🌐 Browser sẽ tự động mở để đăng nhập Gmail...")
    print("   (Nếu mở server SSH/headless, thêm flag --noauth_local_webserver)")
    print()

    try:
        # Khởi tạo OAuth flow
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CLIENT_SECRETS),
            scopes=SCOPES,
            redirect_uri='urn:ietf:wg:oauth:2.0:oob'  # Out-of-band cho desktop
        )

        # Chạy local server để nhận callback (mở browser tự động)
        creds = flow.run_local_server(
            port=8080,
            prompt='consent',
            access_type='offline',  # QUAN TRỌNG: phải có để lấy refresh_token
        )

        # Lưu token
        with open(TOKEN_FILE, 'w') as f:
            f.write(creds.to_json())

        print()
        print(f"✅ Xác thực thành công!")
        print(f"📄 Token đã lưu tại: {TOKEN_FILE}")
        print()

        # Verify bằng cách lấy profile
        service = build('gmail', 'v1', credentials=creds)
        profile = service.users().getProfile(userId='me').execute()
        email = profile.get('emailAddress')
        history_id = profile.get('historyId')

        print(f"📧 Email đã xác thực: {email}")
        print(f"📊 historyId hiện tại: {history_id}")
        print()
        print("📌 Bước tiếp theo:")
        print("   1. Đảm bảo .env đã có đủ GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GOOGLE_PUBSUB_TOPIC")
        print("   2. Khởi động server FastAPI")
        print("   3. Gọi POST /api/ota/gmail/watch để đăng ký Gmail watch")
        print()
        print("=" * 60)
        print("  Setup hoàn tất! OTA system đã sẵn sàng nhận email real-time.")
        print("=" * 60)

    except FileNotFoundError as e:
        print(f"❌ Lỗi: {e}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Đã huỷ bởi người dùng")
        sys.exit(0)
    except Exception as e:
        print(f"❌ Lỗi không xác định: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()

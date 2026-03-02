#!/usr/bin/env python3
"""
Script kiểm tra kết nối OTA Agent
Chạy script này để verify cấu hình .env đã đúng chưa
"""

import sys
import os

# Add app to path
sys.path.append(os.getcwd())

from app.services.ota_agent.listener import OTAListener
from app.services.ota_agent.extractor import OTAExtractor
from app.core.config import settings, logger

def print_header(text):
    """In header đẹp"""
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60)

def print_result(check_name, success, message=""):
    """In kết quả test"""
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{status} | {check_name}")
    if message:
        print(f"     └─ {message}")

def test_env_variables():
    """Kiểm tra các biến môi trường"""
    print_header("1. KIỂM TRA BIẾN MÔI TRƯỜNG")
    
    checks = {
        "GEMINI_API_KEY": settings.GEMINI_API_KEY,
        "IMAP_SERVER": settings.IMAP_SERVER,
        "IMAP_USER": settings.IMAP_USER,
        "IMAP_PASSWORD": settings.IMAP_PASSWORD,
        "OTA_SENDERS": settings.OTA_SENDERS,
    }
    
    all_pass = True
    for key, value in checks.items():
        if value and value != f"your_{key.lower()}_here" and "your_" not in str(value):
            print_result(key, True, f"Đã cấu hình")
        else:
            print_result(key, False, f"Chưa cấu hình hoặc còn giá trị mặc định")
            all_pass = False
    
    return all_pass

def test_gemini_connection():
    """Kiểm tra kết nối Gemini AI"""
    print_header("2. KIỂM TRA GEMINI AI API")
    
    try:
        extractor = OTAExtractor()
        
        if not extractor.client:
            print_result("Gemini Client", False, "API Key chưa được cấu hình")
            return False
        
        print_result("Gemini Client", True, "Client đã khởi tạo thành công")
        
        # Test với một email mẫu đơn giản
        print("\n📤 Đang test extraction với email mẫu...")
        
        sample_html = """
        <html>
        <body>
            <h1>Booking Confirmation</h1>
            <p>Booking ID: TEST123456</p>
            <p>Guest Name: Nguyen Van A</p>
            <p>Hotel: Bin Bin Hotel 17</p>
            <p>Check-in: 2026-02-15</p>
            <p>Check-out: 2026-02-17</p>
            <p>Room Type: Deluxe Double</p>
            <p>Guests: 2</p>
            <p>Total: 1500000 VND</p>
            <p>Payment: Prepaid by Visa</p>
        </body>
        </html>
        """
        
        result = extractor.extract_data(
            html_content=sample_html,
            sender="noreply@booking.com",
            subject="Booking Confirmation - TEST123456"
        )
        
        if result.get("status") == "SUCCESS":
            print_result("AI Extraction", True, "Trích xuất dữ liệu thành công")
            print("\n📊 Dữ liệu trích xuất được:")
            print(f"     - Booking ID: {result.get('external_id')}")
            print(f"     - Guest: {result.get('guest_name')}")
            print(f"     - Hotel: {result.get('hotel_name')}")
            print(f"     - Check-in: {result.get('check_in')}")
            print(f"     - Check-out: {result.get('check_out')}")
            return True
        else:
            print_result("AI Extraction", False, f"Lỗi: {result.get('error')}")
            return False
            
    except Exception as e:
        print_result("Gemini Connection", False, f"Lỗi: {str(e)}")
        return False

def test_imap_connection():
    """Kiểm tra kết nối IMAP"""
    print_header("3. KIỂM TRA KẾT NỐI EMAIL (IMAP)")
    
    try:
        listener = OTAListener()
        
        print(f"📧 Server: {listener.server}")
        print(f"📧 User: {listener.user}")
        print(f"📧 OTA Senders: {len(listener.ota_senders)} địa chỉ")
        
        print("\n🔌 Đang kết nối đến IMAP server...")
        
        if listener.verify_connection():
            print_result("IMAP Connection", True, "Kết nối thành công")
            
            # Thử fetch emails
            print("\n📬 Đang kiểm tra email chưa đọc...")
            emails = listener.fetch_unseen_emails(limit=5)
            
            print_result("Email Fetching", True, f"Tìm thấy {len(emails)} email từ OTA")
            
            if emails:
                print("\n📨 Danh sách email OTA:")
                for i, email in enumerate(emails, 1):
                    print(f"     {i}. From: {email['sender']}")
                    print(f"        Subject: {email['subject'][:60]}...")
                    print(f"        Date: {email['date']}")
            else:
                print("     ℹ️  Không có email chưa đọc từ OTA")
            
            return True
        else:
            print_result("IMAP Connection", False, "Không thể kết nối")
            print("\n💡 Gợi ý:")
            print("     - Kiểm tra IMAP_USER và IMAP_PASSWORD trong .env")
            print("     - Đảm bảo đã bật 2-Step Verification trên Gmail")
            print("     - Tạo App Password tại: https://myaccount.google.com/apppasswords")
            print("     - Kiểm tra IMAP có được bật trong Gmail Settings")
            return False
            
    except Exception as e:
        print_result("IMAP Connection", False, f"Lỗi: {str(e)}")
        logger.error(f"IMAP Error Details: {e}", exc_info=True)
        return False

def test_database_connection():
    """Kiểm tra kết nối database"""
    print_header("4. KIỂM TRA KẾT NỐI DATABASE")
    
    try:
        from app.db.session import SessionLocal
        from app.db.models import Branch, Booking
        
        db = SessionLocal()
        
        # Test query
        branch_count = db.query(Branch).count()
        booking_count = db.query(Booking).count()
        
        print_result("Database Connection", True, "Kết nối thành công")
        print(f"     - Số chi nhánh: {branch_count}")
        print(f"     - Số booking hiện có: {booking_count}")
        
        db.close()
        return True
        
    except Exception as e:
        print_result("Database Connection", False, f"Lỗi: {str(e)}")
        return False

def main():
    """Main function"""
    print("\n")
    print("╔════════════════════════════════════════════════════════════╗")
    print("║         OTA AGENT - KIỂM TRA CẤU HÌNH & KẾT NỐI          ║")
    print("╚════════════════════════════════════════════════════════════╝")
    
    results = {
        "Biến môi trường": test_env_variables(),
        "Gemini AI": test_gemini_connection(),
        "IMAP Email": test_imap_connection(),
        "Database": test_database_connection(),
    }
    
    # Tổng kết
    print_header("📊 TỔNG KẾT")
    
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    
    for name, result in results.items():
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\n🎯 Kết quả: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 HOÀN HẢO! Tất cả cấu hình đều OK!")
        print("✨ Hệ thống OTA Agent đã sẵn sàng hoạt động!")
        print("\n📌 Bước tiếp theo:")
        print("   1. Chạy: python -m app.services.ota_agent.integration")
        print("   2. Hoặc triển khai scheduler để tự động hóa")
    else:
        print("\n⚠️  CẦN KHẮC PHỤC:")
        print("   - Kiểm tra lại các bước cấu hình bị fail")
        print("   - Xem hướng dẫn trong file .env")
        print("   - Đọc tài liệu: ota_next_steps.md")
    
    print("\n" + "="*60 + "\n")
    
    return 0 if passed == total else 1

if __name__ == "__main__":
    sys.exit(main())

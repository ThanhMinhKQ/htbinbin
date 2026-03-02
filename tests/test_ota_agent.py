
from unittest.mock import MagicMock
import sys
import os

# Add app to path
sys.path.append(os.getcwd())

from app.services.ota_agent.extractor import OTAExtractor
from app.services.ota_agent.mapper import HotelMapper

def test_clean_html():
    print("Testing HTML Cleaner...")
    extractor = OTAExtractor()
    html = """
    <html>
        <head><title>Test</title><script>alert(1)</script></head>
        <body>
            <div style="color:red; font-size:12px" class="container">
                <p>Booking Confirmed</p>
                <img src="qc.png">
                <table>
                    <tr><td>Name:</td><td>Nguyen Van A</td></tr>
                </table>
            </div>
            <a href="link">Click here</a>
        </body>
    </html>
    """
    cleaned = extractor.clean_html(html)
    
    # Assertions
    if "<script>" in cleaned: print("FAIL: Script tag found")
    elif "style=" in cleaned: print("FAIL: Style attribute found")
    elif "<img" in cleaned: print("FAIL: Img tag found")
    elif "Booking Confirmed" not in cleaned: print("FAIL: Content missing")
    elif "Nguyen Van A" not in cleaned: print("FAIL: Table content missing")
    else: print("PASS: HTML Cleaner works as expected.")
    
    # print(f"DEBUG Cleaned content: {cleaned}")

def test_mapper_fuzzy():
    print("Testing Fuzzy Mapper...")
    # Mock DB
    mock_db = MagicMock()
    
    # Mock Branches behavior
    class MockBranch:
        def __init__(self, id, name):
            self.id = id
            self.name = name
            
    branches = [
        MockBranch(1, "Bin Bin Hotel 17"),
        MockBranch(2, "Bin Bin Hotel 9 - Quận 7"),
        MockBranch(3, "Bin Bin Hotel 7 - Trần Hưng Đạo")
    ]
    
    # Mock the query chain: db.query(Branch).all()
    mock_db.query.return_value.all.return_value = branches
    
    mapper = HotelMapper(mock_db)
    
    # Test Cases
    cases = [
        ("Bin Bin Hotel 17", 1), # Exact
        ("Khách sạn Bin Bin 17", 1), # Fuzzy
        ("Bin Bin 9", 2), # Short
        ("Bin Bin Hotel 7 Tran Hung Dao", 3), # No accents
        ("Sheraton Saigon", None) # No match
    ]
    
    all_pass = True
    for name, expected_id in cases:
        result = mapper.get_branch_id(name)
        if result != expected_id:
            print(f"FAIL: '{name}' mapped to {result}, expected {expected_id}")
            all_pass = False
        else:
            print(f"PASS: '{name}' -> {result}")
            
    if all_pass:
        print("PASS: All Mapper tests passed.")

if __name__ == "__main__":
    try:
        test_clean_html()
        print("-" * 20)
        test_mapper_fuzzy()
    except Exception as e:
        print(f"TEST ERROR: {e}")

from pathlib import Path


PAGE_LOAD = Path("app/api/inventory/page_load.py")


def test_page_load_import_amount_includes_completed_incoming_transfer_value():
    source = PAGE_LOAD.read_text(encoding="utf-8")

    assert "incoming_val" in source
    assert "FROM inventory_transfer_items" in source
    assert "import_amount = float(stats_row.imp_amount or 0) + float(stats_row.incoming_val or 0)" in source

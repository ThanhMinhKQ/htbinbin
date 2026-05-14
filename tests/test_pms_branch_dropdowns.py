import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://user:pass@localhost:5432/test")

import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.api.pms.pms_pages import _hotel_branch_number, _hotel_branch_sort_key


def branch(branch_code, name, id=1):
    return SimpleNamespace(branch_code=branch_code, name=name, id=id)


def test_hotel_branch_number_excludes_non_hotel_branches():
    assert _hotel_branch_number(branch("BOSS", "Ban giám đốc")) is None
    assert _hotel_branch_number(branch("ADMIN", "Admin")) is None
    assert _hotel_branch_number(branch("DI DONG", "Di động")) is None


def test_hotel_branch_number_accepts_bin_bin_hotel_names_and_numeric_codes():
    assert _hotel_branch_number(branch("B1", "Bin Bin Hotel 1")) == 1
    assert _hotel_branch_number(branch("B17", "Chi nhánh B17")) == 17
    assert _hotel_branch_number(branch("", "Bin Bin Hotel 3 - Near SECC")) == 3


def test_hotel_branch_sort_key_sorts_by_branch_number():
    branches = [
        branch("B10", "Bin Bin Hotel 10", 10),
        branch("B2", "Bin Bin Hotel 2", 2),
        branch("B1", "Bin Bin Hotel 1", 1),
    ]

    assert [b.name for b in sorted(branches, key=_hotel_branch_sort_key)] == [
        "Bin Bin Hotel 1",
        "Bin Bin Hotel 2",
        "Bin Bin Hotel 10",
    ]

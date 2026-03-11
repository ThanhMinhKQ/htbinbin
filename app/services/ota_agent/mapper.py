from thefuzz import process, fuzz
from sqlalchemy.orm import Session
from app.db.models import Branch
from app.core.config import logger
from typing import Optional, List, Dict

# Alias cứng: tên trên email OTA → tên chi nhánh trong DB
# Dùng khi fuzzy match không nhận ra được (tên thương hiệu khác hẳn tên hệ thống)
HOTEL_ALIASES: Dict[str, str] = {
    # Go2Joy thường dùng tên thương hiệu riêng
    # Mappings cho chi nhánh Bin Bin Hotel 10 (Mimosa)
    "bin bin mimosa":       "Bin Bin Hotel 10",
    "mimosa":               "Bin Bin Hotel 10",
    "binbin mimosa":        "Bin Bin Hotel 10",
    "bin bin mimosa hotel - near tan son nhat airport": "Bin Bin Hotel 10",
    "bin bin hotel 10 - mimosa airport (near tan son nhat airport)": "Bin Bin Hotel 10",
    "bin bin hotel 10 - mimosa near tan son nhat airport": "Bin Bin Hotel 10",
}

class HotelMapper:
    def __init__(self, db: Session):
        self.db = db
        self.branch_map = self._load_branches()

    def _load_branches(self) -> Dict[str, int]:
        branches = self.db.query(Branch).all()
        mapping = {}
        for b in branches:
            mapping[b.name] = b.id
        return mapping

    def get_branch_id(self, hotel_name: str) -> Optional[int]:
        """
        Tìm branch_id dựa trên tên khách sạn trong email.
        Ưu tiên: 1) Alias cứng → 2) Exact match → 3) Fuzzy match
        """
        if not hotel_name or not self.branch_map:
            return None

        # 1. Alias cứng (tên thương hiệu đặc biệt)
        alias_key = hotel_name.strip().lower()
        if alias_key in HOTEL_ALIASES:
            target_name = HOTEL_ALIASES[alias_key]
            branch_id = self.branch_map.get(target_name)
            if branch_id:
                logger.info(f"[OTA Mapper] Alias match: '{hotel_name}' -> '{target_name}' (id={branch_id})")
                return branch_id

        # 2. Exact match
        if hotel_name in self.branch_map:
            return self.branch_map[hotel_name]

        # 3. Fuzzy match
        choices = list(self.branch_map.keys())
        best_match = process.extractOne(hotel_name, choices, scorer=fuzz.token_sort_ratio)

        if best_match:
            match_name, score = best_match
            logger.info(f"[OTA Mapper] Fuzzy match: '{hotel_name}' -> '{match_name}' (Score: {score})")

            if score >= 50:
                return self.branch_map[match_name]
            else:
                logger.warning(f"[OTA Mapper] Low confidence match for '{hotel_name}'. Best: '{match_name}' ({score})")

        return None

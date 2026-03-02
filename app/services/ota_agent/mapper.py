from thefuzz import process, fuzz
from sqlalchemy.orm import Session
from app.db.models import Branch
from app.core.config import logger
from typing import Optional, List, Dict

class HotelMapper:
    def __init__(self, db: Session):
        self.db = db
        # Cache branches to handy dict {name: id}
        # In production with many branches, we might query DB or use Redis. 
        # For < 50 branches, memory is fine.
        self.branch_map = self._load_branches()

    def _load_branches(self) -> Dict[str, int]:
        branches = self.db.query(Branch).all()
        mapping = {}
        for b in branches:
            mapping[b.name] = b.id
            # Có thể thêm các biến thể tên nếu muốn (ví dụ Bin Bin Hotel 17 vs Khách sạn Bin Bin 17)
            # Tuy nhiên fuzzy search sẽ lo phần lớn việc này.
        return mapping

    def get_branch_id(self, hotel_name: str) -> Optional[int]:
        """
        Tìm branch_id dựa trên tên khách sạn trong email.
        Sử dụng Fuzzy Matching với ngưỡng 85.
        """
        if not hotel_name or not self.branch_map:
            return None
            
        # 1. Check exact match first
        if hotel_name in self.branch_map:
            return self.branch_map[hotel_name]
            
        # 2. Fuzzy match
        choices = list(self.branch_map.keys())
        best_match = process.extractOne(hotel_name, choices, scorer=fuzz.token_sort_ratio)
        
        if best_match:
            match_name, score = best_match
            logger.info(f"[OTA Mapper] Fuzzy match: '{hotel_name}' -> '{match_name}' (Score: {score})")
            
            # Threshold 50 để match được tên có nhiều mô tả thêm
            if score >= 50:
                return self.branch_map[match_name]
            else:
                logger.warning(f"[OTA Mapper] Low confidence match for '{hotel_name}'. Best: '{match_name}' ({score})")
        
        return None

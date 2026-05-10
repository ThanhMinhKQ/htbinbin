from thefuzz import process, fuzz  # type: ignore
from sqlalchemy.orm import Session  # type: ignore
from app.db.models import Branch  # type: ignore
from app.core.config import logger  # type: ignore
from typing import Optional, Dict
import re
import unicodedata
# Alias cứng: tên trên email OTA → tên chi nhánh trong DB
# Dùng khi fuzzy match không nhận ra được (tên thương hiệu khác hẳn tên hệ thống)
HOTEL_ALIASES: Dict[str, str] = {
    # Go2Joy thường dùng tên thương hiệu riêng
    # Mappings cho chi nhánh Bin Bin Hotel 10 (Mimosa)
    "bin bin mimosa":       "Bin Bin Hotel 10",
    "mimosa":               "Bin Bin Hotel 10",
    "binbin mimosa":        "Bin Bin Hotel 10",
    "bin bin mimosa near tan son nhat airport": "Bin Bin Hotel 10",
    "bin bin mimosa airport near tan son nhat airport": "Bin Bin Hotel 10",
    "bin bin 10 mimosa airport": "Bin Bin Hotel 10",
    "bin bin 10 mimosa near tan son nhat airport": "Bin Bin Hotel 10",
    "b10": "Bin Bin Hotel 10",

    # Mappings cho chi nhánh Bin Bin Hotel 1
    "bin bin 1 near rmit university d7": "Bin Bin Hotel 1",
    "near rmit university d7":           "Bin Bin Hotel 1",

    # Mappings cho chi nhánh Bin Bin Hotel 8
    "bin bin 8 near sunrise city district 7": "Bin Bin Hotel 8",
}

class HotelMapper:
    def __init__(self, db: Session):
        self.db = db
        self.branch_map = self._load_branches()
        # Map branch_code (e.g. "B2") -> branch_id for Website bookings
        self.branch_code_map = self._load_branch_codes()

    def _load_branches(self) -> Dict[str, int]:
        branches = self.db.query(Branch).all()
        mapping: Dict[str, int] = {}
        for b in branches:
            names = {b.name}
            code = getattr(b, "branch_code", None)
            branch_number = re.search(r"(\d+)\s*$", str(b.name or ""))
            if branch_number:
                n = branch_number.group(1)
                names.update({
                    f"Bin Bin Hotel {n}",
                    f"Khách sạn Bin Bin {n}",
                    f"Khach san Bin Bin {n}",
                    f"BinBin Hotel {n}",
                    f"Bin Bin {n}",
                    f"BinBin {n}",
                    f"BB {n}",
                    f"B{n}",
                    f"(B{n})",
                })
            if code:
                names.add(str(code))
                match = re.search(r"B\s*(\d+)", str(code), re.IGNORECASE)
                if match:
                    n = match.group(1)
                    names.update({
                        f"Bin Bin Hotel {n}",
                        f"BinBin Hotel {n}",
                        f"Bin Bin {n}",
                        f"BinBin {n}",
                        f"BB {n}",
                        f"B{n}",
                        f"(B{n})",
                    })
            for name in names:
                if name:
                    mapping[name] = b.id
        return mapping

    def _load_branch_codes(self) -> Dict[str, int]:
        """
        Build a mapping from branch_code (e.g. 'B2') to branch_id.
        Safe for tests that use simple mock Branch objects without branch_code.
        """
        branches = self.db.query(Branch).all()
        mapping: Dict[str, int] = {}
        for b in branches:
            code = getattr(b, "branch_code", None)
            if code:
                mapping[str(code).upper()] = b.id
        return mapping

    def get_branch_id(self, hotel_name: str) -> Optional[int]:
        """
        Tìm branch_id dựa trên tên khách sạn trong email.
        Ưu tiên: 1) Alias cứng → 2) Exact match → 3) Fuzzy match
        """
        if not hotel_name or not self.branch_map:
            return None

        clean_name = self._normalize_hotel_name(hotel_name)

        # 1. Alias cứng (tên thương hiệu đặc biệt)
        alias_key = clean_name.lower()
        if alias_key in HOTEL_ALIASES:
            target_name = HOTEL_ALIASES[alias_key]
            branch_id = self.branch_map.get(target_name)
            if branch_id:
                logger.info(f"[OTA Mapper] Alias match: '{hotel_name}' -> '{target_name}' (id={branch_id})")
                return branch_id

        # 2. Exact match
        for key, branch_id in self.branch_map.items():
            if self._normalize_hotel_name(key).lower() == alias_key:
                logger.info(f"[OTA Mapper] Normalized match: '{hotel_name}' -> '{key}' (id={branch_id})")
                return branch_id

        if "mimosa" in alias_key:
            branch_id = self.branch_code_map.get("B10")
            if branch_id:
                logger.info(f"[OTA Mapper] Mimosa match: '{hotel_name}' -> B10 (id={branch_id})")
                return branch_id

        code_match = re.search(r"\bB\s*(\d+)\b|\((B\s*\d+)\)|bin\s*bin(?:\s*hotel)?\s*(\d+)", str(hotel_name or ""), re.IGNORECASE)
        if not code_match:
            code_match = re.search(r"\bb\s*(\d+)\b|bin\s*bin\s*(\d+)", clean_name, re.IGNORECASE)
        if not code_match:
            code_match = re.search(r"^(\d+)\s+(?:near|gan|gần)\b", clean_name, re.IGNORECASE)
        if code_match:
            number = next((g for g in code_match.groups() if g), "")
            number = re.sub(r"\D", "", number)
            branch_id = self.branch_code_map.get(f"B{number}")
            if not branch_id:
                for key, candidate_id in self.branch_map.items():
                    if self._branch_number(key) == number:
                        branch_id = candidate_id
                        break
            if branch_id:
                logger.info(f"[OTA Mapper] Branch number match: '{hotel_name}' -> B{number} (id={branch_id})")
                return branch_id

        if not self._has_hotel_signal(clean_name):
            logger.info(f"[OTA Mapper] Skip fuzzy match for non-hotel text: '{hotel_name}'")
            return None

        # 3. Fuzzy match
        choices = list(self.branch_map.keys())
        best_match = process.extractOne(clean_name, choices, scorer=fuzz.token_sort_ratio)

        if best_match:
            match_name, score = best_match
            logger.info(f"[OTA Mapper] Fuzzy match: '{hotel_name}' -> '{match_name}' (Score: {score})")

            if score >= 50:
                return self.branch_map[match_name]
            else:
                logger.warning(f"[OTA Mapper] Low confidence match for '{hotel_name}'. Best: '{match_name}' ({score})")

        return None

    def _normalize_hotel_name(self, value: str) -> str:
        text = str(value or "").strip().lower()
        text = unicodedata.normalize("NFD", text)
        text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
        text = text.replace("đ", "d")
        text = re.sub(r"\((b\s*\d+)\)", r" \1 ", text, flags=re.IGNORECASE)
        text = re.sub(r"\([^)]*\)", " ", text)
        text = re.sub(r"\b(?:khach\s*san|hotel|property|branch|chi\s*nhanh)\b", " ", text)
        text = re.sub(r"[-_/|–—:,]+", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _branch_number(self, value: str) -> Optional[str]:
        match = re.search(r"(?:bin\s*bin(?:\s*hotel)?|khach\s*san\s*bin\s*bin|bb|\bB)\s*(\d+)\b", str(value or ""), re.IGNORECASE)
        if match:
            return match.group(1)
        match = re.search(r"(\d+)\s*$", str(value or "").strip())
        return match.group(1) if match else None

    def _has_hotel_signal(self, value: str) -> bool:
        return bool(re.search(r"\b(?:bin\s*bin|mimosa|khach\s*san|hotel|\bB\s*\d+)\b", str(value or ""), re.IGNORECASE))

    def get_branch_id_from_room_type(self, room_type: str) -> Optional[int]:
        """
        Website bookings encode the branch in the room type name,
        e.g. 'Superior Room (B2)' → branch_code 'B2' → Bin Bin Hotel 2.
        """
        if not room_type or not getattr(self, "branch_code_map", None):
            return None

        match = re.search(r"\((B\d+)\)", room_type, re.IGNORECASE)
        if not match:
            return None

        code = match.group(1).upper()
        branch_id = self.branch_code_map.get(code)
        if branch_id:
            logger.info(
                f"[OTA Mapper] Branch code match from room_type: "
                f"'{room_type}' -> '{code}' (id={branch_id})"
            )
        else:
            logger.warning(
                f"[OTA Mapper] Branch code '{code}' from room_type '{room_type}' "
                f"not found in DB."
            )
        return branch_id

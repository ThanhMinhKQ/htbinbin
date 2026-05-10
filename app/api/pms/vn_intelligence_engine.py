# app/api/pms/vn_intelligence_engine.py
"""
Fake Intelligence Engine for Vietnamese Address - v1.0
Core engine cho chuyển đổi địa chỉ cũ → mới sau sát nhập 1/7/2025

Features:
- Province Guard (chặn sai tỉnh)
- Normalize chuẩn tiếng Việt
- Alias System (auto-generate + manual)
- 2-Layer Matching (Exact/Alias + Fuzzy)
- Confidence Scoring
- Threshold Control
- Ambiguity Detection
- Learning System
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional
from functools import lru_cache

# ─── Logging ───────────────────────────────────────────────────────────────────
_logger = logging.getLogger("vn_intelligence")
_log_path = Path(__file__).resolve().parents[2] / "logs" / "vn_intelligence.log"
_log_path.parent.mkdir(exist_ok=True)

class _LogHandler(logging.FileHandler):
    def __init__(self):
        super().__init__(_log_path, encoding="utf-8", mode="a")
    
    def emit(self, record):
        record.msg = f"[{record.levelname}] {record.msg}"
        super().emit(record)

_logger.addHandler(_LogHandler())
_logger.setLevel(logging.DEBUG)

# ─── Data Paths ─────────────────────────────────────────────────────────────────
_BASE = Path(__file__).resolve().parents[2]
_INTELLIGENCE_FILE = _BASE / "static" / "data" / "vn_intelligence.json"
_WARD_MAP_FILE = _BASE / "static" / "data" / "vn_ward_map.json"
_LEARNING_FILE = _BASE / "static" / "data" / "vn_intelligence_learning.json"

# ─── Constants ──────────────────────────────────────────────────────────────────
VN_TZ = "Asia/Ho_Chi_Minh"

# Threshold constants
THRESHOLD_AUTO = 0.90    # > 0.9 → auto accept
THRESHOLD_CONFIRM = 0.70  # 0.7-0.9 → need confirmation
THRESHOLD_REJECT = 0.70   # < 0.7 → reject

# Province aliases (common typos & variants)
_PROVINCE_ALIASES = {
    # TP.HCM
    "tp hcm": "ho chi minh",
    "tp.hcm": "ho chi minh",
    "tphcm": "ho chi minh",
    "ho chi minh": "ho chi minh",
    "hcm": "ho chi minh",
    "tp. hồ chí minh": "ho chi minh",
    # TP.HN
    "tp hn": "ha noi",
    "tp.hn": "ha noi",
    "hanoi": "ha noi",
    "hn": "ha noi",
    "tp. hà nội": "ha noi",
    # Other major TPs
    "da nang": "da nang",
    "đà nẵng": "da nang",
    "can tho": "can tho",
    "cần thơ": "can tho",
    "hai phong": "hai phong",
    "hải phòng": "hai phong",
    # Short names
    "tp đà nẵng": "da nang",
    "tp cần thơ": "can tho",
    "tp hải phòng": "hai phong",
    "tp hà nội": "ha noi",
}

# Admin prefix removal
_ADMIN_PREFIXES = (
    "thi tran ", "thi xa ", "thanh pho ", "thành phố ",
    "tinh ", "tỉnh ", "tp ", "tp. ",
    "quan ", "quận ", "huyen ", "huyện ",
    "thị xã ", "thị trấn ", "tx. ",
    "phuong ", "phường ", "xa ", "xã ",
)

# Prefix patterns for matching
_SHORTEN_PREFIXES = {
    "phường": "p",
    "xã": "x",
    "quận": "q",
    "huyện": "h",
    "thành phố": "tp",
    "tỉnh": "t",
}

# ─── Data Classes ────────────────────────────────────────────────────────────────

@dataclass
class MatchResult:
    """Kết quả matching cho một ward."""
    new_ward: str
    new_province: str
    new_province_short: str
    internal_code: str = ""
    confidence: float = 0.0
    match_level: str = ""  # "exact", "alias", "fuzzy"
    suggestions: list = field(default_factory=list)
    ambiguous: bool = False
    auto_action: str = "confirm"  # "auto", "confirm", "reject"
    note: str = ""

@dataclass
class ConversionInput:
    """Input cho conversion engine."""
    ward: str
    district: str = ""
    province: str = ""
    province_raw: str = ""

# ─── Normalize Functions ────────────────────────────────────────────────────────

def _strip_diacritics(s: str) -> str:
    """Remove Vietnamese diacritics (NFKD + strip combining chars)."""
    if not s:
        return ""
    s = s.replace('đ', 'd')
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c))

def _strip_admin_prefix(s: str) -> str:
    """Strip admin prefixes like Phường, Quận, Tỉnh, etc."""
    if not s:
        return ""
    s = s.lower()
    for prefix in _ADMIN_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()

def _normalize_text(s: str) -> str:
    """Full normalization: lowercase, strip diacritics, remove prefixes, clean chars."""
    if not s:
        return ""
    s = str(s).strip().lower()
    s = _strip_diacritics(s)
    s = _strip_admin_prefix(s)
    # Remove extra chars
    s = re.sub(r"[.,\-/_]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()

def _extract_number(s: str) -> Optional[int]:
    """Extract number from ward name like 'Phường 7' → 7."""
    match = re.search(r'\d+', s)
    return int(match.group()) if match else None

def _generate_short_aliases(ward_name: str) -> list[str]:
    """Generate short aliases for a ward name."""
    aliases = []
    if not ward_name:
        return aliases
    
    stripped = _strip_admin_prefix(ward_name)
    num = _extract_number(stripped)
    
    # Shorten prefixes
    for full, short in _SHORTEN_PREFIXES.items():
        if ward_name.lower().startswith(full):
            if num is not None:
                aliases.append(f"{short}{num}")
                aliases.append(f"{short} {num}")
                aliases.append(f"{full} {num}")  # keep full prefix too
    
    # Remove prefix and try short forms
    if num is not None:
        aliases.append(str(num))
        aliases.append(f"{num}")
    
    return list(set(aliases))

# ─── Intelligence Engine Class ──────────────────────────────────────────────────

class VNIntelligenceEngine:
    """
    Core engine cho address intelligence.
    Load data vào RAM, lookup O(1), fuzzy fallback.
    """
    
    def __init__(self):
        self._loaded = False
        self._data: dict = {}
        self._ward_lookup: dict = {}  # normalized_ward → list of (prov, ward, internal_code)
        self._alias_lookup: dict = {}  # alias → (prov, ward)
        self._fuzzy_index: dict = {}  # prov → list of (normalized_ward, original)
        self._learning_data: dict = {"aliases": {}, "usage": {}, "corrections": {}}
        
    def load(self):
        """Load all data into RAM."""
        if self._loaded:
            return
        
        # Load main intelligence data
        if _INTELLIGENCE_FILE.exists():
            with open(_INTELLIGENCE_FILE, encoding="utf-8") as f:
                self._data = json.load(f)
        
        # Build lookup indexes
        self._build_indexes()
        
        # Load learning data
        self._load_learning()
        
        self._loaded = True
        _logger.info(f"Intelligence Engine loaded: {len(self._ward_lookup)} wards, {len(self._alias_lookup)} aliases")
    
    def _build_indexes(self):
        """Build O(1) lookup indexes from data."""
        self._ward_lookup.clear()
        self._alias_lookup.clear()
        self._fuzzy_index.clear()
        
        for prov, wards in self._data.items():
            prov_norm = _normalize_text(prov)
            
            # Build fuzzy index for this province
            self._fuzzy_index[prov_norm] = []
            
            for ward in wards:
                # Parse internal code if present (format: "WardName|CODE")
                internal_code = ""
                ward_name = ward
                if "|" in ward:
                    parts = ward.rsplit("|", 1)
                    ward_name = parts[0]
                    internal_code = parts[1]
                
                ward_norm = _normalize_text(ward_name)
                
                # Ward lookup (ward_norm → list of matches)
                if ward_norm not in self._ward_lookup:
                    self._ward_lookup[ward_norm] = []
                self._ward_lookup[ward_norm].append((prov_norm, ward_name, internal_code))
                
                # Fuzzy index
                self._fuzzy_index[prov_norm].append((ward_norm, ward_name, internal_code))
                
                # Generate and store aliases
                aliases = _generate_short_aliases(ward_name)
                for alias in aliases:
                    alias_norm = _normalize_text(alias)
                    if alias_norm not in self._alias_lookup:
                        self._alias_lookup[alias_norm] = []
                    self._alias_lookup[alias_norm].append((prov_norm, ward_name, internal_code))
    
    def _load_learning(self):
        """Load learned aliases and corrections."""
        if _LEARNING_FILE.exists():
            try:
                with open(_LEARNING_FILE, encoding="utf-8") as f:
                    self._learning_data = json.load(f)
                
                # Merge learned aliases into lookup
                for alias, target in self._learning_data.get("aliases", {}).items():
                    alias_norm = _normalize_text(alias)
                    target_norm = _normalize_text(target)
                    if target_norm in self._ward_lookup:
                        for prov, ward, code in self._ward_lookup[target_norm]:
                            if alias_norm not in self._alias_lookup:
                                self._alias_lookup[alias_norm] = []
                            self._alias_lookup[alias_norm].append((prov, ward, code))
            except Exception as e:
                _logger.warning(f"Could not load learning data: {e}")
    
    def save_learning(self):
        """Save learned aliases to disk."""
        try:
            with open(_LEARNING_FILE, "w", encoding="utf-8") as f:
                json.dump(self._learning_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            _logger.error(f"Could not save learning data: {e}")
    
    def learn_alias(self, alias: str, target_ward: str, target_province: str):
        """Learn a new alias from user selection."""
        alias_norm = _normalize_text(alias)
        target_norm = _normalize_text(target_ward)
        prov_norm = _normalize_text(target_province)
        
        if "aliases" not in self._learning_data:
            self._learning_data["aliases"] = {}
        
        self._learning_data["aliases"][alias] = target_ward
        
        if "usage" not in self._learning_data:
            self._learning_data["usage"] = {}
        
        key = f"{alias_norm}|{prov_norm}"
        self._learning_data["usage"][key] = self._learning_data["usage"].get(key, 0) + 1
        
        # Add to lookup
        if target_norm in self._ward_lookup:
            if alias_norm not in self._alias_lookup:
                self._alias_lookup[alias_norm] = []
            for prov, ward, code in self._ward_lookup[target_norm]:
                if prov == prov_norm:
                    self._alias_lookup[alias_norm].append((prov, ward, code))
        
        self.save_learning()
        _logger.info(f"Learned alias: '{alias}' → '{target_ward}' in {target_province}")
    
    def record_correction(self, input_ward: str, wrong_result: str, correct_ward: str, correct_province: str):
        """Record when user corrects a wrong suggestion."""
        if "corrections" not in self._learning_data:
            self._learning_data["corrections"] = {}
        
        key = f"{_normalize_text(input_ward)}|{_normalize_text(wrong_result)}"
        if key not in self._learning_data["corrections"]:
            self._learning_data["corrections"][key] = []
        
        self._learning_data["corrections"][key].append({
            "correct": f"{correct_ward}|{correct_province}",
            "count": len(self._learning_data["corrections"][key]) + 1
        })
        
        self.save_learning()
    
    def convert(self, input_data: ConversionInput) -> MatchResult:
        """
        Main conversion method với Province Guard + 2-Layer Matching.
        
        1. Province Guard: Always parse province first, reject if result differs
        2. Layer 1: Exact/Alias match (O(1) dict lookup)
        3. Layer 2: Fuzzy match (fallback, limited to province scope)
        4. Confidence scoring + threshold control
        5. Ambiguity detection
        """
        self.load()
        
        # Normalize input
        ward_norm = _normalize_text(input_data.ward)
        district_norm = _normalize_text(input_data.district)
        prov_norm = _normalize_text(input_data.province)
        
        if not ward_norm:
            return MatchResult(
                new_ward=input_data.ward,
                new_province=input_data.province,
                new_province_short="",
                confidence=0.0,
                match_level="none",
                auto_action="reject",
                note="Ward name is empty"
            )
        
        # Resolve province alias
        prov_lookup = _PROVINCE_ALIASES.get(prov_norm, prov_norm)
        
        # ── Layer 1: Exact Match ────────────────────────────────────────────────
        result = self._layer1_exact_match(ward_norm, prov_lookup)
        if result and result.confidence >= THRESHOLD_AUTO:
            return result
        
        # ── Layer 2: Alias Match ────────────────────────────────────────────────
        result = self._layer2_alias_match(ward_norm, prov_lookup)
        if result and result.confidence >= THRESHOLD_AUTO:
            return result
        
        # ── Layer 3: Fuzzy Match (limited to province) ──────────────────────────
        result = self._layer3_fuzzy_match(ward_norm, prov_lookup)
        if result:
            return result
        
        # ── Layer 4: Fuzzy Match (nationwide, last resort) ────────────────────
        result = self._layer3_fuzzy_match(ward_norm, None)
        if result:
            result.note = "Matched nationwide (province not found)"
            return result
        
        # ── No match: reject ───────────────────────────────────────────────────
        _logger.warning(f"No match found: ward='{input_data.ward}', prov='{input_data.province}'")
        return MatchResult(
            new_ward=input_data.ward,
            new_province=input_data.province,
            new_province_short="",
            confidence=0.0,
            match_level="none",
            auto_action="reject",
            note="Không tìm thấy ánh xạ trong cơ sở dữ liệu"
        )
    
    def _layer1_exact_match(self, ward_norm: str, prov_filter: Optional[str]) -> Optional[MatchResult]:
        """Layer 1: Exact match in ward_lookup."""
        matches = self._ward_lookup.get(ward_norm, [])
        
        if not matches:
            return None
        
        # Filter by province if specified
        if prov_filter:
            matches = [(p, w, c) for p, w, c in matches if p == prov_filter]
        
        if not matches:
            return None
        
        if len(matches) == 1:
            prov, ward, code = matches[0]
            return MatchResult(
                new_ward=ward,
                new_province=self._get_display_province(prov),
                new_province_short=prov,
                internal_code=code,
                confidence=1.0,
                match_level="exact",
                auto_action="auto",
                note="Exact match"
            )
        
        # Multiple exact matches → ambiguous
        return self._make_ambiguous_result(matches, "exact")
    
    def _layer2_alias_match(self, ward_norm: str, prov_filter: Optional[str]) -> Optional[MatchResult]:
        """Layer 2: Alias match in alias_lookup."""
        matches = self._alias_lookup.get(ward_norm, [])
        
        if not matches:
            return None
        
        # Filter by province if specified
        if prov_filter:
            matches = [(p, w, c) for p, w, c in matches if p == prov_filter]
        
        if not matches:
            return None
        
        if len(matches) == 1:
            prov, ward, code = matches[0]
            return MatchResult(
                new_ward=ward,
                new_province=self._get_display_province(prov),
                new_province_short=prov,
                internal_code=code,
                confidence=0.95,
                match_level="alias",
                auto_action="auto",
                note="Matched via alias"
            )
        
        # Multiple alias matches → ambiguous
        return self._make_ambiguous_result(matches, "alias")
    
    def _layer3_fuzzy_match(self, ward_norm: str, prov_filter: Optional[str]) -> Optional[MatchResult]:
        """Layer 3: Fuzzy match using rapidfuzz (limited scope)."""
        try:
            from rapidfuzz import fuzz, process
        except ImportError:
            _logger.warning("rapidfuzz not installed, fuzzy matching disabled")
            return None
        
        candidates = []
        
        if prov_filter:
            # Match only within province (fast)
            if prov_filter in self._fuzzy_index:
                candidates = [
                    (f"{p}|{w}", w, c) 
                    for p, w, c in self._fuzzy_index[prov_filter]
                ]
        else:
            # Match nationwide (slow, last resort)
            for prov_wards in self._fuzzy_index.values():
                for p, w, c in prov_wards:
                    candidates.append((f"{p}|{w}", w, c))
        
        if not candidates:
            return None
        
        # Fuzzy search
        choices = [c[0] for c in candidates]
        results = process.extract(
            ward_norm, 
            choices, 
            scorer=fuzz.ratio, 
            limit=5
        )
        
        if not results:
            return None
        
        # Check if results are good enough
        best_score = results[0][1] / 100.0
        
        if best_score < 0.6:
            return None  # Too low similarity
        
        # Filter by minimum threshold
        valid_results = [(r[0], r[1], r[2]) for r in results if r[1] >= 60]
        
        if not valid_results:
            return None
        
        # Check for ambiguity (scores too close)
        if len(valid_results) >= 2:
            score_diff = valid_results[0][1] - valid_results[1][1]
            if score_diff < 10:
                # Ambiguous
                matches = []
                for r in valid_results[:3]:
                    parts = r[0].split("|", 1)
                    prov = parts[0]
                    ward = r[2]
                    code = r[3] if len(r) > 3 else ""
                    matches.append((prov, ward, code))
                
                return self._make_ambiguous_result(matches, "fuzzy")
        
        # Single best result
        best = valid_results[0]
        parts = best[0].split("|", 1)
        prov = parts[0]
        ward = best[2]
        code = best[3] if len(best) > 3 else ""
        
        # Check province guard
        if prov_filter and prov != prov_filter:
            _logger.warning(f"Province guard rejected: expected={prov_filter}, got={prov}")
            return None
        
        confidence = self._calculate_confidence(best[1] / 100.0, "fuzzy")
        
        return MatchResult(
            new_ward=ward,
            new_province=self._get_display_province(prov),
            new_province_short=prov,
            internal_code=code,
            confidence=confidence,
            match_level="fuzzy",
            auto_action=self._get_auto_action(confidence),
            note=f"Fuzzy match ({best[1]}% similarity)"
        )
    
    def _make_ambiguous_result(self, matches: list, match_level: str) -> MatchResult:
        """Create ambiguous result with top 3 suggestions."""
        suggestions = []
        for prov, ward, code in matches[:3]:
            suggestions.append({
                "ward": ward,
                "province": self._get_display_province(prov),
                "province_short": prov,
                "internal_code": code
            })
        
        return MatchResult(
            new_ward=suggestions[0]["ward"],
            new_province=suggestions[0]["province"],
            new_province_short=suggestions[0]["province_short"],
            internal_code=suggestions[0]["internal_code"],
            confidence=0.5,
            match_level=match_level,
            suggestions=suggestions,
            ambiguous=True,
            auto_action="confirm",
            note=f"Nhiều kết quả ({len(matches)}), cần xác nhận"
        )
    
    def _calculate_confidence(self, similarity: float, match_level: str) -> float:
        """Calculate confidence score based on similarity and match level."""
        base_score = similarity
        
        # Bonus for exact/alias vs fuzzy
        level_bonus = {
            "exact": 0.0,
            "alias": 0.02,
            "fuzzy": 0.0
        }
        
        confidence = min(base_score + level_bonus.get(match_level, 0), 1.0)
        return round(confidence, 2)
    
    def _get_auto_action(self, confidence: float) -> str:
        """Determine auto action based on confidence threshold."""
        if confidence >= THRESHOLD_AUTO:
            return "auto"
        elif confidence >= THRESHOLD_CONFIRM:
            return "confirm"
        else:
            return "reject"
    
    def _get_display_province(self, prov_norm: str) -> str:
        """Get display name for normalized province."""
        display_map = {
            "ho chi minh": "TP. Hồ Chí Minh",
            "ha noi": "TP. Hà Nội",
            "da nang": "TP. Đà Nẵng",
            "can tho": "TP. Cần Thơ",
            "hai phong": "TP. Hải Phòng",
            "hue": "Thành phố Huế",
        }
        
        # Check if it's a short name in our data
        for short_name, full_name in display_map.items():
            if prov_norm == short_name:
                return full_name
        
        # Capitalize for display
        return prov_norm.title()
    
    def get_suggestions(self, partial: str, province: str = "", limit: int = 5) -> list:
        """Get suggestions for partial ward name input."""
        self.load()
        
        partial_norm = _normalize_text(partial)
        if not partial_norm:
            return []
        
        prov_filter = _PROVINCE_ALIASES.get(_normalize_text(province), _normalize_text(province))
        
        suggestions = []
        
        # Check ward_lookup
        for ward_norm, matches in self._ward_lookup.items():
            if ward_norm.startswith(partial_norm) or partial_norm in ward_norm:
                for prov, ward, code in matches:
                    if prov_filter and prov != prov_filter:
                        continue
                    suggestions.append({
                        "ward": ward,
                        "province": self._get_display_province(prov),
                        "internal_code": code
                    })
                    if len(suggestions) >= limit:
                        return suggestions
        
        return suggestions[:limit]

# ─── Global Engine Instance ──────────────────────────────────────────────────────
_engine: Optional[VNIntelligenceEngine] = None

def get_engine() -> VNIntelligenceEngine:
    """Get or create global engine instance."""
    global _engine
    if _engine is None:
        _engine = VNIntelligenceEngine()
    return _engine

# ─── Convenience Functions ──────────────────────────────────────────────────────

def intelligent_convert(
    ward: str,
    province: str,
    district: str = ""
) -> dict:
    """
    Convenience function for intelligent conversion.
    
    Returns dict with:
    - new_ward, new_province, new_province_short
    - internal_code, confidence, match_level
    - suggestions (for ambiguous cases)
    - ambiguous, auto_action, note
    """
    engine = get_engine()
    
    input_data = ConversionInput(
        ward=ward,
        district=district,
        province=province
    )
    
    result = engine.convert(input_data)
    
    return {
        "new_ward": result.new_ward,
        "new_province": result.new_province,
        "new_province_short": result.new_province_short,
        "internal_code": result.internal_code,
        "confidence": result.confidence,
        "match_level": result.match_level,
        "suggestions": result.suggestions,
        "ambiguous": result.ambiguous,
        "auto_action": result.auto_action,
        "note": result.note,
        "matched": result.confidence > 0
    }

def learn_from_selection(alias: str, target_ward: str, target_province: str):
    """Learn alias from user selection."""
    get_engine().learn_alias(alias, target_ward, target_province)

def record_correction(input_ward: str, wrong_result: str, correct_ward: str, correct_province: str):
    """Record correction when user fixes a wrong suggestion."""
    get_engine().record_correction(input_ward, wrong_result, correct_ward, correct_province)

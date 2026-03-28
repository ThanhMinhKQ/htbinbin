"""
app/api/pms/vn_address.py
Backend API for Vietnamese address management.

Data sources:
- app/static/data/vn_new_wards.json   → new 34 provinces + their new wards (from Excel)
- app/static/data/vn_ward_map.json    → old ward name (normalized) → (new_province, new_ward)

Endpoints:
- GET  /api/vn-address/new-provinces          → 34 new province names
- GET  /api/vn-address/new-wards/{prov}       → ward list for a new province
- GET  /api/vn-address/old-provinces          → 63 old provinces (proxied)
- GET  /api/vn-address/old-districts/{code}   → districts for old province (proxied)
- GET  /api/vn-address/old-wards/{code}       → wards for old district (proxied)
- POST /api/vn-address/convert                → old address → new address (deep mapping)
"""
from __future__ import annotations

import json
import ssl
import unicodedata
import urllib.request
from pathlib import Path
from functools import lru_cache

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/vn-address", tags=["VN Address"])

# ─── Data paths ───────────────────────────────────────────────────────────────
_BASE = Path(__file__).resolve().parent.parent.parent  # app/
_NEW_WARDS_FILE   = _BASE / "static" / "data" / "vn_new_wards.json"
_WARD_MAP_FILE   = _BASE / "static" / "data" / "vn_ward_map.json"
_OLD_PROV_FILE   = _BASE / "static" / "data" / "vn_old_provinces.json"
_OLD_API         = "https://provinces.open-api.vn/api"

# ─── Province alias: Excel short names → canonical normalized key ─────────────
_PROV_ALIAS = {
    'hcm':        'ho chi minh',  # Excel "TP HCM" after stripping "tp "
    'vinh phuce': 'vinh phuc',    # Typo in Excel "Vĩnh Phức"
}


def _norm_ward(s: str) -> str:
    """
    Normalize ward name: replace đ→d, strip diacritics, strip admin prefix.
    Identical to the Python rebuild script.
    """
    import re as _re
    if not s:
        return ""
    s = str(s).strip().lower()
    s = _re.sub(r'\s*\(.*?\)', '', s)   # remove disambiguation hints
    s = s.replace('đ', 'd')             # NFKD misses Vietnamese đ
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for prefix in (
        "thi tran ", "thi xa ", "thanh pho ", "quan ",
        "phuong ", "huyen ", "tinh ", "xa ",
    ):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s.strip()


def _norm_prov(s: str) -> str:
    """
    Normalize province name: replace đ→d, strip diacritics, strip admin prefix,
    apply alias map.  Identical to the Python rebuild script.
    """
    if not s:
        return ""
    s = str(s).strip().lower()
    s = s.replace('đ', 'd')
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    for prefix in ('thanh pho ', 'tinh ', 'thi xa ', 'tp '):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    s = s.strip()
    return _PROV_ALIAS.get(s, s)


def _compound_key(old_prov: str, old_ward: str) -> str:
    """Build compound lookup key: 'prov_norm::ward_norm'."""
    return f"{_norm_prov(old_prov)}::{_norm_ward(old_ward)}"

# ─── Load JSON data (lazy, cached) ────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_new_wards() -> dict[str, list[str]]:
    """Returns {province_short: [ward_name, ...]}"""
    if _NEW_WARDS_FILE.exists():
        with open(_NEW_WARDS_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}

@lru_cache(maxsize=1)
def _load_ward_map() -> dict[str, tuple[str, str]]:
    """Returns {normalized_old_ward: [new_province, new_ward]}"""
    if _WARD_MAP_FILE.exists():
        with open(_WARD_MAP_FILE, encoding="utf-8") as f:
            data = json.load(f)
        # Values come as lists from JSON (tuples aren't JSON-serializable)
        return {k: (v[0], v[1]) for k, v in data.items()}
    return {}

# ─── Province display name mapping ───────────────────────────────────────────
# Excel uses short names; map to full official display names for UI

PROV_DISPLAY = {
    "An Giang":    "Tỉnh An Giang",
    "Bắc Ninh":    "Tỉnh Bắc Ninh",
    "Cao Bằng":    "Tỉnh Cao Bằng",
    "Cà Mau":      "Tỉnh Cà Mau",
    "Cần Thơ":     "Thành phố Cần Thơ",
    "Gia Lai":     "Tỉnh Gia Lai",
    "Huế":         "Thành phố Huế",
    "Hà Nội":      "Thành phố Hà Nội",
    "Hà Tĩnh":     "Tỉnh Hà Tĩnh",
    "Hưng Yên":    "Tỉnh Hưng Yên",
    "Hải Phòng":   "Thành phố Hải Phòng",
    "Khánh Hòa":   "Tỉnh Khánh Hòa",
    "Lai Châu":    "Tỉnh Lai Châu",
    "Lào Cai":     "Tỉnh Lào Cai",
    "Lâm Đồng":    "Tỉnh Lâm Đồng",
    "Lạng Sơn":    "Tỉnh Lạng Sơn",
    "Nghệ An":     "Tỉnh Nghệ An",
    "Ninh Bình":   "Tỉnh Ninh Bình",
    "Phú Thọ":     "Tỉnh Phú Thọ",
    "Quảng Ngãi":  "Tỉnh Quảng Ngãi",
    "Quảng Ninh":  "Tỉnh Quảng Ninh",
    "Quảng Trị":   "Tỉnh Quảng Trị",
    "Sơn La":      "Tỉnh Sơn La",
    "TP HCM":      "Thành phố Hồ Chí Minh",
    "Thanh Hóa":   "Tỉnh Thanh Hóa",
    "Thái Nguyên": "Tỉnh Thái Nguyên",
    "Tuyên Quang": "Tỉnh Tuyên Quang",
    "Tây Ninh":    "Tỉnh Tây Ninh",
    "Vĩnh Long":   "Tỉnh Vĩnh Long",
    "Điện Biên":   "Tỉnh Điện Biên",
    "Đà Nẵng":     "Thành phố Đà Nẵng",
    "Đắk Lắk":     "Tỉnh Đắk Lắk",
    "Đồng Nai":    "Tỉnh Đồng Nai",
    "Đồng Tháp":   "Tỉnh Đồng Tháp",
}
# Reverse: display → short
_DISPLAY_TO_SHORT = {v: k for k, v in PROV_DISPLAY.items()}

# ─── Old API proxy (server-side, bypasses browser SSL issues) ─────────────────

def _fetch_old(path: str):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(
            f"{_OLD_API}{path}", timeout=10, context=ctx
        ) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"error": str(e)}


@lru_cache(maxsize=1)
def _load_old_provinces() -> list[dict]:
    """Load 63 old provinces from local cache (authoritative, no external deps)."""
    if _OLD_PROV_FILE.exists():
        with open(_OLD_PROV_FILE, encoding="utf-8") as f:
            return json.load(f)
    return []

# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("/new-provinces")
async def get_new_provinces():
    """Return 34 new provinces (short→display name) from curated Excel data."""
    data = _load_new_wards()
    provinces = [
        {"short": k, "name": PROV_DISPLAY.get(k, k)}
        for k in sorted(data.keys())
    ]
    return JSONResponse({"provinces": provinces})


@router.get("/new-wards/{province_short:path}")
async def get_new_wards(province_short: str):
    """Return wards for a new province from curated Excel data."""
    data = _load_new_wards()
    # Try exact and URL-decoded variants
    wards = data.get(province_short) or data.get(province_short.replace("%20", " "))
    # Also try via display name
    if wards is None:
        short = _DISPLAY_TO_SHORT.get(province_short)
        if short:
            wards = data.get(short)
    if wards is None:
        return JSONResponse({"wards": []})
    return JSONResponse({"wards": sorted(wards)})


@router.get("/old-provinces")
async def get_old_provinces():
    cached = _load_old_provinces()
    if cached:
        return JSONResponse(cached)
    data = _fetch_old("/p/")
    if isinstance(data, list):
        return JSONResponse([{"name": p["name"], "code": p["code"]} for p in data])
    return JSONResponse({"error": "Không lấy được dữ liệu tỉnh/thành"}, status_code=502)


@router.get("/old-districts/{province_code}")
async def get_old_districts(province_code: int):
    data = _fetch_old(f"/p/{province_code}?depth=2")
    if "districts" in data:
        return JSONResponse({
            "province_code": province_code,
            "province_name": data.get("name", ""),
            "districts": [{"name": d["name"], "code": d["code"]} for d in data["districts"]],
        })
    return JSONResponse({
        "province_code": province_code,
        "province_name": "",
        "districts": [],
        "note": "Dữ liệu quận/huyện không khả dụng (API ngoài không truy cập được)"
    })


@router.get("/old-wards/{district_code}")
async def get_old_wards(district_code: int):
    data = _fetch_old(f"/d/{district_code}?depth=2")
    if "wards" in data:
        return JSONResponse({
            "district_code": district_code,
            "district_name": data.get("name", ""),
            "wards": [{"name": w["name"], "code": w["code"]} for w in data["wards"]],
        })
    return JSONResponse({
        "district_code": district_code,
        "district_name": "",
        "wards": [],
        "note": "Dữ liệu phường/xã không khả dụng (API ngoài không truy cập được)"
    })


def convert_old_to_new_sync(
    old_ward: str,
    old_province: str,
    old_district: str = "",
    old_province_code: int | None = None,
) -> dict:
    """
    Synchronous conversion of old ward → new post-2025-reform address.
    Same logic as the /convert endpoint, callable from other handlers.
    """
    ward_map = _load_ward_map()
    old_ward    = str(old_ward or "").strip()
    old_province = str(old_province or "").strip()

    if not old_ward:
        return {"new_province": "", "new_ward": "", "new_district": "", "matched": False}

    compound = _compound_key(old_province, old_ward)
    result = ward_map.get(compound)
    if result:
        new_prov_short, new_ward = result
        return {
            "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
            "new_province_short": new_prov_short,
            "new_ward": new_ward,
            "new_district": "",
            "matched": True,
        }

    ward_only_key = _norm_ward(old_ward)
    prov_norm = _norm_prov(old_province)
    for k, v in ward_map.items():
        k_prov, _, k_ward = k.partition("::")
        if k_ward == ward_only_key:
            if k_prov == prov_norm:
                new_prov_short, new_ward = v
                return {
                    "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
                    "new_province_short": new_prov_short,
                    "new_ward": new_ward,
                    "new_district": "",
                    "matched": True,
                }

    for k, v in ward_map.items():
        _, _, k_ward = k.partition("::")
        if k_ward == ward_only_key:
            new_prov_short, new_ward = v
            return {
                "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
                "new_province_short": new_prov_short,
                "new_ward": new_ward,
                "new_district": "",
                "matched": True,
            }

    return {
        "new_province": old_province,
        "new_ward": old_ward,
        "new_district": "",
        "matched": False,
    }


@router.post("/convert")
async def convert_old_to_new(body: dict):
    """
    Convert old ward name → new post-2025-reform address.

    Input:  { old_ward_name: str, old_province_name: str, old_district_name: str }
    Output: { new_province: str, new_province_short: str, new_ward: str,
              new_district: str, matched: bool, note: str }

    Uses vn_ward_map.json (18,613 compound-keyed entries from official Excel).
    Key format: "old_province_normalized::old_ward_normalized"
    This eliminates same-ward-name collisions across provinces.
    Note: new_district is always "" because the Excel ward consolidation absorbs
    districts — the ward name alone is the authoritative new-address unit.
    """
    ward_map = _load_ward_map()
    old_ward    = str(body.get("old_ward_name",    "")).strip()
    old_province = str(body.get("old_province_name", "")).strip()

    if not old_ward:
        return {"new_province": "", "new_ward": "", "new_district": "", "matched": False}

    # ── Primary: compound province+ward key ──────────────────────────────────
    compound = _compound_key(old_province, old_ward)
    result = ward_map.get(compound)

    if result:
        new_prov_short, new_ward = result
        return {
            "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
            "new_province_short": new_prov_short,
            "new_ward": new_ward,
            "new_district": "",
            "matched": True,
        }

    # ── Fallback 1: try ward-only (no province) ── covers edge cases where
    # user's province name doesn't match Excel "Gộp từ" label exactly
    ward_only_key = _norm_ward(old_ward)
    prov_norm = _norm_prov(old_province)
    # Scan for any compound key whose ward part matches and province is plausible
    for k, v in ward_map.items():
        k_prov, _, k_ward = k.partition("::")
        if k_ward == ward_only_key:
            # Prefer keys from same province
            if k_prov == prov_norm:
                new_prov_short, new_ward = v
                return {
                    "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
                    "new_province_short": new_prov_short,
                    "new_ward": new_ward,
                    "new_district": "",
                    "matched": True,
                    "note": "Matched via province-name fuzzy",
                }

    # ── Fallback 2: ward-only, any province (last resort) ───────────────────
    for k, v in ward_map.items():
        _, _, k_ward = k.partition("::")
        if k_ward == ward_only_key:
            new_prov_short, new_ward = v
            return {
                "new_province": PROV_DISPLAY.get(new_prov_short, new_prov_short),
                "new_province_short": new_prov_short,
                "new_ward": new_ward,
                "new_district": "",
                "matched": True,
                "note": "Matched ward-only (province ambiguous)",
            }

    # ── No match ─────────────────────────────────────────────────────────────
    return {
        "new_province": old_province,
        "new_ward": old_ward,
        "new_district": "",
        "matched": False,
        "note": "No mapping found in official Excel dataset",
    }


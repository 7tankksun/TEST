# -*- coding: utf-8 -*-
"""
급등주·테마 Stage2: 섹터가 비거나 '미분류'일 때 보강.

우선순위
1) payload(후보 JSON)에 유효한 sector 문자열이 있으면 그대로
2) surge_sector_overrides.json (티커 → 표준 섹터)
3) 종목명 + extra_hint(후보 raw 업종 문자열)로 candidates_data.classify_standard_sector
4) 미분류

오버라이드 보강: build_surge_sector_overrides.py (OPENAI), refresh_surge_sector_overrides_yfinance.py (yfinance)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_OVERRIDE_PATH = _HERE / "surge_sector_overrides.json"
_USELESS_SECTOR = frozenset({"미분류", "코스피", "코스닥", "KOSPI", "KOSDAQ", ""})

# Yahoo Finance sector/industry(영문) → candidates_data 표준 15 sector
_YF_TO_STANDARD: list[tuple[str, tuple[str, ...]]] = [
    (
        "반도체/AI",
        (
            "semiconductor",
            "semiconductors",
            "semiconductor equipment",
            "semiconductor memory",
            "semiconductor equipment & materials",
        ),
    ),
    (
        "IT부품/디스플레이장비",
        (
            "consumer electronics",
            "electronic components",
            "computer hardware",
            "scientific & technical instruments",
            "scientific instruments",
            "electronic equipment",
            "hardware, equipment & parts",
            "technology hardware",
            "communication equipment",
            "electronic devices",
            "instruments & components",
        ),
    ),
    (
        "2차전지/소재",
        (
            "electrical equipment",
            "electrical equipment & parts",
            "electrical components",
            "battery",
            "energy storage",
        ),
    ),
    (
        "바이오/의료",
        (
            "healthcare",
            "biotechnology",
            "drug manufacturers",
            "medical devices",
            "medical instruments",
            "medical care",
            "diagnostics",
            "life sciences",
            "health information",
        ),
    ),
    (
        "자동차/부품",
        (
            "auto manufacturers",
            "auto parts",
            "automotive",
            "recreational vehicles",
            "motor vehicles",
        ),
    ),
    (
        "기계/로봇/방산",
        (
            "industrial products",
            "specialty industrial machinery",
            "farm & heavy construction machinery",
            "metal fabrication",
            "aerospace & defense",
            "aerospace",
            "defense",
            "machinery",
            "industrial conglomerates",
        ),
    ),
    (
        "화학/소재",
        (
            "chemicals",
            "specialty chemicals",
            "agricultural inputs",
            "agrochemicals",
            "chemical materials",
        ),
    ),
    (
        "철강/금속",
        (
            "steel",
            "copper",
            "aluminum",
            "gold",
            "silver",
            "other industrial metals",
            "metals & mining",
        ),
    ),
    (
        "건설/건자재",
        (
            "engineering & construction",
            "building materials",
            "construction materials",
            "real estate—development",
            "real estate development",
            "homebuilding",
        ),
    ),
    (
        "금융/지주",
        (
            "financial services",
            "banks",
            "banking",
            "insurance",
            "asset management",
            "capital markets",
            "credit services",
            "financial conglomerates",
            "mortgage finance",
            "insurance diversified",
            "reit",
            "real estate services",
        ),
    ),
    (
        "유통/소비재",
        (
            "apparel manufacturing",
            "apparel retail",
            "department stores",
            "luxury goods",
            "home improvement",
            "packaged foods",
            "household & personal products",
            "restaurants",
            "footwear",
            "textile manufacturing",
            "leisure",
            "discount stores",
        ),
    ),
    (
        "통신/미디어/엔터",
        (
            "communication services",
            "telecommunications services",
            "wireless telecommunications",
            "integrated telecommunications services",
            "media",
            "entertainment",
            "interactive media",
            "internet content",
            "broadcasting",
            "advertising agencies",
            "electronic gaming",
            "gaming",
            "publishing",
            "software - application",
            "software-application",
            "software - infrastructure",
            "software-infrastructure",
            "information technology services",
        ),
    ),
    (
        "에너지/전력/친환경",
        (
            "energy",
            "oil & gas",
            "oil, gas & consumable fuels",
            "coal",
            "solar",
            "utilities",
            "electric utilities",
            "independent power producers",
            "renewable utilities",
            "uranium",
            "regulated gas",
            "regulated electric",
        ),
    ),
    (
        "운송/물류",
        (
            "marine shipping",
            "air freight & logistics",
            "airlines",
            "trucking",
            "railroads",
            "transportation",
            "integrated freight",
            "airport services",
        ),
    ),
    (
        "음식료/농수산",
        (
            "food products",
            "beverages",
            "brewers",
            "distillers",
            "farm products",
            "confectioners",
            "tobacco",
            "agricultural farm",
        ),
    ),
]

# Yahoo가 sector/industry 를 안 줄 때 longName/shortName 영문 키워드
_NAME_EN_TO_STANDARD: list[tuple[str, tuple[str, ...]]] = [
    ("반도체/AI", ("semiconductor", "silicon wafer", "semiconductor materials")),
    ("IT부품/디스플레이장비", (" oled", " LCD", "display", "camera module", "touch panel", "mobile handset")),
    ("2차전지/소재", ("battery", "lithium", "cathode", "anode", "energy materials")),
    ("바이오/의료", ("pharma", "biopharma", "biotech", "therapeutics", "medical", "diagnostic", "healthcare")),
    ("자동차/부품", ("motor", "auto parts", "automotive", "tire", "vehicle")),
    (
        "기계/로봇/방산",
        ("engineering", "machinery", "heavy industries", "plant", "robotics", "aerospace", "defense"),
    ),
    ("화학/소재", ("chemical", "petrochemical", "materials co", "coatings")),
    ("철강/금속", ("steel", "metal", "aluminium", "aluminum", "copper")),
    ("건설/건자재", ("construction", "engineering &", "engineering and")),
    ("금융/지주", (" financial", " bank", "insurance", "capital", "investment", "holdings", "securities")),
    ("유통/소비재", ("retail", "department store", " trading", "fashion", "cosmetics")),
    ("통신/미디어/엔터", ("media", "entertainment", "software", "telecom", "communications", "digital", "game")),
    ("에너지/전력/친환경", ("power", "energy", "solar", "wind", "electric", "renewable", "gas ", "oil ")),
    ("운송/물류", ("shipping", "logistics", "airlines", "marine", "transportation")),
    ("음식료/농수산", ("food", "beverage", "dairy", "agri", "farming", "brew")),
]

# Yahoo longName 등에 sector가 없을 때 (긴 문자열을 앞에 두어 우선 매칭)
_LONGNAME_ALIAS_SECTOR_RAW: list[tuple[str, str]] = [
    ("eone diagnomics genome center", "바이오/의료"),
    ("ev advanced material co", "2차전지/소재"),
    ("youngwoo dsp co", "IT부품/디스플레이장비"),
    ("kolon life science", "바이오/의료"),
    ("kolon tissuegene", "바이오/의료"),
    ("bumhan fuel cell", "에너지/전력/친환경"),
    ("enf technology co", "화학/소재"),
    ("tokai carbon korea", "화학/소재"),
    ("openedges technology", "반도체/AI"),
    ("doosan tesna", "반도체/AI"),
    ("konan technology", "통신/미디어/엔터"),
    ("adtechnology co", "반도체/AI"),
    ("da technology co", "반도체/AI"),
    ("wemade max co", "통신/미디어/엔터"),
    ("posco m-tech", "철강/금속"),
    ("s&w corporation", "기계/로봇/방산"),
    ("isc co., ltd", "반도체/AI"),
    ("isc co.", "반도체/AI"),
    ("viatron technologies", "반도체/AI"),
    ("unitrontech co", "반도체/AI"),
    ("finetechnix", "반도체/AI"),
    ("micro friend", "반도체/AI"),
    ("protec mems", "반도체/AI"),
    ("kpx lifescience", "바이오/의료"),
    ("green lifescience", "바이오/의료"),
    ("tegoscience", "바이오/의료"),
    ("st pharm co", "바이오/의료"),
    ("finger story", "통신/미디어/엔터"),
    ("nice d&b co", "금융/지주"),
    ("ifamilysc co", "금융/지주"),
    ("intellian technologies", "통신/미디어/엔터"),
    ("soop co.", "통신/미디어/엔터"),
    ("noble m&b co", "유통/소비재"),
    ("nara cellar", "음식료/농수산"),
    ("tiger elec", "에너지/전력/친환경"),
    ("tigerelec co", "에너지/전력/친환경"),
    ("zaram technology", "반도체/AI"),
    ("tomatosystem co", "통신/미디어/엔터"),
    ("monitorapp co", "통신/미디어/엔터"),
    ("fine m-tec", "기계/로봇/방산"),
    ("laserssel co", "기계/로봇/방산"),
    ("cp system co", "기계/로봇/방산"),
    ("unid btplus", "바이오/의료"),
    ("softcamp co", "통신/미디어/엔터"),
    ("ecopro co", "2차전지/소재"),
    ("n2tech co", "반도체/AI"),
    ("vina tech co", "2차전지/소재"),
    ("partron co", "IT부품/디스플레이장비"),
    ("oe solutions co", "IT부품/디스플레이장비"),
    ("toptec co", "IT부품/디스플레이장비"),
    ("nexteye co", "IT부품/디스플레이장비"),
    ("opticis company", "IT부품/디스플레이장비"),
    ("namuga co", "IT부품/디스플레이장비"),
    ("jnk global", "유통/소비재"),
    ("dilli illustrate", "통신/미디어/엔터"),
    ("plateer co", "통신/미디어/엔터"),
    ("iteyes inc", "통신/미디어/엔터"),
    ("syswork co", "통신/미디어/엔터"),
    ("gitsn", "통신/미디어/엔터"),
    ("virnect co", "통신/미디어/엔터"),
    ("vidente co", "통신/미디어/엔터"),
    ("emnet inc", "통신/미디어/엔터"),
    ("webzen inc", "통신/미디어/엔터"),
    ("hancom inc", "통신/미디어/엔터"),
    ("wemade co", "통신/미디어/엔터"),
    ("valofe co", "통신/미디어/엔터"),
    ("pamtek co", "기계/로봇/방산"),
    ("pro2000 co", "기계/로봇/방산"),
    ("gi innovation", "바이오/의료"),
    ("h.pio co", "바이오/의료"),
    ("caregen co", "바이오/의료"),
    ("innogene co", "바이오/의료"),
    ("aptocrom", "바이오/의료"),
    ("sands lab", "바이오/의료"),
    ("ggumbi inc", "유통/소비재"),
    ("bistos", "바이오/의료"),
    ("vistos co", "바이오/의료"),
    ("q aid co", "바이오/의료"),
    ("imagis co", "통신/미디어/엔터"),
    ("nable inc", "통신/미디어/엔터"),
    ("alt co., ltd", "바이오/의료"),
    ("ameridge corporation", "유통/소비재"),
    ("dsk co", "기계/로봇/방산"),
    ("dypnf co", "유통/소비재"),
    ("knw co", "기계/로봇/방산"),
    ("tse co", "반도체/AI"),
    ("almac co", "반도체/AI"),
    ("osp co", "IT부품/디스플레이장비"),
    ("4by4 inc", "통신/미디어/엔터"),
]
_LONGNAME_ALIAS_SECTOR: list[tuple[str, str]] = sorted(
    _LONGNAME_ALIAS_SECTOR_RAW, key=lambda x: (-len(x[0]), x[0])
)

# ticker가 포함된 잘못된 행(미국 펀드코드 섞임 등) + Yahoo longName 공백
_TICKER_SECTOR_PATCH: dict[str, str] = {
    "219750.KQ": "유통/소비재",
    "279570.KS": "금융/지주",
    "480370.KS": "통신/미디어/엔터",
    "432980.KQ": "금융/지주",
    "424760.KQ": "금융/지주",
    "451700.KQ": "금융/지주",
    "355150.KQ": "금융/지주",
    "365900.KQ": "금융/지주",
    "196490.KQ": "반도체/AI",
    "222160.KQ": "반도체/AI",
    "230980.KQ": "IT부품/디스플레이장비",
    "245620.KQ": "바이오/의료",
    "269620.KQ": "통신/미디어/엔터",
    "377460.KQ": "바이오/의료",
    "106520.KQ": "유통/소비재",
    "121800.KQ": "통신/미디어/엔터",
}

_override_cache: dict[str, str] | None = None


def _normalize_ticker(t: str) -> str:
    return str(t or "").strip().upper()


def load_surge_sector_overrides() -> dict[str, str]:
    """티커(대문자) → 표준 섹터 라벨."""

    global _override_cache
    if _override_cache is not None:
        return _override_cache
    out: dict[str, str] = {}
    if not _OVERRIDE_PATH.is_file():
        _override_cache = out
        return out
    try:
        raw: Any = json.loads(_OVERRIDE_PATH.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            _override_cache = out
            return out
        for k, v in raw.items():
            ks = str(k).strip().upper()
            if ks.startswith("_"):
                continue
            if not isinstance(v, str) or not v.strip():
                continue
            out[ks] = v.strip()
    except Exception:
        out = {}
    _override_cache = out
    return out


def infer_standard_sector_from_yf(
    info: dict[str, Any],
    name_ko: str = "",
    *,
    ticker: str = "",
) -> str | None:
    """Yahoo Finance ``info`` dict에서 표준 섹터 추정(없으면 None)."""

    tk = _normalize_ticker(ticker)
    if tk in _TICKER_SECTOR_PATCH:
        return _TICKER_SECTOR_PATCH[tk]

    parts: list[str] = []
    for key in ("sector", "industry", "industryKey", "sectorKey", "quoteType"):
        v = info.get(key)
        if v:
            parts.append(str(v))
    summ = info.get("longBusinessSummary")
    if isinstance(summ, str) and summ.strip():
        parts.append(summ[:500])
    for key in ("longName", "shortName"):
        v = info.get(key)
        if v:
            parts.append(str(v))
    if name_ko:
        parts.append(str(name_ko))
    blob = " ".join(parts).lower()
    blob = blob.replace("—", "-").replace("–", "-")
    if not blob.strip():
        return None
    for label, keys in _YF_TO_STANDARD:
        if any(k in blob for k in keys):
            return label
    try:
        from candidates_data import classify_standard_sector

        hint = f"{info.get('industry') or ''} {info.get('sector') or ''}"
        guess = classify_standard_sector(name_ko or str(info.get("longName") or ""), hint)
        if guess:
            return guess
    except Exception:
        pass

    en_blob = f"{info.get('longName') or ''} {info.get('shortName') or ''} {name_ko}".lower()
    en_blob = en_blob.replace("—", "-").replace("–", "-")
    pad = f" {en_blob} "
    if "special purpose acquisition" in en_blob or " spac " in pad:
        return "금융/지주"
    if "kbank" in en_blob:
        return "금융/지주"
    for needle, label in _LONGNAME_ALIAS_SECTOR:
        if needle in en_blob:
            return label
    for label, keys in _NAME_EN_TO_STANDARD:
        if any(k in en_blob for k in keys):
            return label
    sec0 = str(info.get("sector") or "").strip().lower()
    _broad: dict[str, str] = {
        "healthcare": "바이오/의료",
        "financial services": "금융/지주",
        "financials": "금융/지주",
        "technology": "IT부품/디스플레이장비",
        "communication services": "통신/미디어/엔터",
        "consumer cyclical": "유통/소비재",
        "consumer defensive": "음식료/농수산",
        "industrials": "기계/로봇/방산",
        "basic materials": "화학/소재",
        "energy": "에너지/전력/친환경",
        "utilities": "에너지/전력/친환경",
        "real estate": "건설/건자재",
    }
    return _broad.get(sec0)


def merge_surge_sector_overrides(new_entries: dict[str, str]) -> int:
    """병합 후 저장. 반환: 새로 덮어쓴 키 수."""

    global _override_cache
    cur = load_surge_sector_overrides().copy()
    n = 0
    for k, v in new_entries.items():
        ks = _normalize_ticker(k)
        vs = str(v).strip()
        if not ks or not vs or vs == "미분류":
            continue
        if cur.get(ks) != vs:
            n += 1
        cur[ks] = vs
    _OVERRIDE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _OVERRIDE_PATH.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    _override_cache = cur
    return n


def resolve_surge_sector(
    *,
    ticker: str,
    name: str = "",
    payload_sector: str = "",
    extra_hint: str = "",
) -> str:
    """표시/통계용 표준 섹터 한 가지."""

    ps = (payload_sector or "").strip()
    if ps and ps not in _USELESS_SECTOR:
        return ps
    t = _normalize_ticker(ticker)
    ov = load_surge_sector_overrides().get(t)
    if ov and ov not in _USELESS_SECTOR:
        return ov
    try:
        from candidates_data import classify_standard_sector

        blob = f"{extra_hint or ''} {ps or ''} {name or ''}"
        guess = classify_standard_sector(name or "", blob)
        if guess:
            return guess
    except Exception:
        pass
    return "미분류"

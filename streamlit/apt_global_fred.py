"""
FRED(미국) 주요 주택가격 지수: Case-Shiller·FHFA. APT_FRED_API_KEY 또는 FRED_API_KEY.
키 없으면 None 반환(웹·JSON에서 안내 문구만).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

matplotlib.use("Agg")

FRED = "https://api.stlouisfed.org/fred/series/observations"
# FRED 심볼(미국: 월간). BIS*는 분기·심볼이 바뀌면 FRED에서 확인 후 조정.
SERIES = [
    ("미국 – S&P/Case–Shiller 20 (지수, 월)", "SPCS20RSA"),
    ("미국 – FHFA All-Trans HPI (지수, 월)", "USSTHPI"),
    ("영국 – BIS 실질 주택가 (분기)", "QGBR628BIS"),
    ("캐나다 – BIS 실질 주택가 (분기)", "QCAR628BIS"),
    ("일본 – BIS 실질 주택가 (분기)", "QJPR628BIS"),
]


def _key() -> str:
    e = (os.environ.get("APT_FRED_API_KEY") or os.environ.get("FRED_API_KEY") or "").strip()
    if e:
        return e
    here = os.path.dirname(os.path.abspath(__file__))
    for name in ("fred_api_key.txt", "apt_fred_key.txt"):
        p = os.path.join(here, name)
        if os.path.isfile(p):
            try:
                with open(p, "r", encoding="utf-8", errors="replace") as f:
                    line = (f.readline() or "").strip()
                if line and not line.startswith("#"):
                    return line
            except OSError:
                pass
    return ""


def _fetch_fred_json(series_id: str, n: int = 60) -> list[dict[str, Any]]:
    k = _key()
    if not k:
        return []
    u = f"{FRED}?series_id={series_id}&api_key={urllib.parse.quote(k)}&file_type=json&sort_order=desc&limit={n}"
    req = urllib.request.Request(u, headers={"User-Agent": "apt_global_fred/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            body = r.read().decode("utf-8", errors="replace")
        data = json.loads(body)
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:500] if e.fp else str(e)
        print(f"[FRED] HTTP {e.code} {series_id}: {err}")
        return []
    except (urllib.error.URLError, json.JSONDecodeError, OSError, ValueError) as e:
        print(f"[FRED] {series_id}: {e}")
        return []
    return list(data.get("observations") or [])


_FRED_LAST_PCT: dict[str, int] = {}


def _fred_progress_line(j: int, n: int, sid: str) -> None:
    t = max(1, int(n))
    c = min(int(j), t)
    p = 100 if c >= t else (100 * c) // t
    key = f"fred|{t}"
    if _FRED_LAST_PCT.get(key, -1) == p:
        return
    _FRED_LAST_PCT[key] = p
    line = f"[FRED]  {p:3d}%  ({c}/{t})  {sid}"
    plain = (os.environ.get("APT_PLAIN_PROGRESS") or "").strip() in ("1", "true", "yes")
    if plain:
        print(line, flush=True)
    else:
        print(f"\r{line}" + " " * 2, end="", flush=True)


def _fred_progress_done() -> None:
    if (os.environ.get("APT_PLAIN_PROGRESS") or "").strip() in ("1", "true", "yes"):
        return
    print(flush=True)


def build_global_hpi_payload(charts_dir: str) -> dict[str, Any] | None:
    k = _key()
    if not k:
        return {
            "ok": False,
            "empty_reason": "FRED API 키가 없습니다. 환경 변수 FRED_API_KEY 또는 APT_FRED_API_KEY를 설정하거나, streamlit 폴더에 fred_api_key.txt(한 줄에 키)를 두세요. https://fred.stlouisfed.org/docs/api/api_key.html",
            "chart": None,
            "rows": [],
        }
    all_rows: list[dict] = []
    series_for_plot: list[tuple[str, pd.Series]] = []
    _FRED_LAST_PCT.clear()
    n_ser = len(SERIES)
    print(f"[FRED] 시리즈 {n_ser}개 수집")
    for j, (label, sid) in enumerate(SERIES, start=1):
        try:
            obs = _fetch_fred_json(sid, n=60)
            if not obs:
                continue
            pts: list[tuple[pd.Timestamp, float]] = []
            for o in obs:
                d, v = o.get("date"), o.get("value")
                if not d or v in (None, ".", ""):
                    continue
                try:
                    pts.append((pd.to_datetime(d), float(v)))
                except (TypeError, ValueError):
                    continue
            if len(pts) < 2:
                continue
            s = pd.Series({p[0]: p[1] for p in pts}).sort_index()
            last, prev = float(s.iloc[-1]), float(s.iloc[-2])
            mom = ((last / prev) - 1) * 100.0 if prev else None
            yoy = None
            ppy: float | None
            if "628BIS" in sid and len(s) >= 5:
                ppy = float(s.iloc[-5])
            elif "628BIS" not in sid and len(s) >= 13:
                ppy = float(s.iloc[-13])
            else:
                ppy = None
            if ppy and ppy != 0:
                yoy = ((last / ppy) - 1) * 100.0
            all_rows.append(
                {
                    "label": label,
                    "series_id": sid,
                    "last_date": s.index[-1].strftime("%Y-%m"),
                    "last_value": round(last, 2),
                    "mom_pct": None if mom is None else round(mom, 3),
                    "yoy_pct": None if yoy is None else round(yoy, 3),
                }
            )
            base = s.iloc[0]
            s_norm = (s / base) * 100.0 if base else s
            short = label.split("–", 1)[-1].strip() if "–" in label else label
            series_for_plot.append((short[:22], s_norm))
        finally:
            _fred_progress_line(j, n_ser, sid)
    _fred_progress_done()

    if not all_rows:
        return {
            "ok": False,
            "empty_reason": "FRED 응답이 비어 있거나 파싱에 실패했습니다.",
            "chart": None,
            "rows": [],
        }

    out_chart = os.path.join(charts_dir, "global_hpi.png")
    os.makedirs(charts_dir, exist_ok=True)
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for name, s in series_for_plot:
        ax.plot(s.index, s.values, linewidth=1.8, label=name)
    ax.axhline(100, color="#999", linestyle="--", linewidth=0.8)
    ax.set_title("해외 주요 주택·가격지수 (정규화, FRED: 미·영·캐·일; 월/분기 혼재)")
    ax.set_ylabel("정규화 지수(시작=100)")
    ax.legend(loc="best", fontsize=8)
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_chart, dpi=120)
    plt.close(fig)
    print(f"[FRED] 차트 저장: {out_chart} (시리즈 {len(all_rows)}개)")
    return {
        "ok": True,
        "source": "FRED(미 연준·BIS) 기반 지수. 도시 단위 직접 시세·호가 API는 국가별 제약이 커, 대표 HPI/지수로 대체합니다. 유럽·기타는 OECD/ECB BIS를 추가하려면 apt_global_fred.py의 SERIES를 확장하세요.",
        "chart": "global_hpi.png",
        "rows": all_rows,
    }

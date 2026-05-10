import datetime
import json
import os
import time
import warnings
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

import matplotlib
import matplotlib.font_manager as fm
import matplotlib.pyplot as plt
import pandas as pd
import requests
from dateutil.relativedelta import relativedelta

from apt_global_fred import build_global_hpi_payload

matplotlib.use("Agg")
warnings.filterwarnings("ignore", module="matplotlib")
warnings.filterwarnings("ignore", message=".*Glyph.*missing from font.*", category=UserWarning)

SERVICE_KEY = os.environ.get(
    "APT_SERVICE_KEY",
    "aUXAAWocPJtUuzCrGTMvISdCznK2buAlABKhAUqAd/VAosPKeDJSFkLcbf6QJcmWnbh50gRQ+Z+aPOD69+NbHg==",
)
API_URL = "https://apis.data.go.kr/1613000/RTMSDataSvcAptTrade/getRTMSDataSvcAptTrade"

DISPLAY = {
    "last_analysis_time": None,
    "region_summary": [],
    "apts": [],
    "apt_sections": [],
    "global_hpi": None,
    "candidate_count": 0,
}

# block: 권역 정렬 (서울 → 경기 → 인천 → 5대 광역: 부·대·광·대·울) / 세종 제외
# sigungu: 콘솔·웹에서 '강동구' '송파구' 식으로 나열용
BLOCK_ORDER = {
    "seoul": 0,
    "gyeonggi": 1,
    "incheon": 2,
    "busan": 3,
    "daegu": 4,
    "gwangju": 5,
    "daejeon": 6,
    "ulsan": 7,
}
BLOCK_TITLES = {
    "seoul": "서울특별시",
    "gyeonggi": "경기도",
    "incheon": "인천광역시",
    "busan": "부산광역시",
    "daegu": "대구광역시",
    "gwangju": "광주광역시",
    "daejeon": "대전광역시",
    "ulsan": "울산광역시",
}
SUMMARY_KEY = {
    "seoul": "서울",
    "gyeonggi": "경기",
    "incheon": "인천",
    "busan": "부산",
    "daegu": "대구",
    "gwangju": "광주",
    "daejeon": "대전",
    "ulsan": "울산",
}
_PKG_DIR = os.path.dirname(os.path.abspath(__file__))

# 국토부 수집 기간(개월) 기본값 — 3년. `APT_MONTHS_BACK`로 덮어씀
DEFAULT_APT_MONTHS_BACK = 36


def _load_json_apt(name: str) -> dict:
    p = os.path.join(_PKG_DIR, name)
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_apt_registry() -> dict:
    raw = _load_json_apt("apt_registry.json")
    return {c["id"]: c for c in raw.get("complexes", [])}


APT_DATA: Dict[str, dict] = _load_apt_registry()
_CX = _load_json_apt("apt_clusters.json")
CLUSTER_ORDER: List[str] = list(_CX.get("order", ["S1", "S2", "S3", "GG", "REG"]))
CLUSTERS: dict = _CX.get("clusters", {})


# 서울 내 구 가나다순(표시/정렬)
_SEOUL_GU_ORDER: Dict[str, int] = {}


def _cluster_rank(cid: str) -> int:
    try:
        return CLUSTER_ORDER.index(cid)
    except ValueError:
        return 99


def _seoul_gu_order(sigungu: str) -> int:
    if not _SEOUL_GU_ORDER:
        gu_list = sorted(
            {v["sigungu"] for k, v in APT_DATA.items() if v.get("block") == "seoul" and "sigungu" in v}
        )
        for i, g in enumerate(gu_list):
            _SEOUL_GU_ORDER[g] = i
    return _SEOUL_GU_ORDER.get(sigungu, 99)


def _font_prop(base_dir: str):
    paths = [
        os.path.join(base_dir, "fonts", "NanumGothic.ttf"),
        "/usr/share/fonts/truetype/nanum/NanumGothic.ttf",
        "C:/Windows/Fonts/malgun.ttf",
    ]
    for p in paths:
        if os.path.exists(p):
            return fm.FontProperties(fname=p)
    return None


# 동일 run 내에서 "몇 %인지"만 갱신(소수 % 연속 갱신 방지)
_LAST_PROGRESS_PCT: dict[str, int] = {}


def _reset_progress_marks() -> None:
    _LAST_PROGRESS_PCT.clear()


def _progress_line(msg: str, current: int, total: int, detail: str = "", width: int = 100) -> None:
    """콘솔 한 줄, 전체 기준 정수 %만 갱신(이전에 찍은 %와 같으면 생략)."""
    t = max(1, int(total))
    c = min(int(current), t)
    pct_whole = 100 if c >= t else (100 * c) // t
    key = f"{msg}|{t}"
    if _LAST_PROGRESS_PCT.get(key, -1) == pct_whole:
        return
    _LAST_PROGRESS_PCT[key] = pct_whole
    ext = f"  {detail}" if detail else ""
    line = f"{msg}  {pct_whole:3d}%  ({c}/{t}){ext}"
    if len(line) > width:
        line = line[: width - 3] + "..."
    plain = (os.environ.get("APT_PLAIN_PROGRESS") or "").strip() in ("1", "true", "yes")
    if plain:
        print(line, flush=True)
    else:
        print(f"\r{line}" + " " * 4, end="", flush=True)


def _progress_done() -> None:
    if (os.environ.get("APT_PLAIN_PROGRESS") or "").strip() in ("1", "true", "yes"):
        return
    print(flush=True)


def _collect_raw(months_back: int) -> pd.DataFrame:
    now = datetime.datetime.now()
    months = [(now - relativedelta(months=i)).strftime("%Y%m") for i in range(months_back)]
    months.reverse()
    unique_lawds = sorted({info["lawd_cd"] for info in APT_DATA.values()})
    raw: List[Dict] = []

    n_req = max(1, len(unique_lawds) * len(months))
    print(
        f"[APT] 수집 시작: 법정동 {len(unique_lawds)}개 x {len(months)}개월 (요청 {n_req}회)"
    )
    step = 0
    for lawd in unique_lawds:
        for ymd in months:
            step += 1
            _progress_line("[APT] 실거래 수집", step, n_req, f"{lawd} {ymd}")
            params = {
                "serviceKey": requests.utils.unquote(SERVICE_KEY),
                "pageNo": "1",
                "numOfRows": "1000",
                "LAWD_CD": lawd,
                "DEAL_YMD": ymd,
            }
            try:
                res = requests.get(API_URL, params=params, timeout=15)
                if res.status_code != 200:
                    continue
                root = ET.fromstring(res.text)
                for item in root.findall(".//item"):
                    # 매매 취소(해제) 건: 금액이 남아 있으므로 제외 (월전세·월세 API와 혼동 아님 — 본 API는 아파트 매매만)
                    cdeal = (item.findtext("cdealType") or "").strip()
                    if cdeal.upper() == "O":
                        continue
                    area = item.findtext("excluUseAr")
                    if not area:
                        continue
                    if not (84.0 <= float(area) < 86.0):
                        continue
                    amt = item.findtext("dealAmount")
                    day = item.findtext("dealDay")
                    apt_name = (item.findtext("aptNm") or "").strip()
                    if not apt_name or not amt or not day:
                        continue
                    raw.append(
                        {
                            "aptNm": apt_name,
                            "Date": pd.to_datetime(f"{ymd[:4]}-{ymd[4:]}-{int(day):02d}"),
                            "Price": int(amt.replace(",", "").strip()),
                        }
                    )
            except Exception:
                continue
        time.sleep(0.1)
    _progress_done()
    print(f"[APT] 수집 완료: 원시 매칭(84㎡) {len(raw)}건")
    return pd.DataFrame(raw)


def _filter_for_target_apts(df_all: pd.DataFrame) -> pd.DataFrame:
    out = []
    for _key, info in APT_DATA.items():
        pats = [p.strip() for p in str(info.get("api_name", "")).split("|") if p.strip()]
        if not pats:
            continue
        sub: pd.DataFrame | None = None
        for p in pats:
            cand = df_all[df_all["aptNm"].str.contains(p, na=False, regex=False)]
            if not cand.empty:
                sub = cand.copy()
                break
        if sub is None or sub.empty:
            continue
        sub["disp_name"] = info["disp_name"]
        bl = str(info.get("block") or "seoul")
        sub["region"] = SUMMARY_KEY.get(bl, "기타")
        sub["block"] = bl
        sub["sigungu"] = str(info.get("sigungu") or "")
        out.append(sub)
    if not out:
        return pd.DataFrame(
            columns=["aptNm", "Date", "Price", "disp_name", "region", "block", "sigungu"]
        )
    return pd.concat(out, ignore_index=True)


def _filter_price_outlier_trades(df: pd.DataFrame) -> pd.DataFrame:
    """같은 단지 내, 주변(일) 구간의 거래가 중앙가 대비 너무 벗어나면 제외(오신고·취소 전 표시 등).

    기본: ±180일(전후)·동일 그룹(본인 제외) 중앙 ≥2건이면, 중앙의 0.5배 미만 또는 2.0배 초과는 제거.
    APT_NO_PRICE_OUTLIER_FILTER=1 로 끄기.
    """
    if (os.environ.get("APT_NO_PRICE_OUTLIER_FILTER") or "").strip() in ("1", "true", "yes", "Y"):
        return df
    if df.empty or "disp_name" not in df.columns or "Date" not in df.columns or "Price" not in df.columns:
        return df
    half = int(os.environ.get("APT_PRICE_OUTLIER_DAYS", "180"))
    low = float(os.environ.get("APT_PRICE_OUTLIER_LOW_FRAC", "0.5"))
    high = float(os.environ.get("APT_PRICE_OUTLIER_HIGH_FRAC", "2.0"))
    min_around = int(os.environ.get("APT_OUTLIER_MIN_IN_WINDOW", "2"))
    td = pd.Timedelta(days=half)
    n_in = len(df)
    out_parts: List[pd.DataFrame] = []
    n_drop = 0
    for _disp, g in df.groupby("disp_name", sort=False):
        s = g.sort_values("Date").reset_index(drop=True)
        n = len(s)
        if n < 2:
            out_parts.append(s)
            continue
        keep = [True] * n
        for i in range(n):
            di = s.at[i, "Date"]
            m = (s["Date"] - di).abs() <= td
            w = s[m]
            w_other = w[w.index != i]
            if len(w_other) < min_around:
                continue
            med = w_other["Price"].median()
            p = s.at[i, "Price"]
            if med <= 0 or pd.isna(med):
                continue
            if p < med * low or p > med * high:
                keep[i] = False
        s2 = s[keep]
        n_drop += n - len(s2)
        out_parts.append(s2)
    if not out_parts:
        return df
    res = pd.concat(out_parts, ignore_index=True)
    if n_drop > 0:
        print(
            f"[APT] 시세(주변 {half}일 중앙) 대비 이상치 제외: {n_drop}건 / 원본 {n_in}건 "
            f"(남 {len(res)}건, {low:.0%}~{high:.0%} 밖, 주변최소 {min_around}건)"
        )
    return res


def _sort_districts_for_region(region_lab: str, gu_names: List[str]) -> List[str]:
    """대상 단지가 걸쳐 있는 시·군·구 목록을 표에 넣을 순서로."""
    u = [g.strip() for g in gu_names if g and str(g).strip()]
    u = list(dict.fromkeys(u))
    if region_lab == "서울":
        return sorted(u, key=_seoul_gu_order)
    return sorted(u, key=str)


def _build_region_summary(df_target: pd.DataFrame) -> list:
    if df_target.empty:
        return []
    agg = df_target.groupby("region")["Price"].agg(avg_price="mean", trade_count="count")
    rows: List[dict] = []
    for bkey in sorted(BLOCK_ORDER.keys(), key=lambda x: BLOCK_ORDER[x]):
        lab = SUMMARY_KEY.get(bkey)
        if not lab or lab not in agg.index:
            continue
        r = agg.loc[lab]
        row: dict = {
            "region": lab,
            "avg_price_eok": round(float(r["avg_price"]) / 10000.0, 2),
            "trade_count": int(r["trade_count"]),
        }
        part = df_target[df_target["region"] == lab]
        u = [str(x).strip() for x in part["sigungu"].dropna().unique() if str(x).strip()]
        sdist: List[dict] = []
        for gu in _sort_districts_for_region(lab, u):
            sgu = part[part["sigungu"].fillna("").astype(str).str.strip() == gu]
            if sgu.empty:
                continue
            sdist.append(
                {
                    "name": gu,
                    "avg_price_eok": round(float(sgu["Price"].mean()) / 10000.0, 2),
                    "trade_count": int(len(sgu)),
                }
            )
        row["districts"] = sdist
        rows.append(row)
    return rows


def _monthly_mom(sub: pd.DataFrame) -> Tuple[Optional[float], Optional[str]]:
    """월별 평균가 기준 직전 달 대비 증감(%)."""
    if sub.empty:
        return None, None
    m = sub.groupby(sub["Date"].dt.to_period("M"))["Price"].mean().sort_index()
    if len(m) < 2:
        return None, None
    a, b = float(m.iloc[-2]), float(m.iloc[-1])
    if a <= 0:
        return None, None
    pct = round((b / a - 1) * 100, 2)
    lbl = f"{m.index[-2]} vs {m.index[-1]}"
    return pct, lbl


def _build_apt_rows_and_charts(df_target: pd.DataFrame, charts_dir: str, base_dir: str) -> list:
    rows = []
    font_prop = _font_prop(base_dir)
    keys_list = list(APT_DATA.items())
    n_apt = max(1, len(keys_list))
    print(f"[APT] 단지별 차트/행: {n_apt}곳")
    for idx, (key, info) in enumerate(keys_list, start=1):
        disp = info["disp_name"]
        sub = df_target[df_target["disp_name"] == disp].copy()
        chart_name = f"{key}_apt.png"
        chart_path = os.path.join(charts_dir, chart_name)

        if sub.empty:
            if os.path.exists(chart_path):
                os.remove(chart_path)
            _progress_line("[APT] 단지 처리", idx, n_apt, key)
            continue

        daily = sub.groupby("Date", as_index=False)["Price"].mean().sort_values("Date")
        latest = float(daily["Price"].iloc[-1])
        first = float(daily["Price"].iloc[0])
        chg_pct = ((latest / first) - 1.0) * 100.0 if first > 0 else 0.0
        mom_pct, mom_lbl = _monthly_mom(sub)

        fig, ax = plt.subplots(figsize=(10, 4.6))
        ax.plot(daily["Date"], daily["Price"] / 10000.0, color="#2b6cb0", linewidth=2.2)
        sg = str(info.get("sigungu") or "").strip()
        t = f"{sg} {disp} (84㎡) | 최근 {len(daily)}포인트" if sg else f"{disp} (84㎡) | 최근 {len(daily)}포인트"
        ax.set_title(t, fontproperties=font_prop)
        ax.set_ylabel("가격(억원)", fontproperties=font_prop)
        if mom_pct is not None:
            ax.text(
                0.02,
                0.98,
                f"전월 대비(월 평균): {mom_pct:+.2f}%\n({mom_lbl})",
                transform=ax.transAxes,
                va="top",
                fontsize=9,
                bbox=dict(boxstyle="round", facecolor="wheat", alpha=0.4),
            )
        ax.grid(alpha=0.3)
        if font_prop is not None:
            for label in ax.get_xticklabels() + ax.get_yticklabels():
                label.set_fontproperties(font_prop)
        fig.tight_layout()
        fig.savefig(chart_path, dpi=135)
        plt.close(fig)

        bl = str(info.get("block") or "seoul")
        sg2 = str(info.get("sigungu") or "")
        clu = str(info.get("cluster") or "")
        cmeta = CLUSTERS.get(clu) or {}
        clab = (cmeta.get("title") or clu or "").strip()
        rows.append(
            {
                "key": key,
                "cluster": clu,
                "cluster_label": clab,
                "disp_name": disp,
                "size": int(info.get("size") or 0),
                "region": SUMMARY_KEY.get(bl, "기타"),
                "block": bl,
                "sigungu": sg2,
                "latest_price_eok": round(latest / 10000.0, 2),
                "change_pct": round(chg_pct, 2),
                "mom_pct": mom_pct,
                "mom_label": mom_lbl,
                "trade_count": int(len(sub)),
                "chart": chart_name,
            }
        )
        _progress_line("[APT] 단지 처리", idx, n_apt, key)
    _progress_done()
    print(f"[APT] 단지 처리 완료: 차트/행 {len(rows)}곳")
    rows.sort(
        key=lambda x: (
            _cluster_rank(x.get("cluster", "")),
            BLOCK_ORDER.get(x.get("block"), 99),
            _seoul_gu_order(x.get("sigungu", "")) if x.get("block") == "seoul" else 0,
            x.get("sigungu") or "",
            -int(x.get("trade_count", 0)),
            x.get("disp_name") or "",
        )
    )
    return rows


def _build_apt_cluster_sections(apt_rows: list) -> list:
    """권역(클러스터) 제목·설명 + 시·군·구 그룹."""
    if not apt_rows:
        return []
    by_c: dict[str, list] = defaultdict(list)
    for a in apt_rows:
        by_c[str(a.get("cluster") or "REG")].append(a)
    sections: list = []
    for cid in CLUSTER_ORDER:
        items = by_c.get(cid, [])
        if not items:
            continue
        meta = CLUSTERS.get(cid) or {}
        by_gu: dict[str, list] = defaultdict(list)
        for a in items:
            by_gu[str(a.get("sigungu") or "-")].append(a)
        if any(x.get("block") == "seoul" for x in items):
            gu_iter = sorted(by_gu.keys(), key=_seoul_gu_order)
        else:
            gu_iter = sorted(by_gu.keys())
        groups: list = []
        for gu in gu_iter:
            apts = sorted(
                by_gu[gu],
                key=lambda x: (-int(x.get("trade_count", 0)), str(x.get("disp_name") or "")),
            )
            groups.append({"subtitle": gu, "apts": apts})
        sections.append(
            {
                "cluster": cid,
                "title": meta.get("title", cid),
                "description": meta.get("description", ""),
                "groups": groups,
            }
        )
    return sections


def format_apt_leaders_text(apt_sections: List[dict]) -> str:
    """콘솔/로그: 클러스터 순(강남/서초 → …) + 구별 단지."""
    if not apt_sections:
        return "(표시할 대장 단지 섹션이 없습니다.)\n"
    lines: List[str] = [
        "=" * 56,
        "  대장 아파트 (권역별 · 시·군·구 순)",
        "=" * 56,
        "",
    ]
    for sec in apt_sections:
        desc = (sec.get("description") or "").strip()
        if desc:
            lines.append(f"▶ {sec.get('title', '')} — {desc}")
        else:
            lines.append(f"▶ {sec.get('title', '')}")
        for gr in sec.get("groups", []):
            sub = str(gr.get("subtitle", ""))
            apts: List[dict] = gr.get("apts") or []
            names = ", ".join(str(a.get("disp_name", "")) for a in apts)
            if sub and names:
                lines.append(f"   [{sub}]  {names}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_apt_export(base_dir: str) -> dict:
    charts_dir = os.path.join(base_dir, "charts")
    os.makedirs(charts_dir, exist_ok=True)

    months_back = int(os.environ.get("APT_MONTHS_BACK", str(DEFAULT_APT_MONTHS_BACK)))
    months_back = max(6, months_back)
    _reset_progress_marks()

    print(f"[{datetime.datetime.now()}] APT 분석 시작 → {base_dir}")
    global_hpi = build_global_hpi_payload(charts_dir) or {
        "ok": False,
        "empty_reason": "global HPI 모듈 없음",
        "chart": None,
        "rows": [],
    }
    if isinstance(global_hpi, dict) and global_hpi.get("ok"):
        print(
            f"[FRED] 해외 주택지수: OK ({len(global_hpi.get('rows') or [])}개 시리즈, chart={global_hpi.get('chart')})"
        )
    elif isinstance(global_hpi, dict):
        er = (global_hpi.get("empty_reason") or "알 수 없음")[:220]
        print(f"[FRED] 해외 주택지수: 생략 — {er}")

    df_all = _collect_raw(months_back)
    if df_all.empty:
        payload = {
            "last_analysis_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "months_back": months_back,
            "region_summary": [],
            "apts": [],
            "apt_sections": [],
            "global_hpi": global_hpi,
            "candidate_count": len(APT_DATA),
        }
    else:
        df_target = _filter_for_target_apts(df_all)
        df_target = _filter_price_outlier_trades(df_target)
        region_summary = _build_region_summary(df_target)
        apt_rows = _build_apt_rows_and_charts(df_target, charts_dir, base_dir)
        apt_sections = _build_apt_cluster_sections(apt_rows)
        payload = {
            "last_analysis_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "months_back": months_back,
            "region_summary": region_summary,
            "apts": apt_rows,
            "apt_sections": apt_sections,
            "global_hpi": global_hpi,
            "candidate_count": len(APT_DATA),
        }

    out_path = os.path.join(base_dir, "results_web.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    DISPLAY.update(payload)
    print(f"[APT] 완료: 단지 {len(payload['apts'])}개, 파일 {out_path}")
    return payload


def load_apt_display(base_dir: str) -> bool:
    p = os.path.join(base_dir, "results_web.json")
    if not os.path.isfile(p):
        return False
    with open(p, "r", encoding="utf-8") as f:
        data = json.load(f)
    DISPLAY.update(
        {
            "last_analysis_time": data.get("last_analysis_time"),
            "region_summary": data.get("region_summary", []),
            "apts": data.get("apts", []),
            "apt_sections": data.get("apt_sections", []),
            "global_hpi": data.get("global_hpi"),
            "candidate_count": data.get("candidate_count", len(APT_DATA)),
            "months_back": data.get("months_back", DEFAULT_APT_MONTHS_BACK),
        }
    )
    return True

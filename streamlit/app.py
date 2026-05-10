# -*- coding: utf-8 -*-
"""
생활 정보 + GitHub 덴 + 채팅 에이전트 (Streamlit)
UI: Glassmorphism / Neumorphism / Responsive / Sticky Header (CSS)
테마: 따뜻한 신뢰감을 주는 소프트 블루·인디고 팔레트(본문·링크·카드·탭 통일).
레이아웃: 사이드바 option_menu · 메인은 st.container(border=True) 카드 셸 + 전역 카드 CSS.
홈 «마이 대시보드» 탭군에 **여행 스케치** — 국가별 데모 카드.
홈에서는 시장·생활·개발 탭을, 학사정보에서는 명문대·초등·예비 중등을 둡니다.
상단 제목·소개 후 탭 영역이 이어집니다.
- 날씨: Open-Meteo (API 키 불필요)
- 환율: Frankfurter/ECB (API 키 불필요)
- 뉴스: 연합 RSS + Hacker News (API 키 불필요)
- 시계: 주요 도시 시각 + NYSE 정규장 여부(대략, 공휴일 미반영)
- GitHub: 큐레이션 링크 + Search API (선택 GITHUB_TOKEN)
- 주식: 마이 대시보드 탭 — yfinance + Plotly 캔들 (사이드바 종목 선택·기간)
- 교육·입시: 명문대 진학·입시 관련 공식·포털·미디어 링크 모음 탭
- 초등 학부모: 초등 학사·교육청·급식·방과후 등 필수 정보 사이트 모음 탭
- 예비 중등 가이드: 중학 입학·학구·학교 정보·학습·적응까지 학부모 링크·설명 탭
- 에이전트: OPENAI_API_KEY 있으면 OpenAI, 없으면 로컬 규칙 응답
- 네트워크 불가 시에도 UI 확인 가능: 날씨·환율·뉴스·GitHub 검색·주가 탭은 **내장 샘플 데이터**로 폴백
- 인코딩: 본 파일 UTF-8 저장 전제 · 한글 CSV는 utf-8-sig(BOM)로 내보냄(Excel 호환)
- 화장품 가격비교: 채널별 **샘플 표** + 공식몰 링크(실시간 가격 미연동)
- 컴퓨터 가격비교: 제품군별 **샘플 표** + 가격 비교 사이트 링크(실시간 미연동)
"""

from __future__ import annotations

import hashlib
import html
import json
import math
import os
import re
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import streamlit as st

try:
    from streamlit_option_menu import option_menu
except ImportError:
    option_menu = None  # type: ignore[misc, assignment]

try:
    import pandas as pd
except ModuleNotFoundError:
    pd = None  # type: ignore[misc, assignment]

try:
    import yfinance as yf
except ModuleNotFoundError:
    yf = None  # type: ignore[misc, assignment]

try:
    import plotly.graph_objects as go
except ModuleNotFoundError:
    go = None  # type: ignore[misc, assignment]

KST = ZoneInfo("Asia/Seoul")
APP_DISPLAY_TITLE = "생활 정보 포털"

# 섹터 요약 대시보드 막대 차트 — 코스피·코스닥·테마 공통 파스텔 팔레트
_SECTOR_DASHBOARD_PASTEL_COLORS: tuple[str, ...] = (
    "#f9c4d2",  # blush rose
    "#fde68a",  # butter
    "#bbf7d0",  # mint
    "#c4d9ff",  # periwinkle
    "#a5f3fc",  # sky
    "#fbcfe8",  # pink mist
    "#e9d5ff",  # lilac
    "#fed7aa",  # peach
    "#99f6e4",  # aqua
    "#d9f99d",  # lime sorbet
)


def _sector_dashboard_bar_colors(n: int) -> list[str]:
    if n <= 0:
        return []
    pal = _SECTOR_DASHBOARD_PASTEL_COLORS
    return [pal[i % len(pal)] for i in range(n)]


def _file_mtime_str_kst(path: Path, fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    """파일 mtime(UTC 기준 시각)을 KST로 표시. 서버 TZ가 UTC여도 payload와 같은 눈대장이 됨."""

    import datetime as _dt

    try:
        m = path.stat().st_mtime
        return (
            _dt.datetime.fromtimestamp(m, tz=_dt.timezone.utc)
            .astimezone(KST)
            .strftime(fmt)
        )
    except OSError:
        return "-"


def _st_try_border_container() -> Any:
    """테두리 컨테이너(border 미지원 빌드는 일반 container). 카드형 블록 공통."""

    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _tabular_row_count(data: Any) -> int:
    """`st.dataframe`에 넘기는 DataFrame·Styler·행 dict 리스트 등의 행 수."""
    if data is None:
        return 0
    if isinstance(data, list):
        return len(data)
    inner = getattr(data, "data", None)
    if inner is not None and hasattr(inner, "shape"):
        try:
            return int(inner.shape[0])
        except (TypeError, ValueError):
            pass
    if hasattr(data, "shape"):
        try:
            return int(data.shape[0])
        except (TypeError, ValueError):
            pass
    try:
        return len(data)
    except TypeError:
        return 0


def _st_dataframe_all_rows(data: Any, **kwargs: Any) -> None:
    """
    표 안 세로 스크롤을 최소화하고 종목·행을 한꺼번에 보이게 함.
    Streamlit 기본(height 생략 ≈ auto)은 약 10행만 보여 안쪽 스크롤이 생김 → `content` 사용.
    """
    opts: dict[str, Any] = {"use_container_width": True, "hide_index": True}
    opts.update(kwargs)
    try:
        st.dataframe(data, height="content", **opts)
    except TypeError:
        n = _tabular_row_count(data)
        px = min(10000, max(120, 44 + 34 * (n + 1)))
        st.dataframe(data, height=px, **opts)


def _df_to_csv_utf8_sig_bytes(df: Any) -> bytes:
    """pandas DataFrame → 한글·컬럼명 보존 CSV 바이트(Excel 호환 BOM 포함)."""

    return df.to_csv(encoding="utf-8-sig").encode("utf-8-sig")


# 글로벌 시각 탭 — 지도 표시용 (이름, IANA TZ, 위도, 경도, 한 줄 역할)
INVESTMENT_WORLD_HUBS: list[tuple[str, str, float, float, str]] = [
    ("서울", "Asia/Seoul", 37.5665, 126.9780, "코스피·코스닥·현지 매매"),
    ("도쿄", "Asia/Tokyo", 35.6762, 139.6503, "아시아 개장·엔·반도체 심리"),
    ("홍콩", "Asia/Hong_Kong", 22.3193, 114.1694, "H주·중국 유동성·ADR 연결"),
    ("상해", "Asia/Shanghai", 31.2304, 121.4737, "A주·무역·제조 뉴스"),
    ("런던", "Europe/London", 51.5074, -0.1278, "FX·유럽장·한국 아침에 겹침"),
    ("뉴욕", "America/New_York", 40.7128, -74.0060, "NYSE·나스닥·글로벌 레짐"),
    ("시카고", "America/Chicago", 41.8781, -87.6298, "CME 선물·변동성"),
    ("그리니치(UTC)", "UTC", 51.4769, -0.0005, "협정세계시 기준"),
]

# 주식 분석 — 드롭다운 프리셋 (야후 파이낸스 심볼)
STOCK_TICKER_PRESETS: list[tuple[str, str]] = [
    ("AAPL", "Apple"),
    ("MSFT", "Microsoft"),
    ("GOOGL", "Alphabet A"),
    ("NVDA", "NVIDIA"),
    ("META", "Meta"),
    ("AMZN", "Amazon"),
    ("TSLA", "Tesla"),
    ("^GSPC", "S&P 500"),
    ("^IXIC", "NASDAQ 종합"),
    ("^DJI", "다우존스"),
    ("005930.KS", "삼성전자"),
    ("000660.KS", "SK하이닉스"),
    ("035420.KS", "NAVER"),
    ("035720.KS", "카카오"),
    ("051910.KS", "LG화학"),
    ("005380.KS", "현대차"),
    ("006400.KS", "삼성SDI"),
    ("069500.KS", "KODEX 200"),
    ("QQQ", "Invesco QQQ"),
    ("VOO", "Vanguard S&P500 ETF"),
]

_STOCK_PICK_CUSTOM = "직접 입력…"


def _stock_ticker_select_labels() -> tuple[list[str], dict[str, str]]:
    """selectbox 표시문 → 야후 심볼 (직접 입력은 __custom__)."""
    rows = [f"{sym} — {desc}" for sym, desc in STOCK_TICKER_PRESETS]
    m = {rows[i]: STOCK_TICKER_PRESETS[i][0] for i in range(len(rows))}
    rows.append(_STOCK_PICK_CUSTOM)
    m[_STOCK_PICK_CUSTOM] = "__custom__"
    return rows, m


def nyse_regular_session_hint() -> tuple[str, str]:
    """NYSE 정규장(현지 월–금 09:30–16:00 ET) 기준 안내. 미국 공휴일·조기 폐장 미반영."""
    ny = datetime.now(ZoneInfo("America/New_York"))
    if ny.weekday() >= 5:
        return "주말 · 정규장 휴장", "다음 개장은 뉴욕 시각 평일 09:30부터입니다."
    minutes = ny.hour * 60 + ny.minute
    open_m, close_m = 9 * 60 + 30, 16 * 60
    loc = ny.strftime("%H:%M")
    if minutes < open_m:
        return "개장 전 (현지 평일)", f"뉴욕 {loc} · 정규장 09:30–16:00 ET"
    if minutes < close_m:
        return "정규장 진행 중 (현지 평일)", f"뉴욕 {loc} · 16:00 ET 마감 예정 (공휴일 제외 안 함)"
    return "정규장 마감 후 (현일)", f"뉴욕 {loc} · 프리/애프터는 별도 세션"


# 도시 프리셋 (위도, 경도, 표시명)
CITY_PRESETS: dict[str, tuple[float, float, str]] = {
    "서울": (37.5665, 126.9780, "서울"),
    "부산": (35.1796, 129.0756, "부산"),
    "대구": (35.8714, 128.6014, "대구"),
    "인천": (37.4563, 126.7052, "인천"),
    "광주": (35.1595, 126.8526, "광주"),
    "대전": (36.3504, 127.3845, "대전"),
    "제주": (33.4996, 126.5312, "제주"),
}

# GitHub — 홈랩·도구·재테크 등 (40대 남성·개발자 취향 위주 큐레이션, 직접 선별)
CURATED_GITHUB: list[dict] = [
    {
        "title": "🏠 NAS · 홈랩 · 자기 호스팅",
        "items": [
            {"t": "awesome-selfhosted", "d": "집 서버에 올릴 만한 서비스 대 catalog", "u": "https://github.com/awesome-selfhosted/awesome-selfhosted"},
            {"t": "awesome-sysadmin", "d": "시스쿨·백업·모니터링 실무 링크 모음", "u": "https://github.com/n1trux/awesome-sysadmin"},
            {"t": "linuxserver / docker 이미지", "d": "미디어·VPN·유틸 컨테이너 풀세트", "u": "https://github.com/linuxserver"},
            {"t": "Jellyfin", "d": "오픈소스 미디어 서버 (Plex 대안)", "u": "https://github.com/jellyfin/jellyfin"},
            {"t": "Home Assistant", "d": "스마트홈 통합 (브랜드 섞어 쓰기)", "u": "https://github.com/home-assistant/core"},
            {"t": "immich", "d": "구글포토 대체 사진 백업·얼굴인식", "u": "https://github.com/immich-app/immich"},
        ],
    },
    {
        "title": "💰 데이터 · 퀀트 · 재테크 코드",
        "items": [
            {"t": "pandas", "d": "표 데이터 분석 표준", "u": "https://github.com/pandas-dev/pandas"},
            {"t": "yfinance", "d": "야후 파이낸스 시세 (개인 프로젝트에 자주 씀)", "u": "https://github.com/ranaroussi/yfinance"},
            {"t": "QuantLib", "d": "금융 공학·옵션·채권 도구킷", "u": "https://github.com/lballabio/QuantLib"},
            {"t": "Backtrader", "d": "백테스트 프레임워크", "u": "https://github.com/mementum/backtrader"},
            {"t": "Lean (QuantConnect)", "d": "알고 트레이딩 엔진 (C#/Python)", "u": "https://github.com/QuantConnect/Lean"},
            {"t": "Ghostfolio", "d": "포트폴리오 추적·성과 (자기호스팅)", "u": "https://github.com/ghostfolio/ghostfolio"},
        ],
    },
    {
        "title": "🛠️ 터미널 · 생산성 · 개발환경",
        "items": [
            {"t": "Oh My Zsh", "d": "zsh 설정·플러그인 생태계", "u": "https://github.com/ohmyzsh/ohmyzsh"},
            {"t": "Starship", "d": "크로스플랫폼 미니멀 프롬프트 · https://starship.rs", "u": "https://github.com/starship/starship"},
            {"t": "lazygit", "d": "터미널에서 Git을 빠르게", "u": "https://github.com/jesseduffield/lazygit"},
            {"t": "fzf", "d": "퍼지 검색 (히스토리·파일)", "u": "https://github.com/junegunn/fzf"},
            {"t": "Obsidian (커뮤니티)", "d": "PKM — 플러그인·테마는 GitHub 생태계", "u": "https://github.com/obsidianmd/obsidian-releases"},
        ],
    },
    {
        "title": "💪 건강 · 러닝 · 기록 (오픈소스)",
        "items": [
            {"t": "wger", "d": "운동·식단 로그 (자기호스팅)", "u": "https://github.com/wger-project/wger"},
            {"t": "FitTrackee", "d": "러닝·사이클 GPS 기록", "u": "https://github.com/SamR1/FitTrackee"},
            {"t": "Tandoor", "d": "레시피 관리·식단 계획", "u": "https://github.com/TandoorRecipes/recipes"},
        ],
    },
    {
        "title": "🎮 클래식 · 에뮬 · 합법적 보존",
        "items": [
            {"t": "RetroArch", "d": "멀티 에뮬 프론트엔드 (라이선스 준수 ROM은 본인 책임)", "u": "https://github.com/libretro/RetroArch"},
            {"t": "PCSX2", "d": "PS2 에뮬 (공식 오픈소스)", "u": "https://github.com/PCSX2/pcsx2"},
            {"t": "Dolphin", "d": "GameCube / Wii 에뮬", "u": "https://github.com/dolphin-emu/dolphin"},
        ],
    },
    {
        "title": "📖 독서 · 전자책 · 미디어",
        "items": [
            {"t": "calibre", "d": "전자책 라이브러리 관리", "u": "https://github.com/kovidgoyal/calibre"},
            {"t": "Kavita", "d": "만화·소설 서버 (자기호스팅)", "u": "https://github.com/Kareadita/Kavita"},
            {"t": "Audiobookshelf", "d": "오디오북·팟캐스트 서버", "u": "https://github.com/advplyr/audiobookshelf"},
        ],
    },
]

# 명문대 진학·입시 참고용 링크 (공식·포털·미디어 등 — 이용 전 각 사이트 최신 안내 확인)
# parent: 학부모 입장에서 '왜 쓰는지'·'무엇을 볼 수 있는지' 안내
EDU_ADMISSION_SITES: list[dict] = [
    {
        "title": "📰 입시 뉴스 · 미디어",
        "items": [
            {
                "t": "베리타스알파",
                "d": "입시·교육 뉴스·분석을 빠르게 파악",
                "u": "https://www.veritas-a.com/",
                "parent": """**왜 필요할까요?** 대입 일정·전형 방식·고교·지역 교육 이슈가 수시로 바뀝니다. 뉴스만으로 확정 판단은 어렵지만, **무슨 논의가 도는지** 먼저 잡기 좋습니다.

**무엇을 얻을 수 있나요?** 기사·해설로 최근 입시 흐름, 정책 키워드, 학과·대학 동향을 빠르게 훑을 수 있습니다. 자녀와 상담·학교 질문을 정리할 때도 참고가 됩니다.""",
            },
            {
                "t": "교육부",
                "d": "국가 교육 정책·공식 발표의 기준점",
                "u": "https://www.moe.go.kr/",
                "parent": """**왜 필요할까요?** 학제·평가·개편 등 **공식 근거**는 교육부 보도자료·안내가 우선입니다. 카페·커뮤니티 말만으로 결정하면 날짜·표현이 어긋날 수 있습니다.

**무엇을 얻을 수 있나요?** 보도자료, 계열별·연도별 안내, 통합 검색으로 정책 원문과 요약 링크를 확인할 수 있습니다. 학교 안내와 교차 검증할 때 필수입니다.""",
            },
        ],
    },
    {
        "title": "🗂️ 진학 정보 포털 · 방송",
        "items": [
            {
                "t": "어디가 (Adiga)",
                "d": "대입 데이터·모의지원·트렌드 참고",
                "u": "https://www.adiga.kr/",
                "parent": """**왜 필요할까요?** 내신·모평 흐름, 학과별 경쟁 상대 감을 가져야 할 때 ‘숫자 감각’을 잡는 데 도움이 됩니다. 단, **최종 컷·결과는 매년 달라지므로** 참고용입니다.

**무엇을 얻을 수 있나요?** 통계·분석 자료, 모의지원 도구(운영 시점은 사이트 안내에 따름), 전형·학과 정보를 한곳에서 검색하기 쉽습니다.""",
            },
            {
                "t": "진학사",
                "d": "입시 정보·상담·행사 등 종합 포털",
                "u": "https://www.jinhak.com/",
                "parent": """**왜 필요할까요?** 원서 전까지 **학과 구조·학교 특성·일정**을 넓게 비교할 때 유용합니다. 여러 자료가 한 브랜드 안에 모여 있어 초보 학부모가 헤매기 적습니다.

**무엇을 얻을 수 있나요?** 학과·대학 정보, 행사·설명회 안내, 각종 가이드 콘텐츠 등을 활용할 수 있습니다. 유료 서비스는 약관·환불 규정을 꼭 확인하세요.""",
            },
            {
                "t": "EBSi",
                "d": "EBS 방송 연계 강의·입시 콘텐츠",
                "u": "https://www.ebsi.co.kr/",
                "parent": """**왜 필요할까요?** 교육비 부담을 줄이면서도 **공신력 있는 설명·강의**를 보고 싶을 때 적합합니다. 특히 개념 정리·국어·탐구 등 큰 틀을 잡을 때 자주 쓰입니다.

**무엇을 얻을 수 있나요?** 인터넷 강의·클립, 입시 관련 안내·편성 정보 등을 이용할 수 있습니다. 방송 일정은 매 학기마다 달라지니 사이트 공지를 확인하세요.""",
            },
            {
                "t": "유웨이어워즈",
                "d": "원서 접수·모의지원 등 포털성 서비스",
                "u": "https://www.uwayapply.com/",
                "parent": """**왜 필요할까요?** 실제 **원서 접수 시스템과 연계된 절차**를 미리 익혀 두면 당일 실수를 줄일 수 있습니다. ‘언제 어떤 버튼이 나오는지’ 체험이 중요합니다.

**무엇을 얻을 수 있나요?** 서비스별로 원서·모의지원·일정 안내 등이 제공됩니다. 연도·학교별 세부는 해당 연도 공식 요강이 우선입니다.""",
            },
        ],
    },
    {
        "title": "🏛️ 공공 · 평가 · 통계",
        "items": [
            {
                "t": "한국교육과정평가원 (KICE)",
                "d": "교육과정·평가 연구·수능 등 공식 자료",
                "u": "https://www.kice.re.kr/",
                "parent": """**왜 필요할까요?** ‘왜 이렇게 출제되나’ ‘성취기준은 무엇인가’를 보려면 연구기관 원문이 가장 안전합니다. 자극적인 유튜브만 보기보다 **공식 해설·연구**를 함께 보는 것이 좋습니다.

**무엇을 얻을 수 있나요?** 교육과정 해설, 평가 기준·연구 보고서, 수능 관련 공개 자료 등을 찾을 수 있습니다.""",
            },
            {
                "t": "한국교육개발원 (KEDI)",
                "d": "교육통계·정책 연구",
                "u": "https://www.kedi.re.kr/",
                "parent": """**왜 필요할까요?** 지역·단계별 교육 통계를 보면 **큰 그림**(진학률·규모 등)을 짚을 수 있습니다. 맞춤 입시 전략보다는 구조 이해용입니다.

**무엇을 얻을 수 있나요?** 통계 DB, 연구 보고서, 브리프 등 공개 자료를 검색할 수 있습니다.""",
            },
            {
                "t": "학교알리미",
                "d": "학교별 공시·**교복** 관련 안내·급식 등 — **배정(통학) 학교** 확인에 쓰는 공식 학교 정보",
                "u": "https://schoolinfo.go.kr/",
                "parent": """**왜 필요할까요?** 지원 전 **학교 규모·학생 수·급식·교복·학교 정보 공시** 등 객관 지표를 보고 싶을 때 사용합니다. 입학 설명회만 듣기보다 숫자와 함께 비교하면 대화가 명확해집니다.

**무엇을 얻을 수 있나요?** 학교별 공시 자료, 급식 정보 등 공개 범위 안에서 제공되는 항목을 조회할 수 있습니다. **통학·배정의 최종 규칙은 관할 교육청·학교 안내**가 우선입니다.""",
            },
            {
                "t": "한국대학교육협의회",
                "d": "대학 정책·통계·연구",
                "u": "https://www.kcue.or.kr/",
                "parent": """**왜 필요할까요?** 대학 쪽 제도·통계를 **기관 단위**로 볼 때 참고할 만합니다. 학부모가 깊게 파기보다는 ‘구조적 배경’ 확인용으로 쓰면 좋습니다.

**무엇을 얻을 수 있나요?** 연구·통계·간행물 등 공개 자료가 제공될 수 있습니다.""",
            },
        ],
    },
    {
        "title": "📚 인강 · 참고 (민간)",
        "items": [
            {
                "t": "이투스",
                "d": "인터넷 강의·입시 프로그램",
                "u": "https://www.etoos.com/",
                "parent": """**왜 필요할까요?** 학교·과외만으로 부족할 때 **과목별 보충**을 찾는 경우가 많습니다. 결제·환불·분반 규정은 반드시 약관을 읽어야 합니다.

**무엇을 얻을 수 있나요?** 인강·모의고사·패키지 상품 등 서비스별 안내가 제공됩니다. 우리 아이 학년·약점과 맞는지 상담 후 선택하세요.""",
            },
            {
                "t": "메가스터디",
                "d": "인강·모의고사 등 대형 브랜드",
                "u": "https://www.megastudy.net/",
                "parent": """**왜 필요할까요?** 전국 단위 브랜드라 **콘텐츠 양·일정**을 한번에 비교하기 쉽습니다. 과목 선택 전 무료 체험이 있는지 확인하면 좋습니다.

**무엇을 얻을 수 있나요?** 인강·평가·이벤트 등 브랜드별 서비스 안내를 받을 수 있습니다.""",
            },
            {
                "t": "메가엠디",
                "d": "메디컬·편입 등 특수 트랙 참고",
                "u": "https://www.megamd.co.kr/",
                "parent": """**왜 필요할까요?** 의치한·수의·약학 등 **트랙이 다른 진로**를 검토할 때 별도 정보가 필요합니다. 일반 인문 진학과 요건이 완전히 다릅니다.

**무엇을 얻을 수 있나요?** 해당 분야 상품·설명회·자료 안내를 확인할 수 있습니다. 최종 판단은 대학 공식 요강입니다.""",
            },
        ],
    },
]

# 초등학교 학부모용 학사·행정 정보 (공식 위주 — 세부 일정·배정은 시·도 교육청·학교 안내 준수)
ELEMENTARY_PARENT_SITES: list[dict] = [
    {
        "title": "📋 나이스 (NEIS) · 학부모 서비스",
        "items": [
            {
                "t": "나이스 학부모 서비스",
                "d": "성적·출결·생활기록 열람·알림 — 가정에서 **성적·출결 관리**를 시작할 때 쓰는 공식 창구 (유·초·중·고)",
                "u": "https://parents.neis.go.kr/",
                "parent": """**왜 필요할까요?** 학교와 연계된 **출결·성적 통지**를 받고 생활기록을 보려면 학부모 서비스가 기준입니다. 학년이 바뀔수록 알림이 많아지니, **가정에서 확인·관리하는 흐름**을 미리 잡아 두면 좋습니다.

**무엇을 얻을 수 있나요?** 학교가 제공하는 범위 안에서 통지 열람·알림 설정 등을 하며, 공지에 따라 **성적·출결 관리 시작** 절차를 따라가면 됩니다.""",
            },
        ],
    },
    {
        "title": "📣 e-알리미 · 아이알리미 (학교 소통)",
        "items": [
            {
                "t": "e-알리미",
                "d": "가정통신문·학교 공지·알림장 등 스마트 공지 (해당 학교가 도입한 경우)",
                "u": "https://www.ealimi.com/",
            },
            {
                "t": "아이알리미",
                "d": "등하교 알림·학교 공지 안내 등 (학교·기관과 계약·안내 시 이용)",
                "u": "https://www.jtts.co.kr/",
            },
        ],
    },
    {
        "title": "🏛️ 교육부 · 학교 정보",
        "items": [
            {"t": "교육부", "d": "유·초·중등 정책·공지·학사 안내", "u": "https://www.moe.go.kr/"},
            {
                "t": "학교알리미",
                "d": "학교별 공시·**교복** 안내·급식 등 — **배정(통학) 학교** 정보 확인",
                "u": "https://schoolinfo.go.kr/",
                "parent": """**왜 필요할까요?** **교복·운영 방식** 등은 학교 공시와 안내에 따라 다릅니다. 후보 학교를 고를 때 공식 정보를 함께 보면 준비가 수월합니다.

**무엇을 얻을 수 있나요?** 공시 범위 안의 학교 기본정보·급식·교복 관련 게재 분 등을 조회할 수 있습니다. **입학 배정·학구**는 교육청·학교 최신 공지를 확인하세요.""",
            },
            {"t": "한국교육학술정보원 (KERIS)", "d": "교육정보화·디지털교과서 등 안내", "u": "https://www.keris.or.kr/"},
        ],
    },
    {
        "title": "🏫 시·도 교육청 (예시)",
        "items": [
            {"t": "서울특별시교육청", "d": "서울 소재 학교·학사·입학 일정", "u": "https://www.sen.go.kr/"},
            {"t": "경기도교육청", "d": "경기 지역 학교·통합안내", "u": "https://www.goegy.kr/"},
            {"t": "부산광역시교육청", "d": "부산 지역 학교·공지", "u": "https://pen.go.kr/"},
            {"t": "인천광역시교육청", "d": "인천 지역 학교·공지", "u": "https://www.ice.go.kr/"},
        ],
    },
    {
        "title": "📺 방송 · 학습 · 방과후",
        "items": [
            {"t": "EBS 초등", "d": "방송 연계 학습·교양 콘텐츠", "u": "https://primary.ebs.co.kr/"},
            {"t": "방과후학교 정보시스템", "d": "방과후 프로그램·운영 안내(학교별 연계)", "u": "https://www.afterschool.go.kr/"},
            {
                "t": "에듀넷·티-클리어 (T-Clear)",
                "d": "**개정 교육과정** 안내·교수학습·평가 정보 등 공교육 통합 포털 (KERIS)",
                "u": "https://www.edunet.net/",
                "parent": """**왜 필요할까요?** 학교 안내와 맞추려면 **개정 교육과정·성취기준** 흐름을 짚어 두는 것이 좋습니다.

**무엇을 얻을 수 있나요?** 티-클리어 등에서 공개되는 자료·안내를 검색해 볼 수 있습니다.""",
            },
        ],
    },
    {
        "title": "🍱 급식 · 영양",
        "items": [
            {"t": "어린이급식관리 지원센터", "d": "급식·영양 정보·식단 참고", "u": "https://childschoolmeal.korea.kr/"},
            {"t": "식품안전나라 (원산지 등)", "d": "식재료·표시 정보 조회", "u": "https://www.foodsafetykorea.go.kr/"},
        ],
    },
    {
        "title": "💉 건강 · 안전 · 권리",
        "items": [
            {"t": "예방접종 도우미", "d": "국가예방접종 일정·기관 조회", "u": "https://nip.kdca.go.kr/"},
            {"t": "학교폭력 예방·신고", "d": "학교폭력 관련 안내·신고 안내", "u": "https://www.schoolviolence.go.kr/"},
            {"t": "정부24", "d": "민원·증명·주민등록 등 행정 서비스", "u": "https://www.gov.kr/"},
        ],
    },
]

# 예비 중등 학부모용 — 중학 입학·학교 정보·학습·적응 (공식 위주 — 배정·학구는 시·도·학교 공지 최종 확인)
MIDDLE_SCHOOL_PREP_SITES: list[dict] = [
    {
        "title": "📋 입학·학구 · 어디서부터 보나요?",
        "items": [
            {
                "t": "교육부",
                "d": "유·초·중등 학제·정책·공지의 기준점",
                "u": "https://www.moe.go.kr/",
                "parent": """**왜 필요할까요?** 초등 졸업 후 **중학 배정·통학·학구**는 지역·연도마다 세부가 다릅니다. 카페 글보다 **교육청·학교 공지와 함께** 국가 단위 원칙을 짚어 두면 헷갈림이 줄어듭니다.

**무엇을 얻을 수 있나요?** 학제·평가·안내 자료 등 공식 발표와 검색으로 ‘큰 그림’을 확인한 뒤, 거주지 관할 교육청 입학 페이지로 이어가면 좋습니다.""",
            },
            {
                "t": "학교알리미",
                "d": "중학교별 공시·**교복** 안내·급식 등 — **배정(통학) 학교** 확인에 참고",
                "u": "https://schoolinfo.go.kr/",
                "parent": """**왜 필요할까요?** 배정받거나 후보를 좁힐 때 **학교 규모·학생 수·급식·교복·공시** 같은 객관 정보가 필요합니다. 설명회만 듣기보다 숫자와 함께 대화하면 자녀와 논의하기 쉽습니다.

**무엇을 얻을 수 있나요?** 학교유형·공시 자료·급식 등 공개 범위 안의 항목을 비교해 볼 수 있습니다. **배정·학구·통학** 세부는 해당 시·도 교육청·학교 최신 안내가 우선입니다.""",
            },
        ],
    },
    {
        "title": "🔗 나이스 · 학교 소통",
        "items": [
            {
                "t": "나이스 학부모 서비스",
                "d": "성적·출결·알림 — 중학 진학 후에도 **성적·출결 관리**를 가정에서 시작·유지할 때 쓰는 공식 창구",
                "u": "https://parents.neis.go.kr/",
                "parent": """**왜 필요할까요?** 중학에 올라가도 **출결·성적 통지·학교 알림**은 대개 나이스 기반으로 이어집니다. 미리 계정·알림을 정리해 두면 학년 전환 때 덜 분주합니다.

**무엇을 얻을 수 있나요?** 학교가 제공하는 범위 안에서 생활기록·통지 열람, 알림 설정 등을 하며, 공지에 따라 **성적·출결 관리**를 가정에서 어떻게 확인할지 시작할 때 참고하면 됩니다.""",
            },
            {
                "t": "e-알리미",
                "d": "가정통신문·학교 공지 (해당 학교 도입 시)",
                "u": "https://www.ealimi.com/",
                "parent": """**왜 필요할까요?** 중학교에서도 가정통신문·공지를 **앱으로 받는 경우**가 많습니다. 학교 안내에 따라 설치·알림 설정을 맞춰 두면 놓치는 일이 줄어듭니다.

**무엇을 얻을 수 있나요?** 학교가 제공하는 공지·자료 열람(기능은 학교·계약에 따라 상이).""",
            },
        ],
    },
    {
        "title": "🏛️ 시·도 교육청 — 입학·학사 공지",
        "items": [
            {
                "t": "서울특별시교육청",
                "d": "서울 소재 중등 학사·입학·통합 안내",
                "u": "https://www.sen.go.kr/",
                "parent": """**왜 필요할까요?** **중학 배정·신청 일정·제출 서류**는 시·도 교육청·구청 안내가 최종 기준입니다. 맞벌이 부모도 미리 달력에 넣어 두면 좋습니다.

**무엇을 얻을 수 있나요?** 입학·학사 공지, 자주 묻는 질문, 해당 연도 일정 링크 등을 확인할 수 있습니다.""",
            },
            {
                "t": "경기도교육청",
                "d": "경기 지역 중등 학사·통합 안내",
                "u": "https://www.goegy.kr/",
                "parent": """**왜 필요할까요?** 경기는 학교·지역 단위 안내가 세분화되는 경우가 많아 **교육청 본청 공지**와 함께 관할 안내를 챙기는 것이 안전합니다.

**무엇을 얻을 수 있나요?** 통합 공지, 입학 관련 자료, 교육청 산하 학교 정보로 들어가는 링크 등을 참고할 수 있습니다.""",
            },
            {
                "t": "부산광역시교육청",
                "d": "부산 지역 중등 공지",
                "u": "https://pen.go.kr/",
                "parent": """**왜 필요할까요?** 지역·학교군마다 일정 표현이 다르니 **관할 교육청**에서 원문을 확인하는 습관이 좋습니다.

**무엇을 얻을 수 있나요?** 학사·입학·교육청 소식 등 공식 게시를 따라갈 수 있습니다.""",
            },
            {
                "t": "인천광역시교육청",
                "d": "인천 지역 중등 공지",
                "u": "https://www.ice.go.kr/",
                "parent": """**왜 필요할까요?** 전학·이주 예정이 있다면 **현 거주지 기준**과 **이전 후 기준** 안내를 각각 확인해야 혼선이 적습니다.

**무엇을 얻을 수 있나요?** 인천 지역 입학·학사 관련 공식 안내와 고시를 찾을 수 있습니다.""",
            },
        ],
    },
    {
        "title": "📚 학습 · 방과후 · 진로 예비",
        "items": [
            {
                "t": "EBS 중학",
                "d": "**예비 중1** 대비 방송 연계 학습·교양 (중학 과정)",
                "u": "https://mid.ebs.co.kr/",
                "parent": """**왜 필요할까요?** 중학 교과·생활 리듬을 **부담 없이 미리 맛보고 싶을 때** 공영 방송 연계 콘텐츠가 도움이 됩니다. **예비 중1** 단계에서는 개념만 넓히는 용도로도 무난합니다.

**무엇을 얻을 수 있나요?** 과목·단원별 클립·편성 정보 등을 활용할 수 있습니다. 편성은 학기마다 바뀌니 공지를 확인하세요.""",
            },
            {
                "t": "방과후학교 정보시스템",
                "d": "방과후 프로그램·운영 안내 (학교별 연계)",
                "u": "https://www.afterschool.go.kr/",
                "parent": """**왜 필요할까요?** 중학에선 **동아리·방과후** 선택이 생활 패턴과 비용에 영향을 줍니다. 학교별 모집 방식을 미리 구조만이라도 알아 두면 좋습니다.

**무엇을 얻을 수 있나요?** 시스템 소개·운영 개요 등 공통 정보를 보고, 세부는 재학(예정) 학교 안내를 따르면 됩니다.""",
            },
            {
                "t": "에듀넷·티-클리어 (T-Clear)",
                "d": "교육과정·평가·학습 자료 (공교육 포털)",
                "u": "https://www.edunet.net/",
                "parent": """**왜 필요할까요?** ‘중학 성취기준이 뭔지’ **공식 자료**를 보고 싶을 때 유용합니다. 내신·평가 세부는 학교가 안내하지만, 과정 이해에는 포털이 도움이 됩니다.

**무엇을 얻을 수 있나요?** 교수학습 자료, 교육과정 관련 정보 등을 검색할 수 있습니다.""",
            },
            {
                "t": "한국교육학술정보원 (KERIS)",
                "d": "교육정보화·디지털 교과서 등",
                "u": "https://www.keris.or.kr/",
                "parent": """**왜 필요할까요?** 학교에서 안내하는 **온라인 학습·디지털 교과서** 맥락을 짚고 싶을 때 참고할 만합니다.

**무엇을 얻을 수 있나요?** 정보화 정책·서비스 안내 등 공식 정보를 확인할 수 있습니다.""",
            },
        ],
    },
    {
        "title": "💙 적응 · 상담 · 안전",
        "items": [
            {
                "t": "학교폭력 예방·신고",
                "d": "신고·상담 안내 (학교폭력 대응)",
                "u": "https://www.schoolviolence.go.kr/",
                "parent": """**왜 필요할까요?** 새 학교에 들어가면 관계 스트레스가 생기기 쉽습니다. **신고 경로·보호 절차**를 미리 가족이 함께 알아두면 위기 때 진정으로 도움이 됩니다.

**무엇을 얻을 수 있나요?** 신고 방법, FAQ, 관련 법·제도 안내 등을 확인할 수 있습니다.""",
            },
            {
                "t": "청소년 사이버 상담 (1388)",
                "d": "청소년 전화·채팅 상담 안내",
                "u": "https://www.cyber1388.kr/",
                "parent": """**왜 필요할까요?** 사춘기·학교 적응 문제는 자녀가 혼자 삭이기 어렵습니다. **가족이 숫자(1388)·사이트만이라도 공유**해 두면 도움이 됩니다.

**무엇을 얻을 수 있나요?** 상담 이용 방법, 채팅·전화 안내 등 공식 정보를 얻을 수 있습니다.""",
            },
            {
                "t": "정부24",
                "d": "민원·증명 등 행정 (주민등록·가족관계 등)",
                "u": "https://www.gov.kr/",
                "parent": """**왜 필요할까요?** 입학·전학·서류 제출 과정에서 **증명·등본**이 필요할 때가 많습니다. 동네 주민센터 전에 온라인 가능 여부를 보면 시간을 줄일 수 있습니다.

**무엇을 얻을 수 있나요?** 민원 신청·발급 안내, 증명 종류별 절차 등을 확인할 수 있습니다.""",
            },
        ],
    },
]

# 학습준비 — 방송·포털·과정 이해 (학사 행정 링크는 «학사정보» 탭)
LEARNING_PREP_SITES: list[dict] = [
    {
        "title": "📺 초등 연계 · 방송·학습",
        "items": [
            {
                "t": "EBS 초등",
                "d": "방송 연계 학습·교양 콘텐츠",
                "u": "https://primary.ebs.co.kr/",
                "parent": """**왜 필요할까요?** 교과보조·독서 습관·교양을 **가정에서 부담 적게** 챙길 때 공영 콘텐츠가 무난합니다.

**무엇을 얻을 수 있나요?** 학년·주제별 클립과 편성 정보를 참고할 수 있습니다.""",
            },
            {
                "t": "방과후학교 정보시스템",
                "d": "방과후 프로그램·운영 안내 (학교별 연계)",
                "u": "https://www.afterschool.go.kr/",
                "parent": """**왜 필요할까요?** 관심 활동·시간대를 미리 알아 두면 학기 초 선택이 수월합니다.

**무엇을 얻을 수 있나요?** 공통 안내와 운영 개요를 보고, 신청·모집은 재학 학교 공지를 따르면 됩니다.""",
            },
            {
                "t": "에듀넷·티-클리어 (T-Clear)",
                "d": "**개정 교육과정** 안내·교수학습·평가 정보 등 공교육 통합 포털",
                "u": "https://www.edunet.net/",
                "parent": """**왜 필요할까요?** 가정에서 학교 설명과 맞추려면 **개정 교육과정·성취기준** 맥락을 짚어 두는 것이 좋습니다.

**무엇을 얻을 수 있나요?** 티-클리어 등에서 공개되는 자료·안내를 검색해 볼 수 있습니다.""",
            },
        ],
    },
    {
        "title": "📚 중등 연계 · 학습·진로 예비",
        "items": [
            {
                "t": "EBS 중학",
                "d": "**예비 중1**에 대비한 방송 연계 학습·교양 (EBS 중학 과정)",
                "u": "https://mid.ebs.co.kr/",
                "parent": """**왜 필요할까요?** 중학 교과 흐름·용어를 가볍게 맛보고 싶을 때 활용하기 좋습니다. **예비 중1** 단계에서는 과목 리듬·학습 습관을 넓히는 용도로 보시면 부담이 적습니다.

**무엇을 얻을 수 있나요?** 과목·단원별 클립과 편성 안내를 참고할 수 있습니다. 편성은 학기마다 바뀌니 공지를 확인하세요.""",
            },
            {
                "t": "방과후학교 정보시스템",
                "d": "중학에서의 방과후·프로그램 안내 (학교별 연계)",
                "u": "https://www.afterschool.go.kr/",
                "parent": """**왜 필요할까요?** 중학에선 동아리·방과후 선택이 시간·비용에 영향을 줍니다.

**무엇을 얻을 수 있나요?** 공통 구조를 본 뒤 학교별 모집 공지를 확인하세요.""",
            },
            {
                "t": "에듀넷·티-클리어 (T-Clear)",
                "d": "**개정 교육과정** 안내·중등 교수학습·평가 자료",
                "u": "https://www.edunet.net/",
                "parent": """**왜 필요할까요?** 내신·수행은 학교마다 다르지만, **개정 교육과정·성취기준** 이해에는 포털이 도움이 됩니다.

**무엇을 얻을 수 있나요?** 교수학습 자료와 과정 정보를 검색해 볼 수 있습니다.""",
            },
            {
                "t": "한국교육학술정보원 (KERIS)",
                "d": "교육정보화·디지털 교과서 등",
                "u": "https://www.keris.or.kr/",
                "parent": """**왜 필요할까요?** 학교에서 안내하는 디지털 학습맥락을 짚고 싶을 때 참고합니다.

**무엇을 얻을 수 있나요?** 정책·서비스 공식 안내를 확인할 수 있습니다.""",
            },
        ],
    },
    {
        "title": "🎯 진학 이후 참고 (고등·대입)",
        "items": [
            {
                "t": "EBSi",
                "d": "EBS 방송 연계 강의·입시 콘텐츠",
                "u": "https://www.ebsi.co.kr/",
                "parent": """**왜 필요할까요?** 중등 이후 진로를 미리 넓게 볼 때 공신력 있는 무료·저비용 콘텐츠가 있습니다.

**무엇을 얻을 수 있나요?** 강의·클립·입시 관련 안내를 검색할 수 있습니다.""",
            },
            {
                "t": "어디가 (Adiga)",
                "d": "진학 데이터·모의지원 등 참고 포털",
                "u": "https://www.adiga.kr/",
                "parent": """**왜 필요할까요?** ‘나중에 고등·대입 때 어떤 데이터가 공개되는지’ 감만 잡고 싶을 때 참고합니다.

**무엇을 얻을 수 있나요?** 통계·도구(운영 시점은 사이트 안내) 등을 활용할 수 있습니다.""",
            },
        ],
    },
]

# GitHub Search API — 프리셋 (Star·최근 활동 위주)
GITHUB_SEARCH_PRESETS: list[tuple[str, str]] = [
    ("홈랩 / self-hosted (Star)", "topic:self-hosted stars:>2500"),
    ("Docker · Compose 실무", "docker-compose stars:>800 pushed:>2025-09-01"),
    ("Python 데이터·ML 도구", "language:python stars:>8000 pushed:>2025-06-01"),
    ("퀀트·트레이딩·포트폴리오", "(quant OR backtrader OR portfolio) language:python stars:>600"),
    ("터미널·CLI 유틸", "topic:cli language:rust OR language:go stars:>3000"),
    ("게임 엔진·데모 (취미)", "topic:game-engine stars:>2000"),
    ("모바일 없이 쓰는 웹앱 PWA", "topic:pwa stars:>1500 pushed:>2025-01-01"),
]

WMO_CODES: dict[int, str] = {
    0: "맑음",
    1: "대체로 맑음",
    2: "약간 흐림",
    3: "흐림",
    45: "안개",
    48: "안개(서리)",
    51: "이슬비 약함",
    53: "이슬비",
    55: "이슬비 강함",
    61: "비 약함",
    63: "비",
    65: "폭우",
    71: "눈 약함",
    73: "눈",
    75: "폭설",
    80: "소나기 약함",
    81: "소나기",
    82: "폭우(소나기)",
    95: "뇌우",
    96: "뇌우(우박)",
    99: "강한 뇌우(우박)",
}

# 뉴스 브리핑 (RSS, 키 불필요)
NEWS_RSS_FEEDS: dict[str, str] = {
    "연합뉴스 경제": "https://www.yna.co.kr/rss/economy.xml",
    "연합뉴스 IT·과학": "https://www.yna.co.kr/rss/it.xml",
}


def _sample_daily_dates_iso(n: int = 5) -> list[str]:
    d0 = date.today()
    return [(d0 + timedelta(days=i)).isoformat() for i in range(max(1, n))]


def sample_openmeteo_payload_for_city_key(city_key: str) -> dict[str, Any]:
    """Open-Meteo JSON과 동일한 키 구조의 내장 샘플(네트워크 없이 UI 검증용)."""
    profile: dict[str, tuple[float, int]] = {
        "서울": (13.8, 1),
        "부산": (15.4, 2),
        "대구": (14.9, 3),
        "인천": (13.2, 2),
        "광주": (15.0, 2),
        "대전": (14.1, 1),
        "제주": (16.2, 1),
    }
    t0, wc0 = profile.get(city_key, (14.0, 0))
    times = _sample_daily_dates_iso(5)
    n = len(times)
    mx = [t0 + 4.0 + i * 0.35 for i in range(n)]
    mn = [t0 - 3.5 + i * 0.25 for i in range(n)]
    wcodes = [wc0, *[min(95, wc0 + i % 3) for i in range(1, n)]]
    return {
        "current": {
            "temperature_2m": t0,
            "relative_humidity_2m": 58,
            "apparent_temperature": t0 - 0.6,
            "weather_code": wc0,
            "wind_speed_10m": 11.4,
            "surface_pressure": 1013.8,
        },
        "daily": {
            "time": times,
            "weather_code": wcodes,
            "temperature_2m_max": mx,
            "temperature_2m_min": mn,
        },
        "_sample": True,
    }


# Frankfurter 형태의 내장 환율 샘플 (ECB 실시간과 무관)
SAMPLE_FX_USD_BASE: dict[str, Any] = {
    "amount": 1.0,
    "base": "USD",
    "date": "2026-04-25",
    "rates": {"KRW": 1395.42, "JPY": 152.33, "EUR": 0.9187},
}


# RSS 출처별 내장 헤드라인 (키는 NEWS_RSS_FEEDS 와 동일)
SAMPLE_NEWS_HEADLINES_BY_FEED: dict[str, list[dict[str, str]]] = {
    "연합뉴스 경제": [
        {
            "title": "[샘플] 글로벌 성장률 전망 조정… 시장은 단기 변동성 우려 (데모)",
            "url": "https://www.example.invalid/demo-economy-1",
        },
        {
            "title": "[샘플] 원화 변동성·금리 향방 관련 전문가 의견 정리 (데모)",
            "url": "https://www.example.invalid/demo-economy-2",
        },
        {
            "title": "[샘플] 소비·수출 지표 발표 앞두고 관련 업종 관심 (데모)",
            "url": "https://www.example.invalid/demo-economy-3",
        },
    ],
    "연합뉴스 IT·과학": [
        {
            "title": "[샘플] 생성형 AI 도구 도입 사례 — 보안·거버넌스 체크리스트 (데모)",
            "url": "https://www.example.invalid/demo-it-1",
        },
        {
            "title": "[샘플] 클라우드 비용 최적화 트렌드 요약 (데모)",
            "url": "https://www.example.invalid/demo-it-2",
        },
        {
            "title": "[샘플] 반도체 공급망·설비 투자 동향 스케치 (데모)",
            "url": "https://www.example.invalid/demo-it-3",
        },
    ],
}


# Hacker News 대체 샘플 (score 포함)
SAMPLE_HACKERNEWS_ITEMS: list[dict[str, Any]] = [
    {
        "title": "[샘플] Show HN: 로컬에서 돌리는 대시보드 모음 (데모)",
        "url": "https://news.ycombinator.com/item?id=0",
        "score": 214,
    },
    {
        "title": "[샘플] Ask HN: 나스 홈랩 스토리지 구성은 어떻게 하시나요? (데모)",
        "url": "https://news.ycombinator.com/item?id=0",
        "score": 156,
    },
    {
        "title": "[샘플] 오픈 데이터로 만든 생활 정보 위젯 리포지토리 (데모)",
        "url": "https://news.ycombinator.com/item?id=0",
        "score": 98,
    },
]


# GitHub Search API 실패 시 표시할 저장소 샘플 (검색 결과 형식과 동일)
SAMPLE_GITHUB_SEARCH_ROWS: list[dict[str, Any]] = [
    {
        "repo": "streamlit/streamlit",
        "stars": 42000,
        "lang": "Python",
        "설명": "Streamlit — 빠른 데이터 앱 프레임워크 (데모 행)",
        "url": "https://github.com/streamlit/streamlit",
    },
    {
        "repo": "pandas-dev/pandas",
        "stars": 46000,
        "lang": "Python",
        "설명": "데이터 분석용 고성능 자료구조 (데모 행)",
        "url": "https://github.com/pandas-dev/pandas",
    },
    {
        "repo": "microsoft/vscode",
        "stars": 170000,
        "lang": "TypeScript",
        "설명": "코드 편집기 — 확장 생태계 (데모 행)",
        "url": "https://github.com/microsoft/vscode",
    },
]


def sample_stock_ohlc_dataframe(start_d: date, end_d: date, ticker: str) -> Any:
    """야후 파이낸스 실패 시 캔들·메트릭용 결정적 난수 OHLCV (pandas 필요)."""
    if pd is None:
        return None
    try:
        import numpy as np
    except ModuleNotFoundError:
        return None
    idx = pd.date_range(start=start_d, end=end_d, freq="B")
    n = len(idx)
    if n < 1:
        return pd.DataFrame()
    t = ticker.strip().upper()
    base = 82000.0 if t.endswith(".KS") or t.endswith(".KQ") else 180.0
    seed = (hash(t) & 0xFFFFFFFF) ^ int(start_d.toordinal()) ^ int(end_d.toordinal())
    rng = np.random.default_rng(seed)
    r = rng.standard_normal(n) * 0.018
    close = base * np.exp(np.cumsum(r))
    open_ = np.empty(n)
    open_[0] = close[0]
    open_[1:] = close[:-1]
    high = np.maximum(open_, close) * (1.0 + rng.uniform(0.0, 0.006, n))
    low = np.minimum(open_, close) * (1.0 - rng.uniform(0.0, 0.006, n))
    vol = rng.integers(300_000, 9_000_000, size=n)
    df = pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": close, "Volume": vol.astype(float)},
        index=idx,
    )
    df.attrs["_sample"] = True
    return df


# 정식·합법 플랫폼만 (무료 회차, 광고 지원, 공공 도메인 등). 무단 스캔 사이트는 넣지 않음.
FREE_COMICS_SITES: list[dict] = [
    {
        "title": "🇰🇷 한국 · 웹툰 / 만화",
        "items": [
            {"t": "네이버 웹툰", "d": "무료 연재 다수(일부 유료 회차)", "u": "https://comic.naver.com/webtoon"},
            {"t": "카카오페이지 / 웹툰", "d": "무료·할인 회차 혼합", "u": "https://page.kakao.com/main?categoryId=6000"},
            {"t": "LINE 웹툰 (한국)", "d": "글로벌 웹툰 플랫폼 한국어", "u": "https://www.webtoons.com/ko/"},
            {"t": "레진코믹스", "d": "첫화 무료·이벤트 등(작품별 상이)", "u": "https://www.lezhin.com/ko"},
        ],
    },
    {
        "title": "🇯🇵 일본 · 정식 무료 연재",
        "items": [
            {"t": "MANGA Plus by SHUEISHA", "d": "점프 등 공식 무료 회차·동시 연재", "u": "https://mangaplus.shueisha.co.jp/"},
            {"t": "ComicWalker (KADOKAWA)", "d": "카도카와 계열 무료 만화", "u": "https://comic-walker.com/"},
            {"t": "BOOK☆WALKER", "d": "전자서점 · 무료/세일 코믹 코너", "u": "https://bookwalker.jp/"},
        ],
    },
    {
        "title": "🌐 글로벌 · 영어 등",
        "items": [
            {"t": "WEBTOON", "d": "무료 에피소드 위주 웹툰", "u": "https://www.webtoons.com/"},
            {"t": "Tapas", "d": "웹코믹 · 일부 무료 코인", "u": "https://tapas.io/"},
            {"t": "Crunchyroll Manga", "d": "애니 구독 연계 만화(지역·작품별)", "u": "https://www.crunchyroll.com/manga"},
            {"t": "Global LEZHIN", "d": "영문 등 글로벌 웹툰", "u": "https://www.lezhin.com/en"},
        ],
    },
    {
        "title": "📚 공공 도메인·보존 (합법 무료)",
        "items": [
            {"t": "Internet Archive — Comic Books", "d": "저작권 만료·공개된 자료 위주(국가별 다름)", "u": "https://archive.org/details/comicbooks"},
            {"t": "Digital Comic Museum", "d": "골든에이지 미국 코믹 일부 공개", "u": "https://digitalcomicmuseum.com/"},
        ],
    },
]


def wmo_label(code: int) -> str:
    return WMO_CODES.get(code, f"기상코드 {code}")


@st.cache_data(ttl=300, show_spinner=False)
def fetch_weather_cached(lat: float, lon: float) -> dict | None:
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": [
            "temperature_2m",
            "relative_humidity_2m",
            "apparent_temperature",
            "weather_code",
            "wind_speed_10m",
            "surface_pressure",
        ],
        "daily": ["weather_code", "temperature_2m_max", "temperature_2m_min"],
        "timezone": "auto",  # 좌표 기반 자동 타임존 — 전세계 도시 지원
        "forecast_days": 5,
    }
    try:
        r = requests.get(url, params=params, timeout=15)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_fx_usd_base() -> dict | None:
    """ECB 기준 환율(Frankfurter, API 키 불필요). USD 기준 KRW·JPY·EUR."""
    try:
        r = requests.get(
            "https://api.frankfurter.app/latest",
            params={"from": "USD", "to": "KRW,JPY,EUR"},
            timeout=15,
        )
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


@st.cache_data(ttl=3600, show_spinner=False)
def _fx_yahoo_krw_x_close_series(period: str = "2y") -> "pd.Series | None":
    """USD/KRW 일봉 종가 (Yahoo `KRW=X` — 원화로 1달러당)."""

    if yf is None or pd is None:
        return None
    try:
        raw = yf.download("KRW=X", period=period, interval="1d", progress=False, auto_adjust=True)
        if raw is None or raw.empty:
            return None
        if isinstance(raw.columns, pd.MultiIndex):
            try:
                raw = raw.copy()
                raw.columns = raw.columns.get_level_values(0)
            except Exception:
                return None
        if "Close" not in raw.columns:
            return None
        s = raw["Close"].dropna().astype(float)
        s = s[~s.index.duplicated(keep="last")].sort_index()
        return s if len(s) >= 40 else None
    except Exception:
        return None


def _fx_forecast_krw_per_usd_log_linear(
    close: "pd.Series",
    *,
    horizon_days: int,
    fit_window: int,
) -> dict[str, Any] | None:
    """최근 구간 로그가격 직선 추세 외삽 + 잔차 표준편차 기반 대략 밴드(참고용)."""

    import numpy as np

    if close is None or len(close) < 40:
        return None
    fw = max(30, min(int(fit_window), len(close)))
    y = close.iloc[-fw:].dropna()
    if len(y) < 30:
        return None
    logy = np.log(y.values.astype(float))
    t = np.arange(len(logy), dtype=float)
    slope, icept = np.polyfit(t, logy, 1)
    pred_in = slope * t + icept
    resid = logy - pred_in
    sig = float(np.std(resid)) if len(resid) > 1 else 0.0
    ss_res = float(np.sum(resid**2))
    mean_log = float(np.mean(logy))
    ss_tot = float(np.sum((logy - mean_log) ** 2))
    r2 = 1.0 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    last_t = float(len(y) - 1)
    h = np.arange(1, int(horizon_days) + 1, dtype=float)
    fut_t = last_t + h
    fut_log = slope * fut_t + icept
    z = 1.645
    widen = z * sig * np.sqrt(h)
    fut_mid = np.exp(fut_log)
    fut_lo = np.exp(fut_log - widen)
    fut_hi = np.exp(fut_log + widen)

    last_dt = pd.Timestamp(y.index[-1])
    bdays = pd.bdate_range(start=last_dt + pd.Timedelta(days=1), periods=int(horizon_days), freq="B")
    n = min(len(bdays), len(fut_mid))
    return {
        "dates": bdays[:n],
        "mid": fut_mid[:n],
        "lo": fut_lo[:n],
        "hi": fut_hi[:n],
        "slope_log_per_day": float(slope),
        "sigma_log_resid": sig,
        "r2_log": float(max(0.0, min(1.0, r2))),
        "fit_n": int(len(y)),
        "last_close": float(y.iloc[-1]),
        "last_date": last_dt,
    }


_RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; StreamlitLife/1.0; +https://example.invalid)"}


@st.cache_data(ttl=600, show_spinner=False)
def fetch_rss_headlines(feed_url: str, max_items: int = 16) -> list[dict] | None:
    try:
        r = requests.get(feed_url, timeout=20, headers=_RSS_HEADERS)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        channel = root.find("channel")
        if channel is None:
            return None
        out: list[dict] = []
        for item in channel.findall("item"):
            if len(out) >= max_items:
                break
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            if not link:
                guid_el = item.find("guid")
                if guid_el is not None and (guid_el.text or "").strip():
                    link = guid_el.text.strip()
            if title:
                out.append({"title": title, "url": link or "#"})
        return out or None
    except Exception:
        return None


@st.cache_data(ttl=300, show_spinner=False)
def fetch_hackernews_top(max_items: int = 16) -> list[dict] | None:
    try:
        r = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=15,
            headers=_RSS_HEADERS,
        )
        r.raise_for_status()
        ids = r.json()[:max_items]
        out: list[dict] = []
        for i in ids:
            ir = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{i}.json",
                timeout=12,
                headers=_RSS_HEADERS,
            )
            ir.raise_for_status()
            j = ir.json()
            if not j or j.get("dead") or j.get("deleted"):
                continue
            if j.get("type") != "story" or not j.get("title"):
                continue
            url = j.get("url") or f"https://news.ycombinator.com/item?id={i}"
            out.append(
                {
                    "title": j["title"],
                    "url": url,
                    "score": int(j.get("score") or 0),
                }
            )
        return out or None
    except Exception:
        return None


@st.cache_data(ttl=900, show_spinner=False)
def github_search_cached(query: str, per_page: int = 12) -> tuple[list[dict], str | None]:
    """GitHub Search API. (items rows for display, error string or None)."""
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = (os.environ.get("GITHUB_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        r = requests.get(
            url,
            params={"q": query, "sort": "stars", "order": "desc", "per_page": per_page},
            headers=headers,
            timeout=25,
        )
        if r.status_code == 403:
            return [], "GitHub API 제한(403). Personal access token을 `GITHUB_TOKEN` 환경변수로 넣거나 15분 뒤 다시 시도하세요."
        if r.status_code != 200:
            return [], f"GitHub API {r.status_code}: {(r.text or '')[:280]}"
        data = r.json()
        raw = data.get("items") or []
        rows: list[dict] = []
        for it in raw:
            rows.append(
                {
                    "repo": it.get("full_name", ""),
                    "stars": it.get("stargazers_count", 0),
                    "lang": it.get("language") or "—",
                    "설명": (lambda d: (d[:200] + "…") if len(d) > 200 else d)(it.get("description") or ""),
                    "url": it.get("html_url", ""),
                }
            )
        return rows, None
    except Exception as e:
        return [], str(e)[:300]


def _normalize_stock_ohlc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    if isinstance(out.columns, pd.MultiIndex):
        try:
            out.columns = out.columns.droplevel(1)
        except Exception:
            out.columns = [c[0] if isinstance(c, tuple) else c for c in out.columns]
    for col in ("Open", "High", "Low", "Close", "Volume"):
        if col not in out.columns:
            raise ValueError(f"컬럼 누락: {col}")
    return out


def _stock_currency_hint(ticker: str) -> str:
    t = ticker.upper()
    if t.endswith(".KS") or t.endswith(".KQ"):
        return "KRW"
    return "USD"


@st.cache_data(ttl=300, show_spinner=False)
def load_stock_price_data(ticker: str, start: date, end: date) -> "pd.DataFrame":
    assert pd is not None and yf is not None
    t = ticker.strip()
    if not t:
        return pd.DataFrame()
    df = yf.download(
        t,
        start=start,
        end=end + timedelta(days=1),
        progress=False,
        auto_adjust=True,
        threads=False,
    )
    if df.empty:
        return df
    return _normalize_stock_ohlc(df)


def local_agent_reply(text: str) -> str:
    """API 키 없을 때 간단 규칙 응답."""
    t = text.strip().lower()
    if not t:
        return "무엇이든 물어보세요. (예: 오늘 날씨 팁, 미세먼지, 물 많이 마시기)"
    if any(k in t for k in ("안녕", "hello", "hi")):
        return "안녕하세요. 날씨·건강·일상 팁을 물어보시면 답해 드릴게요."
    if "날씨" in t or "weather" in t:
        return (
            "**🌤️ 날씨** 탭 맨 위에서 지역을 고른 뒤 확인하세요. "
            "데이터는 Open-Meteo 무료 API입니다."
        )
    if "미세" in t or "먼지" in t or "pm" in t:
        return (
            "미세먼지는 이 데모에 별도 API를 연결하지 않았습니다. "
            "에어코리아·Open-Meteo Air Quality 등을 붙이면 확장할 수 있어요."
        )
    if "물" in t or "수분" in t:
        return "하루 1.5~2L 정도 충분히 마시고, 더운 날·운동 후엔 조금 더 드세요."
    if "운동" in t or "걷기" in t:
        return "가벼운 걷기 30분도 기분 전환과 혈액순환에 도움이 됩니다."
    if "수면" in t or "잠" in t:
        return "취침 전 스마트폰 줄이기, 방 어둡게, 비슷한 시간에 일어나기를 권합니다."
    if "github" in t or "깃헙" in t or "깃허브" in t:
        return (
            "상단 **GitHub 덴** 탭에 홈랩·퀀트·생산성 위주 링크와 실시간 검색이 있습니다. "
            "API 한도가 걸리면 NAS에 `GITHUB_TOKEN`(classic: public repo read)을 설정해 보세요."
        )
    if "환율" in t or "달러" in t or "엔화" in t or "유로" in t:
        return "미국 주식·해외 자산 감이 필요하면 **💱 환율** 탭에서 달러·엔·유로를 원화로 환산해 보세요. (ECB 기준, 영업일 갱신)"
    if "뉴스" in t or "헤드라인" in t or "연합" in t:
        return "**📰 뉴스** 탭에서 연합 경제·IT RSS와 Hacker News 상위 글을 볼 수 있습니다."
    if "뉴욕" in t or "나스닥" in t or "nyse" in t or "미국장" in t or "시차" in t:
        return "**🌍 시계** 탭에서 뉴욕 시각과 NYSE 정규장 여부(대략)를 볼 수 있습니다. 공휴일은 반영되지 않습니다."
    if "여행" in t or "travel" in t:
        return "**🗺️ 여행 스케치** 탭에서 국가를 고르면 샘플 날씨·여행 시즌·축제·명소 TOP3를 카드로 볼 수 있습니다."
    return (
        f"「{text[:40]}」에 대한 간단 응답: "
        "지금은 로컬 모드입니다. NAS/PC에 `OPENAI_API_KEY`를 설정하면 "
        "더 자연스러운 대화가 가능합니다."
    )


def openai_reply(messages: list[dict], user_text: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return local_agent_reply(user_text)
    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        msgs = [
            {
                "role": "system",
                "content": (
                    "당신은 한국어로 짧고 친절하게 답하는 생활·기술 도우미입니다. "
                    "날씨·건강·GitHub·홈랩·생산성·가벼운 재테크 개념을 다루되, "
                    "의학·법률·투자 조언(매수 매도)은 하지 마세요."
                ),
            },
            *messages,
            {"role": "user", "content": user_text},
        ]
        res = client.chat.completions.create(model=model, messages=msgs, max_tokens=500)
        return (res.choices[0].message.content or "").strip() or "(빈 응답)"
    except Exception as e:
        return f"OpenAI 호출 오류: {str(e)[:200]}\n\n로컬 모드 응답:\n{local_agent_reply(user_text)}"


def _render_curated_link_blocks(blocks: list[dict], *, key_prefix: str) -> None:
    """카테고리별 제목 + 사이트별 카드(st.container + link_button). 스타일은 main() 전역 CSS."""

    def _one_card(it: dict, btn_key: str) -> None:
        with _st_try_border_container():
            st.markdown(f"##### {it['t']}")
            if it.get("d"):
                st.caption(it["d"])
            parent_txt = (it.get("parent") or "").strip()
            if parent_txt:
                st.markdown(parent_txt)
            elif not it.get("d"):
                st.caption("설명 준비 중입니다.")
            if hasattr(st, "link_button"):
                try:
                    st.link_button(
                        "🔗 사이트 열기",
                        it["u"],
                        use_container_width=True,
                        key=btn_key,
                    )
                except TypeError:
                    st.link_button("🔗 사이트 열기", it["u"], use_container_width=True)
            else:
                st.markdown(f"[{it['t']}]({it['u']})")

    n = 0
    for block in blocks:
        st.subheader(str(block["title"]))
        items = block["items"]
        for row_start in range(0, len(items), 2):
            pair = items[row_start : row_start + 2]
            cols = st.columns(len(pair))
            for col, it in zip(cols, pair):
                with col:
                    n += 1
                    _one_card(it, f"{key_prefix}_card_{n}")
        st.markdown("")


# 국가별 여행 샘플 (데모용 — 실제 일정·날씨와 무관)
# 구조: { 국가명(str): { "날씨": str, "시기": str, "축제": list[str], "명소": list[str], … } }
TRAVEL_MOCK_BY_COUNTRY: dict[str, dict[str, Any]] = {
    "대한민국": {
        "lat": 37.5665, "lon": 126.9780, "city": "서울",
        "날씨": "서울 기준 **맑음** · 기온 **14°C** · 바람 약 · 미세먼지 **보통**",
        "시기": "**봄 · 가을 ⭐** — **4~5월·9~10월** 선선한 기온에 벚꽃·단풍·축제 즐기기 좋음. 한여름·혹한기는 일정 여유 있게.",
        "축제": [
            "진해 군항제·벚꽃 축제(봄)",
            "부산 국제영화제(가을)",
            "안동 탈춤축제 등 지역별 전통 축제",
        ],
        "명소": [
            "경복궁·북촌 한옥마을 — 도심 궁궐과 한옥 골목 산책",
            "제주 한라산·성산일출봉 — 해안 드라이브와 자연",
            "경주 불국사·대릉원 — 신라 유적 일주",
        ],
        "travel_tip": "💡 **대한민국** · 교통카드(T-money·카카오 등)를 미리 준비하면 시내 이동이 수월합니다. 인기 맛집·카페는 점심·저녁 피크 시간대 예약을 권합니다.",
        "travel_tip_style": "info",
    },
    "일본": {
        "lat": 35.6762, "lon": 139.6503, "city": "도쿄",
        "날씨": "도쿄 기준 **흐림 곳곳 맑음** · **16°C** · 습도 보통",
        "시기": "**벚꽃 · 단풍 시즌** — **3~5월 벚꽃** · **10~11월 단풍** 인기. 여름은 후지산·북해도 제외하면 더운 편.",
        "축제": [
            "삿포로 눈 축제(겨울)",
            "교토 기온 마츠리(여름)",
            "도쿄 지역 신사·연등 행사(연중)",
        ],
        "명소": [
            "교토 금각사·기요미즈데라 — 사찰·유네스코 세계유산",
            "후지산·하코네 — 온천·전통 여관 체험",
            "오사카성·도톤보리 — 먹거리·야경",
        ],
        "travel_tip": "💡 **일본** · 편의점 ATM·교통카드(IC) 충전은 현금 없이도 가능한 경우가 많습니다. 대중목욕·온천은 작은 타월을 챙기면 편합니다.",
        "travel_tip_style": "info",
    },
    "태국": {
        "lat": 13.7563, "lon": 100.5018, "city": "방콕",
        "날씨": "방콕 기준 **대체로 맑음** · **32°C** · 소나기 가능",
        "시기": "**건기 (11월~2월)** — 더위·습도 상대적으로 덜 부담. 송끌란 등 물축제는 4월 무렵.",
        "축제": [
            "송끌란(태국 새해 물축제, 4월 전후)",
            "로이 끄라통(등불 축제, 북부)",
            "버마 영화제 등 현대 페스티벌",
        ],
        "명소": [
            "방콕 왕궁·왓 포 — 불교 사원·수상 시장",
            "치앙마이 올드타운 — 랜턴·산사·카페",
            "푸켓·피피 섬 — 해변·스노클링",
        ],
        "travel_tip": "⚠️ **태국** · 더위·습기가 큽니다. 수분 보충·자외선 차단을 권합니다. 야시장·관광지에서는 소매치기·택시 요금을 미리 확인하세요. 입국 규정은 공식 안내를 따르세요.",
        "travel_tip_style": "warning",
    },
    "프랑스": {
        "lat": 48.8566, "lon": 2.3522, "city": "파리",
        "날씨": "파리 기준 **약간 흐림** · **12°C** · 서늘한 바람",
        "시기": "**4~6월 · 9~10월** — 관광지 혼잡은 피하려면 비수기 가장자리 추천.",
        "축제": [
            "칸 영화제(5월)",
            "바스티유의 날(7월)",
            "크리스마스 마켓(스트라스부르 등)",
        ],
        "명소": [
            "파리 루브르·에펠탑 — 필수 랜드마크",
            "프로방스 라벤더·아비뇽 — 남부 분위기",
            "몽생미셸 — 섬 수도원 일몰",
        ],
        "travel_tip": "💡 **프랑스** · 미술관은 사전 예약·오전 입장이 한산한 편입니다. 파리 외 지역 이동은 기차(TGV 등) 예약을 미리 하면 좋습니다.",
        "travel_tip_style": "info",
    },
    "미국": {
        "lat": 40.7128, "lon": -74.0060, "city": "뉴욕",
        "날씨": "뉴욕 기준 **맑음** · **11°C** · 봄날씨 느낌",
        "시기": "**지역별 상이** — 뉴욕·DC는 봄·가을, 서부 국립공원은 여름·가을 드라이브 인기.",
        "축제": [
            "추수감사절 퍼레이드(뉴욕)",
            "듀얼 오브 라이츠(내셔널 파크 이벤트 등)",
            "지역별 재즈·음식 페스티벌",
        ],
        "명소": [
            "뉴욕 자유의 여신·브루클린 — 도시 스카이라인",
            "그랜드 캐니언·자이언 — 국립공원 트레킹",
            "샌프란시스코 금문교·피어39 — 해안 도시",
        ],
        "travel_tip": "⚠️ **미국** · ESTA·비자 등 **입국 요건**은 사전에 공식 사이트에서 확인하세요. 식당·택시는 팁 문화가 있습니다. 주별 세금·교통 규칙이 다를 수 있습니다.",
        "travel_tip_style": "warning",
    },
    "이탈리아": {
        "lat": 41.9028, "lon": 12.4964, "city": "로마",
        "날씨": "로마 기준 **맑음** · **18°C** · 봄 햇살",
        "시기": "**4~6월 · 9~10월** — 더위·관광 성수기 혼잡 완화에 유리. 남부 해안은 여름 피크 주의.",
        "축제": [
            "베네치아 카니발(겨울)",
            "시에나 팔리오(여름)",
            "크리스마스 프레세피오 전통",
        ],
        "명소": [
            "로마 콜로세움·바티칸 — 고대·예술 필수",
            "피렌체 우피치·두오모 — 르네상스 거리",
            "베네치아 산마르코·골목 — 수상 도시 산책",
        ],
        "travel_tip": "💡 **이탈리아** · 유적·박물관은 입장권을 미리 끊으면 대기 시간을 줄일 수 있습니다. 관광지 밀집 지역은 소지품을 살펴보세요. 일부 레스토랑에는 테이블 비용(coperto) 등 안내가 있으니 확인하면 좋습니다.",
        "travel_tip_style": "info",
    },
}


def _travel_season_metric(season_md: str) -> str:
    """시기 문단에서 추천 시즌 메트릭 라벨 — EM/EN dash·전각 마이너스 등 국가별 문자 차이 대응."""

    s = (season_md or "").strip()
    if not s:
        return "참고용 샘플"
    # 첫 구분선만 분리 (숫자 범위의 '~'·일반 하이픈은 분리하지 않음)
    parts = re.split(r"\s*[\u2014\u2013\u2212\uFF0D]\s*", s, maxsplit=1)
    head_raw = parts[0].strip().replace("**", "").strip()
    if head_raw:
        return head_raw[:56] + ("…" if len(head_raw) > 56 else "")
    tail = parts[1].strip().replace("**", "").strip() if len(parts) > 1 else ""
    if tail:
        return tail[:56] + ("…" if len(tail) > 56 else "")
    return "참고용 샘플"


def _travel_safe_metric_value(label: str) -> str:
    """st.metric value용 — 빈 문자열·개행 등으로 위젯 오류 나지 않게."""

    v = (label or "").replace("\r\n", " ").replace("\n", " ").strip()
    return v if v else "참고용 샘플"


def _parse_travel_spot_line(line: str) -> tuple[str, str]:
    """명소 한 줄 '제목 — 설명' 분리 (구분자 없으면 제목만). 대시 문자(—–−－) 호환."""

    s = (line or "").strip()
    if not s:
        return "", ""
    parts = re.split(r"\s*[—–−－]\s*", s, maxsplit=1)
    if len(parts) == 2:
        return parts[0].strip(), parts[1].strip()
    return s, ""


def _travel_partition_festivals_two_cols(lines: list[str]) -> tuple[list[str], list[str]]:
    """축제 목록을 2열 카드용으로 균등 분할."""

    mid = (len(lines) + 1) // 2
    return lines[:mid], lines[mid:]


def _travel_named_spots_top3(row: dict[str, Any]) -> list[tuple[str, str]]:
    """명소 문자열 목록 → 최대 3개 (제목, 설명) 튜플."""

    raw = list(row.get("명소") or [])
    return [_parse_travel_spot_line(str(x)) for x in raw[:3]]


def _travel_render_tip_banner(row: dict[str, Any]) -> None:
    tip = str(row.get("travel_tip") or "").strip()
    if not tip:
        return
    if str(row.get("travel_tip_style") or "info").lower() == "warning":
        st.warning(tip)
    else:
        st.info(tip)


def _travel_render_weather_season_cards(row: dict[str, Any]) -> None:
    season_md = str(row.get("시기") or "").strip()
    lat: float | None = row.get("lat")
    lon: float | None = row.get("lon")
    city: str = str(row.get("city") or "")

    # ── 실시간 날씨 카드 ──
    with _st_try_border_container():
        st.markdown(f"##### 🌤️ 현재 날씨 · {city}" if city else "##### 🌤️ 현재 날씨")
        if lat is not None and lon is not None:
            with st.spinner("날씨 정보를 불러오는 중…"):
                data = fetch_weather_cached(lat, lon)
            if data and "current" in data:
                cur = data["current"]
                code = int(cur.get("weather_code", 0))
                col1, col2 = st.columns(2)
                with col1:
                    st.metric("기온", f"{cur.get('temperature_2m', 0):.1f} °C")
                    st.metric("습도", f"{cur.get('relative_humidity_2m', 0)} %")
                with col2:
                    st.metric("체감", f"{cur.get('apparent_temperature', 0):.1f} °C")
                    st.metric("풍속", f"{cur.get('wind_speed_10m', 0):.1f} km/h")
                st.caption(f"☁ {wmo_label(code)}  ·  Open-Meteo 실시간 ({lat:.2f}°, {lon:.2f}°)")
                daily = data.get("daily") or {}
                times = daily.get("time") or []
                if times:
                    st.markdown("**5일 예보**")
                    for i, d in enumerate(times[:5]):
                        mx = daily["temperature_2m_max"][i]
                        mn = daily["temperature_2m_min"][i]
                        wc = wmo_label(int(daily["weather_code"][i]))
                        st.markdown(
                            f'<div style="padding:0.7rem 1rem;margin:0.4rem 0;border-radius:12px;'
                            f"background:linear-gradient(160deg,#433d8b 0%,#3730a3 100%);"
                            f"border:1px solid rgba(165,180,252,0.35);color:#fafaff;"
                            f'font-size:clamp(0.9rem,3.5vw,1rem);line-height:1.45;">'
                            f"<strong>{html.escape(str(d))}</strong> · {html.escape(wc)}<br/>"
                            f'<span style="color:#c7d2fe;">최고 {mx:.1f}°C · 최저 {mn:.1f}°C</span></div>',
                            unsafe_allow_html=True,
                        )
            else:
                # API 실패 시 샘플 텍스트 폴백
                fallback = str(row.get("날씨") or "").strip() or "(날씨 정보 없음)"
                st.warning("날씨 API에 연결하지 못했습니다. 아래는 참고용 샘플입니다.")
                st.markdown(fallback)
        else:
            st.markdown(str(row.get("날씨") or "(좌표 미등록 — 샘플 표시)").strip())

    # ── 여행 최적기 카드 ──
    with _st_try_border_container():
        st.markdown("##### 📅 여행 최적기")
        metric_label = _travel_safe_metric_value(_travel_season_metric(season_md))
        try:
            st.metric(
                label="추천 시즌",
                value=metric_label,
                help="샘플 요약입니다. 아래 문단에서 세부 설명을 확인하세요.",
            )
        except Exception:
            try:
                st.metric("추천 시즌", metric_label)
            except Exception:
                st.markdown(f"**추천 시즌** · {metric_label}")
        st.caption("상세 안내")
        st.markdown(season_md if season_md else "*시기 샘플 문구가 비어 있습니다.*")


def _travel_render_festival_section(row: dict[str, Any]) -> None:
    fest_lines = list(row.get("축제") or [])
    left, right = _travel_partition_festivals_two_cols(fest_lines)
    with _st_try_border_container():
        st.markdown("##### 🎉 주요 축제")
        fc_l, fc_r = st.columns(2)
        with fc_l:
            for line in left:
                st.markdown(f"- {line}")
        with fc_r:
            for line in right:
                st.markdown(f"- {line}")


def _travel_render_spots_top3(row: dict[str, Any]) -> None:
    spots = _travel_named_spots_top3(row)
    st.markdown("##### 🏛️ 필수 방문 명소 TOP 3")
    col_a, col_b, col_c = st.columns(3)
    for col, rank, item in zip((col_a, col_b, col_c), ("1", "2", "3"), spots):
        title, desc = item
        with col:
            with _st_try_border_container():
                st.markdown(f"**TOP {rank}** · {title}")
                st.caption(desc)


# 여행 준비 체크리스트 (세션 저장 — 참고용)
TRAVEL_PREP_CHECKLIST_ITEMS: list[dict[str, str]] = [
    {
        "label": "🛂 **여권** 유효기간·서명·공란 페이지가 목적지 요건에 맞는지 확인",
        "hint": "일부 국가는 잔여 유효 기간 6개월 이상을 요구합니다.",
    },
    {
        "label": "📋 **비자·전자여행허가(ETA)·입국 규정** 확인 (무비자 체류 가능 여부 등)",
        "hint": "외교부·대사관·목적지 입국 관청 공지를 확인하세요.",
    },
    {
        "label": "💱 **환전·결제** — 현금·카드·환율 앱, 현지 통화·수수료 확인",
        "hint": "현지 ATM·카드 수수료·일 한도도 함께 확인하면 좋습니다.",
    },
    {
        "label": "🧾 **항공·숙소** 예약 확인서·예약번호 저장 (오프라인 사본 권장)",
        "hint": "스크린샷·PDF 저장 후 클라우드·메일 백업.",
    },
    {
        "label": "🛡️ **여행자 보험** 필요 여부·보상 범위 확인",
        "hint": "항공 지연·의료·수하물 등 약관을 검토하세요.",
    },
    {
        "label": "📶 **로밍·eSIM·Wi-Fi** 등 통신 준비",
        "hint": "현지 유심·포켓와이파이 예약일 수 있습니다.",
    },
    {
        "label": "🔌 **변환 플러그·멀티탭·보조배터리** 챙기기",
        "hint": "목적지 전압·콘센트 규격을 확인하세요.",
    },
    {
        "label": "📇 여권·비자 사본·비상 연락처를 **별도 보관**",
        "hint": "분실 대비 가족·대사관 연락처도 적어 두면 좋습니다.",
    },
    {
        "label": "🌐 외교부 **해외안전여행**·현지 치안·입국 서류·건강·백신 안내 확인",
        "hint": "공식 해외안전여행 사이트 등을 참고하세요.",
    },
]


def _travel_render_prep_checklist_grid() -> None:
    prep_items = TRAVEL_PREP_CHECKLIST_ITEMS
    n_prep_cols = 3
    with _st_try_border_container():
        for row_start in range(0, len(prep_items), n_prep_cols):
            chunk = prep_items[row_start : row_start + n_prep_cols]
            grid = st.columns(n_prep_cols)
            for j, prep in enumerate(chunk):
                idx = row_start + j
                with grid[j]:
                    st.checkbox(
                        prep["label"],
                        help=prep.get("hint"),
                        key=f"travel_prep_chk_{idx}",
                    )


_NAV_OPTIONS: tuple[str, ...] = (
    "시장",
)

# 주식 앱 상단 바 — 짧은 라벨 `_TOPBAR_NAV_SHORT` → `_SIDEBAR_NAV_OPTIONS` 로 매핑
_MARKET_NAV_OPTIONS: tuple[str, ...] = (
    "오늘의 픽",
    "코스피 스캐너",
    "코스닥 스캐너",
    "ETF 스캐너",
    "관심주식",
)
_WL_NAV_LOGIN = "로그인"
_WL_NAV_REGISTER = "회원가입"
_SIDEBAR_NAV_OPTIONS: tuple[str, ...] = _MARKET_NAV_OPTIONS + (_WL_NAV_LOGIN, _WL_NAV_REGISTER)
# 상단 바(우측 메뉴)용 짧은 라벨 → 전체 메뉴 키
_TOPBAR_NAV_SHORT: tuple[str, ...] = ("오늘의픽", "코스피", "코스닥", "ETF", "관심", "로그인", "가입")
_TOPBAR_SHORT_TO_PAGE: dict[str, str] = dict(zip(_TOPBAR_NAV_SHORT, _SIDEBAR_NAV_OPTIONS))
# 브라우저 주소창 `?p=` — 뒤로가기 시 앱 안에서 이전 메뉴·메인으로 이동하도록 히스토리와 동기화
_NAV_QUERY_SLUG_TO_SHORT: dict[str, str] = {
    "pick": "오늘의픽",
    "kospi": "코스피",
    "kosdaq": "코스닥",
    "etf": "ETF",
    "wl": "관심",
    "login": "로그인",
    "join": "가입",
}
_TOPBAR_SHORT_TO_SLUG: dict[str, str] = {
    short: slug for slug, short in _NAV_QUERY_SLUG_TO_SHORT.items()
}
_PAGE_SLUG_TO_FULL: dict[str, str] = {
    "pick": "오늘의 픽",
    "kospi": "코스피 스캐너",
    "kosdaq": "코스닥 스캐너",
    "etf": "ETF 스캐너",
    "wl": "관심주식",
    "login": _WL_NAV_LOGIN,
    "join": _WL_NAV_REGISTER,
}

# ETF 스캐너 — 순위표·차트 뷰어 공통 섹터 필터(고정 옵션, 드롭다운 전용)
_ETF_SECTOR_FILTER_OPTIONS: tuple[str, ...] = (
    "전체",
    "건설/인프라",
    "금융",
    "레버리지",
    "모빌리티",
    "미국주식",
    "바이오/헬스케어",
)

# 스탠 와인스타인(Stan Weinstein) 4단계 — 짧은 맥락만 UI에 삽입(교육용 요약, 투자 권유 아님)
_WEINSTEIN_TIPS: tuple[str, ...] = (
    "와인스타인식으로 **1단계(베이스)**는 길게 횡보하며 수급이 갈리는 구간, **2단계(어드밴싱)**는 돌파 뒤 상승이 펼쳐지는 구간으로 자주 이야기됩니다. 이 앱의 **Stage2**는 그중 **종목이 2단계에 가깝다고 판단될 때**를 숫자로 거른 결과에 가깝습니다.",
    "**3단계(디스트리뷰션)** 고점 부근에서는 «누가 팔고 있나»를 거래량·변동성으로 보는 식의 경계 이야기가 많고, **4단계(딥클라인)**에서는 손실을 줄이는 쪽이 우선이라는 식의 조언이 흔합니다.",
    "실무 요약 중 하나는 **거래량이 추세를 확인**한다는 것 — 상승이 거래량 동반으로 이어질 때와, 줄은 채 가격만 오를 때를 구분하자는 뉘앙스입니다.",
    "**시장 → 섹터 → 종목** 순으로 맥락을 맞추라는 말은, 위험을 종목 한 곳에만 몰지 말자는 뜻으로 자주 전해집니다. 이 스캐너는 그중 **종목** 레이어를 돕습니다.",
    "30주 이동평균선 근처의 **바닥 다지기·돌파** 이야기는 1→2 전환을 가늠할 때 등장하는 클리셰 중 하나입니다. (이 앱 지수 카드의 MA50/MA200은 다른 관점의 참고선입니다.)",
    "**받아 들이고 나가기**까지 시간을 둔다는 식의 심리·자금관리 이야기도 같이 붙어 다니는 편입니다.",
)


def _weinstein_tip_caption(*, salt: str = "") -> None:
    """짧은 와인스타인 맥락 캡션 1줄(salt로 화면마다 다른 문장 고정 선택)."""
    if not _WEINSTEIN_TIPS:
        return
    i = sum(ord(c) for c in str(salt)) % len(_WEINSTEIN_TIPS)
    st.caption(f"참고 · {_WEINSTEIN_TIPS[i]}")


# 화장품 가격비교 (홈 탭 — 카테고리별 샘플 표, 실시간 가격·재고와 무관)
COSMETICS_PRICE_COMPARE_MOCK: dict[str, list[dict[str, str]]] = {
    "스킨케어 · 에센스": [
        {
            "상품명": "데모 수분 에센스",
            "브랜드": "샘플 브랜드 A",
            "용량": "80ml",
            "올리브영": "28,000원",
            "롭스": "26,400원",
            "쿠팡(참고)": "24,900원~",
            "비고": "행사가 변동",
        },
        {
            "상품명": "데모 비타민 세럼",
            "브랜드": "샘플 브랜드 B",
            "용량": "30ml",
            "올리브영": "42,000원",
            "롭스": "42,000원",
            "쿠팡(참고)": "39,500원~",
            "비고": "카드 할인 전후 상이",
        },
        {
            "상품명": "데모 장벽 크림",
            "브랜드": "샘플 브랜드 C",
            "용량": "50ml",
            "올리브영": "35,000원",
            "롭스": "—",
            "쿠팡(참고)": "33,000원~",
            "비고": "입점 채널별 상이",
        },
    ],
    "메이크업": [
        {
            "상품명": "데모 쿠션 파운데이션",
            "브랜드": "샘플 브랜드 D",
            "용량": "14g",
            "올리브영": "32,000원",
            "롭스": "29,900원",
            "쿠팡(참고)": "27,800원~",
            "비고": "색상 옵션별 재고 상이",
        },
        {
            "상품명": "데모 립 틴트",
            "브랜드": "샘플 브랜드 E",
            "용량": "5g",
            "올리브영": "18,000원",
            "롭스": "17,500원",
            "쿠팡(참고)": "15,900원~",
            "비고": "묶음 행사 시 저렴",
        },
    ],
    "클렌징 · 선케어": [
        {
            "상품명": "데모 폼 클렌저",
            "브랜드": "샘플 브랜드 F",
            "용량": "150ml",
            "올리브영": "15,000원",
            "롭스": "14,500원",
            "쿠팡(참고)": "12,900원~",
            "비고": "세일 주기 확인",
        },
        {
            "상품명": "데모 선크림 SPF50+",
            "브랜드": "샘플 브랜드 G",
            "용량": "50ml",
            "올리브영": "22,000원",
            "롭스": "21,000원",
            "쿠팡(참고)": "19,400원~",
            "비고": "계절 수요 반영",
        },
    ],
}


COSMETICS_PRICE_PORTALS: list[dict[str, str]] = [
    {
        "t": "올리브영",
        "u": "https://www.oliveyoung.co.kr/store/main/main.do",
        "d": "매장·앱 행사가 빠르게 바뀝니다.",
    },
    {
        "t": "롭스 LOHB's",
        "u": "https://www.lohbs.com/",
        "d": "브랜드 입점·가격은 채널별 상이합니다.",
    },
    {
        "t": "쿠팡 뷰티 카테고리",
        "u": "https://www.coupang.com/np/categories/393760",
        "d": "판매자·배송 조건에 따라 최종가가 달라집니다.",
    },
    {
        "t": "화해 (성분)",
        "u": "https://www.hwahae.co.kr/",
        "d": "성분 필터 후 구매 채널을 고르기 좋습니다.",
    },
]


# 컴퓨터 가격비교 (홈 탭 — 제품군별 샘플 표, 실시간 최저가·재고와 무관)
PC_PRICE_COMPARE_MOCK: dict[str, list[dict[str, str]]] = {
    "노트북 · 미니 PC": [
        {
            "상품명": "데모 울트라북 14\"",
            "스펙 요약": "CPU 샘플 · RAM 16GB · SSD 512GB",
            "다나와(참고)": "1,249,000원~",
            "쿠팡(참고)": "1,189,000원~",
            "11번가(참고)": "1,210,000원~",
            "비고": "색상·구성별 변동",
        },
        {
            "상품명": "데모 게이밍 노트북 15.6\"",
            "스펙 요약": "샘플 GPU · RAM 32GB",
            "다나와(참고)": "2,190,000원~",
            "쿠팡(참고)": "2,099,000원~",
            "11번가(참고)": "2,150,000원~",
            "비고": "번들·행사가 차이 큼",
        },
        {
            "상품명": "데모 미니 PC NUC형",
            "스펙 요약": "샘플 CPU · RAM 16GB",
            "다나와(참고)": "689,000원~",
            "쿠팡(참고)": "659,000원~",
            "11번가(참고)": "—",
            "비고": "베어본 vs 완제품 비교",
        },
    ],
    "데스크톱 · 브랜드 PC": [
        {
            "상품명": "데모 사무용 브랜드 데스크톱",
            "스펙 요약": "샘플 i5급 · RAM 16GB · SSD 512GB",
            "다나와(참고)": "989,000원~",
            "쿠팡(참고)": "959,000원~",
            "11번가(참고)": "970,000원~",
            "비고": "AS·보증 기간 확인",
        },
        {
            "상품명": "데모 게이밍 타워",
            "스펙 요약": "샘플 CPU/GPU · RAM 32GB",
            "다나와(참고)": "2,590,000원~",
            "쿠팡(참고)": "2,499,000원~",
            "11번가(참고)": "2,540,000원~",
            "비고": "케이스·파워 옵션별 상이",
        },
    ],
    "주요 부품": [
        {
            "상품명": "데모 그래픽카드 (차세대급)",
            "스펙 요약": "샘플 VRAM 16GB",
            "다나와(참고)": "879,000원~",
            "쿠팡(참고)": "849,000원~",
            "11번가(참고)": "860,000원~",
            "비고": "출시·환율에 따름",
        },
        {
            "상품명": "데모 NVMe SSD 2TB",
            "스펙 요약": "샘플 Gen4",
            "다나와(참고)": "219,000원~",
            "쿠팡(참고)": "199,000원~",
            "11번가(참고)": "209,000원~",
            "비고": "순차읽기 수치 비교 권장",
        },
        {
            "상품명": "데모 DDR5 RAM 32GB kit",
            "스펙 요약": "샘플 5600MHz",
            "다나와(참고)": "189,000원~",
            "쿠팡(참고)": "179,000원~",
            "11번가(참고)": "184,000원~",
            "비고": "메인보드 호환 확인",
        },
    ],
}


PC_PRICE_PORTALS: list[dict[str, str]] = [
    {
        "t": "다나와",
        "u": "https://www.danawa.com/",
        "d": "가격 추이·스펙 비교에 자주 씁니다.",
    },
    {
        "t": "네이버 쇼핑",
        "u": "https://shopping.naver.com/home",
        "d": "검색 후 최저가·판매처 비교.",
    },
    {
        "t": "쿠팡 PC/주변기기",
        "u": "https://www.coupang.com/np/categories/178255",
        "d": "로켓 배송·판매자별 조건 확인.",
    },
    {
        "t": "11번가 PC",
        "u": "https://www.11st.co.kr/browsing/BestSeller.tmall?method=getBestSellerMain&xfrom=main^Best",
        "d": "프로모션·카드 할인 조건 확인.",
    },
]

# 생활 탭 · 컴퓨터 가이드(커뮤니티·시장 경향 참고, 실시간 최저가 아님)
LIFE_PC_AVG_PRICE_BANDS: list[dict[str, str]] = [
    {
        "구분": "사무·학습용 노트북(14\" 내외)",
        "가격대(참고)": "약 80~160만 원",
        "비고": "RAM 16GB·SSD 512GB 전후가 흔한 기준선. 행사가·환율 반영 시 변동.",
    },
    {
        "구분": "휴대 중심 프리미엄 노트북",
        "가격대(참고)": "약 140~250만 원+",
        "비고": "밝은 디스플레이·배터리·무게가 가격을 좌우. 애플 실리콘 포함.",
    },
    {
        "구분": "게이밍 노트북(미드급 GPU)",
        "가격대(참고)": "약 180~320만 원",
        "비고": "세대·VRAM·TGP에 따라 격차 큼. 쿨링·소음은 리뷰 필수.",
    },
    {
        "구분": "완조립 브랜드 데스크톱(사무급)",
        "가격대(참고)": "약 90~150만 원",
        "비고": "AS 일원화 선호 시. 크기·확장성은 자작 대비 제한될 수 있음.",
    },
    {
        "구분": "게이밍 데스크톱(자작·업체 조립)",
        "가격대(참고)": "약 150만 원~400만 원+",
        "비고": "GPU·CPU 선택이 총액의 대부분. 파워 정격·케이스 호환 확인.",
    },
    {
        "구분": "미니 PC",
        "가격대(참고)": "약 50~120만 원",
        "비고": "베어본 vs 완제품. 업무·미디어센터용이 많음.",
    },
]

LIFE_PC_POPULAR_SEGMENTS: list[dict[str, str]] = [
    {
        "카테고리": "노트북",
        "요즘 잘 나가는 유형": "무게·배터리 좋은 직장인용, 학생용 라이트, ‘가성비’ 게이밍 일각",
        "한 줄": "재택·통학 병행으로 **휴대성 + RAM 16GB** 조합이 무난.",
    },
    {
        "카테고리": "데스크톱",
        "요즘 잘 나가는 유형": "미드급 게이밍 조립 PC, 소형 미니 타워",
        "한 줄": "GPU 가격 안정·세대 교체 주기에 맞춰 **특정 카드 기준**으로 견적이 많이 맞춰짐.",
    },
    {
        "카테고리": "주변기기",
        "요즘 잘 나가는 유형": "27\" QHD 고주사율 모니터, NVMe SSD 용량 업, 기계식 키보드",
        "한 줄": "본체 세대보다 **모니터·저장장치** 교체 수요가 꾸준.",
    },
    {
        "카테고리": "그래픽카드",
        "요즘 잘 나가는 유형": "메인스트림 VRAM 8~12GB급, AI·작업용 16GB+",
        "한 줄": "게임·생성 AI 겸용 니즈로 **VRAM 용량**이 검색 키워드 상위.",
    },
]

LIFE_PC_SPEC_RECOMMEND_MARKDOWN: str = """
##### 요즘 새로 맞출 때 자주 권하는 기준(2025~2026경향)

- **RAM**: 일반·사무 **16GB**는 최소선으로 보는 편. 개발·영상·로컬 LLM·듀얼 모니터는 **32GB**를 우선 검토.
- **저장소**: **NVMe SSD 1TB**가 기본 후보가 많음. 클라우드 위주면 512GB도 가능하나, 게임·프로젝트는 금방 찹니다.
- **CPU**: 노트북은 **최신 세대의 전력 대비 성능**(패시브 쿨링·소음) 확인. 데스크톱은 **6코어 이상**이 영상·빌드·경량 ML에 여유.
- **GPU(게임/에딘 X)**: FHD 고주사율이면 중독급, QHD면 상위. **파워 정격·케이스 길이**를 카드 스펙과 함께 확인.
- **디스플레이**: 장시간 작업이면 **플리커 프리·저블루** 유사 기능, 색 작업은 **sRGB/색역** 스펙 확인.
- **OS**: 게임·일반 앱은 **Windows 11** 전제가 대부분. 맥은 **호환 소프트웨어** 먼저 체크.
- **확장**: 메인보드 **M.2 슬롯 수**, 노트북 **RAM/SSD 업그레이드 가능 여부**(납땜 여부)는 매장·리뷰에서 확인.
"""

LIFE_PC_ML_GPU_GUIDE: list[dict[str, str]] = [
    {
        "용도·예산 느낌": "입문·파이썬·소형 모델·캐글식 실습",
        "추천 GPU 성향": "**VRAM 8GB+** (가능하면 12GB). CUDA·PyTorch 생태 기준 **엔비디아**가 자료·예제가 많음.",
        "메모": "로컬보다 **Colab / 클라우드 GPU**로 먼저 습관 잡는 것도 비용 대비 효율적.",
    },
    {
        "용도·예산 느낌": "중급: 파인튜닝(LoRA)·중간 크기 LLM 일부·배치 작은 학습",
        "추천 GPU 성향": "**16GB VRAM** 이상이 유리. 예: **RTX 4060 Ti 16GB**는 VRAM/가격 균형으로 자주 거론.",
        "메모": "모델·양자화(4bit 등)에 따라 필요 VRAM은 크게 달라짐 — **사용 프레임워크 문서** 확인.",
    },
    {
        "용도·예산 느낌": "상급: 큰 배치, 고해상도 이미지·비디오, 로컬에서 가능한 큰 체크포인트",
        "추천 GPU 성향": "**RTX 4080(16GB)**, **RTX 4090(24GB)** 등. 멀티 GPU·워크스테이션은 예산·메인보드·PSU 동시 설계.",
    },
    {
        "용도·예산 느낌": "AMD / ROCm",
        "추천 GPU 성향": "일부 카드는 **ROCm**으로 PyTorch 등 가동 가능. **지원 매트릭스·OS**를 설치 전 필수 확인.",
        "메모": "튜토리얼·플러그인은 **CUDA 기준**이 많아, 초보는 엔비디아가 수고가 덜한 경우가 많음.",
    },
    {
        "용도·예산 느낌": "애플 실리콘(맥)",
        "추천 GPU 성향": "**통합 메모리**로 VRAM 개념과 다름. MLX·Core ML·온디바이스 추론 위주로 설계.",
        "메모": "CUDA 네이티브 연구 코드는 **포팅·대안** 검토가 필요.",
    },
    {
        "용도·예산 느낌": "연구소·상시 서버급",
        "추천 GPU 성향": "**RTX 6000 Ada**, **A100/H100** 클래스 또는 **클라우드 전용 인스턴스**.",
        "메모": "가동률이 낮으면 **클라우드 spot/예약**이 총비용에서 유리한 경우가 많음.",
    },
]


# 자동차 포털 — 인기 차종 요약·셀토스·옵션 가이드(커뮤니티 평가 경향 정리, 실시간 가격·재고 아님)
CAR_POPULAR_MODEL_SUMMARY: list[dict[str, str]] = [
    {
        "모델": "기아 셀토스",
        "세그먼트": "소형 SUV",
        "만족 포인트": "실내 공간 대비 차 크기, 디자인, 주행 거치감(도심·고속 균형)",
        "흔한 지적": "정숙성·승차감은 동급 세단보다 다소 거칠 수 있음. 파워트레인은 시승 필수",
        "옵션 팁": "운전 보조(ADAS) 묶음 우선. 내비/클러스터 일체감은 상위 트림에서 체감",
    },
    {
        "모델": "현대 코나",
        "세그먼트": "소형 SUV",
        "만족 포인트": "개성 있는 디자인, 도심 주차·코너링",
        "흔한 지적": "실내·뒷좌석은 셀토스·투싼 대비 아쉬울 수 있음",
        "옵션 팁": "전기·하이브리드는 충전·주행거리·보조금 조건을 먼저 계산",
    },
    {
        "모델": "현대 투싼",
        "세그먼트": "준중형 SUV",
        "만족 포인트": "넉넉한 실내, 패밀리 1대차로 무난",
        "흔한 지적": "차체가 커 도심 좁은 곳은 부담. 예산 상승",
        "옵션 팁": "가솔린·디젤·하이브리드별 잔진동·연비 차이가 커서 시승 2회 이상 권장",
    },
    {
        "모델": "기아 스포티지",
        "세그먼트": "준중형 SUV",
        "만족 포인트": "디자인·실내, 장거리 승차감 호평 다수",
        "흔한 지적": "옵션 누적 시 예산 급증. 견적 비교 필수",
        "옵션 팁": "통풍·전동시트·헤드업 등은 패키지 단위인 경우 많음",
    },
    {
        "모델": "경·소형 SUV (베뉴·티볼리 등)",
        "세그먼트": "경·소형",
        "만족 포인트": "가격 대비 기본 장비, 도심 위주",
        "흔한 지적": "NVH·고속 안정성은 클래스 한계",
        "옵션 팁": "AS·잔존가율·프로모션을 장기 관점에서 비교",
    },
    {
        "모델": "제네시스 GV70 등 프리미엄 SUV",
        "세그먼트": "프리미엄",
        "만족 포인트": "주행·마감·브랜드 경험",
        "흔한 지적": "유지비·보험·소모품. 파워트레인 선택에 따른 충전/연료",
        "옵션 팁": "빌트인캠·주차 패키지·HUD는 재판매 시에도 선호되는 경향",
    },
    {
        "모델": "레이·캐스퍼 등 도심형",
        "세그먼트": "경·초소형",
        "만족 포인트": "주차·유지비·1~2인 실사용",
        "흔한 지적": "적재·고속 주행은 SUV급과 차이",
        "옵션 팁": "스마트키·열선·기본 ADAS는 이후 후회가 적은 편",
    },
]

# 인기 차종별 상세(선택 시 표시). 요약 테이블 키「모델」과 동일해야 합니다.
CAR_MODEL_DETAILS: dict[str, dict[str, str]] = {
    "기아 셀토스": {
        "특징": (
            "**소형 SUV**에서 실내 체감 공간과 트렁드 활용도가 균형 있게 나오는 편입니다. "
            "전고가 높아 **승·하차와 시야**가 좋고, 투싼·스포티지 대비 **도심 회차·주차 부담**은 덜한 경우가 많습니다. "
            "파워트레인·서스펜션 세팅은 연식·등급마다 다르므로, 스펙만 보지 말고 **출퇴근·고속**을 나눠 시승하는 것이 중요합니다."
        ),
        "추천": (
            "**첫 SUV·1대차**로 도심과 가끔 장거리를 겸할 때 무난한 선택지로 자주 거론됩니다. "
            "가족 승차가 잦다면 **뒷좌석·트렁크 실측** 후 투싼과 비교하고, **ADAS 묶음**이 있는 트림/패키지를 우선 검토하세요. "
            "중고까지 염두에 두면 **인기 색·인기 트림**이 매물·감가에 영향을 줍니다."
        ),
    },
    "현대 코나": {
        "특징": (
            "**개성 있는 디자인**과 콤팩트한 차체로 도심 주행·주차에 유리합니다. "
            "**순수 전기(EV)·하이브리드·가솔린** 등 동일 이름 아래 라인업이 나뉘어 있어, "
            "연료·충전 환경에 따라 완전히 다른 차가 될 수 있습니다."
        ),
        "추천": (
            "**1~2인·출퇴근 위주**에 디자인과 주차 편의를 중시하면 코나 쪽이 셀토스·투싼과 **다른 매력**을 줍니다. "
            "전기 모델은 **집 충전·보조금·월 주행거리**를 숫자로 적어 본 뒤 가솔린과 총비용을 비교하세요. "
            "뒷좌석·트렁크를 자주 쓰면 **투싼·셀토스 실측 비교**가 필수입니다."
        ),
    },
    "현대 투싼": {
        "특징": (
            "**준중형 SUV**로 실내·적재 여유가 셀토스보다 큰 편입니다. "
            "패밀리 1대차로 **장거리·시트·트렁크** 균형이 좋다는 평이 많고, "
            "차체가 커 **좁은 곳 주차·유턴**은 SVU 소형 대비 부담이 될 수 있습니다."
        ),
        "추천": (
            "**영유아 카시트·유모차**를 자주 싣거나 **뒷좌석 장시간 탑승**이 많다면 투싼·스포티지급을 먼저 보는 경우가 많습니다. "
            "**가솔린·디젤·하이브리드**는 연비·정숙·잔진동 체감 차이가 커서 **두 번 이상 시승**을 권합니다. "
            "예산 여유가 있으면 통풍시트·전동시트·공조 편의를 **시승차에서 직접** 확인하세요."
        ),
    },
    "기아 스포티지": {
        "특징": (
            "투싼과 맞먹는 **준중형 SUV**로, 디자인·실내 마감 선호가 갈리는 대표 라이벌 관계입니다. "
            "**장거리 승차감** 호평이 자주 보이며, 옵션을 쌓으면 **견적이 빠르게 상승**합니다."
        ),
        "추천": (
            "투싼과 **동일 조건 견적**(등록비·캐시백·금리)으로 나란히 비교하는 것이 가장 안전합니다. "
            "**패키지 단위 옵션**이 많아, 부분만 골라 담기 어려울 수 있으니 우선순위 리스트를 미리 적어 두세요. "
            "브랜드·디자인 취향 외에는 **AS 거리·대리점 응대**도 후보에 넣으면 좋습니다."
        ),
    },
    "경·소형 SUV (베뉴·티볼리 등)": {
        "특징": (
            "**가격·유지비** 부담이 상대적으로 낮고, **첫 차·세컨카**로 도심 위주 사용에 적합합니다. "
            "**고속·NVH·고속 안정감**은 상위 세그먼트 대비 한계가 있다는 평이 흔합니다."
        ),
        "추천": (
            "**예산 한정·단거리 위주**면 합리적 선택이 될 수 있습니다. "
            "**잔존가율·프로모션·보증 조건**을 장기적으로 비교하고, 고속 주행이 잦다면 **한 클래스 위 시승**도 병행하세요. "
            "옵션은 **안전·주차 보조**를 먼저 채우는 편이 후회가 적습니다."
        ),
    },
    "제네시스 GV70 등 프리미엄 SUV": {
        "특징": (
            "**주행 질감·실내 소재·정숙성**에서 대중 브랜드와 차별화되는 경험을 목표로 한 세그먼트입니다. "
            "**보험료·유지비·소모품 단가**가 함께 올라가므로 총소유비용(TCO) 관점이 필요합니다."
        ),
        "추천": (
            "**브랜드·잔존가**를 중시하면 풀옵션보다 **중고 수요가 있는 패키지**(빌트인캠, 주차, HUD 등) 균형을 맞추는 전략도 있습니다. "
            "전기·가솔린·디젤 선택은 **충전·주행 패턴·유가**를 몇 년 치 가정해 보고 결정하세요. "
            "장기 렌트·리스 조건도 **공식 vs 금융사** 비교가 유효합니다."
        ),
    },
    "레이·캐스퍼 등 도심형": {
        "특징": (
            "**초소형·박스형**에 가까워 협소 구역 주차·유턴에 강합니다. "
            "1~2인 실사용·직배송·짧은 통근에 맞춘 **도심 특화** 성격이 강합니다."
        ),
        "추천": (
            "**주차 지옥·출퇴근 단거리**가 최우선이면 만족도가 높을 수 있습니다. "
            "가족 탑승·장거리·고속이 늘 계획이라면 **한 단계 큰 차급 시승**을 권합니다. "
            "**열선·스마트키·기본 ADAS**는 재판매·일상 만족 모두에 도움이 되는 경우가 많습니다."
        ),
    },
}

CAR_MAINTENANCE_BY_TIMING: list[dict[str, str]] = [
    {
        "시기·주기": "**일상(매 주행 전후)**",
        "점검·작업": "타이어 공기압, 와이퍼, 각종 램프, 브레이크 이상음",
        "메모": "EV도 타이어 마모·공기압은 연비·안전에 직결.",
    },
    {
        "시기·주기": "**1만 km 또는 6개월**(차종·오일 기준 상이)",
        "점검·작업": "엔진오일·필터, 시각 점검(브레이크 패드 두께, 냉각수)",
        "메모": "전기차는 **감속 회생**으로 패드 마모는 적을 수 있으나 점검은 동일하게.",
    },
    {
        "시기·주기": "**2만~4만 km**",
        "점검·작업": "에어클리너, 연료·점화 부주변(가솔린), 미션오일 면제 시기 확인",
        "메모": "디젤은 **요소수·DPF** 운행 조건을 수시 확인.",
    },
    {
        "시기·주기": "**4만~6만 km**",
        "점검·작업": "브레이크 디스크 상태, 배터리(12V 보조), 플러그·코일 점검 시기",
        "메모": "하이브리드·EV는 **12V 보조배터리** 교체 주기를 매뉴얼로 확인.",
    },
    {
        "시기·주기": "**5만~8만 km / 연 1회**",
        "점검·작업": "타이어 위치 교환(로테이션), 얼라인먼트(편마모 시), 에어컨 필터",
        "메모": "편마모면 **추가각·쇼바** 원인부터 점검.",
    },
    {
        "시기·주기": "**6만~10만 km**",
        "점검·작업": "미션·디퍼 오일(해당 시), 워터펌프·벨트류 예방 점검",
        "메모": "모델별로 **장수명 쿨런트**라도 누수·온도는 수시 확인.",
    },
    {
        "시기·주기": "**전기차(EV) 추가**",
        "점검·작업": "**고전압 배터리** 건강도·냉각, SW 업데이트, 충전 커넥터 이물",
        "메모": "주행거리·충전 패턴은 **SOH·보증**과 연결 — 공식 센터 기록 유지 권장.",
    },
]

CAR_EV_GUIDE_MARKDOWN: str = """
##### 전기차(EV)를 고를 때 큰 줄기

- **충전**: 집/직장 **완속** 가능 여부가 우선. 불가하면 **공용 급속** 위치·요금·대기 시간을 지도에 표시해 보세요.
- **주행거리**: 켜둔 옵션(난방·고속)에 따라 **실주행은 표시의 60~85%** 수준으로 가정하는 편이 안전합니다.
- **보조금·세제**: 연도·지역·차종별로 변동 — **구매 직전** 공식 공지·딜러 확인.
- **배터리**: **용량(kWh)** 대신 **실사용 주행거리·보증 기간·SOH** 관련 조항을 매뉴얼·계약서에서 확인하세요.
- **겨울**: 예열·주차 환경에 따라 **체력 저하**가 크니, 최악의 주간 패턴으로 시뮬레이션해 보세요.
- **V2L·대용량**: 캠핑·재난 대비 **외부 전원**이 필요하면 지원 여부와 케이블 규격을 미리 체크.
- **하이브리드와 비교**: 월 주행거리가 짧고 충전이 애매하면 **PHEV·HEV**가 총비용에서 유리할 수 있습니다.
- **보험·수리**: EV는 **부품·수리단가**가 과거 대비 개선 추세지만 차종별 편차가 큼 — **보험료 견적**을 동일 조건으로 비교하세요.
"""

CAR_TIRE_TIPS_MARKDOWN: str = """
##### 타이어·교체 꿀팁 (코스트코 및 일반)

- **코스트코(코리아)**: 회원제 창고형 매장의 **타이어 센터**에서 브랜드별 프로모션·장착비 구조가 있을 수 있습니다. **지점·재고·가격은 시점별 상이** — 방문 전 앱/고객센터·지점 문의 권장.
- **장착비·부가**: 타이어 가격 외 **마운트·밸런스·폐기·얼라인먼트** 분리 여부를 견적서에서 확인하세요. 얼라인은 **편마모·핸들 끌림** 있을 때만이 아니라, 교체 시 권장되는 경우가 많습니다.
- **사이즈·부하**: 도어 스티커·매뉴얼의 **표기 사이즈·하중·속도지수**를 지키세요. 저가 대체 사이즈는 **ABS/ESC 튜닝**과 안 맞을 수 있습니다.
- **계절**: 눈·빙판이 잦으면 **겨울용/올웨더**를 진지하게 검토. 미끄럼 한 번이 비용을 압도합니다.
- **마모**: **마모 지시계**가 나왔으면 교체 검토. 불규칙 마모면 **교환만으로는 재발** — 쇼바·각 조정 필요할 수 있음.
- **공기압**: 한 달에 한 번 차갑고 정지 상태에서 체크. EV는 **순간 토크**가 크고 차량 중량이 있어 타이어 마모가 빠른 편이라 **로테이션** 주기를 매뉴얼보다 앞당기는 오너도 있음.
- **온라인 비교**: 동일 규격으로 **다나와·네이버·오토오아시스 등** 몇 군데 **총액(장착 포함)** 을 표로 적어보면 선택이 쉬워집니다.
- **보관**: 스터드·계절 타이어는 **실내 습도 낮은 곳**, 햇빛 피해 수직 보관. 공기압을 약간 채워 변형 방지.
"""

CAR_SELTOS_FOCUS_MARKDOWN: str = """
##### 지금 고민에 맞춘 체크 포인트 (셀토스)

- **공간**: 가족·짐을 자주 싣는다면 뒷좌석·트렁크를 실측하고, 투싼·스포티지와 **같은 자세**로 비교하세요.
- **파워트레인**: 라인업·연식별로 엔진·변속 조합이 다릅니다. **스펙표보다 시승**(출퇴근·고속)을 나눠 보는 것이 좋습니다.
- **트림 vs 패키지**: 상위 트림은 **중고 매물 다양성**에도 영향을 줍니다. 순수 초기 비용만 보면 하위 트림+패키지가 유리해 보여도, 매각 시기를 생각하면 상위가 나을 수 있습니다.
- **ADAS**: 차로 유지·전방 보조·후측방 등이 **패키지 묶음**인 경우가 많아, 부분만 선택하기 어렵습니다. 안전 관련은 **최우선**으로 두는 선택이 흔합니다.
- **내비·폰**: 빌트인 내비 습관 vs 스마트폰 미러링을 시승 때 함께 맞춰 보세요.
- **선루프·통풍·전동시트**: 계절·복장·출퇴근 패턴에 따라 체감이 큽니다. **시승차에 해당 옵션이 있는지** 확인 후 결정하세요.
- **견적**: 등록비·캐시백·저금리 조합은 대리점마다 다릅니다. 2~3곳을 **동일 조건 표**로 적어 두고 비교하면 혼란이 줄어듭니다.
"""

CAR_OPTION_GUIDE_ROWS: list[dict[str, str]] = [
    {
        "상황": "출퇴근·학원 위주, 좁은 도로",
        "추천 우선순위": "① 주차·전후방 보조 ② ADAS 기본 묶음 ③ 스마트키·열선",
        "덜 우선": "대구경 휠(승차감·타이어 비용)",
    },
    {
        "상황": "고속·장거리 많음",
        "추천 우선순위": "① 크루즈·차로유지 등 고속 보조 ② 전동시트 ③ 연비·정숙(엔진 선택)",
        "덜 우선": "과한 휠, 미사용 패키지",
    },
    {
        "상황": "영유아·패밀리",
        "추천 우선순위": "① 뒷좌석·트렁크 실측 ② 후석 공조 ③ ISOFIX 편의",
        "덜 우선": "외형 위주 패키지",
    },
    {
        "상황": "첫 차·예산 민감",
        "추천 우선순위": "① 필수 안전 ② 중고 매물 많은 트림/색 ③ 보증·할인",
        "덜 우선": "손실 큰 덜 쓰는 옵션",
    },
]

CAR_REVIEW_PORTALS: list[dict[str, str]] = [
    {"t": "보배드림", "u": "https://www.bobaedream.co.kr/", "d": "국내 오너 평·시세 감."},
    {"t": "네이버 자동차", "u": "https://auto.naver.com/", "d": "뉴스·스펙."},
    {"t": "다나와 자동차", "u": "https://auto.danawa.com/", "d": "가격·트림 비교."},
    {"t": "클리앙 자동차", "u": "https://www.clien.net/service/board/cm_car", "d": "실사용 후기·질문."},
]


# 그룹 탭 7개 — 각 그룹 내부에서 서브탭으로 세분화
# 새 기능을 추가할 때: 해당 그룹의 _render_group_* 함수에 서브탭만 추가하면 됩니다.
_HOME_GROUP_SPEC: list[tuple[str, str]] = [
    ("🏘 부동산", "realty"), # 실거래·계산기·관심단지
    ("🌤️ 생활",  "life"),    # 날씨·뉴스·컴퓨터 가이드
    ("🎯 취미",  "hobby"),  # 골프 등 레저
    ("🐙 개발",  "dev"),     # IT·테크·GitHub (만화는 기타)
    ("🛍️ 쇼핑",  "shop"),    # 화장품·컴퓨터 가격비교
    ("🚗 자동차", "auto"),   # 인기 차종·셀토스·옵션 가이드
    ("✈️ 기타",  "misc"),    # 여행 스케치·AI 에이전트
]

_OPTION_MENU_STYLES: dict[str, Any] = {
    "container": {"padding": "0.35rem 0", "background-color": "transparent"},
    # 아이콘에 color를 주면 <a>의 선택/비선택 글자색을 덮어씀 → 크기만 지정하고 색은 부모 상속
    "icon": {"font-size": "1.05rem"},
    "menu-title": {"color": "#111827", "font-weight": "700"},
    "menu-icon": {"font-size": "1.1rem", "color": "#111827"},
    "nav-link": {
        "font-size": "1rem",
        "text-align": "left",
        "margin": "3px 0",
        "padding": "0.58rem 0.68rem",
        "border-radius": "8px",
        "color": "#111827",
        "background-color": "#ffffff",
        "border": "1px solid #e5e7eb",
        "--hover-color": "#f3f4f6",
    },
    "nav-link-selected": {
        "background": "#111827",
        "font-weight": "700",
        "color": "#ffffff",
        "border": "1px solid #111827",
    },
}


def _render_tab_stock() -> None:
    st.header("마이 대시보드")
    st.caption("이 탭에서 **종목·날짜 범위**를 고른 뒤 차트를 확인하세요. · Yahoo Finance")

    _sym_labels, _sym_map = _stock_ticker_select_labels()
    _picked = st.selectbox(
        "종목 선택 (Ticker)",
        options=_sym_labels,
        index=0,
        key="stock_dash_sym_pick",
    )
    if _sym_map[_picked] == "__custom__":
        stock_ticker = st.text_input(
            "Ticker 직접 입력",
            value="AAPL",
            key="stock_dash_ticker_custom",
            placeholder="예: BRK-B, 373220.KS",
        )
    else:
        stock_ticker = _sym_map[_picked]
    _de = date.today()
    _ds = _de - timedelta(days=180)
    stock_dates = st.date_input(
        "날짜 범위",
        value=(_ds, _de),
        min_value=date(1990, 1, 1),
        max_value=_de,
        key="stock_dash_range",
    )
    if st.button("주가 데이터 캐시 비우기", key="stock_dash_cache_clear"):
        load_stock_price_data.clear()

    st.divider()

    if pd is None or yf is None or go is None:
        miss = [n for n, ok in (("pandas", pd), ("yfinance", yf), ("plotly", go)) if ok is None]
        st.error(
            f"주식 탭에 필요한 패키지가 없습니다: **{', '.join(miss)}**. "
            "PC의 `requirements.txt`를 NAS에 동기화한 뒤 컨테이너에서 전체 설치를 다시 하세요."
        )
        st.code(
            "python3 -m pip install --no-cache-dir -r /app/requirements.txt",
            language="bash",
        )
        st.caption(
            "한 줄 실행 명령을 쓰는 경우, 위 `requirements.txt`에 "
            "`pandas`, `numpy`, `yfinance`, `plotly` 가 포함돼 있는지 확인 후 컨테이너 재시작. "
            "Dockerfile 빌드면 이미지 **재빌드**."
        )
    else:
        tkr = (stock_ticker or "").strip()
        if isinstance(stock_dates, tuple) and len(stock_dates) == 2:
            start_d, end_d = stock_dates[0], stock_dates[1]
        else:
            start_d, end_d = _ds, _de
        if start_d > end_d:
            start_d, end_d = end_d, start_d

        if not tkr:
            st.warning("위에서 종목을 선택하거나 직접 입력하세요.")
        else:
            df = load_stock_price_data(tkr, start_d, end_d)
            stock_sample = False
            if df.empty:
                alt = sample_stock_ohlc_dataframe(start_d, end_d, tkr)
                if alt is not None and not getattr(alt, "empty", True):
                    df = alt
                    stock_sample = True
            if df.empty:
                st.error("데이터를 가져오지 못했습니다. 티커·기간·네트워크를 확인하세요.")
            else:
                if stock_sample:
                    st.warning(
                        "야후 파이낸스에서 시세를 받지 못했습니다. **내장 샘플 OHLC**로 차트를 표시합니다 "
                        "(실제 거래와 무관)."
                    )
                close = df["Close"].astype(float)
                last = float(close.iloc[-1])
                prev = float(close.iloc[-2]) if len(close) > 1 else last
                chg = last - prev
                pct = (chg / prev * 100.0) if prev else 0.0
                hi = float(df["High"].max())
                lo = float(df["Low"].min())
                vol = float(df["Volume"].iloc[-1]) if "Volume" in df.columns else 0.0
                unit = _stock_currency_hint(tkr)
                fmt = "{:,.2f}" if unit == "USD" else "{:,.0f}"

                m1, m2 = st.columns(2)
                m3, m4 = st.columns(2)
                with m1:
                    st.metric(
                        "현재가 (종가)",
                        fmt.format(last),
                        delta=f"{chg:+.2f} ({pct:+.2f}%)",
                    )
                with m2:
                    st.metric("기간 최고", fmt.format(hi))
                with m3:
                    st.metric("기간 최저", fmt.format(lo))
                with m4:
                    st.metric("최근 거래량", f"{vol:,.0f}")
                st.caption(f"통화 참고: **{unit}**")

                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=df.index,
                            open=df["Open"].astype(float),
                            high=df["High"].astype(float),
                            low=df["Low"].astype(float),
                            close=df["Close"].astype(float),
                            increasing_line_color="#3fb950",
                            decreasing_line_color="#f85149",
                            increasing_fillcolor="rgba(63,185,80,0.35)",
                            decreasing_fillcolor="rgba(248,81,73,0.35)",
                        )
                    ]
                )
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="#231f57",
                    font=dict(color="#c7d2fe", size=12),
                    title=dict(
                        text=f"<b>{tkr}</b> · OHLC",
                        font=dict(size=18, color="#eef2ff"),
                        x=0,
                        xanchor="left",
                    ),
                    xaxis=dict(
                        gridcolor="rgba(165, 180, 252, 0.22)",
                        rangeslider=dict(visible=False),
                        type="date",
                    ),
                    yaxis=dict(gridcolor="rgba(165, 180, 252, 0.22)", side="right"),
                    margin=dict(l=8, r=8, t=52, b=8),
                    height=420,
                    autosize=True,
                    hovermode="x unified",
                    showlegend=False,
                )
                st.plotly_chart(fig, use_container_width=True)

                st.divider()
                csv_bytes = _df_to_csv_utf8_sig_bytes(df)
                st.download_button(
                    label="주가 데이터 CSV 다운로드",
                    data=csv_bytes,
                    file_name=f"{tkr.replace('^', '')}_{start_d}_{end_d}.csv",
                    mime="text/csv",
                    use_container_width=True,
                )



def _render_tab_weather() -> None:
    st.header("🌤️ 생활 날씨")
    city_key = st.selectbox(
        "지역",
        list(CITY_PRESETS.keys()),
        index=0,
        key="weather_city_pick",
    )
    lat, lon, label = CITY_PRESETS[city_key]
    src_hint = "Open-Meteo (실시간) 또는 내장 샘플"
    st.caption(f"**{label}** ({lat:.2f}°, {lon:.2f}°) · {src_hint}")

    if st.button("새로고침", key="ref_weather", use_container_width=True):
        fetch_weather_cached.clear()

    data = fetch_weather_cached(lat, lon)
    using_sample_w = False
    if not data or "current" not in data:
        data = sample_openmeteo_payload_for_city_key(city_key)
        using_sample_w = True
        st.warning(
            "Open-Meteo에 연결하지 못했습니다. **내장 샘플 데이터**로 같은 레이아웃을 표시합니다 "
            "(네트워크 없이도 UI 확인 가능)."
        )

    cur = data["current"]
    code = int(cur.get("weather_code", 0))
    r1a, r1b = st.columns(2)
    r2a, r2b = st.columns(2)
    with r1a:
        st.metric("기온", f"{cur.get('temperature_2m', 0):.1f} °C")
    with r1b:
        st.metric("체감", f"{cur.get('apparent_temperature', 0):.1f} °C")
    with r2a:
        st.metric("습도", f"{cur.get('relative_humidity_2m', 0)} %")
    with r2b:
        st.metric("풍속", f"{cur.get('wind_speed_10m', 0):.1f} km/h")
    st.subheader(wmo_label(code))
    src_label = "내장 샘플" if using_sample_w else "Open-Meteo"
    st.caption(f"위치: {label} ({lat:.4f}, {lon:.4f}) · {src_label}")

    daily = data.get("daily") or {}
    times = daily.get("time") or []
    if times:
        st.subheader("5일 요약 · 탭하여 보기 좋게")
        for i, d in enumerate(times):
            mx = daily["temperature_2m_max"][i]
            mn = daily["temperature_2m_min"][i]
            wc = wmo_label(int(daily["weather_code"][i]))
            st.markdown(
                f'<div style="padding:1rem 1.1rem;margin:0.55rem 0;border-radius:16px;'
                f"background:linear-gradient(160deg,#433d8b 0%,#3730a3 100%);"
                f"border:1px solid rgba(165,180,252,0.38);box-shadow:0 6px 22px rgba(30,27,75,0.4);"
                f'color:#fafaff;font-size:clamp(1rem, 4vw, 1.12rem);line-height:1.45;">'
                f"<strong>{html.escape(str(d))}</strong> · {html.escape(wc)}<br/>"
                f'<span style="color:#c7d2fe;font-size:1.02em;">'
                f"최고 {mx:.1f}°C · 최저 {mn:.1f}°C</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("---")
    st.info(
        "NAS·Docker에서도 동일하게 동작합니다. "
        "외부 HTTPS 접근이 막혀 있으면 방화벽에서 컨테이너 포트를 허용하세요."
    )


def _render_tab_it_news_trends() -> None:
    st.subheader("📡 IT 뉴스·동향")
    st.caption("해외·국내 **기술 뉴스·토론**을 한곳에서 열 수 있는 링크입니다. (유료·회원 정책은 각 사이트 기준)")
    st.markdown(
        """
##### 해외
- [Hacker News](https://news.ycombinator.com/) — 개발자·스타트업 이슈, 댓글 품질이 높은 편
- [Lobsters](https://lobste.rs/) — 태그 기반 IT 링크(초대 필요할 수 있음)
- [The Verge — Tech](https://www.theverge.com/tech) · [Ars Technica](https://arstechnica.com/) — 산업·정책·하드웨어
- [GitHub Trending](https://github.com/trending) — 저장소 트렌드(일간·언어별)

##### 국내
- [ZDNet Korea](https://zdnet.co.kr/) · [IT동아](https://it.donga.com/) — 기업·정책·리뷰
- [디지털타임스](https://www.dt.co.kr/) · [전자신문 인터넷](https://www.etnews.com/) — 산업 동향

##### 커뮤니티·Q&A
- [Stack Overflow](https://stackoverflow.com/) — 에러 메시지·언어별 태그 검색
- [Reddit r/programming](https://www.reddit.com/r/programming/) — 링크 위주(해외 톤)
- [클리앙 소모임 IT](https://www.clien.net/service/board/park) — 국내 사용자 시선(게시판 성격 상이)
        """
    )


def _render_tab_it_tooling() -> None:
    st.subheader("🛠️ 도구·개발 환경")
    st.markdown(
        """
##### 에디터·IDE
- **VS Code / Cursor / Windsurf**: 확장(ESLint, Python, Remote SSH)로 **언어·원격** 맞추기.
- **JetBrains** 계열: 프로젝트가 크고 **리팩터·디버그** 비중이 크면 고려.

##### 버전 관리
- **Git**: `clone` · `branch` · `commit` · `pull/push` · **`.gitignore`** 로 비밀·대용량 제외.
- **GitHub/GitLab**: PR·이슈·액션(CI) — 팀 단위면 **브랜치 규칙**을 문서로 남기기.

##### OS·터미널
- **Windows**: [WSL2](https://learn.microsoft.com/windows/wsl/)로 Linux 툴체인과 **경로 혼동**을 줄이기. **Windows Terminal** 탭·프로필 설정.
- **macOS**: **Homebrew**로 CLI 도구 설치. **iTerm2** 선택 사항.
- **Linux**: 패키지 매니저(`apt`/`dnf` 등) + **권한(sudo)** 습관 점검.

##### 언어·런타임
- **Python**: `venv` 또는 **uv/poetry**로 프로젝트별 격리. 전역 `pip install` 남용 주의.
- **Node**: **nvm/fnm**으로 버전 전환. `node_modules` 용량·보안 업데이트 주기.

##### NAS·Docker(이 포털 사용자 기준)
- 컨테이너는 **이미지 태그·볼륨 마운트**를 문서화해 두면 재현이 쉬움. **호스트 경로 vs 컨테이너 경로** 혼동 주의.
        """
    )


def _render_tab_it_cloud_infra() -> None:
    st.subheader("☁️ 클라우드·인프라(입문 감각)")
    st.markdown(
        """
##### IaaS / PaaS 한 줄
- **AWS·Azure·GCP**: **무료 티어**는 조건·기간이 바뀌기 쉬움 — 가입 시 **과금 알림·예산** 설정.
- **VPS**(DigitalOcean, Linode, 국내 호스팅): 소규모 웹·VPN·봇에 흔함. **스냅샷·백업** 옵션 확인.

##### 컨테이너
- **Docker**: 앱+의존성을 **이미지**로 묶음. **Dockerfile**은 재현성의 핵심.
- **Compose**: 여러 컨테이너 **로컬·소규모 서버** 오케스트레이션에 편함.
- **Kubernetes**: 서비스가 커지고 **롤링 업데이트·헬스체크**가 필요해질 때 검토(러닝 커브 큼).

##### 네트워크·웹
- **리버스 프록시**: Nginx, Caddy — **TLS 종료**·정적 파일·업스트림 분기.
- **DNS**: 도메인 **A/AAAA/CNAME** 이해. **CDN**(Cloudflare 등)은 캐시·DDoS緩和에 도움될 수 있음.

##### 관측
- **로그**: stdout 수집 vs 파일 마운트 — 디스크 풀 방지(**로그 로테이션**).
- **메트릭**: Prometheus+Grafana는 **자기호스팅**에서도 자주 쓰임(리소스 요구 있음).
        """
    )
    st.info("클라우드 비용은 **몇 분 만에** 누적될 수 있습니다. 실험 후 **리소스 삭제** 습관을 들이세요.", icon="💡")


def _render_tab_it_security_privacy() -> None:
    st.subheader("🔐 보안·프라이버시(일상 IT)")
    st.markdown(
        """
##### 비밀번호·2FA
- **비밀번호 관리자**(Bitwarden, 1Password, KeePass 등): **사이트마다 다른 비밀번호** + 길게.
- **2FA**: TOTP 앱(**Aegis**, Google Authenticator 등) 또는 **하드웨어 키**(YubiKey). **SMS 2FA**는 SIM 스와핑에 상대적으로 취약.
- **백업 코드**는 **오프라인** 안전한 곳에 보관.

##### 통신·VPN
- **공용 Wi-Fi**: 금융·회사 업무는 **VPN** 또는 **셀룰러 핫스팟**을 고려. VPN 업체는 **로그 정책·감사**를 확인.
- **HTTPS 자물쇠**만으로는 **피싱 사이트**를 막지 못함 — **도메인 철자**·북마크 사용.

##### 소프트웨어·OS
- **업데이트**: OS·브라우저·펌웨어. **0-day** 대응의 기본.
- **권한**: 앱이 **연락처·파일**을 왜 요구하는지 의심. 모바일 **앱 권한** 최소화.

##### 홈랩·NAS
- **관리자 포트**를 인터넷에 직접 노출하지 않기 — **VPN·리버스 프록시·방화벽**으로 제한.
- **기본 비밀번호** 변경, **2FA** 가능하면 켜기. **랜섬웨어** 대비 **오프사이트 백업** 한 벌.
        """
    )


def _render_tab_github() -> None:
    st.header("GitHub 덴")
    st.caption(
        "홈랩·자기호스팅·데이터·생산성·취미 위주로 골랐습니다. "
        "저장소 Star·설명은 GitHub 기준이며, 투자·에뮬 사용은 본인 책임·라이선스를 확인하세요."
    )
    sub_cur, sub_search = st.tabs(["📚 큐레이션", "🔍 Star 레포 검색"])

    with sub_cur:
        for block in CURATED_GITHUB:
            st.subheader(str(block["title"]))
            for it in block["items"]:
                d = str(it.get("d") or "").strip()
                line = f"**[{it['t']}]({it['u']})**"
                if d:
                    line += f" — {d}"
                st.markdown(line)
            st.markdown("")

    with sub_search:
        labels = [x[0] for x in GITHUB_SEARCH_PRESETS]
        choice = st.selectbox("검색 프리셋", range(len(labels)), format_func=lambda i: labels[i])
        custom_q = st.text_input(
            "직접 검색어 (GitHub `q` 문법, 비우면 프리셋 사용)",
            placeholder="예: homelab stars:>1000 language:python",
        )
        per_page = st.slider("결과 개수", 5, 20, 12)
        c1, c2 = st.columns(2)
        with c1:
            do_search = st.button("검색 실행", type="primary")
        with c2:
            if st.button("검색 캐시 비우기"):
                github_search_cached.clear()
                st.info("캐시를 비웠습니다. 다시 검색 실행을 누르세요.")

        if do_search:
            q = custom_q.strip() if custom_q.strip() else GITHUB_SEARCH_PRESETS[choice][1]
            rows, err = github_search_cached(q, per_page=per_page)
            if err:
                st.warning(f"{err} · 아래는 **내장 샘플 결과**입니다.")
                rows = SAMPLE_GITHUB_SEARCH_ROWS[
                    : max(1, min(per_page, len(SAMPLE_GITHUB_SEARCH_ROWS)))
                ]
            elif not rows:
                st.warning("결과가 없습니다. 검색어를 바꿔 보세요.")

            if rows:
                src = "내장 샘플 (API 미연결 또는 한도)" if err else "GitHub API 응답"
                st.success(f"쿼리: `{q}` · {src}")
                for row in rows:
                    st.markdown(
                        f"**[{row['repo']}]({row['url']})** · ⭐ {row['stars']:,} · `{row['lang']}`"
                    )
                    if row["설명"]:
                        st.caption(row["설명"])



def _render_tab_comics() -> None:
    st.header("만화·웹툰 (정식 무료 구간)")
    st.warning(
        "**불법 스캔·무단 번역 사이트는 링크하지 않습니다.** "
        "아래는 출판사·플랫폼이 제공하는 무료 회차, 광고 지원 서비스, "
        "또는 공공 도메인·보존 자료입니다. 유료 회차는 각 사이트 정책을 따르세요."
    )
    for bi, block in enumerate(FREE_COMICS_SITES):
        st.subheader(str(block["title"]))
        for ij, it in enumerate(block["items"]):
            d = str(it.get("d") or "").strip()
            safe_name = html.escape(it["t"])
            safe_url = html.escape(it["u"], quote=True)
            st.markdown(
                f'<a href="{safe_url}" target="_blank" rel="noopener noreferrer" '
                f'style="display:block;padding:0.95rem 1.15rem;margin:0.5rem 0;border-radius:16px;'
                f"background:linear-gradient(160deg,#4f46e5 0%,#433d8b 100%);"
                f"border:1px solid rgba(165,180,252,0.38);box-shadow:0 6px 22px rgba(30,27,75,0.38);"
                f"font-size:clamp(1.02rem, 4.2vw, 1.18rem);font-weight:600;color:#fafaff;"
                f'text-decoration:none;line-height:1.35;">{safe_name} <span style="color:#c7d2fe">→</span></a>',
                unsafe_allow_html=True,
            )
            if d:
                st.caption(d)
        st.markdown("")



def _render_tab_fx() -> None:
    st.header("환율 스냅샷 (원화 환산)")
    st.caption(
        "포털에서 US·국내 시장을 같이 보실 때 참고용입니다. "
        "데이터: [Frankfurter](https://www.frankfurter.app/) · ECB 일간 기준(주말·공휴일은 전 영업일). "
        "실거래·세금은 은행·증권사 고시 환율을 확인하세요."
    )
    if st.button("환율 새로고침", key="ref_fx"):
        fetch_fx_usd_base.clear()

    fx = fetch_fx_usd_base()
    using_sample_fx = False
    if not fx or "rates" not in fx:
        fx = SAMPLE_FX_USD_BASE
        using_sample_fx = True
        st.warning(
            "Frankfurter 환율 API에 연결하지 못했습니다. **내장 샘플 환율**로 표시합니다 "
            "(실거래와 무관한 데모 수치)."
        )

    rates = fx["rates"]
    d = fx.get("date", "—")
    krw = float(rates["KRW"])
    jpy = float(rates["JPY"])
    eur = float(rates["EUR"])
    krw_per_jpy = krw / jpy
    krw_per_eur = krw / eur

    c1, c2, c3 = st.columns(3)
    with c1:
        st.metric("1 USD", f"{krw:,.2f} 원")
    with c2:
        st.metric("100 JPY", f"{100 * krw_per_jpy:,.2f} 원")
    with c3:
        st.metric("1 EUR", f"{krw_per_eur:,.2f} 원")

    st.markdown("---")
    st.subheader("역산 (대략)")
    inv = [
        {"표시": "1만 원", "USD": 10_000 / krw, "JPY": 10_000 / krw_per_jpy, "EUR": 10_000 / krw_per_eur},
        {"표시": "10만 원", "USD": 100_000 / krw, "JPY": 100_000 / krw_per_jpy, "EUR": 100_000 / krw_per_eur},
    ]
    st.dataframe(
        [
            {
                "기준": row["표시"],
                "≈ USD": f"{row['USD']:.2f}",
                "≈ JPY": f"{row['JPY']:.0f}",
                "≈ EUR": f"{row['EUR']:.2f}",
            }
            for row in inv
        ],
        use_container_width=True,
        hide_index=True,
    )
    cap = f"기준일: {d} · 1 USD = {jpy:.2f} JPY · 1 USD = {eur:.4f} EUR"
    if using_sample_fx:
        cap += " · 출처: 내장 샘플"
    st.caption(cap)

    st.markdown("---")
    st.subheader("🔮 USD/KRW 단기 참고 예측")
    st.caption(
        "Yahoo Finance 일봉(`KRW=X`)으로 **최근 N거래일 로그-선형 추세**를 맞춘 뒤, 다음 영업일 구간을 **통계적으로 외삽**합니다. "
        "밴드는 회귀 잔차 표준편차에 비례한 **단순 구간**입니다. "
        "**실제 거래·고시 환율과 다르며**, 뉴스·금리·지정학에 환율이 크게 흔들릴 수 있어 **교육·감각용**으로만 보세요."
    )
    cpa, cpb, cpc = st.columns(3)
    with cpa:
        fx_hist_period = st.selectbox("과거 일봉 구간", ["1y", "2y", "5y"], index=1, key="fx_pred_yf_period")
    with cpb:
        fx_horizon = st.slider("예측 영업일 수", 5, 60, 20, key="fx_pred_horizon_days")
    with cpc:
        fx_fit_w = st.slider("추세 적합 거래일 수", 40, 252, 120, key="fx_pred_fit_window")
    if st.button("일봉 캐시 비우기", key="fx_pred_clear_yf_cache"):
        _fx_yahoo_krw_x_close_series.clear()
        st.rerun()

    hist_s = _fx_yahoo_krw_x_close_series(fx_hist_period)
    if hist_s is None:
        st.warning("Yahoo Finance에서 USD/KRW 일봉을 가져오지 못했습니다. 네트워크·방화벽·yfinance 설치를 확인해 주세요.")
    else:
        fc = _fx_forecast_krw_per_usd_log_linear(
            hist_s,
            horizon_days=int(fx_horizon),
            fit_window=int(fx_fit_w),
        )
        if fc is None:
            st.info("데이터가 부족해 예측을 계산하지 못했습니다. 구간을 넓혀 보세요.")
        else:
            st.caption(
                f"적합 표본 **{fc['fit_n']}**거래일 · 로그추세 R²≈**{fc['r2_log']:.3f}** · "
                f"마지막 종가 **{fc['last_close']:,.2f}**원/$ ({fc['last_date'].strftime('%Y-%m-%d')})"
            )
            m1, m2, m3 = st.columns(3)
            with m1:
                st.metric(
                    f"예측 종가일 ({fc['dates'][-1].strftime('%Y-%m-%d')}) 중앙",
                    f"{float(fc['mid'][-1]):,.2f} 원/$",
                )
            with m2:
                st.metric("같은 날 밴드 하단(참고)", f"{float(fc['lo'][-1]):,.2f} 원/$")
            with m3:
                st.metric("같은 날 밴드 상단(참고)", f"{float(fc['hi'][-1]):,.2f} 원/$")

            tail_n = min(300, len(hist_s))
            tail = hist_s.iloc[-tail_n:]
            if go is not None:
                fig_fx = go.Figure()
                fig_fx.add_trace(
                    go.Scatter(
                        x=tail.index,
                        y=tail.values,
                        name="종가(과거)",
                        line=dict(color="#64748b", width=1.2),
                    )
                )
                xd = fc["dates"]
                fig_fx.add_trace(
                    go.Scatter(
                        x=xd,
                        y=fc["hi"],
                        mode="lines",
                        line=dict(width=0),
                        showlegend=False,
                        hoverinfo="skip",
                    )
                )
                fig_fx.add_trace(
                    go.Scatter(
                        x=xd,
                        y=fc["lo"],
                        mode="lines",
                        line=dict(width=0),
                        fill="tonexty",
                        fillcolor="rgba(37,99,235,0.18)",
                        name="대략 밴드",
                    )
                )
                fig_fx.add_trace(
                    go.Scatter(
                        x=xd,
                        y=fc["mid"],
                        name="예측(중앙)",
                        line=dict(color="#2563eb", width=2, dash="dash"),
                    )
                )
                fig_fx.update_layout(
                    height=420,
                    margin=dict(t=28, b=40, l=48, r=24),
                    legend=dict(orientation="h", y=1.08, x=0, font=dict(size=11)),
                    yaxis=dict(title="원 / 1 USD", gridcolor="rgba(148,163,184,0.2)"),
                    xaxis=dict(gridcolor="rgba(148,163,184,0.2)"),
                    paper_bgcolor="rgba(255,255,255,0)",
                    plot_bgcolor="rgba(248,250,252,0.9)",
                )
                st.plotly_chart(fig_fx, use_container_width=True, config={"displayModeBar": True})
            elif pd is not None:
                st.line_chart(
                    pd.DataFrame({"과거": tail, "예측중앙": pd.Series(fc["mid"], index=fc["dates"])}),
                    use_container_width=True,
                )
            else:
                st.caption("Plotly·pandas가 없어 차트 대신 위 수치만 표시합니다.")

            with st.expander("예측 일별 표 (영업일)", expanded=False):
                tbl = pd.DataFrame(
                    {
                        "영업일": [x.strftime("%Y-%m-%d") for x in fc["dates"]],
                        "중앙(원/$)": [round(float(x), 2) for x in fc["mid"]],
                        "하단(원/$)": [round(float(x), 2) for x in fc["lo"]],
                        "상단(원/$)": [round(float(x), 2) for x in fc["hi"]],
                    }
                )
                st.dataframe(tbl, use_container_width=True, hide_index=True)


def _render_tab_clocks() -> None:
    st.header("글로벌 시각 · 투자 허브")
    st.caption(
        "주요 증시·선물 거점의 **현재 시각**과 **지도**를 함께 봅니다. "
        "휴장·서머타임·단축장은 거래소 캘린더를 따르세요."
    )

    with st.container(border=True):
        st.markdown("##### 어디를 주로 보면 좋을까? (한국 투자자 기준)")
        st.markdown(
            """
| 우선순위 | 거점 | 왜 보나 |
|:---|:---|:---|
| **1** | **미국 (뉴욕·시카고)** | 글로벌 금리·빅테크·**야간 선물·전일 증시**가 다음날 **코스피·환율 심리**에 가장 크게 스며듦. |
| **2** | **서울** | **현물·ETF** 실제 매매 시간. 장중 뉴스·수급의 기준. |
| **3** | **일본** | 아시아에서 가장 먼저 움직이는 축. **엔·반도체·리스크온/오프** 감각. |
| **4** | **홍콩·중국(상해)** | **H주·ADR·무역·원자재** 등 중국 성장·정책 뉴스의 전초. |
| **5** | **영국(런던)** | **FX·유럽장**. 한국 **아침**에 유럽 마감·미국 프리마켓 뉴스가 겹치는 시간대. |

**홍콩 vs 미국?** 둘 다 중요하지만, 보통 **미국 증시·금리 → 그다음 날 아시아** 순으로 **심리·자금 흐름**이 전파되는 경우가 많습니다. 홍콩은 **중국·H주** 비중이 클 때 더 민감합니다.
            """
        )

    hub_rows: list[dict[str, Any]] = []
    lats: list[float] = []
    lons: list[float] = []
    map_text: list[str] = []
    map_colors: list[str] = []

    _hub_color: dict[str, str] = {
        "서울": "#2563eb",
        "도쿄": "#2563eb",
        "홍콩": "#2563eb",
        "상해": "#2563eb",
        "런던": "#059669",
        "그리니치(UTC)": "#64748b",
        "뉴욕": "#7c3aed",
        "시카고": "#7c3aed",
    }

    for label, zid, la, lo, role in INVESTMENT_WORLD_HUBS:
        try:
            zi = ZoneInfo(zid)
        except Exception:
            zi = ZoneInfo("UTC")
        t = datetime.now(zi)
        ts = t.strftime("%m-%d %H:%M")
        hub_rows.append({"도시": label, "현지 시각": ts, "역할": role, "TZ": zid})
        lats.append(la)
        lons.append(lo)
        map_text.append(f"{label}  {ts}")
        map_colors.append(_hub_color.get(label, "#64748b"))

    if pd is not None:
        st.dataframe(pd.DataFrame(hub_rows), use_container_width=True, hide_index=True)
    else:
        st.json(hub_rows)

    if go is not None:
        fig_geo = go.Figure(
            data=[
                go.Scattergeo(
                    lon=lons,
                    lat=lats,
                    text=map_text,
                    mode="markers+text",
                    textposition="top center",
                    marker=dict(
                        size=12,
                        color=map_colors,
                        line=dict(width=1.5, color="#ffffff"),
                        opacity=0.92,
                    ),
                    hovertemplate="%{text}<extra></extra>",
                )
            ]
        )
        fig_geo.update_layout(
            title=dict(text="주요 투자·거래 거점 (현지 시각은 표·마커 참고)", font=dict(size=14)),
            height=460,
            margin=dict(l=0, r=0, t=48, b=0),
            geo=dict(
                projection=dict(type="natural earth"),
                showland=True,
                landcolor="#f1f5f9",
                showocean=True,
                oceancolor="#e0f2fe",
                showcountries=True,
                countrycolor="#cbd5e1",
                resolution=110,
                lonaxis=dict(range=[-170, 180]),
                lataxis=dict(range=[-55, 72]),
            ),
            paper_bgcolor="rgba(255,255,255,0)",
        )
        st.plotly_chart(fig_geo, use_container_width=True, config={"displayModeBar": True})
        st.caption("마커 색: **파랑** 아시아권 · **초록** 유럽·중동권 · **보라** 미주.")
    else:
        st.info("Plotly가 없어 세계 지도는 생략됩니다. 표의 시각만 참고하세요.")

    st.markdown("---")
    st.subheader("미국 주식 정규장 (NYSE · 참고)")
    hint_title, hint_body = nyse_regular_session_hint()
    st.info(f"**{hint_title}**  \n{hint_body}")
    st.caption(
        "정규장은 미 동부 09:30–16:00, 월–금만 표시합니다. "
        "독립기념일 등 휴장·단축장은 반영하지 않습니다."
    )



def _calc_land_tax(공시지가_만원: float, land_type: str = "종합합산 (나대지·잡종지)") -> float:
    """연간 토지 보유세 추정 (토지분 재산세 + 종합합산 종부세, 만원 반환).

    공시지가 = 시세 × 65% (2024년 현실화율 평균)
    토지 재산세: 공시지가 × 공정가액비율(70%) 기준 누진세율
    종합부동산세(종합합산): 공시지가 합산 5억 초과분에 누진세율
    ※ 별도합산(상가용 토지)은 공시지가 80억 기준이므로 일반 개인 토지는 종합합산 적용
    """
    공시지가 = 공시지가_만원 * 0.65  # 현실화율 65%

    # ── 토지분 재산세 ──
    # 과세표준 = 공시지가 × 공정가액비율(70%)
    과세표준 = 공시지가 * 0.70

    if land_type == "종합합산 (나대지·잡종지)":
        # 종합합산 세율: 0.2% ~ 0.5%
        종합_구간: list[tuple[float, float, float]] = [
            (5_000,      0.0,    0.002),   # 5천만 이하 0.2%
            (100_000,    10.0,   0.003),   # 5천만~10억 0.3%
            (float("inf"), 295.0, 0.005),  # 10억 초과 0.5%
        ]
        재산세 = 0.0
        prev = 0.0
        for limit, base, rate in 종합_구간:
            if 과세표준 <= prev:
                break
            taxable = min(과세표준, limit) - prev
            재산세 = base + taxable * rate
            prev = limit
            if 과세표준 <= limit:
                break
    elif land_type == "별도합산 (상가·사무실 부속토지)":
        # 별도합산 세율: 0.2% ~ 0.4%
        별도_구간: list[tuple[float, float, float]] = [
            (20_000,     0.0,    0.002),
            (1_000_000,  40.0,   0.003),
            (float("inf"), 2_980.0, 0.004),
        ]
        재산세 = 0.0
        prev = 0.0
        for limit, base, rate in 별도_구간:
            if 과세표준 <= prev:
                break
            taxable = min(과세표준, limit) - prev
            재산세 = base + taxable * rate
            prev = limit
            if 과세표준 <= limit:
                break
    else:
        # 분리과세 (전·답·목장용지·임야): 공시지가 × 0.07%
        재산세 = 과세표준 * 0.0007

    if land_type != "종합합산 (나대지·잡종지)":
        return 재산세  # 별도합산·분리과세는 개인 수준 종부세 낮으므로 재산세만

    # ── 종합합산토지 종부세 ──
    # 과세표준 = (공시지가 - 5억 공제) × 100% (토지분 공정가액비율 100%)
    공제액 = 50_000  # 5억 만원
    종부_과세표준 = max(0.0, 공시지가 - 공제액)
    종부_구간: list[tuple[float, float]] = [
        (100_000,    0.010),   # 10억 이하 1.0%
        (400_000,    0.020),   # 40억 이하 2.0%
        (float("inf"), 0.030), # 40억 초과 3.0%
    ]
    종부세 = 0.0
    prev2 = 0.0
    for limit2, rate2 in 종부_구간:
        if 종부_과세표준 <= prev2:
            break
        taxable2 = min(종부_과세표준, limit2) - prev2
        종부세 += taxable2 * rate2
        prev2 = limit2
        if 종부_과세표준 <= limit2:
            break

    return 재산세 + 종부세


def _calc_property_tax(시세_만원: float, num_houses: int) -> float:
    """연간 부동산 보유세 추정 (재산세 + 종부세, 만원 반환).

    단순화 모델:
    - 공시가격 = 시세 × 70%
    - 재산세: 공시가격 × 공정가액비율(60%) 기준 누진세율
    - 종부세: 1주택 공제 12억 / 다주택 공제 9억, 누진세율
    실제 세금은 공시가격·세율 변경·각종 공제에 따라 크게 다릅니다.
    """
    공시가격 = 시세_만원 * 0.70
    공정가액 = 공시가격 * 0.60  # 재산세 과세표준

    # 재산세 누진세율 (과세표준 기준, 만원)
    재산세_구간: list[tuple[float, float, float]] = [
        (6_000,  0,       0.001),   # 6천만 이하 0.1%
        (15_000, 6,       0.0015),  # 6천~1.5억 0.15%
        (30_000, 19.5,    0.0025),  # 1.5억~3억 0.25%
        (float("inf"), 57, 0.004),  # 3억 초과 0.4%
    ]
    재산세 = 0.0
    prev = 0.0
    for limit, base, rate in 재산세_구간:
        if 공정가액 <= prev:
            break
        taxable = min(공정가액, limit) - prev
        재산세 = base + taxable * rate
        prev = limit
        if 공정가액 <= limit:
            break

    # 종부세 (공시가격 합산 기준)
    if num_houses <= 0:
        return 재산세

    if num_houses == 1:
        공제액 = 120_000   # 12억 만원
        종부_구간: list[tuple[float, float]] = [
            (30_000,  0.005),
            (60_000,  0.007),
            (120_000, 0.010),
            (250_000, 0.013),
            (500_000, 0.015),
            (940_000, 0.020),
            (float("inf"), 0.027),
        ]
    else:
        공제액 = 90_000    # 9억 만원
        종부_구간 = [
            (30_000,  0.012),
            (60_000,  0.016),
            (120_000, 0.022),
            (250_000, 0.036),
            (500_000, 0.050),
            (float("inf"), 0.060),
        ]

    종부_과세표준 = max(0.0, (공시가격 - 공제액) * 0.60)
    종부세 = 0.0
    prev2 = 0.0
    for limit2, rate2 in 종부_구간:
        if 종부_과세표준 <= prev2:
            break
        taxable2 = min(종부_과세표준, limit2) - prev2
        종부세 += taxable2 * rate2
        prev2 = limit2
        if 종부_과세표준 <= limit2:
            break

    return 재산세 + 종부세


def _render_tab_asset_sim() -> None:  # noqa: PLR0912, PLR0914, PLR0915
    """💰 자산 시뮬레이션 — 부동산·토지·금융·대출·월세·생활비·세금 10년 예측"""
    st.header("💰 자산 시뮬레이션")

    # ── 인사이트 배너 ──
    st.markdown(
        """
<div style="padding:1.1rem 1.2rem 1.2rem;border-radius:16px;
background-color:#e8f2ff;border:1px solid #bfdbfe;border-left:5px solid #60a5fa;
margin-bottom:0.85rem;box-shadow:0 1px 3px rgba(15,23,42,0.06);">
<p style="margin:0 0 0.55rem;font-size:1.08rem;font-weight:800;color:#0c4a6e;letter-spacing:-0.02em;">
🧠 이 시뮬레이터가 바라보는 방식</p>

<p style="margin:0 0 0.45rem;color:#1e293b;font-size:0.98rem;line-height:1.55;">
<b style="color:#0f172a;">① 실질 수익률 = 명목 상승률 − 물가 상승률</b><br>
모든 금액은 물가를 차감한 <u style="color:#0e7490;">실질 가치(오늘의 구매력)</u>로 표시합니다.<br>
부동산 연 +1% · 물가 +2.5% → 실질 <b style="color:#b91c1c;">−1.5%</b> &nbsp;|&nbsp;
예금 +3% · 물가 +2.5% → 실질 <b style="color:#047857;">+0.5%</b></p>

<p style="margin:0 0 0.45rem;color:#1e293b;font-size:0.98rem;line-height:1.55;">
<b style="color:#0f172a;">② 전세의 진짜 비용 = 기회비용</b><br>
전세는 월세 대신 목돈을 맡기는 구조입니다.
그 돈을 투자했다면 얻을 수익이 <u style="color:#0e7490;">사라진 기회비용</u>이며, 이것이 실질 월세입니다.<br>
예) 전세금 3억 × 연 5% ÷ 12 = 월 <b style="color:#b45309;">125만원</b> 기회비용<br>
집주인 입장에서는 무이자 대출을 받아 그 돈을 운용하는 구조입니다.</p>

<p style="margin:0;color:#334155;font-size:0.9rem;line-height:1.45;">
📌 차트 선이 <b style="color:#0f172a;">상승</b> = 실질 구매력 증가 &nbsp;|&nbsp;
<b style="color:#0f172a;">수평</b> = 물가만큼만 유지 &nbsp;|&nbsp; <b style="color:#0f172a;">하락</b> = 실질 손실</p>
</div>
        """,
        unsafe_allow_html=True,
    )

    # ── 상승률·수익률 프리셋 ──
    RE_RATE_MAP: dict[str, float] = {
        "서울 (연 +5.0%)":   5.0,
        "수도권 (연 +3.5%)": 3.5,
        "광역시 (연 +2.5%)": 2.5,
        "지방 (연 +1.5%)":   1.5,
        "직접 입력":          0.0,
    }
    LAND_RATE_MAP: dict[str, float] = {
        "서울 핵심 (강남·마포, 연 +6.5%)":      6.5,
        "서울 근교·경기 개발지 (연 +5.0%)":     5.0,
        "세종시·신도시 (연 +5.5%)":             5.5,
        "수도권 일반 (연 +3.5%)":               3.5,
        "지방 광역시 (연 +2.5%)":               2.5,
        "지방 일반 (연 +1.5%)":                 1.5,
        "농지·임야 (연 +1.0%)":                 1.0,
        "직접 입력":                             0.0,
    }
    STOCK_RATE_MAP: dict[str, float] = {
        "S&P 500 장기 평균 (연 +10%)": 10.0,
        "코스피 장기 평균 (연 +6%)":    6.0,
        "혼합 포트폴리오 (연 +8%)":     8.0,
        "직접 입력":                     0.0,
    }

    st.caption("입력값·상승률은 **예측·참고치**입니다. 실제 세금·수익률은 시장·개인 상황에 따라 크게 다를 수 있습니다.")

    # ════════════════════════════════════════
    # ① 자산 입력
    # ════════════════════════════════════════
    with _st_try_border_container():
        st.subheader("🏠 부동산")
        c1, c2 = st.columns(2)
        with c1:
            re_val_uk = st.number_input(
                "현재 시세 (억원)", min_value=0.0, value=5.0, step=0.5,
                format="%.1f", key="sim_re_val",
            )
            re_val = re_val_uk * 10_000
        with c2:
            re_region = st.selectbox("지역·상승률 기준", list(RE_RATE_MAP.keys()), key="sim_re_region")
        if re_region == "직접 입력":
            re_rate = st.number_input("부동산 연 상승률 (%)", min_value=-20.0, max_value=50.0,
                                      value=3.0, step=0.5, format="%.1f", key="sim_re_rate_custom")
        else:
            re_rate = RE_RATE_MAP[re_region]

        st.markdown("**🏛️ 종부세 과세 주택 수**")
        num_houses = st.radio(
            "종부세 과세 주택 수",
            options=[0, 1, 2, 3],
            format_func=lambda x: {0:"0채(무주택)",1:"1채(공제12억)",2:"2채(공제9억·중과)",3:"3채+(공제9억·중과)"}[x],
            index=1, key="sim_num_houses", horizontal=True,
        )
        n_houses = int(num_houses)
        preview_tax = _calc_property_tax(re_val_uk * 10_000, n_houses)
        st.caption(f"현재 연간 보유세 추정 **{preview_tax:,.0f} 만원** · 재산세+종부세 단순모델")
        with st.expander("💡 부동산 금융 상식", expanded=False):
            st.markdown("""
**레버리지 효과**
대출로 5억 집을 1억 자본으로 샀을 때, 집값이 10% 오르면 투자 수익률은 50% (단, 이자 비용 차감 필요)

**실질 수익률 공식**
> 실질 수익률 = 시세 상승률 − 물가 상승률 − 보유세율 − 거래비용(취득세·중개수수료 등)

**공시가격과 실거래가**  
공시가격 ≈ 시세 × 60~80% (지역·유형별 차이) → 종부세 과세 기준

**다주택 핵심 리스크**  
2주택부터 종부세 중과 + 양도세 중과 적용 → 보유 기간 중 현금흐름 꼼꼼히 확인
""")

    LAND_TYPE_OPTIONS = [
        "종합합산 (나대지·잡종지)",
        "별도합산 (상가·사무실 부속토지)",
        "분리과세 (전·답·임야)",
    ]

    with _st_try_border_container():
        st.subheader("🌱 토지")
        ca, cb = st.columns(2)
        with ca:
            land_val_uk = st.number_input("토지 현재 시세 (억원)", min_value=0.0, value=0.0,
                                          step=0.5, format="%.1f", key="sim_land_val")
            land_val = land_val_uk * 10_000
        with cb:
            land_region = st.selectbox("토지 지역·상승률", list(LAND_RATE_MAP.keys()), key="sim_land_region")
        if land_region == "직접 입력":
            land_rate = st.number_input("토지 연 상승률 (%)", min_value=-20.0, max_value=50.0,
                                        value=2.0, step=0.5, format="%.1f", key="sim_land_rate_custom")
        else:
            land_rate = LAND_RATE_MAP[land_region]

        land_type = st.radio(
            "토지 유형 (세금 계산 기준)",
            options=LAND_TYPE_OPTIONS,
            index=0,
            key="sim_land_type",
            horizontal=True,
            help="종합합산: 나대지·잡종지(가장 높은 세율) | 별도합산: 상가 부속 토지 | 분리과세: 농지·임야",
        )

        if land_val > 0:
            # 시세 → 공시지가로 변환해 세금 계산
            preview_land_tax = _calc_land_tax(land_val, land_type)
            st.caption(
                f"현재 연간 토지 보유세 추정 **{preview_land_tax:,.0f} 만원** "
                f"(공시지가 {land_val * 0.65 / 10_000:.2f}억 기준 · {land_type[:5]})"
            )
        with st.expander("💡 토지 금융 상식", expanded=False):
            st.markdown("""
**토지 수익의 특성**  
건물 없이 '개발 기대감'만으로 가격 형성 → 장기 보유 관점, 환금성(팔기 어려움)이 낮음

**비사업용 토지 양도세 중과**  
농지·임야 등 직접 사용하지 않는 토지는 양도세율 +10%p 중과 가능성 → 취득 전 확인 필수

**농지 취득 요건 (농지법)**  
농지는 농업인·농업법인만 취득 원칙 → 주말·체험영농 목적은 1,000㎡ 이하 가능  
농지취득자격증명(농취증) 미발급 시 매매 불가

**토지 개발이익**  
도로 개설·용도 변경·도시계획 수립 시 가치 급등 가능 → 정보 비대칭이 큰 시장
""")

    with _st_try_border_container():
        st.subheader("📈 금융자산 (주식·펀드·예금)")
        c3, c4 = st.columns(2)
        with c3:
            stock_val = st.number_input("주식·펀드 평가액 (만원)", min_value=0, value=5_000,
                                        step=500, key="sim_stock_val")
            cash_val  = st.number_input("현금·예금 (만원)", min_value=0, value=3_000,
                                        step=500, key="sim_cash_val")
        with c4:
            stock_preset = st.selectbox("수익률 기준", list(STOCK_RATE_MAP.keys()), key="sim_stock_preset")
            monthly_invest = st.number_input("월 추가 투자 (만원)", min_value=0, value=100,
                                             step=50, key="sim_monthly")
        if stock_preset == "직접 입력":
            stock_rate = st.number_input("주식 연 수익률 (%)", min_value=-50.0, max_value=100.0,
                                         value=8.0, step=0.5, format="%.1f", key="sim_stock_rate_custom")
        else:
            stock_rate = STOCK_RATE_MAP[stock_preset]
        with st.expander("💡 금융자산 투자 상식", expanded=False):
            st.markdown("""
**복리의 힘 (72의 법칙)**  
원금이 2배 되는 기간 ≈ 72 ÷ 연 수익률  
연 8% → 약 9년 / 연 6% → 약 12년

**달러 비용 평균법 (DCA)**  
매월 일정액을 꾸준히 투자 → 고점 집중 매수 위험 완화 · 심리적 부담 감소

**분산 투자 원칙**  
| 유형 | 특징 |
|---|---|
| 국내 지수(코스피) | 환율 위험 없음, 연 수익률 낮음 |
| 미국 지수(S&P500) | 장기 연 10% 수준, 환율 변동 있음 |
| 채권 혼합 | 변동성 완화, 수익률 낮음 |

**세금 고려**  
국내 주식 매매차익: 대주주 기준 아니면 비과세  
해외 주식 매매차익: 연 250만원 초과분 22% 양도세
""")

    with _st_try_border_container():
        st.subheader("🏦 대출")
        c5, c6 = st.columns(2)
        with c5:
            loan_val  = st.number_input("대출 잔액 (만원)", min_value=0, value=20_000,
                                        step=1_000, key="sim_loan_val")
            loan_rate = st.number_input("대출 금리 (%/년)", min_value=0.0, value=4.0,
                                        step=0.1, format="%.1f", key="sim_loan_rate")
        with c6:
            loan_repay = st.number_input("연간 상환액 (만원)", min_value=0, value=1_200,
                                         step=100, key="sim_loan_repay",
                                         help="원리금 합산 연간 상환액")
            inflation  = st.number_input("물가 상승률 (%/년)", min_value=0.0, value=2.5,
                                         step=0.1, format="%.1f", key="sim_inflation")
        with st.expander("💡 대출 금융 상식", expanded=False):
            st.markdown("""
**단기 vs 장기 대출 선택 전략**

| 상황 | 유리한 선택 |
|---|---|
| 금리 **하락** 예상 | 단기·변동금리 → 만기 후 더 낮은 금리로 재대출 |
| 금리 **상승** 예상 | 장기·고정금리 → 지금 낮은 금리 장기 확보 |
| 금리 **불확실** | 혼합형(5년 고정 후 변동) 분산 |

**상환 방식 비교**

| 방식 | 특징 |
|---|---|
| 원리금균등상환 | 매달 동일 납부, 초기 이자 비중 높음 |
| 원금균등상환 | 초기 부담 크지만 **총이자 적음** |
| 거치식 | 원금 유예, 이자만 납부 → 총비용 가장 큼 |

**DSR (총부채원리금상환비율)**  
연 소득 대비 전체 대출 원리금 상환액 비율  
2024년 기준: **스트레스 DSR** 적용으로 실질 한도 축소  
→ 연 소득의 40% 초과 시 신규 대출 제한

**금리 1%의 무게**  
1억 대출 기준 금리 1% 차이 = 연 약 **100만원** 이자 차이  
3억 대출이라면 1% = 연 **300만원** 차이
""")

    with _st_try_border_container():
        st.subheader("💸 월별 수입 / 지출")
        st.caption("모든 항목은 만원/월 기준 · 기본값은 일반적인 100만원대 규모")

        c7, c8 = st.columns(2)
        with c7:
            monthly_rent_in  = st.number_input("🟢 월세 수입 (만원/월)", min_value=0, value=0,
                                               step=100, key="sim_rent_in",
                                               help="보유 부동산 임대 수입")
            monthly_etc_in   = st.number_input("🟢 기타 수입 (만원/월)", min_value=0, value=0,
                                               step=100, key="sim_etc_in",
                                               help="근로소득 외 사업·배당 등 추가 수입")
        with c8:
            monthly_rent_out = st.number_input("🔴 월세 지출 (만원/월)", min_value=0, value=0,
                                               step=100, key="sim_rent_out",
                                               help="임차 중인 경우의 월세")
            monthly_living   = st.number_input("🔴 생활비 (만원/월)", min_value=0, value=300,
                                               step=100, key="sim_living",
                                               help="식비·교통·통신·교육 등 월 생활비")

        # ── 전세 섹션 ──
        st.markdown("---")
        st.markdown("**🔑 전세 설정**")
        jeonse_type = st.radio(
            "전세 구분",
            options=["없음", "전세 임차 (내가 세입자)", "전세 임대 (내가 집주인)"],
            index=0, key="sim_jeonse_type", horizontal=True,
        )

        jeonse_opp_cost_monthly = 0.0  # 최종 월 기회비용/수익

        if jeonse_type != "없음":
            jc1, jc2 = st.columns(2)
            with jc1:
                jeonse_uk = st.number_input(
                    "전세 보증금 (억원)", min_value=0.0, value=3.0, step=0.5,
                    format="%.1f", key="sim_jeonse_uk",
                )
            with jc2:
                jeonse_opp_rate = st.number_input(
                    "기회비용률 (%/년)", min_value=0.0, value=5.0, step=0.5,
                    format="%.1f", key="sim_jeonse_rate",
                    help="전세금을 다른 곳에 투자했을 때의 연 수익률 (기회비용 기준)",
                )
            jeonse_val_man = jeonse_uk * 10_000  # 만원
            jeonse_opp_cost_monthly = jeonse_val_man * (jeonse_opp_rate / 100) / 12

            if jeonse_type == "전세 임차 (내가 세입자)":
                # 세입자: 전세금이 묶여 기회비용 발생 → 월 비용으로 처리
                st.markdown(
                    f"<div style='padding:0.6rem 0.9rem;border-radius:11px;"
                    f"background:rgba(251,146,60,0.16);border-left:3px solid #fb923c;"
                    f"font-size:0.92rem;color:#fed7aa;'>"
                    f"🔒 전세금 <b>{jeonse_uk:.1f}억</b>이 묶여 있는 동안의 기회비용<br>"
                    f"연 {jeonse_opp_rate:.1f}% 기준 → 월 <b>{jeonse_opp_cost_monthly:,.0f} 만원</b> "
                    f"(연 {jeonse_opp_cost_monthly*12:,.0f} 만원)<br>"
                    f"<span style='font-size:0.85rem;opacity:0.85;'>"
                    f"이것이 월세를 내지 않는 대신 포기하는 실질 비용입니다.</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                jeonse_opp_cost_monthly = jeonse_opp_cost_monthly  # 지출로 반영
            else:
                # 집주인: 받은 전세금을 운용 → 월 수익으로 처리
                st.markdown(
                    f"<div style='padding:0.6rem 0.9rem;border-radius:11px;"
                    f"background:rgba(52,211,153,0.16);border-left:3px solid #34d399;"
                    f"font-size:0.92rem;color:#a7f3d0;'>"
                    f"💰 전세금 <b>{jeonse_uk:.1f}억</b> 수령 후 연 {jeonse_opp_rate:.1f}% 운용 가정<br>"
                    f"월 수익 <b>{jeonse_opp_cost_monthly:,.0f} 만원</b> "
                    f"(연 {jeonse_opp_cost_monthly*12:,.0f} 만원)<br>"
                    f"<span style='font-size:0.85rem;opacity:0.85;'>"
                    f"전세 만기 시 보증금 반환 의무가 있습니다 — 별도 유동성 확보 필요.</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )
                jeonse_opp_cost_monthly = -jeonse_opp_cost_monthly  # 수입으로 반영

        # ── 순현금흐름 요약 ──
        net_monthly_cf = (
            monthly_rent_in + monthly_etc_in
            - monthly_rent_out - monthly_living
            - jeonse_opp_cost_monthly
        )
        cf_color = "#34d399" if net_monthly_cf >= 0 else "#f87171"
        jeonse_label = ""
        if jeonse_type == "전세 임차 (내가 세입자)":
            jeonse_label = f" (전세 기회비용 −{abs(jeonse_opp_cost_monthly):,.0f}만 포함)"
        elif jeonse_type == "전세 임대 (내가 집주인)":
            jeonse_label = f" (전세 운용수익 +{abs(jeonse_opp_cost_monthly):,.0f}만 포함)"
        st.markdown(
            f"<div style='padding:0.65rem 1rem;border-radius:12px;margin-top:0.5rem;"
            f"background:rgba(99,102,241,0.18);border-left:3px solid {cf_color};'>"
            f"월 순현금흐름{jeonse_label}:<br>"
            f"<b style='color:{cf_color};font-size:1.2rem;'>{net_monthly_cf:+,.0f} 만원</b>"
            f"&nbsp;&nbsp;<span style='color:#c7d2fe;font-size:0.9rem;'>"
            f"(연 {net_monthly_cf*12:+,.0f} 만원)</span>"
            f"</div>",
            unsafe_allow_html=True,
        )
        with st.expander("💡 현금흐름 & 전세 금융 상식", expanded=False):
            st.markdown("""
**50/30/20 예산 법칙**

| 비율 | 용도 |
|---|---|
| 50% | 필수 지출 (주거·식비·교통) |
| 30% | 선택 지출 (외식·취미·구독) |
| 20% | 저축·투자·부채 상환 |

**비상금 원칙**  
생활비 **3~6개월치**를 CMA·MMF 등 수시 인출 가능한 상품에 보유  
→ 갑작스러운 실직·의료비·금리 상승에 대비

**전세 vs 월세 분기점 계산**

> 전세 = 월세가 유리한 시점: `월세 ÷ 전세금 × 12 × 100` = 전월세 전환율  
> 전환율이 **시중 예금 금리보다 낮으면 전세가 유리**, 높으면 월세가 유리

**전세 임차인 주의사항**  
- 전입신고 + 확정일자: 보증금 보호의 핵심  
- 전세가율 80% 초과 물건은 경매 시 보증금 회수 위험  
- 전세보증보험(HUG·SGI) 가입 적극 권장
""")

    # ════════════════════════════════════════
    # ② 시뮬레이션 계산
    # ════════════════════════════════════════
    YEARS = 10
    re_r    = re_rate    / 100.0
    land_r  = land_rate  / 100.0
    st_r    = stock_rate / 100.0
    inf_r   = inflation  / 100.0
    lo_r    = loan_rate  / 100.0
    ann_invest   = float(monthly_invest)  * 12.0
    ann_net_cf   = float(net_monthly_cf)  * 12.0
    ann_rent_in  = float(monthly_rent_in) * 12.0
    # 전세 기회비용은 이미 net_monthly_cf에 포함됨
    ann_living   = float(monthly_living + monthly_rent_out) * 12.0
    ann_jeonse_opp = abs(float(jeonse_opp_cost_monthly)) * 12.0  # 전세 기회비용(절대값, 정보 표시용)

    yr_labels: list[int]   = list(range(YEARS + 1))
    re_series:   list[float] = []
    land_series: list[float] = []
    stk_series:  list[float] = []
    cash_series: list[float] = []
    loan_series: list[float] = []
    net_series:  list[float] = []
    real_series: list[float] = []
    ann_tax_s:   list[float] = []
    ann_int_s:       list[float] = []
    ann_out_s:       list[float] = []   # 연간 총지출
    ann_land_tax_s:  list[float] = []   # 연간 토지 세금
    cum_out_s:       list[float] = []
    cash_gone_yr: int | None = None   # 현금 고갈 연도

    re_cur   = float(re_val)
    land_cur = float(land_val)
    stk_cur  = float(stock_val)
    cash_cur = float(cash_val)
    loan_cur = float(loan_val)
    cum_out  = 0.0

    for y in yr_labels:
        ann_tax      = _calc_property_tax(re_cur, n_houses)
        ann_land_tax = _calc_land_tax(land_cur, land_type) if land_cur > 0 else 0.0
        ann_total_tax = ann_tax + ann_land_tax
        ann_int      = loan_cur * lo_r
        ann_out      = ann_total_tax + ann_int + ann_living - ann_rent_in
        cum_out      += ann_out

        effective_cash = cash_cur + ann_net_cf - ann_total_tax
        if effective_cash < 0 and cash_gone_yr is None:
            cash_gone_yr = y

        re_series.append(re_cur)
        land_series.append(land_cur)
        stk_series.append(stk_cur)
        cash_series.append(max(0.0, effective_cash))
        loan_series.append(loan_cur)
        ann_tax_s.append(ann_total_tax)
        ann_land_tax_s.append(ann_land_tax)
        ann_int_s.append(ann_int)
        ann_out_s.append(ann_out)
        cum_out_s.append(cum_out)

        total    = re_cur + land_cur + stk_cur + max(0.0, effective_cash)
        net      = total - loan_cur
        real_net = net / ((1 + inf_r) ** y) if inf_r >= 0 else net
        net_series.append(net)
        real_series.append(real_net)

        re_cur   = re_cur   * (1 + re_r)
        land_cur = land_cur * (1 + land_r)
        stk_cur  = (stk_cur + ann_invest) * (1 + st_r)
        cash_cur = max(0.0, effective_cash * (1 + inf_r))
        loan_cur = max(0.0, loan_cur * (1 + lo_r) - float(loan_repay))

    # ════════════════════════════════════════
    # ③ 파산 위험 판단
    # ════════════════════════════════════════
    st.divider()
    loan_growing = any(
        loan_series[i] > loan_series[i - 1] + 1 for i in range(1, len(loan_series))
    )
    net_negative_yr = next((y for y in yr_labels if real_series[y] < 0), None)
    annual_outflow_now = ann_out_s[0]
    annual_income_now  = ann_rent_in + float(monthly_etc_in) * 12

    # 위험 점수 (0~4)
    risk_score = sum([
        cash_gone_yr is not None and cash_gone_yr <= 5,
        cash_gone_yr is not None,
        loan_growing,
        net_negative_yr is not None,
    ])
    if risk_score == 0:
        risk_label, risk_color, risk_icon = "안전", "#34d399", "✅"
    elif risk_score == 1:
        risk_label, risk_color, risk_icon = "주의", "#fbbf24", "⚠️"
    elif risk_score == 2:
        risk_label, risk_color, risk_icon = "경고", "#fb923c", "🔶"
    else:
        risk_label, risk_color, risk_icon = "위험", "#f87171", "🚨"

    risk_msgs: list[str] = []
    if cash_gone_yr is not None:
        risk_msgs.append(f"현금이 **{cash_gone_yr}년 차**에 고갈될 수 있습니다.")
    if loan_growing:
        risk_msgs.append("상환액이 이자보다 적어 **대출 잔액이 증가**하고 있습니다.")
    if net_negative_yr is not None:
        risk_msgs.append(f"**{net_negative_yr}년 차**에 순자산이 마이너스로 전환될 수 있습니다.")
    if annual_outflow_now > annual_income_now * 3:
        risk_msgs.append("연간 지출이 비근로 수입의 3배를 초과합니다. 현금흐름을 점검하세요.")

    st.markdown(
        f"<div style='padding:1rem 1.1rem;border-radius:16px;"
        f"background:rgba(30,27,75,0.6);border:2px solid {risk_color};"
        f"margin-bottom:0.8rem;'>"
        f"<span style='font-size:1.4rem;font-weight:700;color:{risk_color};'>"
        f"{risk_icon} 파산 위험 등급: {risk_label}</span><br/>"
        + ("<br/>".join(f"<span style='color:#fca5a5;font-size:0.95rem;'>• {m}</span>"
                        for m in risk_msgs) if risk_msgs
           else "<span style='color:#86efac;font-size:0.95rem;'>현재 입력 기준으로 뚜렷한 위험 신호가 없습니다.</span>")
        + "</div>",
        unsafe_allow_html=True,
    )

    # ════════════════════════════════════════
    # ④ 스냅샷 카드 (1·5·10년)
    # ════════════════════════════════════════
    st.subheader("📊 1 · 5 · 10년 후 실질 자산 예측")
    st.caption(f"물가 상승률 {inflation:.1f}%/년 반영 — 오늘의 구매력 기준 금액입니다.")
    snap_cols = st.columns(3)
    for col, sy in zip(snap_cols, [1, 5, 10]):
        real_now  = real_series[0]
        real_snap = real_series[sy]
        cum_s     = cum_out_s[sy]
        re_tax_s  = sum(ann_tax_s[1:sy + 1]) - sum(ann_land_tax_s[1:sy + 1])
        land_tax_s = sum(ann_land_tax_s[1:sy + 1])
        total_tax_s = re_tax_s + land_tax_s
        int_s     = sum(ann_int_s[1:sy + 1])
        # 실질 순자산 변화율
        dpct = ((real_snap - real_now) / abs(real_now) * 100) if real_now != 0 else 0.0
        delta_color = "normal" if dpct >= 0 else "inverse"
        with col:
            with _st_try_border_container():
                st.markdown(f"#### {sy}년 후")
                st.metric(
                    f"실질 순자산",
                    f"{real_snap/10_000:.2f} 억원",
                    delta=f"{dpct:+.1f}%",
                    delta_color=delta_color,
                )
                st.caption(f"물가 {inflation:.1f}%×{sy}년 차감 기준")
                land_tax_line = (
                    f"<span style='font-size:0.82rem;'>"
                    f"└ 부동산세 {re_tax_s/10_000:.2f}억 · 토지세 {land_tax_s/10_000:.2f}억</span><br>"
                    if land_tax_s > 0 else ""
                )
                st.markdown(
                    f"<div style='margin-top:0.4rem;padding:0.45rem 0.65rem;"
                    f"background:rgba(248,113,113,0.16);border-radius:9px;"
                    f"border-left:3px solid #f87171;font-size:0.85rem;color:#fca5a5;'>"
                    f"세금 <b>{total_tax_s/10_000:.2f}억</b> · 이자 <b>{int_s/10_000:.2f}억</b><br>"
                    f"{land_tax_line}"
                    f"총지출 <b>{cum_s/10_000:.2f}억</b>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ════════════════════════════════════════
    # ⑤ 4선 차트 (전체자산·부동산·금융자산·누적지출)
    # ════════════════════════════════════════
    st.divider()
    st.subheader("📈 10년 실질 자산 추이 (물가 반영)")
    st.caption(f"모든 금액은 물가 {inflation:.1f}%/년 차감 후 오늘 기준 구매력으로 환산한 값입니다.")
    UK = 10_000.0

    # 물가 디플레이터: y년 후 금액을 오늘 구매력으로 환산
    def _real(nominal: float, y: int) -> float:
        div = (1 + inf_r) ** y
        return nominal / div if div > 0 else nominal

    # 실질 합산 시리즈 (왼쪽 Y축 — 자산)
    total_asset_uk = [_real(re_series[i] + land_series[i] + stk_series[i] + cash_series[i], i) / UK
                      for i in yr_labels]
    re_total_uk    = [_real(re_series[i] + land_series[i], i) / UK for i in yr_labels]
    fin_asset_uk   = [_real(stk_series[i] + cash_series[i], i) / UK for i in yr_labels]
    # 오른쪽 Y축 — 누적 지출 (양수로 표시)
    out_uk_pos     = [_real(cum_out_s[i], i) / UK for i in yr_labels]

    if go is not None:
        fig2 = go.Figure()

        # ── 오른쪽 Y축: 누적 지출 (bar — 뒤에 그려야 선이 위로 올라옴) ──
        # 로그 스케일 우측 축 → 0 제외 (0.001 대체)
        out_uk_safe = [max(v, 0.001) for v in out_uk_pos]
        fig2.add_trace(go.Bar(
            x=yr_labels, y=out_uk_safe, name="누적 지출",
            yaxis="y2",
            marker=dict(
                color=[f"rgba(248,113,113,{0.10 + 0.18 * i / 10})" for i in yr_labels],
                line=dict(color="rgba(248,113,113,0.55)", width=0),
                cornerradius=4,
            ),
            hovertemplate=(
                "<b>누적 지출</b>  %{x}년 후 누적: "
                "<b>%{y:.2f}억</b><extra></extra>"
            ),
        ))

        # ── 왼쪽 Y축: 전체 자산 (로그 스케일 — fill 없음) ──
        fig2.add_trace(go.Scatter(
            x=yr_labels, y=total_asset_uk, name="전체 자산",
            yaxis="y",
            mode="lines+markers",
            line=dict(color="#fbbf24", width=3.5),
            marker=dict(size=8, color="#fbbf24",
                        symbol="circle",
                        line=dict(color="rgba(15,12,60,0.7)", width=1.5)),
            hovertemplate="<b>전체 자산</b>  %{x}년 후: <b>%{y:.2f}억</b><extra></extra>",
        ))

        # ── 부동산·금융자산 (면 없음) ──
        for name, vals, color, lw, symbol in [
            ("부동산",   re_total_uk,  "#818cf8", 2.5, "diamond"),
            ("금융자산", fin_asset_uk, "#34d399", 2.5, "square"),
        ]:
            fig2.add_trace(go.Scatter(
                x=yr_labels, y=vals, name=name,
                yaxis="y",
                mode="lines+markers",
                line=dict(color=color, width=lw, dash="solid"),
                marker=dict(size=7, color=color, symbol=symbol,
                            line=dict(color="rgba(15,12,60,0.7)", width=1.5)),
                hovertemplate=(
                    f"<b>{name}</b>  %{{x}}년 후: <b>%{{y:.2f}}억</b><extra></extra>"
                ),
            ))

        # 1·5·10년 기준선
        for sy, slabel in [(1, "1년"), (5, "5년"), (10, "10년")]:
            fig2.add_vline(
                x=sy,
                line=dict(color="rgba(199,210,254,0.22)", width=1, dash="dot"),
                annotation_text=f"<b>{slabel}</b>",
                annotation_position="top",
                annotation_font=dict(color="#a5b4fc", size=12),
            )

        fig2.update_layout(
            title=dict(
                text=(
                    f"<b>10년 실질 자산 시뮬레이션</b>"
                    f"<span style='font-size:12px;color:#a5b4fc;'> · 물가 {inflation:.1f}%/년 반영</span>"
                ),
                font=dict(size=16, color="#e0e7ff"),
                x=0.02, xanchor="left",
                pad=dict(t=4),
            ),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,12,60,0.30)",
            font=dict(color="#eef2ff", size=13),
            legend=dict(
                orientation="h", yanchor="top", y=-0.14,
                xanchor="center", x=0.5,
                bgcolor="rgba(15,12,60,0.55)",
                bordercolor="rgba(165,180,252,0.25)", borderwidth=1,
                font=dict(size=13), itemsizing="constant",
                traceorder="normal",
            ),
            xaxis=dict(
                title=dict(text="경과 연도 (년)", font=dict(size=13, color="#a5b4fc")),
                tickmode="linear", tick0=0, dtick=1,
                tickfont=dict(size=12, color="#a5b4fc"),
                gridcolor="rgba(165,180,252,0.08)",
                linecolor="rgba(165,180,252,0.25)",
                mirror=True,
            ),
            yaxis=dict(
                title=dict(
                    text=f"실질 자산 (억원, 로그)",
                    font=dict(size=12, color="#a5b4fc"),
                ),
                type="log",
                tickformat=".2f",
                tickfont=dict(size=11, color="#a5b4fc"),
                gridcolor="rgba(165,180,252,0.10)",
                linecolor="rgba(165,180,252,0.25)",
                side="left",
            ),
            yaxis2=dict(
                title=dict(text="누적 지출 (억원)", font=dict(size=11, color="#fca5a5")),
                type="log",
                tickformat=".2f",
                tickfont=dict(size=11, color="#fca5a5"),
                overlaying="y",
                side="right",
                showgrid=False,
                linecolor="rgba(248,113,113,0.3)",
            ),
            barmode="overlay",
            hovermode="x unified",
            hoverlabel=dict(
                bgcolor="rgba(15,12,60,0.94)",
                bordercolor="rgba(165,180,252,0.4)",
                font=dict(size=13, color="#eef2ff"),
                namelength=-1,
            ),
            margin=dict(l=8, r=60, t=50, b=110),
            height=320,
        )
        st.plotly_chart(fig2, use_container_width=True,
                        config={"displayModeBar": False, "scrollZoom": False})
    elif pd is not None:
        import pandas as _pd  # noqa: PLC0415
        _df = _pd.DataFrame({
            "전체자산(억)": total_asset_uk,
            "부동산(억)":   re_total_uk,
            "금융자산(억)": fin_asset_uk,
        }, index=yr_labels)
        st.line_chart(_df)
        st.caption(f"누적 지출: {out_uk_pos[-1]:.2f}억원 (10년 합계)")

    # ════════════════════════════════════════
    # ⑥ 가정 요약
    # ════════════════════════════════════════
    with st.expander("📋 시뮬레이션 가정 보기", expanded=False):
        preview_land_tax_now = _calc_land_tax(land_val, land_type) if land_val > 0 else 0.0
        st.markdown(f"""
| 항목 | 값 |
|---|---|
| 부동산 시세 | **{re_val_uk:.1f} 억원** · 연 {re_rate:.1f}% ({re_region}) |
| 부동산 연 보유세 | **{preview_tax:,.0f} 만원** (재산세+종부세 · {n_houses}채 기준) |
| 토지 시세 | **{land_val_uk:.1f} 억원** · 연 {land_rate:.1f}% ({land_region}) |
| 토지 유형 | **{land_type}** |
| 토지 연 보유세 | **{preview_land_tax_now:,.0f} 만원** (공시지가 {land_val*0.65/10_000:.2f}억 기준) |
| 주식·펀드 | **{float(stock_val)/10_000:.2f} 억원** · 연 {stock_rate:.1f}% / 월 적립 {monthly_invest:,}만원 |
| 현금·예금 | **{float(cash_val)/10_000:.2f} 억원** |
| 대출 잔액 | **{float(loan_val)/10_000:.2f} 억원** · 금리 {loan_rate:.1f}% · 연상환 {loan_repay:,}만원 |
| 월세 수입 | **{monthly_rent_in:,} 만원/월** |
| 기타 수입 | **{monthly_etc_in:,} 만원/월** |
| 월세 지출 | **{monthly_rent_out:,} 만원/월** |
| 생활비 | **{monthly_living:,} 만원/월** |
| 전세 구분 | **{jeonse_type}** |
| 전세 기회비용(연) | **{ann_jeonse_opp:,.0f} 만원** ({ann_jeonse_opp/10_000:.3f} 억원) |
| 물가 상승률 | **{inflation:.1f}%** |

> ⚠️ 보유세는 단순화 모델 · 양도세·금융소득세·거래비용 미반영  
> 토지분 종부세: 종합합산 5억 공제 후 1~3% 누진 / 별도합산·분리과세는 재산세만 반영
""")

    # ════════════════════════════════════════
    # ⑦ 금융 지표 참고 차트
    # ════════════════════════════════════════
    st.divider()
    st.subheader("📊 금융 지표 참고")
    st.caption("시뮬레이션 가정을 점검하는 데 참고하세요. yfinance 실시간 데이터 (1년)")

    if yf is None or go is None:
        st.info("yfinance 또는 plotly 라이브러리가 없어 차트를 표시할 수 없습니다.")
    else:
        @st.cache_data(ttl=3600, show_spinner=False)
        def _fetch_indicator(ticker: str, period: str = "1y") -> "tuple[list, list]":
            try:
                df = yf.download(ticker, period=period, interval="1d",
                                 progress=False, auto_adjust=True)
                if df is None or df.empty:
                    return [], []
                closes = df["Close"]
                if hasattr(closes, "squeeze"):
                    closes = closes.squeeze()
                dates  = [str(d)[:10] for d in closes.index.tolist()]
                vals   = [float(v) for v in closes.tolist()]
                return dates, vals
            except Exception:
                return [], []

        # ── 차트 공통 레이아웃 팩토리 ──
        # ── 공통 레이아웃 팩토리 (절반 높이 · 선택적 로그 스케일) ──
        def _fin_layout(
            title: str,
            ytitle: str,
            ycolor: str = "#a5b4fc",
            log_y: bool = False,
            yformat: str = "",
            ysuffix: str = "",
        ) -> dict:
            yaxis_cfg: dict = dict(
                title=dict(text=ytitle, font=dict(size=10, color=ycolor)),
                tickfont=dict(size=9, color=ycolor),
                gridcolor="rgba(165,180,252,0.08)",
                linecolor="rgba(165,180,252,0.18)",
                zeroline=False,
            )
            if log_y:
                yaxis_cfg["type"] = "log"
            if yformat:
                yaxis_cfg["tickformat"] = yformat
            if ysuffix:
                yaxis_cfg["ticksuffix"] = ysuffix
            return dict(
                title=dict(
                    text=f"<b>{title}</b>",
                    font=dict(size=12, color="#e0e7ff"),
                    x=0.02, xanchor="left", pad=dict(t=2),
                ),
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(15,12,60,0.28)",
                font=dict(color="#eef2ff", size=11),
                xaxis=dict(
                    showgrid=False,
                    tickfont=dict(size=9, color="#64748b"),
                    linecolor="rgba(165,180,252,0.18)",
                    nticks=5,
                ),
                yaxis=yaxis_cfg,
                hovermode="x unified",
                hoverlabel=dict(
                    bgcolor="rgba(15,12,60,0.92)",
                    bordercolor="rgba(165,180,252,0.35)",
                    font=dict(size=11, color="#eef2ff"),
                    namelength=-1,
                ),
                margin=dict(l=6, r=8, t=36, b=30),
                height=130,
                legend=dict(
                    orientation="h", y=1.18, x=0.5, xanchor="center",
                    bgcolor="rgba(0,0,0,0)", font=dict(size=10),
                ),
                showlegend=True,
            )

        # ── 데이터 일괄 로드 ──
        with st.spinner("금융 지표 데이터 로딩 중…"):
            d_us10, v_us10 = _fetch_indicator("^TNX")
            d_us3m, v_us3m = _fetch_indicator("^IRX")
            d_kr10, v_kr10 = _fetch_indicator("KR10YT=RR")
            d_ks,   v_ks   = _fetch_indicator("^KS11")
            d_sp,   v_sp   = _fetch_indicator("^GSPC")
            d_fx,   v_fx   = _fetch_indicator("USDKRW=X")
            d_gold, v_gold = _fetch_indicator("GC=F")   # 금 선물
            d_oil,  v_oil  = _fetch_indicator("CL=F")   # WTI 원유

        gc1, gc2 = st.columns(2)

        # ── 1. 시중 금리 추이 (선형 — 금리는 음수 가능, 로그 제외) ──
        with gc1:
            fig_rate = go.Figure()
            _rate_series = [
                ("미 10년물", d_us10, v_us10, "#fbbf24", "solid"),
                ("미 단기(3M)", d_us3m, v_us3m, "#60a5fa", "dash"),
                ("한국 10년물", d_kr10, v_kr10, "#34d399", "dot"),
            ]
            any_rate = False
            for rname, rdates, rvals, rcolor, rdash in _rate_series:
                if rdates and rvals:
                    any_rate = True
                    fig_rate.add_trace(go.Scatter(
                        x=rdates, y=rvals, name=rname, mode="lines",
                        line=dict(color=rcolor, width=1.8, dash=rdash),
                        hovertemplate=f"<b>{rname}</b> %{{y:.2f}}%<extra></extra>",
                    ))
            if any_rate:
                fig_rate.update_layout(**_fin_layout(
                    "📈 시중 금리 (1년)", "수익률 (%)", "#fbbf24",
                    log_y=False, ysuffix="%",
                ))
                st.plotly_chart(fig_rate, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption("장단기 금리 역전 시 경기 침체 선행 신호")
            else:
                st.info("금리 데이터 없음")

        # ── 2. KOSPI vs S&P500 (정규화 · 로그 스케일) ──
        with gc2:
            fig_idx = go.Figure()
            any_idx = False
            for iname, idates, ivals, icolor in [
                ("KOSPI", d_ks, v_ks, "#818cf8"),
                ("S&P500", d_sp, v_sp, "#fbbf24"),
            ]:
                if idates and ivals and ivals[0] > 0:
                    any_idx = True
                    base = ivals[0]
                    norm = [v / base * 100 for v in ivals]
                    fig_idx.add_trace(go.Scatter(
                        x=idates, y=norm, name=iname, mode="lines",
                        line=dict(color=icolor, width=1.8),
                        hovertemplate=f"<b>{iname}</b> %{{y:.1f}}<extra></extra>",
                    ))
            if any_idx:
                fig_idx.add_hline(y=100,
                                  line=dict(color="rgba(165,180,252,0.3)",
                                            width=1, dash="dot"))
                fig_idx.update_layout(**_fin_layout(
                    "📊 KOSPI vs S&P500 (시작=100)", "상대 수익", "#a5b4fc",
                    log_y=True,
                ))
                st.plotly_chart(fig_idx, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption("로그 스케일 — 수익률 비율 변화 확인")
            else:
                st.info("지수 데이터 없음")

        gc3, gc4 = st.columns(2)

        # ── 3. 원/달러 환율 (로그 스케일) ──
        with gc3:
            fig_fx = go.Figure()
            if d_fx and v_fx:
                avg_fx = sum(v_fx) / len(v_fx)
                fig_fx.add_trace(go.Scatter(
                    x=d_fx, y=v_fx, name="USD/KRW",
                    mode="lines",
                    line=dict(color="#34d399", width=1.8),
                    hovertemplate="<b>USD/KRW</b> %{y:,.0f}원<extra></extra>",
                ))
                fig_fx.add_hline(
                    y=avg_fx,
                    line=dict(color="rgba(165,180,252,0.4)", width=1, dash="dash"),
                    annotation_text=f"평균 {avg_fx:,.0f}",
                    annotation_font=dict(size=9, color="#a5b4fc"),
                    annotation_position="bottom right",
                )
                fx_layout = _fin_layout(
                    "💱 원/달러 환율 (1년)", "원 (KRW)", "#34d399",
                    log_y=True, yformat=",.0f",
                )
                fig_fx.update_layout(**fx_layout)
                st.plotly_chart(fig_fx, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption("환율 상승 = 원화 약세 · 수입물가 상승")
            else:
                st.info("환율 데이터 없음")

        # ── 4. 금(Gold) vs WTI 원유 — 인플레이션 헤지 참고 (로그 스케일) ──
        with gc4:
            fig_com = go.Figure()
            any_com = False
            for cname, cdates, cvals, ccolor, cfmt in [
                ("금 ($/oz)", d_gold, v_gold, "#fcd34d",
                 "<b>금</b> $%{y:,.0f}<extra></extra>"),
                ("WTI ($/배럴)", d_oil, v_oil, "#fb923c",
                 "<b>WTI</b> $%{y:.1f}<extra></extra>"),
            ]:
                if cdates and cvals and all(v > 0 for v in cvals):
                    any_com = True
                    fig_com.add_trace(go.Scatter(
                        x=cdates, y=cvals, name=cname, mode="lines",
                        line=dict(color=ccolor, width=1.8),
                        hovertemplate=cfmt,
                    ))
            if any_com:
                fig_com.update_layout(**_fin_layout(
                    "🥇 금 · WTI 원유 (1년, USD)", "가격 (USD)", "#fcd34d",
                    log_y=True,
                ))
                st.plotly_chart(fig_com, use_container_width=True,
                                config={"displayModeBar": False})
                st.caption("금↑ = 안전자산 선호 · WTI↑ = 인플레이션·물가 상승 압력")
            else:
                st.info("원자재 데이터 없음")


def _render_tab_news() -> None:
    st.header("헤드라인 브리핑")
    st.caption(
        "경제·IT·개발 트렌드를 한 번에 훑기 위한 용도입니다. "
        "기사 본문은 각 링크에서 확인하세요."
    )
    news_choices = [*NEWS_RSS_FEEDS.keys(), "Hacker News"]
    src = st.selectbox("출처", news_choices, index=0, key="news_src")
    if st.button("뉴스 새로고침", key="ref_news"):
        fetch_rss_headlines.clear()
        fetch_hackernews_top.clear()

    if src == "Hacker News":
        items = fetch_hackernews_top()
        st.caption("출처: [Hacker News](https://news.ycombinator.com) (Y Combinator 커뮤니티, 영어)")
    else:
        feed_url = NEWS_RSS_FEEDS[src]
        items = fetch_rss_headlines(feed_url)
        st.caption(f"RSS: [{src}]({feed_url})")

    using_sample_news = False
    if not items:
        if src == "Hacker News":
            items = list(SAMPLE_HACKERNEWS_ITEMS)
        else:
            items = list(SAMPLE_NEWS_HEADLINES_BY_FEED.get(src, []))
        if items:
            using_sample_news = True
            st.warning(
                "RSS/Hacker News에 연결하지 못했습니다. **내장 샘플 헤드라인**으로 레이아웃을 채웁니다."
            )

    if not items:
        st.error(
            "뉴스 샘플까지 불러오지 못했습니다. RSS 설정·네트워크를 확인하세요."
        )
    else:
        if using_sample_news:
            st.caption("현재 표시: 내장 샘플 · 링크는 예시용(example.invalid)입니다.")
        for i, it in enumerate(items, start=1):
            safe_title = html.escape(it["title"])
            safe_url = html.escape(it["url"], quote=True)
            st.markdown(
                f'<p>{i}. <a href="{safe_url}" target="_blank" rel="noopener noreferrer">{safe_title}</a></p>',
                unsafe_allow_html=True,
            )
            if src == "Hacker News" and "score" in it:
                st.caption(f"↑ {it['score']}")



def _render_tab_edu() -> None:
    st.header("🎓 명문대 진학 · 교육·입시 사이트 모음")
    st.caption(
        "대학 입시 일정·학생부·전형은 매년 달라집니다. 아래는 참고용 링크이며, "
        "**지원 전 반드시 해당 기관 공식 요강·공지**를 확인하세요."
    )
    st.info(
        "민간 학원·인강은 지역·브랜드별로 특성이 다릅니다. 상담·환불 조건은 각 사이트 약관을 따르세요."
    )

    _render_curated_link_blocks(EDU_ADMISSION_SITES, key_prefix="edu")



def _render_tab_elem() -> None:
    st.header("📘 초등 학부모 · 학사 정보 한눈에")
    st.caption(
        "**입학·전학·돌봄·방과후·급식** 등 세부 일정과 규정은 매년·지역별로 다릅니다. "
        "반드시 **거주지 관할 교육청·재학(예정) 학교 공지**를 확인하세요."
    )
    st.warning(
        "이 탭은 공개된 **공식·준공식 포털 링크 모음**입니다. "
        "민원·증명은 각 기관 창구 또는 정부24·교육청 누리집 절차를 따르세요."
    )
    _render_curated_link_blocks(ELEMENTARY_PARENT_SITES, key_prefix="elem")


def _render_middle_school_parent_tips() -> None:
    """하단 도우미: 앱·계정 팁 (예비 중등 탭 전용)."""
    st.divider()
    st.subheader("💡 학부모 도우미 팁")
    with st.expander("📱 학부모를 위한 앱 설치·업데이트 팁", expanded=False):
        st.markdown(
            """
- **공식 스토어만 이용하기**: 학교·교육청이 안내한 링크 또는 **Google Play / App Store**에서 개발사 이름을 확인하고 설치하세요.
- **권한 최소화**: 알림은 필요할 때만 켜고, 연락처·사진 접근은 정말 필요할 때만 허용하면 좋습니다.
- **업데이트**: 보안 패치가 포함되는 경우가 많아, 가족 휴대폰은 가끔 **업데이트 일괄 확인**을 추천합니다.
- **가족 공유**: 부모 폰에만 두기보다, 자녀 기기가 있다면 **같은 공지를 각자 받도록** 알림만 맞춰 두면 놓침이 줄어듭니다.
            """.strip()
        )
    with st.expander("🔐 비밀번호·계정 관리법", expanded=False):
        st.markdown(
            """
- **사이트마다 다른 비밀번호**: 나이스·이메일·쇼핑몰을 동일 비밀번호로 두면, 한 곳 유출 시 피해가 커집니다. **비밀번호 관리자**(OS·브라우저 내장 또는 신뢰할 수 있는 전용 앱) 사용을 권합니다.
- **2단계 인증**: 지원하는 서비스는 **OTP·문자 인증**을 켜 두면 안전합니다.
- **자녀 계정**: 가능하면 **학부모 연락처 복구 수단**을 함께 등록해 두면 분실·잠금 시 수월합니다.
- **피싱 주의**: ‘교육청·학교’를 사칭한 문자·링크는 공식 도메인인지 확인하고, 의심되면 **학교 유선**으로 확인하세요.
            """.strip()
        )


def _render_tab_mid() -> None:
    st.header("📙 예비 중등 가이드 대시보드")
    st.caption(
        "**중학 입학·학구·배정·서류**는 지역·연도마다 다릅니다. 아래 링크는 출발점이며, "
        "**거주지 관할 교육청·재학(예정) 학교 공지**가 최종 기준입니다."
    )
    st.success(
        "🌷 새 학년 준비, 학부모도 함께 배워 가면 됩니다. 링크 아래 **학부모 안내**를 펼쳐 보시면 "
        "각 사이트를 언제 쓰면 좋은지 정리되어 있습니다."
    )
    _render_curated_link_blocks(MIDDLE_SCHOOL_PREP_SITES, key_prefix="mid")
    _render_middle_school_parent_tips()


def _render_tab_cosmetics_compare() -> None:
    """채널별 샘플 가격 표 — 외부 쇼핑몰 API 미연동."""

    st.header("💄 화장품 가격비교")
    st.caption(
        "**카테고리**를 고른 뒤 표에서 채널별 예시 가격을 비교해 보세요. 아래 링크는 참고용입니다."
    )
    st.warning(
        "표시 금액은 **데모용 가상 데이터**입니다. 실제 **행사가·재고·판매자**는 각 공식몰·앱에서 확인하세요."
    )

    cats = list(COSMETICS_PRICE_COMPARE_MOCK.keys())
    cat = st.selectbox(
        "카테고리",
        options=cats,
        index=0,
        key="cosmetics_compare_cat",
    )
    rows = COSMETICS_PRICE_COMPARE_MOCK.get(cat, [])
    if pd is not None and rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    elif rows:
        st.table(rows)
    else:
        st.info("이 카테고리에는 샘플 행이 없습니다.")

    st.divider()
    st.subheader("🔗 주요 비교·구매 채널 (링크)")
    with _st_try_border_container():
        for it in COSMETICS_PRICE_PORTALS:
            st.markdown(f"**[{it['t']}]({it['u']})** — {it['d']}")


def _render_tab_pc_compare() -> None:
    """제품군별 샘플 가격 표 — 다나와 등 외부 실시간 데이터 미연동."""

    st.header("💻 컴퓨터 가격비교")
    st.caption(
        "**제품군**을 고른 뒤 채널별 **참고 가격(가상)** 을 비교해 보세요. 아래 링크로 실제 최저가를 확인할 수 있습니다."
    )
    st.warning(
        "표시 금액은 **데모용 가상 데이터**입니다. **환율·행사·재고·판매자**에 따라 실구매가는 달라집니다."
    )

    cats = list(PC_PRICE_COMPARE_MOCK.keys())
    cat = st.selectbox(
        "제품군",
        options=cats,
        index=0,
        key="pc_compare_cat",
    )
    rows = PC_PRICE_COMPARE_MOCK.get(cat, [])
    if pd is not None and rows:
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
    elif rows:
        st.table(rows)
    else:
        st.info("이 카테고리에는 샘플 행이 없습니다.")

    st.divider()
    st.subheader("🔗 가격 비교·구매 채널 (링크)")
    with _st_try_border_container():
        for it in PC_PRICE_PORTALS:
            st.markdown(f"**[{it['t']}]({it['u']})** — {it['d']}")


def _render_tab_life_pc() -> None:
    """생활 그룹 — 컴퓨터: 가격대·인기 세그먼트·추천 사양·ML GPU (참고용)."""

    st.header("💻 컴퓨터 · 시장 참고")
    st.caption(
        "국내 커뮤니티·유통 경향을 **요약한 참고용**입니다. 실구매 전 **다나와·쇼핑몰**에서 최신가를 확인하세요."
    )
    st.info(
        "숫자가 들어 있는 **가격 비교 데모 표**는 **쇼핑 → 💻 컴퓨터** 탭에 있습니다.",
        icon="🛒",
    )

    st.subheader("평균적으로 보는 가격대(대략)")
    if pd is not None:
        st.dataframe(
            pd.DataFrame(LIFE_PC_AVG_PRICE_BANDS),
            use_container_width=True,
            hide_index=True,
        )
    else:
        for row in LIFE_PC_AVG_PRICE_BANDS:
            st.markdown(f"**{row.get('구분', '')}** — {row.get('가격대(참고)', '')}")
            st.caption(row.get("비고", ""))

    st.divider()
    st.subheader("요즘 잘 나가는 제품·세그먼트 경향")
    if pd is not None:
        st.dataframe(
            pd.DataFrame(LIFE_PC_POPULAR_SEGMENTS),
            use_container_width=True,
            hide_index=True,
        )
    else:
        for row in LIFE_PC_POPULAR_SEGMENTS:
            st.markdown(f"**{row.get('카테고리', '')}**: {row.get('요즘 잘 나가는 유형', '')}")
            st.caption(row.get("한 줄", ""))

    st.divider()
    st.subheader("요즘 맞춰 쓰기 좋은 사양(추천 기준)")
    st.markdown(LIFE_PC_SPEC_RECOMMEND_MARKDOWN)

    st.divider()
    st.subheader("머신러닝·딥러닝용 그래픽카드 — 어떻게 고르면 좋은지")
    st.caption(
        "**VRAM 용량·CUDA(또는 ROCm) 지원·전력(PSU)** 이 세 가지를 먼저 맞추고, 그 다음 세대·가격을 보는 순서를 추천합니다."
    )
    if pd is not None:
        st.dataframe(
            pd.DataFrame(LIFE_PC_ML_GPU_GUIDE),
            use_container_width=True,
            hide_index=True,
        )
    else:
        for row in LIFE_PC_ML_GPU_GUIDE:
            st.markdown(f"**{row.get('용도·예산 느낌', '')}**")
            st.markdown(row.get("추천 GPU 성향", ""))
            st.caption(row.get("메모", ""))

    st.divider()
    st.subheader("실시간 가격·스펙 비교 링크")
    with _st_try_border_container():
        for it in PC_PRICE_PORTALS:
            st.markdown(f"**[{it['t']}]({it['u']})** — {it['d']}")


def _render_tab_golf() -> None:
    """생활 그룹 — 골프: 기본 상식·경남·부킹·비용(참고)."""

    st.header("⛳ 골프 · 기본 & 경남·부산권 부킹")
    st.caption(
        "직장인이 **저렴한 라운딩·티타임**을 잡는 방법, **부킹**의 뜻, **회원권·레슨·인원**별 비용 감을 "
        "한곳에 정리했습니다. 금액은 **시기·요일·날씨에 따라 크게 달라지므로** 반드시 **당일 앱·전화**로 확인하세요."
    )
    st.warning(
        "아래 숫자는 **국내에서 흔히 나오는 참고 범위**이며, 특정 골프장 가격표가 **아닙니다**. "
        "투자·매매 조언이 아닙니다.",
        icon="⚠️",
    )

    gt1, gt2, gt3, gt4 = st.tabs(["📘 기본 상식", "🗺️ 경남·부산권 부킹", "💰 비용·인원", "🔗 예약·정보 채널"])

    with gt1:
        st.markdown(
            """
##### 골프를 처음 접할 때 알아두면 좋은 것
- **라운딩**: 실제 필드(코스)에서 18홀(또는 9홀)을 도는 것. 이동·시간(보통 반나절~)·체력이 필요합니다.
- **스크린·연습장**: 실내 스크린골프는 **시간제(베이당)** 로 치며, 필드와 느낌·룰이 다를 수 있습니다. 비용·접근은 보통 스크린이 더 부담이 적습니다.
- **티타임(Tee time)**: 출발 시간대. 예약은 **이 티타임을 확보**한다는 뜻으로, 골프장마다 슬롯이 다릅니다.
- **그린피(Green fee)**: 당일 코스 이용료(비회원·일일 기준으로 자주 표기). **카트·캐디**는 별도인 곳이 많습니다.
- **회원권**: 특정 클럽 **장기 이용·우선 예약**을 위한 권리(양도·가격은 시장·규정 따름). **연회비·입장료**는 별도인 경우가 흔합니다.
- **에티켓**: 다른 조의 티타임을 밀지 않기, 느린 플레이는 양해·통과 요청, 디봇(잔디) 복구, 모래 살짝 등 **코스 보호**가 기본입니다.
            """
        )
        st.info(
            "**부킹(booking)** 은 골프 용어로 **「라운딩할 날짜·시간대(티타임)를 미리 예약하는 것」** 입니다. "
            "숙소 예약과 같이 **‘자리를 선점’** 한다는 의미에 가깝고, **“가장 싼 가격이 자동 보장”** 은 아닙니다.",
            icon="📌",
        )

    with gt2:
        st.markdown("##### 왜 경남·창원·김해·부산·진주를 같이 보나")
        st.caption(
            "이동 거리·주말 교통·가격대가 비슷한 **동일 생활권**으로 묶어 보면, 평일 조조·야간 이동 전략을 세우기 좋습니다."
        )
        st.markdown(
            """
- **창원**: 직장 기준으로 **당일 왕복** 가능한 코스를 고를 때, **출발·복귀 시간**을 티타임에 맞추는 게 핵심입니다. **평일 오전·한가한 요일**이 상대적으로 여유 있습니다.
- **김해**: 공항·광역 접근이 좋아 **출장 다음 날 라운딩**을 짜기도 합니다. **지역 카페·동호회**에서 ‘조인(합류)’ 정보가 올라오기도 합니다.
- **부산**: **광역시 안·인근(기장·양산 방향 등)** 으로 선택지가 넓습니다. **주말·공휴일**은 티타임 경쟁이 세니 **2~3주 전**부터 앱·전화로 확인하는 편이 안전합니다.
- **진주·내륙(거창·산청 등)**: 창원에서 **차로 1~2시간대**가 되는 경우가 많아, **하루 일정**으로 묶거나 숙박·연휴에 맞추는 경우가 있습니다. **가격·여유**는 필드마다 차이가 큽니다.

**직장인·저렴하게 노리는 팁(일반론)**  
- **평일 조조**(이른 티타임): 주말 대비 그린피·혼잡이 유리한 경우가 많습니다. 출근 전·반차와 맞춰야 합니다.  
- **비수기·날씨 리스크**: 겨울·장마·한파 직후 등은 수요가 줄어 **프로모션**이 붙기도 하지만, 코스 상태는 직접 확인이 필요합니다.  
- **2~3명만 갈 때**: 4명 **조인**이 기본인 클럽이 많아, **부족 인원 요금·랜덤 조인** 규정을 예약 시 물어보세요.  
- **스크린으로 먼저**: 주 1회 스크린으로 **스윙·거리감**만 유지하고, 월 1회 필드로 가는 식이 비용·시간 균형이 잘 맞는 경우가 많습니다.
            """
        )

    with gt3:
        st.markdown("##### 비용을 볼 때 체크리스트")
        st.markdown(
            "- **그린피만**인지, **카트(2인1조/1인1카트)·캐디·락카**가 포함·별도인지 표를 꼭 봅니다.\n"
            "- **주말·공휴일·오전대**는 같은 코스라도 **큰 폭**으로 비쌀 수 있습니다.\n"
            "- **레슨**: 실내 스튜디오·연습장·필드 레슨·프로 지명 여부에 따라 **단가가 완전히 다릅니다**."
        )
        _golf_cost_rows = [
            {
                "항목": "비회원 일일 라운딩(그린피 위주)",
                "대략 범위(참고)": "평일·시즌·등급에 따라 **약 8만~35만원+** / 1인",
                "비고": "카트·캐디 별도. 주말·명절은 상한이 훨씬 올라갈 수 있음",
            },
            {
                "항목": "스크린골프(베이·시간)",
                "대략 범위(참고)": "**약 2만~5만원**/시간대·매장 (2인 분담 시 인당 절반)",
                "비고": "심야·평일 할인, 회원권·충전형이 있으면 더 저렴",
            },
            {
                "항목": "프로 레슨(1회·1:1)",
                "대략 범위(참고)": "**약 6만~20만원+**/회 (30~60분)",
                "비고": "필드 동반·그룹 레슨은 1인당 단가가 낮아지는 경우 많음",
            },
            {
                "항목": "회원권(취득)",
                "대략 범위(참고)": "클럽·권종에 따라 **수천만~수억 원** + 연회비",
                "비고": "양도·담보·세금은 전문 자료 확인. ‘저렴 라운딩’과 별개로 **대출·유동성 리스크** 큼",
            },
            {
                "항목": "인원(4명 스타트)",
                "대략 범위(참고)": "보통 **4명이 1조**; 2~3명이면 **조인·추가요금** 문의",
                "비고": "‘1인당 ○만원’이 아니라 **조·시간대·옵션 합산**으로 보는 게 안전",
            },
        ]
        if pd is not None:
            st.dataframe(pd.DataFrame(_golf_cost_rows), use_container_width=True, hide_index=True)
        else:
            for row in _golf_cost_rows:
                st.markdown(f"**{row['항목']}** — {row['대략 범위(참고)']}")
                st.caption(row["비고"])
        st.caption(
            "**장소·회원권·레슨·인원별 비용** 은 위 표처럼 **항목을 나눠 보면** 정리하기 좋습니다. "
            "실제 견적은 **해당 장의 당일 공지**가 정답입니다."
        )

    with gt4:
        st.markdown("##### 예약·정보를 찾을 때(자주 쓰는 흐름)")
        st.markdown(
            "1. **네이버 지도 / 네이버 검색**에 골프장명 → **전화번호·공식 예약 페이지** 확인  \n"
            "2. **해당 골프장 공식 홈페이지·대표번호**로 티타임(부킹) — 가장 정확한 **잔여·요금**  \n"
            "3. **스마트스코어·골프다이어리** 등 앱 — 스코어·코스 정보·일부 예약 연동(앱마다 상이)  \n"
            "4. **지역 골프 카페·동호회·오픈채팅** — 조인·교통편·주차 팁(검증은 본인 책임)  \n"
            "5. **대형 마켓·여행사형 골프 패키지** — 숙박+라운딩 묶음은 **취소 규정**을 꼭 확인"
        )
        st.markdown("##### 웹·앱 링크(일반)")
        st.markdown(
            "- [네이버 지도](https://map.naver.com/) — 장소·전화·리뷰 확인  \n"
            "- [스마트스코어](https://www.smartscore.kr/) — 대회·코스·앱 안내  \n"
            "- [한국골프협회 KGA](https://www.kga.or.kr/) — 대회·규정·교육(참고)  \n"
            "- [골프존](https://www.golfzon.com/) — 스크린·브랜드별 매장 검색에 활용"
        )
        st.info(
            "**창원 중심·김해·부산·진주** 까지 저렴한 예약을 넓게 찾을수록 선택지는 늘지만, "
            "**이동비·피로**도 같이 늘어납니다. 우선 **창원 출발 기준 왕복 1시간 이내** 후보를 지도에 찍고, "
            "**평일 조조** 위주로 전화·앱을 비교해 보는 방식을 추천합니다.",
            icon="💡",
        )


def _render_tab_camping() -> None:
    st.header("🏕️ 캠핑 · 입문~주말 나들이")
    st.caption("장비·예약·에티켓 참고입니다. **화기·쓰레기·소음** 규정은 캠핑장마다 다릅니다.")
    c1, c2, c3 = st.tabs(["입문 체크", "예약·정보", "시즌·매너"])
    with c1:
        st.markdown(
            """
##### 처음 갈 때
- **숙박 형태**: 오토캠(차 옆)·글램핑·카라반 대여 등 **부담이 적은 것**부터 경험해 보기.
- **필수 느낌**: 방수포·랜턴·의자·버너(또는 전기)·쓰레기봉투·물. **밤 기온**은 낮보다 많이 떨어집니다.
- **안전**: 일산화탄소·화상·연료 보관. **텐트 안 화기 금지**가 기본입니다.
- **전기**: 사이트에 **콘센트 유무·와트 제한** 확인(포터블 전원·멀티탭 남용 주의).
            """
        )
    with c2:
        st.markdown(
            """
##### 예약·검색
- 지도 앱에서 **‘캠핑장’** 검색 후 **전화·네이버 예약**으로 잔여 확인.
- 성수기·연휴는 **수 주~한 달 전**부터 매진이 흔합니다.
- **반려동물·총성(입영)** 가능 여부는 사이트마다 다릅니다.
            """
        )
        st.markdown(
            "- [네이버 지도](https://map.naver.com/) — **캠핑장** 검색·전화·리뷰\n"
            "- [한국관광공사](https://www.visitkorea.or.kr/) — 지역 여행·축제 안내"
        )
    with c3:
        st.markdown(
            """
##### 시즌·에티켓
- **겨울**: 난방·결빙·동파. **여름**: 벌레·더위·장마 텐트 관리.
- **소음**: 심야 스피커·과한 음주는 민원이 됩니다. **조용한 시간**이 있으면 지키기.
- **쓰레기**: **분리수거**·음식물 처리. 자연 보호 구역은 **취사 금지**인 경우가 많습니다.
            """
        )


def _render_tab_car_wash() -> None:
    st.header("🚿 세차·실내외 관리")
    st.caption("셀프 세차장·가정에서의 기본 순서입니다. **코팅·폴리싱**은 제품 매뉴얼을 따르세요.")
    w1, w2, w3 = st.tabs(["셀프 세차 순서", "실내·냄새", "코팅·왁스 감각"])
    with w1:
        st.markdown(
            """
##### 권장 순서(일반)
1. **휠·타이어** 먼지 제거 → **프리워시**(큰 입자 흙 씻기)  
2. **양동이 두 개**: 깨끗한 물 / 샴푸 물 — **같은 장갑으로 휠·차체 섞지 않기**  
3. 위에서 아래로, **직선 스트로크**로 닦기(원을 그리면 스월 자국이 남기 쉬움)  
4. **건조**: 극세사 건조 타월, **물기 마른 뒤** 이동하면 얼룩이 줄어듦  
5. **엔진룸**은 물 세척 금지인 차종이 많습니다. 매뉴얼 확인.
            """
        )
    with w2:
        st.markdown(
            """
- **매트·시트**: 진공 + **브러시**, 음식 찌든 때는 전용 클리너.
- **에어컨 냄새**: 필터·증발기 관리(정비용). **방향제만**으로 가리면 한계가 있습니다.
- **트렁크**: 습기·액체 누수 확인.
            """
        )
    with w3:
        st.markdown(
            """
- **왁스**: 주기가 너무 짧으면 **잔여층**이 쌓일 수 있습니다. 제품별 권장 간격 확인.
- **코팅제**: DIY는 **작은 면적부터** 시험, **직사광선·고온 차체**에 바르지 않기.
- **고압수**: **가까이 대면** 도장 손상·고무 노화에 주의.
            """
        )


def _render_tab_hobby_men40() -> None:
    st.header("🧔 40대 남성에게 자주 꼽히는 취미(참고)")
    st.caption(
        "**개인차가 큽니다.** 국내 온·오프라인 커뮤니티에서 **빈도가 높게 언급되는 축**을 정리했습니다."
    )
    st.markdown(
        """
##### 운동·아웃도어
- **등산·트레킹**: 주말 루틴으로 체력·멘탈 관리. **무릎·등산화·지팡이**부터 맞추면 장기적으로 유리합니다.
- **자전거·그래블**: 유지비·보관이 자동차보다 단순한 편. **헬멧·야간 라이트** 필수.
- **낚시**: 장비 단계를 나눠 **지역 규제·금어기** 확인.

##### 감각·수집
- **오디오**: 이어폰·스피커·LP 등 **듣는 환경**을 점진적으로 업그레이드. 청력 보호(볼륨·시간).
- **위스키·커피**: 취향을 **기록**(메모)해 두면 다음 구매가 쉬워집니다. **과음·과카페인** 주의.
- **사진**: 스마트폰만으로도 **구도·빛** 연습 가능. 무거운 렌즈는 **목·손목** 부담을 고려.

##### 디지털·메이킹
- **PC·기계 키보드·미니 PC**: 조립·튜닝은 **시간 대비 만족**이 큰 편. 전기·환기·먼지 관리.
- **프라모델·건프라**: 집중 시간 확보(아이·반려와 **안전 거리**).

##### 관계
- **동호회·지역 모임**: 과음 문화가 있으면 **본인 룰**(물 마시기·택시비)을 미리 정해 두면 좋습니다.
        """
    )


def _render_tab_figures() -> None:
    st.header("🎨 피규어·프라모델·수집")
    st.caption("**정품·예약·보관** 위주로 정리했습니다. 특정 작품·등급 논쟁은 커뮤니티 규칙을 따르세요.")
    f1, f2, f3 = st.tabs(["입문·용어", "보관·전시", "구매·예약 문화"])
    with f1:
        st.markdown(
            """
- **스케일**: 1/7, 1/8 등 **키 높이** 감각이 다릅니다. 선반 깊이를 미리 재 보세요.
- **재질**: PVC·ABS·레진 등 **온도·직사광선**에 민감한 재질이 있습니다.
- **프라모델**: **니퍼·게이트 자국** 연습이 퀄리티를 좌우합니다.
            """
        )
    with f2:
        st.markdown(
            """
- **먼지**: 정전기 먼지 제거·**소프트 브러시**. 습식 청소는 **도장 손상** 위험.
- **자외선**: 창가 전시는 **변색**이 빠를 수 있습니다. UV 차단 필름·박스 보관 고려.
- **습기**: 해안·지하 공간은 **곰팡이**에 유의. 제습제·밀폐 케이스.
            """
        )
    with f3:
        st.markdown(
            """
- **예약·선주문**: 인기 작품은 **출시 전 결제**가 흔합니다. 취소·배송 정책을 읽기.
- **중고**: **박스·부품 누락** 사진을 꼭 확인. 사기 피해는 **직거래·에스크로** 습관으로 줄이기.
- **세금·관세**: 해외 직구는 **통관·부가세**가 붙을 수 있습니다.
            """
        )


def _render_tab_agent() -> None:
    with st.expander("에이전트 · 환경변수 안내", expanded=False):
        st.markdown(
            "- **`OPENAI_API_KEY`**: 있으면 GPT 대화, 없으면 규칙 기반 응답.\n"
            "- **`OPENAI_MODEL`**: 기본 `gpt-4o-mini`.\n"
            "- GitHub 검색 한도: **`GITHUB_TOKEN`** (선택)."
        )
    st.header("생활 도우미")
    if os.environ.get("OPENAI_API_KEY", "").strip():
        st.success("모드: OpenAI 연결 (`OPENAI_MODEL` 기본: gpt-4o-mini)")
    else:
        st.warning("모드: 로컬 규칙 응답 (API 키 없음)")

    if "agent_messages" not in st.session_state:
        st.session_state.agent_messages = []

    for m in st.session_state.agent_messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])

    if prompt := st.chat_input("메시지를 입력하세요…"):
        st.session_state.agent_messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        hist = [
            {"role": x["role"], "content": x["content"]}
            for x in st.session_state.agent_messages[:-1]
            if x["role"] in ("user", "assistant")
        ][-10:]
        with st.chat_message("assistant"):
            with st.spinner("생각 중…"):
                reply = openai_reply(hist, prompt)
            st.markdown(reply)
        st.session_state.agent_messages.append({"role": "assistant", "content": reply})


def _render_tab_travel_mock() -> None:
    """선택 국가별 여행 샘플 — 날씨·시즌·축제·명소 TOP3 카드. 탭 상단에서 국가 선택."""
    st.header("🗺️ 여행 스케치")
    st.caption("아래에서 **국가를 고르면** 해당 샘플 카드가 바로 바뀝니다.")

    st.warning(
        "표시 정보는 **데모용 샘플 데이터**입니다. 실제 여행·항공·비자·안전 정보는 "
        "외교부 해외안전여행, 현지 관광청 등 **공식 채널**을 확인하세요."
    )

    countries = list(TRAVEL_MOCK_BY_COUNTRY.keys())
    if "travel_mock_country_name" not in st.session_state:
        st.session_state.travel_mock_country_name = countries[0]
    elif st.session_state.travel_mock_country_name not in TRAVEL_MOCK_BY_COUNTRY:
        st.session_state.travel_mock_country_name = countries[0]

    st.selectbox(
        "보고 싶은 나라",
        options=countries,
        key="travel_mock_country_name",
        help="샘플 데이터입니다. 실제 일정·비자·안전은 공식 안내를 확인하세요.",
    )
    country = str(st.session_state.travel_mock_country_name)
    row = TRAVEL_MOCK_BY_COUNTRY[country]

    _travel_render_tip_banner(row)
    _travel_render_weather_season_cards(row)
    _travel_render_festival_section(row)
    _travel_render_spots_top3(row)

    st.divider()
    st.subheader("✈️ 여행 준비 체크리스트")
    st.caption("출발 전 확인용입니다. 체크 상태는 **이 브라우저 세션**에만 저장됩니다.")
    _travel_render_prep_checklist_grid()


# ── 시도 코드 ─────────────────────────────────────────────────
_SIDO_MAP: dict[str, str] = {
    "서울": "11", "부산": "26", "대구": "27", "인천": "28",
    "광주": "29", "대전": "30", "울산": "31", "세종": "36",
    "경기": "41", "강원": "42", "충북": "43", "충남": "44",
    "전북": "45", "전남": "46", "경북": "47", "경남": "48", "제주": "50",
}

# ── 시군구 코드 (시도코드 → {시군구명: 5자리코드}) ──────────────
_SIGUNGU_MAP: dict[str, dict[str, str]] = {
    "11": {  # 서울
        "종로구": "11110", "중구":    "11140", "용산구": "11170",
        "성동구": "11200", "광진구":  "11215", "동대문구": "11230",
        "중랑구": "11260", "성북구":  "11290", "강북구": "11305",
        "도봉구": "11320", "노원구":  "11350", "은평구": "11380",
        "서대문구": "11410", "마포구": "11440", "양천구": "11470",
        "강서구": "11500", "구로구":  "11530", "금천구": "11545",
        "영등포구": "11560", "동작구": "11590", "관악구": "11620",
        "서초구": "11650", "강남구":  "11680", "송파구": "11710",
        "강동구": "11740",
    },
    "26": {  # 부산
        "중구": "26110", "서구": "26140", "동구": "26170",
        "영도구": "26200", "부산진구": "26230", "동래구": "26260",
        "남구": "26290", "북구": "26320", "해운대구": "26350",
        "사하구": "26380", "금정구": "26410", "강서구": "26440",
        "연제구": "26470", "수영구": "26500", "사상구": "26530",
        "기장군": "26710",
    },
    "27": {  # 대구
        "중구": "27110", "동구": "27140", "서구": "27170",
        "남구": "27200", "북구": "27230", "수성구": "27260",
        "달서구": "27290", "달성군": "27710", "군위군": "27720",
    },
    "28": {  # 인천
        "중구": "28110", "동구": "28140", "미추홀구": "28177",
        "연수구": "28185", "남동구": "28200", "부평구": "28237",
        "계양구": "28245", "서구": "28260",
        "강화군": "28710", "옹진군": "28720",
    },
    "29": {  # 광주
        "동구": "29110", "서구": "29140", "남구": "29155",
        "북구": "29170", "광산구": "29200",
    },
    "30": {  # 대전
        "동구": "30110", "중구": "30140", "서구": "30170",
        "유성구": "30200", "대덕구": "30230",
    },
    "31": {  # 울산
        "중구": "31110", "남구": "31140", "동구": "31170",
        "북구": "31200", "울주군": "31710",
    },
    "36": {  # 세종
        "세종시": "36110",
    },
    "41": {  # 경기
        "수원 장안구": "41111", "수원 권선구": "41113",
        "수원 팔달구": "41115", "수원 영통구": "41117",
        "성남 수정구": "41131", "성남 중원구": "41133", "성남 분당구": "41135",
        "의정부시": "41150",
        "안양 만안구": "41171", "안양 동안구": "41173",
        "부천시": "41190", "광명시": "41210", "평택시": "41220",
        "동두천시": "41250",
        "안산 상록구": "41271", "안산 단원구": "41273",
        "고양 덕양구": "41281", "고양 일산동구": "41285", "고양 일산서구": "41287",
        "과천시": "41290", "구리시": "41310", "남양주시": "41360",
        "오산시": "41370", "시흥시": "41390", "군포시": "41410",
        "의왕시": "41430", "하남시": "41450",
        "용인 처인구": "41461", "용인 기흥구": "41463", "용인 수지구": "41465",
        "파주시": "41480", "이천시": "41500", "안성시": "41550",
        "김포시": "41570", "화성시": "41590", "광주시": "41610",
        "양주시": "41630", "포천시": "41650", "여주시": "41670",
        "연천군": "41800", "가평군": "41820", "양평군": "41830",
    },
    "42": {  # 강원
        "춘천시": "42110", "원주시": "42130", "강릉시": "42150",
        "동해시": "42170", "태백시": "42190", "속초시": "42210",
        "삼척시": "42230", "홍천군": "42720", "횡성군": "42730",
        "영월군": "42750", "평창군": "42760", "정선군": "42770",
        "철원군": "42780", "화천군": "42790", "양구군": "42800",
        "인제군": "42810", "고성군": "42820", "양양군": "42830",
    },
    "43": {  # 충북
        "청주 상당구": "43111", "청주 서원구": "43112",
        "청주 흥덕구": "43113", "청주 청원구": "43114",
        "충주시": "43130", "제천시": "43150",
        "보은군": "43720", "옥천군": "43730", "영동군": "43740",
        "증평군": "43745", "진천군": "43750", "괴산군": "43760",
        "음성군": "43770", "단양군": "43800",
    },
    "44": {  # 충남
        "천안 동남구": "44131", "천안 서북구": "44133",
        "공주시": "44150", "보령시": "44180", "아산시": "44200",
        "서산시": "44210", "논산시": "44230", "계룡시": "44250",
        "당진시": "44270", "금산군": "44710", "부여군": "44760",
        "서천군": "44770", "청양군": "44790", "홍성군": "44800",
        "예산군": "44810", "태안군": "44825",
    },
    "45": {  # 전북
        "전주 완산구": "45111", "전주 덕진구": "45113",
        "군산시": "45130", "익산시": "45140", "정읍시": "45180",
        "남원시": "45190", "김제시": "45210",
        "완주군": "45710", "진안군": "45720", "무주군": "45730",
        "장수군": "45740", "임실군": "45750", "순창군": "45770",
        "고창군": "45790", "부안군": "45800",
    },
    "46": {  # 전남
        "목포시": "46110", "여수시": "46130", "순천시": "46150",
        "나주시": "46170", "광양시": "46230",
        "담양군": "46710", "곡성군": "46720", "구례군": "46730",
        "고흥군": "46770", "보성군": "46780", "화순군": "46790",
        "장흥군": "46800", "강진군": "46810", "해남군": "46820",
        "영암군": "46830", "무안군": "46840", "함평군": "46860",
        "영광군": "46870", "장성군": "46880", "완도군": "46890",
        "진도군": "46900", "신안군": "46910",
    },
    "47": {  # 경북
        "포항 남구": "47111", "포항 북구": "47113",
        "경주시": "47130", "김천시": "47150", "안동시": "47170",
        "구미시": "47190", "영주시": "47210", "영천시": "47230",
        "상주시": "47250", "문경시": "47280", "경산시": "47290",
        "의성군": "47730", "청송군": "47750", "영양군": "47760",
        "영덕군": "47770", "청도군": "47820", "고령군": "47830",
        "성주군": "47840", "칠곡군": "47850",
        "예천군": "47900", "봉화군": "47920", "울진군": "47930",
        "울릉군": "47940",
    },
    "48": {  # 경남
        "창원 의창구": "48121", "창원 성산구": "48123",
        "창원 마산합포구": "48125", "창원 마산회원구": "48127",
        "창원 진해구": "48129",
        "진주시": "48170", "통영시": "48220", "사천시": "48240",
        "김해시": "48250", "밀양시": "48270", "거제시": "48310",
        "양산시": "48330",
        "의령군": "48720", "함안군": "48730", "창녕군": "48740",
        "고성군": "48820", "남해군": "48840", "하동군": "48850",
        "산청군": "48860", "함양군": "48870", "거창군": "48880",
        "합천군": "48890",
    },
    "50": {  # 제주
        "제주시": "50110", "서귀포시": "50130",
    },
}

# 하위 호환: 기존 코드에서 직접 쓰던 flat map (레이더 등에서 사용)
_MOLIT_REGION_MAP: dict[str, str] = {
    f"{sido} {sigungu}": code
    for sido, sido_code in _SIDO_MAP.items()
    for sigungu, code in _SIGUNGU_MAP.get(sido_code, {}).items()
}


def _region_selector(prefix: str = "") -> tuple:
    """시도 → 시군구 → (선택적) 동 필터 3단계 UI.
    반환: (lawd_cd_5자리, 시군구_레이블, 동_필터문자열)
    
    ※ sigungu key에 sido 이름을 포함시켜 sido 변경 시 위젯을 자동 초기화함.
    """
    sido_list = list(_SIDO_MAP.keys())
    default_sido_idx = sido_list.index("서울") if "서울" in sido_list else 0

    # ── 시도 선택 ──
    sido = st.selectbox("📍 시/도", sido_list, index=default_sido_idx,
                        key=f"{prefix}_sido")

    sido_code    = _SIDO_MAP[sido]
    sigungu_dict = _SIGUNGU_MAP.get(sido_code, {})
    sigungu_list = list(sigungu_dict.keys())

    # ── 시군구 선택: key에 sido 이름 포함 → sido 변경 시 자동 새 위젯 ──
    default_sg_idx = 0
    if sido == "서울" and "강남구" in sigungu_list:
        default_sg_idx = sigungu_list.index("강남구")

    sigungu = st.selectbox("🏘 시/군/구", sigungu_list, index=default_sg_idx,
                           key=f"{prefix}_{sido}_sg")

    lawd_cd = sigungu_dict.get(sigungu, (list(sigungu_dict.values()) or ["11110"])[0])

    # ── 동 필터 ──
    dong_filter = st.text_input(
        "🔍 읍·면·동 필터 (선택, 미입력 시 전체)",
        key=f"{prefix}_dong",
        placeholder="예: 대치동 (비워두면 전체 표시)",
    )

    st.caption(f"선택 지역: **{sido} {sigungu}** (코드 {lawd_cd})")
    return lawd_cd, f"{sido} {sigungu}", dong_filter.strip()

def _molit_fetch_xml(endpoint: str, params: dict) -> str:
    """urllib로 국토부 API XML 조회 (requests 미설치 환경 대응)."""
    from urllib.parse import urlencode  # noqa: PLC0415
    from urllib.request import urlopen  # noqa: PLC0415
    qs  = urlencode(params)
    full_url = f"{endpoint}?{qs}"
    with urlopen(full_url, timeout=10) as resp:  # noqa: S310
        raw = resp.read()
    # 인코딩 자동 감지
    for enc in ("utf-8", "euc-kr", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_molit_trade(lawd_cd: str, deal_ymd: str, api_key: str,
                       num_rows: int = 50) -> list[dict]:
    """국토교통부 아파트 매매 실거래 조회. 반환: list of dict."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    endpoint = (
        "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest"
        "/RTMSOBJSvc/getRTMSDataSvcAptTradeDev"
    )
    params = {
        "serviceKey": api_key,
        "LAWD_CD":    lawd_cd,
        "DEAL_YMD":   deal_ymd,
        "numOfRows":  num_rows,
        "pageNo":     1,
    }
    try:
        xml_text = _molit_fetch_xml(endpoint, params)
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        rows = []
        for item in items:
            def _t(tag: str, _item: "ET.Element" = item) -> str:
                el = _item.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            price_raw = _t("거래금액").replace(",", "").strip()
            try:
                price = int(price_raw)
            except ValueError:
                continue
            rows.append({
                "단지명":   _t("아파트"),
                "가격":     price,
                "가격표시": f"{price // 10_000}억 {price % 10_000:,}" if price >= 10_000
                            else f"{price:,}만",
                "전용면적": _t("전용면적"),
                "층":       _t("층"),
                "년":       _t("년"),
                "월":       _t("월"),
                "일":       _t("일"),
                "법정동":   _t("법정동"),
                "건축년도": _t("건축년도"),
            })
        return sorted(rows, key=lambda r: r["가격"], reverse=True)
    except Exception:
        return []


@st.cache_data(ttl=1800, show_spinner=False)
def _fetch_molit_rent(lawd_cd: str, deal_ymd: str, api_key: str,
                      num_rows: int = 50) -> list[dict]:
    """국토교통부 아파트 전월세 조회."""
    import xml.etree.ElementTree as ET  # noqa: PLC0415
    endpoint = (
        "http://openapi.molit.go.kr/OpenAPI_ToolInstallPackage/service/rest"
        "/RTMSOBJSvc/getRTMSDataSvcAptRent"
    )
    params = {
        "serviceKey": api_key,
        "LAWD_CD":    lawd_cd,
        "DEAL_YMD":   deal_ymd,
        "numOfRows":  num_rows,
        "pageNo":     1,
    }
    try:
        xml_text = _molit_fetch_xml(endpoint, params)
        root = ET.fromstring(xml_text)
        items = root.findall(".//item")
        rows = []
        for item in items:
            def _t(tag: str, _item: "ET.Element" = item) -> str:
                el = _item.find(tag)
                return el.text.strip() if el is not None and el.text else ""
            dep_raw  = _t("보증금액").replace(",", "").strip()
            rent_raw = _t("월세금액").replace(",", "").strip()
            try:
                dep  = int(dep_raw)  if dep_raw  else 0
                rent = int(rent_raw) if rent_raw else 0
            except ValueError:
                continue
            rows.append({
                "단지명":   _t("아파트"),
                "보증금":   dep,
                "월세":     rent,
                "표시":     f"보증 {dep:,}만/{rent:,}만" if rent > 0 else f"전세 {dep:,}만",
                "전용면적": _t("전용면적"),
                "층":       _t("층"),
                "년":       _t("년"),
                "월":       _t("월"),
                "일":       _t("일"),
                "법정동":   _t("법정동"),
            })
        return sorted(rows, key=lambda r: r["보증금"], reverse=True)
    except Exception:
        return []


def _price_card_html(rank: int, name: str, price_str: str,
                     area: str, date: str, dong: str,
                     floor: str, built: str = "") -> str:
    """실거래 카드 HTML 한 줄."""
    area_py = f"{float(area)/3.3058:.1f}평" if area else ""
    built_str = f" · {built}년" if built else ""
    return (
        f"<div style='padding:0.55rem 0.75rem;margin-bottom:0.4rem;"
        f"background:rgba(30,27,75,0.55);border-radius:10px;"
        f"border-left:3px solid #818cf8;'>"
        f"<span style='color:#a5b4fc;font-size:0.82rem;'>#{rank} {dong}</span>"
        f"<br><b style='font-size:1.05rem;'>{name}</b>"
        f"&nbsp;<span style='color:#fbbf24;font-weight:700;'>{price_str}</span>"
        f"<br><span style='color:#94a3b8;font-size:0.82rem;'>"
        f"{area}㎡({area_py}) · {floor}층 · {date}{built_str}</span>"
        f"</div>"
    )


def _render_tab_apt_market() -> None:
    """🔥 아파트 실거래 — apt2.me 스타일 (국토부 API 연동)"""
    st.header("🔥 아파트 실거래 현황")

    # ── 빠른 링크 (API 없이도 사용 가능) ───────────────────────
    st.markdown(
        "<div style='display:flex;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.7rem;'>"
        + "".join(
            f"<a href='{url}' target='_blank' style='padding:0.3rem 0.65rem;"
            f"background:rgba(99,102,241,0.25);border-radius:20px;"
            f"color:#a5b4fc;font-size:0.85rem;text-decoration:none;"
            f"border:1px solid rgba(129,140,248,0.35);white-space:nowrap;'>{lbl}</a>"
            for lbl, url in [
                ("🏠 아파트미 홈", "https://apt2.me"),
                ("🗺️ 실거래 지도", "https://apt2.me/apt/MapList.jsp"),
                ("📅 일별 실거래", "https://apt2.me/apt/map_day.jsp"),
                ("📆 주간 실거래", "https://apt2.me/apt/AptWDaily.jsp"),
                ("🏆 이달 신고가", "https://apt2.me/apt/AptMonth.jsp"),
                ("🔄 반등 실거래", "https://apt2.me/apt/AptMonthBfSin.jsp"),
                ("📝 분양권 실거래", "https://apt2.me/apt/BunMonth.jsp"),
                ("🏠 전세 실거래", "https://apt2.me/apt/RentMonth.jsp"),
            ]
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    # ── 키워드 검색 바로가기 ──────────────────────────────────
    with _st_try_border_container():
        st.markdown("**🔍 단지 키워드 검색 (아파트미)**")
        st.caption("ex) 송파 헬리오 → 단어+공백+단어 형식")
        kc1, kc2 = st.columns([5, 1])
        with kc1:
            kw = st.text_input("단지명 검색", key="apt2_kw",
                               placeholder="예: 래미안 원베일리",
                               label_visibility="collapsed")
        with kc2:
            if st.button("검색 →", key="apt2_kw_go"):
                if kw.strip():
                    q = kw.strip().replace(" ", "+")
                    st.markdown(
                        f"<script>window.open('https://apt2.me/apt/AptSearch.jsp?keyword={q}','_blank')</script>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"[🔗 아파트미에서 **'{kw}'** 검색하기]"
                        f"(https://apt2.me/apt/AptSearch.jsp?keyword={q.replace('+','%20')})"
                        f" ← 클릭해 새 탭에서 확인",
                    )

    st.divider()

    api_key = (
        (
            os.environ.get("MOLIT_API_KEY")
            or os.environ.get("DATA_GO_KR_SERVICE_KEY")
            or os.environ.get("APT_SERVICE_KEY")
            or ""
        )
        .strip()
    )
    if not api_key:
        st.info(
            "국토부 실거래 **표/API 직접 조회**는 서버에 `MOLIT_API_KEY` 또는 "
            "`DATA_GO_KR_SERVICE_KEY` 또는 `APT_SERVICE_KEY` 환경변수가 있을 때만 켜집니다. "
            "위 링크·단지 검색은 키 없이 이용할 수 있습니다."
        )
        return

    # ── 시도 → 시군구 → 동 3단계 지역 선택 ───────────────────
    from datetime import date as _date  # noqa: PLC0415
    today = _date.today()

    st.markdown("**📍 지역 선택**")
    lawd_cd, region_label, dong_filter = _region_selector("mkt")

    dc1, dc2 = st.columns(2)
    with dc1:
        year_opt = st.selectbox("년도", list(range(today.year, today.year - 4, -1)),
                                key="molit_year")
    with dc2:
        month_opt = st.selectbox("월",
                                 list(range(today.month, 0, -1))
                                 + list(range(12, today.month, -1)),
                                 key="molit_month",
                                 format_func=lambda m: f"{m:02d}월")
    if dong_filter:
        st.caption(f"🔍 동 필터 적용: **{dong_filter}** 포함 거래만 표시")

    deal_ymd = f"{year_opt}{month_opt:02d}"

    # ── 데이터 조회 ───────────────────────────────────────────
    t_trade, t_rent = st.tabs(["🏷️ 매매 실거래", "📋 전세·월세"])

    with t_trade:
        with st.spinner(f"{region_label} {year_opt}년 {month_opt:02d}월 매매 조회 중…"):
            rows_all = _fetch_molit_trade(lawd_cd, deal_ymd, api_key)
        # 동 필터 적용
        rows = [r for r in rows_all if dong_filter in r["법정동"]] if dong_filter else rows_all

        if not rows:
            st.warning("데이터가 없습니다. API 키·지역·기간을 확인하세요.")
        else:
            st.caption(f"총 **{len(rows)}건** 조회 (가격 내림차순)")

            # ── 신고가 TOP10 ──
            st.markdown("#### 🏆 신고가 TOP 10")
            for i, r in enumerate(rows[:10], 1):
                date_str = f"{r['년']}.{r['월']}.{r['일']}"
                st.markdown(
                    _price_card_html(i, r["단지명"], r["가격표시"],
                                     r["전용면적"], date_str,
                                     r["법정동"], r["층"], r["건축년도"]),
                    unsafe_allow_html=True,
                )

            # ── 전체 실거래 테이블 ──
            if pd is not None:
                with st.expander(f"📋 전체 {len(rows)}건 보기", expanded=False):
                    import pandas as _pd  # noqa: PLC0415
                    df = _pd.DataFrame([{
                        "단지명": r["단지명"], "가격(만원)": r["가격"],
                        "전용㎡": r["전용면적"], "층": r["층"],
                        "법정동": r["법정동"], "계약일": f"{r['년']}.{r['월']}.{r['일']}",
                        "건축": r["건축년도"],
                    } for r in rows])
                    st.dataframe(df, use_container_width=True, hide_index=True)

            # ── 가격 분포 차트 ──
            if go is not None and rows:
                prices = [r["가격"] for r in rows]
                names  = [r["단지명"][:10] for r in rows[:20]]
                fig_p = go.Figure()
                fig_p.add_trace(go.Bar(
                    x=list(range(1, len(names) + 1)),
                    y=[p / 10_000 for p in prices[:20]],
                    text=names, textposition="outside",
                    marker=dict(
                        color=[f"rgba(129,140,248,{0.5 + 0.5*i/20})"
                               for i in range(len(names))],
                        line=dict(color="rgba(165,180,252,0.4)", width=0),
                        cornerradius=4,
                    ),
                    hovertemplate="<b>%{text}</b><br>%{y:.2f}억<extra></extra>",
                ))
                fig_p.update_layout(
                    title=dict(
                        text=f"<b>매매 신고가 TOP20 · {region_label} {year_opt}.{month_opt:02d}</b>",
                        font=dict(size=13, color="#e0e7ff"), x=0.02,
                    ),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,12,60,0.28)",
                    font=dict(color="#eef2ff", size=11),
                    xaxis=dict(title="순위", tickfont=dict(size=10),
                               showgrid=False),
                    yaxis=dict(title="가격 (억원)", tickformat=".1f",
                               tickfont=dict(size=10),
                               gridcolor="rgba(165,180,252,0.10)"),
                    margin=dict(l=8, r=8, t=44, b=36),
                    height=280,
                    showlegend=False,
                    hovermode="x",
                    hoverlabel=dict(bgcolor="rgba(15,12,60,0.92)",
                                    font=dict(size=11, color="#eef2ff")),
                )
                st.plotly_chart(fig_p, use_container_width=True,
                                config={"displayModeBar": False})

                # ── 가격대별 분포 히스토그램 ──
                fig_h = go.Figure()
                fig_h.add_trace(go.Histogram(
                    x=[p / 10_000 for p in prices],
                    nbinsx=20,
                    marker=dict(color="rgba(129,140,248,0.65)",
                                line=dict(color="rgba(165,180,252,0.5)", width=1)),
                    hovertemplate="<b>%{x:.1f}억대</b> %{y}건<extra></extra>",
                ))
                fig_h.update_layout(
                    title=dict(text="<b>가격대별 거래 분포</b>",
                               font=dict(size=13, color="#e0e7ff"), x=0.02),
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(15,12,60,0.28)",
                    font=dict(color="#eef2ff", size=11),
                    xaxis=dict(title="가격 (억원)", tickfont=dict(size=10),
                               gridcolor="rgba(165,180,252,0.08)"),
                    yaxis=dict(title="거래 건수", tickfont=dict(size=10),
                               gridcolor="rgba(165,180,252,0.10)"),
                    margin=dict(l=8, r=8, t=44, b=36),
                    height=220,
                    showlegend=False,
                    bargap=0.08,
                    hoverlabel=dict(bgcolor="rgba(15,12,60,0.92)",
                                    font=dict(size=11, color="#eef2ff")),
                )
                st.plotly_chart(fig_h, use_container_width=True,
                                config={"displayModeBar": False})

    with t_rent:
        with st.spinner(f"{region_label} {year_opt}년 {month_opt:02d}월 전월세 조회 중…"):
            rent_rows_all = _fetch_molit_rent(lawd_cd, deal_ymd, api_key)
        rent_rows = ([r for r in rent_rows_all if dong_filter in r["법정동"]]
                     if dong_filter else rent_rows_all)

        if not rent_rows:
            st.warning("전월세 데이터가 없거나 API 오류입니다.")
        else:
            jeonse = [r for r in rent_rows if r["월세"] == 0]
            monthly = [r for r in rent_rows if r["월세"] > 0]
            st.caption(f"전세 **{len(jeonse)}건** · 월세 **{len(monthly)}건** (보증금 내림차순)")

            rr1, rr2 = st.columns(2)
            with rr1:
                st.markdown("#### 🔑 전세 TOP 10")
                for i, r in enumerate(jeonse[:10], 1):
                    date_str = f"{r['년']}.{r['월']}.{r['일']}"
                    st.markdown(
                        f"<div style='padding:0.45rem 0.65rem;margin-bottom:0.35rem;"
                        f"background:rgba(52,211,153,0.12);border-radius:9px;"
                        f"border-left:3px solid #34d399;'>"
                        f"<span style='color:#6ee7b7;font-size:0.8rem;'>#{i} {r['법정동']}</span><br>"
                        f"<b>{r['단지명']}</b> "
                        f"<span style='color:#34d399;font-weight:700;'>{r['표시']}</span><br>"
                        f"<span style='color:#94a3b8;font-size:0.8rem;'>"
                        f"{r['전용면적']}㎡ · {r['층']}층 · {date_str}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )
            with rr2:
                st.markdown("#### 💵 월세 TOP 10")
                for i, r in enumerate(monthly[:10], 1):
                    date_str = f"{r['년']}.{r['월']}.{r['일']}"
                    st.markdown(
                        f"<div style='padding:0.45rem 0.65rem;margin-bottom:0.35rem;"
                        f"background:rgba(251,191,36,0.12);border-radius:9px;"
                        f"border-left:3px solid #fbbf24;'>"
                        f"<span style='color:#fcd34d;font-size:0.8rem;'>#{i} {r['법정동']}</span><br>"
                        f"<b>{r['단지명']}</b> "
                        f"<span style='color:#fbbf24;font-weight:700;'>{r['표시']}</span><br>"
                        f"<span style='color:#94a3b8;font-size:0.8rem;'>"
                        f"{r['전용면적']}㎡ · {r['층']}층 · {date_str}</span>"
                        f"</div>",
                        unsafe_allow_html=True,
                    )


def _render_tab_real_estate_calc() -> None:
    """🏠 부동산 계산기 — 취득세 · 대출 월 상환액 · 임대 수익률"""
    st.header("🏠 부동산 계산기")

    calc_tabs = st.tabs(["🧾 취득세", "🏦 대출 계산", "📊 임대 수익률"])

    # ── ① 취득세 ──────────────────────────────────────────────
    with calc_tabs[0]:
        st.subheader("취득세 계산 (2024년 기준)")
        c1, c2 = st.columns(2)
        with c1:
            price_uk = st.number_input("매매가 (억원)", min_value=0.1, value=5.0,
                                       step=0.5, format="%.1f", key="re_calc_price")
            owned = st.radio("현재 보유 주택 수",
                             ["0주택 (무주택)", "1주택", "2주택", "3주택 이상"],
                             index=0, key="re_calc_owned")
        with c2:
            adjusted = st.radio("조정대상지역 여부",
                                ["조정대상지역", "비조정지역"],
                                index=0, key="re_calc_adj")
            house_type = st.radio("주택 면적",
                                  ["국민주택(85㎡ 이하)", "85㎡ 초과"],
                                  index=1, key="re_calc_area")

        price = price_uk * 1_0000  # 만원

        # 취득세율 결정
        is_adj = adjusted == "조정대상지역"
        if owned == "0주택 (무주택)" or owned == "1주택":
            # 1주택 이하 취득: 1~3% 누진
            if price <= 6_0000:
                acq_rate = 0.01
            elif price <= 9_0000:
                acq_rate = (price * 2 / 30_000 - 3) / 100
            else:
                acq_rate = 0.03
        elif owned == "2주택":
            acq_rate = 0.08 if is_adj else (0.01 if price <= 6_0000 else 0.03)
        else:  # 3주택 이상
            acq_rate = 0.12 if is_adj else 0.08

        edu_rate  = 0.001 if acq_rate <= 0.01 else (0.002 if acq_rate <= 0.03 else 0.004)
        agri_rate = 0.002 if house_type == "85㎡ 초과" and acq_rate < 0.08 else 0.0

        acq_tax   = price * acq_rate
        edu_tax   = price * edu_rate
        agri_tax  = price * agri_rate
        total_tax = acq_tax + edu_tax + agri_tax
        total_rate = total_tax / price * 100

        st.markdown("---")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("취득세", f"{acq_tax:,.0f} 만원", f"{acq_rate*100:.1f}%")
        mc2.metric("지방교육세", f"{edu_tax:,.0f} 만원", f"{edu_rate*100:.2f}%")
        mc3.metric("농어촌특별세", f"{agri_tax:,.0f} 만원", f"{agri_rate*100:.2f}%")
        mc4.metric("합계", f"{total_tax:,.0f} 만원", f"취득가의 {total_rate:.2f}%")

        st.caption("⚠️ 취득세율은 단순화 모델 · 세율은 2024년 기준이며 법령 개정 시 달라질 수 있습니다.")

    # ── ② 대출 계산 ────────────────────────────────────────────
    with calc_tabs[1]:
        st.subheader("대출 월 상환액 계산")
        lc1, lc2 = st.columns(2)
        with lc1:
            loan_uk  = st.number_input("대출 금액 (억원)", min_value=0.1, value=3.0,
                                       step=0.5, format="%.1f", key="loan_calc_amt")
            loan_yr  = st.number_input("대출 기간 (년)", min_value=1, value=30,
                                       step=1, key="loan_calc_yr")
        with lc2:
            loan_rate_pct = st.number_input("금리 (%/년)", min_value=0.1, value=4.5,
                                            step=0.1, format="%.2f", key="loan_calc_rate")
            repay_type = st.radio("상환 방식",
                                  ["원리금균등상환", "원금균등상환"],
                                  index=0, key="loan_calc_type", horizontal=True)

        P  = loan_uk * 1_0000  # 만원
        r  = loan_rate_pct / 100 / 12
        n  = loan_yr * 12

        if repay_type == "원리금균등상환":
            if r > 0:
                monthly_payment = P * r * (1 + r) ** n / ((1 + r) ** n - 1)
            else:
                monthly_payment = P / n
            total_repay = monthly_payment * n
            total_int   = total_repay - P

            st.markdown("---")
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("월 상환액", f"{monthly_payment:,.0f} 만원")
            rc2.metric("총 상환액", f"{total_repay/1_0000:.2f} 억원")
            rc3.metric("총 이자", f"{total_int/1_0000:.2f} 억원",
                       delta=f"이자율 {total_int/P*100:.1f}%", delta_color="inverse")
        else:
            monthly_principal = P / n
            first_int  = P * r
            first_pay  = monthly_principal + first_int
            last_pay   = monthly_principal + monthly_principal * r
            total_int  = sum((P - monthly_principal * i) * r for i in range(n))
            total_repay = P + total_int

            st.markdown("---")
            rc1, rc2, rc3 = st.columns(3)
            rc1.metric("첫 달 상환액", f"{first_pay:,.0f} 만원",
                       help=f"마지막 달: {last_pay:,.0f} 만원")
            rc2.metric("총 상환액", f"{total_repay/1_0000:.2f} 억원")
            rc3.metric("총 이자", f"{total_int/1_0000:.2f} 억원",
                       delta=f"원리금균등 대비 절약", delta_color="normal")

        # 금리별 비교표
        with st.expander("📊 금리별 월 상환액 비교", expanded=False):
            rows = []
            for r_pct in [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0]:
                r_m = r_pct / 100 / 12
                if r_m > 0:
                    mp = P * r_m * (1 + r_m) ** n / ((1 + r_m) ** n - 1)
                else:
                    mp = P / n
                rows.append({"금리": f"{r_pct:.1f}%",
                              "월 상환": f"{mp:,.0f} 만원",
                              "총 이자": f"{(mp*n - P)/1_0000:.2f} 억원"})
            if pd is not None:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)

    # ── ③ 임대 수익률 ──────────────────────────────────────────
    with calc_tabs[2]:
        st.subheader("임대 수익률 분석")
        ic1, ic2 = st.columns(2)
        with ic1:
            buy_price_uk  = st.number_input("매매가 (억원)", min_value=0.1, value=5.0,
                                            step=0.5, format="%.1f", key="yield_buy")
            deposit_uk    = st.number_input("보증금 (억원)", min_value=0.0, value=1.0,
                                            step=0.5, format="%.1f", key="yield_dep")
        with ic2:
            monthly_rent  = st.number_input("월세 (만원)", min_value=0, value=100,
                                            step=10, key="yield_rent")
            annual_cost   = st.number_input("연간 유지비 (만원, 관리비·수선·세금)",
                                            min_value=0, value=300,
                                            step=50, key="yield_cost")

        net_invest     = (buy_price_uk - deposit_uk) * 1_0000
        annual_income  = monthly_rent * 12
        annual_net     = annual_income - annual_cost
        gross_yield    = annual_income / (buy_price_uk * 1_0000) * 100
        net_yield      = annual_net   / net_invest * 100 if net_invest > 0 else 0.0
        cap_rate       = annual_net   / (buy_price_uk * 1_0000) * 100

        st.markdown("---")
        yc1, yc2, yc3 = st.columns(3)
        yc1.metric("총 수익률 (Gross)", f"{gross_yield:.2f}%", help="연 임대료 / 매매가")
        yc2.metric("순 수익률 (Net)", f"{net_yield:.2f}%",
                   help=f"실투자금 {net_invest/1_0000:.1f}억 기준")
        yc3.metric("CAP Rate", f"{cap_rate:.2f}%", help="순임대수익 / 매매가")

        payback = net_invest / annual_net if annual_net > 0 else float("inf")
        st.caption(f"💡 순수익 기준 투자금 회수 예상 기간: **{payback:.1f}년**")


def _breakeven_win_rate_pct(avg_win_pct: float, avg_loss_pct: float) -> float:
    """평균 이익·평균 손실(절댓값 %) 가정 시 기댓값 0이 되는 승률(%). p = L/(W+L)."""
    w, ell = float(avg_win_pct), float(avg_loss_pct)
    if w <= 0 or ell <= 0:
        return float("nan")
    return 100.0 * ell / (w + ell)


def _expected_return_per_trade_pct(
    win_rate_pct: float, avg_win_pct: float, avg_loss_pct: float,
    *, round_trip_cost_pct: float = 0.0,
) -> float:
    """회당 순이익 기대값(%). 왕복 비용은 이익에서 차감·손실에 가산(단순 모델)."""
    p = max(0.0, min(1.0, float(win_rate_pct) / 100.0))
    w = max(0.0, float(avg_win_pct) - float(round_trip_cost_pct))
    ell = float(avg_loss_pct) + float(round_trip_cost_pct)
    return p * w - (1.0 - p) * ell


def _render_tab_stock_calc() -> None:
    """📈 주식 계산기 — 수익률·복리·세금·승률 참고"""
    st.header("📈 주식 계산기")
    calc_tabs = st.tabs(["💹 수익률 계산", "📦 복리 계산", "🧾 세금 계산", "🎯 승률·손익비 참고"])

    # ── ① 수익률 계산 ──────────────────────────────────────────
    with calc_tabs[0]:
        st.subheader("매매 수익률 계산")
        sc1, sc2 = st.columns(2)
        with sc1:
            buy_price  = st.number_input("매수가 (원)", min_value=1, value=50000,
                                         step=100, key="stk_buy")
            shares     = st.number_input("주수", min_value=1, value=100,
                                         step=1, key="stk_shares")
            fee_rate   = st.number_input("수수료율 (%)", min_value=0.0, value=0.015,
                                         step=0.005, format="%.3f", key="stk_fee")
        with sc2:
            sell_price = st.number_input("목표가 (원)", min_value=1, value=60000,
                                         step=100, key="stk_sell")
            is_overseas = st.checkbox("해외 주식 (양도세 22% 적용)", key="stk_overseas")

        invest      = buy_price * shares
        proceed     = sell_price * shares
        buy_fee     = invest  * fee_rate / 100
        sell_fee    = proceed * fee_rate / 100
        gross_gain  = proceed - invest
        net_before_tax = gross_gain - buy_fee - sell_fee

        # 세금
        if is_overseas:
            exempt = 250_0000  # 250만원 공제
            taxable = max(0.0, net_before_tax - exempt)
            cap_gain_tax = taxable * 0.22
        else:
            cap_gain_tax = 0.0  # 소액 주주 비과세 (국내)

        net_gain = net_before_tax - cap_gain_tax
        ret_pct  = net_gain / invest * 100

        st.markdown("---")
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("투자금", f"{invest:,.0f}원")
        mc2.metric("순 수익", f"{net_gain:,.0f}원",
                   delta=f"{ret_pct:+.2f}%",
                   delta_color="normal" if net_gain >= 0 else "inverse")
        mc3.metric("수수료 합계", f"{buy_fee + sell_fee:,.0f}원")
        mc4.metric("양도세", f"{cap_gain_tax:,.0f}원",
                   help="해외 주식: 250만원 공제 후 22%")

        # 손익분기점
        bep = buy_price * (1 + (buy_fee + sell_fee) / invest)
        st.caption(f"💡 손익분기점 (수수료 회수): **{bep:,.0f}원**")

    # ── ② 복리 계산 ────────────────────────────────────────────
    with calc_tabs[1]:
        st.subheader("복리·적립식 계산")
        cc1, cc2 = st.columns(2)
        with cc1:
            cp = st.number_input("초기 투자금 (만원)", min_value=0, value=1000,
                                 step=100, key="comp_principal")
            cm = st.number_input("월 적립금 (만원)", min_value=0, value=50,
                                 step=10, key="comp_monthly")
        with cc2:
            cr = st.number_input("연 수익률 (%)", min_value=0.0, value=8.0,
                                 step=0.5, format="%.1f", key="comp_rate")
            cy = st.number_input("투자 기간 (년)", min_value=1, value=20,
                                 step=1, key="comp_years")

        r_m = cr / 100 / 12
        n_m = cy * 12
        # 원금 복리
        pv_future = cp * (1 + r_m) ** n_m if r_m > 0 else cp
        # 월 적립 미래가치
        if r_m > 0:
            fv_monthly = cm * ((1 + r_m) ** n_m - 1) / r_m
        else:
            fv_monthly = cm * n_m
        total_future = pv_future + fv_monthly
        total_invest = cp + cm * n_m

        st.markdown("---")
        bc1, bc2, bc3 = st.columns(3)
        bc1.metric("총 투자원금", f"{total_invest:,.0f} 만원")
        bc2.metric("예상 미래 자산", f"{total_future:,.0f} 만원",
                   delta=f"{total_future/1_0000:.2f} 억원")
        bc3.metric("수익 (복리 효과)", f"{total_future - total_invest:,.0f} 만원",
                   delta=f"{(total_future/total_invest - 1)*100:.1f}%",
                   delta_color="normal")

        st.caption(f"💡 72의 법칙: 연 {cr:.1f}% → 원금 2배 약 **{72/cr:.1f}년**" if cr > 0 else "")

        if go is not None:
            # 연도별 성장 차트
            yrs = list(range(cy + 1))
            vals_k = []
            for y in yrs:
                n_y = y * 12
                pv = cp * (1 + r_m) ** n_y if r_m > 0 else cp
                fv = cm * ((1 + r_m) ** n_y - 1) / r_m if r_m > 0 else cm * n_y
                vals_k.append((pv + fv) / 1_0000)
            invest_line = [(cp + cm * y * 12) / 1_0000 for y in yrs]

            fig_c = go.Figure()
            fig_c.add_trace(go.Scatter(x=yrs, y=vals_k, name="복리 자산",
                                       fill="tozeroy", fillcolor="rgba(52,211,153,0.10)",
                                       line=dict(color="#34d399", width=2.5)))
            fig_c.add_trace(go.Scatter(x=yrs, y=invest_line, name="단순 원금",
                                       line=dict(color="#a5b4fc", width=1.5, dash="dot")))
            fig_c.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(15,12,60,0.25)",
                font=dict(color="#eef2ff", size=12),
                xaxis=dict(title="년", tickfont=dict(size=11)),
                yaxis=dict(title="억원", tickformat=".2f", tickfont=dict(size=11),
                           gridcolor="rgba(165,180,252,0.10)"),
                legend=dict(orientation="h", y=1.12, x=0.5, xanchor="center",
                            bgcolor="rgba(0,0,0,0)", font=dict(size=11)),
                margin=dict(l=8, r=8, t=36, b=36), height=220,
                hovermode="x unified",
            )
            st.plotly_chart(fig_c, use_container_width=True,
                            config={"displayModeBar": False})

    # ── ③ 세금 계산 ────────────────────────────────────────────
    with calc_tabs[2]:
        st.subheader("주식 세금 정리")
        st.markdown("""
| 구분 | 세율 | 공제 | 비고 |
|---|---|---|---|
| **국내 주식 (소액주주)** | 비과세 | — | 매매차익 비과세 |
| **국내 주식 (대주주)** | 20~25% | — | 지분 1% 또는 10억 이상 |
| **해외 주식 양도세** | 22% | 250만원/년 | 확정신고 5월 |
| **배당소득세** | 15.4% | — | 종합소득 2천만 초과 시 종합과세 |
| **금융투자소득세** | 20~25% | 5천만원 | 2025년 시행 예정 (변동 가능) |
""")
        st.divider()
        st.subheader("해외 주식 양도세 시뮬레이션")
        tx1, tx2 = st.columns(2)
        with tx1:
            annual_gain = st.number_input("연간 총 수익 (만원)", min_value=0, value=500,
                                          step=50, key="tax_gain")
        with tx2:
            annual_loss = st.number_input("연간 총 손실 (만원)", min_value=0, value=0,
                                          step=50, key="tax_loss")
        net = annual_gain - annual_loss
        taxable = max(0, net - 250)  # 250만원 공제
        tax_due = taxable * 0.22
        tc1, tc2, tc3 = st.columns(3)
        tc1.metric("순 수익", f"{net:,.0f} 만원")
        tc2.metric("과세 대상", f"{taxable:,.0f} 만원", help="250만원 기본공제 후")
        tc3.metric("납부 세액", f"{tax_due:,.0f} 만원", help="22% (지방소득세 포함)")
        st.caption("신고 기한: 매년 5월 / 손익통산 가능 (국가별 아님, 개인별 합산)")

    # ── ④ 승률·손익비 참고 (단타·스윙·장기) ─────────────────────
    with calc_tabs[3]:
        st.subheader("승률이 어느 정도여야 하나요?")
        st.caption(
            "한 회 매매에서 **평균 이익·평균 손실(절댓값)**이 비슷하게 반복된다고 가정할 때의 **참고치**입니다. "
            "실제로는 연속 손실·슬리피지·심리 때문에 더 높은 엣지가 필요합니다."
        )

        st.markdown("##### 프리셋 (탭 내 입력란에 반영)")
        pc1, pc2, pc3 = st.columns(3)
        with pc1:
            if st.button("⚡ 단타형", key="preset_day", use_container_width=True):
                st.session_state["wr_avg_win"] = 0.8
                st.session_state["wr_avg_loss"] = 0.5
                st.session_state["wr_cost"] = 0.08
                st.session_state["wr_my_win"] = 55.0
                st.session_state["wr_trades_y"] = 200
                st.rerun()
        with pc2:
            if st.button("📈 스윙형", key="preset_swing", use_container_width=True):
                st.session_state["wr_avg_win"] = 4.0
                st.session_state["wr_avg_loss"] = 2.0
                st.session_state["wr_cost"] = 0.04
                st.session_state["wr_my_win"] = 45.0
                st.session_state["wr_trades_y"] = 40
                st.rerun()
        with pc3:
            if st.button("🌳 장기형", key="preset_lt", use_container_width=True):
                st.session_state["wr_avg_win"] = 25.0
                st.session_state["wr_avg_loss"] = 8.0
                st.session_state["wr_cost"] = 0.02
                st.session_state["wr_my_win"] = 55.0
                st.session_state["wr_trades_y"] = 8
                st.rerun()

        st.markdown(
            """
| 스타일 | 가정 요지 | 프리셋 요지 |
|:---:|:---|:---|
| **단타** | 거래 많음·목표·스탑 촘촘 | 작은 % 이익/손실, 왕복 비용 비중 큼 → **승률 요구↑** |
| **스윙** | 며칠~몇 주 보유 | 손익비·승률 중간, 비용은 상대적으로 작음 |
| **장기** | 큰 추세·적은 거래 | 한 번의 손익 폭 큼, 이론상 손익분기 승률은 낮아질 수 있음 |
"""
        )

        if "wr_avg_win" not in st.session_state:
            st.session_state["wr_avg_win"] = 4.0
            st.session_state["wr_avg_loss"] = 2.0
            st.session_state["wr_cost"] = 0.04
            st.session_state["wr_my_win"] = 45.0
            st.session_state["wr_trades_y"] = 40

        wn1, wn2, wn3 = st.columns(3)
        with wn1:
            avg_win = st.number_input(
                "평균 이익 (%)", min_value=0.01, value=float(st.session_state["wr_avg_win"]),
                step=0.1, format="%.2f", key="wr_avg_win",
                help="수익본 거래들의 평균 수익률(대략)",
            )
        with wn2:
            avg_loss = st.number_input(
                "평균 손실 (%) 절댓값", min_value=0.01, value=float(st.session_state["wr_avg_loss"]),
                step=0.1, format="%.2f", key="wr_avg_loss",
                help="손절·손실 거래 평균 |절손실|%",
            )
        with wn3:
            cost_rt = st.number_input(
                "왕복 비용·슬리피지 (%)", min_value=0.0, value=float(st.session_state["wr_cost"]),
                step=0.01, format="%.3f", key="wr_cost",
                help="매수+매도 수수료·세금·체결 미끄럼을 한 번에 대략 잡은 값",
            )

        rr = avg_win / avg_loss if avg_loss > 0 else 0.0
        be_raw = _breakeven_win_rate_pct(avg_win, avg_loss)
        be_cost = _breakeven_win_rate_pct(
            max(0.01, avg_win - cost_rt), avg_loss + cost_rt
        )

        wm1, wm2 = st.columns(2)
        with wm1:
            my_wr = st.slider(
                "내가 가정하는 승률 (%)", 5.0, 95.0,
                float(st.session_state["wr_my_win"]), step=0.5, key="wr_my_win",
            )
        with wm2:
            n_trade_y = st.number_input(
                "연간 거래 횟수(회)", min_value=1, value=int(st.session_state["wr_trades_y"]),
                step=1, key="wr_trades_y",
                help="단타는 크게, 장기는 작게",
            )

        ev = _expected_return_per_trade_pct(my_wr, avg_win, avg_loss, round_trip_cost_pct=cost_rt)
        ev_simple = _expected_return_per_trade_pct(my_wr, avg_win, avg_loss, round_trip_cost_pct=0.0)

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(
            "손익분기 승률 (비용 전)",
            f"{be_raw:.1f}%" if be_raw == be_raw else "—",
            help="p = 평균손실 / (평균이익 + 평균손실)",
        )
        m2.metric(
            "손익분기 승률 (비용 반영)",
            f"{be_cost:.1f}%" if be_cost == be_cost else "—",
            help="이익측에서 왕복비용 차감, 손실측에 가산한 단순 모델",
        )
        m3.metric(
            "손익비 (평균이익/평균손실)", f"{rr:.2f}:1",
        )
        m4.metric(
            "회당 기대수익 (%)", f"{ev:+.3f}%",
            delta=f"비용 제외 시 {ev_simple:+.2f}%",
            delta_color="normal" if ev >= 0 else "inverse",
        )

        if ev == ev:
            st.caption(
                f"연 **{n_trade_y}**회·단순 가정 시 연간 기대 누적(복리 없이): **{ev * n_trade_y:+.1f}%** "
                f"(실제와 다를 수 있음)"
            )

        st.divider()
        st.markdown("**체크** — 내 승률이 손익분기보다 얼마나 위인가")
        if be_cost != be_cost:
            pass
        elif my_wr > be_cost + 0.05:
            edge = my_wr - be_cost
            st.success(f"가정상 손익분기(비용 반영) **{be_cost:.1f}%** 대비 승률 **+{edge:.1f}%p** 여유.")
        elif my_wr < be_cost - 0.05:
            st.warning(
                f"가정상 손익분기(비용 반영) **{be_cost:.1f}%** — 지금 승률 **{my_wr:.1f}%**는 이론상 **엣지 부족**."
            )
        else:
            st.info(
                f"손익분기(비용 반영) **{be_cost:.1f}%**와 거의 같습니다. "
                "분포·연속 손실·비용 변동만으로도 쉽게 마이너스로 갈 수 있습니다."
            )

        with st.expander("수식 요약", expanded=False):
            st.markdown(
                r"""
- **손익분기 승률** \(p^\*\): \(p^* = \dfrac{L}{W+L}\)  ($W$=평균 이익%, $L$=평균 손실 절댓값%)
- **손익비**: $R = W/L$ 이면 $p^* = \dfrac{1}{R+1}$
- **회당 기대값**(비용 $c$): $p(W-c) - (1-p)(L+c)$
- 단타는 $c$ 대비 $W,L$이 작아 **같은 전략이라도** $p^*$가 쉽게 올라갑니다.
"""
            )


def _render_tab_apt_watchlist() -> None:
    """🏘 관심 단지 — 실거래 흐름 & 유용한 링크"""
    st.header("🏘 관심 단지")
    st.caption("국토교통부 실거래가 API 또는 링크로 관심 단지 실거래 흐름을 확인하세요.")

    # ── 관심 단지 목록 관리 ──────────────────────────────────────
    if "apt_watchlist" not in st.session_state:
        st.session_state["apt_watchlist"] = []

    with _st_try_border_container():
        st.subheader("📌 관심 단지 등록")
        col_in, col_btn = st.columns([5, 1])
        with col_in:
            new_apt = st.text_input("단지명 입력 (예: 래미안 원베일리, 잠원 한신)",
                                    key="apt_input", placeholder="단지명을 입력하세요")
        with col_btn:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ 추가", key="apt_add"):
                name = new_apt.strip()
                if name and name not in st.session_state["apt_watchlist"]:
                    st.session_state["apt_watchlist"].append(name)

        if st.session_state["apt_watchlist"]:
            st.markdown("**등록된 관심 단지**")
            for i, apt in enumerate(st.session_state["apt_watchlist"]):
                ac1, ac2 = st.columns([8, 1])
                with ac1:
                    st.markdown(f"🏢 **{apt}**")
                with ac2:
                    if st.button("❌", key=f"apt_del_{i}"):
                        st.session_state["apt_watchlist"].pop(i)
                        st.rerun()
        else:
            st.info("관심 단지를 추가하면 바로 아래에서 실거래 검색 링크를 제공합니다.")

    # ── 실거래 조회 링크 ──────────────────────────────────────────
    if st.session_state["apt_watchlist"]:
        st.divider()
        st.subheader("🔍 실거래 조회 바로가기")
        from urllib.parse import quote  # noqa: PLC0415
        for apt in st.session_state["apt_watchlist"]:
            # 호갱노노/아실/네이버/KB 모두 UTF-8 퍼센트 인코딩 쿼리를 사용하는 편이 안정적
            q_enc = quote(apt.strip(), safe="")
            with _st_try_border_container():
                st.markdown(f"#### 🏢 {apt}")
                lc1, lc2, lc3, lc4 = st.columns(4)
                lc1.markdown(
                    f"[![호갱노노](https://img.shields.io/badge/호갱노노-FF6B35?style=flat)]"
                    f"(https://hogangnono.com/apt/search?q={q_enc})")
                lc2.markdown(
                    f"[![아실](https://img.shields.io/badge/아실-4CAF50?style=flat)]"
                    f"(https://asil.kr/asil/search.jsp?ename={q_enc})")
                lc3.markdown(
                    f"[![네이버부동산](https://img.shields.io/badge/네이버-03C75A?style=flat)]"
                    f"(https://land.naver.com/search/search.naver?query={q_enc})")
                lc4.markdown(
                    f"[![KB부동산](https://img.shields.io/badge/KB부동산-FFB900?style=flat)]"
                    f"(https://kbland.kr/map?tab=1&searchKeyword={q_enc})")

    # ── 부동산 시장 주요 지표 ──────────────────────────────────────
    st.divider()
    st.subheader("📊 부동산 관련 유용한 정보 사이트")
    info_rows = [
        ("🏠 국토교통부 실거래가", "https://rt.molit.go.kr", "아파트·빌라·토지 실거래가 공식 자료"),
        ("📊 KB 주택가격동향", "https://kbland.kr/map", "KB 시세·매매·전세 지수"),
        ("🗺️ 호갱노노", "https://hogangnono.com", "단지별 실거래 흐름·인구·학군 정보"),
        ("📈 아실 (아파트실거래가)", "https://asil.kr", "시세 변동·갭투자 분석"),
        ("🏘️ 부동산 플래닛", "https://www.bdsplanet.com", "토지·건물 실거래 및 수익률 분석"),
    ]
    for name, url, desc in info_rows:
        st.markdown(f"- [{name}]({url}) — {desc}")


# ── 관심주식 사용자 인증 / 영구 저장 헬퍼 ─────────────────────────────
import hashlib as _hashlib

def _fmt_index_metric(v: Any) -> str:
    """지수 카드용 — NaN/None 은 '-' 로 (Streamlit metric에 'nan' 문자 노출 방지)."""
    if v is None:
        return "-"
    try:
        x = float(v)
        if not math.isfinite(x):
            return "-"
        return f"{x:,.2f}"
    except (TypeError, ValueError):
        return "-"


# 빠른 로그인 슬롯 (아이디 user_a/user_d/user_e/user_f · 공통 기본 비밀번호)
_WL_PRESET_SLOT_PW = "wl2026"
_WL_PRESET_USERS: tuple[tuple[str, str], ...] = (
    ("user_a", "A · 준(본인)"),
    ("user_d", "D · 공용"),
    ("user_e", "E · 공용"),
    ("user_f", "F · 공용"),
)


def _wl_ensure_preset_users(here: Path) -> None:
    """user_a~f 가 없으면 기본 비밀번호로 생성(기존 aaa 등은 유지)."""
    data = _wl_load(here)
    users = data.setdefault("users", {})
    hpw = _wl_hash(_WL_PRESET_SLOT_PW)
    changed = False
    for uid, _lbl in _WL_PRESET_USERS:
        if uid not in users:
            users[uid] = {"pw": hpw, "tickers": []}
            changed = True
    if changed:
        _wl_save(here, data)


def _wl_users_path(here: Path) -> Path:
    d = here / "watchlist_data"
    d.mkdir(parents=True, exist_ok=True)
    return d / "users.json"

def _wl_hash(pw: str) -> str:
    return _hashlib.sha256(pw.encode("utf-8")).hexdigest()

def _wl_load(here: Path) -> dict:
    p = _wl_users_path(here)
    if not p.exists():
        # 기본 계정(aaa/bbb) 포함해 초기화
        data = {"users": {"aaa": {"pw": _wl_hash("bbb"), "tickers": ["005930.KS", "AAPL", "TSLA"]}}}
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return data
    try:
        with open(p, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}

def _wl_save(here: Path, data: dict) -> None:
    p = _wl_users_path(here)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def _wl_login(here: Path, uid: str, pw: str) -> bool:
    data = _wl_load(here)
    user = data["users"].get(uid)
    return user is not None and user.get("pw") == _wl_hash(pw)

def _wl_register(here: Path, uid: str, pw: str) -> tuple[bool, str]:
    if not uid.strip():
        return False, "아이디를 입력하세요."
    if not pw.strip():
        return False, "비밀번호를 입력하세요."
    if len(uid) < 2:
        return False, "아이디는 2자 이상이어야 합니다."
    data = _wl_load(here)
    if uid in data["users"]:
        return False, "이미 존재하는 아이디입니다."
    data["users"][uid] = {"pw": _wl_hash(pw), "tickers": []}
    _wl_save(here, data)
    return True, "가입 완료!"


def _wl_upsert_quick_label(here: Path, uid: str, quick_label: str) -> None:
    data = _wl_load(here)
    users = data.setdefault("users", {})
    if uid in users:
        users[uid]["quick_label"] = quick_label
        _wl_save(here, data)


def _wl_collect_quick_accounts(here: Path) -> list[tuple[str, str]]:
    """빠른 로그인 버튼 목록(프리셋 + 사용자 추가 슬롯)."""
    quick: list[tuple[str, str]] = list(_WL_PRESET_USERS)
    data = _wl_load(here)
    users = data.get("users", {})
    for uid, info in users.items():
        if uid in {x[0] for x in _WL_PRESET_USERS}:
            continue
        ql = str((info or {}).get("quick_label") or "").strip()
        if ql:
            quick.append((uid, ql))
    return quick


def _wl_next_quick_prefix(here: Path) -> str:
    used: set[str] = set()
    for _uid, label in _wl_collect_quick_accounts(here):
        first = label.strip()[:1].upper()
        if first and "A" <= first <= "Z":
            used.add(first)
    for code in range(ord("A"), ord("Z") + 1):
        c = chr(code)
        if c not in used:
            return c
    return "N"

def _wl_get_tickers(here: Path, uid: str) -> list[str]:
    data = _wl_load(here)
    return list(data["users"].get(uid, {}).get("tickers", []))

def _wl_set_tickers(here: Path, uid: str, tickers: list[str]) -> None:
    data = _wl_load(here)
    if uid in data["users"]:
        data["users"][uid]["tickers"] = tickers
        _wl_save(here, data)


def _wl_ensure_watchlist_session(here: Path, uid: str) -> None:
    if "stk_watchlist" not in st.session_state:
        st.session_state["stk_watchlist"] = _wl_get_tickers(here, uid)


def _wl_add_ticker(here: Path, uid: str, raw_ticker: str) -> tuple[bool, str]:
    t = (raw_ticker or "").strip().upper()
    if not t:
        return False, "티커가 비어 있습니다."
    data = _wl_load(here)
    if uid not in data.get("users", {}):
        return False, "로그인 정보를 다시 확인하세요."
    cur = list(data["users"][uid].get("tickers", []))
    cur_u = [str(x).strip().upper() for x in cur]
    if t in cur_u:
        return False, "이미 관심 목록에 있습니다."
    cur.append(t)
    data["users"][uid]["tickers"] = cur
    _wl_save(here, data)
    if st.session_state.get("wl_user") == uid:
        st.session_state["stk_watchlist"] = cur
    return True, f"{t} 관심에 추가했습니다."


def _wl_remove_ticker(here: Path, uid: str, raw_ticker: str) -> tuple[bool, str]:
    t = (raw_ticker or "").strip().upper()
    if not t:
        return False, "티커가 비어 있습니다."
    data = _wl_load(here)
    if uid not in data.get("users", {}):
        return False, "로그인 정보를 다시 확인하세요."
    cur = list(data["users"][uid].get("tickers", []))
    cur_u = [str(x).strip().upper() for x in cur]
    if t not in cur_u:
        return False, "관심 목록에 없습니다."
    new_cur = [x for x in cur if str(x).strip().upper() != t]
    data["users"][uid]["tickers"] = new_cur
    _wl_save(here, data)
    if st.session_state.get("wl_user") == uid:
        st.session_state["stk_watchlist"] = new_cur
    return True, f"{t} 관심에서 제거했습니다."


def _wl_remove_at(here: Path, uid: str, index: int) -> None:
    cur = list(_wl_get_tickers(here, uid))
    if 0 <= index < len(cur):
        cur.pop(index)
        data = _wl_load(here)
        if uid in data.get("users", {}):
            data["users"][uid]["tickers"] = cur
            _wl_save(here, data)
        st.session_state["stk_watchlist"] = cur


@st.cache_data(ttl=600, show_spinner=False)
def _wl_yf_series_3mo(ticker: str) -> dict[str, Any]:
    """3개월 일봉 기준 이름·종가·누적수익률 시리즈."""
    empty: dict[str, Any] = {
        "ok": False, "name": "", "dates": [], "closes": [], "norm_pct": [],
        "last": None, "prev_close": None, "d1_pct": None, "period_pct": None,
    }
    if yf is None:
        return empty
    try:
        hist = yf.download(
            ticker, period="3mo", interval="1d", progress=False, auto_adjust=True,
        )
        if hist is None or hist.empty:
            return empty
        c = hist["Close"]
        if hasattr(c, "squeeze"):
            c = c.squeeze()
        closes = [float(x) for x in c.tolist()]
        dates = [str(d)[:10] for d in c.index.tolist()]
        tk = yf.Ticker(ticker)
        info = tk.fast_info
        name = ""
        try:
            inf = tk.info or {}
            name = str(inf.get("shortName") or inf.get("longName") or "").strip()
        except Exception:
            name = ""
        if not name:
            name = ticker
        last = float(closes[-1]) if closes else None
        prev = getattr(info, "previous_close", None)
        if prev is None and len(closes) >= 2:
            prev = float(closes[-2])
        period_pct = None
        if closes and closes[0]:
            period_pct = (closes[-1] / closes[0] - 1.0) * 100.0
        d1_pct = None
        if last is not None and prev:
            try:
                d1_pct = (last / float(prev) - 1.0) * 100.0
            except (TypeError, ValueError, ZeroDivisionError):
                d1_pct = None
        norm_pct: list[float] = []
        if closes and closes[0]:
            first = closes[0]
            norm_pct = [(cl / first - 1.0) * 100.0 for cl in closes]
        return {
            "ok": True,
            "name": name,
            "dates": dates,
            "closes": closes,
            "norm_pct": norm_pct,
            "last": last,
            "prev_close": float(prev) if prev is not None else None,
            "d1_pct": d1_pct,
            "period_pct": period_pct,
        }
    except Exception:
        return empty


def _wl_render_watch_star_grid(
    here: Path,
    uid: str,
    rows: list[dict],
    *,
    cols_step: int = 3,
    key_fn: Any,
    show_intro: bool = True,
) -> None:
    """코스피·코스닥 순위 / 오늘의 픽 공통: 접는 ⭐ 관심 칩 그리드(3열, 모바일 친화)."""
    if not rows:
        return
    wl_set = {str(x).strip().upper() for x in _wl_get_tickers(here, uid)}
    step = max(3, min(int(cols_step), 6))

    def _render_rows() -> None:
        if show_intro:
            st.caption("⭐ 추가 · ★ 담김(한 번 더 누르면 제거)")
        for row_start in range(0, len(rows), step):
            chunk = rows[row_start : row_start + step]
            try:
                gcols = st.columns(step, gap="small")
            except TypeError:
                gcols = st.columns(step)
            for j in range(step):
                with gcols[j]:
                    if j >= len(chunk):
                        continue
                    m = chunk[j]
                    i = row_start + j
                    t_raw = str(m.get("ticker") or "").strip()
                    if not t_raw:
                        st.caption("—")
                        continue
                    t_key = t_raw.upper()
                    nm = str(m.get("name") or "").strip()
                    sym = t_raw.split(".")[0] if "." in t_raw else t_raw
                    # 칩용 짧은 라벨 (한 줄·좁은 열)
                    nm_chip = ((nm[:4] if nm else sym) or sym)[:5]
                    in_wl = t_key in wl_set
                    btn_lbl = f"★ {nm_chip}" if in_wl else f"⭐ {nm_chip}"
                    h = (
                        f"{nm} · {t_raw} — 클릭 시 관심에서 제거"
                        if in_wl
                        else f"{nm} · {t_raw} — 클릭 시 관심에 추가"
                    )
                    if st.button(
                        btn_lbl,
                        key=key_fn(i, m),
                        help=h,
                        type="primary" if in_wl else "secondary",
                        use_container_width=True,
                    ):
                        if in_wl:
                            ok, msg = _wl_remove_ticker(here, uid, t_raw)
                        else:
                            ok, msg = _wl_add_ticker(here, uid, t_raw)
                        if ok:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.warning(msg)

    if show_intro:
        with st.expander("⭐ 관심에 담기", expanded=False):
            _render_rows()
    else:
        _render_rows()


def _wl_render_pick_quick_add(here: Path, matches: list[dict], bucket_key: str) -> None:
    """오늘의 픽 각 버킷 하단 — 원클릭 관심."""
    uid = st.session_state.get("wl_user")
    if not matches:
        return
    if not uid:
        st.caption("**관심주식**에서 로그인하면 여기서도 바로 담을 수 있습니다.")
        return
    _wl_ensure_watchlist_session(here, uid)
    st.caption("아래는 위 표와 **위에서부터 같은 순서**입니다.")
    _wl_render_watch_star_grid(
        here,
        uid,
        matches,
        key_fn=lambda i, m, bk=bucket_key: f"wlpk_{bk}_{i}_{str(m.get('ticker') or '').strip()}",
    )


def _render_tab_stock_watchlist() -> None:
    """관심 주식 — 사용자별 영구 저장 워치리스트"""
    st.header("관심 주식")

    here = Path(__file__).resolve().parent

    # ── 로그인 상태 확인 ────────────────────────────────────────
    logged_in_user: str | None = st.session_state.get("wl_user")

    if not logged_in_user:
        st.caption("관심 종목은 로그인 후 저장됩니다.")

        with _st_try_border_container():
            st.markdown(f"""
> **안내**  
> 테스트 계정: 아이디 `aaa` / 비밀번호 `bbb`  
> 상단 **{_WL_NAV_LOGIN}** / **{_WL_NAV_REGISTER}** 에서도 동일 화면을 쓸 수 있습니다.  
> 아래 탭에서도 입력할 수 있습니다.
""")

        tab_login, tab_reg = st.tabs([_WL_NAV_LOGIN, _WL_NAV_REGISTER])

        with tab_login:
            _wl_render_login_form(here)

        with tab_reg:
            _wl_render_register_form(here)
        return  # 로그인 전이면 여기서 종료

    if yf is None:
        st.warning("yfinance 라이브러리가 없어 시세를 불러올 수 없습니다.")
        return

    # ── 로그인 완료: 워치리스트 화면 ─────────────────────────────
    col_title, col_logout = st.columns([4, 1])
    with col_title:
        st.caption(f"**{logged_in_user}** 님의 관심 종목 · 새로고침해도 저장됩니다.")
    with col_logout:
        if st.button("로그아웃", key="wl_logout"):
            del st.session_state["wl_user"]
            st.session_state.pop("stk_watchlist", None)
            st.rerun()

    # session_state 초기화 (최초 로그인 후)
    if "stk_watchlist" not in st.session_state:
        st.session_state["stk_watchlist"] = _wl_get_tickers(here, logged_in_user)

    _wl_ensure_watchlist_session(here, logged_in_user)

    st.markdown(
        "**오늘의 픽** · **코스피/코스닥 스캐너** 표 아래 **⭐** 로 추가, **★** 를 다시 누르면 제거됩니다. "
        "또는 아래에서 티커를 직접 넣을 수 있습니다."
    )
    _weinstein_tip_caption(salt="watchlist_logged_in")

    with _st_try_border_container():
        st.subheader("티커 직접 추가")
        st.caption("Yahoo Finance 형식 예: `005930.KS`, `247540.KQ`, `AAPL`")
        row_a, row_b = st.columns([5, 1])
        with row_a:
            st.text_input(
                "티커",
                key="wl_manual_ticker",
                placeholder="005930.KS",
                label_visibility="collapsed",
            )
        with row_b:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("추가", key="wl_manual_add", type="primary", use_container_width=True):
                mv = str(st.session_state.get("wl_manual_ticker", "")).strip()
                ok, msg = _wl_add_ticker(here, logged_in_user, mv)
                if ok:
                    st.session_state["wl_manual_ticker"] = ""
                    st.success(msg)
                    st.rerun()
                else:
                    st.warning(msg)

    tickers = list(st.session_state["stk_watchlist"])
    if not tickers:
        st.info(
            "아직 관심 종목이 없습니다.\n\n"
            "· **오늘의 픽** 또는 **코스피 스캐너** / **코스닥 스캐너** 로 이동한 뒤, "
            "표 아래 **⭐ 관심에 담기** 버튼을 눌러 보세요.\n\n"
            "아래에는 **비교용**으로 코스피·코스닥 지수 수익률을 기본 표시합니다."
        )

    st.divider()
    st.subheader("3개월 누적 수익률 (각 종목·지수 첫 거래일 종가 = 0%)")
    st.caption(
        "회색 점선·점점선은 **코스피(^KS11)**·**코스닥(^KQ11)** 벤치입니다. "
        "같은 기간·같은 Y축으로 비교합니다. 출처: yfinance 일봉(자동 조정 종가)."
    )

    panels: list[tuple[str, dict[str, Any]]] = []
    with st.spinner("시세·차트 데이터 불러오는 중…"):
        bench_ks = _wl_yf_series_3mo("^KS11")
        bench_kq = _wl_yf_series_3mo("^KQ11")
        for t in tickers:
            panels.append((t, _wl_yf_series_3mo(t)))

    if go is not None:
        fig_cmp = go.Figure()
        for label, bench, color, dash in (
            ("코스피 ^KS11", bench_ks, "#64748b", "dash"),
            ("코스닥 ^KQ11", bench_kq, "#94a3b8", "dot"),
        ):
            if bench.get("ok") and bench.get("dates"):
                fig_cmp.add_trace(
                    go.Scatter(
                        x=bench["dates"],
                        y=bench["norm_pct"],
                        name=label,
                        mode="lines",
                        line=dict(color=color, width=2, dash=dash),
                        hovertemplate=f"{label}<br>%{{x}}<br>%{{y:.2f}}%<extra></extra>",
                    )
                )
        palette = [
            "#60a5fa", "#34d399", "#fbbf24", "#f472b6", "#a78bfa",
            "#fb923c", "#38bdf8", "#4ade80", "#facc15", "#fda4af",
            "#c084fc", "#22d3ee",
        ]
        n_bench = len(fig_cmp.data)
        for i, (t, p) in enumerate(panels):
            if not p.get("ok") or not p.get("dates"):
                continue
            nm = str(p.get("name") or t)[:18]
            fig_cmp.add_trace(
                go.Scatter(
                    x=p["dates"],
                    y=p["norm_pct"],
                    name=nm,
                    mode="lines",
                    line=dict(color=palette[(n_bench + i) % len(palette)], width=2),
                    hovertemplate=f"{nm}<br>%{{x}}<br>%{{y:.2f}}%<extra></extra>",
                )
            )
        if fig_cmp.data:
            fig_cmp.update_layout(
                xaxis_title="일자",
                yaxis_title="누적 수익률 (%)",
                height=460,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0),
                margin=dict(t=24, b=48),
                hovermode="x unified",
            )
            st.plotly_chart(fig_cmp, use_container_width=True)
        else:
            st.warning("차트용 데이터를 가져오지 못했습니다. 네트워크·티커를 확인하세요.")
    else:
        st.warning("plotly 가 없어 통합 차트를 생략합니다.")

    st.subheader("요약 표")
    table_rows: list[dict[str, Any]] = []

    def _wl_summary_row(label: str, sym: str, p: dict[str, Any]) -> dict[str, Any]:
        d1 = p.get("d1_pct")
        p3 = p.get("period_pct")
        last_v = p.get("last")
        return {
            "종목": label,
            "티커": sym,
            "현재가": f"{float(last_v):,.2f}" if last_v is not None else "—",
            "전일대비": f"{float(d1):+.2f}%" if d1 is not None else "—",
            "3M 누적": f"{float(p3):+.2f}%" if p3 is not None else "—",
        }

    if bench_ks.get("ok"):
        table_rows.append(_wl_summary_row("코스피 지수", "^KS11", bench_ks))
    if bench_kq.get("ok"):
        table_rows.append(_wl_summary_row("코스닥 지수", "^KQ11", bench_kq))
    for t, p in panels:
        table_rows.append(_wl_summary_row(str(p.get("name") or t), t, p))
    if pd is not None:
        _st_dataframe_all_rows(pd.DataFrame(table_rows))
    else:
        st.table(table_rows)

    if tickers:
        st.subheader("목록에서 제거")
        del_cols = st.columns(min(len(tickers), 6))
        for i, t in enumerate(tickers):
            p = panels[i][1]
            nm = str(p.get("name") or t)[:10]
            with del_cols[i % len(del_cols)]:
                if st.button(f"삭제 · {nm}", key=f"wl_del_{i}", use_container_width=True):
                    _wl_remove_at(here, logged_in_user, i)
                    st.rerun()


def _scanner_payload_matches(payload: dict | None) -> list[dict[str, Any]]:
    if not payload:
        return []
    return list(payload.get("top_table") or payload.get("matches") or [])


def _load_scanner_results(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _universe_meta_cache_updated_at(app_root: Path | None) -> str:
    """`collector_hourly`가 쓰는 공용 일봉 캐시 메타 시각 (tema_cache_data/cache/universe_meta.json)."""
    if app_root is None:
        return ""
    p = app_root / "tema_cache_data" / "cache" / "universe_meta.json"
    try:
        if not p.is_file():
            return ""
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        if not isinstance(d, dict):
            return ""
        v = d.get("updated_at")
        s = str(v).strip() if v is not None else ""
        if s and s not in ("—", "-", "None", "null"):
            return s
    except Exception:
        pass
    return ""


def _scanner_freshest_display_time(payload: dict | None, *, app_root: Path | None = None) -> str:
    """Stage2 전체 스캔 시각, results_web의 캐시필드, 공용 universe_meta 중 가장 늦은 KST 문자열."""
    raw: list[str] = []
    if isinstance(payload, dict):
        for k in ("last_analysis_time", "universe_cache_updated_at"):
            v = payload.get(k)
            if v is None:
                continue
            s = str(v).strip()
            if s and s not in ("—", "-", "None", "null"):
                raw.append(s)
    um = _universe_meta_cache_updated_at(app_root)
    if um:
        raw.append(um)
    if not raw:
        return "—"
    best_s: str | None = None
    best_dt: datetime | None = None
    for s in raw:
        try:
            dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=KST)
        except ValueError:
            continue
        if best_dt is None or dt > best_dt:
            best_dt = dt
            best_s = s
    return best_s or raw[0]


def _merge_kospi_kosdaq_matches(
    here: Path,
) -> tuple[list[dict[str, Any]], str, str, dict[str, Any] | None, dict[str, Any] | None]:
    pk = _load_scanner_results(here / "kospi_data" / "results_web.json")
    qk = _load_scanner_results(here / "kosdaq_data" / "results_web.json")
    out: list[dict[str, Any]] = []
    for m in _scanner_payload_matches(pk):
        mm = dict(m)
        mm["market"] = "코스피"
        out.append(mm)
    for m in _scanner_payload_matches(qk):
        mm = dict(m)
        mm["market"] = "코스닥"
        out.append(mm)
    kt = _scanner_freshest_display_time(pk, app_root=here)
    qt = _scanner_freshest_display_time(qk, app_root=here)
    return out, str(kt), str(qt), pk, qk


def _bars_since_stage2(m: dict[str, Any]) -> int:
    v = m.get("bars_since_stage2_entry")
    try:
        return int(v) if v is not None else 10_000
    except (TypeError, ValueError):
        return 10_000


def _score_match(m: dict[str, Any]) -> float:
    try:
        return float(m.get("score") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _daily_pick_rank_delta_1d_int(m: dict[str, Any]) -> int:
    """Δ1d를 대략 정수로(순위 개선=양수). 수급·관심 프록시로 장투 탭 정렬에 사용."""
    s = str(m.get("rank_delta_1d", "") or "").strip()
    if not s or s in ("—", "-", "None", "null"):
        return 0
    try:
        return int(float(s))
    except (TypeError, ValueError):
        pass
    if s.startswith("+"):
        try:
            return int(float(s[1:]))
        except (TypeError, ValueError):
            return 0
    if s.startswith("-"):
        try:
            return -int(float(s[1:]))
        except (TypeError, ValueError):
            return 0
    return 0


def _ret_since_stage2_pct(m: dict[str, Any]) -> float:
    v = m.get("ret_since_entry_pct")
    if v is not None:
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    try:
        return float(m.get("ret_3m_pct") or 0)
    except (TypeError, ValueError):
        return 0.0


def _daily_pick_disparity_pct(m: dict[str, Any], days: int) -> float | None:
    """
    20/50일 이격도(%): (현재가 / MA - 1) * 100
    - 결과 JSON 키가 있으면 우선 사용
    - 없으면 close/ma 값으로 계산 시도
    """
    key_map = {
        20: ("dist_ma20_pct", "disparity_20_pct", "close_vs_ma20_pct", "price_to_ma20_pct", "pct_from_ma20"),
        50: ("dist_ma50_pct", "disparity_50_pct", "close_vs_ma50_pct", "price_to_ma50_pct", "pct_from_ma50"),
    }
    ma_key_map = {
        20: ("ma20", "MA20", "sma20"),
        50: ("ma50", "MA50", "sma50"),
    }
    for k in key_map.get(days, ()):
        v = m.get(k)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            pass
    close_v = None
    for ck in ("close", "last_close", "close_price"):
        cv = m.get(ck)
        if cv is None:
            continue
        try:
            close_v = float(cv)
            break
        except (TypeError, ValueError):
            continue
    ma_v = None
    for mk in ma_key_map.get(days, ()):
        mv = m.get(mk)
        if mv is None:
            continue
        try:
            ma_v = float(mv)
            break
        except (TypeError, ValueError):
            continue
    if close_v is None or ma_v is None or ma_v == 0:
        return None
    return (close_v / ma_v - 1.0) * 100.0


def _daily_pick_overbought_ok(m: dict[str, Any]) -> bool | None:
    """
    점수가 높은 종목(>=85) 중 과열(20/50 이격도) 여부 체크.
    - 기준: d20 <= +8%, d50 <= +15%
    - 이격도 데이터가 없으면 None
    """
    if _score_match(m) < 85:
        return None
    d20 = _daily_pick_disparity_pct(m, 20)
    d50 = _daily_pick_disparity_pct(m, 50)
    if d20 is None and d50 is None:
        return None
    ok20 = True if d20 is None else (d20 <= 8.0)
    ok50 = True if d50 is None else (d50 <= 15.0)
    return bool(ok20 and ok50)


def _daily_pick_stage2_status(m: dict[str, Any]) -> str:
    """
    초기2단계(비과열) 상태 라벨:
    - 초기: bars_since_stage2_entry <= 20
    - 과열: 20일이격 >= +20% 또는 50일이격 >= +30%
    """
    b = _bars_since_stage2(m)
    d20 = _daily_pick_disparity_pct(m, 20)
    d50 = _daily_pick_disparity_pct(m, 50)
    is_initial = b <= 20
    is_overheated = bool(
        (d20 is not None and d20 >= 20.0) or
        (d50 is not None and d50 >= 30.0)
    )
    if is_initial and is_overheated:
        return "초기·과열"
    if is_initial and not is_overheated:
        return "초기·비과열"
    if (d20 is not None) or (d50 is not None):
        return "일반"
    return "—"


def _classify_daily_pick_buckets(matches: list[dict[str, Any]], *, n: int = 12) -> dict[str, list[dict[str, Any]]]:
    """
    단타·스윙·장투 — 사용자 매매 스타일(짧게 2~3일 / 추세 전체 / 수개월+눌림)에 맞춘 휴리스틱.

    - **버킷 사이**: 동일 티커가 **여러 탭에 동시에** 올 수 있음(의도적 중복·시나리오 분할용).
    - **버킷 안**: 티커 중복 없이 최대 ``n``개.

    일봉 스캔만 있으므로 「2~3일」은 **진입 후 거래일 수(bars)** 로 근사합니다.
    """
    pool = sorted(matches, key=_score_match, reverse=True)

    def br(m: dict[str, Any]) -> int:
        return _bars_since_stage2(m)

    def _ob_bonus(m: dict[str, Any]) -> int:
        """고점수 + 비과열(20/50 이격도)면 가점."""
        return 1 if _daily_pick_overbought_ok(m) is True else 0

    def _parse_delta(m: dict[str, Any], key: str) -> int:
        """rank_delta 문자열을 정수로 파싱. 순위 상승=양수, 하락=음수, 없음=0."""
        s = str(m.get(key, "") or "").strip()
        if not s or s in ("—", "-", "None", "null"):
            return 0
        try:
            return int(float(s))
        except (TypeError, ValueError):
            return 0

    def _swing_sort_key(m: dict[str, Any]) -> float:
        """점수 + Δ가점(1일*0.5 + 3일*0.3 + 6일*0.2). 순위가 올라올수록 높아짐."""
        d1 = _parse_delta(m, "rank_delta_1d")
        d3 = _parse_delta(m, "rank_delta_3d")
        d6 = _parse_delta(m, "rank_delta_6d")
        delta_bonus = d1 * 0.5 + d3 * 0.3 + d6 * 0.2
        return _score_match(m) + delta_bonus

    def _uniq_best(pred: Any, *, sort_key: Any, reverse: bool = True) -> list[dict[str, Any]]:
        cand = [m for m in pool if pred(m)]
        cand.sort(key=sort_key, reverse=reverse)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for m in cand:
            t = str(m.get("ticker") or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(m)
            if len(out) >= n:
                break
        return out

    # 단타: 2~3일~수일 보유 — Stage2 **초입** + 짧은 구간 + (겹침) 고점수 초기
    pred_day = lambda m: (
        br(m) <= 6
        or br(m) <= 18
        or (br(m) <= 28 and _score_match(m) >= 95)
    )
    daytrade = _uniq_best(pred_day, sort_key=lambda m: (_ob_bonus(m), _score_match(m)))
    if not daytrade:
        daytrade = pool[:n]

    # 스윙: 코스피 상위 50개·코스닥 상위 30개 풀에서 Δ가점 반영 정렬 후 합산
    def _uniq_best_from(src: list[dict[str, Any]], pred: Any, *, max_n: int) -> list[dict[str, Any]]:
        """src 리스트 안에서 pred 통과 종목을 _swing_sort_key 내림차순으로 최대 max_n개."""
        cand = [m for m in src if pred(m)]
        cand.sort(key=lambda m: (_ob_bonus(m), _swing_sort_key(m)), reverse=True)
        seen: set[str] = set()
        out: list[dict[str, Any]] = []
        for m in cand:
            t = str(m.get("ticker") or "").strip()
            if not t or t in seen:
                continue
            seen.add(t)
            out.append(m)
            if len(out) >= max_n:
                break
        return out

    pred_swing = lambda m: 3 <= br(m) <= 110

    # 코스피/코스닥 분리 후 각각 점수 상위로 먼저 자름
    kospi_pool = sorted(
        [m for m in pool if str(m.get("market", "")) == "코스피"],
        key=_score_match, reverse=True
    )[:50]
    kosdaq_pool = sorted(
        [m for m in pool if str(m.get("market", "")) == "코스닥"],
        key=_score_match, reverse=True
    )[:50]

    # 각 풀에서 Δ가점 반영 정렬로 스윙 후보 추출 (합계 최대 n개)
    n_kospi = max(1, round(n * 50 / 100))  # 약 6개
    n_kosdaq = max(1, n - n_kospi)  # 약 6개
    swing_kospi = _uniq_best_from(kospi_pool, pred_swing, max_n=n_kospi)
    swing_kosdaq = _uniq_best_from(kosdaq_pool, pred_swing, max_n=n_kosdaq)

    # 합산 후 Δ가점 기준으로 최종 재정렬
    swing = sorted(
        swing_kospi + swing_kosdaq,
        key=lambda m: (_ob_bonus(m), _swing_sort_key(m)),
        reverse=True
    )[:n]

    # 후보 부족 시 기존 방식으로 폴백
    if not swing:
        swing = pool[: min(n, len(pool))]

    # 장투: 수개월·눌림 — 진입 **오래됨** + 점수 버팀 + Δ1d 급락 아님(대략 수급 프록시)
    def pred_lt(m: dict[str, Any]) -> bool:
        b = br(m)
        sc = _score_match(m)
        rs = _ret_since_stage2_pct(m)
        d1 = _daily_pick_rank_delta_1d_int(m)
        if b >= 45:
            return d1 >= -12
        if b >= 28 and sc >= 85:
            return rs >= -12.0 and d1 >= -15
        if b >= 20 and sc >= 95:
            return rs >= -18.0 and d1 >= -18
        return False

    def sort_lt(m: dict[str, Any]) -> tuple[int, float, int]:
        return (br(m), _score_match(m), _daily_pick_rank_delta_1d_int(m))

    longterm = _uniq_best(pred_lt, sort_key=sort_lt, reverse=True)
    if not longterm:
        tail = sorted(pool, key=br, reverse=True)[: max(n * 2, n)]
        longterm = _uniq_best(lambda m: m in tail, sort_key=sort_lt, reverse=True)
    if not longterm:
        longterm = sorted(pool, key=lambda m: (br(m), _score_match(m)), reverse=True)[:n]
    return {"daytrade": daytrade, "swing": swing, "longterm": longterm}


def _pick_minimal_record(m: dict[str, Any]) -> dict[str, Any]:
    close_v = m.get("close")
    try:
        close_v = float(close_v) if close_v is not None else None
    except (TypeError, ValueError):
        close_v = None
    return {
        "ticker": m.get("ticker", "") or "",
        "name": m.get("name", "") or "",
        "market": m.get("market", "") or "",
        "score": round(_score_match(m), 2),
        "bars": _bars_since_stage2(m),
        "close": close_v,
    }


_JOURNAL_FILE = "daily_stock_journal.json"
_JOURNAL_CAP = 45


def _daily_pick_journal_path(here: Path) -> Path:
    return here / _JOURNAL_FILE


def _journal_load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {"entries": []}
    try:
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        if isinstance(d, dict) and isinstance(d.get("entries"), list):
            return d
    except Exception:
        pass
    return {"entries": []}


def _journal_save(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def _journal_upsert_today(path: Path, today: str, picks: dict[str, list[dict[str, Any]]]) -> None:
    data = _journal_load(path)
    ent = [e for e in data["entries"] if e.get("date") != today]
    slim: dict[str, list[dict[str, Any]]] = {
        k: [_pick_minimal_record(m) for m in v] for k, v in picks.items()
    }
    ent.append({"date": today, "picks": slim})
    ent.sort(key=lambda e: str(e.get("date", "")))
    if len(ent) > _JOURNAL_CAP:
        ent = ent[-_JOURNAL_CAP:]
    data["entries"] = ent
    _journal_save(path, data)


def _journal_find_yesterday(entries: list[dict[str, Any]], today: str) -> dict[str, Any] | None:
    try:
        td = date.fromisoformat(today)
    except ValueError:
        return None
    y = (td - timedelta(days=1)).isoformat()
    for e in reversed(entries):
        if e.get("date") == y:
            return e
    best: dict[str, Any] | None = None
    for e in entries:
        d = str(e.get("date") or "")
        if not d or d >= today:
            continue
        if best is None or d > str(best.get("date") or ""):
            best = e
    return best


def _ticker_index(matches: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for m in matches:
        t = m.get("ticker")
        if t:
            out[str(t)] = m
    return out


def _fmt_ret_since(m: dict[str, Any], strategy: str = "longterm") -> str:
    if strategy == "daytrade":
        v = m.get("ret_daytrade_pct")
    elif strategy == "swing":
        v = m.get("ret_swing_pct")
    else:
        v = m.get("ret_since_entry_pct")
    if v is not None:
        try:
            return f"{float(v):+.1f}%"
        except (TypeError, ValueError):
            pass
    try:
        return f'{float(m.get("ret_3m_pct") or 0):+.1f}%'
    except (TypeError, ValueError):
        return "—"


def _render_tab_daily_stock_picks() -> None:
    """오늘의 픽 — 단타·스윙·장투 구분 + 어제 픽 복기(로컬 저널)."""
    # ── 헤더 ────────────────────────────────────────────────
    st.header("오늘의 픽")
    st.caption("시장→섹터→종목 순서로 확인 · Stage2 종목만 추출 · 참고용")

    here = Path(__file__).resolve().parent
    matches, kt, qt, pk, qk = _merge_kospi_kosdaq_matches(here)
    if not matches:
        st.warning("스캔 결과가 없습니다. 코스피·코스닥 스캐너에서 먼저 분석하세요.")
        return

    today_kst = datetime.now(KST).date().isoformat()
    buckets = _classify_daily_pick_buckets(matches, n=12)
    _journal_upsert_today(_daily_pick_journal_path(here), today_kst, buckets)
    st.caption(f"코스피 분석: **{kt}** · 코스닥 분석: **{qt}**")

    # ── 공통 헬퍼 ────────────────────────────────────────────
    def _ret_color(v: str) -> str:
        try:
            x = float(str(v).replace("%", "").replace("+", ""))
            if x >= 10.0:
                return "#15803d"
            if x >= 3.0:
                return "#166534"
            if x >= 0.0:
                return "#374151"
            if x >= -5.0:
                return "#991b1b"
            return "#b91c1c"
        except (TypeError, ValueError):
            return "#94a3b8"

    def _delta_color(v: str) -> str:
        try:
            x = float(str(v).replace("+", ""))
            if x > 0:
                return "#15803d"
            if x < 0:
                return "#b91c1c"
            return "#64748b"
        except (TypeError, ValueError):
            return "#94a3b8"

    def _disp_color(v: str) -> str:
        """20일 이격 색상: 0~8% 초록, 9~15% 주황, 16%+ 빨강."""
        try:
            x = float(str(v).replace("%", "").replace("+", ""))
            if x <= 8.0:
                return "#15803d"
            if x <= 15.0:
                return "#b45309"
            return "#b91c1c"
        except (TypeError, ValueError):
            return "#64748b"

    def _highlight_cards(lst: list[dict[str, Any]], strategy: str) -> None:
        """상위 3개 하이라이트 카드."""
        top3 = lst[:3]
        if not top3:
            return
        cols = st.columns(len(top3))
        for col, m in zip(cols, top3):
            name = m.get("name", "")
            market = m.get("market", "")
            score = round(_score_match(m), 1)
            ret = _fmt_ret_since(m, strategy)
            d1 = str(m.get("rank_delta_1d", "—") or "—")
            d3 = str(m.get("rank_delta_3d", "—") or "—")
            d6 = str(m.get("rank_delta_6d", "—") or "—")
            bars = _bars_since_stage2(m)
            bars_txt = f"{bars}일" if bars < 10_000 else "—"
            d20 = _daily_pick_disparity_pct(m, 20)
            d20_txt = f"{float(d20):+.1f}%" if d20 is not None else "—"
            col.markdown(
                f"""<div style="border:1px solid #e2e8f0;border-radius:10px;
                    padding:0.6rem 0.75rem;background:#f8fafc;margin-bottom:0.3rem;">
                  <div style="font-size:0.82rem;font-weight:700;color:#0f172a;
                      white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name}</div>
                  <div style="font-size:0.68rem;color:#64748b;margin-bottom:0.2rem;">
                      {market} · {score}점 · 진입 {bars_txt}</div>
                  <div style="font-size:1.0rem;font-weight:800;color:{_ret_color(ret)};">{ret}</div>
                  <div style="font-size:0.65rem;color:{_disp_color(d20_txt)};margin-top:0.1rem;">
                      20일이격 {d20_txt}</div>
                  <div style="font-size:0.65rem;margin-top:0.1rem;">
                      <span style="color:{_delta_color(d1)};">Δ1d {d1}</span>
                      &nbsp;<span style="color:{_delta_color(d3)};">Δ3d {d3}</span>
                      &nbsp;<span style="color:{_delta_color(d6)};">Δ6d {d6}</span>
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )

    def _pick_table(lst: list[dict[str, Any]], strategy: str) -> None:
        """핵심 컬럼 테이블 + 수익률·Δ·이격 색상 강조."""
        if not lst:
            st.info("후보가 없습니다. 스캐너에서 먼저 분석하세요.")
            return
        import pandas as _pd_pick

        rows = []
        for i, m in enumerate(lst, 1):
            d20 = _daily_pick_disparity_pct(m, 20)
            if strategy == "daytrade":
                entry = m.get("entry_daytrade") or m.get("entry", "") or "—"
            elif strategy == "swing":
                entry = m.get("entry_swing") or m.get("entry", "") or "—"
            else:
                entry = m.get("entry", "") or "—"
            rows.append({
                "#": i,
                "종목": m.get("name", ""),
                "시장": m.get("market", ""),
                "점수": round(_score_match(m), 1),
                "진입후수익": _fmt_ret_since(m, strategy),
                "20일이격": (f"{float(d20):+.1f}%" if d20 is not None else "—"),
                "Δ1d": str(m.get("rank_delta_1d", "—") or "—"),
                "Δ3d": str(m.get("rank_delta_3d", "—") or "—"),
                "Δ6d": str(m.get("rank_delta_6d", "—") or "—"),
                "진입일": str(entry)[:10] if entry and entry != "—" else "—",
            })

        df = _pd_pick.DataFrame(rows)

        def _sty_ret(v: Any) -> str:
            try:
                x = float(str(v).replace("%", "").replace("+", ""))
                if x >= 10.0:
                    return "color:#15803d;font-weight:800;"
                if x >= 3.0:
                    return "color:#166534;font-weight:700;"
                if x >= 0.0:
                    return "color:#374151;"
                if x >= -5.0:
                    return "color:#991b1b;"
                return "color:#b91c1c;font-weight:700;"
            except (TypeError, ValueError):
                return ""

        def _sty_delta(v: Any) -> str:
            try:
                x = float(str(v).replace("+", ""))
                if x > 0:
                    return "color:#15803d;font-weight:600;"
                if x < 0:
                    return "color:#b91c1c;"
                return ""
            except (TypeError, ValueError):
                return ""

        def _sty_disp(v: Any) -> str:
            try:
                x = float(str(v).replace("%", "").replace("+", ""))
                if x <= 8.0:
                    return "color:#15803d;"
                if x <= 15.0:
                    return "color:#b45309;font-weight:600;"
                return "color:#b91c1c;font-weight:700;"
            except (TypeError, ValueError):
                return ""

        df_styled = (
            df.style
            .map(_sty_ret, subset=["진입후수익"])
            .map(_sty_delta, subset=["Δ1d", "Δ3d", "Δ6d"])
            .map(_sty_disp, subset=["20일이격"])
        )
        _st_dataframe_all_rows(
            df_styled,
            column_config={
                "#": st.column_config.NumberColumn("#", width="small"),
                "종목": st.column_config.TextColumn("종목"),
                "시장": st.column_config.TextColumn("시장", width="small"),
                "점수": st.column_config.NumberColumn("점수", format="%.1f"),
                "진입후수익": st.column_config.TextColumn("진입후수익"),
                "20일이격": st.column_config.TextColumn("20일이격"),
                "Δ1d": st.column_config.TextColumn("Δ1d", width="small"),
                "Δ3d": st.column_config.TextColumn("Δ3d", width="small"),
                "Δ6d": st.column_config.TextColumn("Δ6d", width="small"),
                "진입일": st.column_config.TextColumn("진입일"),
            },
        )

    # ── 시장 강도 카드 ────────────────────────────────────────
    kospi_matches = [m for m in matches if str(m.get("market", "")) == "코스피"]
    kosdaq_matches = [m for m in matches if str(m.get("market", "")) == "코스닥"]
    kospi_index_status = dict((pk or {}).get("index") or {})
    kosdaq_index_status = dict((qk or {}).get("index") or {})

    def _avg_score(lst: list[dict[str, Any]]) -> float:
        return sum(_score_match(x) for x in lst) / len(lst) if lst else 0.0

    def _pick_index_1d_pct(payload, idx) -> float | None:
        for src in (idx, payload or {}):
            for k in ("ret_1d_pct", "change_pct", "pct_change_1d", "chg_1d_pct", "daily_return_pct", "return_1d_pct"):
                v = src.get(k)
                try:
                    if v is not None and str(v).strip() != "":
                        return float(v)
                except (TypeError, ValueError):
                    continue
        return None

    kospi_stage2 = bool(kospi_index_status.get("is_stage2", False))
    kosdaq_stage2 = bool(kosdaq_index_status.get("is_stage2", False))
    kospi_avg = _avg_score(kospi_matches)
    kosdaq_avg = _avg_score(kosdaq_matches)
    kospi_1d = _pick_index_1d_pct(pk, kospi_index_status)
    kosdaq_1d = _pick_index_1d_pct(qk, kosdaq_index_status)
    kospi_count = len(kospi_matches)
    kosdaq_count = len(kosdaq_matches)

    def _mkt_badge(is_s2: bool, count: int, avg: float, ret_1d: float | None, label: str) -> str:
        s2_txt = "✅ Stage2" if is_s2 else "⛔ Stage2 아님"
        s2_color = "#15803d" if is_s2 else "#b91c1c"
        ret_txt = f"{ret_1d:+.2f}%" if ret_1d is not None else "—"
        ret_c = _ret_color(ret_txt)
        return (
            f'<div style="border:1px solid #e2e8f0;border-radius:10px;'
            f'padding:0.6rem 0.8rem;background:#f8fafc;">'
            f'<div style="font-size:0.88rem;font-weight:800;color:#0f172a;'
            f'margin-bottom:0.2rem;">{label}</div>'
            f'<div style="font-size:0.75rem;font-weight:700;color:{s2_color};'
            f'margin-bottom:0.15rem;">{s2_txt}</div>'
            f'<div style="font-size:0.72rem;color:#374151;">후보 {count}개 · 평균점수 {avg:.1f}</div>'
            f'<div style="font-size:0.8rem;font-weight:700;color:{ret_c};'
            f'margin-top:0.15rem;">1일 {ret_txt}</div>'
            f'</div>'
        )

    mc1, mc2 = st.columns(2)
    mc1.markdown(_mkt_badge(kospi_stage2, kospi_count, kospi_avg, kospi_1d, "코스피"), unsafe_allow_html=True)
    mc2.markdown(_mkt_badge(kosdaq_stage2, kosdaq_count, kosdaq_avg, kosdaq_1d, "코스닥"), unsafe_allow_html=True)

    # 시장 종합 판단
    kospi_stronger = kosdaq_stronger = False
    if kospi_stage2 and (kospi_count > kosdaq_count or kospi_avg > kosdaq_avg):
        kospi_stronger = True
    elif kosdaq_stage2 and (kosdaq_count > kospi_count or kosdaq_avg > kospi_avg + 3.0):
        kosdaq_stronger = True
    elif kospi_1d is not None and kosdaq_1d is not None:
        if (kospi_1d - kosdaq_1d) >= 0.5:
            kospi_stronger = True
        elif (kosdaq_1d - kospi_1d) >= 0.5:
            kosdaq_stronger = True

    if kospi_stronger:
        st.success("📈 코스피 강세 — 코스피 Stage2 종목 위주로 접근")
    elif kosdaq_stronger:
        st.success("🚀 코스닥 강세 — 코스닥 단타·스윙 중심으로 접근")
    else:
        st.info("⚖️ 혼조세 — 종목별 개별 점수와 Δ 모멘텀 우선 확인")

    st.markdown("---")

    # ── 전략 가이드 expander ─────────────────────────────────
    with st.expander("📌 단타·스윙·장투 분류 기준", expanded=False):
        st.markdown(
            "**분류 기준**: Stage2 진입 후 경과 봉(영업일) 기준으로 탭을 나눕니다. "
            "같은 종목이 여러 탭에 동시에 표시될 수 있고 탭 안에서는 최대 12개입니다.\n\n"
            "| 구분 | 진입 후 경과 | 추가 조건 |\n"
            "|------|------------|----------|\n"
            "| **단타** | ~6봉 이내 (또는 ~18봉, 고점수면 ~28봉) | 점수·비과열 우선 |\n"
            "| **스윙** | 3~110봉 | 점수 + Δ모멘텀(코스피50·코스닥30 풀) |\n"
            "| **장투** | 28봉 이상 (기본 45봉+) | 점수 85+, 진입후수익 -12% 이상, Δ1d -12 이상 |\n\n"
            "- 20봉 ≈ 1개월 / 60봉 ≈ 3개월\n"
            "- **Δ1d·3d·6d**: 양수 = 순위 상승(모멘텀 강화), 음수 = 순위 하락(주의)\n"
            "- **20일이격**: 0~8% 이상적 · 9~15% 주의 · 16%+ 과열\n"
            "- 후보 부족 시 조건 완화 후 점수 상위로 자동 채움"
        )

    # ── 탭 ──────────────────────────────────────────────────
    tip, tsw, tlt, trev = st.tabs(["단타", "스윙", "장투", "어제 복기"])

    def _score_reason(m: dict[str, Any]) -> str:
        """점수 근거를 한 줄 요약으로 반환."""
        parts: list[str] = []
        bars = _bars_since_stage2(m)
        if bars < 10_000:
            parts.append(f"진입{bars}일")
        sc = _score_match(m)
        if sc >= 150:
            parts.append("고점수")
        elif sc >= 100:
            parts.append("중상점수")
        r3m = m.get("ret_3m_pct")
        try:
            r3m_f = float(r3m or 0)
            if r3m_f >= 30:
                parts.append(f"3개월+{r3m_f:.0f}%")
            elif r3m_f <= -20:
                parts.append(f"3개월{r3m_f:.0f}%↓")
        except (TypeError, ValueError):
            pass
        sec = (m.get("sector") or "").strip()
        if sec and sec != "미분류":
            parts.append(sec)
        return " · ".join(parts) if parts else "—"

    def _rows_for_table(lst: list[dict[str, Any]], strategy: str) -> list[dict[str, Any]]:
        rows = []
        for m in lst:
            d20 = _daily_pick_disparity_pct(m, 20)
            d50 = _daily_pick_disparity_pct(m, 50)
            ob = _daily_pick_overbought_ok(m)
            if strategy == "daytrade":
                _entry = m.get("entry_daytrade") or m.get("entry", "") or "—"
            elif strategy == "swing":
                _entry = m.get("entry_swing") or m.get("entry", "") or "—"
            else:
                _entry = m.get("entry", "") or "—"
            rows.append({
                "종목": m.get("name", ""),
                "시장": m.get("market", ""),
                "점수": f'{round(_score_match(m), 1):.1f}',
                "점수근거": _score_reason(m),
                "20일이격": (f"{float(d20):+.1f}%" if d20 is not None else "—"),
                "50일이격": (f"{float(d50):+.1f}%" if d50 is not None else "—"),
                "초기2단계(비과열)": _daily_pick_stage2_status(m),
                "진입일": _entry,
                "진입후수익": _fmt_ret_since(m, strategy),
                "Δ순위": m.get("rank_delta_1d", "—"),
            })
        return rows

    def _yesterday_learn_daytrade_top5() -> list[dict[str, Any]]:
        """어제 저널 단타 픽 + 오늘 스캔 스냅샷으로 단타 추천 Top5(휴리스틱, 참고용)."""
        jpath = _daily_pick_journal_path(here)
        journal = _journal_load(jpath)
        entries = list(journal.get("entries") or [])
        yent = _journal_find_yesterday(entries, today_kst)
        if not yent:
            return []
        y_list = list((yent.get("picks") or {}).get("daytrade") or [])
        if not y_list:
            return []
        idx = _ticker_index(matches)
        scored: list[tuple[float, dict[str, Any]]] = []
        seen: set[str] = set()
        for rec in y_list:
            tick = str(rec.get("ticker") or "").strip()
            if not tick or tick in seen:
                continue
            seen.add(tick)
            cur = idx.get(tick)
            if not cur:
                continue
            d1 = _daily_pick_rank_delta_1d_int(cur)
            sc = _score_match(cur)
            d20 = _daily_pick_disparity_pct(cur, 20)
            rd = float(d20) if d20 is not None else 8.0
            over_pen = 0.0
            if rd > 22:
                over_pen = -18.0
            elif rd > 16:
                over_pen = -6.0
            rdt = cur.get("ret_daytrade_pct")
            try:
                rdt_f = float(rdt) if rdt is not None else 0.0
            except (TypeError, ValueError):
                rdt_f = 0.0
            # 어제 후보가 오늘도 살아 있고, 순위·모멘텀·이격이 과열이 아닐수록 가산
            key = (
                sc * 0.55
                + max(d1, -5) * 1.8
                + min(max(rd, 0.0), 18.0) * 0.65
                + max(rdt_f, 0.0) * 0.12
                + over_pen
            )
            # "오늘 단타 추천(어제 복기 기반)"은 종목별 실제 Stage2 진입일을 우선 표시
            _entry_raw = cur.get("entry") or cur.get("entry_daytrade") or ""
            _entry = str(_entry_raw).strip() if _entry_raw is not None else ""
            if len(_entry) >= 10 and _entry[4:5] == "-" and _entry[7:8] == "-":
                _entry = _entry[:10]
            if not _entry:
                _entry = "—"
            scored.append(
                (
                    key,
                    {
                        "종목": str(cur.get("name") or ""),
                        "시장": str(cur.get("market") or ""),
                        "점수": round(sc, 1),
                        "20일이격": (f"{float(d20):+.1f}%" if d20 is not None else "—"),
                        "진입일": _entry,
                        "Δ순위": cur.get("rank_delta_1d", "—"),
                    },
                )
            )
        scored.sort(key=lambda x: x[0], reverse=True)
        return [row for _, row in scored[:5]]

    # ── 단타 탭 ─────────────────────────────────────────────
    with tip:
        st.subheader("⚡ 단타 후보")
        st.caption("Stage2 진입 초입(~6봉) 위주 · 짧게 보유 · 20일이격 0~15% 우선")

        with st.expander("20일 이격 가이드", expanded=False):
            st.markdown(
                "| 20일이격 | 의미 | 추천도 |\n"
                "|---------|------|-------|\n"
                "| 0~8% | 상승 초기·적당한 모멘텀 | 🟢 최적 |\n"
                "| 9~15% | 모멘텀 강함 | 🟡 양호 |\n"
                "| 16~22% | 상당히 올라옴 | 🟠 주의 |\n"
                "| 23%+ | 강한 과열 | 🔴 위험 |"
            )

        st.markdown("##### 🔥 Top 3")
        _highlight_cards(buckets["daytrade"], "daytrade")
        st.markdown("<div style='margin-top:0.5rem'></div>", unsafe_allow_html=True)

        _learn_rows = _yesterday_learn_daytrade_top5()
        if _learn_rows:
            st.markdown("##### 📌 어제 복기 기반 추천 Top 5")
            st.caption("어제 단타 후보 중 오늘도 살아남은 종목 · 순위·점수·이격 종합")
            import pandas as _pd_learn
            _learn_df = _pd_learn.DataFrame(_learn_rows)
            st.dataframe(
                _learn_df, use_container_width=True, hide_index=True,
                column_config={
                    "종목": st.column_config.TextColumn("종목"),
                    "시장": st.column_config.TextColumn("시장", width="small"),
                    "점수": st.column_config.NumberColumn("점수", format="%.1f"),
                    "20일이격": st.column_config.TextColumn("20일이격"),
                    "진입일": st.column_config.TextColumn("진입일"),
                    "Δ순위": st.column_config.TextColumn("Δ순위"),
                },
            )

        st.markdown("##### 📋 전체 후보")
        _pick_table(buckets["daytrade"], "daytrade")
        st.caption("참고용")
        _wl_render_pick_quick_add(here, buckets["daytrade"], "dt")

    # ── 스윙 탭 ─────────────────────────────────────────────
    with tsw:
        st.subheader("🟢 스윙 후보")
        st.caption("코스피 상위 50개·코스닥 상위 30개 풀 · 순위 상승 모멘텀(Δ) + 점수 정렬")

        st.markdown("##### 🏆 Top 3")
        _highlight_cards(buckets["swing"], "swing")
        st.markdown("<div style='margin-top:0.5rem'></div>", unsafe_allow_html=True)

        with st.expander("스윙 진입 체크리스트", expanded=False):
            st.markdown(
                "- ✅ 지수(코스피·코스닥) Stage2 확인\n"
                "- ✅ 섹터도 상승 추세인지 확인\n"
                "- ✅ Δ1d·Δ3d 양수 (순위 올라오는 중)\n"
                "- ✅ 20일이격 15% 이하\n"
                "- ✅ 점수 80점 이상\n"
                "- ✅ 진입후수익 플러스 또는 소폭 마이너스"
            )

        st.markdown("##### 📋 전체 후보")
        _pick_table(buckets["swing"], "swing")
        st.caption("참고용")
        _wl_render_pick_quick_add(here, buckets["swing"], "sw")

    # ── 장투 탭 ─────────────────────────────────────────────
    with tlt:
        st.subheader("📈 장투 후보")
        st.caption("진입 28봉+ · 점수 85+ · 눌림에도 순위 유지 · 수개월 보유 관점")

        st.markdown("##### 🏆 Top 3")
        _highlight_cards(buckets["longterm"], "longterm")
        st.markdown("<div style='margin-top:0.5rem'></div>", unsafe_allow_html=True)

        with st.expander("장투 진입 체크리스트", expanded=False):
            st.markdown(
                "- ✅ 지수 Stage2 지속 여부 확인\n"
                "- ✅ Δ1d -12 이상 유지 (수급 이탈 없음)\n"
                "- ✅ 진입후수익 -12% 이상 (손실 제한)\n"
                "- ✅ 점수 85점 이상 유지\n"
                "- ✅ 섹터 강도 확인\n"
                "- ✅ 분할매수 계획 수립"
            )

        st.markdown("##### 📋 전체 후보")
        _pick_table(buckets["longterm"], "longterm")
        st.caption("참고용")
        _wl_render_pick_quick_add(here, buckets["longterm"], "lt")

    # ── 어제 복기 탭 ─────────────────────────────────────────
    with trev:
        st.subheader("🔁 어제 픽 복기")
        st.caption("어제 저장된 픽 → 오늘 종가 기준 1일 수익률 · 순위 변화 확인")

        jpath = _daily_pick_journal_path(here)
        journal = _journal_load(jpath)
        entries = list(journal.get("entries") or [])
        yent = _journal_find_yesterday(entries, today_kst)

        if not yent:
            st.info("어제 기록이 없습니다. 오늘부터 저널에 픽이 쌓이면 내일부터 확인 가능합니다.")
        else:
            st.success(f"비교 기준일: **{yent.get('date')}** ↔ 오늘 스캔")
            idx = _ticker_index(matches)
            yp = yent.get("picks") or {}
            _yday_ref = str(yent.get("date") or "").strip() or "—"

            def _yday_score_float_1f(rec0: dict[str, Any]) -> float:
                v = rec0.get("score")
                if v is None:
                    return float("nan")
                if isinstance(v, str) and v.strip() in ("—", "-", "", "None", "null"):
                    return float("nan")
                try:
                    return round(float(v), 1)
                except (TypeError, ValueError):
                    return float("nan")

            alive_rows: list[dict[str, Any]] = []
            drop_rows: list[dict[str, Any]] = []

            for key, lbl in [("daytrade", "단타"), ("swing", "스윙"), ("longterm", "장기")]:
                for rec in yp.get(key) or []:
                    tick = str(rec.get("ticker") or "")
                    nm = rec.get("name", "")
                    mk = rec.get("market", "")
                    y_sc = _yday_score_float_1f(rec)
                    cur = idx.get(tick) if tick else None
                    if cur is None:
                        drop_rows.append({
                            "분류": lbl, "종목": nm, "시장": mk,
                            "어제점수": y_sc, "상태": "탈락",
                        })
                    else:
                        try:
                            y_close = float(rec.get("close")) if rec.get("close") is not None else None
                        except (TypeError, ValueError):
                            y_close = None
                        try:
                            t_close = float(cur.get("close")) if cur.get("close") is not None else None
                        except (TypeError, ValueError):
                            t_close = None
                        ret_txt = (
                            f"{((t_close / y_close) - 1.0) * 100.0:+.1f}%"
                            if y_close and y_close > 0 and t_close is not None else "—"
                        )
                        alive_rows.append({
                            "분류": lbl,
                            "종목": cur.get("name", nm),
                            "시장": cur.get("market", mk),
                            "어제점수": y_sc,
                            "1일수익률": ret_txt,
                            "오늘순위": str(cur.get("rank", "—")),
                            "Δ1d": cur.get("rank_delta_1d", "—"),
                        })

            if alive_rows:
                import pandas as _pd_rev
                df_rev = _pd_rev.DataFrame(alive_rows)

                def _sty_rev_ret(v: Any) -> str:
                    try:
                        x = float(str(v).replace("%", "").replace("+", ""))
                        if x >= 3.0:
                            return "color:#15803d;font-weight:700;"
                        if x >= 0.0:
                            return "color:#166534;"
                        if x <= -3.0:
                            return "color:#b91c1c;font-weight:700;"
                        return "color:#991b1b;"
                    except (TypeError, ValueError):
                        return ""

                def _sty_rev_delta(v: Any) -> str:
                    try:
                        x = float(str(v).replace("+", ""))
                        if x > 0:
                            return "color:#15803d;font-weight:600;"
                        if x < 0:
                            return "color:#b91c1c;"
                        return ""
                    except (TypeError, ValueError):
                        return ""

                df_sty = (
                    df_rev.style
                    .map(_sty_rev_ret, subset=["1일수익률"])
                    .map(_sty_rev_delta, subset=["Δ1d"])
                )
                try:
                    df_sty = df_sty.format("{:.1f}", subset=["어제점수"], na_rep="—")
                except Exception:
                    pass

                st.markdown("##### ✅ 생존 종목")
                _st_dataframe_all_rows(
                    df_sty,
                    column_config={
                        "분류": st.column_config.TextColumn("분류", width="small"),
                        "종목": st.column_config.TextColumn("종목"),
                        "시장": st.column_config.TextColumn("시장", width="small"),
                        "어제점수": st.column_config.NumberColumn("어제점수", format="%.1f", help=f"{_yday_ref} 기준"),
                        "1일수익률": st.column_config.TextColumn("1일수익률"),
                        "오늘순위": st.column_config.TextColumn("오늘순위", width="small"),
                        "Δ1d": st.column_config.TextColumn("Δ1d", width="small"),
                    },
                )

            if drop_rows:
                with st.expander(f"⛔ 탈락 종목 {len(drop_rows)}개", expanded=False):
                    import pandas as _pd_drop
                    st.dataframe(
                        _pd_drop.DataFrame(drop_rows),
                        use_container_width=True,
                        hide_index=True,
                    )

            if not alive_rows and not drop_rows:
                st.info("어제 저장된 픽이 비어 있습니다.")

    st.divider()
    st.caption(
        "전체 순위·차트는 **코스피** / **코스닥** Stage2 스캐너에서 확인하세요. "
        "지수·섹터까지 겹쳐 보는 습관은 와인스타인식 **시장→섹터→종목** 순서와도 잘 맞습니다."
    )


FRED_API_OBS = "https://api.stlouisfed.org/fred/series/observations"
FRED_API_SERIES = "https://api.stlouisfed.org/fred/series"
FRED_API_SEARCH = "https://api.stlouisfed.org/fred/series/search"

# [FRED](https://fred.stlouisfed.org/) 시리즈 ID 프리셋 — 조회 실패 시 하단 검색으로 대체 가능
FRED_SERIES_CATALOG: dict[str, list[tuple[str, str]]] = {
    "성장·활동": [
        ("미국 실질 GDP (분기)", "GDPC1"),
        ("미국 GDP(명목)", "GDP"),
        ("미국 산업생산지수", "INDPRO"),
        ("미국 소매판매", "RSAFS"),
        ("총 산업 가동률 (Capacity Util.)", "TCU"),
        ("개인소비지출(명목)", "PCE"),
    ],
    "물가·기대": [
        ("미국 CPI(전체)", "CPIAUCSL"),
        ("미국 Core CPI", "CPILFESL"),
        ("미국 PPI(최종수요)", "PPIACO"),
        ("미국 PCE 물가지수", "PCEPI"),
        ("5Y 브레이크이븐 인플레", "T5YIE"),
        ("10Y 브레이크이븐 인플레", "T10YIE"),
        ("5Y5Y Forward 인플레", "T5YIFR"),
    ],
    "금리·채권": [
        ("연준 기준금리 목표(상단)", "DFEDTARU"),
        ("연준 기준금리 목표(하단)", "DFEDTARL"),
        ("미국 3개월 국채", "DGS3MO"),
        ("미국 2년 국채", "DGS2"),
        ("미국 5년 국채", "DGS5"),
        ("미국 10년 국채", "DGS10"),
        ("미국 30년 국채", "DGS30"),
        ("장단기 금리차 (10Y−2Y)", "T10Y2Y"),
        ("장단기 금리차 (10Y−3M)", "T10Y3M"),
        ("SOFR(담보금리)", "SOFR"),
    ],
    "고용": [
        ("미국 실업률", "UNRATE"),
        ("U-6 실업(광의)", "U6RATE"),
        ("비농업 고용자수", "PAYEMS"),
        ("주간 신규 실업수당청구", "ICSA"),
        ("경제활동참가율", "CIVPART"),
    ],
    "환율·달러": [
        ("미국 달러(광의 무역가중)", "DTWEXBGS"),
        ("미국 달러(주요국)", "DTWEXM"),
        ("USD/KRW (원/달러)", "DEXKOUS"),
        ("USD/JPY", "DEXJPUS"),
        ("USD/EUR", "DEXUSEU"),
        ("USD/GBP", "DEXUSUK"),
        ("USD/CNY", "DEXCHUS"),
        ("USD/MXN", "DEXMXUS"),
        ("미국 무역수지", "BOPGSTB"),
    ],
    "금·원자재·에너지": [
        ("금 PM Fix (런던 USD/oz)", "GOLDPMGBD228NLBM"),
        ("은 (런던 USD/oz)", "SLVPRUSD"),
        ("WTI 원유 ($/bbl)", "DCOILWTICO"),
        ("Brent 원유 ($/bbl)", "DCOILBRENTEU"),
        ("미국 휘발유 가격(전국)", "GASREGW"),
        ("구리 세계가 (USD/톤)", "PCOPPUSDM"),
        ("철광석 수입가 (USD/톤)", "PIORECRUSDM"),
        ("천연가스 (헨리허브)", "MHHNGSP"),
    ],
    "리스크·유동성·신용": [
        ("VIX (공포지수)", "VIXCLS"),
        ("Chicago Fed NFCI", "NFCI"),
        ("ICE BofA 하이일드 OAS", "BAMLH0A0HYM2"),
        ("St. Louis 금융스트레스 지수", "STLFSI4"),
        ("연준 총자산 (WALCL)", "WALCL"),
        ("역레포 일일 규모", "RRPONTSYD"),
        ("M2 통화량", "M2SL"),
    ],
    "주식·위험자산": [
        ("Wilshire 5000 총시가", "WILL5000IND"),
        ("S&P 500", "SP500"),
        ("나스닥 종합", "NASDAQCOM"),
    ],
    "주택": [
        ("Case-Shiller 20 도시", "SPCS20RSA"),
        ("FHFA 주택가격지수", "USSTHPI"),
        ("30년 모기지 고정금리", "MORTGAGE30US"),
        ("신규 주택착공", "HOUST"),
        ("기존주택판매 (연율화 만건)", "EXHOSLUSM"),
    ],
}

FRED_DEFAULT_CATEGORIES: tuple[str, ...] = (
    "성장·활동",
    "물가·기대",
    "금리·채권",
    "환율·달러",
    "금·원자재·에너지",
    "리스크·유동성·신용",
)

# Investing.com 등 시장 사이트와 교차 확인용 외부 링크(실시간 시세·캘린더는 FRED와 성격이 다름)
INVESTING_COM_EXTERNAL_LINKS: tuple[tuple[str, str], ...] = (
    ("경제 캘린더", "https://www.investing.com/economic-calendar/"),
    ("세계 지수", "https://www.investing.com/indices/world-indices"),
    ("미국 국채·금리", "https://www.investing.com/rates-bonds/u.s.-government-bonds"),
    ("환율", "https://www.investing.com/currencies/single-currency-crosses"),
    ("원자재", "https://www.investing.com/commodities/"),
    ("주요 주식", "https://www.investing.com/equities/"),
)

# 버튼 한 번으로 «추가 시리즈 ID» 칸을 채우는 프리셋(Investing 메인에서 자주 보는 축)
FRED_PRESET_ID_STRINGS: dict[str, str] = {
    "핵심 10종": (
        "SP500, DGS10, VIXCLS, DCOILWTICO, GOLDPMGBD228NLBM, DEXKOUS, CPIAUCSL, UNRATE, DTWEXBGS, T10Y2Y"
    ),
    "금리 곡선": "DGS3MO, DGS2, DGS5, DGS10, DGS30, T10Y2Y, T10Y3M, SOFR",
    "물가·기대인플": "CPIAUCSL, CPILFESL, PCEPI, T5YIE, T10YIE, T5YIFR, PPIACO",
    "원자재·VIX": "DCOILWTICO, DCOILBRENTEU, GOLDPMGBD228NLBM, SLVPRUSD, PCOPPUSDM, VIXCLS, BAMLH0A0HYM2",
}

# 핵심 스냅샷 카드(메트릭)에 우선 표시할 시리즈 ID — Investing 대시보드와 결이 비슷한 조합
FRED_SNAPSHOT_SERIES_ORDER: tuple[str, ...] = (
    "SP500",
    "DGS10",
    "VIXCLS",
    "DCOILWTICO",
    "DEXKOUS",
)


def _fred_api_key() -> str:
    key = (os.environ.get("FRED_API_KEY") or os.environ.get("APT_FRED_API_KEY") or "").strip()
    if key:
        return key
    here = Path(__file__).resolve().parent
    for fn in ("fred_api_key.txt", "apt_fred_key.txt"):
        p = here / fn
        if p.is_file():
            try:
                line = (p.read_text(encoding="utf-8", errors="replace").splitlines() or [""])[0].strip()
            except OSError:
                line = ""
            if line and not line.startswith("#"):
                return line
    return ""


@st.cache_data(ttl=60 * 30, show_spinner=False)
def _fred_fetch_series(series_id: str, api_key: str, start_date: str, end_date: str) -> Any:
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start_date,
        "observation_end": end_date,
        "sort_order": "asc",
        "limit": "100000",
    }
    r = requests.get(FRED_API_OBS, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()
    obs = list(data.get("observations") or [])
    if pd is None:
        return obs
    rows: list[dict[str, Any]] = []
    for o in obs:
        ds = str(o.get("date") or "").strip()
        vs = o.get("value")
        if not ds or vs in (None, ".", ""):
            continue
        try:
            rows.append({"date": pd.to_datetime(ds), "value": float(vs)})
        except (TypeError, ValueError):
            continue
    if not rows:
        return pd.DataFrame(columns=["date", "value"])
    return pd.DataFrame(rows).sort_values("date")


@st.cache_data(ttl=3600, show_spinner=False)
def _fred_series_meta(series_id: str, api_key: str) -> dict[str, Any]:
    """시리즈 제목·단위·주기 (표·툴팁용)."""

    r = requests.get(
        FRED_API_SERIES,
        params={"series_id": series_id, "api_key": api_key, "file_type": "json"},
        timeout=25,
    )
    r.raise_for_status()
    ser = (r.json().get("seriess") or [None])[0]
    if not ser:
        return {"title": series_id, "units": "", "freq": ""}
    return {
        "title": str(ser.get("title") or series_id),
        "units": str(ser.get("units") or ""),
        "freq": str(ser.get("frequency_short") or ser.get("frequency") or ""),
    }


@st.cache_data(ttl=1800, show_spinner=False)
def _fred_search_series_api(q: str, api_key: str, *, limit: int = 30) -> list[dict[str, Any]]:
    """FRED 공개 검색 API — 시리즈 ID 탐색."""

    q = (q or "").strip()
    if len(q) < 2:
        return []
    r = requests.get(
        FRED_API_SEARCH,
        params={
            "search_text": q,
            "api_key": api_key,
            "file_type": "json",
            "limit": min(limit, 1000),
            "order_by": "popularity",
            "sort_order": "desc",
        },
        timeout=30,
    )
    r.raise_for_status()
    return list(r.json().get("seriess") or [])


def _fred_value_change_stats(s: "pd.Series") -> dict[str, Any]:
    """일·월 등 혼합 주기에 맞춰 직전 봉·약 1년 전 대비 변화율."""

    s = s.dropna().sort_index()
    if s.empty:
        return {"last": None, "d1_pct": None, "yoy_pct": None, "last_dt": None}
    last_dt = s.index[-1]
    last_v = float(s.iloc[-1])
    prev_v = float(s.iloc[-2]) if len(s) >= 2 else None
    d1 = ((last_v / prev_v) - 1.0) * 100.0 if prev_v not in (None, 0) else None
    cutoff = last_dt - pd.DateOffset(months=12)
    hist = s[s.index <= cutoff]
    yoy = None
    if len(hist) >= 1:
        y0 = float(hist.iloc[-1])
        if y0 != 0:
            yoy = ((last_v / y0) - 1.0) * 100.0
    return {"last": last_v, "d1_pct": d1, "yoy_pct": yoy, "last_dt": last_dt}


def _fred_compile_insights(
    merged: dict[str, Any],
    titles: dict[str, str],
) -> list[str]:
    """동시에 로드된 시리즈로부터 간단한 매크로 인사이트(참고용, 투자 권유 아님)."""

    def series_last(sid: str) -> float | None:
        df = merged.get(sid)
        if df is None or not isinstance(df, pd.DataFrame) or df.empty:
            return None
        return float(df["value"].iloc[-1])

    out: list[str] = []

    t10y2y = series_last("T10Y2Y")
    if t10y2y is not None:
        if t10y2y < 0:
            out.append(
                "**장단기 금리차(10Y−2Y) < 0** — 미국 국채 곡선 **역전** 구간으로, 경기 후반·신용·금융 스트레스 논의와 자주 연결됩니다(과거와 미래를 보장하지는 않음)."
            )
        else:
            out.append(
                f"**장단기 금리차(10Y−2Y)** 약 **{t10y2y:.2f}%p** — 단기 대비 장기 금리 프리미엄이 **양수**인 상태입니다."
            )

    t10y3m = series_last("T10Y3M")
    if t10y3m is not None and t10y3m < 0:
        out.append(
            "**10Y−3M 금리차 < 0** — 뉴욕 연은 등에서 언급되는 **역전 신호** 중 하나로, 장기 역사 샘플에서 경기침체 선행과 상관 연구가 있습니다."
        )

    vix = series_last("VIXCLS")
    if vix is not None:
        if vix >= 25:
            out.append(f"**VIX** {vix:.1f} — 변동성·불확실성이 **높은** 편(장기 평균 대비 상대적 수치로 해석).")
        elif vix <= 14:
            out.append(f"**VIX** {vix:.1f} — 상대적으로 **낮은** 공포 지수(시장 안정 vs 과도한 안이함 논쟁은 별개).")

    nfci = series_last("NFCI")
    if nfci is not None:
        out.append(
            f"**Chicago Fed NFCI** {nfci:+.3f} — 0보다 **크면** 금융여건이 역사적 평균보다 **긴축**, **작으면** 완화 쪽으로 해석됩니다."
        )

    hy = series_last("BAMLH0A0HYM2")
    if hy is not None:
        out.append(
            f"**하이일드 OAS** 약 **{hy:.0f} bp** — 위험채 스프레드(신용 리스크 프리미엄) 참고치입니다."
        )

    wti = series_last("DCOILWTICO")
    brent = series_last("DCOILBRENTEU")
    if wti is not None and brent is not None:
        out.append(
            f"**Brent − WTI** ≈ **${brent - wti:+.2f}/bbl** — 지역·품질·재고에 따른 **유종 간 갭**(단기 공급 신호로 읽는 경우가 많음)."
        )

    krw = merged.get("DEXKOUS")
    if krw is not None and isinstance(krw, pd.DataFrame) and len(krw) >= 2:
        stt = _fred_value_change_stats(krw.set_index("date")["value"])
        if stt.get("yoy_pct") is not None:
            out.append(
                f"**USD/KRW** (원/달러) 1년 전 대비 약 **{stt['yoy_pct']:+.2f}%** — "
                f"양수면 같은 달러당 **원화 표시 약세**(수치는 표본·주기에 따라 달라짐)."
            )

    t5 = series_last("T5YIE")
    t10 = series_last("DGS10")
    if t5 is not None and t10 is not None:
        approx = t10 - t5
        out.append(
            f"**대략적 실질 장기금리(참고)** 10Y − 5Y 브레이크이븐 ≈ **{approx:+.2f}%p** "
            f"(명목 10Y와 기대 인플레를 단순 차감한 휴리스틱)."
        )

    if not out:
        out.append("선택한 지표만으로는 자동 인사이트가 제한됩니다. **금리·VIX·원유·환율**을 함께 넣으면 요약이 풍부해집니다.")
    return out


def _fred_render_investing_style_header() -> None:
    """Investing.com 느낌의 강조 헤더 + 빠른 링크 행."""
    st.markdown(
        """
<div style="background: linear-gradient(105deg, #0f172a 0%, #1e3a5f 42%, #0f172a 100%);
  border: 1px solid rgba(59,130,246,0.35); border-left: 5px solid #3b82f6;
  border-radius: 12px; padding: 18px 20px 16px; margin: 0 0 14px 0;
  box-shadow: 0 8px 24px rgba(15,23,42,0.35);">
  <div style="font-size: 0.72rem; letter-spacing: 0.14em; text-transform: uppercase; color: #93c5fd; font-weight: 700;">
    Macro · FRED</div>
  <div style="font-size: 1.42rem; font-weight: 800; color: #f8fafc; margin-top: 6px; line-height: 1.2;">
    글로벌 매크로 대시보드</div>
  <div style="font-size: 0.92rem; color: #94a3b8; margin-top: 10px; line-height: 1.45;">
    공식 통계는 <strong style="color:#e2e8f0;">FRED</strong> · 시세·일정·뉴스 흐름은
    <strong style="color:#93c5fd;">Investing.com</strong> 스타일로 교차 확인하세요.
  </div>
</div>
        """,
        unsafe_allow_html=True,
    )
    n_links = len(INVESTING_COM_EXTERNAL_LINKS)
    if n_links:
        lc = st.columns(min(n_links, 6))
        for i, (lab, url) in enumerate(INVESTING_COM_EXTERNAL_LINKS[:6]):
            with lc[i % len(lc)]:
                st.markdown(f"[**{lab}**]({url})")
    if n_links > 6:
        st.caption(
            " · ".join(f"[{lab}]({url})" for lab, url in INVESTING_COM_EXTERNAL_LINKS[6:])
        )


def _fred_render_macro_snapshot_metrics(summary_rows: list[dict[str, Any]]) -> None:
    """Investing 메인에 자주 나오는 축과 비슷하게, 요약 표에서 핵심 ID만 메트릭 카드로."""
    if not summary_rows:
        return
    by_id = {str(r.get("ID") or ""): r for r in summary_rows}
    found: list[str] = [sid for sid in FRED_SNAPSHOT_SERIES_ORDER if sid in by_id]
    if not found:
        return
    st.markdown("##### ⚡ 핵심 스냅샷 · 최종 관측값")
    st.caption("아래 카드는 **이번에 조회된 지표 중** 위 목록에 해당할 때만 표시됩니다.")
    cols = st.columns(len(found))
    for i, sid in enumerate(found):
        r = by_id[sid]
        title = str(r.get("지표") or sid)
        if len(title) > 22:
            title = title[:20] + "…"
        v = r.get("최종값")
        d1 = r.get("직전대비%")
        with cols[i]:
            try:
                delta = None
                if d1 is not None:
                    delta = f"{float(d1):+.2f}%"
                if v is None:
                    st.metric(label=title, value="—", delta=delta)
                else:
                    fv = float(v)
                    vf = f"{fv:,.4g}" if abs(fv) >= 0.01 or fv == 0 else f"{fv:.4e}"
                    st.metric(label=title, value=vf, delta=delta)
            except (TypeError, ValueError):
                st.metric(label=title, value="—")


def _render_tab_fred_dashboard() -> None:
    _fred_render_investing_style_header()
    st.markdown(
        "[FRED](https://fred.stlouisfed.org/) **공식 API**로 "
        "**금리·물가·환율·유가·금속·VIX·신용** 등 거시 시계열을 불러옵니다. "
        "[Investing.com](https://www.investing.com/) 은 **실시간 시세·경제 캘린더·뉴스**에 강해 "
        "**같은 지표라도 숫자·주기가 다를 수** 있습니다(교육·모니터링용, 투자 권유 아님)."
    )
    api_key = _fred_api_key()
    if not api_key:
        st.warning(
            "FRED API 키가 없습니다. 환경변수 `FRED_API_KEY`(또는 `APT_FRED_API_KEY`) 또는 "
            "이 앱 폴더의 `fred_api_key.txt` 첫 줄에 키를 넣어 주세요. "
            "키 발급: [FRED API Keys](https://fred.stlouisfed.org/docs/api/api_key.html)"
        )
        return
    if pd is None:
        st.error("pandas가 없어 지표 테이블/차트를 렌더링할 수 없습니다.")
        return

    if "fred_custom_series_ids" not in st.session_state:
        st.session_state.fred_custom_series_ids = ""

    all_categories = list(FRED_SERIES_CATALOG.keys())
    default_cats = [c for c in FRED_DEFAULT_CATEGORIES if c in all_categories]
    sel_categories = st.multiselect(
        "카테고리",
        all_categories,
        default=default_cats or all_categories[:6],
        help="너무 많이 선택하면 API 호출·렌더가 무거워질 수 있습니다.",
    )

    option_labels: list[str] = []
    label_to_sid: dict[str, str] = {}
    for cat in sel_categories:
        for name, sid in FRED_SERIES_CATALOG.get(cat, []):
            label = f"{name} [{sid}]"
            option_labels.append(label)
            label_to_sid[label] = sid

    default_pick_n = min(10, len(option_labels))
    default_labels = option_labels[:default_pick_n] if option_labels else []
    pick_labels = st.multiselect(
        "조회 지표 (복수)",
        options=option_labels,
        default=default_labels,
        help="프리셋에서 고른 뒤, 필요하면 추가 시리즈 ID로 확장하세요.",
    )
    st.markdown("##### Investing 스타일 빠른 프리셋")
    st.caption(
        "아래 버튼은 **추가 시리즈 ID** 입력란을 채웁니다. "
        "[Investing.com](https://www.investing.com/) 메인·시장 메뉴에서 자주 보는 축과 비슷하게 맞춰 두었습니다."
    )
    _pcols = st.columns(4)
    for _pi, (_plab, _pids) in enumerate(FRED_PRESET_ID_STRINGS.items()):
        with _pcols[_pi % 4]:
            if st.button(_plab, key=f"fred_preset_{_pi}", use_container_width=True):
                st.session_state.fred_custom_series_ids = _pids
                st.rerun()
    custom_ids_raw = st.text_input(
        "추가 시리즈 ID (쉼표·공백 구분)",
        key="fred_custom_series_ids",
        placeholder="예: UNRATE, CPIAUCSL, DGS10, VIXCLS — 또는 위 버튼으로 자동 입력",
    )
    with st.expander("🔎 FRED에서 시리즈 ID 검색", expanded=False):
        sq = st.text_input("검색어 (영문 권장)", value="", key="fred_search_q", placeholder="gold, korea, breakeven …")
        if sq and len(sq.strip()) >= 2:
            try:
                hits = _fred_search_series_api(sq.strip(), api_key, limit=25)
                if hits:
                    rh = []
                    for h in hits:
                        rh.append(
                            {
                                "id": h.get("id"),
                                "제목": (h.get("title") or "")[:120],
                                "단위": h.get("units"),
                                "주기": h.get("frequency_short"),
                            }
                        )
                    st.dataframe(pd.DataFrame(rh), use_container_width=True, hide_index=True)
                    st.caption("표의 `id` 열을 복사해 위 **추가 시리즈 ID**에 붙여 넣으면 됩니다.")
                else:
                    st.caption("검색 결과가 없습니다.")
            except Exception as ex:
                st.warning(f"검색 API 오류: {ex}")

    c1, c2 = st.columns(2)
    with c1:
        start_d = st.date_input("시작일", value=date.today() - timedelta(days=365 * 5))
    with c2:
        end_d = st.date_input("종료일", value=date.today())

    series_ids: list[str] = [label_to_sid[x] for x in pick_labels]
    custom_ids = [x.strip().upper() for x in re.split(r"[,;\s]+", custom_ids_raw) if x.strip()]
    for sid in custom_ids:
        if sid not in series_ids:
            series_ids.append(sid)
    if not series_ids:
        st.info("지표를 1개 이상 선택하거나 추가 시리즈 ID를 입력해 주세요.")
        return

    start_s, end_s = start_d.isoformat(), end_d.isoformat()
    merged: dict[str, Any] = {}
    failed: list[str] = []
    with st.spinner(f"FRED에서 지표 {len(series_ids)}개를 불러오는 중…"):
        for sid in series_ids:
            try:
                dff = _fred_fetch_series(sid, api_key=api_key, start_date=start_s, end_date=end_s)
                if isinstance(dff, pd.DataFrame) and not dff.empty:
                    merged[sid] = dff
                else:
                    failed.append(sid)
            except Exception:
                failed.append(sid)

    if failed:
        st.caption(f"조회 실패 또는 빈 데이터(시리즈 종료·ID 오타 가능): `{', '.join(failed)}`")
    if not merged:
        st.error("표시할 데이터가 없습니다. 기간·시리즈 ID를 확인하거나 검색으로 ID를 찾아 주세요.")
        return

    titles: dict[str, str] = {}
    summary_rows: list[dict[str, Any]] = []
    wide: Any = None
    for sid, dff in merged.items():
        meta_u = ""
        try:
            meta = _fred_series_meta(sid, api_key)
            titles[sid] = str(meta.get("title") or sid)
            meta_u = str(meta.get("units") or "")
        except Exception:
            titles[sid] = sid
        s = dff.set_index("date")["value"].sort_index()
        stt = _fred_value_change_stats(s)
        ld = stt.get("last_dt")
        summary_rows.append(
            {
                "ID": sid,
                "지표": titles.get(sid, sid),
                "단위(메타)": meta_u,
                "최종일": ld.strftime("%Y-%m-%d") if ld is not None else "",
                "최종값": None if stt["last"] is None else round(float(stt["last"]), 6),
                "직전대비%": None if stt["d1_pct"] is None else round(float(stt["d1_pct"]), 3),
                "약1년전대비%": None if stt["yoy_pct"] is None else round(float(stt["yoy_pct"]), 3),
            }
        )
        if wide is None:
            wide = s.to_frame(sid)
        else:
            wide = wide.join(s.to_frame(sid), how="outer")

    _fred_render_macro_snapshot_metrics(summary_rows)

    st.subheader("📊 전체 요약 표 · 최신 관측")
    _df_sum = pd.DataFrame(summary_rows)
    try:
        st.dataframe(
            _df_sum,
            use_container_width=True,
            hide_index=True,
            column_config={
                "최종값": st.column_config.NumberColumn("최종값", format="%.6g"),
                "직전대비%": st.column_config.NumberColumn("직전 Δ%", format="%.2f%%"),
                "약1년전대비%": st.column_config.NumberColumn("1년 Δ%", format="%.2f%%"),
                "지표": st.column_config.TextColumn("지표", width="large"),
            },
        )
    except Exception:
        st.dataframe(_df_sum, use_container_width=True, hide_index=True)

    insights = _fred_compile_insights(merged, titles)
    with st.expander("💡 매크로 인사이트 (자동 요약)", expanded=True):
        for line in insights:
            st.markdown(f"- {line}")

    if wide is not None and not wide.empty:
        chart_df_raw = wide.sort_index()
        n_series = int(chart_df_raw.shape[1])
        mode_labels = [
            "정규화 (첫 유효값=100) — 단위가 달라도 추세 비교",
            "한 그래프·원시값 — GDP·지수·%가 섞이면 거의 안 보임",
            "패널 — 지표마다 별도 Y축 (세로 분리)",
        ]
        default_mode_idx = 0 if n_series >= 2 else 1
        chart_mode = st.radio(
            "시계열 차트 방식",
            mode_labels,
            index=min(default_mode_idx, len(mode_labels) - 1),
            horizontal=True,
            key="fred_ts_chart_mode",
        )
        use_norm = chart_mode.startswith("정규화")
        use_panel = chart_mode.startswith("패널")

        if use_norm:
            chart_df = chart_df_raw.apply(
                lambda col: (col / col.dropna().iloc[0]) * 100.0
                if col.dropna().size and float(col.dropna().iloc[0]) != 0
                else col
            )
            y_title = "지수 (첫 유효 관측=100)"
        else:
            chart_df = chart_df_raw
            y_title = "원시 수준 (시리즈별 단위 상이)"

        if not use_norm and not use_panel and n_series >= 2:
            st.warning(
                "지표마다 **단위·크기**(조 달러 vs % 등)가 다르면 한 Y축에 겹쳐 보이지 않습니다. "
                "**정규화** 또는 **패널**을 권장합니다."
            )

        st.subheader("📈 시계열 차트")
        pal = (
            "#7dd3fc",
            "#fda4af",
            "#86efac",
            "#c4b5fd",
            "#fcd34d",
            "#f9a8d4",
            "#67e8f9",
            "#bef264",
        )
        if go is not None and use_panel and n_series >= 1:
            from plotly.subplots import make_subplots  # noqa: PLC0415

            sub_titles = [f"{c}" for c in chart_df_raw.columns]
            fig_p = make_subplots(
                rows=max(n_series, 1),
                cols=1,
                shared_xaxes=True,
                vertical_spacing=min(0.06, 0.5 / max(n_series, 1)),
                subplot_titles=sub_titles,
            )
            for i, col in enumerate(chart_df_raw.columns, start=1):
                fig_p.add_trace(
                    go.Scatter(
                        x=chart_df_raw.index,
                        y=chart_df_raw[col],
                        mode="lines",
                        line=dict(width=1.5, color=pal[(i - 1) % len(pal)]),
                        name=str(col),
                        showlegend=False,
                        connectgaps=False,
                    ),
                    row=i,
                    col=1,
                )
            fig_p.update_layout(
                template="plotly_dark",
                height=min(100 * n_series + 120, 2200),
                margin=dict(t=28, b=32, l=52, r=20),
                paper_bgcolor="rgba(15,23,42,0.4)",
                plot_bgcolor="rgba(15,23,42,0.2)",
            )
            fig_p.update_xaxes(gridcolor="rgba(148,163,184,0.12)", showgrid=True)
            fig_p.update_yaxes(gridcolor="rgba(148,163,184,0.12)", showgrid=True)
            st.plotly_chart(fig_p, use_container_width=True, config={"displayModeBar": True})
        elif go is not None:
            fig = go.Figure()
            for i, col in enumerate(chart_df.columns):
                fig.add_trace(
                    go.Scatter(
                        x=chart_df.index,
                        y=chart_df[col],
                        name=f"{col} — {titles.get(str(col), col)}"[:72],
                        mode="lines",
                        line=dict(width=1.6, color=pal[i % len(pal)]),
                        connectgaps=False,
                    )
                )
            fig.update_layout(
                template="plotly_dark",
                height=460,
                margin=dict(t=36, b=44, l=52, r=24),
                legend=dict(orientation="h", yanchor="bottom", y=1.07, x=0, font=dict(size=9)),
                xaxis=dict(gridcolor="rgba(148,163,184,0.15)", title="날짜"),
                yaxis=dict(
                    title=y_title,
                    gridcolor="rgba(148,163,184,0.15)",
                    zerolinecolor="rgba(148,163,184,0.25)",
                ),
                paper_bgcolor="rgba(15,23,42,0.4)",
                plot_bgcolor="rgba(15,23,42,0.25)",
            )
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": True})
        else:
            st.line_chart(chart_df, use_container_width=True)
        with st.expander("원시 데이터 (병합 시계열)", expanded=False):
            st.caption("차트가 정규화여도 이 표는 **원시 병합값**입니다.")
            st.dataframe(chart_df_raw.tail(500), use_container_width=True)

    st.caption(
        "FRED에는 수십만 개 시리즈가 있습니다. 위 검색으로 ID를 찾거나 "
        "[FRED](https://fred.stlouisfed.org/)에서 시리즈 코드를 복사해 확장하세요. "
        "실시간 시세·경제일정은 [Investing.com 경제 캘린더](https://www.investing.com/economic-calendar/) 등과 함께 보세요. "
        "API: [fred.stlouisfed.org/docs/api](https://fred.stlouisfed.org/docs/api/fred)"
    )


def _render_tab_ml_stock_picks() -> None:
    st.header("ML 종목 선정 리포트")
    st.caption(
        "로컬 스크립트 `ML/stock_ml_selector.py`가 만든 **CSV/JSON/HTML**을 읽어 표시합니다. "
        "아래 **「이게 내가 생각한 그 ML인가요?」**를 꼭 읽어 주세요."
    )

    with st.expander("ML 선정이 무엇인지 · 제가 생각한 것과 같은가요?", expanded=True):
        st.markdown(
            """
### 한 줄 요약
**「앞으로 가장 많이 오를 종목」을 미리 찍어 주는 프로그램이 아닙니다.**  
코스피·코스닥·(테마) Stage2 스캔에서 **이미 뽑힌 매칭 종목들**만 모아, 숫자 특성이 비슷한 패턴으로 **다시 줄 세운 참고용 순위**입니다.

와인스타인식으로 말하면 **이미 2단계(어드밴싱) 후보 풀 안에서만** 다시 줄을 세운 것이라, **지수·섹터가 받쳐 주는지**는 여전히 **코스피/코스닥 스캐너·섹터 탭**에서 따로 보는 것이 맞습니다.

---

### 무슨 데이터를 쓰나
- `kospi_data/results_web.json`, `kosdaq_data/results_web.json`, `tema_stage2_data/results_web.json` 의 **matches** 를 합칩니다.
- KRX 마스터(`kospi_kosdaq_all.csv` 등)로 **보통주·티커**를 맞춥니다.

### 모형이 하는 일 (코드 기준)
- **입력 특성(예)**: Stage2 점수, 진입 후 경과 봉, RS, 3개월 수익률, 거래량 비율, 시가총액(log), 영업이익률 등.
- **라벨(약한 지도학습)**: 같은 시점 스냅샷 안에서  
  **「순위가 상위권(20위 이내)이면서 3개월 수익률이 샘플 중앙값 이상」** 인 종목을 긍정(1)으로 두고,  
  **로지스틱 회귀(자체 구현)** 로 가중치를 맞춥니다.
- **ml_score**: 위 모형의 확률을 0~100 근사로 올린 값.  
- **선정**: `ml_score`가 **전체 후보 중 상위 약 15%(85% 분위)** 이상인 종목(없으면 상위 30개 등으로 완화).

### 그래서 “선점”과는 어떻게 다른가
- **미래 주가·수익률을 예측**하지 않습니다. **과거 스냅샷에서 만든 규칙**으로 현재 후보를 재정렬한 것입니다.
- **자동 매수·목표가·손절가**를 주지 않습니다. 같은 Stage2 유니버스 안에서 **관심 종목을 줄이는 2차 필터** 정도로 보는 것이 맞습니다.
- 시장 구조가 바뀌면 패턴이 무너질 수 있고, **과최적화·표본 편향**에 취약합니다.

### 이렇게 쓰면 좋다
- 코스피/코스닥/테마 스캐너를 먼저 돌린 뒤, **너무 많을 때 후보를 줄이거나 정렬할 참고**로 쓰기.
- 반드시 **공시·섹터·리스크**는 별도로 확인. 투자 권유가 아닙니다.

---
생성 명령: `py -3 streamlit/ML/stock_ml_selector.py` (경로는 환경에 맞게)
            """
        )

    ml_dir = Path(__file__).resolve().parent / "ML" / "results"
    csv_path = ml_dir / "selected_stocks.csv"
    json_path = ml_dir / "selected_stocks.json"
    html_path = ml_dir / "report.html"

    c1, c2, c3 = st.columns(3)
    c1.metric("CSV", "준비됨" if csv_path.is_file() else "없음")
    c2.metric("JSON", "준비됨" if json_path.is_file() else "없음")
    c3.metric("HTML", "준비됨" if html_path.is_file() else "없음")

    if not csv_path.is_file():
        st.info(
            "ML 결과가 아직 없습니다. 아래 명령으로 생성해 주세요:\n\n"
            "`py -3 c:\\code\\SynologyDrive\\streamlit\\ML\\stock_ml_selector.py`"
        )
        return

    if pd is None:
        st.error("pandas가 없어 ML 결과 표를 표시할 수 없습니다.")
        return

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
    except Exception as e:
        st.error(f"CSV 로드 실패: {e}")
        return

    st.subheader("ML 선정 종목")
    st.dataframe(df, use_container_width=True, hide_index=True)

    st.subheader("리포트 파일")
    st.code(str(html_path), language="text")
    st.caption("브라우저에서 열기: `file:///C:/code/SynologyDrive/streamlit/ML/results/report.html`")

    if html_path.is_file():
        try:
            html_text = html_path.read_text(encoding="utf-8", errors="replace")
            with st.expander("리포트 미리보기(요약)", expanded=False):
                st.components.v1.html(html_text, height=720, scrolling=True)
        except OSError:
            pass


def _wl_render_login_form(here: Path) -> None:
    _wl_ensure_preset_users(here)
    st.subheader("빠른 로그인")
    st.caption(
        f"프리셋 계정 기본 비밀번호: `{_WL_PRESET_SLOT_PW}` · "
        "추가한 계정도 아래 버튼으로 즉시 로그인할 수 있습니다."
    )
    quick_accounts = _wl_collect_quick_accounts(here)
    per_row = 4
    for s in range(0, len(quick_accounts), per_row):
        row = quick_accounts[s:s + per_row]
        cols = st.columns(per_row)
        for i, (uid, label) in enumerate(row):
            with cols[i]:
                if st.button(label, key=f"wl_quick_login_{uid}", use_container_width=True):
                    # 빠른 로그인은 폼 입력 없이 바로 세션 로그인 처리
                    st.session_state["wl_user"] = uid
                    st.session_state["stk_watchlist"] = _wl_get_tickers(here, uid)
                    st.rerun()

    st.markdown("---")
    if "wl_show_add_account_form" not in st.session_state:
        st.session_state["wl_show_add_account_form"] = False
    if st.button("➕ 새 계정 추가하기", key="wl_btn_show_add_account", type="primary", use_container_width=True):
        st.session_state["wl_show_add_account_form"] = True
        st.rerun()

    if st.session_state.get("wl_show_add_account_form", False):
        with st.container(border=True):
            st.markdown("**새 계정 정보 입력**")
            new_nick = st.text_input("별명", key="wl_new_nick", placeholder="예: 민수")
            new_id = st.text_input("아이디", key="wl_new_id", placeholder="예: user_g 또는 minsu")
            new_pw = st.text_input("비밀번호", key="wl_new_pw", type="password", placeholder="비밀번호")
            c_save, c_cancel = st.columns(2)
            with c_save:
                if st.button("✅ 저장하고 추가", key="wl_btn_add_account_save", type="primary", use_container_width=True):
                    uid = new_id.strip()
                    nick = new_nick.strip()
                    ok, msg = _wl_register(here, uid, new_pw)
                    if not ok:
                        st.error(msg)
                    else:
                        prefix = _wl_next_quick_prefix(here)
                        label = f"{prefix} · {nick or uid}"
                        _wl_upsert_quick_label(here, uid, label)
                        st.success(f"{label} 계정이 추가되었습니다.")
                        st.session_state["wl_show_add_account_form"] = False
                        st.rerun()
            with c_cancel:
                if st.button("취소", key="wl_btn_add_account_cancel", use_container_width=True):
                    st.session_state["wl_show_add_account_form"] = False
                    st.rerun()

    st.divider()
    uid_in = st.text_input("아이디", key="wl_uid_login", placeholder="aaa")
    pw_in = st.text_input("비밀번호", key="wl_pw_login", type="password", placeholder="bbb")
    if st.button("로그인", key="wl_btn_login", type="primary", use_container_width=True):
        if _wl_login(here, uid_in.strip(), pw_in):
            st.session_state["wl_user"] = uid_in.strip()
            st.session_state["stk_watchlist"] = _wl_get_tickers(here, uid_in.strip())
            st.rerun()
        else:
            st.error("아이디 또는 비밀번호가 틀렸습니다.")


def _wl_render_register_form(here: Path) -> None:
    uid_r = st.text_input("아이디 (2자 이상)", key="wl_uid_reg", placeholder="원하는 아이디")
    pw_r = st.text_input("비밀번호", key="wl_pw_reg", type="password", placeholder="원하는 비밀번호")
    if st.button("회원가입", key="wl_btn_reg", type="primary", use_container_width=True):
        ok, msg = _wl_register(here, uid_r.strip(), pw_r)
        if ok:
            st.success(f"{msg} 상단 메뉴 **로그인**에서 로그인하세요.")
        else:
            st.error(msg)


def _render_wl_login_page(here: Path) -> None:
    st.header(_WL_NAV_LOGIN)
    cur = st.session_state.get("wl_user")
    if cur:
        st.success(f"이미 **{cur}** 님으로 로그인되어 있습니다.")
        if st.button("로그아웃", key="wl_page_login_logout"):
            del st.session_state["wl_user"]
            st.session_state.pop("stk_watchlist", None)
            st.rerun()
        st.caption("관심 목록은 **관심주식** 메뉴에서 확인하세요.")
        return
    st.caption(
        "관심 주식 저장에 사용합니다. 테스트 계정: `aaa` / `bbb` · "
        f"빠른 슬롯: `user_a`,`user_d`,`user_e`,`user_f` / `{_WL_PRESET_SLOT_PW}`"
    )
    with _st_try_border_container():
        st.markdown(
            "> 비밀번호는 `watchlist_data/users.json`에 **SHA-256 해시**로만 저장됩니다."
        )
    _wl_render_login_form(here)


def _render_wl_register_page(here: Path) -> None:
    st.header(_WL_NAV_REGISTER)
    if st.session_state.get("wl_user"):
        u = str(st.session_state["wl_user"])
        st.info(f"**{u}** 님으로 로그인 중입니다. 다른 계정을 만들려면 로그아웃하세요.")
        if st.button("로그아웃", key="wl_page_reg_logout"):
            del st.session_state["wl_user"]
            st.session_state.pop("stk_watchlist", None)
            st.rerun()
        return
    st.caption("아이디 2자 이상 · 비밀번호를 입력하세요.")
    _wl_render_register_form(here)


def _render_group_market(selected: str) -> None:
    """상단 메뉴에서 고른 한 화면만 렌더(시장 4종 + 로그인·회원가입)."""
    here = Path(__file__).resolve().parent
    opts = list(_SIDEBAR_NAV_OPTIONS)
    raw_selected = str(selected or "").strip()
    page_slug = str(st.session_state.get("page") or "").strip().lower()
    alias_to_full = {
        "오늘의픽": "오늘의 픽",
        "코스피": "코스피 스캐너",
        "코스닥": "코스닥 스캐너",
        "ETF": "ETF 스캐너",
        "관심": "관심주식",
        "로그인": _WL_NAV_LOGIN,
        "가입": _WL_NAV_REGISTER,
        "pick": "오늘의 픽",
        "kospi": "코스피 스캐너",
        "kosdaq": "코스닥 스캐너",
        "etf": "ETF 스캐너",
        "wl": "관심주식",
        "login": _WL_NAV_LOGIN,
        "join": _WL_NAV_REGISTER,
    }
    if raw_selected in opts:
        pick = raw_selected
    elif raw_selected in alias_to_full:
        pick = alias_to_full[raw_selected]
    elif page_slug in _PAGE_SLUG_TO_FULL:
        pick = _PAGE_SLUG_TO_FULL[page_slug]
    else:
        pick = _MARKET_NAV_OPTIONS[0]
    if pick == _WL_NAV_LOGIN:
        _render_wl_login_page(here)
    elif pick == _WL_NAV_REGISTER:
        _render_wl_register_page(here)
    elif pick == "오늘의 픽":
        _render_tab_daily_stock_picks()
    elif pick == "코스피 스캐너":
        _render_page_kospi()
    elif pick == "코스닥 스캐너":
        _render_page_kosdaq()
    elif pick == "ETF 스캐너":
        _render_page_etf()
    else:
        _render_tab_stock_watchlist()


def _render_tab_volume_radar() -> None:
    """📉 급등 예상 레이더 — 매물 물량 급락 지역 순위"""

    # ── 인사이트 배너 ──────────────────────────────────────────
    st.header("📉 급등 예상 지역 레이더")
    st.markdown(
        """
<div style="padding:0.9rem 1.1rem;border-radius:14px;
background:linear-gradient(135deg,rgba(99,102,241,0.28) 0%,rgba(15,12,60,0.85) 100%);
border-left:4px solid #6366f1;margin-bottom:0.8rem;">
<p style="margin:0 0 0.4rem;font-size:1.02rem;font-weight:700;color:#e0e7ff;">
🧠 물량 급락 → 급등 선행 신호 원리</p>
<p style="margin:0 0 0.3rem;color:#c7d2fe;font-size:0.93rem;">
<b>① 매물 급락</b> — 집주인이 매도를 거두고 보유로 전환 = 공급 감소<br>
<b>② 전세 급락</b> — 전세 씨가 마름 = 세입자가 매수 전환 또는 임대인이 매매 기대로 전환<br>
<b>③ 거래량 선행</b> — 거래량이 먼저 줄다가 다시 늘어나면 가격 상승 동행<br>
<b>④ 갭 축소</b> — 전세가율 상승 = 갭투자 부담 감소 → 수요 재유입</p>
<p style="margin:0;color:#a5b4fc;font-size:0.86rem;">
📌 실거래 거래 <b>건수 감소 후 반등</b>이 관측되는 지역이 가격 급등 선행 지역입니다.</p>
</div>
        """,
        unsafe_allow_html=True,
    )

    st.caption(
        "아파트 실거래·지도 바로가기는 **부동산 → 🔥 실거래 현황** 탭을 이용하세요. "
        "여기서는 물량·거래 변화를 직접 입력하거나(아래), 서버에 `MOLIT_API_KEY`가 있으면 API 자동 분석을 씁니다."
    )

    api_key = (
        (
            os.environ.get("MOLIT_API_KEY")
            or os.environ.get("DATA_GO_KR_SERVICE_KEY")
            or os.environ.get("APT_SERVICE_KEY")
            or ""
        )
        .strip()
    )
    if not api_key:
        st.caption(
            "국토부 거래량 자동 비교는 "
            "`MOLIT_API_KEY` / `DATA_GO_KR_SERVICE_KEY` / `APT_SERVICE_KEY` 설정 시에만 표시됩니다."
        )

    st.divider()

    # ── 수동 입력 레이더 (API 없이도 사용) ────────────────────
    st.subheader("🎯 지역별 물량 변화 직접 입력")
    st.caption("각 지역의 현재 매물 수 또는 거래 건수를 입력하면 급등 예상 순위를 계산합니다.")

    if "radar_data" not in st.session_state:
        st.session_state["radar_data"] = [
            {"지역": "서울 강남구", "전월": 120, "금월": 72},
            {"지역": "서울 서초구", "전월": 95,  "금월": 61},
            {"지역": "서울 송파구", "전월": 180, "금월": 134},
            {"지역": "서울 마포구", "전월": 88,  "금월": 75},
            {"지역": "경기 성남 분당", "전월": 210, "금월": 158},
        ]

    # 입력 테이블
    with _st_try_border_container():
        r_labels = ["전월 매물/거래수", "금월 매물/거래수"]
        edited_rows = []
        for idx, row in enumerate(st.session_state["radar_data"]):
            rc1, rc2, rc3, rc4 = st.columns([3, 2, 2, 1])
            with rc1:
                region = st.text_input("지역", value=row["지역"],
                                       key=f"radar_reg_{idx}",
                                       label_visibility="collapsed" if idx > 0 else "visible")
            with rc2:
                # 빈 label("") 는 일부 Streamlit 버전에서 number_input 예외 유발 → 동일 문구 + 상위 행만 표시
                prev_v = st.number_input(
                    r_labels[0],
                    min_value=0,
                    value=int(row["전월"]),
                    key=f"radar_prev_{idx}",
                    label_visibility="visible" if idx == 0 else "collapsed",
                )
            with rc3:
                curr_v = st.number_input(
                    r_labels[1],
                    min_value=0,
                    value=int(row["금월"]),
                    key=f"radar_curr_{idx}",
                    label_visibility="visible" if idx == 0 else "collapsed",
                )
            with rc4:
                if idx == 0:
                    st.markdown("<br>", unsafe_allow_html=True)
                if st.button("❌", key=f"radar_del_{idx}"):
                    st.session_state["radar_data"].pop(idx)
                    st.rerun()
            edited_rows.append({"지역": region, "전월": prev_v, "금월": curr_v})
        st.session_state["radar_data"] = edited_rows

        ac1, ac2 = st.columns([1, 4])
        with ac1:
            if st.button("➕ 지역 추가"):
                st.session_state["radar_data"].append(
                    {"지역": "새 지역", "전월": 100, "금월": 80})
                st.rerun()

    # ── 급등 예상 순위 계산 ──────────────────────────────────
    results = []
    for row in st.session_state["radar_data"]:
        prev, curr = row["전월"], row["금월"]
        if prev > 0:
            chg_pct = (curr - prev) / prev * 100
        else:
            chg_pct = 0.0
        results.append({
            "지역": row["지역"], "전월": prev, "금월": curr,
            "변화율": chg_pct,
            "점수": -chg_pct,  # 급락일수록 높은 점수
        })
    results.sort(key=lambda r: r["점수"], reverse=True)

    st.divider()
    st.subheader("🏆 급등 예상 지역 순위")
    st.caption("물량/거래 감소율이 클수록 상위 — 감소 후 반등 시 가격 상승 가능성 ↑")

    # 순위 카드
    rank_colors = ["#fbbf24", "#94a3b8", "#fb923c",
                   "#818cf8", "#34d399", "#60a5fa",
                   "#f472b6", "#a3e635"]
    for rank, r in enumerate(results, 1):
        chg   = r["변화율"]
        color = "#f87171" if chg <= -20 else ("#fbbf24" if chg <= -10 else "#34d399")
        badge = "🔴 강력 매수 신호" if chg <= -20 else ("🟡 주목" if chg <= -10 else "🟢 중립")
        rc = rank_colors[min(rank - 1, len(rank_colors) - 1)]
        bar_w = max(0, min(100, abs(chg) * 3))
        st.markdown(
            f"<div style='padding:0.55rem 0.75rem;margin-bottom:0.4rem;"
            f"background:rgba(15,12,60,0.55);border-radius:11px;"
            f"border-left:4px solid {rc};'>"
            f"<div style='display:flex;justify-content:space-between;align-items:center;'>"
            f"<span><b style='font-size:1.05rem;'>#{rank} {r['지역']}</b>"
            f"&nbsp;<span style='font-size:0.82rem;'>{badge}</span></span>"
            f"<span style='color:{color};font-size:1.1rem;font-weight:700;'>{chg:+.1f}%</span>"
            f"</div>"
            f"<div style='margin:0.3rem 0 0.1rem;"
            f"background:rgba(165,180,252,0.12);border-radius:4px;height:6px;'>"
            f"<div style='width:{bar_w}%;background:{color};"
            f"border-radius:4px;height:100%;'></div></div>"
            f"<span style='color:#94a3b8;font-size:0.8rem;'>"
            f"전월 {r['전월']:,} → 금월 {r['금월']:,} 건</span>"
            f"</div>",
            unsafe_allow_html=True,
        )

    # ── 막대 차트 ─────────────────────────────────────────────
    if go is not None and results:
        labels = [r["지역"] for r in results]
        chgs   = [r["변화율"] for r in results]
        colors = ["#f87171" if c <= -20 else "#fbbf24" if c <= -10 else "#34d399"
                  for c in chgs]

        fig_r = go.Figure()
        fig_r.add_trace(go.Bar(
            x=labels, y=chgs,
            marker=dict(color=colors, cornerradius=5,
                        line=dict(color="rgba(165,180,252,0.3)", width=0)),
            text=[f"{c:+.1f}%" for c in chgs],
            textposition="outside",
            hovertemplate="<b>%{x}</b><br>변화율: %{y:+.1f}%<extra></extra>",
        ))
        fig_r.add_hline(y=0, line=dict(color="rgba(165,180,252,0.4)", width=1))
        fig_r.update_layout(
            title=dict(text="<b>지역별 물량 변화율 (음수 = 급락)</b>",
                       font=dict(size=13, color="#e0e7ff"), x=0.02),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(15,12,60,0.25)",
            font=dict(color="#eef2ff", size=11),
            xaxis=dict(tickfont=dict(size=10), showgrid=False),
            yaxis=dict(title="변화율 (%)", ticksuffix="%",
                       tickfont=dict(size=10),
                       gridcolor="rgba(165,180,252,0.09)"),
            margin=dict(l=8, r=8, t=44, b=60),
            height=280,
            showlegend=False,
            hovermode="x",
            hoverlabel=dict(bgcolor="rgba(15,12,60,0.92)",
                            font=dict(size=11, color="#eef2ff")),
        )
        st.plotly_chart(fig_r, use_container_width=True,
                        config={"displayModeBar": False})

    # ── API 연동 자동 분석 ────────────────────────────────────
    if api_key:
        st.divider()
        st.subheader("🤖 API 자동 분석 (국토부 실거래 거래량 비교)")
        st.caption("선택한 두 달의 거래 건수를 비교해 급락 지역을 자동 탐색합니다.")

        from datetime import date as _date  # noqa: PLC0415
        today = _date.today()

        # 시도 선택 → 해당 시도의 전체 시군구를 멀티셀렉트
        radar_sido = st.selectbox("시/도 선택", list(_SIDO_MAP.keys()),
                                  key="radar_sido")
        radar_sido_code = _SIDO_MAP[radar_sido]
        radar_sigungu_all = list(_SIGUNGU_MAP.get(radar_sido_code, {}).keys())

        # ── sido 이름을 key에 포함 → sido 변경 시 완전히 새 멀티셀렉트 렌더링 ──
        ms_key = f"radar_sg_multi_{radar_sido}"
        default_pick = radar_sigungu_all[:min(6, len(radar_sigungu_all))]
        cmp_sigungu = st.multiselect(
            "비교할 시/군/구 선택 (복수 가능)",
            radar_sigungu_all,
            default=default_pick,
            key=ms_key,
        )
        # 코드 변환
        sg_map = _SIGUNGU_MAP.get(radar_sido_code, {})
        cmp_regions_labeled = [(f"{radar_sido} {sg}", sg_map[sg])
                               for sg in cmp_sigungu if sg in sg_map]

        ac2, ac3 = st.columns(2)
        with ac2:
            base_ym = st.selectbox(
                "기준월 (전월)",
                [f"{today.year}{m:02d}" if m <= today.month
                 else f"{today.year-1}{m:02d}"
                 for m in range(today.month, today.month - 6, -1)],
                index=1, key="radar_base_ym",
                format_func=lambda s: f"{s[:4]}년 {s[4:]}월",
            )
        with ac3:
            comp_ym = st.selectbox(
                "비교월 (금월)",
                [f"{today.year}{m:02d}" if m <= today.month
                 else f"{today.year-1}{m:02d}"
                 for m in range(today.month, today.month - 6, -1)],
                index=0, key="radar_comp_ym",
                format_func=lambda s: f"{s[:4]}년 {s[4:]}월",
            )

        if st.button("🔍 거래량 자동 분석 실행", key="radar_run"):
            auto_results = []
            total = len(cmp_regions_labeled)
            prog = st.progress(0)
            for i, (label, code) in enumerate(cmp_regions_labeled):
                with st.spinner(f"{label} 조회 중…"):
                    base_rows = _fetch_molit_trade(code, base_ym, api_key, num_rows=100)
                    comp_rows = _fetch_molit_trade(code, comp_ym, api_key, num_rows=100)
                base_cnt = len(base_rows)
                comp_cnt = len(comp_rows)
                if base_cnt > 0:
                    chg_pct = (comp_cnt - base_cnt) / base_cnt * 100
                    auto_results.append({
                        "지역": label, "전월": base_cnt, "금월": comp_cnt,
                        "변화율": chg_pct,
                    })
                prog.progress((i + 1) / max(total, 1))

            prog.empty()
            auto_results.sort(key=lambda r: r["변화율"])
            st.session_state["radar_auto_results"] = auto_results

        if "radar_auto_results" in st.session_state:
            auto_r = st.session_state["radar_auto_results"]
            st.markdown("#### 자동 분석 결과")
            for rank, r in enumerate(auto_r, 1):
                chg = r["변화율"]
                badge = "🔴 물량 급락" if chg <= -20 else ("🟡 감소" if chg <= -10 else "🟢 유지")
                color = "#f87171" if chg <= -20 else "#fbbf24" if chg <= -10 else "#34d399"
                st.markdown(
                    f"<div style='padding:0.45rem 0.7rem;margin-bottom:0.35rem;"
                    f"background:rgba(15,12,60,0.5);border-radius:9px;"
                    f"border-left:3px solid {color};display:flex;"
                    f"justify-content:space-between;'>"
                    f"<span><b>#{rank} {r['지역']}</b> {badge}</span>"
                    f"<span style='color:{color};font-weight:700;'>"
                    f"{r['변화율']:+.1f}%"
                    f" ({r['전월']}건→{r['금월']}건)</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    # ── 참고 지표 설명 ────────────────────────────────────────
    st.divider()
    with st.expander("📚 급등 예상 판단 기준 가이드", expanded=False):
        st.markdown("""
**매물 감소 해석 기준 (경험 법칙)**

| 변화율 | 신호 | 행동 제안 |
|---|---|---|
| **-30% 이상** | 🔴 강력 매수 신호 | 단기 급등 가능성 높음 · 현장 확인 필수 |
| **-20% ~ -30%** | 🟠 매수 고려 | 공급 감소 진행 중 · 모니터링 강화 |
| **-10% ~ -20%** | 🟡 주목 | 추세 전환 가능성 · 관심 단지 점검 |
| **0% ~ -10%** | 🟢 중립 | 현재 안정적 |
| **0% 이상** | ⬆️ 공급 증가 | 당분간 가격 하락 압력 가능 |

**함께 봐야 할 지표**
- **전세가율**: 70% 이상이면 갭투자 수요 유입 가능
- **준공 예정 물량**: 향후 2년 내 대규모 입주 예정 지역은 주의
- **인구 순이동**: 전입 > 전출 지역이 수요 기반 확실
- **금리 방향**: 금리 하락 시 고LTV 지역 수혜 집중

**실까 앱 / 아파트미 활용**
→ [실까](https://naver.me/xEX1mw8c): 실거래가 공개 즉시 반영 · 신고가 알림
→ [아파트미](https://apt2.me/apt/AptMonthBfSin.jsp): 반등 실거래 목록 (직전 최저 대비 상승)
→ [아실](https://asil.kr): 매물 수 변화 트래킹
""")


def _load_apt_export_payload() -> tuple[dict[str, Any] | None, Any]:
    """`apt/SynologyDrive` 배치 export 결과(JSON + charts/) 경로 탐색."""
    import json
    from pathlib import Path

    here = Path(__file__).resolve().parent
    paths: list[Path] = []
    rjson = (os.environ.get("APT_RESULTS_JSON") or "").strip()
    pdir = (os.environ.get("APT_PAYLOAD_DIR") or "").strip()
    export_dir = (os.environ.get("EXPORT_DIR") or "").strip()
    if rjson:
        paths.append(Path(rjson))
    for d in (pdir, export_dir):
        if d:
            base = Path(d)
            paths.extend(
                [base / "results_web.json", base / "nas_web_payload_apt" / "results_web.json"]
            )
    paths.extend(
        [
            here / "apt_data" / "results_web.json",
        ]
    )
    seen: set[str] = set()
    for p in paths:
        rp = str(p.resolve()) if p.exists() else str(p)
        if rp in seen:
            continue
        seen.add(rp)
        try:
            if p.is_file():
                with open(p, encoding="utf-8") as f:
                    return json.load(f), p.parent
        except (OSError, json.JSONDecodeError, ValueError):
            continue
    return None, None


def _render_tab_apt_export_dashboard() -> None:
    """@apt 배치 분석 리포트 — `apt_data/` 동기화 또는 APT_RESULTS_JSON / APT_PAYLOAD_DIR."""
    from pathlib import Path

    payload, root = _load_apt_export_payload()
    st.header("🏢 APT 거시·단지 리포트")
    st.caption(
        "배치: 이 폴더에서 **`py -3 run_portal_batch.py`** (또는 **`run_portal_batch.cmd`**). "
        "APT는 **하루 1회**만 갱신되고, 나머지는 매 회 실행됩니다. "
        "별도 경로: **APT_RESULTS_JSON** / **EXPORT_DIR** / **APT_PAYLOAD_DIR**."
    )
    if not payload:
        st.info("표시할 APT 분석 파일이 없습니다. 위 경로로 동기화하면 이 탭에 요약·차트가 나타납니다.")
        return

    st.markdown(f"**마지막 분석:** {payload.get('last_analysis_time') or '-'}")

    apts = payload.get("apts") or []
    rs = payload.get("region_summary") or []
    t_sale, t_jeonse = st.tabs(["🏢 APT 리포트", "🔑 전세 리포트"])

    def _apt_soft_gray_styler(df):
        if pd is None:
            return df
        return (
            df.style.set_table_styles(
                [
                    {
                        "selector": "thead th",
                        "props": [
                            ("background-color", "#e5e7eb"),
                            ("color", "#111827"),
                            ("font-weight", "700"),
                            ("border", "1px solid #d1d5db"),
                        ],
                    },
                    {
                        "selector": "tbody td",
                        "props": [
                            ("background-color", "#f3f4f6"),
                            ("color", "#111827"),
                            ("border", "1px solid #e5e7eb"),
                        ],
                    },
                    {
                        "selector": "tbody tr:nth-child(even) td",
                        "props": [("background-color", "#eef2f7")],
                    },
                ]
            )
            .set_properties(**{"font-size": "0.9rem"})
            .format(na_rep="-")
        )

    with t_sale:
        if apts:
            rows = []
            for a in apts:
                mom = a.get("mom_pct")
                chg = a.get("change_pct")
                tc = int(a.get("trade_count") or 0)
                size = int(a.get("size") or 0)
                density = round(tc / size, 4) if size > 0 else None
                if mom is None:
                    trend = "—"
                else:
                    mv = float(mom)
                    trend = "상승" if mv >= 2 else ("하락" if mv <= -2 else "횡보")
                rows.append(
                    {
                        "권역": (a.get("cluster_label") or "")[:30],
                        "구": a.get("sigungu", ""),
                        "단지": a.get("disp_name", ""),
                        "MoM%": None if mom is None else round(float(mom), 2),
                        "누적%": None if chg is None else round(float(chg), 2),
                        "최신(억)": a.get("latest_price_eok"),
                        "거래": tc,
                        "거래밀도": density,
                        "추세": trend,
                        "비교": a.get("mom_label", ""),
                    }
                )
            st.subheader("대장 단지 요약")
            st.caption("추가 지표: 거래밀도(거래수/세대수), 추세(MoM 기준 상승·횡보·하락)")
            if pd is not None:
                st.dataframe(_apt_soft_gray_styler(pd.DataFrame(rows)), use_container_width=True, hide_index=True)
            else:
                st.json(rows[:30])

        if rs:
            st.subheader("지역별 요약 대시보드")
            st.caption("지역 카드를 누르면 하단에 해당 지역 단지 차트가 표시됩니다.")
            cards = sorted(
                rs,
                key=lambda r: int(r.get("trade_count") or 0),
                reverse=True,
            )
            region_labels = [str(r.get("region") or "-") for r in cards]
            if region_labels and "apt_region_selected" not in st.session_state:
                st.session_state["apt_region_selected"] = region_labels[0]
            selected_region = st.session_state.get("apt_region_selected")
            cols_per_row = 4
            for i in range(0, len(cards), cols_per_row):
                row_items = cards[i : i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, r in zip(cols, row_items):
                    region = str(r.get("region") or "-")
                    trade_n = int(r.get("trade_count") or 0)
                    avg_eok = r.get("avg_price_eok")
                    districts = r.get("districts") or []
                    gu_n = len(districts)
                    top_gu = ""
                    if districts:
                        top_sorted = sorted(
                            districts,
                            key=lambda d: float(d.get("avg_price_eok") or 0),
                            reverse=True,
                        )
                        top_gu = str((top_sorted[0] or {}).get("name") or "")
                    with col:
                        is_sel = region == selected_region
                        st.markdown(
                            f"""
<div style="border:1px solid {'#93c5fd' if is_sel else '#dbe4f0'};border-radius:14px;padding:0.75rem 0.85rem;background:#ffffff;
box-shadow:0 1px 3px rgba(15,23,42,0.08);min-height:125px;">
  <div style="font-weight:800;color:#0f172a;font-size:1.05rem;">{region}</div>
  <div style="margin-top:0.15rem;color:#1e293b;font-size:0.95rem;"><b>{trade_n:,}</b>건</div>
  <div style="margin-top:0.2rem;color:#2563eb;font-size:0.9rem;">평균 <b>{avg_eok if avg_eok is not None else '-'}억</b></div>
  <div style="margin-top:0.2rem;color:#475569;font-size:0.84rem;">주요 구 {gu_n}곳</div>
  <div style="margin-top:0.1rem;color:#64748b;font-size:0.82rem;">TOP 구: {top_gu or '-'}</div>
</div>
                            """,
                            unsafe_allow_html=True,
                        )
                        if st.button(
                            f"{'선택됨' if is_sel else '이 지역 보기'} · {region}",
                            key=f"apt_region_btn_{region}",
                            use_container_width=True,
                        ):
                            st.session_state["apt_region_selected"] = region
                            selected_region = region

            with st.expander("표 형태로 보기", expanded=False):
                flat = [
                    {
                        "지역": r.get("region"),
                        "평균(억)": r.get("avg_price_eok"),
                        "거래수": r.get("trade_count"),
                        "주요구수": len(r.get("districts") or []),
                    }
                    for r in rs
                ]
                if pd is not None:
                    st.dataframe(pd.DataFrame(flat), use_container_width=True, hide_index=True)
                else:
                    st.json(flat)

    with t_jeonse:
        api_key = (
            (
                os.environ.get("MOLIT_API_KEY")
                or os.environ.get("DATA_GO_KR_SERVICE_KEY")
                or os.environ.get("APT_SERVICE_KEY")
                or ""
            ).strip()
        )
        if not api_key:
            st.info(
                "전세 리포트 자동 생성은 서버에 "
                "`MOLIT_API_KEY` / `DATA_GO_KR_SERVICE_KEY` / `APT_SERVICE_KEY` "
                "중 하나가 있을 때 표시됩니다."
            )
        elif not apts:
            st.info("APT 리포트 데이터가 없어 전세 리포트를 계산할 수 없습니다.")
        else:
            from datetime import date as _date  # noqa: PLC0415

            deal_ymd = _date.today().strftime("%Y%m")
            # 거래 많은 지역 우선 4개만 조회해 API 부하 최소화
            top_sigungu = sorted(
                {(str(a.get("region") or ""), str(a.get("sigungu") or "")) for a in apts if a.get("sigungu")},
                key=lambda x: -sum(int(k.get("trade_count") or 0) for k in apts if str(k.get("region") or "") == x[0] and str(k.get("sigungu") or "") == x[1]),
            )[:4]

            summary_rows: list[dict[str, Any]] = []
            top_rows: list[dict[str, Any]] = []
            for region, sigungu in top_sigungu:
                s_code = _SIDO_MAP.get(region)
                if not s_code:
                    continue
                lawd_cd = (_SIGUNGU_MAP.get(s_code) or {}).get(sigungu)
                if not lawd_cd:
                    continue
                rr = _fetch_molit_rent(lawd_cd=lawd_cd, deal_ymd=deal_ymd, api_key=api_key, num_rows=200)
                jeonse = [r for r in rr if int(r.get("월세") or 0) == 0]
                if not jeonse:
                    continue
                deps = [int(r.get("보증금") or 0) for r in jeonse if int(r.get("보증금") or 0) > 0]
                if not deps:
                    continue
                deps_sorted = sorted(deps)
                mid = len(deps_sorted) // 2
                med = deps_sorted[mid]
                avg = int(sum(deps_sorted) / len(deps_sorted))
                summary_rows.append(
                    {
                        "지역": region,
                        "구": sigungu,
                        "전세건수": len(jeonse),
                        "전세 중앙값(만)": med,
                        "전세 평균(만)": avg,
                    }
                )
                for r in jeonse[:5]:
                    top_rows.append(
                        {
                            "지역": region,
                            "구": sigungu,
                            "단지": r.get("단지명", ""),
                            "전세(만)": int(r.get("보증금") or 0),
                            "전용면적": r.get("전용면적", ""),
                            "거래일": f"{r.get('년','')}-{str(r.get('월','')).zfill(2)}-{str(r.get('일','')).zfill(2)}",
                        }
                    )
            st.subheader("전세 지역 요약")
            st.caption(f"기준월: {deal_ymd} · APT 리포트 상위 거래 지역 중심")
            if summary_rows:
                if pd is not None:
                    st.dataframe(pd.DataFrame(summary_rows), use_container_width=True, hide_index=True)
                else:
                    st.json(summary_rows)
                st.subheader("전세 상위 단지")
                if pd is not None:
                    st.dataframe(pd.DataFrame(top_rows[:40]), use_container_width=True, hide_index=True)
                else:
                    st.json(top_rows[:40])
            else:
                st.info("조회 지역에서 전세 데이터를 찾지 못했습니다.")

    if root is not None:
        charts_dir = Path(root) / "charts"
        if charts_dir.is_dir() and apts:
            st.subheader("단지 추세 차트")
            valid_pairs: list[tuple[dict[str, Any], Path]] = []
            for a in apts:
                ch = a.get("chart")
                if not ch:
                    continue
                fp = charts_dir / ch
                if fp.is_file():
                    valid_pairs.append((a, fp))
            selected_region = st.session_state.get("apt_region_selected")
            selected_pairs = [
                (a, fp) for (a, fp) in valid_pairs if str(a.get("region") or "") == str(selected_region or "")
            ]
            if selected_region and selected_pairs:
                st.markdown(f"**선택 지역:** {selected_region}")
                for a, fp in selected_pairs:
                    st.caption(f"{a.get('disp_name', '')} · {a.get('sigungu', '')}")
                    st.image(str(fp), use_container_width=True)
                st.divider()
            for i, (a, fp) in enumerate(valid_pairs):
                if i < 6:
                    st.caption(a.get("disp_name", ""))
                    st.image(str(fp), use_container_width=True)
            if len(valid_pairs) > 6:
                with st.expander(f"차트 더 보기 ({len(valid_pairs) - 6}개)", expanded=False):
                    for a, fp in valid_pairs[6:]:
                        st.caption(a.get("disp_name", ""))
                        st.image(str(fp), use_container_width=True)


def _render_group_realty() -> None:
    """🏘 부동산 그룹: APT리포트·실거래·급등레이더·계산기·관심단지"""
    t1, t2, t3, t4, t5 = st.tabs([
        "🏢 APT 리포트",
        "🔥 실거래 현황", "📉 급등 레이더", "🧮 부동산 계산기", "🏘 관심 단지",
    ])

    _TAB_FUNCS = [
        ("🏢 APT 리포트", _render_tab_apt_export_dashboard),
        ("🔥 실거래 현황", _render_tab_apt_market),
        ("📉 급등 레이더", _render_tab_volume_radar),
        ("🧮 부동산 계산기", _render_tab_real_estate_calc),
        ("🏘 관심 단지",   _render_tab_apt_watchlist),
    ]
    for tab_ctx, (tab_name, fn) in zip([t1, t2, t3, t4, t5], _TAB_FUNCS):
        with tab_ctx:
            try:
                fn()
            except Exception as _e:
                import traceback as _tb  # noqa: PLC0415
                st.error(f"**[{tab_name}] 렌더링 오류** — {_e}")
                with st.expander("오류 상세"):
                    st.code(_tb.format_exc(), language="python")


def _render_group_life() -> None:
    """🌤️ 생활 그룹: 날씨·뉴스·컴퓨터 가이드"""
    t1, t2, t3 = st.tabs(["🌤️ 날씨", "📰 뉴스", "💻 컴퓨터"])
    with t1:
        _render_tab_weather()
    with t2:
        _render_tab_news()
    with t3:
        _render_tab_life_pc()


def _render_group_hobby() -> None:
    """🎯 취미 그룹: 골프·캠핑·세차·수집 등"""
    st.header("🎯 취미")
    st.caption("골프·캠핑·세차·40대 남성층에 흔한 취미 축·피규어 등 **참고용** 정보입니다.")
    h1, h2, h3, h4, h5 = st.tabs(
        ["⛳ 골프", "🏕️ 캠핑", "🚿 세차·케어", "🧔 40대 남성 인기 취미", "🎨 피규어·수집"],
    )
    with h1:
        _render_tab_golf()
    with h2:
        _render_tab_camping()
    with h3:
        _render_tab_car_wash()
    with h4:
        _render_tab_hobby_men40()
    with h5:
        _render_tab_figures()


def _render_group_dev() -> None:
    """🐙 개발 그룹: IT·테크 잡학 + GitHub"""
    st.header("🐙 개발 · IT·테크")
    st.caption("뉴스·도구·클라우드·보안·GitHub까지 **잡다한 IT** 참고용입니다. (만화·웹툰은 **기타** 탭으로 옮겼습니다.)")
    d1, d2, d3, d4, d5 = st.tabs(
        ["📡 IT 뉴스·동향", "🛠️ 도구·환경", "☁️ 클라우드·인프라", "🔐 보안·프라이버시", "🐙 GitHub 덴"],
    )
    with d1:
        _render_tab_it_news_trends()
    with d2:
        _render_tab_it_tooling()
    with d3:
        _render_tab_it_cloud_infra()
    with d4:
        _render_tab_it_security_privacy()
    with d5:
        _render_tab_github()


def _render_group_shop() -> None:
    """🛍️ 쇼핑 그룹: 화장품·컴퓨터 가격비교"""
    t1, t2 = st.tabs(["💄 화장품", "💻 컴퓨터"])
    with t1:
        _render_tab_cosmetics_compare()
    with t2:
        _render_tab_pc_compare()


def _render_group_auto() -> None:
    """🚗 자동차: 인기 차종 평가·셀토스·옵션·정비·EV·타이어"""
    st.header("🚗 자동차 · 신차 옵션 가이드")
    st.caption(
        "커뮤니티·장기 사용 후기에서 자주 보이는 **평가 경향**을 요약한 참고용입니다. "
        "출고가·트림명·프로모션은 **기아·대리점·공식 카탈로그**를 기준으로 하세요."
    )
    t1, t2, t3, t4, t5 = st.tabs(
        [
            "🔥 인기 차종 평가",
            "🚙 기아 셀토스",
            "⚙️ 옵션 추천",
            "🛠️ 정비·전기차·타이어",
            "🔗 리뷰·비교 사이트",
        ]
    )
    with t1:
        _car_model_labels = [row.get("모델", "") for row in CAR_POPULAR_MODEL_SUMMARY if row.get("모델")]
        _pick = st.selectbox(
            "차종을 선택하면 **특징·추천**을 자세히 볼 수 있습니다.",
            options=_car_model_labels,
            index=0,
            key="auto_popular_model_pick",
        )
        st.markdown("##### 요약 표")
        if pd is not None:
            st.dataframe(pd.DataFrame(CAR_POPULAR_MODEL_SUMMARY), use_container_width=True, hide_index=True)
        else:
            for row in CAR_POPULAR_MODEL_SUMMARY:
                with _st_try_border_container():
                    st.markdown(f"**{row.get('모델', '')}** · {row.get('세그먼트', '')}")
                    st.markdown(f"- 잘 받는 평: {row.get('만족 포인트', '')}")
                    st.markdown(f"- 흔한 지적: {row.get('흔한 지적', '')}")
                    st.markdown(f"- 옵션: {row.get('옵션 팁', '')}")
        _detail = CAR_MODEL_DETAILS.get(_pick or "")
        if _detail:
            st.divider()
            st.markdown(f"##### **{_pick}** — 상세")
            st.markdown("**특징**")
            st.markdown(_detail.get("특징", "—"))
            st.markdown("**이런 분께 추천·구매 시 참고**")
            st.markdown(_detail.get("추천", "—"))
        else:
            st.caption("이 차종에 대한 상세 문구가 없습니다. `CAR_MODEL_DETAILS`에 키를 추가하세요.")
        st.info(
            "특정 연식·엔진에서는 평가가 갈릴 수 있습니다. **시승·견적 2~3곳**이 가장 빠른 판단 기준입니다.",
            icon="💡",
        )
    with t2:
        st.markdown("**기아 셀토스**를 염두에 둔 경우에만 읽어도 되는 요약입니다.")
        st.markdown(CAR_SELTOS_FOCUS_MARKDOWN)
        with st.expander("셀토스 구매 전 짧은 체크리스트", expanded=True):
            checks = (
                "뒷좌석 무릎·머리 공간, 트렁크에 유모차·캐리어 적재 테스트",
                "야간 주차: 어댑티드/일반 헤드램프, 후진·주차 시 UI 가독성",
                "주유(또는 충전) 위치·캡 개폐, 연비·주행 가능 거리 체감",
                "보험료 견적(같은 운전자 조건으로 타 차종과 비교)",
                "할부 조건(금리·중도상환·캐시백) 숫자로 정리",
            )
            for i, c in enumerate(checks):
                st.checkbox(c, key=f"seltos_chk_{i}")
        st.caption("체크리스트는 브라우저 세션에만 저장되며 서버로 전송되지 않습니다.")
    with t3:
        if pd is not None:
            st.dataframe(pd.DataFrame(CAR_OPTION_GUIDE_ROWS), use_container_width=True, hide_index=True)
        else:
            for row in CAR_OPTION_GUIDE_ROWS:
                st.markdown(f"**{row['상황']}**")
                st.caption(row["추천 우선순위"])
                st.caption(f"덜 우선: {row['덜 우선']}")
        st.markdown(
            "##### 패키지 고를 때 한 줄 규칙\n"
            "- **안전·운전 보조**는 되돌리기 어렵고, 매각·타인 탑승 시에도 이득인 경우가 많습니다.\n"
            "- **휠·외관**은 취향이지만 타이어 비용·편의성에 영향합니다.\n"
            "- **내장 색**은 중고 매물에서 수요 차이가 날 수 있습니다."
        )
    with t4:
        st.markdown("##### 시기·주기별 정비 체크(참고)")
        st.caption(
            "차종·주행 환경·매뉴얼에 따라 간격이 다릅니다. 아래는 **일반적인 점검 흐름** — 최종은 차량 매뉴얼·제조사 권장 주기를 따르세요."
        )
        if pd is not None:
            st.dataframe(pd.DataFrame(CAR_MAINTENANCE_BY_TIMING), use_container_width=True, hide_index=True)
        else:
            for row in CAR_MAINTENANCE_BY_TIMING:
                st.markdown(f"**{row.get('시기·주기', '')}**")
                st.caption(row.get("점검·작업", ""))
                st.caption(row.get("메모", ""))
        st.divider()
        st.markdown("##### 전기차(EV)")
        st.markdown(CAR_EV_GUIDE_MARKDOWN)
        st.divider()
        st.markdown("##### 타이어·교체 꿀팁(코스트코 등)")
        st.markdown(CAR_TIRE_TIPS_MARKDOWN)
    with t5:
        for p in CAR_REVIEW_PORTALS:
            st.markdown(f"- [{p['t']}]({p['u']}) — {p['d']}")


def _render_group_misc() -> None:
    """✈️ 여행·챗봇·만화 그룹"""
    t1, t2, t3 = st.tabs(["🗺️ 여행 스케치", "💬 AI 에이전트", "📖 만화·웹툰"])
    with t1:
        _render_tab_travel_mock()
    with t2:
        _render_tab_agent()
    with t3:
        _render_tab_comics()


_HOME_GROUP_DISPATCH: dict[str, Any] = {
    # 홈 포털에서 시장만 단독 렌더 시 사이드바 없음 → 첫 항목(오늘의 픽) 고정
    "market": lambda: _render_group_market(_MARKET_NAV_OPTIONS[0]),
    "realty": _render_group_realty,
    "life":   _render_group_life,
    "hobby":  _render_group_hobby,
    "dev":    _render_group_dev,
    "shop":   _render_group_shop,
    "auto":   _render_group_auto,
    "misc":   _render_group_misc,
}


def _sidebar_travel_country_picker(nav_selected: str) -> None:
    """홈 메뉴일 때 사이드바에 여행 선택 상태 표시(본 선택은 «여행 스케치» 탭 상단)."""
    if nav_selected != "홈":
        return
    countries = list(TRAVEL_MOCK_BY_COUNTRY.keys())
    cur = st.session_state.get("travel_mock_country_name")
    if cur not in TRAVEL_MOCK_BY_COUNTRY:
        cur = countries[0]
    with st.sidebar:
        st.divider()
        st.markdown("##### 🗺️ 여행 스케치")
        st.caption("국가는 메인 화면 **«여행 스케치» 탭** 상단에서 고릅니다.")
        st.info(f"현재 선택: **{cur}**")


def _sidebar_nav_select() -> str:
    """`streamlit_option_menu` 또는 라디오 폴백."""
    opts = list(_NAV_OPTIONS)
    with st.sidebar:
        if option_menu is not None:
            sel = option_menu(
                menu_title="메뉴",
                options=opts,
                icons=[
                    "house", "graph-up-arrow", "pin-map", "chat-quote",
                    "fire", "journal-text", "book", "globe2",
                    "lightbulb", "egg-fried", "shop", "shield-check",
                    "cpu", "hammer", "flower1", "gavel", "heart-pulse", "activity",
                ],
                menu_icon="compass",
                default_index=0,
                styles=_OPTION_MENU_STYLES,
            )
            return str(sel)
        return str(
            st.radio(
                "메뉴",
                options=opts,
                index=0,
                key="nav_fallback_radio",
            )
        )


def _nav_slug_from_query() -> str:
    """URL 쿼리 `p` 한 값(소문자 슬러그). 미지원·오류 시 빈 문자열."""
    if not hasattr(st, "query_params"):
        return ""
    try:
        v = st.query_params.get("p")
    except Exception:
        return ""
    if v is None:
        return ""
    if isinstance(v, (list, tuple)):
        return str(v[0] if v else "").strip().lower()
    return str(v).strip().lower()


def _sync_topbar_nav_from_query_params() -> None:
    """`?p=pick|kospi|...` 가 있으면 상단 메뉴 세션과 맞춤. 없으면 메인(오늘의픽)으로 간주."""
    slug = _nav_slug_from_query()
    if slug in _NAV_QUERY_SLUG_TO_SHORT:
        st.session_state["app_nav_short"] = _NAV_QUERY_SLUG_TO_SHORT[slug]
        st.session_state["page"] = slug
    elif not slug:
        st.session_state["app_nav_short"] = _TOPBAR_NAV_SHORT[0]
        st.session_state["page"] = "pick"


def _render_topbar_nav_select() -> str:
    """실까(silgga.com) 형태: 상단 한 줄에서 브랜드는 왼쪽, 메뉴(바)는 오른쪽에 모음."""
    shorts = _TOPBAR_NAV_SHORT
    if hasattr(st, "query_params"):
        _sync_topbar_nav_from_query_params()
    st.session_state.setdefault("app_nav_short", shorts[0])
    cur = str(st.session_state.get("app_nav_short") or shorts[0])
    if cur not in _TOPBAR_SHORT_TO_PAGE:
        cur = shorts[0]
        st.session_state["app_nav_short"] = cur
    with _st_try_border_container():
        # 가중치: 중간 여백(c_sp)으로 메뉴 버튼을 화면 오른쪽으로 밀어 붙임
        c_brand, c_sp, c1, c2, c3, c4, c5, c6, c7 = st.columns(
            [2.0, 3.2, 1, 1, 1, 1, 1, 1, 1],
        )
        with c_brand:
            st.markdown(
                """
<p style="margin:0;font-size:1.22rem;font-weight:800;letter-spacing:-0.04em;color:#0f172a;line-height:1.15;">
오늘의<span style="color:#2563eb;">픽</span>
</p>
<p style="margin:0.12rem 0 0;font-size:0.74rem;color:#64748b;line-height:1.25;">
코스피·코스닥·ETF Stage2 · 관심주식
</p>
""",
                unsafe_allow_html=True,
            )
        with c_sp:
            st.empty()
        for i, short in enumerate(shorts):
            col = (c1, c2, c3, c4, c5, c6, c7)[i]
            with col:
                btn_type = "primary" if cur == short else "secondary"
                if st.button(
                    short,
                    key=f"app_topnav_{short}",
                    use_container_width=True,
                    type=btn_type,
                ):
                    st.session_state["app_nav_short"] = short
                    st.session_state["page"] = _TOPBAR_SHORT_TO_SLUG.get(short, "pick")
                    if hasattr(st, "query_params"):
                        try:
                            st.query_params["p"] = _TOPBAR_SHORT_TO_SLUG.get(short, "pick")
                        except Exception:
                            pass
                    st.rerun()
        u = st.session_state.get("wl_user")
        if u:
            cap_txt = f"<b>{html.escape(str(u))}</b> 로그인 중"
        else:
            cap_txt = "비로그인 — 관심 저장은 로그인 후"
        st.markdown(
            f'<p style="text-align:right;margin:0.15rem 0 0;font-size:0.78rem;color:#64748b;">{cap_txt}</p>',
            unsafe_allow_html=True,
        )
    return _TOPBAR_SHORT_TO_PAGE[str(st.session_state.get("app_nav_short") or shorts[0])]


@contextmanager
def _portal_page_card() -> Iterator[None]:
    """메인 영역 카드 셸 — `st.container(border=True)` + main() 내 포털 카드 CSS."""

    shell = _st_try_border_container()
    with shell:
        yield


def _render_page_education_regions() -> None:
    """🎓 학군·교육 지역 — edu_data/regions.json → results_web.json"""
    import threading
    import sys
    from pathlib import Path

    st.header("🎓 학군·교육 지역")
    st.caption(
        "지역별 **샘플 지표**는 참고용입니다. 데이터는 **edu_data/regions.json**에서 편집한 뒤 내보내기 하세요."
    )
    HERE = Path(__file__).resolve().parent
    DATA_DIR = HERE / "edu_data"
    RESULTS_JSON = DATA_DIR / "results_web.json"
    DATA_DIR.mkdir(exist_ok=True)

    metric_label_map = {
        "capital_4yr_share_pct": "수도권 4년제 진학률(%)",
        "seoul_4yr_share_pct": "서울권 4년제 진학률(%)",
        "private_edu_monthly_10kkrw": "사교육비(월, 만원)",
        "living_cost_index_natl100": "생활비 지수(전국=100)",
        "school_satisfaction_5": "학교 만족도(5점)",
        "school_safety_5": "학교 안전 체감(5점)",
        "academy_access_5": "학원 접근성(5점)",
        "commute_convenience_5": "통학 편의성(5점)",
        "year": "기준연도",
    }

    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        from education_export_core import run_education_export  # noqa: PLC0415

        _edu_ok = True
    except Exception as e:
        st.error(f"education_export_core 임포트 실패: {e}")
        _edu_ok = False
        run_education_export = None  # type: ignore[misc, assignment]

    scan_key, err_key = "edu_data_scanning", "edu_data_error"
    if scan_key not in st.session_state:
        st.session_state[scan_key] = False
    if err_key not in st.session_state:
        st.session_state[err_key] = None

    c1, c2 = st.columns([1, 4])
    with c1:
        go = st.button(
            "📤 내보내기",
            key="btn_edu_export",
            disabled=st.session_state[scan_key] or not _edu_ok,
            use_container_width=True,
        )
    with c2:
        if st.session_state[scan_key]:
            st.info("처리 중…", icon="⏳")
        elif RESULTS_JSON.is_file():
            ts = _file_mtime_str_kst(RESULTS_JSON, "%Y-%m-%d %H:%M")
            st.success(f"마지막 내보내기(KST): {ts}", icon="✅")

    if go and _edu_ok and run_education_export is not None:
        st.session_state[scan_key] = True
        st.session_state[err_key] = None

        def _run():
            try:
                run_education_export(str(DATA_DIR))
            except Exception as ex:
                st.session_state[err_key] = str(ex)
            finally:
                st.session_state[scan_key] = False

        threading.Thread(target=_run, daemon=True).start()
        st.rerun()

    if st.session_state.get(err_key):
        st.error(st.session_state[err_key])

    payload: dict[str, Any] | None = None
    if RESULTS_JSON.is_file():
        try:
            with open(RESULTS_JSON, encoding="utf-8") as f:
                payload = json.load(f)
        except Exception as e:
            st.warning(f"결과 로드 실패: {e}")

    regions = (payload or {}).get("regions") or []
    if not regions:
        rf = DATA_DIR / "regions.json"
        if rf.is_file():
            try:
                with open(rf, encoding="utf-8") as f:
                    regions = json.load(f)
            except Exception:
                regions = []
    if not regions:
        st.info("`edu_data/regions.json`이 비었거나 내보내기를 아직 하지 않았습니다.")
        return

    st.caption(f"지역 **{len(regions)}**개 · {(payload or {}).get('last_export_time', '')}")

    for r in regions:
        name = r.get("name", r.get("id", "?"))
        brief = r.get("parent_brief") or ""
        cluster = r.get("cluster", "")
        sig = f"{r.get('sido', '')} {r.get('sigungu', '')}".strip()
        metrics = r.get("metrics") or {}
        with _st_try_border_container():
            st.markdown(f"#### {name}")
            if cluster:
                st.caption(cluster)
            if sig:
                st.caption(sig)
            if brief:
                st.markdown(brief)
            if metrics:
                mcols = st.columns(min(4, max(1, len(metrics))))
                for i, (k, v) in enumerate(metrics.items()):
                    if k == "year":
                        continue
                    with mcols[i % len(mcols)]:
                        st.metric(metric_label_map.get(str(k), str(k)), str(v))


def _render_page_opic() -> None:
    """🗣 OPIC 학습 자료 뷰어 — opic_data/*.json"""
    from pathlib import Path

    st.header("🗣 OPIC 학습 허브")
    st.caption(
        "로컬 `opic_data/` JSON을 읽어 보여줍니다. "
        "면접 답안 참고용이며, 실제 시험 답변은 본인 경험 중심으로 바꿔 연습하세요."
    )

    here = Path(__file__).resolve().parent
    data_dir = here / "opic_data"

    def _load_json(name: str) -> dict[str, Any]:
        p = data_dir / name
        if not p.is_file():
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return d if isinstance(d, dict) else {}
        except (OSError, json.JSONDecodeError, ValueError):
            return {}

    materials = _load_json("materials.json")
    travel = _load_json("travel.json")
    library = _load_json("library.json")
    news = _load_json("it-news.json")

    t1, t2, t3, t4, t5 = st.tabs(
        ["📘 스크립트", "🧳 여행 토픽", "📚 문장·독서", "📖 추천도서", "📰 IT 뉴스"]
    )

    with t1:
        meta = materials.get("meta") or {}
        if meta:
            st.caption(
                f"레벨 목표: {meta.get('levelGoal', '-')} · 생성: {str(meta.get('generatedAt') or '')[:16]}"
            )
            if meta.get("blurb"):
                st.info(str(meta.get("blurb")))
        files = materials.get("files") or []
        if not files:
            st.info("`opic_data/materials.json` 자료가 없습니다.")
        else:
            rows = []
            for f in files:
                paras = f.get("paragraphs") or []
                rows.append(
                    {
                        "제목": f.get("title", ""),
                        "원본": f.get("sourceFile", ""),
                        "문장수": len(paras),
                    }
                )
            if pd is not None:
                st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
            else:
                st.json(rows[:50])
            with st.expander("스크립트 미리보기", expanded=False):
                sel_idx = st.number_input(
                    "파일 번호(1~N)",
                    min_value=1,
                    max_value=max(1, len(files)),
                    value=1,
                    step=1,
                    key="opic_preview_idx",
                )
                picked = files[int(sel_idx) - 1]
                st.markdown(f"**{picked.get('title', '')}**")
                paras = picked.get("paragraphs") or []
                for line in paras[:30]:
                    st.write(str(line))
                if len(paras) > 30:
                    st.caption(f"... 이하 {len(paras) - 30}줄 생략")

    with t2:
        if not travel:
            st.info("`opic_data/travel.json` 자료가 없습니다.")
        else:
            st.markdown(f"**{travel.get('title', '여행 토픽')}**")
            if travel.get("intro"):
                st.caption(str(travel.get("intro")))
            dest = travel.get("destinations") or []
            rows = []
            for d in dest:
                rows.append(
                    {
                        "순위": d.get("rank"),
                        "국가/도시": d.get("name", ""),
                        "요약": str(d.get("summary", ""))[:90],
                        "권장시기": str((d.get("bestTime") or {}).get("recommended", ""))[:32],
                    }
                )
            if rows:
                if pd is not None:
                    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                else:
                    st.json(rows)

    with t3:
        if not library:
            st.info("`opic_data/library.json` 자료가 없습니다.")
        else:
            st.markdown(f"**{library.get('title', '문장·독서')}**")
            if library.get("intro"):
                st.caption(str(library.get("intro")))
            quotes = library.get("quotes") or []
            if quotes:
                st.subheader("좋은 문장")
                for q in quotes[:8]:
                    st.markdown(f"- {q.get('text', '')}  \n  — *{q.get('source', '')}*")
            books = library.get("books") or []
            if books:
                st.subheader("책 메모")
                rows_b = [{"제목": b.get("title", ""), "저자": b.get("author", ""), "메모": b.get("note", "")} for b in books]
                if pd is not None:
                    st.dataframe(pd.DataFrame(rows_b), use_container_width=True, hide_index=True)
                else:
                    st.json(rows_b)

    with t4:
        kb = library.get("kidsBooks") or {}
        items_raw = kb.get("items") if isinstance(kb.get("items"), list) else []
        if not items_raw:
            st.info(
                "`opic_data/library.json` 의 **kidsBooks.items** 에 도서를 넣으면 "
                "5·7세 추천 랭크가 표시됩니다. (지금은 데이터가 비어 있을 수 있습니다.)"
            )
        else:
            st.markdown(f"**{kb.get('title', '5·7세 추천 도서')}**")
            if kb.get("intro"):
                st.caption(str(kb.get("intro")))
            filt = st.radio(
                "연령 필터",
                ["전체 순위", "5세 중심", "7세 중심", "5세·7세 공통만"],
                horizontal=True,
                key="opic_kids_book_age_filter",
            )

            def _norm_ages(it: dict[str, Any]) -> list[str]:
                a = it.get("ages") or it.get("age")
                if isinstance(a, str):
                    return [x.strip() for x in a.replace(",", " ").split() if x.strip()]
                if isinstance(a, list):
                    return [str(x).strip() for x in a if str(x).strip()]
                return []

            items = sorted(
                [it for it in items_raw if isinstance(it, dict)],
                key=lambda x: int(x.get("rank") or 9999),
            )
            if filt == "5세 중심":
                items = [it for it in items if "5" in _norm_ages(it)]
            elif filt == "7세 중심":
                items = [it for it in items if "7" in _norm_ages(it)]
            elif filt == "5세·7세 공통만":
                items = [
                    it
                    for it in items
                    if "5" in _norm_ages(it) and "7" in _norm_ages(it)
                ]

            rows_k = []
            for it in items:
                ages = _norm_ages(it)
                if ages:
                    age_s = (
                        "·".join(
                            sorted(ages, key=lambda s: int(s) if str(s).isdigit() else 99)
                        )
                        + "세"
                    )
                else:
                    age_s = "—"
                rows_k.append(
                    {
                        "순위": int(it.get("rank") or 0),
                        "연령": age_s,
                        "제목": it.get("title", ""),
                        "저자": it.get("author", ""),
                        "분야": it.get("category", ""),
                        "추천 이유": it.get("reason", ""),
                    }
                )
            if rows_k:
                if pd is not None:
                    st.dataframe(pd.DataFrame(rows_k), use_container_width=True, hide_index=True)
                else:
                    st.json(rows_k)
                st.caption(
                    "정렬: **rank** 숫자 오름차순(1이 가장 위). "
                    "내용 편집은 `opic_data/library.json` → **kidsBooks** 입니다."
                )
            else:
                st.info("선택한 필터에 해당하는 도서가 없습니다.")

    with t5:
        if not news:
            st.info("`opic_data/it-news.json` 자료가 없습니다.")
        else:
            st.caption(f"수집시각: {str(news.get('fetchedAt') or '')[:16]}")
            items = news.get("items") or []
            for it in items[:30]:
                ttl = str(it.get("title", ""))
                src = str(it.get("source", ""))
                link = str(it.get("link", "") or "")
                st.markdown(f"- **{ttl}** · {src}")
                if link:
                    st.markdown(f"  - [원문 열기]({link})")


def _render_page_local_surge() -> None:
    """테마주·Stage2 통합 유니버스 (tema surge core)"""
    st.error(
        "참고용 스캐너입니다. 이 화면만 보고 매수하지 마세요. "
        "뉴스/공시/실적/유동성/손절 계획을 반드시 별도로 확인해야 합니다."
    )
    # 메인에 스캐너 탭만 두면 CSS상 '최상위 탭' 스타일(작은 셀·글자)이 적용됨.
    # 시장 > 코스피처럼 한 단계 감싸 .stTabs .stTabs 규칙을 타게 해 동일한 탭/터치 크기로 맞춤.
    _t_scan, = st.tabs(["스캔 결과"])
    with _t_scan:
        _render_scanner_page(
            title="테마주 (Theme Stocks) Stage2 스캔",
            data_dir_name="tema_stage2_data",
            module_name="tema_stage2_export_core",
            candidates_module="candidates_data",
            index_label="—",
            show_index=False,
            run_export_name="run_analysis_export",
        )


def _market_label_from_ticker(ticker: str | None) -> str:
    t = str(ticker or "").upper()
    if t.endswith(".KS"):
        return "코스피"
    if t.endswith(".KQ"):
        return "코스닥"
    return "기타"


def _infer_theme_label(name: str | None, sector: str | None) -> str:
    blob = f"{name or ''} {sector or ''}".lower()
    theme_rules: list[tuple[str, tuple[str, ...]]] = [
        ("AI·로봇", ("ai", "인공지능", "로봇", "자동화", "휴머노이드")),
        ("반도체", ("반도체", "semicon", "칩", "파운드리", "메모리")),
        ("2차전지", ("2차전지", "배터리", "리튬", "양극", "음극", "전해질")),
        ("전력·원전", ("전력", "변압", "송전", "배전", "원전", "원자력")),
        ("바이오·헬스케어", ("바이오", "제약", "백신", "의료", "헬스", "진단")),
        ("자동차·부품", ("자동차", "차량", "ev", "전기차", "부품", "모빌리티")),
        ("조선·해운", ("조선", "해운", "선박", "항공", "물류")),
        ("건설·인프라", ("건설", "시멘트", "인프라", "철강", "플랜트")),
        ("금융", ("은행", "증권", "보험", "금융", "카드")),
        ("소비재", ("화장품", "식품", "유통", "면세", "패션", "의류")),
    ]
    for label, keys in theme_rules:
        if any(k in blob for k in keys):
            return label
    return "기타"


def _local_surge_labels(m: dict[str, Any]) -> tuple[str, str, str]:
    market = _market_label_from_ticker(m.get("ticker"))
    raw_sector = str(m.get("sector") or "").strip()
    ticker = str(m.get("ticker") or "").strip()
    name = str(m.get("name") or "").strip()
    extra = ""
    try:
        from candidates_data import CANDIDATES

        ci = CANDIDATES.get(ticker)
        if isinstance(ci, (list, tuple)) and len(ci) > 1:
            extra = str(ci[1] or "")
    except Exception:
        pass
    try:
        from surge_sector_resolve import resolve_surge_sector

        if raw_sector and raw_sector not in ("코스피", "코스닥", "KOSPI", "KOSDAQ"):
            sector = resolve_surge_sector(ticker=ticker, name=name, payload_sector=raw_sector, extra_hint=extra)
        else:
            sector = resolve_surge_sector(ticker=ticker, name=name, payload_sector="미분류", extra_hint=extra)
    except Exception:
        if raw_sector and raw_sector not in ("코스피", "코스닥", "KOSPI", "KOSDAQ"):
            sector = raw_sector
        else:
            sector = _infer_theme_label(m.get("name"), "")
    theme = _infer_theme_label(m.get("name"), sector)
    return market, sector, theme


def _sector_label_for_match(m: dict[str, Any], is_surge_scanner: bool) -> str:
    if is_surge_scanner:
        return _local_surge_labels(m)[1]
    sec = str(m.get("sector") or "").strip()
    return sec or "미분류"


def _kospi_sector_etf_pair(sec: str) -> tuple[str, str]:
    """
    코스피 스캐너 섹터 라벨(예: 반도체/AI)에 대응하는 **참고용** 국내 상장 ETF 심볼.
    1:1 구성 일치는 아니며, 야후 파이낸스 등에서 흐름만 비교할 때 쓰기 위한 힌트입니다.
    """
    s = (sec or "").strip()
    if not s:
        return "", ""
    # (키워드가 섹터 문자열에 포함되면 매칭) — kospi_candidates.py 의 두 번째 토큰과 맞춤
    rules: tuple[tuple[tuple[str, ...], str, str], ...] = (
        (("반도체", "AI"), "091160.KS", "KODEX 반도체"),
        (("모빌리티", "방산"), "091180.KS", "KODEX 자동차"),
        (("전력", "인프라"), "139230.KS", "TIGER 200 산업재"),
        (("금융", "밸류업"), "102970.KS", "KODEX 증권"),
        (("소비재", "바이오"), "244580.KS", "TIGER 바이오TOP10"),
    )
    for keys, tkr, lbl in rules:
        if any(k in s for k in keys):
            return tkr, lbl
    if s == "미분류":
        return "069500.KS", "KODEX 200"
    return "069500.KS", "KODEX 200"


def _sector_table_from_top_candidates(
    top_table: list[dict[str, Any]],
    *,
    is_surge_scanner: bool,
    universe_sector_counts: dict[str, int] | None = None,
    top_n: int = 30,
) -> list[dict[str, Any]]:
    ranked = sorted(
        top_table,
        key=lambda m: (
            int(m.get("rank") or 999999),
            -float(m.get("score") or 0),
        ),
    )
    top_ranked = ranked[:top_n]
    agg: dict[str, dict[str, Any]] = {}
    for m in top_table:
        sec = _sector_label_for_match(m, is_surge_scanner)
        row = agg.setdefault(
            sec,
            {"sector": sec, "universe_n": 0, "top30_n": 0, "score_sum": 0.0, "max_score": 0.0, "match_n": 0},
        )
        score = float(m.get("score") or 0.0)
        row["match_n"] += 1
        row["score_sum"] += score
        row["max_score"] = max(float(row["max_score"]), score)
    for m in top_ranked:
        sec = _sector_label_for_match(m, is_surge_scanner)
        if sec in agg:
            agg[sec]["top30_n"] += 1
        else:
            agg[sec] = {
                "sector": sec,
                "universe_n": 0,
                "top30_n": 1,
                "score_sum": 0.0,
                "max_score": 0.0,
                "match_n": 0,
            }

    # 분모: 후보 유니버스 섹터별 종목수 (누락 섹터도 표시)
    universe_sector_counts = universe_sector_counts or {}
    for sec, n in universe_sector_counts.items():
        row = agg.setdefault(
            sec,
            {"sector": sec, "universe_n": 0, "top30_n": 0, "score_sum": 0.0, "max_score": 0.0, "match_n": 0},
        )
        row["universe_n"] = int(n)

    rows = list(agg.values())
    for r in rows:
        n = int(r.get("universe_n") or 0)
        top_cnt = int(r["top30_n"])
        match_n = int(r.get("match_n") or 0)
        avg = (float(r["score_sum"]) / match_n) if match_n > 0 else 0.0
        # 요청: 소수점 아래 버림
        pct = int((100.0 * top_cnt / n)) if n > 0 else 0
        r["avg_score"] = round(avg, 2)
        r["top30_pct_int"] = pct
    rows.sort(key=lambda r: (-float(r["avg_score"]), -int(r["top30_n"]), -int(r["universe_n"]), str(r["sector"])))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return rows


def _candidate_universe_sector_counts(
    *,
    module_name: str,
    candidates_module: str,
    is_surge_scanner: bool,
) -> dict[str, int]:
    out: dict[str, int] = {}
    try:
        cm = __import__(candidates_module)
        cand = getattr(cm, "CANDIDATES", {}) or {}
        if not isinstance(cand, dict):
            return out
        if is_surge_scanner:
            em = __import__(module_name)
            get_sector = getattr(em, "get_sector", None)
            if get_sector is None:
                return out
            for t in cand.keys():
                try:
                    sec = str(get_sector(t) or "").strip() or "미분류"
                except Exception:
                    sec = "미분류"
                out[sec] = out.get(sec, 0) + 1
            return out
        # 코스피/코스닥 후보: [종목명, 섹터]
        for info in cand.values():
            sec = "미분류"
            if isinstance(info, (list, tuple)) and len(info) > 1:
                sec = str(info[1] or "").strip() or "미분류"
            out[sec] = out.get(sec, 0) + 1
    except Exception:
        return {}
    return out


def _diff_history_event_key(it: dict[str, Any]) -> tuple[Any, ...]:
    """신규·탈락 행을 정규화해 diff 지문에 쓰는 키(티커·표시용 필드)."""

    sc = it.get("score")
    try:
        sc_n = round(float(sc), 4) if sc is not None else None
    except (TypeError, ValueError):
        sc_n = None
    return (
        str(it.get("ticker") or ""),
        str(it.get("name") or ""),
        str(it.get("sector") or ""),
        sc_n,
        str(it.get("entry") or ""),
    )


def _diff_history_fingerprint(added: list[dict[str, Any]], removed: list[dict[str, Any]]) -> str:
    """동일 스냅샷이 반복 저장되는 것을 막기 위한 내용 기반 지문."""

    a = sorted(_diff_history_event_key(x) for x in added)
    r = sorted(_diff_history_event_key(x) for x in removed)
    blob = json.dumps({"added": a, "removed": r}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _diff_history_last_fingerprint(conn: Any, scanner: str) -> str | None:
    """해당 스캐너의 가장 최근 run에 기록된 이벤트 세트 지문."""

    cur = conn.cursor()
    cur.execute("SELECT id FROM runs WHERE scanner = ? ORDER BY id DESC LIMIT 1", (scanner,))
    row = cur.fetchone()
    if not row:
        return None
    run_id = int(row[0])
    cur.execute(
        """
        SELECT event_type, ticker, name, sector, score, entry
        FROM events
        WHERE run_id = ?
        ORDER BY event_type, ticker
        """,
        (run_id,),
    )
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for et, t, n, s, sc, e in cur.fetchall():
        d = {"ticker": t, "name": n, "sector": s, "score": sc, "entry": e}
        if et == "added":
            added.append(d)
        elif et == "removed":
            removed.append(d)
    return _diff_history_fingerprint(added, removed)


def _record_diff_history_sqlite(
    *,
    data_dir: Path,
    scanner: str,
    analysis_time: str,
    baseline_date: str,
    added: list[dict[str, Any]],
    removed: list[dict[str, Any]],
) -> Path:
    import sqlite3

    state_dir = data_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / "diff_history.db"
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              scanner TEXT NOT NULL,
              analysis_time TEXT NOT NULL,
              baseline_date TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(scanner, analysis_time)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              run_id INTEGER NOT NULL,
              event_type TEXT NOT NULL,
              ticker TEXT NOT NULL,
              name TEXT,
              sector TEXT,
              score REAL,
              entry TEXT,
              created_at TEXT DEFAULT CURRENT_TIMESTAMP,
              UNIQUE(run_id, event_type, ticker),
              FOREIGN KEY(run_id) REFERENCES runs(id)
            )
            """
        )
        # 분석 시각만 바뀌고 신규·탈락 목록이 동일하면(앱 재실행·재동기화 등) 행을 추가하지 않음
        fp_new = _diff_history_fingerprint(added, removed)
        fp_prev = _diff_history_last_fingerprint(conn, scanner)
        if fp_prev is not None and fp_prev == fp_new:
            return db_path
        cur.execute(
            """
            INSERT OR IGNORE INTO runs(scanner, analysis_time, baseline_date)
            VALUES (?, ?, ?)
            """,
            (scanner, analysis_time, baseline_date),
        )
        cur.execute(
            "SELECT id FROM runs WHERE scanner = ? AND analysis_time = ?",
            (scanner, analysis_time),
        )
        row = cur.fetchone()
        run_id = int(row[0]) if row else None
        if run_id is not None:
            for et, items in (("added", added), ("removed", removed)):
                for it in items:
                    cur.execute(
                        """
                        INSERT OR IGNORE INTO events(run_id, event_type, ticker, name, sector, score, entry)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            et,
                            str(it.get("ticker") or ""),
                            str(it.get("name") or ""),
                            str(it.get("sector") or ""),
                            float(it.get("score")) if it.get("score") is not None else None,
                            str(it.get("entry") or ""),
                        ),
                    )
        conn.commit()
    finally:
        conn.close()
    return db_path


def _load_diff_history_sqlite(
    *,
    db_path: Path,
    scanner: str,
    limit: int = 200,
    candidates_module: str | None = None,
) -> tuple[int, int, list[dict[str, Any]]]:
    import sqlite3

    if not db_path.exists():
        return 0, 0, []
    conn = sqlite3.connect(str(db_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
              COUNT(DISTINCT CASE WHEN e.event_type='added' THEN e.ticker END) AS added_n,
              COUNT(DISTINCT CASE WHEN e.event_type='removed' THEN e.ticker END) AS removed_n
            FROM events e
            JOIN runs r ON r.id = e.run_id
            WHERE r.scanner = ?
            """,
            (scanner,),
        )
        c = cur.fetchone() or (0, 0)
        total_added = int(c[0] or 0)
        total_removed = int(c[1] or 0)
        cur.execute(
            """
            CREATE TEMP TABLE IF NOT EXISTS candidate_lookup (
              ticker TEXT PRIMARY KEY,
              name TEXT,
              sector TEXT
            )
            """
        )
        cur.execute("DELETE FROM candidate_lookup")
        if candidates_module:
            try:
                cm = __import__(candidates_module)
                cand = getattr(cm, "CANDIDATES", {}) or {}
                if isinstance(cand, dict):
                    rows_to_insert: list[tuple[str, str, str]] = []
                    for tk, info in cand.items():
                        t = str(tk or "").strip()
                        if not t:
                            continue
                        nm = ""
                        sec = ""
                        if isinstance(info, (list, tuple)):
                            if len(info) > 0:
                                nm = str(info[0] or "").strip()
                            if len(info) > 1:
                                sec = str(info[1] or "").strip()
                        rows_to_insert.append((t, nm, sec))
                    if rows_to_insert:
                        cur.executemany(
                            "INSERT OR REPLACE INTO candidate_lookup(ticker, name, sector) VALUES (?, ?, ?)",
                            rows_to_insert,
                        )
            except Exception:
                pass
        cur.execute(
            """
            SELECT
              r.analysis_time,
              e.event_type,
              e.ticker,
              COALESCE(NULLIF(e.name, ''), c.name, '') AS name,
              COALESCE(NULLIF(e.sector, ''), c.sector, '') AS sector,
              e.score
            FROM events e
            JOIN runs r ON r.id = e.run_id
            LEFT JOIN candidate_lookup c ON c.ticker = e.ticker
            WHERE r.scanner = ?
            ORDER BY e.id DESC
            LIMIT ?
            """,
            (scanner, int(limit)),
        )
        seen: set[tuple[str, str]] = set()
        rows: list[dict[str, Any]] = []
        for (a, et, t, n, s, sc) in cur.fetchall():
            key = (str(t), et)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "분析시각": a,
                "구분": ("신규" if et == "added" else "탈락"),
                "티커": t,
                "종목명": n,
                "섹터": s,
                "점수": sc,
            })
        return total_added, total_removed, rows
    finally:
        conn.close()


def _apply_rank_delta_enrichment(payload: dict, data_dir: Path) -> None:
    """열어둔 payload에 대해 state/rank_by_date.json으로 Δ1d/Δ3d/Δ6d를 다시 붙입니다.
    스냅샷 앵커는 ``diff_snapshot_date``(없으면 KST 오늘)입니다."""

    import sys

    if not isinstance(payload, dict):
        return
    state_path = data_dir / "state" / "rank_by_date.json"
    if not state_path.is_file():
        return
    top = payload.get("top_table")
    matches = payload.get("matches") or []
    if not isinstance(top, list) or not top:
        return
    here = data_dir.parent.resolve()
    if str(here) not in sys.path:
        sys.path.insert(0, str(here))
    try:
        from rank_delta_utils import (
            attach_rank_deltas_to_rows,
            calendar_today_kst_iso,
            load_rank_by_date,
            normalize_ticker_key,
        )
    except ImportError:
        return
    rank_hist = load_rank_by_date(str(state_path))
    if not rank_hist:
        return
    asof = str(payload.get("diff_snapshot_date") or "").strip()
    if len(asof) != 10:
        idx0 = payload.get("index")
        if isinstance(idx0, dict):
            asof = str(idx0.get("as_of") or "").strip()
    if len(asof) != 10:
        lat0 = str(payload.get("last_analysis_time") or "").strip()
        if len(lat0) >= 10 and lat0[4] == "-" and lat0[7] == "-":
            asof = lat0[:10]
    if len(asof) != 10:
        asof = calendar_today_kst_iso()
    rank_hist_before = {k: v for k, v in rank_hist.items() if k != asof}
    tr: dict[str, int] = {}
    for m in matches:
        if not isinstance(m, dict) or m.get("ticker") is None:
            continue
        try:
            tr[normalize_ticker_key(str(m["ticker"]))] = int(m["rank"])
        except (TypeError, ValueError, KeyError):
            continue
    for row in top:
        if not isinstance(row, dict):
            continue
        tid = normalize_ticker_key(str(row.get("ticker") or ""))
        if tid and tid in tr:
            row["rank"] = tr[tid]
    meta = attach_rank_deltas_to_rows(top, rank_hist_before, asof)
    prev = payload.get("rank_delta_meta")
    payload["rank_delta_meta"] = {**(prev if isinstance(prev, dict) else {}), **meta}


def _render_scanner_page(
    title: str,
    data_dir_name: str,
    module_name: str,
    candidates_module: str,
    index_label: str,
    *,
    show_index: bool = True,
    run_export_name: str | None = None,
) -> None:
    """코스닥/코스피 스캐너 공통 렌더러. 급등주(로컬)는 show_index=False."""
    import os, json, threading, sys
    from pathlib import Path

    st.title(title)
    _weinstein_tip_caption(salt=f"scanner_title:{data_dir_name}")

    HERE        = Path(__file__).parent
    DATA_DIR    = HERE / data_dir_name
    CHARTS_DIR  = DATA_DIR / "charts"
    RESULTS_JSON = DATA_DIR / "results_web.json"
    DATA_DIR.mkdir(exist_ok=True)

    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        mod = __import__(module_name)
        if run_export_name:
            run_export = getattr(mod, run_export_name)
        else:
            run_export = getattr(mod, f"run_{module_name.split('_')[0]}_export")
        _core_ok = True
    except Exception as e:
        st.error(f"{module_name} 임포트 실패: {e}")
        _core_ok = False
        run_export = None

    scan_key = f"{data_dir_name}_scanning"
    err_key  = f"{data_dir_name}_error"
    if scan_key not in st.session_state:
        st.session_state[scan_key] = False
    if err_key not in st.session_state:
        st.session_state[err_key] = None

    def _quick_last_analysis_from_json(p: Any) -> str | None:
        """스캐너 시각: results_web + 공용 universe_meta.updated_at 중 더 늦은 값."""
        try:
            if not p.is_file():
                return None
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            if not isinstance(d, dict):
                return None
            v = _scanner_freshest_display_time(d, app_root=HERE)
            return v if v != "—" else None
        except Exception:
            return None

    with _st_try_border_container():
        col_btn, col_status = st.columns([1, 4])
        with col_btn:
            scan_clicked = st.button(
                "스캔 시작",
                key=f"btn_{data_dir_name}",
                disabled=st.session_state[scan_key] or not _core_ok,
                use_container_width=True,
            )
        with col_status:
            if st.session_state[scan_key]:
                st.info("스캔 중… (5~20분 소요)")
            elif RESULTS_JSON.exists():
                ts_payload = _quick_last_analysis_from_json(RESULTS_JSON)
                if ts_payload:
                    st.success(f"마지막 분석: {ts_payload}")
                else:
                    ts = _file_mtime_str_kst(RESULTS_JSON, "%Y-%m-%d %H:%M")
                    st.success(f"마지막 분석(파일시각 KST): {ts}")

    if scan_clicked and _core_ok:
        st.session_state[scan_key] = True
        st.session_state[err_key]  = None

        def _run():
            try:
                run_export(str(DATA_DIR))
            except Exception as ex:
                st.session_state[err_key] = str(ex)
            finally:
                st.session_state[scan_key] = False

        threading.Thread(target=_run, daemon=True).start()
        st.rerun()

    if st.session_state.get(err_key):
        st.error(f"스캔 오류: {st.session_state[err_key]}")

    payload: dict | None = None
    if RESULTS_JSON.exists():
        try:
            with open(RESULTS_JSON, encoding="utf-8") as f:
                payload = json.load(f)
            if isinstance(payload, dict):
                _apply_rank_delta_enrichment(payload, DATA_DIR)
        except Exception as e:
            st.warning(f"결과 파일 로드 실패: {e}")

    if payload is None:
        st.info("결과 없음. '스캔 시작' 버튼을 눌러 분석을 실행하세요.")
        return

    if show_index:
        # ── 지수 현황 ────────────────────────────────────────────────
        idx_status = payload.get("index", {})
        tone       = idx_status.get("tone", "unknown")
        headline   = idx_status.get("headline", "")
        tone_map   = {
            "stage2":  ("Stage2 상승", "success", "#15803d"),
            "bear":    ("약세 (종가<MA200)", "error", "#b91c1c"),
            "caution": ("단기 둔화 (종가<MA50)", "error", "#c2410c"),
            "weak":    ("조정·횡보", "error", "#b45309"),
            "unknown": ("데이터 없음", "info", "#64748b"),
        }
        tone_lbl, _, tone_color = tone_map.get(tone, ("알 수 없음", "info", "#64748b"))

        with st.container(border=True):
            _idx_close = _fmt_index_metric(idx_status.get("last_close"))
            _idx_ma50 = _fmt_index_metric(idx_status.get("ma50"))
            _idx_ma200 = _fmt_index_metric(idx_status.get("ma200"))
            hl_txt = html.escape(str(headline or "").strip() or str(tone_lbl))
            _badge_bg = {"stage2": "#dcfce7", "bear": "#fee2e2", "caution": "#ffedd5", "weak": "#fef3c7"}.get(
                tone, "#f1f5f9"
            )
            _badge_fg = {"stage2": "#15803d", "bear": "#b91c1c", "caution": "#c2410c", "weak": "#b45309"}.get(
                tone, "#64748b"
            )
            st.markdown(
                f"""<div style="padding:0.45rem 0.6rem 0.35rem 0.6rem;line-height:1.3;">
  <div style="display:flex;align-items:center;gap:0.5rem;flex-wrap:wrap;margin-bottom:0.3rem;">
    <span style="font-size:0.88rem;font-weight:700;color:#0f172a;">📊 {html.escape(str(index_label))} 지수</span>
    <span style="font-size:0.78rem;font-weight:700;padding:0.1rem 0.55rem;border-radius:999px;background:{_badge_bg};color:{_badge_fg};">{html.escape(tone_lbl)}</span>
  </div>
  <div style="display:flex;gap:0.9rem;flex-wrap:wrap;font-size:0.8rem;color:#374151;">
    <span><span style="color:#94a3b8;font-size:0.72rem;">종가</span>&nbsp;<b style="color:#0f172a;">{html.escape(_idx_close)}</b></span>
    <span><span style="color:#94a3b8;font-size:0.72rem;">MA50</span>&nbsp;<b style="color:#0f172a;">{html.escape(_idx_ma50)}</b></span>
    <span><span style="color:#94a3b8;font-size:0.72rem;">MA200</span>&nbsp;<b style="color:#0f172a;">{html.escape(_idx_ma200)}</b></span>
  </div>
  <div style="margin-top:0.25rem;font-size:0.72rem;color:{tone_color};line-height:1.3;">{hl_txt}</div>
</div>""",
                unsafe_allow_html=True,
            )
            with st.expander("Stage2·MA 판단 기준 (상세)", expanded=False):
                st.caption(
                    "※ **사상 최고가**와 이 카드의 **지수 2단계**는 다릅니다. "
                    "**엄격**: 종가>MA150>MA200·MA200 20일 우상·MA50(10봉) 상승·종가>MA50 을 **동시에** 만족하면 2단계. "
                    "**완화**: MA150>MA200 정렬 전이어도 종가가 MA150·MA200 **모두 위**이고 나머지 추세·MA50 조건이 같으면 2단계로 표시합니다(급반등 구간 참고)."
                )
            with st.expander("스탠 와인스타인 · 매수를 생각할 때 세 가지 (요약)", expanded=False):
                st.markdown(
                    """
**스탠 와인스타인(Stan Weinstein)** 의 4단계 모델에서, 롱 매수를 검토할 때는 보통 아래 **세 가지가 함께 맞는지**부터 점검합니다.

1. **시장(대표 지수)이 2단계** — 지수가 상승 추세 구간인지. 이 블록의 지수 메시지가 그 여부를 가리킵니다.  
2. **섹터(업종)가 좋을 것** — 주도 업종·상대 강도가 살아 있는지. **이 페이지의 「섹터 분포」 탭**에서 교차 확인하세요.  
3. **개별 종목이 2단계** — 종목 자체가 돌파·추세 전환 후 상승 국면에 있는지. 이 스캐너의 Stage2 후보는 그중 **종목 쪽**을 정리한 결과입니다.

셋 중 하나라도 부족하면 성공 확률이 떨어지기 쉽습니다. **“지수는 약한데 종목만 센 경우”**·**“종목만 보고 시장·섹터를 안 보는 경우”**는 특히 손익 구조를 나쁘게 만들 수 있으니, 위 순서로 화면을 함께 보는 것이 좋습니다.

*(투자 권유가 아니라 단계 이론·이 앱 UI 흐름에 맞춘 요약입니다.)*
"""
                )
            with st.expander("4단계만 짚어보기 (와인스타인)", expanded=False):
                st.markdown(
                    """
| 단계 | 흔히 쓰는 이름 | 짧은 느낌 |
|------|----------------|-----------|
| **1** | 베이스(Basing) | 오래 횡보·바닥권에서 수급이 갈리는 구간 |
| **2** | 어드밴싱(Advancing) | 돌파 뒤 **상승 추세 본론** — 이 스캐너 **Stage2** 후보는 여기에 가깝게 잡힌다고 보면 됩니다 |
| **3** | 디스트리뷰션(Distribution) | **분배·분출** — 고점 근처에서 «누가 팔고 있나»를 거래량으로 보는 이야기가 많아짐 |
| **4** | 딥클라인(Declining) | 하락 국면 — **손실 억제·현금 비중** 같은 말이 앞으로 나옵니다 |

한 종목만 보지 말고 **지수·섹터와 겹쳐 읽으라**는 말이 자주 따라붙습니다.
"""
                )
    else:
        st.info(
            "**통합 유니버스** 스캔 — 코스피·코스닥 후보를 한 번에 Stage2로 걸러 순위화합니다. "
            "**RS 점수**에는 가격 상대강도와 함께 **시가총액·영업이익(률)** 품질 가점이 RS 상한(기본 40pt) 안에서 합산되어 잡주를 약하게 만듭니다. "
            "와인스타인식으로 보면 **2단계(어드밴싱)**에 가까운 후보를 한 번에 모아 본다고 생각하면 이해가 빠릅니다.",
        )

    is_surge_scanner = (
        payload.get("scanner_type") in ("local_surge", "tema_surge", "tema_surge_cache", "tema_stage2", "tema_stage2_cache")
        or (payload.get("scoring") or {}).get("scanner_type") in ("local_surge", "tema_surge", "tema_surge_cache", "tema_stage2", "tema_stage2_cache")
    )
    top_table = payload.get("top_table") or payload.get("matches", [])
    top_table_rank_view: list[dict[str, Any]] = list(top_table)
    if str(data_dir_name) == "etf_data":
        n_cand = int(payload.get("candidate_count") or 0)
        n_s2 = len(payload.get("matches") or [])
        st.caption(f"총 ETF 후보: {n_cand}개 | Stage2: {n_s2}개")
        st.session_state.setdefault("etf_data_sector_filter", _ETF_SECTOR_FILTER_OPTIONS[0])
        with st.container(border=True):
            _flt = st.selectbox(
                "섹터 필터",
                options=list(_ETF_SECTOR_FILTER_OPTIONS),
                key="etf_data_sector_filter",
                help="목록에서만 선택할 수 있습니다. (고정 옵션)",
            )

            def _etf_rank_keep(m: dict[str, Any]) -> bool:
                if _flt == "전체":
                    return True
                return str(m.get("sector") or "").strip() == _flt

            if _flt != "전체":
                top_table_rank_view = [m for m in top_table if _etf_rank_keep(m)]
    universe_sector_counts = _candidate_universe_sector_counts(
        module_name=module_name,
        candidates_module=candidates_module,
        is_surge_scanner=is_surge_scanner,
    )
    sector_rows_100 = _sector_table_from_top_candidates(
        top_table_rank_view,
        is_surge_scanner=is_surge_scanner,
        universe_sector_counts=universe_sector_counts,
        top_n=30,
    )

    # 신규/탈락 누적 이력 DB 저장 (동일 diff 반복 방지: 직전 run과 이벤트 지문 비교)
    _scanner_name = str(payload.get("scanner_type") or data_dir_name)
    _analysis_time = str(payload.get("last_analysis_time") or "")
    _baseline = str(payload.get("diff_baseline_date") or "")
    _added_now = payload.get("last_diff_added") or []
    _removed_now = payload.get("last_diff_removed") or []
    diff_db_path = _record_diff_history_sqlite(
        data_dir=DATA_DIR,
        scanner=_scanner_name,
        analysis_time=_analysis_time,
        baseline_date=_baseline,
        added=_added_now,
        removed=_removed_now,
    )
    total_added_hist, total_removed_hist, recent_hist_rows = _load_diff_history_sqlite(
        db_path=diff_db_path,
        scanner=_scanner_name,
        limit=200,
        candidates_module=candidates_module,
    )

    # 순위 표·섹터 드릴다운 등 탭 전역에서 쓰는 스타일 헬퍼 (if/else 밖에 두어 NameError 방지)
    def _sty_ret(v: Any) -> str:
        try:
            x = float(str(v).replace("%", "").replace("+", ""))
            if x >= 10.0:
                return "color:#15803d;font-weight:800;"
            if x >= 3.0:
                return "color:#166534;font-weight:700;"
            if x >= 0.0:
                return "color:#374151;"
            if x >= -5.0:
                return "color:#991b1b;"
            return "color:#b91c1c;font-weight:700;"
        except (TypeError, ValueError):
            return ""

    def _sty_delta(v: Any) -> str:
        s = str(v)
        if s.startswith("+"):
            return "color:#16a34a;font-weight:700;"
        if s.startswith("-"):
            return "color:#dc2626;font-weight:700;"
        return ""

    def _sty_score(v: Any) -> str:
        try:
            x = float(v)
            if x >= 80:
                return "color:#15803d;font-weight:700;"
            if x >= 50:
                return "color:#b45309;font-weight:700;"
            return "color:#b91c1c;font-weight:700;"
        except Exception:
            return ""

    def _sty_rs(v: Any) -> str:
        try:
            x = float(str(v).replace("-", ""))
            if x >= 1.0:
                return "color:#15803d;font-weight:700;"
            if x >= 0.95:
                return "color:#b45309;font-weight:600;"
            return "color:#94a3b8;"
        except Exception:
            return ""

    if not top_table:
        st.info("Stage2 해당 종목 없음")
    elif not top_table_rank_view:
        st.warning("섹터 필터에 맞는 ETF가 없습니다. 필터를 바꿔 보세요.")
    else:
        import pandas as _pd

        def _ret_color_css(v: str) -> str:
            try:
                x = float(str(v).replace("%", "").replace("+", ""))
                if x >= 5.0:
                    return "#15803d"
                if x >= 0.0:
                    return "#374151"
                return "#b91c1c"
            except (TypeError, ValueError):
                return "#94a3b8"

        def _delta_color_css(v: str) -> str:
            try:
                x = float(str(v).replace("+", ""))
                if x > 0:
                    return "#15803d"
                if x < 0:
                    return "#b91c1c"
                return "#64748b"
            except (TypeError, ValueError):
                return "#94a3b8"

        def _fmt_ret_since_stage2_entry(m: dict) -> str:
            v = m.get("ret_since_entry_pct")
            if v is not None:
                try:
                    return f"{float(v):+.1f}%"
                except (TypeError, ValueError):
                    pass
            try:
                return f"{float(m.get('ret_3m_pct') or 0):+.1f}%"
            except (TypeError, ValueError):
                return "—"

        # ── Top3 하이라이트 카드 (진입 적합성 기준 재선정) ──────────
        def _top3_entry_score(m: dict[str, Any]) -> float:
            """
            단순 점수 순위가 아닌 "지금 진입하기 좋은" 종목 선정 기준.
            높을수록 좋음.

            구성:
              1) 기본 점수 (40%) - RS·거래량 강도 반영
              2) 진입 초입 가점 (30%) - bars 적을수록 높음
              3) 비과열 가점 (20%) - 20일이격 낮을수록 높음
              4) Δ 모멘텀 가점 (10%) - 순위 올라오는 중이면 가점
            """
            base_score = float(m.get("score") or 0)

            # 1) 기본 점수 반영 (0~40)
            pts_base = min(base_score / 100.0 * 40.0, 40.0)

            # 2) 진입 초입 가점: bars 적을수록 높음 (0~30)
            bars = int(m.get("bars_since_stage2_entry") or 10_000)
            if bars <= 5:
                pts_bars = 30.0
            elif bars <= 10:
                pts_bars = 25.0
            elif bars <= 20:
                pts_bars = 20.0
            elif bars <= 40:
                pts_bars = 12.0
            elif bars <= 60:
                pts_bars = 6.0
            elif bars <= 110:
                pts_bars = 2.0
            else:
                pts_bars = 0.0

            # 3) 비과열 가점: 20일이격 낮을수록 높음 (0~20), 과열이면 패널티
            d20 = None
            for k in ("dist_ma20_pct", "disparity_20_pct", "close_vs_ma20_pct", "pct_from_ma20"):
                v = m.get(k)
                if v is not None:
                    try:
                        d20 = float(v)
                        break
                    except (TypeError, ValueError):
                        pass
            if d20 is None:
                pts_disp = 10.0  # 데이터 없으면 중립
            elif d20 <= 5.0:
                pts_disp = 20.0
            elif d20 <= 10.0:
                pts_disp = 15.0
            elif d20 <= 15.0:
                pts_disp = 8.0
            elif d20 <= 20.0:
                pts_disp = 2.0
            else:
                pts_disp = -15.0  # 과열 패널티

            # 4) Δ 모멘텀 가점 (0~10)
            def _pd(key: str) -> int:
                s = str(m.get(key, "") or "").strip()
                if not s or s in ("—", "-", "None", "null"):
                    return 0
                try:
                    return int(float(s))
                except (TypeError, ValueError):
                    return 0

            d1 = _pd("rank_delta_1d")
            d3 = _pd("rank_delta_3d")
            pts_delta = min(max(d1 * 0.5 + d3 * 0.3, -5.0), 10.0)

            return pts_base + pts_bars + pts_disp + pts_delta

        # 과열 종목(20일이격 +25% 초과)은 Top3 후보에서 제외
        def _is_overheated_top3(m: dict[str, Any]) -> bool:
            for k in ("dist_ma20_pct", "disparity_20_pct", "close_vs_ma20_pct", "pct_from_ma20"):
                v = m.get(k)
                if v is not None:
                    try:
                        return float(v) > 25.0
                    except (TypeError, ValueError):
                        pass
            return False

        _top3_pool = [m for m in top_table_rank_view if not _is_overheated_top3(m)]
        _top3_pool.sort(key=_top3_entry_score, reverse=True)
        top3 = _top3_pool[:3]

        # 후보 부족 시 원래 순위로 폴백
        if not top3:
            top3 = top_table_rank_view[:3]
        if top3:
            st.markdown("##### 🏆 Top 3")
            cols_t3 = st.columns(len(top3))
            for col, m in zip(cols_t3, top3):
                name = m.get("name", "")
                score = round(float(m.get("score") or 0), 1)
                ret = _fmt_ret_since_stage2_entry(m)
                try:
                    rs = f"{float(m.get('rs_ratio')):.3f}" if m.get("rs_ratio") is not None else "—"
                except (TypeError, ValueError):
                    rs = "—"
                d1 = str(m.get("rank_delta_1d", "—") or "—")
                d3 = str(m.get("rank_delta_3d", "—") or "—")
                d6 = str(m.get("rank_delta_6d", "—") or "—")
                entry = str(m.get("entry", "") or "—")[:10]
                sector = str(m.get("sector", "") or "—")
                col.markdown(
                    f"""<div style="border:1px solid #e2e8f0;border-radius:10px;
                        padding:0.65rem 0.8rem;background:#f8fafc;margin-bottom:0.4rem;">
                      <div style="font-size:0.83rem;font-weight:800;color:#0f172a;
                          white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{html.escape(name)}</div>
                      <div style="font-size:0.68rem;color:#64748b;margin-bottom:0.2rem;">
                          {html.escape(sector)} · {score}점</div>
                      <div style="font-size:1.0rem;font-weight:800;
                          color:{_ret_color_css(ret)};">{html.escape(ret)}</div>
                      <div style="font-size:0.68rem;color:#64748b;margin-top:0.1rem;">
                          RS {html.escape(rs)} · 진입 {html.escape(entry)}</div>
                      <div style="font-size:0.65rem;margin-top:0.1rem;">
                          <span style="color:{_delta_color_css(d1)};">Δ1d {html.escape(d1)}</span>
                          &nbsp;<span style="color:{_delta_color_css(d3)};">Δ3d {html.escape(d3)}</span>
                          &nbsp;<span style="color:{_delta_color_css(d6)};">Δ6d {html.escape(d6)}</span>
                      </div>
                    </div>""",
                    unsafe_allow_html=True,
                )
            st.markdown("<div style='margin-top:0.4rem'></div>", unsafe_allow_html=True)

        # ── 순위 테이블 ──────────────────────────────────────────
        rows: list[dict[str, Any]] = []
        for m in top_table_rank_view:
            _rsv = m.get("rs_ratio")
            try:
                rs_cell = f"{float(_rsv):.3f}" if _rsv is not None else "—"
            except (TypeError, ValueError):
                rs_cell = "—"
            row: dict[str, Any] = {
                "순위": int(m.get("rank") or 0),
                "종목명": m.get("name", ""),
                "점수": round(float(m.get("score") or 0), 1),
                "진입후수익": _fmt_ret_since_stage2_entry(m),
                "RS": rs_cell,
                "1Δ": m.get("rank_delta_1d", "—"),
                "3Δ": m.get("rank_delta_3d", "—"),
                "6Δ": m.get("rank_delta_6d", "—"),
                "진입일": str(m.get("entry", "") or "—")[:10],
                "섹터": m.get("sector", ""),
            }
            if is_surge_scanner:
                mkt, sec, theme = _local_surge_labels(m)
                row["시장"] = mkt
                row["섹터"] = sec
                row["테마"] = theme
                mcap = m.get("market_cap")
                om = m.get("operating_margin")
                try:
                    row["시총(억)"] = f"{float(mcap)/1e8:,.1f}" if mcap is not None else "—"
                except Exception:
                    row["시총(억)"] = "—"
                try:
                    row["영업이익률"] = f"{float(om)*100:.1f}%" if om is not None else "—"
                except Exception:
                    row["영업이익률"] = "—"
            rows.append(row)

        df_top = _pd.DataFrame(rows)

        _col_order_surge = ["순위", "종목명", "점수", "진입후수익", "RS", "1Δ", "3Δ", "6Δ", "진입일", "시장", "섹터", "테마", "시총(억)", "영업이익률"]
        _col_order_normal = ["순위", "종목명", "점수", "진입후수익", "RS", "1Δ", "3Δ", "6Δ", "진입일", "섹터"]
        _col_order = _col_order_surge if is_surge_scanner else _col_order_normal
        _have = list(df_top.columns)
        df_top = df_top[[c for c in _col_order if c in _have] + [c for c in _have if c not in _col_order]]

        _sty = df_top.style
        for _fn, _cols in (
            (_sty_ret, ["진입후수익"]),
            (_sty_delta, ["1Δ", "3Δ", "6Δ"]),
            (_sty_score, ["점수"]),
            (_sty_rs, ["RS"]),
        ):
            _avail = [c for c in _cols if c in df_top.columns]
            if _avail:
                if hasattr(_sty, "map"):
                    _sty = _sty.map(_fn, subset=_avail)
                elif hasattr(_sty, "applymap"):
                    _sty = _sty.applymap(_fn, subset=_avail)

        _df_disp = _sty

        if str(data_dir_name) in ("kospi_data", "kosdaq_data", "etf_data"):
            uid_wl = st.session_state.get("wl_user")
            if uid_wl:
                _wl_ensure_watchlist_session(HERE, uid_wl)

            try:
                _st_dataframe_all_rows(
                    _df_disp,
                    column_config={
                        "순위": st.column_config.NumberColumn("순위", width="small"),
                        "종목명": st.column_config.TextColumn("종목명"),
                        "점수": st.column_config.NumberColumn("점수", format="%.1f"),
                        "진입후수익": st.column_config.TextColumn("진입후수익"),
                        "RS": st.column_config.TextColumn("RS", width="small"),
                        "1Δ": st.column_config.TextColumn("1Δ", width="small"),
                        "3Δ": st.column_config.TextColumn("3Δ", width="small"),
                        "6Δ": st.column_config.TextColumn("6Δ", width="small"),
                        "진입일": st.column_config.TextColumn("진입일"),
                        "섹터": st.column_config.TextColumn("섹터"),
                    },
                )
            except Exception:
                _st_dataframe_all_rows(df_top)
            st.caption(f"Stage2 종목 **{len(top_table_rank_view)}개** · 분석: {_scanner_freshest_display_time(payload, app_root=HERE)}")

            with st.expander("📌 점수 산출 기준", expanded=False):
                st.markdown(
                    "| 항목 | 최대 점수 | 설명 |\n"
                    "|------|----------|------|\n"
                    "| **RS (상대강도)** | 58pt | Mansfield 방식 · RS 0.95+ 최소 45pt 보장 |\n"
                    "| **최근성** | 25pt | Stage2 진입 직후일수록 높음 |\n"
                    "| **거래량 모멘텀** | 35pt | 5일/20일/벤치 대비 거래량 강도 |\n"
                    "| **펀더멘털 가점** | 10pt | 시가총액 + 영업이익률 |\n\n"
                    "- **진입후수익**: Stage2 진입일 종가 → 오늘 종가 누적 수익률\n"
                    "- **RS**: 1.0 이상 = 시장 대비 강세 · 데이터 부족 시 63일 RS로 폴백\n"
                    "- **Δ1d·3d·6d**: 양수(+) = 순위 상승, 음수(−) = 순위 하락"
                )

            _weinstein_tip_caption(salt=f"rank:{data_dir_name}:{len(top_table_rank_view)}")

            if uid_wl:
                _wl_render_watch_star_grid(
                    HERE, uid_wl, top_table_rank_view,
                    cols_step=6,
                    key_fn=lambda i, m, dn=data_dir_name: f"wlstar_{dn}_{i}",
                )
        else:
            try:
                _st_dataframe_all_rows(_df_disp)
            except Exception:
                _st_dataframe_all_rows(df_top)

        st.markdown("---")

    tab_diff, tab_sector, tab_charts = st.tabs(["신규·탈락", "섹터 분포", "차트 뷰어"])

    with tab_diff:
        added = payload.get("last_diff_added", [])
        removed = payload.get("last_diff_removed", [])
        baseline = payload.get("diff_baseline_date", "-")
        st.caption(f"비교 기준일: **{baseline}**")
        _weinstein_tip_caption(salt=f"diff:{data_dir_name}")

        ca, cr = st.columns(2)
        with ca:
            st.markdown(
                f'<div style="font-size:0.9rem;font-weight:800;color:#15803d;'
                f'margin-bottom:0.4rem;">🟢 신규 진입 {len(added)}개</div>',
                unsafe_allow_html=True,
            )
            if added:
                import pandas as _pd
                if is_surge_scanner:
                    _st_dataframe_all_rows(_pd.DataFrame([{
                        "티커": r.get("ticker", ""),
                        "종목명": r.get("name", ""),
                        "시장": _local_surge_labels(r)[0],
                        "섹터": _local_surge_labels(r)[1],
                        "테마": _local_surge_labels(r)[2],
                        "점수": r.get("score", "-"),
                    } for r in added]))
                else:
                    _st_dataframe_all_rows(_pd.DataFrame([{
                        "티커": r.get("ticker", ""),
                        "종목명": r.get("name", ""),
                        "섹터": r.get("sector", ""),
                        "점수": r.get("score", "-"),
                    } for r in added]))
            else:
                st.info("없음")

        with cr:
            st.markdown(
                f'<div style="font-size:0.9rem;font-weight:800;color:#b91c1c;'
                f'margin-bottom:0.4rem;">🔴 탈락 {len(removed)}개</div>',
                unsafe_allow_html=True,
            )
            if removed:
                import pandas as _pd
                if is_surge_scanner:
                    _st_dataframe_all_rows(_pd.DataFrame([{
                        "티커": r.get("ticker", ""),
                        "종목명": r.get("name", ""),
                        "시장": _local_surge_labels(r)[0],
                        "섹터": _local_surge_labels(r)[1],
                        "테마": _local_surge_labels(r)[2],
                    } for r in removed]))
                else:
                    _st_dataframe_all_rows(_pd.DataFrame([{
                        "티커": r.get("ticker", ""),
                        "종목명": r.get("name", ""),
                        "섹터": r.get("sector", ""),
                    } for r in removed]))
            else:
                st.info("없음")

        st.divider()
        st.markdown(
            f'<div style="display:flex;gap:1rem;flex-wrap:wrap;margin-bottom:0.5rem;">'
            f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:0.4rem 0.8rem;'
            f'background:#f0fdf4;font-size:0.82rem;">'
            f'<span style="color:#64748b;">누적 신규</span>&nbsp;'
            f'<b style="color:#15803d;font-size:1.0rem;">{total_added_hist}</b></div>'
            f'<div style="border:1px solid #e2e8f0;border-radius:8px;padding:0.4rem 0.8rem;'
            f'background:#fff1f2;font-size:0.82rem;">'
            f'<span style="color:#64748b;">누적 탈락</span>&nbsp;'
            f'<b style="color:#b91c1c;font-size:1.0rem;">{total_removed_hist}</b></div>'
            f'</div>',
            unsafe_allow_html=True,
        )
        st.caption(f"저장 DB: `{diff_db_path}` · 최신 200건")
        if recent_hist_rows:
            import pandas as _pd
            _st_dataframe_all_rows(_pd.DataFrame(recent_hist_rows))
        else:
            st.info("누적 이력이 아직 없습니다.")

    with tab_sector:
        if not sector_rows_100:
            st.info("섹터 데이터 없음")
        else:
            import pandas as _pd
            min_universe_n = 3
            sector_rows_visible = [
                r for r in sector_rows_100 if int(r.get("universe_n") or 0) >= min_universe_n
            ]
            universe_total = sum(int(v) for v in (universe_sector_counts or {}).values())
            st.caption(
                f"상위30 비중 기준 정렬 · 유니버스 3종목 이상 섹터만 표시 · 합계 {universe_total}종"
            )
            _weinstein_tip_caption(salt=f"sector:{data_dir_name}")

            if str(data_dir_name) == "kospi_data":
                with st.expander("섹터 + ETF 활용법", expanded=False):
                    st.markdown(
                        "섹터 상위% 가 높을수록 해당 업종에 Stage2 종목이 많이 집중된 것입니다. "
                        "코스피 섹터에는 **참고 ETF**가 표시되며, 흐름 비교용입니다. "
                        "실제 보유 종목·비중은 발행사 공시를 확인하세요."
                    )

            cards_sec = sorted(
                sector_rows_visible,
                key=lambda r: (-int(r.get("top30_pct_int") or 0), -float(r.get("avg_score") or 0.0)),
            )
            cols_per_row = 4
            for i in range(0, len(cards_sec), cols_per_row):
                row_items = cards_sec[i: i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, r in zip(cols, row_items):
                    sec = str(r.get("sector") or "-")
                    pct = int(r.get("top30_pct_int") or 0)
                    top30_n = int(r.get("top30_n") or 0)
                    uni_n = int(r.get("universe_n") or 0)
                    avg_s = float(r.get("avg_score") or 0.0)

                    # 상위% 색상
                    if pct <= 10:
                        pct_color = "#15803d"
                    elif pct <= 30:
                        pct_color = "#b45309"
                    else:
                        pct_color = "#64748b"

                    etf_html = ""
                    if str(data_dir_name) == "kospi_data":
                        _tk, _el = _kospi_sector_etf_pair(sec)
                        if _tk:
                            etf_html = (
                                f'<div style="margin-top:0.3rem;color:#0f766e;'
                                f'font-size:0.72rem;">'
                                f'{html.escape(_el)} '
                                f'<span style="color:#94a3b8;">{html.escape(_tk)}</span></div>'
                            )
                    with col:
                        st.markdown(
                            f"""<div style="border:1px solid #e2e8f0;border-radius:12px;
                                padding:0.65rem 0.8rem;background:#ffffff;
                                box-shadow:0 1px 3px rgba(15,23,42,0.07);
                                min-height:110px;">
                              <div style="font-weight:800;color:#0f172a;
                                  font-size:0.9rem;">{html.escape(sec)}</div>
                              <div style="font-size:1.0rem;font-weight:800;
                                  color:{pct_color};margin-top:0.1rem;">상위 {pct}%</div>
                              <div style="font-size:0.75rem;color:#2563eb;
                                  margin-top:0.1rem;">평균 {avg_s:.1f}점</div>
                              <div style="font-size:0.7rem;color:#64748b;">
                                  상위30 {top30_n}개 / {uni_n}종</div>
                              {etf_html}
                            </div>""",
                            unsafe_allow_html=True,
                        )

            # 섹터 요약 테이블
            rows_sec = []
            for rk, r in enumerate(sorted(
                sector_rows_visible,
                key=lambda r: (-int(r.get("top30_pct_int") or 0), -int(r.get("top30_n") or 0), -float(r.get("avg_score") or 0.0)),
            ), start=1):
                row_s: dict[str, Any] = {
                    "섹터": r.get("sector", ""),
                    "랭킹": rk,
                    "상위%": f"{int(r.get('top30_pct_int') or 0)}%",
                    "평균점수": r.get("avg_score"),
                    "최고점수": r.get("max_score"),
                    "상위30": int(r.get("top30_n") or 0),
                    "유니버스": int(r.get("universe_n") or 0),
                }
                if str(data_dir_name) == "kospi_data":
                    _tk, _el = _kospi_sector_etf_pair(str(r.get("sector") or ""))
                    row_s["참고ETF"] = f"{_el}({_tk})" if _tk else "—"
                rows_sec.append(row_s)
            if rows_sec:
                _st_dataframe_all_rows(_pd.DataFrame(rows_sec))

            st.divider()
            st.subheader("섹터별 종목")
            sector_labels_drill = [str(r.get("sector") or "미분류") for r in cards_sec]
            if sector_labels_drill:
                def _sec_drill_ret(m: dict[str, Any]) -> float | None:
                    v = m.get("ret_since_entry_pct")
                    if v is not None:
                        try:
                            return float(v)
                        except (TypeError, ValueError):
                            return None
                    try:
                        return float(m.get("ret_3m_pct") or 0)
                    except (TypeError, ValueError):
                        return None

                pick_sec = st.pills(
                    "분석할 섹터",
                    options=sector_labels_drill,
                    selection_mode="single",
                    default=sector_labels_drill[0],
                    key=f"sector_drill_pick_{data_dir_name}",
                )
                if isinstance(pick_sec, list):
                    pick_sec = pick_sec[0] if pick_sec else sector_labels_drill[0]
                pick_sec = str(pick_sec or sector_labels_drill[0])

                meta_sec = next(
                    (r for r in sector_rows_visible if str(r.get("sector") or "미분류") == pick_sec),
                    None,
                )
                picked_matches = [
                    m for m in top_table
                    if _sector_label_for_match(m, is_surge_scanner) == pick_sec
                ]
                picked_matches.sort(key=lambda m: (int(m.get("rank") or 999999), -float(m.get("score") or 0)))

                with st.container(border=True):
                    if meta_sec:
                        mc1, mc2, mc3, mc4 = st.columns(4)
                        _pct_v = int(meta_sec.get("top30_pct_int") or 0)
                        _pct_c = "#15803d" if _pct_v <= 10 else ("#b45309" if _pct_v <= 30 else "#64748b")
                        mc1.markdown(
                            f'<div style="font-size:0.75rem;color:#64748b;">상위%</div>'
                            f'<div style="font-size:1.1rem;font-weight:800;color:{_pct_c};">{_pct_v}%</div>',
                            unsafe_allow_html=True,
                        )
                        mc2.metric("평균점수", f'{float(meta_sec.get("avg_score") or 0):.1f}')
                        mc3.metric("상위30", f'{int(meta_sec.get("top30_n") or 0)}개')
                        mc4.metric("유니버스", f'{int(meta_sec.get("universe_n") or 0)}종')

                    if not picked_matches:
                        st.info("이 섹터에 해당하는 종목이 없습니다.")
                    else:
                        drill_rows: list[dict[str, Any]] = []
                        for m in picked_matches:
                            _drv = m.get("rs_ratio")
                            try:
                                rs_dr = f"{float(_drv):.3f}" if _drv is not None else "—"
                            except (TypeError, ValueError):
                                rs_dr = "—"
                            dr: dict[str, Any] = {
                                "순위": int(m.get("rank") or 0),
                                "종목명": m.get("name", ""),
                                "티커": m.get("ticker", ""),
                                "점수": round(float(m.get("score") or 0), 1),
                                "진입후수익": _sec_drill_ret(m),
                                "RS": rs_dr,
                                "1Δ": m.get("rank_delta_1d", "—"),
                                "3Δ": m.get("rank_delta_3d", "—"),
                                "6Δ": m.get("rank_delta_6d", "—"),
                                "진입일": str(m.get("entry", "") or "—")[:10],
                            }
                            if is_surge_scanner:
                                _mk, _sc_l, _th = _local_surge_labels(m)
                                dr["시장"] = _mk
                                dr["테마"] = _th
                            drill_rows.append(dr)

                        drill_df = _pd.DataFrame(drill_rows)
                        _order_d = (
                            ["순위", "종목명", "티커", "점수", "진입후수익", "시장", "테마", "RS", "1Δ", "3Δ", "6Δ", "진입일"]
                            if is_surge_scanner
                            else ["순위", "종목명", "티커", "점수", "진입후수익", "RS", "1Δ", "3Δ", "6Δ", "진입일"]
                        )
                        drill_df = drill_df[[c for c in _order_d if c in drill_df.columns]]

                        def _sty_drill_ret(v: Any) -> str:
                            try:
                                x = float(str(v).replace("%", "").replace("+", "")) if isinstance(v, str) else float(v or 0)
                                if x >= 10.0:
                                    return "color:#15803d;font-weight:800;"
                                if x >= 3.0:
                                    return "color:#166534;font-weight:700;"
                                if x >= 0.0:
                                    return "color:#374151;"
                                if x >= -5.0:
                                    return "color:#991b1b;"
                                return "color:#b91c1c;font-weight:700;"
                            except (TypeError, ValueError):
                                return ""

                        drill_sty = drill_df.style
                        if hasattr(drill_sty, "map"):
                            drill_sty = drill_sty.map(_sty_drill_ret, subset=["진입후수익"])
                            drill_sty = drill_sty.map(_sty_delta, subset=[c for c in ["1Δ", "3Δ", "6Δ"] if c in drill_df.columns])
                        elif hasattr(drill_sty, "applymap"):
                            drill_sty = drill_sty.applymap(_sty_drill_ret, subset=["진입후수익"])
                            drill_sty = drill_sty.applymap(_sty_delta, subset=[c for c in ["1Δ", "3Δ", "6Δ"] if c in drill_df.columns])

                        _cc_drill = {
                            "순위": st.column_config.NumberColumn("순위", width="small"),
                            "점수": st.column_config.NumberColumn("점수", format="%.1f"),
                            "진입후수익": st.column_config.NumberColumn("진입후수익", format="%.2f%%"),
                        }
                        try:
                            st.dataframe(
                                drill_sty,
                                use_container_width=True,
                                hide_index=True,
                                column_config=_cc_drill,
                            )
                        except Exception:
                            _st_dataframe_all_rows(drill_df, column_config=_cc_drill)

    with tab_charts:
        matches    = payload.get("matches", [])
        chart_items = [m for m in matches if m.get("chart")]
        if not chart_items:
            st.info("저장된 차트 없음 — 스캔 시 자동 생성됩니다.")
        else:
            if is_surge_scanner:
                st.markdown("**차트 필터**")
                filter_kind = st.selectbox(
                    "분류 기준",
                    ["시장", "섹터", "테마"],
                    key=f"surge_filter_kind_{data_dir_name}",
                )
                label_fn = (
                    (lambda x: _local_surge_labels(x)[0]) if filter_kind == "시장" else
                    (lambda x: _local_surge_labels(x)[1]) if filter_kind == "섹터" else
                    (lambda x: _local_surge_labels(x)[2])
                )
                all_labels = sorted({label_fn(m) for m in chart_items})
                sel_label = st.selectbox(
                    f"{filter_kind} 선택",
                    ["전체"] + all_labels,
                    key=f"surge_filter_value_{data_dir_name}",
                )
                filtered = chart_items if sel_label == "전체" else [m for m in chart_items if label_fn(m) == sel_label]
            else:
                if str(data_dir_name) == "etf_data":
                    st.session_state.setdefault("etf_data_sector_filter", _ETF_SECTOR_FILTER_OPTIONS[0])
                    sel_sector = str(st.session_state.get("etf_data_sector_filter") or "전체")
                    st.caption(
                        f"차트는 상단 **섹터 필터**와 동일하게 적용됩니다. (현재: **{html.escape(sel_sector)}**)"
                    )
                    filtered = (
                        chart_items
                        if sel_sector == "전체"
                        else [m for m in chart_items if str(m.get("sector") or "").strip() == sel_sector]
                    )
                else:
                    all_sectors = sorted({m.get("sector", "미분류") for m in chart_items})
                    sel_sector = st.selectbox(
                        "섹터 필터",
                        ["전체"] + all_sectors,
                        key=f"sec_{data_dir_name}",
                    )
                    filtered = (
                        chart_items
                        if sel_sector == "전체"
                        else [m for m in chart_items if m.get("sector") == sel_sector]
                    )
            _weinstein_tip_caption(salt=f"charts:{data_dir_name}")
            st.caption(f"차트 {len(filtered)}개 · 와인스타인식으로는 **2단계 추세**를 눈으로 확인하는 보조 도구에 가깝습니다.")
            cols_per_row = 2
            for i in range(0, len(filtered), cols_per_row):
                row_items = filtered[i: i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, item in zip(cols, row_items):
                    with col:
                        chart_path = CHARTS_DIR / item["chart"]
                        caption = (
                            f"**#{item.get('rank')} {item.get('name')}** · "
                            f"점수 {item.get('score', 0):.1f} · 진입 {item.get('entry', '-')}"
                        )
                        if chart_path.exists():
                            st.image(str(chart_path), caption=caption,
                                     use_container_width=True)
                        else:
                            st.warning(f"차트 없음: {item['chart']}")


def _render_page_kosdaq() -> None:
    _render_scanner_page(
        title="코스닥 Stage2 스캐너",
        data_dir_name="kosdaq_data",
        module_name="kosdaq_export_core",
        candidates_module="kosdaq_candidates",
        index_label="코스닥",
    )


def _render_page_kospi() -> None:
    _render_scanner_page(
        title="📊 코스피 Stage2 순위",
        data_dir_name="kospi_data",
        module_name="kospi_export_core",
        candidates_module="kospi_candidates",
        index_label="코스피",
    )


def _render_page_etf() -> None:
    _render_scanner_page(
        title="ETF Stage2 추천",
        data_dir_name="etf_data",
        module_name="etf_export_core",
        candidates_module="etf_candidates",
        index_label="코스피",
    )


def _render_market_kospi_kosdaq_banners() -> None:
    """시장 진입 시 코스피·코스닥으로 안내하는 대형 배너(탭은 하단 유지)."""

    b1, b2 = st.columns(2)
    with b1:
        st.markdown(
            """
<div style="border-radius:18px;padding:clamp(1.25rem,3vw,2.1rem) 1.4rem;
background:linear-gradient(135deg,#1d4ed8 0%,#0f172a 52%,#0b1220 100%);
border:1px solid rgba(96,165,250,0.4);box-shadow:0 10px 28px rgba(15,23,42,0.4);">
<div style="font-size:clamp(1.55rem,4.5vw,2.25rem);font-weight:900;color:#f8fafc;letter-spacing:-0.03em;line-height:1.15;">
코스피 Stage2</div>
<div style="margin-top:0.55rem;font-size:clamp(0.95rem,2.5vw,1.12rem);color:#bfdbfe;line-height:1.5;">
섹터 · 순위 · RS · 진입일까지 한 스캐너</div>
<div style="margin-top:0.85rem;font-size:0.84rem;color:#94a3b8;">아래 메뉴에서 <b style="color:#e2e8f0;">코스피 스캐너</b>를 누르세요</div>
</div>
            """,
            unsafe_allow_html=True,
        )
    with b2:
        st.markdown(
            """
<div style="border-radius:18px;padding:clamp(1.25rem,3vw,2.1rem) 1.4rem;
background:linear-gradient(135deg,#0f766e 0%,#0f172a 52%,#0b1220 100%);
border:1px solid rgba(45,212,191,0.38);box-shadow:0 10px 28px rgba(15,23,42,0.4);">
<div style="font-size:clamp(1.55rem,4.5vw,2.25rem);font-weight:900;color:#f8fafc;letter-spacing:-0.03em;line-height:1.15;">
코스닥 Stage2</div>
<div style="margin-top:0.55rem;font-size:clamp(0.95rem,2.5vw,1.12rem);color:#99f6e4;line-height:1.5;">
KQ11 벤치 · 섹터 요약 · Δ순위</div>
<div style="margin-top:0.85rem;font-size:0.84rem;color:#94a3b8;">아래 메뉴에서 <b style="color:#e2e8f0;">코스닥 스캐너</b>를 누르세요</div>
</div>
            """,
            unsafe_allow_html=True,
        )


def _render_page_home() -> None:
    with _portal_page_card():
        group_labels = [lbl for lbl, _ in _HOME_GROUP_SPEC]
        group_keys = [k for _, k in _HOME_GROUP_SPEC]
        # st.tabs 는 매 rerun 시 모든 탭 본문이 실행되어(날씨·시장 JSON 등) NAS에서 매우 무거움.
        # 배너(버튼) 또는 라디오 모두 **선택한 그룹만** `_HOME_GROUP_DISPATCH` 로 렌더 → 동일하게 가볍게 유지.
        _HOME_GROUP_PICK_KEY = "home_group_pick"
        if _HOME_GROUP_PICK_KEY not in st.session_state:
            _legacy = st.session_state.get("home_group_pick_radio")
            st.session_state[_HOME_GROUP_PICK_KEY] = (
                _legacy if _legacy in group_labels else group_labels[0]
            )
        pick = str(st.session_state.get(_HOME_GROUP_PICK_KEY, group_labels[0]))
        if pick not in group_labels:
            pick = group_labels[0]
            st.session_state[_HOME_GROUP_PICK_KEY] = pick

        st.caption("아래 **배너**에서 섹션을 고르면 해당 내용만 로드됩니다.")
        row1 = st.columns(4)
        row2 = st.columns(3)
        for i, (lbl, gk) in enumerate(zip(group_labels, group_keys)):
            col = row1[i] if i < 4 else row2[i - 4]
            with col:
                if st.button(
                    lbl,
                    key=f"home_grp_btn_{gk}",
                    use_container_width=True,
                    type="primary" if pick == lbl else "secondary",
                ):
                    st.session_state[_HOME_GROUP_PICK_KEY] = lbl
        pick = str(st.session_state[_HOME_GROUP_PICK_KEY])
        key = group_keys[group_labels.index(pick)]
        _HOME_GROUP_DISPATCH[key]()


def _render_page_haksa() -> None:
    with _portal_page_card():
        st.header("📚 학사정보")
        st.caption("초등 → 중등 → 대학입시 순서로, 학년별 준비 로드맵과 지역/운동 가이드를 함께 봅니다.")
        ht1, ht2, ht3 = st.tabs(["📘 초등", "📙 중등", "🎓 대학입시"])
        with ht1:
            st.subheader("학년별 준비 로드맵 (초등)")
            rows_elem = [
                {"학년": "1~2학년", "학습": "읽기·쓰기·연산 자동화, 책 읽는 습관", "생활/정서": "등하교 루틴·수면시간 고정", "부모 체크": "담임 소통, 결석/지각 패턴 점검"},
                {"학년": "3~4학년", "학습": "독해(비문학)·기본 영문장·수학 서술형 시작", "생활/정서": "친구관계·디지털 사용 규칙", "부모 체크": "과목별 약점 1개씩 보완 계획"},
                {"학년": "5~6학년", "학습": "중등 선행은 최소화, 개념·독해·서술형 완성", "생활/정서": "자기주도 시간표(주간 계획)", "부모 체크": "중학교 배정/학군 일정 확인"},
            ]
            if pd is not None:
                st.dataframe(pd.DataFrame(rows_elem), use_container_width=True, hide_index=True)
            else:
                st.table(rows_elem)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🏫 지역 학원 선택 가이드")
                st.markdown(
                    "- 통학 20~30분 이내 우선\n"
                    "- 반 정원/레벨테스트 기준 공개 여부\n"
                    "- 월간 피드백(학부모 리포트) 유무\n"
                    "- 숙제량보다 오답 관리 품질 확인\n"
                    "- 4주 체험 후 유지/변경 판단"
                )
            with c2:
                st.markdown("#### ⚽ 운동·체력 루틴")
                st.markdown(
                    "- 주 3회 이상 유산소(축구·수영·농구·줄넘기)\n"
                    "- 자세·유연성(성장기 부상 예방) 포함\n"
                    "- 학원 많은 날은 20분 걷기라도 유지\n"
                    "- 취침 1시간 전 스크린 최소화\n"
                    "- 평일 수면 9시간 내외 목표"
                )
            _render_tab_elem()
        with ht2:
            st.subheader("학년별 준비 로드맵 (중등)")
            rows_mid = [
                {"학년": "중1", "학습": "수학 개념/오답노트, 영어 문법 기초", "생활/정서": "자습 시간 고정(하루 1.5~2h)", "부모 체크": "중간·기말 과목별 학습법 정착"},
                {"학년": "중2", "학습": "과학·사회 서술형, 독해량 확대", "생활/정서": "스마트폰/게임 사용시간 관리", "부모 체크": "내신+비교과 균형(동아리/독서)"},
                {"학년": "중3", "학습": "내신 안정화 + 고등과정 기초 연결", "생활/정서": "진로탐색(계열/학교유형)", "부모 체크": "고교 선택 일정·설명회 체크"},
            ]
            if pd is not None:
                st.dataframe(pd.DataFrame(rows_mid), use_container_width=True, hide_index=True)
            else:
                st.table(rows_mid)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🏫 지역 학원 운영 체크")
                st.markdown(
                    "- 과목별 강사 고정 여부\n"
                    "- 내신 기간 보강/자습 관리 방식\n"
                    "- 시험 후 오답 리포트 제공 여부\n"
                    "- 학원 2개 이상 병행 시 과제 총량 확인\n"
                    "- 성적보다 학습 습관 개선률을 같이 점검"
                )
            with c2:
                st.markdown("#### 🏃 운동·생활 습관")
                st.markdown(
                    "- 주 3회 40~60분 운동(심폐+근지구력)\n"
                    "- 장시간 앉는 날은 스트레칭 10분\n"
                    "- 카페인 음료 늦은 시간 제한\n"
                    "- 시험 2주 전에도 운동 강도만 낮춰 유지\n"
                    "- 평일 수면 8시간 이상 목표"
                )
            _render_tab_mid()
        with ht3:
            st.subheader("학년별 준비 로드맵 (대학입시)")
            rows_adm = [
                {"학년": "고1", "학습": "전과목 기본기·내신 체계 확립", "입시 준비": "희망 전공 탐색, 학생부 기록 습관", "부모 체크": "무리한 선행보다 결손 과목 제거"},
                {"학년": "고2", "학습": "과탐/사탐 선택 확정, 모의고사 약점 보완", "입시 준비": "학생부 활동의 일관성(전공 연계)", "부모 체크": "수시/정시 비중 초안 설정"},
                {"학년": "고3", "학습": "킬러보다 실수 관리·시간 배분", "입시 준비": "원서 전략(상향/적정/안정)과 일정 관리", "부모 체크": "컨디션·수면·멘탈 안정 지원"},
            ]
            if pd is not None:
                st.dataframe(pd.DataFrame(rows_adm), use_container_width=True, hide_index=True)
            else:
                st.table(rows_adm)
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### 🧭 지역 입시/학원 정보 활용법")
                st.markdown(
                    "- 학교 진학부·교육청 설명회 일정을 먼저 확인\n"
                    "- 입시컨설팅은 '기록 정리' 목적 중심으로 활용\n"
                    "- 학원 선택 시 최근 2~3년 실적 공개 기준 확인\n"
                    "- 합격사례보다 유사 성적대 전략을 우선 검토\n"
                    "- 비용/환불/교재비 조건을 계약 전 확인"
                )
            with c2:
                st.markdown("#### 🏋️ 고등 운동·컨디션 관리")
                st.markdown(
                    "- 주 3회 30~45분 유산소(집중력 유지)\n"
                    "- 허리·목·어깨 보강(장시간 앉음 대비)\n"
                    "- 시험기엔 강도 70%로만 유지\n"
                    "- 수면 우선(최소 7시간, 가능하면 7.5~8시간)\n"
                    "- 주간 1회 완전 휴식 블록 확보"
                )
            _render_tab_edu()


def _render_page_learning_prep() -> None:
    with _portal_page_card():
        st.header("📖 학습준비")
        st.caption("방송·공교육 포털·진학 참고 링크입니다. 세부 일정은 학교·교육청 안내를 따르세요.")
        _render_curated_link_blocks(LEARNING_PREP_SITES, key_prefix="learn")


def _render_page_ybm_ecc_curriculum() -> None:
    """YBM·ECC 재원 아동 가정 연계 참고 — 비공식 안내."""
    with _portal_page_card():
        st.header("📘 YBM·어학 커리큘럼 · ECC 가정 가이드")
        st.caption(
            "**YBM 공식 페이지가 아닙니다.** 과정명·교재·레벨·원비는 **지점·연도**마다 다릅니다. "
            "항상 **원·담임 선생님 안내**를 우선하세요."
        )
        st.warning(
            "아래는 **ECC·유아·초등 영어**를 다니는 아이가 있는 가정을 위한 **교양용 정리**입니다. "
            "입시·치료·학습장애 판단은 전문가에게 맡기세요.",
            icon="⚠️",
        )

        y1, y2, y3, y4, y5 = st.tabs(
            [
                "🏫 ECC·영어 루틴",
                "📚 집에서 연계하기",
                "🔗 YBM·공부 자료",
                "📈 레벨·평가 감각",
                "💬 부모 마음가짐",
            ],
        )
        with y1:
            st.markdown(
                """
##### ECC 다닐 때 흔한 방향(일반론)
- **노출 시간**: 주당 수업 시간만으로는 **부족**하다는 말이 자주 나옵니다. 집에서는 **짧게라도 매일** 듣기·말하기가 도움이 됩니다.
- **말하기 부담**: 아이가 **틀려도** 일단 말하게 두기. 교정은 **한두 가지만** 짧게(전체 문장 고치기 반복은 기피로 이어질 수 있음).
- **리듬**: 등원 전 **영어 노래·책 한 권**이 하루 시작을 고정해 주면 부모 스트레스가 줄어듭니다.
- **숙제**: 원에서 내준 범위를 **끝내기 vs 이해하기** 중 무엇을 우선할지 선생님과 기준을 맞추면 갈등이 줄어듭니다.
                """
            )
        with y2:
            st.markdown(
                """
##### 집 연계 (바쁜 부모용)
- **그림책**: 단어 몰라도 **그림 추측**하게 두기. 부모가 매번 한글로 설명만 하면 **영어 듣기 시간**이 줄어듭니다.
- **팟캐스트·노래**: 이동·식사·취침 전 **5~10분**. 화면이 부담이면 **오디오만**.
- **파닉스·스펠링**: 원에서 배우는 **책자·앱**이 있으면 그걸로 통일. **여러 체계를 동시에** 섞으면 아이가 헷갈릴 수 있습니다.
- **한글 학습과의 균형**: 국어·수학 기초가 흔들리면 **영어만 늘어난 것처럼 보여도** 중장기로 부담이 될 수 있습니다. **수면·놀이 시간**을 지키는 것도 실력입니다.
                """
            )
            st.info(
                "**스크린 타임**은 가족 규칙을 정해 두고(식사·침대 위 금지 등), ECC 화상·앱이 있으면 **누적 시간**을 의식하세요.",
                icon="💡",
            )
        with y3:
            st.markdown(
                """
##### 공식·검색 시작점
- [YBM 본사](https://www.ybm.co.kr/) — 프로그램·지점 안내는 **최신 공지**를 확인하세요.
- [YBM 시사닷컴](https://www.ybmsisa.com/) — 어학·출판·강좌 정보가 함께 올라오는 경우가 많습니다.
- **지점**: 전화·방문 시 **체험·레벨 테스트·교재**를 직접 확인하는 것이 가장 정확합니다.

##### 무료·저가 보조(선택)
- **공영 EBS 영어** · **지역도서관 영어도서** — 부담 없이 **노출량**만 늘리기 좋습니다.
- **OPIC / 성인 영어**는 같은 앱의 **다른 메뉴**와 섞지 말고, 아이 학습은 **유아용 콘텐츠** 위주로 검색하세요.
                """
            )
        with y4:
            st.markdown(
                """
##### 레벨·평가를 볼 때
- **동년배 비교**: SNS·학원 로비에서 듣는 ‘우리 아이 레벨’은 **참고**만. 커리큘럼이 다르면 숫자만으로 비교가 어렵습니다.
- **정체 구간**: 한 레벨에 **오래 머무는 것**이 이상이 아닐 수 있습니다. **기초 체득**이 오히려 중요한 경우가 많습니다.
- **말하기·듣기·읽기·쓰기** 균형: 시험 위주로 가면 **말하기**가 뒤처질 수 있어, 원의 목표와 **집에서 보완할 축**을 나눠 보세요.
- **리포트**: 월간·분기 피드백이 있으면 **한 줄이라도** 메모해 두었다가 3개월 뒤와 비교하면 방향이 보입니다.
                """
            )
        with y5:
            st.markdown(
                """
##### 비교·불안 줄이기
- **다른 가정과 비교**는 정보가 불완전할 때 특히 위험합니다. **우리 아이의 수면·식사·놀이**가 먼저인지 점검해 보세요.
- **부모 영어**: 부모가 유창하지 않아도 **함께 듣기·따라 읽기**만으로도 태도 모델이 됩니다.
- **번아웃**: 학원·알림장·준비물이 겹치면 **한 가지를 줄이는** 선택도 장기적으로 이득일 수 있습니다.
- **같이 쉬는 날**: 가끔은 **영어 없는 하루**도 관계 회복에 도움이 됩니다. 다음 날 다시 리듬을 잡으면 됩니다.
                """
            )


def _render_page_phishing_prevention() -> None:
    """스미싱·피싱·보이스피싱 예방 — 공식 링크·상담 번호는 기관 공지 우선."""
    with _portal_page_card():
        st.header("🛡️ 피싱·보이스피싱 예방")
        st.caption(
            "최근에는 **문자(스미싱)·카톡·가짜 앱·AI 음성**까지 수법이 다양합니다. "
            "**번호·신고 절차는 기관 공식 안내**가 정확합니다."
        )
        st.warning(
            "이 페이지는 **법률·수사 조언이 아닙니다.** 큰 금액·협박이 있으면 **112** 등 **즉시 신고**하세요.",
            icon="⚠️",
        )

        p1, p2, p3, p4 = st.tabs(
            ["📌 최근 수법·트렌드", "✅ 예방 노하우", "🔗 공식 사이트·신고", "🆘 피해를 줄이려면"],
        )
        with p1:
            st.markdown(
                """
##### 자주 바뀌는 수법(일반)
- **스미싱**: 택배·대출·검찰·은행 사칭 **링크**를 문자로 보냄. 링크만 눌러도 **악성앱·피싱 페이지**로 연결될 수 있음.
- **보이스피싱**: 수사기관·은행·자녀 사칭, **‘비밀 조사’** 를 핑계로 **계좌·OTP** 요구. **화상(딥페이크) 얼굴**까지 쓰는 사례가 늘고 있음.
- **메신저·SNS**: 지인인 척 **급전·투자** 권유, **가짜 중고거래** 링크.
- **가짜 앱**: 공식 스토어가 아닌 **APK·설치 파일**로 유도. **원격 제어·코인 지갑** 탈취 목적.
- **투자·코인**: **수익 인증**·채팅방에서 **선입금** 유도. 정식 증권사·거래소와 **도메인·앱 이름**을 비슷하게 흉내.

##### 공통 심리
- **급함**: “지금 안 하면 동결·체포” — 시간을 벌어 **확인**하게 만드는 것이 핵심입니다.
- **권위**: 제복·로고·공문 **이미지**는 쉽게 조작됩니다.
                """
            )
        with p2:
            st.markdown(
                """
##### 기본 원칙
1. **링크를 누르지 않기** — 필요하면 **직접 공식 앱·홈페이지 주소**를 입력하거나 즐겨찾기 사용.
2. **전화로 온 사람을 그대로 믿지 않기** — **끊고**, 명함·앱에 나온 **대표번호로 다시 걸기**(콜백).
3. **OTP·공인인증서·비밀번호·계좌번호**를 전화·화면 공유로 알려주지 않기.
4. **원격 제어(AnyDesk, TeamViewer 등)** 설치 요구 시 **거절** — 금융기관·수사기관이 이렇게 요구하지 않습니다.
5. **앱은 공식 스토어**만. 문자·메일의 ‘업데이트’ 링크는 가짜인 경우가 많습니다.
6. **가족·지인 급전 요청**은 **다른 채널**(직접 통화·만남)으로 한 번 더 확인.
7. **투자 초대**는 **수익을 보장**하는 말이 나오면 의심. **냉정한 날**에 다시 읽기.
8. **개인정보**는 ‘확인’이 아니라 **수집 목적**을 보고 최소한만.
9. **스마트폰 OS·앱·백신** 최신 유지, **의심 문자는 차단·신고** 습관.
10. **의심스러우면** 아무것도 하지 않고 **신고·상담 번호**부터 검색.

##### 가정·노년 부모
- **큰 금액 이체** 전에 **가족 암호 한 마디**로 확인.
- 스피커폰으로 **함께 통화**해 주기(보이스피싱은 고립시키려 함).
                """
            )
        with p3:
            st.markdown(
                """
##### 주요 기관(링크는 공식 홈에서 최신 경로 확인)
- [한국인터넷진흥원 KISA](https://www.kisa.or.kr/) — 스미싱·피싱 예방·신고 안내
- [경찰청 사이버안전국](https://cyberbureau.police.go.kr/) — 사이버범죄 신고·유형별 대응
- [금융감독원](https://www.fss.or.kr/) — 금융 사기·불법 대출·보이스피싱 관련 민원·안내
- [KrCERT/CC 인터넷침해대응지원센터](https://www.krcert.or.kr/) — 침해사고 대응 정보

##### 전화·신고(기억하기 쉬운 번호 — **세부는 기관 공지 우선**)
- **112** — 긴급 범죄·신변 위협
- **KISA 통합신고 118** — 인터넷·스미싱 등 **침해사고·불법 스팸** 상담·신고(운영 시간·절차는 KISA 안내)
- **금융감독원 국번 없이 1332** — 금융 관련 사기·불법행위 신고·상담(공식 안내 확인)

##### 검색 팁
- 기관명 + **‘공식’** 으로 검색할 때 **광고 링크**와 **실제 도메인**을 구분하세요.
                """
            )
        with p4:
            st.markdown(
                """
##### 이미 링크를 눌렀거나 정보를 말한 뒤라면
1. **당황해도** 곧바로 **통화 종료** — 추가 정보를 주지 않기.
2. **금융**이면 **해당 은행·카드사 공식 번호**(카드 뒷면·앱)로 연락해 **이체·한도** 확인, 필요 시 **지급정지·계좌 동결** 요청.
3. **원격 프로그램**을 설치했다면 **네트워크 끊기** → 프로그램 삭제 → **백신 검사** → **비밀번호 변경**(다른 기기에서).
4. **앱 설치**를 했다면 **공식 스토어 외 APK**는 삭제 후 **공식 앱만** 재설치 검토.
5. **증거 보존**: 문자·캡처·통화 녹취(법적 제한 있을 수 있음) — **신고 시 도움**이 될 수 있음.
6. **2차 피해** 방지: 같은 비밀번호를 **다른 사이트**에 쓰고 있었다면 **순차적으로 변경**.

##### 정서적 대응
- 피해를 입었어도 **가해자는 범죄자**입니다. **혼자 해결하려 하지 말고** 가족·신고 창구에 알리는 것이 **추가 피해 예방**에 유리합니다.

---
**가족용**: 이 메뉴를 **부모님 폰 즐겨찾기**에 넣어 두고, **큰 돈이 나가기 전**에 함께 읽는 습관을 추천합니다.
                """
            )


def _render_page_tech_industry() -> None:
    """반도체·자동차 등 최신 산업 동향 요약 — 투자 권유 아님, 시점별로 뉴스 확인 필요."""
    with _portal_page_card():
        st.header("⚡ 최신 테크·산업 동향")
        st.caption(
            "반도체·자동차 등 **구조적 이슈**를 한곳에 모았습니다. **수치·실적·주가는 매일 변하므로** "
            "아래 **뉴스·기관 링크**에서 최신 기사를 확인하세요."
        )
        st.warning(
            "**투자·매매 조언이 아닙니다.** 관세·보조금·실적은 분기마다 바뀔 수 있습니다.",
            icon="⚠️",
        )

        z1, z2, z3 = st.tabs(["🔲 반도체·전자", "🚗 자동차·모빌리티", "📰 뉴스·자료 출처"])
        with z1:
            st.markdown(
                """
##### 최근 몇 년간 반복되는 축(개념 정리)
- **AI·데이터센터 수요**: 대규모 언어모델·추론 서비스 확산으로 **고성능 GPU·고대역폭 메모리(HBM)** 수요가 한동안 **업황을 이끄는 변수**로 자주 언급됩니다.
- **첨단 패키징**: 미세 공정만큼 **칩렛·2.5D/3D 적층**이 성능·전력에서 중요해졌고, **OSAT·후공정** 비중이 커졌습니다.
- **파운드리·공정**: 선단 로직은 **소수 파운드리** 중심으로 집중. **공정 미세화·수율**이 원가·납기에 직결됩니다.
- **메모리**: DRAM·NAND는 **가격·재고 사이클**이 뚜렷해 **슈퍼사이클·침체**가 교대로 보도됩니다.
- **지정학·수출 통제**: 반도체 장비·소재는 **국가별 규제·동맹 정책**에 민감합니다. **CHIPS법·수출 허가** 뉴스가 업체 실적에 직접 영향을 줄 수 있습니다.
- **국내 산업**: 메모리·소재·장비·후공정에 **강점**이 있으나, **선단 로직**은 글로벌 경쟁이 치열합니다.

##### 키워드로 뉴스 찾기
`HBM`, `파운드리`, `칩렛`, `EUV`, `후공정`, `CXL`, `전력 사용량 데이터센터` 등.
                """
            )
        with z2:
            st.markdown(
                """
##### 전동화·하이브리드
- **xEV**(BEV·PHEV·HEV) 비중은 지역·규제·충전 인프라에 따라 속도가 다릅니다. **순수 내연만** 고수하는 브랜드는 줄어드는 추세입니다.
- **배터리**: **원재료·리사이클·충전 표준**이 비용·안전 이슈로 자주 다뤄집니다. 국내는 **배터리 3사·소재**와 **OEM 수출**이 함께 언급됩니다.
- **보조금·규제**: 각국 **보조금 축소·관세**는 **차량 가격·수출입** 기사와 연결되어 나옵니다.

##### 소프트웨어·주행
- **ADAS**: 신차에서 **L2 전후(차로 유지·추종)** 가 대중화됐고, **완전 자율(로보택시)** 은 **도시·규제·책임** 이슈가 남아 있습니다.
- **SDV(소프트웨어 정의 차량)**: **OTA 업데이트**·구독 기능·**전장 SW** 비중이 커지면서 IT·완성차 협업·분쟁 뉴스가 늘었습니다.
- **스마트 팩토리·로봇**: 차체·배터리 조립에 **자동화·협동로봇** 도입 사례가 보도됩니다.

##### 시장 구조
- **중국 EV**의 가격·내수 경쟁, **미·유럽**의 관세·환경 규제가 **글로벌 완성차·부품사** 실적 기사에 자주 등장합니다.
- 국내에선 **현대·기아** 글로벌 판매와 **국내 부품·소재** 동반 기사를 함께 보는 편이 구조 이해에 도움이 됩니다.
                """
            )
        with z3:
            st.markdown(
                """
##### 국내 매체·산업
- [전자신문 ETNews](https://www.etnews.com/) — 반도체·디스플레이·전장 빠른 속보
- [디지털타임스](https://www.dt.co.kr/) — IT·정책
- [The Elec](https://thelec.net/) — 디스플레이·반도체 **영문·한글** 산업 뉴스
- [대한무역투자진흥공사 KOTRA](https://www.kotra.or.kr/) — 해외 시장·규제 동향
- [한국무역협회 KITA](https://www.kita.net/) — 수출·통상 통계·보고서
- [한국산업기술진흥원 KIAT](https://www.kiat.or.kr/) — 산업기술 정책

##### 글로벌·영문
- [Reuters Technology](https://www.reuters.com/technology/) · [Bloomberg Technology](https://www.bloomberg.com/technology) — 거시·기업 뉴스
- [IEEE Spectrum](https://spectrum.ieee.org/) — 기술 심화
- [SemiEngineering](https://semiengineering.com/) — 반도체 공정·설계 산업

##### 자동차 전문지
- [Automotive News](https://www.autonews.com/) — 글로벌 완성차·부품
- 국내: ETNews·매경·한경 등 **자동차·모빌리티** 섹션

##### 기업 IR(실적·가이던스)
- 개별 기업 **IR 페이지·분기 실적 발표**는 **공시·본사 자료**가 정확합니다. 이 포털은 **링크만 안내**합니다.

---
**활용 팁**: 같은 키워드로 **한국어·영문**을 번갈아 검색하면 **시차** 있는 이슈(미국 규제·아시아 공급망)를 같이 볼 수 있습니다.
                """
            )


def _render_page_psychology() -> None:
    """일상에 도움이 되는 심리학 요약 — MBTI·인식·부동산·종교. (전문 상담·진단 대체 아님)"""
    with _portal_page_card():
        st.header("🧠 심리학 · 생각의 도구")
        st.caption(
            "아래는 **입문·참고용 정리**입니다. 정신건강의학적 진단·약물·심층 상담은 전문가를 찾으세요."
        )
        st.warning(
            "MBTI·유형 테스트는 **성격의 일부 측면**만 건드립니다. 중요한 결정(채용·임상)의 유일한 근거로 쓰기 어렵습니다.",
            icon="⚠️",
        )

        t1, t2, t3, t4, t5 = st.tabs(
            ["🅼 MBTI", "🛸 우주·외계 인식", "🏠 부동산 심리", "🕯️ 종교·믿음", "📚 더 넣으면 좋은 것"],
        )
        with t1:
            st.subheader("MBTI란 무엇인가")
            st.markdown(
                """
- **출발점**: 융의 심리 유형 이론을 바탕으로 만든 **자기보고식 설문**에서 네 글자 유형(예: INTJ)을 붙이는 도구입니다. **학문적으로 ‘완전한 성격검사’로 인정받지는 않습니다.**
- **네 축(일반적 이해)**: 에너지 방향(E/I), 인식(S/N), 판단(T/F), 생활양식(J/P) — 제품·문항 버전에 따라 세부 정의가 조금씩 다릅니다.
- **잘 쓰는 법**: ‘나와 대화할 때의 경향’을 **말의 출발점**으로 삼기, 팀에서 역할·소통 스타일을 **가볍게** 나누기.
- **조심할 점**: 유형에 **낙인(stereotype)** 을 붙이거나, 채용·승진의 **단일 필터**로 쓰면 오류와 불공정이 커집니다. 성격의 많은 부분은 **Big Five(성실성·외향성 등)** 같은 다른 틀로도 설명됩니다.
                """
            )
            st.info(
                "같은 유형이라도 문화·나이·상황에 따라 행동은 크게 달라질 수 있습니다. **유형 한 줄로 사람을 단정하지 않기**가 실무에서 가장 안전합니다.",
                icon="💡",
            )
        with t2:
            st.subheader("‘우주인’·UAP을 둘러싼 인식 심리")
            st.markdown(
                """
- **패턴 탐지**: 불확실한 빛·소리에서 **의미**를 찾으려는 경향은 인간에게 흔합니다. 때로는 **거짓 양성**(본 것은 맞는데 해석이 빗나감)이 생깁니다.
- **의인화**: 자연 현상에 **의도·주체**를 붙이기 쉬운 인지 편향이 있습니다. 이는 ‘미신’이라기보다 **뇌의 기본 작동**에 가깝습니다.
- **정보 환경**: 반복 노출·같은 믿음의 커뮤니티는 **확증**을 키울 수 있습니다. 반대로 과학 공동체는 **재현·관측 규칙**으로 주장을 거르는 편입니다.
- **존중과 경계**: 타인의 경험담을 **듣는 태도**와, 주장을 **증거 수준에 맞게** 평가하는 것은 별개입니다. 심리학은 “그 믿음이 **어떤 필요**(안전·신비·소속)와 연결되는지”를 이해하는 데 도움을 줄 수 있습니다.
                """
            )
            st.caption(
                "이 섹션은 **외계 생명의 존재 여부를 판정**하지 않습니다. **인지·정서·사회적 요인**을 정리한 참고용입니다."
            )
        with t3:
            st.subheader("부동산 결정을 흔드는 심리")
            st.markdown(
                """
- **앵커링**: 처음 본 가격·전세가이 **기준점**으로 남아 다음 판단을 당깁니다. 비교 매물을 **여러 번·다양한 조건**으로 보는 게 완화에 도움이 됩니다.
- **손실 회피**: ‘오르기 전에’에 반응하기 쉬워 **FOMO(놓칠 공포)** 가 커질 수 있습니다. 반대로 **‘내가 지는 상황’** 을 과하게 피하려 할 수도 있습니다.
- **떼 행동**: 많은 사람이 움직일 때 **안전하다고 느끼는 착각**(정보가 같다는 뜻은 아님)이 생깁니다.
- **시간 압박**: ‘오늘 계약’ 압박은 **인지 여유**를 줄입니다. **하룻밤 규칙**(큰 금액은 잠깐 떼어 두고 다시 읽기)이 실수를 줄이는 경우가 많습니다.
- **프레이밍**: ‘투자’ vs ‘내 집’ 같은 **말의 틀**이 동일 숫자를 다르게 느끼게 합니다. **숫자(금리·관리비·세금·현금흐름)** 를 표로 정리해 두면 덜 흔들립니다.
                """
            )
        with t4:
            st.subheader("종교·영성을 바라보는 심리학")
            st.markdown(
                """
- **종교 심리학**은 특정 교리의 **참·거짓을 판정**하는 학문이 아니라, 믿음·의식·공동체가 **마음·행동·건강**에 어떤 역할을 하는지 연구합니다.
- **의미·소속**: 불확실한 시기에 **해석 틀**과 **관계 네트워크**를 제공할 수 있습니다.
- **대처(coping)**: 기도·명상·예배는 어떤 이에게는 **정서 조절** 경로가 됩니다(개인차 큼).
- **건강한 경계**: 신념이 **타인의 자유를 침해**하지 않는지, **금전·권력**이 과도하게 얽히지 않는지 스스로 점검하는 시각도 심리적으로 중요합니다.
- **다른 관점**: 무신론·불가지론을 포함해, **의미 찾기**의 경로는 사람마다 다를 수 있습니다.
                """
            )
            st.caption(
                "신앙 선택은 개인의 영역입니다. 여기서는 **심리학적 관찰 각도**만 다룹니다."
            )
        with t5:
            st.subheader("이 메뉴에 더 넣으면 좋은 주제(제안)")
            st.markdown(
                """
- **인지 왜곡 목록**: 비관·전부·아니면 전무 등 **자동 사고**를 알아채는 치트시트.
- **수면·스트레스**: 수면 위생, 호흡·HRV 입문(의학적 조언은 전문의).
- **노년·은퇴 전환**: 역할 상실·우울 예방을 **생활 리듬**으로 다루기.
- **소비 심리**: 할인·할부·구독이 **지각된 가치**를 어떻게 바꾸는지.
- **디지털·주의력**: 스크롤·알림이 **작업 기억**에 미치는 영향(개인 실험 팁).
- **부모·자녀**: 애착·칭찬·경계 설정을 **발달 단계**에 맞게(교양용).

원하시면 위 중 하나를 골라 **다음 탭**으로 나누어 넣을 수 있습니다.
                """
            )


def _render_page_cooking() -> None:
    """집밥·레시피 참고 — 영양·알레르기는 개인별로 확인."""
    with _portal_page_card():
        st.header("🍳 요리 · 레시피 & 집밥")
        st.caption(
            "**흐름·비율·습관** 위주로 길게 모았습니다. 분량·열량은 가정마다 다르니 **당·혈압·알레르기**는 전문가와 조절하세요."
        )
        st.warning(
            "생식·장시간 상온 보관·지저분한 도마는 **식중독 위험**이 있습니다. **손 씻기·교차 오염**을 습관화하세요.",
            icon="⚠️",
        )

        r1, r2, r3, r4, r5, r6, r7 = st.tabs(
            [
                "🍚 밥·죽·육수",
                "🍲 국·찌개·찜",
                "🍳 볶음·구이·면",
                "♨️ 전자·압력·에어",
                "🧊 밀프렙·위생",
                "🧂 양념·비율",
                "🔗 채널·표",
            ],
        )
        with r1:
            st.markdown(
                """
##### 밥
- **쌀 씻기**: 찬물로 **3~4회** 정도까지 흐려짐이 줄면 충분한 경우가 많습니다. **과도한 문지르기**는 영양 손실 논쟁이 있으니 가정 룰로 정하기.
- **불리기**: 20~30분 불리면 **알이 고와** 보이는 경우가 많음. 다이어트 쌀은 **물 비율** 따로 확인.
- **밥칸 눈금**은 쌀 종류·불림에 따라 조정. **처음은 눈금보다 약간 적게** 넣어 밍밍함을 막고, 다음 번에 보정.
- **현미·잡곡**: 물·시간이 더 필요한 편. **압력 밥솥** 프리셋 활용.

##### 죽·스프
- **죽**: 불린 쌀 + 많은 물, **저어가며** 눌러붙음 방지. 냉동 해산물은 **완전히 익히기**.
- **육수 베이스**: 멸치·다시마 **불린 물**부터 끓이면 깊이. **다시다·액상**은 **나트륨** 라벨 확인.
                """
            )
        with r2:
            st.markdown(
                """
##### 국·찌개 공통
- **간 순서**: **고춧가루·국간장·된장** 등은 끓는 중간에 나눠 넣고 마지막에 **소금**으로 미세 조정하면 덜 실패.
- **채소 순서**: 뿌리(무·감자·양파) → 단단한 버섯 → 부드러운 채소·두부 → **잎**은 끝.
- **고기**: 냄새 줄이려면 **미리 데치기**·**생강·맛술** 등 가정 룰. **기름기 많은 부위**는 국물이 무거워질 수 있음.

##### 찌개·찜
- **된장찌개**: 된장은 **체에 걸러** 덩어리 줄이기. **두부**는 끝에 넣어 부서짐 감소.
- **김치찌개**: 익은 김치+국물 일부+**설탕/올리고당** 소량으로 산미 밸런스.
- **찜**: **적은 액체·강한 중불→약불**로 증기 활용. **전자렌지 찜기**는 뚜껑 화기 확인.
                """
            )
        with r3:
            st.markdown(
                """
##### 볶음
- **팬 온도**: 물방울이 **타닥**하면 대체로 충분히 예열된 편(종류별 차이 있음).
- **고기 볶음**: **전분·간장 밑간** 후 한 겹으로 펼쳐 **겉만 익히고** 채소 합류.
- **채소 볶음**: 수분 많은 채소는 **소금을 끝**에 두면 물이 덜 나올 때가 많음.

##### 구이·튀김
- **튀김**: 기름 온도 **너무 낮으면 기름 먹고**, 너무 높으면 겉만 탐. **한 번에 너무 많이** 넣지 않기.
- **에어프라이**: **예열** 여부는 기종별. **한 겹**·**중간 뒤집기**. **종이 호일**은 기종·설명서 확인(화재 위험).

##### 면·분식
- **파스타**: 면수 **한 국자**로 소스 농도. **알단테**는 패키지보다 **1분 일찍** 꺼내 맛보기.
- **국수**: 면 건져 **찬물 헹굼** 여부는 면 종류·취향.
- **볶음밥**: 밥을 먼저 **수분 날리기** → 재료 → **간장은 끝**에 색 맞추기.
                """
            )
        with r4:
            st.markdown(
                """
##### 전자레인지
- **덮개**로 수분 유지. **가운데가 안 익으면** 링 모양 배치·중간 섞기.
- **랩** 사용 시 **화기 표시** 있는 제품만, **증기 구멍** 뚫기.

##### 압력솥·전기압력
- **밸브·패킹** 청소 습관. **최대 용량선** 넘지 않기. **빠른 출기** 후 뚜껑 열기.
- **고기·감자**는 시간 단축에 유리. **죽 모드**는 넘침 주의.

##### 에어프라이어
- **바스켓 용량** 넘치면 공기 순환 실패. **기름 없는 요리**도 표면에 **한 방울** 기름이 마이야르에 도움될 수 있음.
- **냉동 만두**: 시간보다 **중간 확인**이 안전.
                """
            )
        with r5:
            st.markdown(
                """
##### 밀프렙
- **3일 이내** 먹을 것만 손질. **샐러드 채소**는 건조·키친타올 후 밀폐.
- **육류 소분**: **납작**하게 눌러 **해동 속도**↑. 라벨에 **날짜·메뉴** 적기.
- **냉동**: **급속 냉동** 후 장기 보관. **재냉동**은 품질·안전 모두 불리.

##### 위생·교차 오염
- **도마·칼**: 생고기용·채소용 **분리**. 흠 있는 플라스틱 도마는 **세균** 논의 있음 → 주기 교체.
- **손·수세미**: 생선·닭 다룬 뒤 **비누**로 손. **행주**는 자주 끓이거나 교체.
- **상온**: **2시간 룰**(기온 높을수록 짧게)을 가정 룰로.
- **달걀**: **완전히 익히기**(특히 어린이·임산부 가정에서 보수적으로).
                """
            )
        with r6:
            st.markdown(
                """
##### 기본 비율(출발점)
- **초간장(무침·샐러드)**: 간장:식초:설탕·올리고당 ≈ **2:1:1**부터 시작해 취향 조절.
- **고추장 양념**: 고추장+다진 마늘+참기름+설탕/올리고당+**물·식초**로 농도.
- **간장 베이스 볶음**: 간장+설탕+마늘+참기름+후추 — **타지 않게** 불 조절.

##### 육수·국물
- **멸치**: 머리·내장 **적당히 제거**하면 비린내 감소. **다시마**는 끓기 직전·짧게(과다 우려면 끈적).
- **팔팔 끓인 뒤** 거품 걷기 → 맑은 국물.

##### 계량
- **종이컵·숟가락**으로 재는 법을 한 번 표준화해 두면 **엄마표 레시피** 복제가 쉬움.
- **오븐·에어프라이**는 기종별로 온도 편차 큼 → **레시피보다 5~10℃ 낮게** 시작해 보정.
                """
            )
        with r7:
            st.markdown(
                """
##### 검색·채널
- [만개의레시피](https://www.10000recipe.com/) — 검색량·후기 많은 **집밥**
- [네이버 요리·쿡쿡TV](https://tv.naver.com/) — 영상
- 유튜브: **백종원·쿡캐스트·1분요리** 등 — **화력·기종** 차이로 실패하면 **온도·시간만** 조정해 재시도

##### 저작·저장
- 블로그·책 레시피 **전문 복제**는 권리 문제가 될 수 있음. **본인 가정용 메모**로만 활용 권장.

##### 온도·시간(참고)
| 음식 | 중심 온도 감각 |
|------|----------------|
| 닭고기 | 중심 **75℃ 전후** 완전 익힘(가정에서는 절단 확인) |
| 돼지고기 | **회색·육즙 맑음**까지 |
| 소고기 스테이 | 취향에 따라 **희귀~웰던** (임신·어린이는 완숙 권장) |
| 계란 흰자 | 완고형 **응고** |
                """
            )
        st.info(
            "**알레르기** 표시 제품·**당·나트륨** 관리는 가정·의사와 상담하세요.",
            icon="💡",
        )
        _recipe_demo = [
            {"요리": "된장찌개", "핵심": "육수→뿌리 채소→된장 풀기→두부·호박→간"},
            {"요리": "김치찌개", "핵심": "익은 김치+국물+돼지/참치→설탕으로 산미·맵기 조절"},
            {"요리": "계란볶음밥", "핵심": "밥 수분 날림→재료→간장 마지막·불 세게"},
            {"요리": "간장 계란밥", "핵심": "밥 위에 계란·버터·간장·참기름·깨"},
            {"요리": "닭볶음탕", "핵심": "닭 데치기→감자 당근→고추장·양념 졸이기"},
            {"요리": "라면 업그레이드", "핵심": "물 적게·우유·치즈·파·계란 타이밍"},
            {"요리": "두부조림", "핵심": "키친타월 물 제거→간장 베이스 한소끔"},
            {"요리": "감자조림", "핵심": "감자 모서리·전분 가라앉힌 뒤 조리"},
        ]
        st.subheader("한 끼 레시피 뼈대(요약)")
        if pd is not None:
            st.dataframe(pd.DataFrame(_recipe_demo), use_container_width=True, hide_index=True)
        else:
            for row in _recipe_demo:
                st.markdown(f"**{row['요리']}** — {row['핵심']}")


def _render_page_tools_workshop() -> None:
    """공구·드릴·작업장 안전 — 비전문가 DIY 참고."""
    with _portal_page_card():
        st.header("🔧 공구 · 작업장 & 드릴")
        st.caption(
            "**취미·가정 수리** 위주입니다. 전기·배관·구조 보강은 **자격·법규**가 있을 수 있으니 전문가에게 맡기세요."
        )
        st.warning(
            "**보호구·집진·환기** 없이 목재·금속 가공은 사고·질병 위험이 큽니다. **사용 설명서**를 먼저 읽으세요.",
            icon="⚠️",
        )

        w1, w2, w3, w4 = st.tabs(["🔩 드릴·비트", "🪚 작업장·집진", "⚡ 안전·전기", "🔗 정보·브랜드"])
        with w1:
            st.markdown(
                """
##### 드릴 종류
- **드라이버(임팩트)**: 나사 조임·풀기. **토크 조절**이 있으면 목재·가구에 유리.
- **해머드릴·로터리**: **콘크리트·벽체** 천공 시. 집에서는 **배관·전선** 위치 확인(탐지기·도면) 후 작업.
- **전동드릴(클러치)**: 목재·금속 **소구경** 구멍. **속도·토크** 단계 조절.

##### 비트·날
- **십자(+)·일자(-)** 나사에 맞는 비트. **미끄럼** 줄이려면 압력을 축으로.
- **목재용 스파이럴 비트**: 입문용. **금속용 HSS·코발트**는 재질 표기 확인.
- **홀쏘**: 큰 구멍. **뒤집어서** 마무리하면 턱 덜 남는 경우가 많음.

##### 사용 습관
- **재료 고정**: 바이스·클램프로 **손가락이 회전부에서 멀게**.
- **선택 RPM**: 목재는 너무 빠르면 **그을음**, 금속은 **냉각·낮은 RPM**이 도움되는 경우 많음.
- **배터리**: 리튬 배터리 **고온·충전 직후** 보관 주의. **2차 전지** 분리 수거 규정 준수.
                """
            )
        with w2:
            st.markdown(
                """
##### 작업대
- **높이**: 팔꿈치 각도가 편한 높이가 장시간 작업에 유리. **다리 받침**으로 높이 보정.
- **조명**: 그림자 안 생기게 **측면+상면** 조명. **색온도** 맞추면 실색 판단 쉬움.
- **정리**: 공구는 **윤곽 그리기**(바닥 실루엣)로 제자리 습관.

##### 집진·환기
- **목재·MDF** 먼지는 **호흡기** 장시간 노출 시 건강 이슈. **집진기·흡입 마스크(KF94/FFP 등)** 병행.
- **금속 연마** 스파크는 **인화물** 멀리. **소화기** 근처에 두기.

##### 소음·이웃
- 아파트는 **시간대·진동** 규약 확인. **고무 매트**로 진동·소음 완화.
                """
            )
        with w3:
            st.markdown(
                """
##### 전기
- **연장선**: 정격 **전류(A)·길이**. 여러 고출력 공구 **동시 사용** 자제.
- **누전차단기(ELCB)** 동작 확인. **젖은 손**·젖은 바닥에서 전동공구 금지.
- **배터리 충전기**: 통풍·가연물 멀리. **야간 무인 충전**은 설명서 권장 범위 내.

##### 보호구
- **안전경**: 파편·먼지. **방진 마스크**는 작업 종류에 맞게.
- **청력**: 그라인더·로터리는 **귀마개** 권장.
- **장갑**: 회전 공구에 **장갑 끼고 만지면 위험**한 경우 있음 — 설명서 확인.

##### 응급
- **출혈**: 압박·거상. **깊은 상처**는 병원.
- **화상·스파크**: **물로 식히기** vs **기름 화재**는 다른 대응 — 소화기 **종류** 확인.
                """
            )
        with w4:
            st.markdown(
                """
##### 국내에서 정보 찾기
- **유튜브**: `DIY 목공`, `전동공구 리뷰` — **채널별 안전 수준**이 다름. 댓글에 **부작용**도 읽기.
- **대형마트·철물**: 비트·날 **규격**을 손에 잡고 비교.
- 브랜드 예시(선호에 따라): **보쉬·마끼다·디월트·히타치(하이코키)·미워키** 등 — **AS·배터리 호환**을 구매 전에 확인.

##### 책·커뮤니티
- **목공 입문서**는 **수공구→전동** 순으로 읽으면 이해가 빠름.
- **클리앙·네이버 카페** DIY — **사진·도면** 있는 글을 우선 참고.

---
**원칙**: 처음에는 **작은 폐목·저렴한 재료**로 연습하고, **만족할 때** 가구 본 작업에 들어가면 비용·스트레스가 줄어듭니다.
                """
            )


def _render_page_farming_hwaseong() -> None:
    """경기 화성시 기준 소규모 과수·채소·하우스 — 월별 참고(미세 기후·품종에 따라 조정)."""
    _hwaseong_monthly_md: dict[int, str] = {
        1: """
##### 1월 — 한겨울 · 휴면 & 저장
- **기후(화성권 감각)**: 서리·건조한 바람. **낮 기온**이 잠깐 올라도 이슬·결로로 병이 번질 수 있음.
- **사과**: 낙엽 정리, **동계 전정** 시작(가지 방향·내부 충실). 상처에는 **살균 도포** 습관. **설해** 대비 뿌리 부담 줄이기(퇴비 과다 피하기).
- **블루베리**: 휴면기. **화분·밭** 배수구 막힘 점검. **산도(pH)** 측정 계획(봄에 유황·피트믹스 보정).
- **감자·저장**: 저장 감자 **싹·쑥음** 건지기. 동결·습기 피해 확인.
- **고구마**: 저장고 **통풍·10~15℃ 부근** 유지 노력. 상한 것은 즉시 분리.
- **토마토**: 씨앗 주문·품종 결정(대과/방울, 착색). **육묘**는 남쪽 창가·LED 보조등으로 2월~초 파종 준비.
- **하우스(1동)**: **결로** 방지(환기 틈·바닥 습기). 난방 사용 시 **일산화탄소·화재**. 비닐·골조 **누수** 점검.
        """,
        2: """
##### 2월 — 입춘 전후 · 준비 본격화
- **사과**: 전정 마무리. **해충 방제**는 유인제·도장 시기 **품목별** 확인(지역 농업기술센터).
- **블루베리**: 기온 오르면 **관수** 시작. **가지치기**(너무 무성하면 열매 품질↓). **멀칭** 보충 계획.
- **감자**: **종薯 준비**·싹 띄우기(어두운 곳). **정식은 3월말~4월** 노지 기준(서리 주의).
- **고구마**: 육묘용 **고랑** 정비, 지력 보강. (모종은 보통 5월 전후 이식)
- **토마토**: **파종**(실내) 시작하는 분들 많음. **과습** 금지, **배수 좋은 상토**.
- **하우스**: **토양 소독**(태양열·유기농 허용 약제) 시즌. 침대분 정리.
        """,
        3: """
##### 3월 — 봄 기운 · 정식 준비
- **사과**: **화수가지** 정리, 꽃눈 확인. **병해** 예방 도장 1차(품목·등록약은 **농약 판매점·지도**).
- **블루베리**: **새순** 나오기 시작. **pH 4.5~5.5** 목표로 유황·피트 혼합(토양검사 뒤). **새 방지망** 수리.
- **감자**: **땅 얼음** 풀리면 **김·거름** 넣고 **정식**(두둑·행간). **이식 깊이** 일정하게.
- **고구마**: **육묘상** 비닐하우스·작은 하우스에서 **모종 키우기** 시작하는 경우 많음(온도 25℃ 전후 관리).
- **토마토**: **육묘** 커지면 **펜치**·**본박** 준비. **저온 스트레스**에 약한 품종은 이식 늦추기.
- **하우스**: **주간 환기** 늘리고 **야간 보온** 유지. **초기 병** 예방에 과습 금지.
        """,
        4: """
##### 4월 — 서리 주의 · 본격 영농
- **사과**: **화기**, **잎기** 전 **살균**. **꽃눈 냉해** — 이슬·바람 강한 날 **스모크·관수** 등 지역 기법 참고.
- **블루베리**: **개화 전** 병해 1차. **꽃가루 매개** 위해 벌·곤충 활동 관찰.
- **감자**: **김 매기기**·**북주기**. **감자역병** 예방: 침수 금지, **종薯** 건전하게.
- **고구마**: 모종 **육묘** 관리(잎 마름·과습). 노지 이식은 **5월 중순 이후**가 안전한 경우 많음.
- **토마토**: **상토 이식**·**대목** 사용 여부. **노지 정식**은 **최종 서리 끝난 뒤**(화성권 **4월 말~5월 초** 대략, 매년 예보 확인).
- **하우스**: **주간 온도** 급상승 — **측막·창문** 환기로 **30℃ 넘김** 방지. **진딧물** 발생 시 초기 차단.
        """,
        5: """
##### 5월 — 성장 가속 · 토마토·고구마
- **사과**: **적과 1차**(과밀 제거), **나방류** 유인·포획 시작. **물 관리**(가뭄·과습 모두 주의).
- **블루베리**: **초기 착색** 들어가는 품종은 **새·벌** 방어. **관수** 균일(과습은 뿌리 질병).
- **감자**: **꽃·줄기** 관찰. **조생종**은 **6월 초** 수확 가능. **병반** 나오면 잎 제거·약제.
- **고구마**: **모종 이식**(노지). **이식 직후** 건조·바람에 말라 죽지 않게 **관수**. **마운드** 형성.
- **토마토**: **지주·유인**, **아랫잎** 제거로 통풍. **흑반병** 예방: 잎 물 안 뭍히기, **과습 금지**.
- **하우스**: 토마토·기타 **채소 풀타임** — **일출 전 환기**로 이슬 말리기.
        """,
        6: """
##### 6월 — 장마 전후 · 블루베리·감자
- **사과**: **여름 전정**(생육 과다 가지), **병해** 살포 주기. **가지 끝** 햇빛 들게.
- **블루베리**: **본수확**. **아침 일찍** 따면 신선도↑. **수확 후** 냉장·판매·가공 계획.
- **감자**: **감자 덩이리균병**·**역병** 주의 — **침수 절대 금지**. **잎 마름** 후 **7~10일** 뒤 캐기도 방법.
- **고구마**: **순 정리**(너무 무성하면 지하 덩이로 양분). **덩굴** 방향 유인.
- **토마토**: **첫 수확**. **일괄 착색** 위해 **하엽** 정리. **칼슘 결핍**(끝부 패임)이면 **엽면시비** 검토.
- **하우스**: **장마** 전 **배수로**·**비닐 위 물 고임** 점검. **습도** 높으면 **곰팡이성 병** 폭발.
        """,
        7: """
##### 7월 — 무더위 · 병충해 최성기
- **사과**: **여름병**·**진딧물**·**응애** 모니터링. **살포**는 **이슬 말린 뒤**·**저녁** 위주(약제 지침).
- **블루베리**: 후기 품종 **수확**. **가지치기** 계획(너무 무거운 가지 줄이기).
- **감자**: **캐기** 본격(품종별). **그늘 건조** 후 저장.
- **고구마**: **덩이 비대기** — **건조·일조** 중요. **가뭄** 시 깊이 관수.
- **토마토**: **고온**에서 **과실 부작**·**줄기 멈춤** — **그늘막**·**미스트**(과습 주의). **물은 아침**.
- **하우스**: **환기·차광막**·**양액**(채택 시) EC 관리. **열사병** 작업자 주의.
        """,
        8: """
##### 8월 — 폭염 · 토마토·고구마 관건
- **사과**: **가지** 햇빛 들게 유지. **낙과**·**병과** 제거. **가을 전정** 준비.
- **블루베리**: 수확 마무리. **휴식기** 들어가기 전 **관수** 리듬 조절.
- **감자**: 대부분 수확 끝. **밭** 휴식·녹비 작물 파종 검토.
- **고구마**: **덩이 비대** 최종 구간. **덩굴** 지나치면 **잘라** 양분 아래로.
- **토마토**: **고온 장해** — **방울토마토**는 비교적 강하나 **대과**는 **떨어짐** 많음. **적과**·**그늘**.
- **하우스**: **태풍** 대비 **비닐·밴드** 점검. **야간 환기**로 온도 낮추기.
        """,
        9: """
##### 9월 — 가을 준비 · 사과·고구마
- **사과**: **수확 시기**(품종·당도·색). **종이봉지** 쓰는 경우 **안쪽 습기** 확인. **낙과** 방지 병해.
- **블루베리**: **가을 전정**(과도하게 무성한 것만). **유기질** 멀칭 추가(겨울 뿌리 보호).
- **감자**: 저장지 **소독**·**통풍**. 다음 해 **작물 순환** 계획.
- **고구마**: **캐기** 시작(서리 전 **덩이 비대** 확인). **상처 난 것**은 먼저 소비.
- **토마토**: **말기** — **청경**·**잼**·**건조** 활용. **병 잎** 제거 후 **퇴비화**.
- **하우스**: **가을 작물**(상추·시금치 등) 전환 준비. **야간 기온** 낮아지면 **보온** 준비.
        """,
        10: """
##### 10월 — 수확 · 저장 & 낙엽기
- **사과**: **본수확**. **저장**은 **통풍·낮은 습도**·품종별. **상처 과일**은 먼저.
- **블루베리**: **낙엽** 정리(병원균 줄이기). **멀칭** 두껍게(동해). **새 가지** 색 진하게 전까지 기다리기.
- **감자**: 저장 중 **싹**·**쑥음** 점검. 다음 해 **두둑** 위치 바꾸기.
- **고구마**: **수확 완료** 목표(중상순 이전). **햇빛·바람**에 **후숙** 후 저장 맛↑.
- **토마토**: **끝물** 수확·덩군 제거. **토양** 태양열·유기물로 회복.
- **하우스**: **비닐·골조** 보수. **겨울작물** 파종(상추·시금치 등).
        """,
        11: """
##### 11월 — 월동 준비
- **사과**: **낙엽** 청소·소각(병원균). **겨울 살포** 일정(지역 병해에 따라). **설주** 보호.
- **블루베리**: **수분** 적당히(가뭄 시). **토양** 덮기(멀칭). **새** 그물 정비.
- **감자**: 저장고 **온도** 낮추기(빛 차단). **종薯** 확보.
- **고구마**: 저장 **온도 12~15℃** 부근 목표. **상한 것** 제거.
- **토마토**: 시설 내 **마지막** 수확·정리. **토양 개량** 자재 준비.
- **하우스**: **보온재**·**이중 비닐**·**난방** 점검. **결로** 심한 구간 **환기 설계** 재검토.
        """,
        12: """
##### 12월 — 정리 · 내년 설계
- **사과**: **동계 전정**·**해충 유인목** 설치. **도장** 계획(날씨 창).
- **블루베리**: **휴면** 깊어짐. **토양 검정** 의뢰·**시비 설계**.
- **감자**: 내년 **품종·면적** 결정. **종薯** 발주.
- **고구마**: 저장 상태 점검. **육묘** 시설 청소.
- **토마토**: **씨앗**·**품종** 리스트. **육묘 시설** 소독.
- **하우스**: **1년 치 기록**(온도·병해·수확량) 정리 — 내년 개선점 도출.
        """,
    }
    _hwaseong_overview_rows = [
        {"월": "1월", "사과": "동계 전정·설해", "블루베리": "휴면·산도계획", "감자": "저장 점검", "고구마": "저장", "토마토": "씨 주문", "하우스": "결로·난방"},
        {"월": "2월", "사과": "전정 마무리", "블루베리": "가지·멀칭", "감자": "싹띄우기", "고구마": "육묘 준비", "토마토": "파종 시작", "하우스": "토양 소독"},
        {"월": "3월", "사과": "화수·병 예방", "블루베리": "pH·새망", "감자": "정식 준비", "고구마": "육묘", "토마토": "육묘", "하우스": "환기·병방제"},
        {"월": "4월", "사과": "냉해·살균", "블루베리": "개화 전", "감자": "정식", "고구마": "모종", "토마토": "노지 정식", "하우스": "고온 방지"},
        {"월": "5월", "사과": "적과·방제", "블루베리": "수확 초", "감자": "김·역병", "고구마": "노지 이식", "토마토": "유인·흑반", "하우스": "본격 재배"},
        {"월": "6월", "사과": "여름 전정", "블루베리": "본수확", "감자": "수확·병", "고구마": "순 관리", "토마토": "첫 수확", "하우스": "장마 배수"},
        {"월": "7월", "사과": "병충해", "블루베리": "후기 수확", "감자": "캐기", "고구마": "비대기", "토마토": "고온 대책", "하우스": "환기·열"},
        {"월": "8월", "사과": "낙과·가지", "블루베리": "휴식 전", "감자": "정리", "고구마": "덩이 비대", "토마토": "적과", "하우스": "태풍 대비"},
        {"월": "9월", "사과": "수확", "블루베리": "가을 전정", "감자": "저장", "고구마": "캐기", "토마토": "말기", "하우스": "가을 작물"},
        {"월": "10월", "사과": "저장", "블루베리": "낙엽·멀칭", "감자": "순환", "고구마": "후숙", "토마토": "정리", "하우스": "보온 준비"},
        {"월": "11월", "사과": "낙엽·월동", "블루베리": "월동 물", "감자": "종薯", "고구마": "저장", "토마토": "끝", "하우스": "보온 강화"},
        {"월": "12월", "사과": "전정·유인", "블루베리": "휴면·검정", "감자": "발주", "고구마": "점검", "토마토": "계획", "하우스": "기록 정리"},
    ]

    with _portal_page_card():
        st.header("🌱 농사 · 화성시 텃밭")
        st.caption(
            "**경기도 화성시** 소재 기준 **참고용**입니다. 인근(수원·오산·평택)과 **미세 기후**(남향·물가·도시열)에 따라 "
            "**1~2주 차이**가 날 수 있습니다. **품종·시설**에 맞게 조정하세요."
        )
        st.info(
            "재배 작물: **사과·블루베리·감자·고구마·토마토** + **비닐하우스 1동**. "
            "**농약·비료**는 등록·지침을 따르고, **농업기술센터** 상담을 권장합니다.",
            icon="💡",
        )

        a1, a2, a3 = st.tabs(["📅 월별 달력 & 상세", "🌳 작물별 연간", "🏠 하우스 1동"])
        with a1:
            st.subheader("연간 한눈표 (키워드)")
            if pd is not None:
                st.dataframe(pd.DataFrame(_hwaseong_overview_rows), use_container_width=True, hide_index=True)
            else:
                st.table(_hwaseong_overview_rows)

            st.divider()
            _mon_labels = [f"{m}월" for m in range(1, 13)]
            _pick = st.selectbox(
                "월을 고르면 아래에 **그달 할 일**이 펼쳐집니다.",
                options=list(range(1, 13)),
                format_func=lambda i: _mon_labels[i - 1],
                key="hwaseong_farm_month_pick",
            )
            st.markdown(_hwaseong_monthly_md.get(_pick, ""))

        with a2:
            st.markdown(
                """
##### 사과 (낙엽 수목)
- **전정**: 겨울(형태·햇빛·통풍), 여름(생육 조절). **상처**는 살균 처리.
- **적과·피복**: 과밀하면 크기·당도↓. **봉지**는 품종·목적에 따라.
- **병해**: 검은별무늬병·붕괴병 등 — **예방 살포** 시기가 핵심(지역 달력).
- **수확**: 품종별 **당도·색**. 저장은 **통풍·저온**.

##### 블루베리 (산성 토양)
- **pH 4.5~5.5** 유지(피트·유황). **배수** 필수(뿌리 무산소 싫어함).
- **가지치기**: 겨울~초봄, 너무 무성하면 열매 품질↓.
- **새**: 그물·충격음. **수확**은 아침이 신선.
- **품종**: 남고·북고·반고에 따라 **수확 월**이 갈림.

##### 감자 (덩이줄기)
- **종薯**: 건전한 것, **싹** 균일하게. **역병**은 침수·종薯가 핵심.
- **김 매기기**·**북주기**: 덩이 햇빛 막고 품질 유지.
- **수확**: 잎 마름 후 **껍질 굳기** 기간 두면 저장성↑.

##### 고구마 (덩이뿌리)
- **육묘**→**이식**(따뜻해진 뒤). **순** 너무 무성하면 **덩이**로 양분 이동.
- **수확**: **서리 전**, 덩이 **후숙**(맛·저장).
- **저장**: 12~15℃·통풍. **상처** 최소화해 캐기.

##### 토마토 (온대 채소)
- **육묘** 2~3월, **정식** 서리 지난 뒤. **무한성장형**은 유인·순치기.
- **흑반병·역병**: 과습·잎 물 금지. **칼슘** 결핍(끝부 패임) 주의.
- **고온**: **주와·그늘막**. **저온**: **과실 부작**.

---
**화성시**: [화성시청](https://www.hs.go.kr/) 에서 **농업·축산**·**농업기술센터** 메뉴를 검색해 최신 **교육·상담** 일정을 확인하세요.
                """
            )
        with a3:
            st.markdown(
                """
##### 비닐하우스 1동 운영 체크리스트
- **환기**: 낮 **과열**(30℃+) 방지가 여름 최우선. **측창·천창** 규칙적으로.
- **결로**: 잎·과실에 물방울 → **병**. **환기**로 이슬 말리기, **방제**와 병행.
- **겨울**: **이중 비닐**·**스크린**·**난방** 비용 vs 작물 가치. **일산화탄소**·**화재** 센서 권장.
- **토양**: 연중 재배 시 **염류·병원균** 축적 — **휴지기 태양열 소독**·**유기물** 투입·**작물 로테이션**.
- **양액**(사용 시): **EC·pH** 매일 기록. **누출**·**펌프** 점검.
- **태풍**: **밴드**·**앵커**·**비닐** 찢김 대비. 작업 중 **안전**.

##### 공간이 한 동뿐일 때
- **우선순위**를 정해 **토마토·채소** vs **육묘**를 분리(병 옮김). 가능하면 **구역** 나누기.
                """
            )
            st.caption("하우스 내 **온도 로그**(최저·최고)를 월별로 메모해 두면 내년 개선에 큰 도움이 됩니다.")


def _render_page_auction() -> None:
    """부동산·동산 경매 입문 — 땅·공장·아파트 등 유형별로 흐름·체크 포인트 정리(참고용, 법률 자문 아님)."""
    with _portal_page_card():
        st.header("⚖️ 경매 · 입찰 가이드")
        st.caption(
            "**법원 경매·공매·민간 경매** 등 절차·용어가 다릅니다. 아래는 **시작하기 쉬운 흐름** 위주이며, "
            "**낙찰 전·후** 반드시 **등기·현장·전문가**로 확인하세요. (법률·투자 조언이 아닙니다.)"
        )
        st.warning(
            "경매 물건은 **하자·권리관계·인도 지연** 리스크가 큽니다. **보증금·잔금** 일정을 어기면 **몰수** 등 불이익이 생길 수 있습니다.",
            icon="⚠️",
        )

        t0, t1, t2, t3, t4, t5 = st.tabs(
            [
                "시작하기",
                "토지·땅",
                "공장·창고",
                "아파트·집합",
                "공매·기타",
                "체크리스트",
            ]
        )

        with t0:
            st.markdown(
                """
##### 왜 단위가 나뉘나
- **토지**: 용도·고도·도로·분할 가능성이 핵심.
- **공장·상가**: **건축·소방·환경**·**설비 노후**·**영업 적합성**이 핵심.
- **아파트**: **지분·관리비·대항력 있는 임차인**·**재건축** 가능성 등 **집합건물** 이슈가 핵심.

##### 법원 경매(대략적 흐름)
1. **사건 검색** → 물건 **명세·현황** PDF, **감정평가서**, **기일** 확인  
2. **현장 답사**(가능하면 여러 번) — 점유·주변 시세·소음·진입로  
3. **권리분석**(말소 기준권리·선순위·임대차) — **등기부·매각물건명세서**  
4. **입찰** — **보증금** 준비, **전자입찰** 절차 숙지  
5. **낙찰** → **잔금** → **등기 이전** → **인도**(별도 소송·협의 가능성 염두)

##### 자주 쓰는 용어
| 용어 | 뜻(요약) |
|------|----------|
| **최저매각가격** | 그 금액 미만 입찰은 무효인 경우가 많음 |
| **매각기일** | 입찰하는 날(시간 엄수) |
| **말소 기준 권리** | 매각으로 소멸·인수 여부가 갈리는 기준 |
| **대항력** | 확정일자 등으로 보호받는 임차인 등 |
| **별도 등기** | 낙찰자가 인수해야 할 권리(예: 지상권) |

##### 정보는 어디서
- **법원**: [대법원 경매정보](https://www.courtauction.go.kr/) — 사건·물건·일정  
- **공매**: [온비드](https://www.onbid.co.kr/) 등 **기관·지자체**별 공고  
- **실거래가**: 국토부 **실거래가 공개** 등으로 **주변 시세** 감 잡기  
                """
            )

        with t1:
            st.markdown(
                """
##### 토지·땅 경매에서 볼 것
- **지목·용도지역** — 건축 가능 여부, **고도·건폐율·용적률**  
- **도로 접도** — 맹지 여부, 진입로 확보  
- **도시계획** — 개발제한구역, 도로계획, 분할 제한  
- **실측·경계** — 표시와 실제 다를 수 있음, **인접 필지** 분쟁  
- **토지거래허가구역** — 취득 절차·자격  
- **농지·산지** — 취득·전용·경작 의무 등 별도 규제  

##### 답사 팁
- **위성지도 + 현장** — 경사·접도·주변 용도  
- **상하수도·전기** 인입 거리·비용은 **별도 견적** 염두  

##### 리스크
- **지상물·무허가 건물** — 인도·철거 비용  
- **분묘·수목** — 관련 비용·협의  
                """
            )

        with t2:
            st.markdown(
                """
##### 공장·창고·근린상가 유형
- **건축물 대장** — 용도·층수·면적·위반 건축물 여부  
- **소방·전기·위험물** — 업종 바꿀 때 **시설 기준** 달라질 수 있음  
- **환경**(악취·소음·배출) — 주변 민원·규제  
- **설비** — 크레인·압축기·냉동 등 **잔존·철거 비용**  
- **임대차** — **대항력 있는 세입자**·**보증금** 인수 여부  

##### 공장 매입 후
- **사업자 등록·업종**과 **시설 기준** 맞추기  
- **전력 용량** — 증설 비용·기간  
- **하역·진입로** — 대형 차량 출입  

##### 상가·점포
- **유동인구·상권** — 공실률, 경쟁 점포  
- **권리금** 별도 협상인지, **공매 비고** 확인  
                """
            )

        with t3:
            st.markdown(
                """
##### 아파트·오피스텔·집합건물
- **전유부·대지권** — 면적·지분 비율  
- **관리비·미납** — **인수**되는지 명세 확인  
- **점유** — **대항력 있는 임차인**·**전세** 등 **인도 지연** 가능성  
- **재건축·재개발** — 조합·사업성·추가 분담  
- **주차·저당** — 배정·별도 권리 여부  

##### 입찰 전
- **같은 단지 최근 낙찰가율**·**실거래가** 비교  
- **하자·누수** — 현장·입주민 커뮤니티는 참고만(확정 판단 X)  

##### 세대 내부
- **인도 시점**에 **원상회복·집기** 문제 — 명세·사진으로 가늠  
                """
            )

        with t4:
            st.markdown(
                """
##### 공매(온비드 등)
- **기관별** 규칙·**입찰 자격**·**대금 납부** 방식이 **법원과 다름**  
- **국·공유재산** — 사용허가·목적 외 사용 제한  
- **지방재정·공기업** — **유찰** 시 **가격·조건** 변동 있음  

##### 민간·온라인 경매
- **물건 설명·책임** 한도가 **다름** — 약관·유의사항 필독  
- **위탁 경매** — 원소유자·채권 관계 확인  

##### 동산·기계
- **현장 시운전**·**등록**(차량)·**반출 비용**  
- **유치권·압류** 말소 여부  

##### 세금·비용(개략)
- **취득세·등록면허세** 등 — **낙찰일·기준**은 세법·지침 따름(확인 필수)  
- **중개·법무사·등기** 비용 별도  
                """
            )

        with t5:
            st.markdown(
                """
##### 입찰 전 체크 (O / X 메모용)
- [ ] **등기부등본**·**매각물건명세서**·**감정평가서** 읽음  
- [ ] **현장** 방문(낮·저녁·주말 각각 가능하면)  
- [ ] **선순위 권리**·**말소/인수** 구분 이해  
- [ ] **임차인·점유** — 명세표·전입·확정일자 등 **비교**  
- [ ] **자금** — 보증금·잔금 일정·**대출 가능 여부**(경매는 은행 심사 까다로운 편)  
- [ ] **인도·명도** — 소송·기간·비용 **시나리오**  
- [ ] **세금·취득 후 비용** 러프 산출  

##### 낙찰 후
- [ ] **잔금일** 절대 놓치지 않기  
- [ ] **등기** — 법무사 일정  
- [ ] **명도** — 협의·법적 절차·**추가 비용**  

---
**기록**: 물건 번호·사건번호·열람 일시·질문한 전문가 답변을 **한 곳에** 남기면 다음 입찰에 재사용하기 좋습니다.
                """
            )

        st.divider()
        st.caption("최신 절차·요건은 **대법원 경매정보**, **온비드** 등 공식 공지를 우선 확인하세요.")


def _render_page_health() -> None:
    """고혈압·당뇨·성인병 — 생활·주의 참고(의료 행위·진단 대체 아님)."""
    with _portal_page_card():
        st.header("❤️ 건강 · 생활 관리")
        st.caption(
            "아래는 **일반적인 건강정보·생활 습관** 정리입니다. **증상·약 조절·목표 수치**는 사람마다 다르므로 "
            "**의사·약사**와 상담하세요. 이 페이지는 **진단·치료를 대신하지 않습니다.**"
        )
        st.info(
            "**응급**: 가슴 통증·호흡곤란·한쪽 팔다리 마비·말 어눌·심한 저혈당 의심 시 **119** 또는 응급실.",
            icon="🚨",
        )

        h1, h2, h3, h4 = st.tabs(["고혈압", "당뇨", "성인병·대사", "검진·기록"])

        with h1:
            st.markdown(
                """
##### 고혈압 환자가 특히 주의할 점
- **염분(소금)** — 가공식품·국물·젓갈·라면·패스트푸드에 **숨은 나트륨**이 많습니다. **영양표시**를 습관화하세요.  
- **음주** — 혈압을 끌어올리고 약 효과를 흐립니다. 권장량·금주는 **담당 의사**와 결정.  
- **금연** — 담배는 혈관을 해치고 뇌·심장 위험을 키웁니다.  
- **혈압 측정** — 같은 시간대·안정 후 **2~3회** 평균에 가깝게 기록. **팔 높이·커프 크기** 맞는지 확인.  
- **약 복용** — 혈압이 좋아졌다고 **임의 중단**하면 반동·위험이 커질 수 있습니다. 조절은 **전문가**와.  
- **감기약·염증 진통제(NSAIDs)** 일부는 **혈압·신장**에 부담이 될 수 있어, **복용 중인 약**을 알리고 상담.  
- **추위·스트레스·코골이(수면무호흡 의심)** — 혈압 변동·밤샘 악화 요인.  
- **운동** — 규칙적인 **유산소**(걷기 등)와 의사가 허용한 **근력**은 도움이 되는 경우가 많으나, **수축기 180 이상** 등 통제 안 될 때는 먼저 진료.  
- **카페인** — 개인차가 큼. 혈압 들쭉날쭉하면 **줄이고** 반응을 관찰.

##### 목표와 동반질환
- 당뇨·신장질환·심장질환이 있으면 **혈압 목표**가 더 빡빡할 수 있습니다. **본인 기준**은 진료에서 확인하세요.

---
**참고**: [질병관리청 건강정보](https://www.kdca.go.kr/) · [국민건강보험 건강정보](https://www.nhis.or.kr/) 에서 **생활습관** 자료를 볼 수 있습니다.
                """
            )

        with h2:
            st.markdown(
                """
##### 당뇨병(특히 제2형)에서 중요한 것
- **혈당 관리** — 공복·식후 목표는 **개인별**. **HbA1c(당화혈색소)** 는 2~3개월 평균을 봅니다.  
- **식이** — **탄수화물 총량·종류**(정제 탄수·당 음료 과다 주의), **채소·단백질** 배치. **혼자 극단적 금식**은 저혈당 위험.  
- **운동** — 규칙적 활동은 **인슐린 저항** 개선에 도움이 되는 경우가 많습니다. **인슐린·혈당강하제** 복용 시 **저혈당** 대비(간식·규칙).  
- **발 관리** — 감각 저하·상처는 **감염·괴사**로 이어질 수 있어 **맨발 금지·신발 확인·상처 조기 치료**.  
- **눈·신장** — 망막·신기능 검사는 **합병증 조기 발견**에 중요합니다.  
- **혈압·지질** — 당뇨는 **심혈관 위험**이 함께 올라가기 쉬워 **염분·금연·혈압·콜레스테롤**도 같이 봅니다.  
- **저혈당 신호** — 식은땀·손떨림·공복감·어지러움 시 **당을 소량** 섭취(의료진이 안내한 대응) 후 혈당 재측정·필요 시 도움 요청.

##### 인슐린·경구약
- **용량·시간** 임의 변경 금지. **감염·수술·식이 변화** 시 혈당이 흔들리기 쉬우니 **연락 가능한 의료진** 염두.

---
**참고**: 당뇨 교육은 **당뇨교육실**·**가정의학과·내분비내과**에서 프로그램을 안내하는 경우가 많습니다.
                """
            )

        with h3:
            st.markdown(
                """
##### 성인병(만성질환)과 대사
- **대사증후군** — 복부비만·고혈압·고혈당·고중성지방·낮은 HDL 등이 **겹치면** 심혈관 위험이 커집니다.  
- **이상지질혈증** — **LDL·중성지방**은 식이·운동·필요 시 약으로 관리. 검사는 **주기적으로**.  
- **비알코올성 지방간** — 체중·당·지질 관리가 중심. **과음**도 지방간에 가세합니다.  
- **골다공증·퇴행성 관절염** — 나이 들며 흔해지므로 **낙상 예방**·적절한 **운동·칼슘·비타민D**는 진료와 상의.  
- **수면·정신건강** — 만성 스트레스·불면은 **혈압·혈당·식욕**을 흔듭니다.

##### 생활 습관 공통
- **체중**: 서서히 감량(급격한 요요는 유지 어려움).  
- **가공육·튀김·가당 음료** 줄이기.  
- **좌식** 줄이고 **하루 총 활동량** 늘리기.

---
이 탭 내용은 **예방·자가 점검**용 개요이며, **약물·목표 수치**는 반드시 **개인 진료**로 확정하세요.
                """
            )

        with h4:
            st.markdown(
                """
##### 정기 검진(한국에서 흔한 틀)
- **국가건강검진** 대상·주기는 **나이·공단 안내**에 따릅니다. **혈압·공복혈당·지질·신장** 등 기본 항목을 챙기세요.  
- **생애전환기** — 중년 이후 **암 검진**·**골밀도** 등 권장 항목이 늘어납니다.  
- **가족력** — 조기 심혈관·당뇨 가족력이 있으면 **더 일찍·촘촘히** 논의할 가치가 있습니다.

##### 집에서 기록하면 좋은 것
- **혈압**: 날짜·시간·수치·특이사항(음주·잠 부족 등).  
- **혈당**: 측정기 사용 시 **식전·식후** 규칙을 정해 두고(의사와) 기록.  
- **체중·허리둘레**: 월 1회라도 추세 파악에 도움.

---
**응급 징후**(다시 한 번): 턱·팔·등으로 퍼지는 가슴 통증, 숨참, 갑작스런 한쪽 약함, 말이 어눌해짐, 의식 저하 → **즉시 119**.
                """
            )

        st.divider()
        st.caption("증상이 있거나 약을 복용 중이면 **이 앱의 문구로 조절하지 말고** 의료기관을 이용하세요.")


def _render_page_diet() -> None:
    """체중·비만 관리 — 식이·운동·의약품 개요(처방·진단 대체 아님)."""
    with _portal_page_card():
        st.header("🥗 다이어트 · 체중 관리")
        st.caption(
            "**식이·운동·약·수술** 선택은 사람마다 다릅니다. 아래는 **참고용 정리**이며, "
            "**비만 치료제는 반드시 의사 처방·감독** 하에 사용하는 것이 원칙입니다. "
            "**이 페이지는 처방·용량·구매를 안내하지 않습니다.**"
        )
        st.warning(
            "**자가 구매·공동구매·해외 직구 의약품**은 위약·부작용·법적 문제 위험이 큽니다. "
            "**정식 진료**를 받으세요.",
            icon="⚠️",
        )

        d1, d2, d3, d4, d5 = st.tabs(
            ["시작하기", "운동·활동", "주사제·GLP-1 계열", "기타 약·수술", "부작용·주의"]
        )

        with d1:
            st.markdown(
                """
##### 목표 세우기
- **체중**만이 아니라 **허리둘레·혈압·혈당·지질·근력** 등 **건강 지표**를 함께 보는 편이 안전합니다.  
- **급격한 굶주림** 다이어트는 **요요·근손실·담석** 등 위험이 있어, **지속 가능한 속도**를 의료진과 논의하세요.

##### 식이(생활)
- **총 칼로리**와 **영양 균형**(단백질·채소·통곡물) — 극단적 **탄수 절단**은 당뇨·약 복용자에게 특히 위험할 수 있습니다.  
- **가당 음료·알코올·가공 간식** 줄이기 — 체감 칼로리 감소에 효과적인 경우가 많습니다.  
- **기록** — 며칠간 식사·간식을 적으면 **패턴**이 보입니다(앱·수첩 무관).

##### 언제 약·병원을 고려하나
- **BMI·동반질환(당뇨·고혈압·수면무호흡 등)** 에 따라 **비만 의학적 치료** 권고 여부가 달라집니다. **본인 기준**은 진료에서만 확정됩니다.

---
**참고**: [질병관리청 비만](https://www.kdca.go.kr/) · [식약처 안전정보](https://www.mfds.go.kr/) — **공식 가이드**를 우선하세요.
                """
            )

        with d2:
            st.markdown(
                """
##### 운동의 역할
- **유산소**(걷기·자전거·수영 등) — 심폐·에너지 소모. 무릎 부담이 적은 종목부터 **시간을 늘리기**.  
- **근력 운동** — 근육량 유지가 **기초대사·요요 방지**에 도움이 됩니다. **올바른 자세**가 우선.  
- **NEAT**(비운동성 활동) — 계단·집안 일·산책으로 **앉아 있는 시간** 줄이기.

##### 시작할 때
- 오래 운동하지 않았다면 **짧게·자주** — 통증·호흡곤란 시 **중단**하고 진료.  
- **스트레칭·준비운동** — 하체·허리 보호.  
- **수분** 보충, 더운 날 **온열질환** 주의.

##### 약 병행 시
- **혈당강하제·인슐린** 복용 중 **공복 운동**은 저혈당 위험 — **의사·약사**와 운동 계획 공유.

---
운동 종목·강도는 **개인 체력·관절**에 맞게 조절하세요.
                """
            )

        with d3:
            st.markdown(
                """
##### 왜 요즘 이야기가 많은지
- **장에서 포만감·혈당 조절**에 관여하는 호르몬을 닮은 약(주로 **주사**)이 등장하면서, **생활습관 교정**과 병행할 때 체중 감소에 도움이 되는 경우가 **임상에서** 보고되고 있습니다.  
- **모두에게 맞지 않으며**, **부작용·금기·비용**이 있어 **전문의 평가**가 필요합니다.

##### 성분·제품 구분(이름만 정리 — 적응증은 제품·국가별 상이)
| 흔한 명칭 | 성분(계열) | 비고(개략) |
|-----------|------------|------------|
| **삭센다(Saxenda)** | 리라글루타이드(GLP-1 유사) | 비만 치료 **전용 표시**가 있는 제품(국가별 상이). **당뇨용 제품과 용량·목적이 다름** |
| **위고비(Wegovy)** | 세마글루타이드 | 비만 적응 **주사** |
| **오젬픽(Ozempic)** | 세마글루타이드 | 원래 **당뇨 치료** 표시; 일부 지역에서 비만에 쓰이기도 하나 **표시·처방 관행은 국가·지침** 따름 |
| **마운자로·젭바운드** 등 | 티르제파타이드(GLP-1+GIP) | 당뇨·비만 **표시가 제품별로 다름** |

##### 공통적으로 알아둘 점
- **점진적 용량 조절**(titrate) 등 **지침**이 있어 **임의로 바꾸면 안 됩니다**.  
- **구토·설사·복통** 등 **위장 부작용**이 흔히 보고됩니다 — 심하면 **중단·진료**.  
- **갑상선 수종·가족력**, **췌장염 병력** 등 **금기·주의**가 있을 수 있습니다.  
- **임신·수유** — 대부분 사용 피해야 합니다(제품별).  

---
**다시 한 번**: 표의 브랜드명은 **설명용**이며, **구입·복용 결정은 의사만** 하세요.
                """
            )

        with d4:
            st.markdown(
                """
##### 경구제(예시)
- **오를리스타트(Orlistat)** — 지방 흡수 억제. **지방성 설사·흡수** 등 주의, **저지방 식이**와 병행 논의.  
- 과거 **식욕억제 경구제**류는 **심혈관·정신건강** 이슈로 **엄격한 적응**이 있을 수 있어, **현재 한국에서 쓰이는지·본인에게 맞는지**는 반드시 **진료**에서 확인.

##### 수술적 치료
- **비만 수술**(위 절제술·우회술 등)은 **중증 비만·동반질환** 등 기준을 만족할 때 검토. **영양 결핍·복합 비타민** 평생 관리가 필요한 경우가 많습니다.

##### 생활 요법이 먼저
- 약·수술은 **식이·운동·행동 치료**와 **병행**되는 경우가 많고, **단독 만능**이 아닙니다.

---
**의약품 승인·표시**는 시기마다 바뀝니다. **식약처 허가·첨단의료** 공지를 확인하세요.
                """
            )

        with d5:
            st.markdown(
                """
##### 흔한 부작용·신호
- **소화기**: 오심, 구토, 설사, 변비 — 초기에 많고 **시간이 지나며** 나아지는 경우도 있으나 **개인차** 큼.  
- **저혈당** — **당뇨약·인슐린**과 병용 시 특히 주의. **식은땀·어지러움** 시 대응법은 **진료에서** 교육.  
- **담낭·췌장** — **복통이 심하거나 등으로 퍼짐** → **응급** 고려.  
- **탈수** — 구토·설사 시 **수분·전해질**.

##### 약물·병행
- **다른 GLP-1 제제**와 **중복 사용** 금지.  
- **위장관 약·일부 항생제** 등 **상호작용** — 처방 시 **복용 목록**을 모두 알리기.

##### 법·안전
- **타인 처방전**·**불법 유통**은 처벌 대상이 될 수 있습니다.  
- **SNS·공구** 약은 **성분·보관** 불명으로 위험합니다.

---
**응급**: 호흡곤란, 의식 이상, 심한 복통 → **119** 또는 응급실.
                """
            )

        st.divider()
        st.caption(
            "체중 감량 목표·약물 선택은 **내분비내과·가정의학과·비만 클리닉** 등에서 **개인별**로 결정하세요."
        )


def _render_page_restaurants() -> None:
    """지역별 맛집 탐색 가이드 — 실시간 영업·가격은 앱에서 확인."""
    with _portal_page_card():
        st.header("🍽️ 맛집·식당 정보 탐색")
        st.caption(
            "이 페이지는 **특정 가게를 추천·비방하지 않습니다.** "
            "**서울·경기·지방**으로 나누어 **찾는 방법·지역 특성**만 정리했습니다."
        )
        s1, s2, s3, s4 = st.tabs(["서울", "경기·인천", "광역·지방 도시", "전국 공통 팁"])
        with s1:
            st.markdown(
                """
##### 서울에서 찾을 때
- **밀집**: 강남·홍대·명동·종로·성수 등 **역세권**은 웨이팅·가격대가 높은 편입니다. **점심·평일**이 상대적으로 수월한 경우가 많습니다.
- **골목**: 지도 **스트리트뷰·최근 리뷰 사진**으로 메뉴 변화를 확인. **현금·카드** 표기도 체크.
- **주차**: **발렛·주차장 유무**를 먼저 보고 방문하면 스트레스가 줄어듭니다.
                """
            )
            st.markdown("- [네이버 지도 — 서울](https://map.naver.com/p/search/%EC%84%9C%EC%9A%B8%20%EB%A7%9B%EC%A7%91)")
        with s2:
            st.markdown(
                """
##### 경기·인천
- **신도시·대형몰 주변**은 체인·브랜드가 많고, **구시가지·항구(인천)** 는 향토 음식·해산물 축이 섞입니다.
- **출퇴근 반경**: 집·직장 기준 **지도 저장**을 만들어 두면 주말 외식 선택이 빨라집니다.
- **주차 넓은 곳**: 가족 단위로 **브런치·한정식** 찾을 때 유리한 경우가 많습니다.
                """
            )
            st.markdown("- [네이버 지도 — 경기 맛집 검색](https://map.naver.com/)")
        with s3:
            st.markdown(
                """
##### 부산·대구·광주·대전 등
- **항구·시장**(부산 자갈치 등): **회·밀면** 를 찾는 흐름이 흔합니다. **시세·위생**은 현장·리뷰 최신글을 보세요.
- **내륙**: **한우·닭·쌀국수** 지역 특색이 갈립니다. **현지 블로그보다 최근 3개월 리뷰**를 우선하세요.
- **관광지 인근**: 성수기 **웨이팅·가격** 프리미엄을 감안하세요.
                """
            )
        with s4:
            st.markdown(
                """
##### 전국 공통
- **검색어**: `지역명 + 먹거리 + (점심 OR 저녁)` 보다 **`동네 이름 + 음식 종류`** 가 때로 더 잘 맞습니다.
- **앱**: **네이버 지도·카카오맵** — 길찾기·리뷰. **망고플레이트** — 큐레이션(취향 차 큼). **미슐랭 가이드** — 상위권 레스토랑(예약 필수인 경우 많음).
- **리뷰**: **극단적 호·혹평**은 참고만. **사진 날짜·메뉴판**이 맞는지 봅니다.
- **예약**: 네이버·캐치테이블·전화. **노쇼**는 업주·다음 손님 모두에게 피해입니다.

---
**재미 요소**: 친구와 **지역별 ‘해먹어 볼 리스트’**(예: 서울 냉면 3곳, 경기 브런치 2곳)를 메모 앱에 두고 **천천히 채우는** 식으로 쓰면 부담 없이 즐기기 좋습니다.
                """
            )
            st.markdown(
                "- [망고플레이트](https://www.mangoplate.com/) · [미슐랭 가이드 서울](https://guide.michelin.com/kr/ko)"
            )


def main() -> None:
    st.set_page_config(
        page_title="오늘의 픽 · 주식 스캐너",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    # 기본은 다크 톤 블록 + 이후 «PC 레퍼런스» 블록에서 실까형 라이트로 덮어씀
    st.markdown(
        """
<style>
    /* ── 기본 ── */
    html {
        -webkit-text-size-adjust: 100%;
        scroll-padding-top: 3.5rem;
    }
    /* ── 앱 배경 ── */
    .stApp {
        -webkit-tap-highlight-color: rgba(59, 130, 246, 0.20);
        background: radial-gradient(1200px 700px at 10% -10%, rgba(96, 165, 250, 0.18), transparent 55%),
                    radial-gradient(1000px 600px at 100% 0%, rgba(139, 92, 246, 0.16), transparent 52%),
                    linear-gradient(180deg, #0f172a 0%, #111827 52%, #0b1220 100%) fixed !important;
        color: #e5e7eb !important;
    }
    /* ── 메인 컨테이너: 모바일 우선 ── */
    .main .block-container {
        padding-top: 0.75rem !important;
        padding-bottom: env(safe-area-inset-bottom, 2rem) !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
        max-width: 720px !important;
        font-size: clamp(1rem, 3.5vw, 1.08rem) !important;
    }
    /* ── 사이드바 ── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(30, 27, 75, 0.98) 0%, rgba(49, 46, 129, 0.94) 100%) !important;
        border-right: 1px solid rgba(165, 180, 252, 0.28);
    }
    /* ── 텍스트 ── */
    .main h1 { font-size: clamp(1.5rem, 5vw, 2rem) !important; color: #fafaff !important; text-shadow: 0 1px 3px rgba(30,27,75,0.45); margin-bottom: 0.35rem !important; }
    .main h2 { font-size: clamp(1.2rem, 4vw, 1.6rem) !important; color: #fafaff !important; }
    .main h3 { font-size: clamp(1.05rem, 3.5vw, 1.3rem) !important; color: #fafaff !important; }
    .main p, .main li, .main .stMarkdown { color: #eef2ff !important; }
    .main a { color: #a5b4fc !important; text-decoration: underline; text-underline-offset: 2px; font-weight: 500; }
    .main a:visited { color: #c7d2fe !important; }
    .stCaption, [data-testid="stCaptionContainer"] > div {
        color: #e0e7ff !important;
        font-size: clamp(0.88rem, 3vw, 0.98rem) !important;
        opacity: 1 !important;
    }
    /* ── Sticky Header ── */
    header[data-testid="stHeader"] {
        position: sticky !important;
        top: 0 !important;
        z-index: 999991 !important;
        background: rgba(30, 27, 75, 0.92) !important;
        backdrop-filter: blur(6px) !important;
        -webkit-backdrop-filter: blur(6px) !important;
        border-bottom: 1px solid rgba(165, 180, 252, 0.28) !important;
    }
    header[data-testid="stHeader"] [data-testid="stToolbar"] button { color: #e0e7ff !important; }
    /* ── 상단 그룹 탭 바: 한 줄에 모두 표시 ── */
    .stTabs [data-baseweb="tab-list"] {
        display: flex !important;
        flex-wrap: nowrap !important;
        gap: 0.2rem;
        padding: 0.25rem !important;
        background: rgba(30, 41, 59, 0.70);
        border-radius: 12px;
        border: 1px solid rgba(148, 163, 184, 0.22);
        overflow: visible !important;
    }
    .stTabs [data-baseweb="tab-list"] button {
        flex: 1 1 0 !important;          /* 균등 너비 */
        min-width: 0 !important;
        min-height: 2.1rem !important;
        padding: 0.18rem 0.22rem !important;
        font-size: clamp(0.64rem, 2.4vw, 0.78rem) !important;
        line-height: 1.1 !important;
        border-radius: 9px !important;
        color: #cbd5e1 !important;
        background: rgba(51, 65, 85, 0.65) !important;
        border: 1px solid rgba(100, 116, 139, 0.30) !important;
        white-space: normal !important;
        word-break: keep-all !important;
        text-align: center !important;
        transition: background 0.15s ease;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background: linear-gradient(165deg, #3b82f6 0%, #2563eb 100%) !important;
        color: #f8fafc !important;
        border-color: rgba(147, 197, 253, 0.68) !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 12px rgba(37, 99, 235, 0.35) !important;
    }
    /* ── 서브 탭 (탭 안의 탭): 넘치면 다음 줄로 — 모바일에서 코스피/코스닥 등 */
    .stTabs .stTabs [data-baseweb="tab-list"] {
        display: flex !important;
        flex-wrap: wrap !important;
        overflow-x: visible !important;
        background: rgba(30, 27, 75, 0.5);
        border-radius: 10px;
        padding: 0.3rem !important;
        gap: 0.35rem;
        justify-content: flex-start;
    }
    .stTabs .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
    .stTabs .stTabs [data-baseweb="tab-list"] button {
        flex: 1 1 calc(50% - 0.35rem) !important;
        min-width: min(100%, 9.5rem) !important;
        max-width: 100% !important;
        min-height: 1.85rem !important;
        padding: 0.18rem 0.36rem !important;
        font-size: clamp(0.64rem, 2.4vw, 0.8rem) !important;
        border-radius: 8px !important;
        white-space: normal !important;
        word-break: keep-all !important;
        text-align: center !important;
        line-height: 1.1 !important;
    }
    /* ── 메트릭 카드 ── */
    div[data-testid="stMetric"] {
        background: linear-gradient(160deg, rgba(30, 41, 59, 0.96) 0%, rgba(15, 23, 42, 0.95) 100%) !important;
        border: 1px solid rgba(148, 163, 184, 0.28) !important;
        border-radius: 12px !important;
        box-shadow: 0 4px 14px rgba(2, 6, 23, 0.42) !important;
        padding: 1rem !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] { color: #c7d2fe !important; font-size: clamp(0.8rem, 3vw, 0.95rem) !important; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #fafaff !important; font-size: clamp(1.3rem, 5.5vw, 1.8rem) !important; }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] { color: #a5b4fc !important; }
    /* ── 위젯 공통 ── */
    label[data-testid="stWidgetLabel"], label[data-testid="stWidgetLabel"] p {
        color: #eef2ff !important; font-weight: 500 !important;
    }
    /* ── 입력 필드 ── */
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div {
        background-color: #312e81 !important;
        border-color: rgba(129, 140, 248, 0.42) !important;
        color: #fafaff !important;
    }
    div[data-baseweb="select"] span,
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea { color: #fafaff !important; }
    .stTextInput input, .stNumberInput input {
        background-color: #312e81 !important; color: #fafaff !important;
        border: 1px solid rgba(129, 140, 248, 0.42) !important;
        caret-color: #a5b4fc !important;
        font-size: clamp(1rem, 3.5vw, 1.08rem) !important;
        padding: 0.6rem 0.8rem !important;
        border-radius: 10px !important;
    }
    div[data-baseweb="datepicker"] input, [data-testid="stDateInput"] input {
        background-color: #312e81 !important; color: #fafaff !important;
        border-color: rgba(129, 140, 248, 0.42) !important;
    }
    div[data-testid="stSlider"] label { color: #e0e7ff !important; }
    /* ── 버튼 ── */
    button[kind="secondary"] {
        background: #433d8b !important; color: #eef2ff !important;
        border: 1px solid rgba(165, 180, 252, 0.38) !important;
        border-radius: 12px !important;
        min-height: 2.8rem !important;
        font-size: clamp(0.95rem, 3.5vw, 1.05rem) !important;
        width: 100% !important;
    }
    button[kind="primary"] {
        border-radius: 12px !important; font-weight: 600 !important;
        background: linear-gradient(165deg, #6366f1 0%, #4f46e5 100%) !important;
        color: #fafaff !important;
        border: 1px solid rgba(199, 210, 254, 0.45) !important;
        min-height: 2.8rem !important;
        font-size: clamp(0.95rem, 3.5vw, 1.05rem) !important;
        width: 100% !important;
    }
    /* ── 링크 버튼 ── */
    a[data-testid="stLinkButton"] {
        width: 100% !important;
        min-height: 2.8rem !important;
        border-radius: 12px !important;
        font-size: clamp(0.95rem, 3.5vw, 1.05rem) !important;
    }
    /* ── 접기 패널 ── */
    details summary, .streamlit-expanderHeader {
        color: #eef2ff !important; background: #312e81 !important;
        border-radius: 10px !important;
        border: 1px solid rgba(165, 180, 252, 0.22) !important;
        padding: 0.8rem 1rem !important;
        font-size: clamp(0.95rem, 3.5vw, 1.05rem) !important;
    }
    /* ── 알림 패널 ── */
    div[data-testid="stAlert"] {
        border-radius: 14px !important;
        background: linear-gradient(165deg, rgba(49, 46, 129, 0.92) 0%, rgba(67, 56, 202, 0.55) 100%) !important;
        border: 1px solid rgba(165, 180, 252, 0.45) !important;
        color: #eef2ff !important;
    }
    div[data-testid="stAlert"] p, div[data-testid="stAlert"] span { color: #eef2ff !important; }
    /* ── 포털 카드 (border 컨테이너) ── */
    section.main div[data-testid="stVerticalBlockBorderWrapper"] {
        background: linear-gradient(165deg, rgba(30, 41, 59, 0.78) 0%, rgba(15, 23, 42, 0.88) 100%) !important;
        border: 1px solid rgba(100, 116, 139, 0.40) !important;
        border-radius: 14px !important;
        box-shadow: 0 10px 26px rgba(2, 6, 23, 0.34), inset 0 1px 0 rgba(255,255,255,0.05) !important;
        padding: 1rem 1rem 1.2rem !important;
        margin-bottom: 0.75rem !important;
        border-left: 3px solid rgba(59, 130, 246, 0.55) !important;
        transition: border-color 0.2s ease, box-shadow 0.2s ease;
    }
    section.main div[data-testid="stVerticalBlockBorderWrapper"]:hover {
        border-color: rgba(199, 210, 254, 0.42) !important;
        box-shadow: 0 16px 44px rgba(30, 27, 75, 0.48), inset 0 1px 0 rgba(255,255,255,0.08) !important;
    }
    section.main div[data-testid="stVerticalBlockBorderWrapper"] p,
    section.main div[data-testid="stVerticalBlockBorderWrapper"] li { color: #eef2ff !important; }
    section.main div[data-testid="stVerticalBlockBorderWrapper"] [data-testid="stCaptionContainer"] { opacity: 0.92 !important; }
    /* ── 모바일 전용 (≤480px) ── */
    @media (max-width: 480px) {
        .main .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
        }
        /* 그룹 탭: 폰에서 더 작게 */
        .stTabs [data-baseweb="tab-list"] {
            gap: 0.15rem;
            padding: 0.25rem !important;
        }
        .stTabs [data-baseweb="tab-list"] button {
            min-height: 1.75rem !important;
            padding: 0.12rem 0.14rem !important;
            font-size: clamp(0.58rem, 2.3vw, 0.72rem) !important;
        }
        div[data-testid="stMetric"] { padding: 0.8rem !important; }
    }
</style>
        """,
        unsafe_allow_html=True,
    )
    # 화이트 톤 오버라이드 (요청 반영)
    st.markdown(
        """
<style>
    .stApp {
        background: #f8fafc !important;
        color: #0f172a !important;
    }
    section[data-testid="stSidebar"] {
        background: #ffffff !important;
        border-right: 1px solid #e2e8f0 !important;
    }
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"],
    section[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p,
    section[data-testid="stSidebar"] label,
    section[data-testid="stSidebar"] label p,
    section[data-testid="stSidebar"] .stCaption {
        color: #0f172a !important;
        opacity: 1 !important;
    }
    section[data-testid="stSidebar"] a.nav-link {
        color: #0f172a !important;
        background: #f8fafc !important;
        border: 1px solid #d1d5db !important;
        font-weight: 600 !important;
    }
    section[data-testid="stSidebar"] a.nav-link i,
    section[data-testid="stSidebar"] a.nav-link span {
        color: inherit !important;
    }
    section[data-testid="stSidebar"] a.nav-link.active {
        color: #ffffff !important;
        background: #111827 !important;
        border-color: #111827 !important;
    }
    .main h1, .main h2, .main h3,
    .main p, .main li, .main .stMarkdown,
    .stCaption, [data-testid="stCaptionContainer"] > div {
        color: #0f172a !important;
        text-shadow: none !important;
    }
    .stTabs [data-baseweb="tab-list"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
    }
    .stTabs [data-baseweb="tab-list"] button {
        background: #f8fafc !important;
        color: #334155 !important;
        border: 1px solid #e2e8f0 !important;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background: #0f172a !important;
        color: #ffffff !important;
        border-color: #0f172a !important;
        box-shadow: none !important;
    }
    div[data-testid="stMetric"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.08) !important;
    }
    section.main div[data-testid="stVerticalBlockBorderWrapper"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        border-left: 3px solid #94a3b8 !important;
        box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06) !important;
    }
    section.main div[data-testid="stVerticalBlockBorderWrapper"] p,
    section.main div[data-testid="stVerticalBlockBorderWrapper"] li {
        color: #0f172a !important;
    }
    /* 다크 테마 잔여 규칙 무력화: 라벨·메트릭·입력·알림·확장 패널 */
    label[data-testid="stWidgetLabel"], label[data-testid="stWidgetLabel"] p {
        color: #334155 !important;
    }
    section[data-testid="stSidebar"] label[data-testid="stWidgetLabel"],
    section[data-testid="stSidebar"] label[data-testid="stWidgetLabel"] p {
        color: #0f172a !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] {
        color: #475569 !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] {
        color: #0f172a !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #334155 !important;
    }
    div[data-testid="stAlert"] {
        background: #ffffff !important;
        border: 1px solid #e2e8f0 !important;
        color: #0f172a !important;
    }
    div[data-testid="stAlert"] p,
    div[data-testid="stAlert"] span,
    div[data-testid="stAlert"] div {
        color: #0f172a !important;
    }
    .stTextInput input, .stNumberInput input,
    div[data-baseweb="input"] input,
    div[data-baseweb="textarea"] textarea {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border: 1px solid #cbd5e1 !important;
        caret-color: #0f172a !important;
    }
    div[data-baseweb="select"] > div,
    div[data-baseweb="input"] > div,
    div[data-baseweb="textarea"] > div {
        background-color: #ffffff !important;
        border-color: #cbd5e1 !important;
        color: #0f172a !important;
    }
    div[data-baseweb="select"] span { color: #0f172a !important; }
    div[data-baseweb="datepicker"] input, [data-testid="stDateInput"] input {
        background-color: #ffffff !important;
        color: #0f172a !important;
        border-color: #cbd5e1 !important;
    }
    div[data-testid="stSlider"] label { color: #334155 !important; }
    details summary, .streamlit-expanderHeader {
        color: #0f172a !important;
        background: #f1f5f9 !important;
        border: 1px solid #e2e8f0 !important;
    }
    header[data-testid="stHeader"] {
        background: #ffffff !important;
        border-bottom: 1px solid #e2e8f0 !important;
    }
    header[data-testid="stHeader"] [data-testid="stToolbar"] button {
        color: #334155 !important;
    }
    /* 모바일: 사이드바 열기(>>) — testid가 버튼에 직접 붙음 */
    button[data-testid="stExpandSidebarButton"] {
        color: #0f172a !important;
        background-color: #f1f5f9 !important;
        border: 2px solid #475569 !important;
        border-radius: 12px !important;
        min-width: 2.85rem !important;
        min-height: 2.85rem !important;
        box-shadow: 0 1px 4px rgba(15, 23, 42, 0.18) !important;
    }
    button[data-testid="stExpandSidebarButton"]:hover {
        background-color: #e2e8f0 !important;
        border-color: #0f172a !important;
    }
    button[data-testid="stExpandSidebarButton"] svg,
    button[data-testid="stExpandSidebarButton"] span {
        color: #0f172a !important;
        fill: #0f172a !important;
        stroke: #0f172a !important;
    }
    /* 접기 « — testid는 헤더 래퍼에, 기본 color가 fadedText60 */
    div[data-testid="stSidebarCollapseButton"] {
        color: #0f172a !important;
    }
    div[data-testid="stSidebarCollapseButton"] button {
        color: #0f172a !important;
        background-color: #f1f5f9 !important;
        border: 2px solid #475569 !important;
        border-radius: 12px !important;
        min-width: 2.85rem !important;
        min-height: 2.85rem !important;
        box-shadow: 0 1px 4px rgba(15, 23, 42, 0.18) !important;
    }
    div[data-testid="stSidebarCollapseButton"] button:hover {
        background-color: #e2e8f0 !important;
        border-color: #0f172a !important;
    }
    div[data-testid="stSidebarCollapseButton"] svg,
    div[data-testid="stSidebarCollapseButton"] span {
        color: #0f172a !important;
        fill: #0f172a !important;
        stroke: #0f172a !important;
    }
    /* 구버전 Streamlit 등 */
    button[kind="header"] {
        color: #0f172a !important;
        background-color: #f1f5f9 !important;
        border: 2px solid #475569 !important;
        border-radius: 12px !important;
    }
    .main a { color: #2563eb !important; }
    .main a:visited { color: #4f46e5 !important; }
    /* 중첩 탭(코스피/코스닥 등) */
    .stTabs .stTabs [data-baseweb="tab-list"] {
        background: #f8fafc !important;
        border: 1px solid #e2e8f0 !important;
    }
    .stTabs .stTabs [data-baseweb="tab-list"] button {
        background: #ffffff !important;
        color: #334155 !important;
        border: 1px solid #e2e8f0 !important;
    }
    .stTabs .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background: #0f172a !important;
        color: #ffffff !important;
        border-color: #0f172a !important;
    }
    /* dataframe / table 주변 보조 텍스트 */
    .stDataFrame, [data-testid="stDataFrame"] { color: #0f172a !important; }
    button[kind="primary"] {
        background: #0f172a !important;
        color: #ffffff !important;
        border: 1px solid #0f172a !important;
    }
    button[kind="secondary"] {
        background: #f1f5f9 !important;
        color: #0f172a !important;
        border: 1px solid #cbd5e1 !important;
    }
</style>
        """,
        unsafe_allow_html=True,
    )
    # PC 레퍼런스 톤 강제 통일 (최종 오버라이드)
    st.markdown(
        """
<style>
    @media (min-width: 1024px) {
        .main .block-container {
            max-width: min(960px, calc(100vw - 2.5rem)) !important;
            margin-left: auto !important;
            margin-right: clamp(0.75rem, 2vw, 1.75rem) !important;
            padding-top: 1.05rem !important;
            padding-left: 1.25rem !important;
            padding-right: 1.25rem !important;
        }
    }
    .stApp {
        background: #ffffff !important;
        color: #111827 !important;
    }
    .main h1, .main h2, .main h3 {
        color: #0b1220 !important;
        font-weight: 800 !important;
        letter-spacing: -0.01em;
    }
    .main p, .main li, .main .stMarkdown, .stCaption {
        color: #1f2937 !important;
    }
    section.main div[data-testid="stVerticalBlockBorderWrapper"] {
        border: 1px solid #dbe3ee !important;
        border-left: 1px solid #dbe3ee !important;
        border-radius: 12px !important;
        box-shadow: none !important;
        background: #ffffff !important;
    }
    /* 탭: 포털·시장 공통 — 코스피 스캐너 서브탭과 동일하게 넉넉한 터치·줄바꿈 */
    .stTabs [data-baseweb="tab-list"] {
        background: #ffffff !important;
        border: none !important;
        border-bottom: 1px solid #d1d9e6 !important;
        border-radius: 0 !important;
        display: flex !important;
        flex-wrap: wrap !important;
        gap: 0.35rem !important;
        row-gap: 0.4rem !important;
        padding: 0.2rem 0 0.35rem 0 !important;
        overflow-x: visible !important;
    }
    .stTabs [data-baseweb="tab-list"] button {
        background: #ffffff !important;
        border: none !important;
        border-radius: 0 !important;
        color: #374151 !important;
        min-height: 2.75rem !important;
        min-width: min(100%, 7.5rem) !important;
        padding: 0.5rem 0.85rem !important;
        font-size: clamp(0.88rem, 2.6vw, 1.02rem) !important;
        font-weight: 600 !important;
        flex: 1 1 auto !important;
        white-space: normal !important;
        word-break: keep-all !important;
        text-align: center !important;
        line-height: 1.25 !important;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        color: #111827 !important;
        border-bottom: 2px solid #111827 !important;
        background: #ffffff !important;
        box-shadow: none !important;
    }
    /* 중첩 탭(홈→부동산 내부 탭, 코스피→순위 테이블 등): 동일 높이·여백 유지 */
    .stTabs .stTabs [data-baseweb="tab-list"] {
        flex-wrap: wrap !important;
        gap: 0.4rem !important;
        padding: 0.25rem 0 !important;
        border-bottom: 1px solid #e2e8f0 !important;
    }
    .stTabs .stTabs [data-baseweb="tab-list"] button {
        min-height: 2.75rem !important;
        min-width: min(100%, 9rem) !important;
        padding: 0.5rem 0.85rem !important;
        font-size: clamp(0.88rem, 2.6vw, 1rem) !important;
        flex: 1 1 calc(50% - 0.35rem) !important;
    }
    @media (max-width: 480px) {
        .stTabs [data-baseweb="tab-list"] button,
        .stTabs .stTabs [data-baseweb="tab-list"] button {
            min-height: 2.7rem !important;
            font-size: clamp(0.84rem, 3.1vw, 0.98rem) !important;
            padding: 0.48rem 0.7rem !important;
            flex: 1 1 calc(50% - 0.35rem) !important;
            max-width: 100% !important;
        }
    }
    /* 입력/버튼 톤도 통일 */
    .stTextInput input, .stNumberInput input,
    div[data-baseweb="input"] input, div[data-baseweb="select"] > div {
        border: 1px solid #cbd5e1 !important;
        border-radius: 10px !important;
        background: #ffffff !important;
        color: #111827 !important;
    }
    button[kind="primary"] {
        background: #111827 !important;
        border-color: #111827 !important;
        color: #ffffff !important;
    }
    button[kind="secondary"] {
        background: #ffffff !important;
        border: 1px solid #cbd5e1 !important;
        color: #111827 !important;
    }
    /* 실까형: 좌측 내비 제거(상단 바만 사용) */
    section[data-testid="stSidebar"] { display: none !important; }
    div[data-testid="stSidebarCollapsedControl"] { display: none !important; }
    /* 구버전 Streamlit 사이드 펼침 버튼 */
    button[data-testid="stExpandSidebarButton"] { display: none !important; }
    [data-testid="collapsedControl"] { display: none !important; }
    /* 메인: 넓은 화면에서 오른쪽 정렬(실까처럼 본문이 우측 영역에 모임) */
    .main .block-container {
        max-width: min(960px, calc(100vw - 2.5rem)) !important;
        margin-left: auto !important;
        margin-right: clamp(0.5rem, 2vw, 1.75rem) !important;
    }
    @media (max-width: 640px) {
        .main .block-container {
            margin-left: auto !important;
            margin-right: auto !important;
            max-width: 100% !important;
        }
    }
    div[data-testid="stMetric"] {
        background: #f8fafc !important;
        border: 1px solid #e2e8f0 !important;
        box-shadow: none !important;
    }
    div[data-testid="stMetric"] [data-testid="stMetricLabel"] { color: #64748b !important; }
    div[data-testid="stMetric"] [data-testid="stMetricValue"] { color: #0f172a !important; }
</style>
        """,
        unsafe_allow_html=True,
    )

    _app_path = Path(__file__).resolve()
    _app_mtime_kst = _file_mtime_str_kst(_app_path)
    st.caption(f"`app.py` 저장 시각(KST): {_app_mtime_kst}")

    _nav = _render_topbar_nav_select()
    _render_group_market(_nav)

if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
생활 정보 + GitHub 덴 + 채팅 에이전트 (Streamlit)
UI: Glassmorphism / Neumorphism / Responsive / Sticky Header (CSS)
테마: 따뜻한 신뢰감을 주는 소프트 블루·인디고 팔레트(본문·링크·카드·탭 통일).
레이아웃: 사이드바 option_menu · 메인은 st.container(border=True) 카드 셸 + 전역 카드 CSS.
홈 «마이 대시보드» 탭군에 **여행 스케치(목업)** — 국가별 데모 카드.
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
- 화장품 가격비교: 채널별 **목업 표** + 공식몰 링크(실시간 가격 미연동)
- 컴퓨터 가격비교: 제품군별 **목업 표** + 가격 비교 사이트 링크(실시간 미연동)
"""

from __future__ import annotations

import html
import os
import re
from contextlib import contextmanager
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


def _st_try_border_container() -> Any:
    """테두리 컨테이너(border 미지원 빌드는 일반 container). 카드형 블록 공통."""

    try:
        return st.container(border=True)
    except TypeError:
        return st.container()


def _df_to_csv_utf8_sig_bytes(df: Any) -> bytes:
    """pandas DataFrame → 한글·컬럼명 보존 CSV 바이트(Excel 호환 BOM 포함)."""

    return df.to_csv(encoding="utf-8-sig").encode("utf-8-sig")


# 글로벌 시각 탭
CLOCK_ZONES: list[tuple[str, str]] = [
    ("서울", "Asia/Seoul"),
    ("뉴욕", "America/New_York"),
    ("런던", "Europe/London"),
    ("UTC", "UTC"),
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

# 필수체크리스트 — 학부모 행동 단위 (세션에 체크 상태 저장)
PARENT_CHECKLIST_ITEMS: list[dict[str, str]] = [
    {
        "label": "📌 관할 시·도 교육청·(해당 시) 구청 **입학·배정 공지** 확인",
        "hint": "연도·거주지별로 일정과 서류가 다릅니다.",
    },
    {
        "label": "🏫 **학교알리미**로 배정·관심 학교 조회 (**교복**·공시·**통학·배정** 참고)",
        "hint": "공시 범위 안에서 비교하고, 최종 배정·학구는 교육청·학교 공지를 따르세요.",
    },
    {
        "label": "🔔 **나이스 학부모**에서 연락처·알림 설정 · **성적·출결** 확인 흐름 익히기",
        "hint": "통지·열람 경로를 미리 맞춰 두면 학년 전환 시 수월합니다.",
    },
    {
        "label": "📱 **e-알리미·아이알리미** 등 학교 안내 앱 설치·알림 설정",
        "hint": "학교가 채택한 서비스만 해당합니다.",
    },
    {
        "label": "📄 입학·전학에 필요한 **민원·증명(정부24 등)** 준비 여부 확인",
        "hint": "주민등록·가족관계등본 등 발급 가능 여부.",
    },
    {
        "label": "🚌 자녀와 **통학·등하교 안전 동선** 이야기 나누기",
        "hint": "처음 다니는 길은 여유 있게 연습할 수 있습니다.",
    },
    {
        "label": "☎️ 가족이 **청소년 상담 1388** 번호·사이트를 아는지 확인",
        "hint": "위기 시 바로 쓸 수 있게 공유해 두면 좋습니다.",
    },
    {
        "label": "📅 학교 **방과후·동아리 모집 시즌** 공지 확인",
        "hint": "학교 홈페이지·알림 앱을 함께 보세요.",
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
        return "**🗺️ 여행 스케치** 탭에서 국가를 고르면 목업 날씨·여행 시즌·축제·명소 TOP3를 카드로 볼 수 있습니다."
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


# 국가별 여행 목업 (데모용 — 실제 일정·날씨와 무관)
# 구조: { 국가명(str): { "날씨": str, "시기": str, "축제": list[str], "명소": list[str], … } }
TRAVEL_MOCK_BY_COUNTRY: dict[str, dict[str, Any]] = {
    "대한민국": {
        "lat": 37.5665, "lon": 126.9780, "city": "서울",
        "날씨": "서울 기준 **맑음** · 기온 **14°C** · 바람 약 · 미세먼지 **보통** (목업)",
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
        "travel_tip": "💡 **대한민국** · 교통카드(T-money·카카오 등)를 미리 준비하면 시내 이동이 수월합니다. 인기 맛집·카페는 점심·저녁 피크 시간대 예약을 권합니다. (목업 안내)",
        "travel_tip_style": "info",
    },
    "일본": {
        "lat": 35.6762, "lon": 139.6503, "city": "도쿄",
        "날씨": "도쿄 기준 **흐림 곳곳 맑음** · **16°C** · 습도 보통 (목업)",
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
        "travel_tip": "💡 **일본** · 편의점 ATM·교통카드(IC) 충전은 현금 없이도 가능한 경우가 많습니다. 대중목욕·온천은 작은 타월을 챙기면 편합니다. (목업 안내)",
        "travel_tip_style": "info",
    },
    "태국": {
        "lat": 13.7563, "lon": 100.5018, "city": "방콕",
        "날씨": "방콕 기준 **대체로 맑음** · **32°C** · 소나기 가능(목업)",
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
        "travel_tip": "⚠️ **태국** · 더위·습기가 큽니다. 수분 보충·자외선 차단을 권합니다. 야시장·관광지에서는 소매치기·택시 요금을 미리 확인하세요. 입국 규정은 공식 안내를 따르세요. (목업 안내)",
        "travel_tip_style": "warning",
    },
    "프랑스": {
        "lat": 48.8566, "lon": 2.3522, "city": "파리",
        "날씨": "파리 기준 **약간 흐림** · **12°C** · 서늘한 바람 (목업)",
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
        "travel_tip": "💡 **프랑스** · 미술관은 사전 예약·오전 입장이 한산한 편입니다. 파리 외 지역 이동은 기차(TGV 등) 예약을 미리 하면 좋습니다. (목업 안내)",
        "travel_tip_style": "info",
    },
    "미국": {
        "lat": 40.7128, "lon": -74.0060, "city": "뉴욕",
        "날씨": "뉴욕 기준 **맑음** · **11°C** · 봄날씨 느낌 (목업)",
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
        "travel_tip": "⚠️ **미국** · ESTA·비자 등 **입국 요건**은 사전에 공식 사이트에서 확인하세요. 식당·택시는 팁 문화가 있습니다. 주별 세금·교통 규칙이 다를 수 있습니다. (목업 안내)",
        "travel_tip_style": "warning",
    },
    "이탈리아": {
        "lat": 41.9028, "lon": 12.4964, "city": "로마",
        "날씨": "로마 기준 **맑음** · **18°C** · 봄 햇살 (목업)",
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
        "travel_tip": "💡 **이탈리아** · 유적·박물관은 입장권을 미리 끊으면 대기 시간을 줄일 수 있습니다. 관광지 밀집 지역은 소지품을 살펴보세요. 일부 레스토랑에는 테이블 비용(coperto) 등 안내가 있으니 확인하면 좋습니다. (목업 안내)",
        "travel_tip_style": "info",
    },
}


def _travel_season_metric(season_md: str) -> str:
    """시기 문단에서 추천 시즌 메트릭 라벨 — EM/EN dash·전각 마이너스 등 국가별 문자 차이 대응."""

    s = (season_md or "").strip()
    if not s:
        return "참고용 목업"
    # 첫 구분선만 분리 (숫자 범위의 '~'·일반 하이픈은 분리하지 않음)
    parts = re.split(r"\s*[\u2014\u2013\u2212\uFF0D]\s*", s, maxsplit=1)
    head_raw = parts[0].strip().replace("**", "").strip()
    if head_raw:
        return head_raw[:56] + ("…" if len(head_raw) > 56 else "")
    tail = parts[1].strip().replace("**", "").strip() if len(parts) > 1 else ""
    if tail:
        return tail[:56] + ("…" if len(tail) > 56 else "")
    return "참고용 목업"


def _travel_safe_metric_value(label: str) -> str:
    """st.metric value용 — 빈 문자열·개행 등으로 위젯 오류 나지 않게."""

    v = (label or "").replace("\r\n", " ").replace("\n", " ").strip()
    return v if v else "참고용 목업"


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
                # API 실패 시 목업 텍스트 폴백
                fallback = str(row.get("날씨") or "").strip() or "(날씨 정보 없음)"
                st.warning("날씨 API에 연결하지 못했습니다. 아래는 참고용 목업입니다.")
                st.markdown(fallback)
        else:
            st.markdown(str(row.get("날씨") or "(좌표 미등록 — 목업 표시)").strip())

    # ── 여행 최적기 카드 ──
    with _st_try_border_container():
        st.markdown("##### 📅 여행 최적기")
        metric_label = _travel_safe_metric_value(_travel_season_metric(season_md))
        try:
            st.metric(
                label="추천 시즌",
                value=metric_label,
                help="목업 요약입니다. 아래 문단에서 세부 설명을 확인하세요.",
            )
        except Exception:
            try:
                st.metric("추천 시즌", metric_label)
            except Exception:
                st.markdown(f"**추천 시즌** · {metric_label}")
        st.caption("상세 안내")
        st.markdown(season_md if season_md else "*시기 목업 문구가 비어 있습니다.*")


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


_NAV_OPTIONS: tuple[str, ...] = ("홈", "코스닥 스캐너", "코스피 스캐너", "학사정보", "학습준비", "필수체크리스트")

# 화장품 가격비교 (홈 탭 — 카테고리별 목업 표, 실시간 가격·재고와 무관)
COSMETICS_PRICE_COMPARE_MOCK: dict[str, list[dict[str, str]]] = {
    "스킨케어 · 에센스": [
        {
            "상품명": "데모 수분 에센스",
            "브랜드": "(목업 브랜드 A)",
            "용량": "80ml",
            "올리브영": "28,000원",
            "롭스": "26,400원",
            "쿠팡(참고)": "24,900원~",
            "비고": "행사가 변동 (목업)",
        },
        {
            "상품명": "데모 비타민 세럼",
            "브랜드": "(목업 브랜드 B)",
            "용량": "30ml",
            "올리브영": "42,000원",
            "롭스": "42,000원",
            "쿠팡(참고)": "39,500원~",
            "비고": "카드 할인 전후 상이",
        },
        {
            "상품명": "데모 장벽 크림",
            "브랜드": "(목업 브랜드 C)",
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
            "브랜드": "(목업 브랜드 D)",
            "용량": "14g",
            "올리브영": "32,000원",
            "롭스": "29,900원",
            "쿠팡(참고)": "27,800원~",
            "비고": "색상 옵션별 재고 상이",
        },
        {
            "상품명": "데모 립 틴트",
            "브랜드": "(목업 브랜드 E)",
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
            "브랜드": "(목업 브랜드 F)",
            "용량": "150ml",
            "올리브영": "15,000원",
            "롭스": "14,500원",
            "쿠팡(참고)": "12,900원~",
            "비고": "세일 주기 확인",
        },
        {
            "상품명": "데모 선크림 SPF50+",
            "브랜드": "(목업 브랜드 G)",
            "용량": "50ml",
            "올리브영": "22,000원",
            "롭스": "21,000원",
            "쿠팡(참고)": "19,400원~",
            "비고": "계절 수요 반영 (목업)",
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


# 컴퓨터 가격비교 (홈 탭 — 제품군별 목업 표, 실시간 최저가·재고와 무관)
PC_PRICE_COMPARE_MOCK: dict[str, list[dict[str, str]]] = {
    "노트북 · 미니 PC": [
        {
            "상품명": "데모 울트라북 14\"",
            "스펙 요약": "CPU 목업 · RAM 16GB · SSD 512GB",
            "다나와(참고)": "1,249,000원~",
            "쿠팡(참고)": "1,189,000원~",
            "11번가(참고)": "1,210,000원~",
            "비고": "색상·구성별 변동 (목업)",
        },
        {
            "상품명": "데모 게이밍 노트북 15.6\"",
            "스펙 요약": "목업 GPU · RAM 32GB",
            "다나와(참고)": "2,190,000원~",
            "쿠팡(참고)": "2,099,000원~",
            "11번가(참고)": "2,150,000원~",
            "비고": "번들·행사가 차이 큼",
        },
        {
            "상품명": "데모 미니 PC NUC형",
            "스펙 요약": "목업 CPU · RAM 16GB",
            "다나와(참고)": "689,000원~",
            "쿠팡(참고)": "659,000원~",
            "11번가(참고)": "—",
            "비고": "베어본 vs 완제품 비교",
        },
    ],
    "데스크톱 · 브랜드 PC": [
        {
            "상품명": "데모 사무용 브랜드 데스크톱",
            "스펙 요약": "목업 i5급 · RAM 16GB · SSD 512GB",
            "다나와(참고)": "989,000원~",
            "쿠팡(참고)": "959,000원~",
            "11번가(참고)": "970,000원~",
            "비고": "AS·보증 기간 확인",
        },
        {
            "상품명": "데모 게이밍 타워",
            "스펙 요약": "목업 CPU/GPU · RAM 32GB",
            "다나와(참고)": "2,590,000원~",
            "쿠팡(참고)": "2,499,000원~",
            "11번가(참고)": "2,540,000원~",
            "비고": "케이스·파워 옵션별 상이",
        },
    ],
    "주요 부품 (목업)": [
        {
            "상품명": "데모 그래픽카드 (차세대급)",
            "스펙 요약": "목업 VRAM 16GB",
            "다나와(참고)": "879,000원~",
            "쿠팡(참고)": "849,000원~",
            "11번가(참고)": "860,000원~",
            "비고": "출시·환율에 따름",
        },
        {
            "상품명": "데모 NVMe SSD 2TB",
            "스펙 요약": "목업 Gen4",
            "다나와(참고)": "219,000원~",
            "쿠팡(참고)": "199,000원~",
            "11번가(참고)": "209,000원~",
            "비고": "순차읽기 수치 비교 권장",
        },
        {
            "상품명": "데모 DDR5 RAM 32GB kit",
            "스펙 요약": "목업 5600MHz",
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


# 그룹 탭 5개 — 각 그룹 내부에서 서브탭으로 세분화
# 새 기능을 추가할 때: 해당 그룹의 _render_group_* 함수에 서브탭만 추가하면 됩니다.
_HOME_GROUP_SPEC: list[tuple[str, str]] = [
    ("📊 시장",  "market"),  # 주식·환율·세계시각
    ("🏘 부동산", "realty"), # 실거래·계산기·관심단지
    ("🌤️ 생활",  "life"),    # 날씨·뉴스
    ("🐙 개발",  "dev"),     # GitHub·만화·웹툰
    ("🛍️ 쇼핑",  "shop"),    # 화장품·컴퓨터 가격비교
    ("✈️ 기타",  "misc"),    # 여행 스케치·AI 에이전트
]

_OPTION_MENU_STYLES: dict[str, Any] = {
    "container": {"padding": "0.35rem 0", "background-color": "transparent"},
    "icon": {"font-size": "1.1rem", "color": "#c7d2fe"},
    "nav-link": {
        "font-size": "0.95rem",
        "text-align": "left",
        "margin": "4px 0",
        "padding": "0.55rem 0.65rem",
        "border-radius": "10px",
        "color": "#e0e7ff",
        "background-color": "rgba(99, 102, 241, 0.12)",
    },
    "nav-link-selected": {
        "background": "linear-gradient(165deg, #6366f1 0%, #4f46e5 100%)",
        "font-weight": "600",
        "color": "#fafaff",
        "border-left": "3px solid #c7d2fe",
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



def _render_tab_clocks() -> None:
    st.header("글로벌 시각")
    st.caption(
        "포털 US 리포트와 같이 볼 때 시차 확인용입니다. "
        "증시 일정·휴장은 브로커·거래소 캘린더를 따르세요."
    )
    c1, c2, c3, c4 = st.columns(4)
    for col, (label, zid) in zip((c1, c2, c3, c4), CLOCK_ZONES):
        with col:
            t = datetime.now(ZoneInfo(zid))
            st.metric(label, t.strftime("%m-%d %H:%M"))
            st.caption(zid.split("/")[-1])
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
<div style="padding:1rem 1.15rem 1.15rem;border-radius:16px;
background:linear-gradient(160deg,rgba(79,70,229,0.32) 0%,rgba(49,46,129,0.85) 100%);
border-left:4px solid #818cf8;margin-bottom:0.75rem;">
<p style="margin:0 0 0.55rem;font-size:1.05rem;font-weight:700;color:#e0e7ff;">
🧠 이 시뮬레이터가 바라보는 방식</p>

<p style="margin:0 0 0.35rem;color:#c7d2fe;font-size:0.96rem;">
<b>① 실질 수익률 = 명목 상승률 − 물가 상승률</b><br>
모든 금액은 물가를 차감한 <u>실질 가치(오늘의 구매력)</u>로 표시합니다.<br>
부동산 연 +1% · 물가 +2.5% → 실질 <b style="color:#f87171;">−1.5%</b> &nbsp;|&nbsp;
예금 +3% · 물가 +2.5% → 실질 <b style="color:#34d399;">+0.5%</b></p>

<p style="margin:0 0 0.35rem;color:#c7d2fe;font-size:0.96rem;">
<b>② 전세의 진짜 비용 = 기회비용</b><br>
전세는 월세 대신 목돈을 맡기는 구조입니다.
그 돈을 투자했다면 얻을 수익이 <u>사라진 기회비용</u>이며, 이것이 실질 월세입니다.<br>
예) 전세금 3억 × 연 5% ÷ 12 = 월 <b style="color:#fbbf24;">125만원</b> 기회비용<br>
집주인 입장에서는 무이자 대출을 받아 그 돈을 운용하는 구조입니다.</p>

<p style="margin:0;color:#a5b4fc;font-size:0.88rem;">
📌 차트 선이 <b>상승</b> = 실질 구매력 증가 &nbsp;|&nbsp;
<b>수평</b> = 물가만큼만 유지 &nbsp;|&nbsp; <b>하락</b> = 실질 손실</p>
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
                    itemgap=8,
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
    """채널별 목업 가격 표 — 외부 쇼핑몰 API 미연동."""

    st.header("💄 화장품 가격비교 (목업)")
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
        st.info("이 카테고리에는 목업 행이 없습니다.")

    st.divider()
    st.subheader("🔗 주요 비교·구매 채널 (링크)")
    with _st_try_border_container():
        for it in COSMETICS_PRICE_PORTALS:
            st.markdown(f"**[{it['t']}]({it['u']})** — {it['d']}")


def _render_tab_pc_compare() -> None:
    """제품군별 목업 가격 표 — 다나와 등 외부 실시간 데이터 미연동."""

    st.header("💻 컴퓨터 가격비교 (목업)")
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
        st.info("이 카테고리에는 목업 행이 없습니다.")

    st.divider()
    st.subheader("🔗 가격 비교·구매 채널 (링크)")
    with _st_try_border_container():
        for it in PC_PRICE_PORTALS:
            st.markdown(f"**[{it['t']}]({it['u']})** — {it['d']}")


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
    """선택 국가별 여행 목업 — 날씨·시즌·축제·명소 TOP3 카드. 탭 상단에서 국가 선택."""
    st.header("🗺️ 여행 스케치 (목업)")
    st.caption("아래에서 **국가를 고르면** 해당 목업 카드가 바로 바뀝니다.")

    st.warning(
        "표시 정보는 **데모용 목업 데이터**입니다. 실제 여행·항공·비자·안전 정보는 "
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
        help="목업 데이터입니다. 실제 일정·비자·안전은 공식 안내를 확인하세요.",
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

    # ── API 키 입력 ───────────────────────────────────────────
    with st.expander("🔑 국토교통부 API 연동 (data.go.kr 키 필요)", expanded=True):
        st.markdown(
            "[공공데이터포털](https://www.data.go.kr) → "
            "`국토교통부_아파트매매 실거래 상세 자료` 검색 → 활용신청 → 인증키 발급"
        )
        api_key = st.text_input("API 인증키 (Encoding)", type="password",
                                key="molit_api_key",
                                placeholder="data.go.kr 발급 인증키")

    if not api_key:
        st.info("API 키를 입력하면 실거래 데이터를 직접 조회할 수 있습니다.")
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


def _render_tab_stock_calc() -> None:
    """📈 주식 계산기 — 수익률·복리·세금"""
    st.header("📈 주식 계산기")
    calc_tabs = st.tabs(["💹 수익률 계산", "📦 복리 계산", "🧾 세금 계산"])

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
        for apt in st.session_state["apt_watchlist"]:
            q = apt.replace(" ", "+")
            q_enc = apt.replace(" ", "%20")
            with _st_try_border_container():
                st.markdown(f"#### 🏢 {apt}")
                lc1, lc2, lc3, lc4 = st.columns(4)
                lc1.markdown(
                    f"[![호갱노노](https://img.shields.io/badge/호갱노노-FF6B35?style=flat)]"
                    f"(https://hogangnono.com/apt/search?q={q})")
                lc2.markdown(
                    f"[![아실](https://img.shields.io/badge/아실-4CAF50?style=flat)]"
                    f"(https://asil.kr/asil/search.jsp?ename={q_enc})")
                lc3.markdown(
                    f"[![네이버부동산](https://img.shields.io/badge/네이버-03C75A?style=flat)]"
                    f"(https://land.naver.com/search/search.naver?query={q_enc})")
                lc4.markdown(
                    f"[![KB부동산](https://img.shields.io/badge/KB부동산-FFB900?style=flat)]"
                    f"(https://kbland.kr/map?tab=1&searchKeyword={q_enc})")

    # ── 국토교통부 API (선택) ──────────────────────────────────────
    st.divider()
    with st.expander("🔑 국토교통부 실거래가 API 연동 (선택 · API 키 필요)", expanded=False):
        st.markdown("""
**API 키 발급 방법**
1. [공공데이터포털](https://www.data.go.kr) 접속 → 회원가입
2. `국토교통부_아파트매매 실거래자료` 검색 → 활용신청
3. 발급된 **일반 인증키(Encoding)** 를 아래에 입력

발급 후 즉시 사용 가능 (당일 승인)
""")
        api_key = st.text_input("공공데이터포털 API 키", type="password",
                                key="apt_api_key",
                                placeholder="발급받은 인증키 붙여넣기")
        if api_key:
            st.success("API 키가 입력됐습니다. 현재 버전은 단지명 검색 연동 개발 예정입니다.")
            st.caption("지역코드(법정동 코드) 기반 조회 → 추후 단지 필터 추가 예정")

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


def _render_tab_stock_watchlist() -> None:
    """⭐ 관심 주식 — yfinance 실시간 워치리스트"""
    st.header("⭐ 관심 주식")
    st.caption("티커 심볼을 등록하면 실시간 시세와 차트를 확인할 수 있습니다.")

    if yf is None:
        st.warning("yfinance 라이브러리가 없어 시세를 불러올 수 없습니다.")
        return

    # ── 워치리스트 관리 ──────────────────────────────────────────
    if "stk_watchlist" not in st.session_state:
        st.session_state["stk_watchlist"] = ["005930.KS", "AAPL", "TSLA"]  # 기본값

    with _st_try_border_container():
        st.subheader("📌 종목 등록")
        st.caption("한국 주식: 종목코드.KS (예: 005930.KS) / 미국 주식: 티커 (예: AAPL)")
        wc1, wc2 = st.columns([5, 1])
        with wc1:
            new_ticker = st.text_input("티커 입력", key="stk_ticker_input",
                                       placeholder="005930.KS  또는  AAPL")
        with wc2:
            st.markdown("<br>", unsafe_allow_html=True)
            if st.button("➕ 추가", key="stk_add"):
                t = new_ticker.strip().upper()
                if t and t not in st.session_state["stk_watchlist"]:
                    st.session_state["stk_watchlist"].append(t)

        # 현재 목록
        tickers = st.session_state["stk_watchlist"]
        if tickers:
            rem_cols = st.columns(min(len(tickers), 6))
            for i, t in enumerate(tickers):
                col = rem_cols[i % len(rem_cols)]
                if col.button(f"❌ {t}", key=f"stk_rem_{i}"):
                    st.session_state["stk_watchlist"].pop(i)
                    st.rerun()

    if not st.session_state["stk_watchlist"]:
        st.info("관심 종목을 추가해 주세요.")
        return

    st.divider()

    @st.cache_data(ttl=300, show_spinner=False)
    def _fetch_quote(ticker: str) -> dict:
        try:
            tk = yf.Ticker(ticker)
            info = tk.fast_info
            hist = yf.download(ticker, period="1mo", interval="1d",
                               progress=False, auto_adjust=True)
            closes: list[float] = []
            dates:  list[str]   = []
            if hist is not None and not hist.empty:
                c = hist["Close"]
                if hasattr(c, "squeeze"):
                    c = c.squeeze()
                closes = [float(v) for v in c.tolist()]
                dates  = [str(d)[:10] for d in c.index.tolist()]
            return {
                "price":       getattr(info, "last_price",      None),
                "prev_close":  getattr(info, "previous_close",  None),
                "high_52w":    getattr(info, "year_high",       None),
                "low_52w":     getattr(info, "year_low",        None),
                "currency":    getattr(info, "currency",        ""),
                "closes":      closes,
                "dates":       dates,
            }
        except Exception:
            return {}

    # ── 종목 카드 ──────────────────────────────────────────────
    for ticker in st.session_state["stk_watchlist"]:
        with st.spinner(f"{ticker} 시세 로딩…"):
            q = _fetch_quote(ticker)

        with _st_try_border_container():
            h1, h2 = st.columns([3, 2])
            with h1:
                st.markdown(f"#### {ticker}")
                if q.get("price") and q.get("prev_close"):
                    price    = q["price"]
                    prev     = q["prev_close"]
                    chg      = price - prev
                    chg_pct  = chg / prev * 100 if prev else 0.0
                    currency = q.get("currency", "")
                    color    = "#34d399" if chg >= 0 else "#f87171"
                    sign     = "+" if chg >= 0 else ""
                    st.markdown(
                        f"<span style='font-size:1.5rem;font-weight:700;'>"
                        f"{price:,.2f} <span style='font-size:1rem;color:#94a3b8;'>{currency}</span>"
                        f"</span>&nbsp;&nbsp;"
                        f"<span style='color:{color};font-size:1.1rem;'>"
                        f"{sign}{chg:,.2f} ({sign}{chg_pct:.2f}%)</span>",
                        unsafe_allow_html=True,
                    )
                    if q.get("high_52w") and q.get("low_52w"):
                        h52, l52 = q["high_52w"], q["low_52w"]
                        pos = (price - l52) / (h52 - l52) * 100 if h52 != l52 else 50
                        st.caption(
                            f"52주 고: {h52:,.2f}  /  저: {l52:,.2f}  "
                            f"(현재 위치 {pos:.0f}%)"
                        )
                else:
                    st.warning("시세를 가져올 수 없습니다. 티커를 확인하세요.")

            with h2:
                # 1개월 미니 차트
                if go is not None and q.get("closes") and len(q["closes"]) > 1:
                    closes = q["closes"]
                    dates  = q["dates"]
                    c_color = "#34d399" if closes[-1] >= closes[0] else "#f87171"
                    fig_mini = go.Figure()
                    fig_mini.add_trace(go.Scatter(
                        x=dates, y=closes, mode="lines",
                        line=dict(color=c_color, width=2),
                        fill="tozeroy", fillcolor=f"rgba({'52,211,153' if closes[-1] >= closes[0] else '248,113,113'},0.08)",
                        hovertemplate="%{x}<br>%{y:,.2f}<extra></extra>",
                        showlegend=False,
                    ))
                    fig_mini.update_layout(
                        paper_bgcolor="rgba(0,0,0,0)",
                        plot_bgcolor="rgba(15,12,60,0.20)",
                        margin=dict(l=0, r=0, t=4, b=4),
                        height=80,
                        xaxis=dict(visible=False),
                        yaxis=dict(visible=False),
                    )
                    st.plotly_chart(fig_mini, use_container_width=True,
                                    config={"displayModeBar": False})


def _render_group_market() -> None:
    """📊 시장 그룹: 코스피·코스닥·자산시뮬·주식·환율·세계시각·주식계산기·관심주식"""
    t1, t2, t3, t4, t5, t6, t7, t8 = st.tabs([
        "📊 코스피", "📈 코스닥",
        "💰 자산시뮬", "📈 주식", "💱 환율", "🌍 세계시각",
        "📊 주식계산기", "⭐ 관심주식",
    ])
    with t1:
        _render_page_kospi()
    with t2:
        _render_page_kosdaq()
    with t3:
        _render_tab_asset_sim()
    with t4:
        _render_tab_stock()
    with t5:
        _render_tab_fx()
    with t6:
        _render_tab_clocks()
    with t7:
        _render_tab_stock_calc()
    with t8:
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

    # ── 실까 · 아파트미 빠른 링크 ──────────────────────────────
    st.markdown(
        "<div style='display:flex;gap:0.45rem;flex-wrap:wrap;margin-bottom:0.7rem;'>"
        + "".join(
            f"<a href='{url}' target='_blank' style='padding:0.28rem 0.6rem;"
            f"background:rgba(99,102,241,0.22);border-radius:18px;"
            f"color:#a5b4fc;font-size:0.82rem;text-decoration:none;"
            f"border:1px solid rgba(129,140,248,0.3);'>{lbl}</a>"
            for lbl, url in [
                ("📲 실까 앱", "https://naver.me/xEX1mw8c"),
                ("🔄 반등 실거래 (아파트미)", "https://apt2.me/apt/AptMonthBfSin.jsp"),
                ("🗺️ 실거래 지도", "https://apt2.me/apt/MapList.jsp"),
                ("📅 일별 신거래", "https://apt2.me/apt/map_day.jsp"),
                ("📊 KB 주택동향", "https://kbland.kr"),
                ("🏠 아실 (매물 추적)", "https://asil.kr"),
            ]
        )
        + "</div>",
        unsafe_allow_html=True,
    )

    api_key = st.session_state.get("molit_api_key", "")
    if not api_key:
        st.info("🔑 '실거래 현황' 탭에서 국토교통부 API 키를 먼저 입력하면\n"
                "지역별 거래량 자동 분석이 활성화됩니다.")

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
                prev_v = st.number_input(r_labels[0] if idx == 0 else "",
                                         min_value=0, value=row["전월"],
                                         key=f"radar_prev_{idx}",
                                         label_visibility="collapsed" if idx > 0 else "visible")
            with rc3:
                curr_v = st.number_input(r_labels[1] if idx == 0 else "",
                                         min_value=0, value=row["금월"],
                                         key=f"radar_curr_{idx}",
                                         label_visibility="collapsed" if idx > 0 else "visible")
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


def _render_group_realty() -> None:
    """🏘 부동산 그룹: 실거래·급등레이더·계산기·관심단지"""
    t1, t2, t3, t4 = st.tabs([
        "🔥 실거래 현황", "📉 급등 레이더", "🧮 부동산 계산기", "🏘 관심 단지",
    ])

    _TAB_FUNCS = [
        ("🔥 실거래 현황", _render_tab_apt_market),
        ("📉 급등 레이더", _render_tab_volume_radar),
        ("🧮 부동산 계산기", _render_tab_real_estate_calc),
        ("🏘 관심 단지",   _render_tab_apt_watchlist),
    ]
    for tab_ctx, (tab_name, fn) in zip([t1, t2, t3, t4], _TAB_FUNCS):
        with tab_ctx:
            try:
                fn()
            except Exception as _e:
                import traceback as _tb  # noqa: PLC0415
                st.error(f"**[{tab_name}] 렌더링 오류** — {_e}")
                with st.expander("오류 상세"):
                    st.code(_tb.format_exc(), language="python")


def _render_group_life() -> None:
    """🌤️ 생활 그룹: 날씨·뉴스"""
    t1, t2 = st.tabs(["🌤️ 날씨", "📰 뉴스"])
    with t1:
        _render_tab_weather()
    with t2:
        _render_tab_news()


def _render_group_dev() -> None:
    """🐙 개발 그룹: GitHub·만화·웹툰"""
    t1, t2 = st.tabs(["🐙 GitHub 덴", "📖 만화·웹툰"])
    with t1:
        _render_tab_github()
    with t2:
        _render_tab_comics()


def _render_group_shop() -> None:
    """🛍️ 쇼핑 그룹: 화장품·컴퓨터 가격비교"""
    t1, t2 = st.tabs(["💄 화장품", "💻 컴퓨터"])
    with t1:
        _render_tab_cosmetics_compare()
    with t2:
        _render_tab_pc_compare()


def _render_group_misc() -> None:
    """✈️ 여행·챗봇 그룹"""
    t1, t2 = st.tabs(["🗺️ 여행 스케치", "💬 AI 에이전트"])
    with t1:
        _render_tab_travel_mock()
    with t2:
        _render_tab_agent()


_HOME_GROUP_DISPATCH: dict[str, Any] = {
    "market": _render_group_market,
    "realty": _render_group_realty,
    "life":   _render_group_life,
    "dev":    _render_group_dev,
    "shop":   _render_group_shop,
    "misc":   _render_group_misc,
}


def _sidebar_travel_country_picker(nav_selected: str) -> None:
    """홈 메뉴일 때 사이드바에 여행 목업 선택 상태 표시(본 선택은 «여행 스케치» 탭 상단)."""
    if nav_selected != "홈":
        return
    countries = list(TRAVEL_MOCK_BY_COUNTRY.keys())
    cur = st.session_state.get("travel_mock_country_name")
    if cur not in TRAVEL_MOCK_BY_COUNTRY:
        cur = countries[0]
    with st.sidebar:
        st.divider()
        st.markdown("##### 🗺️ 여행 스케치 (목업)")
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
                icons=["house", "graph-up-arrow", "bar-chart-line", "journal-text", "book", "clipboard-check"],
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


@contextmanager
def _portal_page_card() -> Iterator[None]:
    """메인 영역 카드 셸 — `st.container(border=True)` + main() 내 포털 카드 CSS."""

    shell = _st_try_border_container()
    with shell:
        yield


def _render_scanner_page(
    title: str,
    data_dir_name: str,
    module_name: str,
    candidates_module: str,
    index_label: str,
) -> None:
    """코스닥/코스피 스캐너 공통 렌더러."""
    import os, json, threading, sys
    from pathlib import Path

    st.title(title)

    HERE        = Path(__file__).parent
    DATA_DIR    = HERE / data_dir_name
    CHARTS_DIR  = DATA_DIR / "charts"
    RESULTS_JSON = DATA_DIR / "results_web.json"
    DATA_DIR.mkdir(exist_ok=True)

    try:
        if str(HERE) not in sys.path:
            sys.path.insert(0, str(HERE))
        mod = __import__(module_name)
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

    col_btn, col_status = st.columns([1, 4])
    with col_btn:
        scan_clicked = st.button(
            "🔍 스캔 시작",
            key=f"btn_{data_dir_name}",
            disabled=st.session_state[scan_key] or not _core_ok,
            use_container_width=True,
        )
    with col_status:
        if st.session_state[scan_key]:
            st.info("⏳ 스캔 중… (5~20분 소요)", icon="⏳")
        elif RESULTS_JSON.exists():
            import datetime as _dt
            mtime = RESULTS_JSON.stat().st_mtime
            ts = _dt.datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
            st.success(f"마지막 분석: {ts}", icon="✅")

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
        except Exception as e:
            st.warning(f"결과 파일 로드 실패: {e}")

    if payload is None:
        st.info("결과 없음. '스캔 시작' 버튼을 눌러 분석을 실행하세요.")
        return

    # ── 지수 현황 ────────────────────────────────────────────────
    idx_status = payload.get("index", {})
    tone       = idx_status.get("tone", "unknown")
    headline   = idx_status.get("headline", "")
    tone_map   = {
        "stage2":  ("✅ Stage2 상승", "success"),
        "bear":    ("❌ 약세 (종가<MA200)", "error"),
        "caution": ("⚠️ 단기 둔화 (종가<MA50)", "warning"),
        "weak":    ("🔶 조정·횡보", "warning"),
        "unknown": ("❓ 데이터 없음", "info"),
    }
    tone_lbl, tone_type = tone_map.get(tone, ("❓ 알 수 없음", "info"))

    with st.container(border=True):
        st.markdown(f"### 🏛️ {index_label} 지수 현황")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("지수 상태", tone_lbl)
        c2.metric("종가",  f"{idx_status.get('last_close', '-'):,}" if idx_status.get("last_close") else "-")
        c3.metric("MA50",  f"{idx_status.get('ma50',  '-'):,}"      if idx_status.get("ma50")       else "-")
        c4.metric("MA200", f"{idx_status.get('ma200', '-'):,}"      if idx_status.get("ma200")      else "-")
        getattr(st, tone_type)(headline)

    tab_rank, tab_sector, tab_diff, tab_charts = st.tabs(
        ["📊 순위 테이블", "🗂️ 섹터 분포", "🔔 신규·탈락", "🖼️ 차트 뷰어"]
    )

    with tab_rank:
        top_table = payload.get("top_table") or payload.get("matches", [])
        if not top_table:
            st.info("Stage2 해당 종목 없음")
        else:
            import pandas as _pd
            rows = [{
                "순위":      m.get("rank", "-"),
                "티커":      m.get("ticker", ""),
                "종목명":    m.get("name", ""),
                "섹터":      m.get("sector", ""),
                "점수":      round(float(m.get("score") or 0), 1),
                "진입일":    m.get("entry", ""),
                "경과봉":    m.get("bars_since_stage2_entry", "-"),
                "RS비율":    f"{m.get('rs_ratio'):.3f}" if m.get("rs_ratio") else "-",
                "3개월수익": f"{m.get('ret_3m_pct') or 0:.1f}%",
                "Δ1d":       m.get("rank_delta_1d", "—"),
                "Δ3d":       m.get("rank_delta_3d", "—"),
                "Δ6d":       m.get("rank_delta_6d", "—"),
            } for m in top_table]
            df_top = _pd.DataFrame(rows)

            def _cdelta(v):
                s = str(v)
                if s.startswith("+"): return "color:#16a34a;font-weight:bold"
                if s.startswith("-"): return "color:#dc2626;font-weight:bold"
                return ""

            def _cscore(v):
                try:
                    fv = float(v)
                    if fv >= 80: return "background-color:#dcfce7"
                    if fv >= 50: return "background-color:#fef9c3"
                    return "background-color:#fee2e2"
                except Exception: return ""

            st.markdown(f"**Stage2 종목 {len(top_table)}개** | 분석시각: {payload.get('last_analysis_time', '-')}")
            st.dataframe(
                df_top.style
                    .applymap(_cdelta, subset=["Δ1d", "Δ3d", "Δ6d"])
                    .applymap(_cscore, subset=["점수"]),
                use_container_width=True, hide_index=True,
            )

    with tab_sector:
        sec_tbl = payload.get("sector_score_table") or []
        if not sec_tbl:
            st.info("섹터 데이터 없음")
        else:
            import pandas as _pd
            df_sec = _pd.DataFrame(sec_tbl).rename(columns={
                "sector": "섹터", "count": "종목수",
                "avg_score": "평균점수", "max_score": "최고점수",
            })
            c_left, c_right = st.columns([2, 3])
            with c_left:
                st.dataframe(df_sec, use_container_width=True, hide_index=True)
            with c_right:
                try:
                    import plotly.graph_objects as go
                    fig = go.Figure(go.Bar(
                        x=df_sec["섹터"], y=df_sec["종목수"],
                        marker_color="#0ea5e9", text=df_sec["종목수"],
                        textposition="outside",
                    ))
                    fig.update_layout(
                        title=f"섹터별 Stage2 종목 수",
                        xaxis_tickangle=-35, height=350,
                        margin=dict(t=50, b=80),
                    )
                    st.plotly_chart(fig, use_container_width=True)
                except ImportError:
                    st.bar_chart(df_sec.set_index("섹터")["종목수"])

    with tab_diff:
        added   = payload.get("last_diff_added",   [])
        removed = payload.get("last_diff_removed", [])
        baseline = payload.get("diff_baseline_date", "-")
        st.caption(f"비교 기준일: **{baseline}**")
        ca, cr = st.columns(2)
        with ca:
            st.markdown(f"#### 🟢 신규 진입 ({len(added)}개)")
            if added:
                import pandas as _pd
                st.dataframe(_pd.DataFrame([{
                    "티커": r.get("ticker",""), "종목명": r.get("name",""),
                    "섹터": r.get("sector",""), "점수": r.get("score","-"),
                } for r in added]), use_container_width=True, hide_index=True)
            else:
                st.info("없음")
        with cr:
            st.markdown(f"#### 🔴 탈락 ({len(removed)}개)")
            if removed:
                import pandas as _pd
                st.dataframe(_pd.DataFrame([{
                    "티커": r.get("ticker",""), "종목명": r.get("name",""),
                    "섹터": r.get("sector",""),
                } for r in removed]), use_container_width=True, hide_index=True)
            else:
                st.info("없음")

    with tab_charts:
        matches    = payload.get("matches", [])
        chart_items = [m for m in matches if m.get("chart")]
        if not chart_items:
            st.info("저장된 차트 없음 — 스캔 시 자동 생성됩니다.")
        else:
            all_sectors = sorted({m.get("sector", "미분류") for m in chart_items})
            sel_sector  = st.selectbox("섹터 필터", ["전체"] + all_sectors,
                                        key=f"sec_{data_dir_name}")
            filtered    = chart_items if sel_sector == "전체" \
                          else [m for m in chart_items if m.get("sector") == sel_sector]
            st.caption(f"차트 {len(filtered)}개")
            cols_per_row = 2
            for i in range(0, len(filtered), cols_per_row):
                row_items = filtered[i: i + cols_per_row]
                cols = st.columns(cols_per_row)
                for col, item in zip(cols, row_items):
                    with col:
                        chart_path = CHARTS_DIR / item["chart"]
                        caption = (
                            f"**#{item.get('rank')} {item.get('name')} ({item.get('ticker')})**  "
                            f"점수: {item.get('score', 0):.1f} | 진입: {item.get('entry', '-')} | "
                            f"경과: {item.get('bars_since_stage2_entry', '-')}봉"
                        )
                        if chart_path.exists():
                            st.image(str(chart_path), caption=caption,
                                     use_container_width=True)
                        else:
                            st.warning(f"차트 없음: {item['chart']}")


def _render_page_kosdaq() -> None:
    _render_scanner_page(
        title="📈 코스닥 Stage2 스캐너",
        data_dir_name="kosdaq_data",
        module_name="kosdaq_export_core",
        candidates_module="kosdaq_candidates",
        index_label="코스닥",
    )


def _render_page_kospi() -> None:
    _render_scanner_page(
        title="📊 코스피 Stage2 스캐너",
        data_dir_name="kospi_data",
        module_name="kospi_export_core",
        candidates_module="kospi_candidates",
        index_label="코스피",
    )


def _render_page_home() -> None:
    with _portal_page_card():
        group_labels = [lbl for lbl, _ in _HOME_GROUP_SPEC]
        group_keys   = [k   for _, k in _HOME_GROUP_SPEC]
        group_tabs   = st.tabs(group_labels)
        for idx, key in enumerate(group_keys):
            with group_tabs[idx]:
                _HOME_GROUP_DISPATCH[key]()


def _render_page_haksa() -> None:
    with _portal_page_card():
        st.header("📚 학사정보")
        st.caption("명문대·입시 참고, 초등 학부모, 예비 중등 가이드입니다.")
        ht1, ht2, ht3 = st.tabs(["🎓 명문대·입시", "📘 초등 학부모", "📙 예비 중등"])
        with ht1:
            _render_tab_edu()
        with ht2:
            _render_tab_elem()
        with ht3:
            _render_tab_mid()


def _render_page_learning_prep() -> None:
    with _portal_page_card():
        st.header("📖 학습준비")
        st.caption("방송·공교육 포털·진학 참고 링크입니다. 세부 일정은 학교·교육청 안내를 따르세요.")
        _render_curated_link_blocks(LEARNING_PREP_SITES, key_prefix="learn")


def _render_page_checklist() -> None:
    with _portal_page_card():
        st.header("✅ 필수 체크리스트")
        st.caption("체크 상태는 **이 브라우저 세션**에만 저장됩니다. 중요한 일정은 캘린더에도 적어 두세요.")
        items = PARENT_CHECKLIST_ITEMS
        n_chk_cols = 2
        for row_start in range(0, len(items), n_chk_cols):
            chunk = items[row_start : row_start + n_chk_cols]
            cols = st.columns(n_chk_cols)
            for j, row_item in enumerate(chunk):
                idx = row_start + j
                with cols[j]:
                    st.checkbox(
                        row_item["label"],
                        help=row_item.get("hint"),
                        key=f"parent_chk_{idx}",
                    )


def main() -> None:
    st.set_page_config(
        page_title="생활 정보 포털",
        page_icon="🐙",
        layout="centered",
        initial_sidebar_state="collapsed",
    )

    # 모바일 퍼스트: 어두운 배경 + 고대비 텍스트 · 터치 친화 UI
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
        -webkit-tap-highlight-color: rgba(129, 140, 248, 0.22);
        background: linear-gradient(165deg, #252448 0%, #1e1b4b 44%, #172554 100%) fixed !important;
        color: #eef2ff !important;
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
        backdrop-filter: blur(14px) !important;
        -webkit-backdrop-filter: blur(14px) !important;
        border-bottom: 1px solid rgba(165, 180, 252, 0.28) !important;
    }
    header[data-testid="stHeader"] [data-testid="stToolbar"] button { color: #e0e7ff !important; }
    /* ── 상단 그룹 탭 바: 한 줄에 모두 표시 ── */
    .stTabs [data-baseweb="tab-list"] {
        display: flex !important;
        flex-wrap: nowrap !important;
        gap: 0.25rem;
        padding: 0.35rem !important;
        background: rgba(49, 46, 129, 0.42);
        border-radius: 16px;
        overflow: visible !important;
    }
    .stTabs [data-baseweb="tab-list"] button {
        flex: 1 1 0 !important;          /* 균등 너비 */
        min-width: 0 !important;
        min-height: 3.2rem !important;
        padding: 0.45rem 0.3rem !important;
        font-size: clamp(0.78rem, 3vw, 0.95rem) !important;
        line-height: 1.3 !important;
        border-radius: 12px !important;
        color: #e0e7ff !important;
        background: rgba(255, 255, 255, 0.07) !important;
        border: 1px solid rgba(165, 180, 252, 0.22) !important;
        white-space: normal !important;
        word-break: keep-all !important;
        text-align: center !important;
        transition: background 0.15s ease;
    }
    .stTabs [data-baseweb="tab-list"] button[aria-selected="true"] {
        background: linear-gradient(165deg, #6366f1 0%, #4f46e5 100%) !important;
        color: #fafaff !important;
        border-color: rgba(199, 210, 254, 0.6) !important;
        font-weight: 700 !important;
        box-shadow: 0 4px 14px rgba(99, 102, 241, 0.45) !important;
    }
    /* ── 서브 탭 (탭 안의 탭): 가로 스크롤 허용 ── */
    .stTabs .stTabs [data-baseweb="tab-list"] {
        background: rgba(30, 27, 75, 0.5);
        border-radius: 10px;
        padding: 0.25rem !important;
        flex-wrap: nowrap !important;
        overflow-x: auto !important;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
    }
    .stTabs .stTabs [data-baseweb="tab-list"]::-webkit-scrollbar { display: none; }
    .stTabs .stTabs [data-baseweb="tab-list"] button {
        flex: 1 1 auto !important;
        min-width: max-content !important;
        min-height: 2.7rem !important;
        padding: 0.4rem 0.9rem !important;
        font-size: clamp(0.85rem, 3.2vw, 0.97rem) !important;
        border-radius: 8px !important;
        white-space: nowrap !important;
    }
    /* ── 메트릭 카드 ── */
    div[data-testid="stMetric"] {
        background: linear-gradient(160deg, #433d8b 0%, #3730a3 100%) !important;
        border: 1px solid rgba(165, 180, 252, 0.35) !important;
        border-radius: 16px !important;
        box-shadow: 0 6px 20px rgba(30, 27, 75, 0.42) !important;
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
        background: linear-gradient(165deg, rgba(79, 70, 229, 0.28) 0%, rgba(49, 46, 129, 0.88) 100%) !important;
        border: 1px solid rgba(165, 180, 252, 0.38) !important;
        border-radius: 18px !important;
        box-shadow: 0 10px 32px rgba(30, 27, 75, 0.42), inset 0 1px 0 rgba(255,255,255,0.06) !important;
        padding: 1rem 1rem 1.2rem !important;
        margin-bottom: 0.75rem !important;
        border-left: 3px solid rgba(129, 140, 248, 0.65) !important;
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
            min-height: 2.9rem !important;
            padding: 0.35rem 0.2rem !important;
            font-size: clamp(0.72rem, 2.8vw, 0.88rem) !important;
        }
        div[data-testid="stMetric"] { padding: 0.8rem !important; }
    }
</style>
        """,
        unsafe_allow_html=True,
    )

    selected = _sidebar_nav_select()
    _sidebar_travel_country_picker(selected)

    if selected == "홈":
        st.title(APP_DISPLAY_TITLE)
        _render_page_home()
    elif selected == "코스닥 스캐너":
        _render_page_kosdaq()
    elif selected == "코스피 스캐너":
        _render_page_kospi()
    elif selected == "학사정보":
        _render_page_haksa()
    elif selected == "학습준비":
        _render_page_learning_prep()
    else:
        _render_page_checklist()

if __name__ == "__main__":
    main()

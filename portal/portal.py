from flask import Flask, Response
import time
import datetime
import os
app = Flask(__name__)

# --- 배포용 설정 ( Synology / Docker / 리버스 프록시에서도 조정 ) ---
# 기본: edu.junna3d.i234.me (DNS는 대소문자 무시 — URL에는 소문자 권장)
def _env_bool(key: str, default: str = "1") -> bool:
    return os.environ.get(key, default).strip().lower() in ("1", "true", "yes", "on")


def _base_url() -> str:
    """
    절대 URL prefix. 풀URL을 쓰면 서브도메인·포트·경로를 한 번에 맞출 수 있음.
    예: https://junna3d.i234.me  또는 http (내부망·자체서명)
    """
    full = (os.environ.get("PORTAL_BASE_URL") or "").strip().rstrip("/")
    if full:
        return full
    domain = (os.environ.get("PORTAL_BASE_DOMAIN") or "junna3d.i234.me").strip().lower()
    scheme = "https" if _env_bool("PORTAL_HTTPS", "1") else "http"
    return f"{scheme}://{domain}"


def _service_url(subdomain: str) -> str:
    """{sub}.junna3d... 형태. 루트가 아닌 path가 필요하면 PORTAL_OVERRIDES_* 사용."""
    return f"{_base_url().replace('://', f'://{subdomain}.', 1)}"


def _url_or_override(env_key: str, subdomain: str) -> str:
    override = (os.environ.get(env_key) or "").strip()
    if override:
        return override.rstrip("/")
    return _service_url(subdomain)


@app.route("/")
def index():
    base = _base_url()
    domain_from_base = base.split("://", 1)[-1] if "://" in base else "junna3d.i234.me"

    # 브라우저 캐시 방지
    nocache = int(time.time())
    v = f"?v={nocache}"

    def with_cache(u: str) -> str:
        return u if "?" in u else f"{u}{v}"

    # 개별 오버라이드(역프록시 뒤 포트·path 다를 때)
    # 예: EDU_URL=https://edu.junna3d.i234.me:5002
    url_kospi = with_cache(_url_or_override("KOSPI_URL", "stock"))
    url_kosdaq = with_cache(_url_or_override("KOSDAQ_URL", "stock2"))
    url_us = with_cache(_url_or_override("US_URL", "us"))
    url_apt = with_cache(_url_or_override("APT_URL", "apt"))
    url_other = with_cache(_url_or_override("OTHER_URL", "other"))
    url_edu = with_cache(_url_or_override("EDU_URL", "edu"))
    # OPIC: 기본 https://opic.<도메인> (EDU와 동일 패턴). 포트만 쓰면 OPIC_URL=http://IP:8508
    url_opic = with_cache(_url_or_override("OPIC_URL", "opic"))
    # Streamlit 생활정보(날씨·에이전트): 기본 https://life.<도메인> — NAS 직접 포트면 STREAMLIT_URL=http://IP:8509
    url_streamlit = with_cache(_url_or_override("STREAMLIT_URL", "life"))

    # 디버그: 포털이 어떤 base로 링크를 찍는지(문제 잡을 때)
    if _env_bool("PORTAL_DEBUG_LINKS", "0"):
        lines = [
            f"PORTAL_BASE_URL / PORTAL_BASE_DOMAIN → effective base: {base}",
            f"EDU link → {url_edu.split('?')[0]}",
            f"OPIC link → {url_opic.split('?')[0]}",
            f"Streamlit link → {url_streamlit.split('?')[0]}",
        ]
        return Response("\n".join(lines), mimetype="text/plain; charset=utf-8")

    html = f"""
    <!DOCTYPE html>
    <html lang="ko">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
        <title>JUNNA3D Intelligence Portal</title>
        <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.0.0/css/all.min.css" rel="stylesheet">
        <style>
            @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.8/dist/web/static/pretendard.css");

            :root {{
                --bg: #F2F4F6;
                --primary: #191F28;
                --blue: #3182F6;
                --green: #00D084;
                --red: #F04452;
                --indigo: #6366F1;
                --orange: #FF9500;
                --shadow: 0 8px 24px rgba(0,0,0,0.07);
            }}

            body {{
                font-family: 'Pretendard Variable', -apple-system, sans-serif;
                background-color: var(--bg);
                margin: 0; padding: 0;
                display: flex; flex-direction: column; align-items: center;
                color: var(--primary);
                word-break: keep-all;
            }}

            header {{
                background: white;
                width: 100%;
                padding: 60px 20px;
                text-align: center;
                border-bottom: 1px solid #E5E8EB;
            }}

            header h1 {{ font-size: 1.6rem; font-weight: 850; margin: 0; letter-spacing: -1px; }}
            header p {{ color: #8B95A1; font-size: 1rem; margin-top: 10px; font-weight: 500; }}

            .container {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
                gap: 20px;
                max-width: 1100px;
                width: 90%;
                margin: 40px 0;
            }}

            .card {{
                background: white;
                border-radius: 28px;
                padding: 40px 30px;
                text-decoration: none;
                color: inherit;
                transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
                box-shadow: var(--shadow);
                display: flex;
                flex-direction: column;
                position: relative;
                border: 1px solid rgba(0,0,0,0.02);
            }}

            .card:hover {{ transform: translateY(-5px); box-shadow: 0 12px 30px rgba(0,0,0,0.1); }}
            .card:active {{ transform: scale(0.97); }}

            .icon-box {{
                width: 60px; height: 60px;
                border-radius: 20px;
                display: flex; align-items: center; justify-content: center;
                font-size: 1.8rem; margin-bottom: 24px;
            }}

            .icon-kospi {{ background: #E8F3FF; color: var(--blue); }}
            .icon-kosdaq {{ background: #E7F9F0; color: var(--green); }}
            .icon-apt {{ background: #F4F4FF; color: var(--indigo); }}
            .icon-us {{ background: #FFF0F0; color: var(--red); }}
            .icon-other {{ background: #F0F4FF; color: var(--indigo); }}
            .icon-edu {{ background: #E8F4FD; color: #0B6BCB; }}
            .icon-opic {{ background: #EDF6F1; color: #2A9D6E; }}
            .icon-life {{ background: #E8F6FC; color: #0EA5E9; }}

            .card h2 {{ margin: 0; font-size: 1.4rem; font-weight: 800; letter-spacing: -0.5px; }}
            .card p {{ color: #4E5968; font-size: 1rem; line-height: 1.6; margin: 12px 0 24px; }}

            .go-btn {{
                font-size: 0.95rem; font-weight: 700; color: var(--blue);
                display: flex; align-items: center; gap: 6px; margin-top: auto;
            }}

            .domain-hint {{ font-size: 0.78rem; color: #8B95A1; margin-top: 4px; word-break: break-all; }}
            footer {{ margin-top: auto; padding: 60px 20px; text-align: center; color: #ADB5BD; font-size: 0.85rem; line-height: 1.8; }}
        </style>
    </head>
    <body>
        <header>
            <h1>JUNNA3D Intelligence</h1>
            <p>글로벌 마켓 및 스마트 라이프 통합 관제 포털</p>
        </header>

        <div class="container">
            <a href="{url_kospi}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-kospi"><i class="fas fa-landmark"></i></div>
                <h2>KOSPI 우량주</h2>
                <p>국내 시총 상위 50대 기업<br>추세 추종 4단계 집중 분석</p>
                <div class="go-btn">리포트 진입 <i class="fas fa-chevron-right"></i></div>
            </a>

            <a href="{url_kosdaq}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-kosdaq"><i class="fas fa-rocket"></i></div>
                <h2>KOSDAQ 주도주</h2>
                <p>코스닥 수급 핵심 종목 및<br>기술적 반등 구간 실시간 탐색</p>
                <div class="go-btn" style="color: var(--green);">리포트 진입 <i class="fas fa-chevron-right"></i></div>
            </a>

            <a href="{url_us}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-us"><i class="fas fa-flag-usa"></i></div>
                <h2>S&amp;P 500 TECH</h2>
                <p>미국 빅테크 및 반도체 섹터<br>200일선 상승 추세 종목 포착</p>
                <div class="go-btn" style="color: var(--red);">US 마켓 진입 <i class="fas fa-chevron-right"></i></div>
            </a>

            <a href="{url_apt}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-apt"><i class="fas fa-city"></i></div>
                <h2>부동산 사이클</h2>
                <p>수도권 1,000세대 이상 대단지<br>억 단위 실거래가 추세 리포트</p>
                <div class="go-btn" style="color: var(--indigo);">트렌드 진입 <i class="fas fa-chevron-right"></i></div>
            </a>

            <a href="{url_other}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-other"><i class="fas fa-bolt"></i></div>
                <h2>급등주 검색기</h2>
                <p>모든 종목에서 검색<br>코스피·코스닥 우량주 제외</p>
                <div class="go-btn" style="color: var(--orange);">검색기 열기 <i class="fas fa-chevron-right"></i></div>
            </a>

            <a href="{url_edu}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-edu"><i class="fas fa-graduation-cap"></i></div>
                <h2>교육 / EDU</h2>
                <p>Stage2·학군 대시보드 등<br>교육·분석용 서비스 (edu 서브도메인)</p>
                <div class="go-btn" style="color: #0B6BCB;">EDU 열기 <i class="fas fa-chevron-right"></i></div>
                <div class="domain-hint">링크: {url_edu.split("?")[0]}</div>
            </a>

            <a href="{url_opic}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-opic"><i class="fas fa-language"></i></div>
                <h2>OPIC 2급 암기</h2>
                <p>정적 웹(질문 카드·문장 암기)<br>기본: opic 서브도메인 (역프록시·8508은 NAS에서 연결)</p>
                <div class="go-btn" style="color: #2A9D6E;">OPIC 열기 <i class="fas fa-chevron-right"></i></div>
                <div class="domain-hint">링크: {url_opic.split("?")[0]}</div>
            </a>

            <a href="{url_streamlit}" class="card" rel="noopener noreferrer" target="_blank">
                <div class="icon-box icon-life"><i class="fas fa-cloud-sun"></i></div>
                <h2>생활 정보 · 날씨</h2>
                <p>Streamlit 대시보드 (지역 날씨·5일 예보·채팅 에이전트)<br>NAS 기본 포트 8509 · 역프록시 시 life 서브도메인</p>
                <div class="go-btn" style="color: #0EA5E9;">열기 <i class="fas fa-chevron-right"></i></div>
                <div class="domain-hint">링크: {url_streamlit.split("?")[0]} · 오버라이드: STREAMLIT_URL</div>
            </a>

        </div>

        <footer>
            &copy; {datetime.datetime.now().year} JUNNA3D LAB. All rights reserved.<br>
            <span style="font-size: 0.75rem; opacity: 0.8;">Data Processing &amp; Cloud System based on Synology Docker</span><br>
            <span style="font-size: 0.7rem; opacity: 0.7;">Base: {domain_from_base} · EDU: EDU_URL · OPIC: OPIC_URL · Streamlit: STREAMLIT_URL (미설정 시 life.&lt;도메인&gt;, 포트 8509)</span>
        </footer>
    </body>
    </html>
    """
    return html


if __name__ == "__main__":
    # 포털 통합 관제 포트: 8500
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8500")))

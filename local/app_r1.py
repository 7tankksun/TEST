"""
로컬 올인원: 분석 실행 + 웹 (개발/확인용).
운영 분리 시: 스케줄은 run_local_export.py, NAS는 app_nas_serve.py 만 사용.
"""

import os
import datetime

from flask import Flask, send_file, render_template_string, abort

from analysis_core import DISPLAY, run_analysis_export, load_display_from_export
from web_templates import INDEX_HTML

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "charts")


def _render_index(show_rerun: bool, mode_label: str, footer_note: str):
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    matches = DISPLAY.get("matches", [])
    sector_blocks = DISPLAY.get("sector_blocks", [])
    sector_summary = DISPLAY.get("sector_summary", [])
    return render_template_string(
        INDEX_HTML,
        now=now,
        mode_label=mode_label,
        matches=matches,
        sector_blocks=sector_blocks,
        sector_summary=sector_summary,
        last_analysis_time=DISPLAY.get("last_analysis_time"),
        candidate_count=DISPLAY.get("candidate_count", 0),
        last_diff_added=DISPLAY.get("last_diff_added", []),
        last_diff_removed=DISPLAY.get("last_diff_removed", []),
        show_rerun=show_rerun,
        scoring=DISPLAY.get("scoring"),
        sector_score_table=DISPLAY.get("sector_score_table", []),
        top_table=DISPLAY.get("top_table", []),
        footer_note=footer_note,
    )


@app.route("/")
def index():
    return _render_index(
        show_rerun=True,
        mode_label="(app_r1 로컬)",
        footer_note="NAS만 쓰려면 run_local_export.py → nas_web_payload 동기화 → app_nas_serve.py",
    )


@app.route("/run-analysis")
def run_analysis():
    run_analysis_export(BASE_DIR)
    return (
        '<meta http-equiv="refresh" content="0; url=/" />'
        "분석 완료. 잠시 후 메인 화면으로 이동합니다."
    )


@app.route("/image/<filename>")
def get_image(filename):
    path = os.path.join(SAVE_DIR, filename)
    if filename != os.path.basename(filename) or ".." in filename or not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png")


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5001"))

    if os.environ.get("SKIP_ANALYSIS_ON_START") == "1":
        load_display_from_export(BASE_DIR)
        print("[시작] SKIP_ANALYSIS_ON_START=1 → 기존 results_web.json 만 로드")
    else:
        print(f"[시작] 후보 전체 분석 → {BASE_DIR}")
        run_analysis_export(BASE_DIR)

    print(f"[완료] http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)

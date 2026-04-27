import os
import datetime

from flask import Flask, send_file, render_template_string, abort

from candidates_data import CANDIDATES
from analysis_core import DISPLAY, run_analysis_export
from web_templates import INDEX_HTML

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "charts")
last_analysis_time = None

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)


def run_analysis_task():
    global last_analysis_time
    run_analysis_export(BASE_DIR)
    last_analysis_time = DISPLAY.get("last_analysis_time")
    return DISPLAY.get("matches", [])


@app.route("/")
def index():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return render_template_string(
        INDEX_HTML,
        now=now,
        mode_label="(app.py)",
        matches=DISPLAY.get("matches", []),
        sector_blocks=DISPLAY.get("sector_blocks", []),
        sector_summary=DISPLAY.get("sector_summary", []),
        last_analysis_time=DISPLAY.get("last_analysis_time"),
        candidate_count=DISPLAY.get("candidate_count", len(CANDIDATES)),
        last_diff_added=DISPLAY.get("last_diff_added", []),
        last_diff_removed=DISPLAY.get("last_diff_removed", []),
        show_rerun=True,
        scoring=DISPLAY.get("scoring"),
        sector_score_table=DISPLAY.get("sector_score_table", []),
        top_table=DISPLAY.get("top_table", []),
        footer_note="운영은 run_local_export.py + app_nas_serve 권장",
    )


@app.route("/run-analysis")
def run_analysis():
    run_analysis_task()
    return (
        '<meta http-equiv="refresh" content="0; url=/" />'
        "분석 완료. 잠시 후 메인 화면으로 이동합니다."
    )


@app.route("/image/<filename>")
def get_image(filename):
    if filename != os.path.basename(filename) or ".." in filename:
        abort(400)
    path = os.path.join(SAVE_DIR, filename)
    if not os.path.isfile(path):
        abort(404)
    return send_file(path, mimetype="image/png")


if __name__ == "__main__":
    print(f"[시작] 후보 {len(CANDIDATES)}개 전체 분석 후 결과 저장, 그다음 웹을 띄웁니다.")
    print("(시간이 매우 오래 걸릴 수 있습니다. 중단하려면 Ctrl+C)")
    run_analysis_task()
    print("[완료] 브라우저에서 http://127.0.0.1:5000 을 여세요.")
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False)

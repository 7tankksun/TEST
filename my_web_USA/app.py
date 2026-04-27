import os
import datetime
import time
from flask import Flask, send_file, render_template_string

from usa_candidates import CANDIDATES
from usa_export_core import run_usa_export

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SAVE_DIR = os.path.join(BASE_DIR, "charts")
os.makedirs(SAVE_DIR, exist_ok=True)

signal_times = {}


def run_analysis_task():
    """BASE_DIR에 charts/·state/·results_web.json (run_local_export와 동일 루트 구조)."""
    global signal_times
    print(f"[{datetime.datetime.now()}] US Stage2 export…")
    payload = run_usa_export(BASE_DIR)
    signal_times = {m["ticker"]: m.get("entry", "") for m in payload.get("matches", [])}
    print(f"[{datetime.datetime.now()}] Done. Stage2 count: {len(signal_times)}")


@app.route("/")
def index():
    sector_groups = {}
    for ticker in signal_times.keys():
        name, sector = CANDIDATES[ticker]
        if sector not in sector_groups:
            sector_groups[sector] = []
        sector_groups[sector].append(name)

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    nocache = int(time.time())

    summary_html = ""
    for sector, names in sector_groups.items():
        summary_html += f"""
            <tr>
                <td style="padding:12px; border-bottom:1px solid #EEE;"><b>{sector}</b></td>
                <td style="padding:12px; border-bottom:1px solid #EEE; text-align:center;"><span style="background:#3182F6; color:white; padding:2px 8px; border-radius:5px;">{len(names)}</span></td>
                <td style="padding:12px; border-bottom:1px solid #EEE; color:#666; font-size:0.9rem;">{", ".join(names)}</td>
            </tr>"""

    chart_html = ""
    for ticker in signal_times.keys():
        chart_html += f"""
        <div style="background:white; margin-bottom:20px; padding:20px; border-radius:15px; box-shadow:0 2px 10px rgba(0,0,0,0.05);">
            <h3>{CANDIDATES[ticker][0]} ({ticker})</h3>
            <img src="/image/{ticker}_trend.png?v={nocache}" style="width:100%;">
        </div>"""

    return render_template_string(
        f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <style>
            body {{ font-family: sans-serif; background:#F5F7F9; padding:20px; }}
            .container {{ max-width: 900px; margin: auto; }}
            table {{ width:100%; border-collapse:collapse; background:white; border-radius:10px; overflow:hidden; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>US Stocks · Stage 2 ({now_str})</h1>
            <p style="color:#666;font-size:0.9rem;">NAS: <code>run_local_export.py</code> → <code>app_nas_serve_usa.py</code> (port 8504)</p>
            <div style="background:white; padding:20px; border-radius:15px; margin-bottom:30px;">
                <h2 style="margin-top:0;">By sector</h2>
                <table>
                    <tr style="background:#F9FAFB;"><th>Sector</th><th>Count</th><th>Names</th></tr>
                    {summary_html if summary_html else "<tr><td colspan='3' style='padding:20px; text-align:center;'>No matches.</td></tr>"}
                </table>
            </div>
            {chart_html}
        </div>
    </body>
    </html>"""
    )


@app.route("/image/<filename>")
def get_image(filename):
    return send_file(os.path.join(SAVE_DIR, filename), mimetype="image/png")


if __name__ == "__main__":
    run_analysis_task()
    app.run(host="0.0.0.0", port=8504)

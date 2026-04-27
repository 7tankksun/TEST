"""
NAS 전용: results_web.json + charts/ 만 읽어 웹 표시.

- Synology Drive로 파일이 늦게 들어와도, 요청마다 경로를 다시 탐색합니다.
- PNG는 /app/charts, nas_web_payload/charts 등 후보를 순서대로 찾습니다.
"""

import json
import os
import datetime

from flask import Flask, send_file, render_template_string, abort

from web_templates import INDEX_HTML

HERE = os.path.dirname(os.path.abspath(__file__))

app = Flask(__name__)


def _result_json_candidates():
    pd = os.environ.get("PAYLOAD_DIR")
    c = []
    if pd:
        c.append(os.path.join(pd, "results_web.json"))
        c.append(os.path.join(pd, "nas_web_payload", "results_web.json"))
    c.append(os.path.join(HERE, "results_web.json"))
    c.append(os.path.join(HERE, "nas_web_payload", "results_web.json"))
    return c


def _chart_dir_candidates(results_path):
    """이미지 검색 순서 (앞에 올수록 우선)."""
    pd = os.environ.get("PAYLOAD_DIR")
    out = []
    if results_path:
        out.append(os.path.join(os.path.dirname(results_path), "charts"))
    out.append(os.path.join(HERE, "charts"))
    out.append(os.path.join(HERE, "nas_web_payload", "charts"))
    if pd:
        out.append(os.path.join(pd, "charts"))
        out.append(os.path.join(pd, "nas_web_payload", "charts"))
    # 중복 제거(순서 유지)
    seen = set()
    uniq = []
    for p in out:
        ap = os.path.abspath(p)
        if ap not in seen:
            seen.add(ap)
            uniq.append(p)
    return uniq


def resolve_results_path():
    for p in _result_json_candidates():
        if os.path.isfile(p):
            return p
    return None


def resolve_chart_roots():
    """실제 존재하는 charts 디렉터리만 리스트로."""
    roots = []
    res = resolve_results_path()
    for d in _chart_dir_candidates(res):
        if os.path.isdir(d):
            roots.append(d)
    return roots, res


def _read_payload():
    path = resolve_results_path()
    if not path:
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _prepare_index_view(data: dict) -> dict:
    """점수순 정렬, 섹터 요약·상위표·차트용 sector_blocks 보강(구 JSON 호환)."""
    matches = sorted(
        list(data.get("matches") or []),
        key=lambda x: (-float(x.get("score") or 0), x.get("ticker") or ""),
    )
    sector_score_table = data.get("sector_score_table")
    top_table = data.get("top_table")
    try:
        from analysis_core import sector_blocks_charts_only, sector_score_table_from_matches

        if not sector_score_table:
            sector_score_table = sector_score_table_from_matches(matches)
        if not top_table:
            n = int((data.get("scoring") or {}).get("summary_table_rows") or 50)
            top_table = matches[: max(1, n)]
        sector_blocks = sector_blocks_charts_only(matches)
        sector_summary = [(r["sector"], r["count"]) for r in sector_score_table]
    except Exception:
        sector_score_table = sector_score_table or []
        top_table = top_table or matches[:50]
        sector_blocks = data.get("sector_blocks") or []
        sector_summary = data.get("sector_summary") or []
    for i, m in enumerate(matches, 1):
        m["rank"] = int(i)
    t_rank = {m.get("ticker"): m.get("rank") for m in matches if m.get("ticker")}
    for r in top_table or []:
        tid = r.get("ticker")
        if tid and tid in t_rank:
            r["rank"] = t_rank[tid]
    return {
        "matches": matches,
        "sector_score_table": sector_score_table,
        "top_table": top_table,
        "sector_blocks": sector_blocks,
        "sector_summary": sector_summary,
    }


@app.route("/")
def index():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chart_roots, json_path = resolve_chart_roots()
    data = _read_payload()
    if not data:
        data = {
            "last_analysis_time": None,
            "candidate_count": 0,
            "matches": [],
            "sector_blocks": [],
            "sector_summary": [],
            "sector_score_table": [],
            "top_table": [],
            "last_diff_added": [],
            "last_diff_removed": [],
            "scoring": None,
        }
    v = _prepare_index_view(data)
    roots_display = ", ".join(chart_roots) if chart_roots else "(charts 폴더 없음)"
    return render_template_string(
        INDEX_HTML,
        now=now,
        mode_label="(NAS · 읽기 전용)",
        matches=v["matches"],
        sector_blocks=v["sector_blocks"],
        sector_summary=v["sector_summary"],
        sector_score_table=v["sector_score_table"],
        top_table=v["top_table"],
        last_analysis_time=data.get("last_analysis_time"),
        candidate_count=data.get("candidate_count", 0),
        last_diff_added=data.get("last_diff_added", []),
        last_diff_removed=data.get("last_diff_removed", []),
        show_rerun=False,
        scoring=data.get("scoring"),
        footer_note=(
            "로컬 run_local_export.py → Drive 동기화 후 새로고침. "
            f"JSON: {json_path or '(아직 없음 — 동기화 대기)'} | charts 후보: {roots_display}"
        ),
    )


@app.route("/image/<filename>")
def get_image(filename):
    if filename != os.path.basename(filename) or ".." in filename:
        abort(400)
    for base in resolve_chart_roots()[0]:
        path = os.path.join(base, filename)
        if os.path.isfile(path):
            return send_file(path, mimetype="image/png")
    roots, _ = resolve_chart_roots()
    app.logger.warning("[NAS] PNG 없음: %s (검색: %s)", filename, roots)
    abort(404)


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "5001"))
    roots, jr = resolve_chart_roots()
    print(f"[NAS] RESULTS_JSON_PATH = {jr}")
    print(f"[NAS] chart roots         = {roots}")
    print(f"[NAS] http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)

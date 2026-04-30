"""
NAS: results_web.json + charts/ 만 읽어 US Stage2 웹.
  FLASK_HOST / FLASK_PORT (기본 8504) · PAYLOAD_DIR
"""

import json
import os
import sys
import datetime

from flask import Flask, send_file, render_template_string, abort

HERE = os.path.dirname(os.path.abspath(__file__))


def _ensure_web_templates_path():
    candidates = [HERE, os.path.normpath(os.path.join(HERE, "..", "local"))]
    for d in candidates:
        if os.path.isfile(os.path.join(d, "web_templates.py")):
            if d not in sys.path:
                sys.path.insert(0, d)
            return
    raise ImportError("web_templates.py not found next to this script.")


_ensure_web_templates_path()

from web_templates import INDEX_HTML  # noqa: E402

app = Flask(__name__)


def _result_json_candidates():
    pd = os.environ.get("PAYLOAD_DIR")
    c = []
    if pd:
        c.append(os.path.join(pd, "results_web.json"))
        c.append(os.path.join(pd, "nas_web_payload", "results_web.json"))
    c.append(os.path.join(HERE, "nas_web_payload", "results_web.json"))
    c.append(os.path.join(HERE, "results_web.json"))
    return c


def _chart_dir_candidates(results_path):
    pd = os.environ.get("PAYLOAD_DIR")
    out = []
    if results_path:
        out.append(os.path.join(os.path.dirname(results_path), "charts"))
    out.append(os.path.join(HERE, "charts"))
    out.append(os.path.join(HERE, "nas_web_payload", "charts"))
    if pd:
        out.append(os.path.join(pd, "charts"))
        out.append(os.path.join(pd, "nas_web_payload", "charts"))
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


def _sector_score_table_from_matches(matches: list) -> list:
    buckets: dict[str, list[float]] = {}
    for m in matches:
        sec = (m.get("sector") or "—").strip() or "—"
        buckets.setdefault(sec, []).append(float(m.get("score") or 0))
    rows = []
    for sec, scores in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
        rows.append(
            {
                "sector": sec,
                "count": len(scores),
                "avg_score": round(sum(scores) / len(scores), 2),
                "max_score": round(max(scores), 2),
            }
        )
    return rows


def _sector_blocks_charts_only(matches: list) -> list:
    from collections import OrderedDict

    charts = [m for m in matches if m.get("chart")]
    groups = OrderedDict()
    for m in charts:
        sec = m.get("sector") or "—"
        groups.setdefault(sec, []).append(m)
    for sec in groups:
        groups[sec].sort(key=lambda x: (-x.get("score", 0), x.get("ticker", "")))
    blocks = [
        {"sector": sec, "entries": items}
        for sec, items in sorted(groups.items(), key=lambda kv: len(kv[1]), reverse=True)
    ]
    return blocks


def _prepare_index_view(data: dict) -> dict:
    matches = sorted(
        list(data.get("matches") or []),
        key=lambda x: (-float(x.get("score") or 0), x.get("ticker") or ""),
    )
    sector_score_table = data.get("sector_score_table")
    top_table = data.get("top_table")
    if not sector_score_table:
        sector_score_table = _sector_score_table_from_matches(matches)
    if not top_table:
        n = int((data.get("scoring") or {}).get("summary_table_rows") or 50)
        top_table = matches[: max(1, n)]
    sector_blocks = data.get("sector_blocks") or _sector_blocks_charts_only(matches)
    sector_summary = [(r["sector"], r["count"]) for r in sector_score_table]
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


@app.route("/health")
def health():
    roots, jr = resolve_chart_roots()
    return (f"ok usa-nas json={jr or 'none'} charts={roots}", 200, {"Content-Type": "text/plain; charset=utf-8"})


@app.route("/")
def index():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    chart_roots, json_path = resolve_chart_roots()
    data = _read_payload()
    if not data:
        data = {
            "last_analysis_time": None,
            "index": None,
            "candidate_count": 0,
            "matches": [],
            "sector_blocks": [],
            "sector_summary": [],
            "sector_score_table": [],
            "top_table": [],
            "last_diff_added": [],
            "last_diff_removed": [],
            "diff_snapshot_date": None,
            "diff_baseline_date": None,
            "diff_past_days": [],
            "scoring": None,
        }
    v = _prepare_index_view(data)
    roots_display = ", ".join(chart_roots) if chart_roots else "(no charts dir)"
    return render_template_string(
        INDEX_HTML,
        now=now,
        mode_label="(NAS US · read-only)",
        index=data.get("index"),
        matches=v["matches"],
        sector_blocks=v["sector_blocks"],
        sector_summary=v["sector_summary"],
        sector_score_table=v["sector_score_table"],
        top_table=v["top_table"],
        last_analysis_time=data.get("last_analysis_time"),
        candidate_count=data.get("candidate_count", 0),
        last_diff_added=data.get("last_diff_added", []),
        last_diff_removed=data.get("last_diff_removed", []),
        diff_snapshot_date=data.get("diff_snapshot_date"),
        diff_baseline_date=data.get("diff_baseline_date"),
        diff_past_days=data.get("diff_past_days") or [],
        show_rerun=False,
        scoring=data.get("scoring"),
        footer_note=(
            "PC: my_web_USA/run_local_export.py then sync. "
            f"JSON: {json_path or '(none)'} | charts: {roots_display}"
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
    app.logger.warning("[NAS US] missing PNG: %s (tried: %s)", filename, roots)
    abort(404)


if __name__ == "__main__":
    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "8504"))
    roots, jr = resolve_chart_roots()
    print(f"[NAS US] RESULTS_JSON_PATH = {jr}")
    print(f"[NAS US] chart roots         = {roots}")
    print(f"[NAS US] http://{host}:{port}")
    app.run(host=host, port=port, debug=False, use_reloader=False)

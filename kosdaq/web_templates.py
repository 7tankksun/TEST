"""Flask `render_template_string`용 공통 HTML (로컬 app_r1 / NAS app_nas_serve 공용)."""

INDEX_HTML = """
    <!doctype html>
    <html lang="ko">
    <head>
      <meta charset="utf-8" />
      <title>Stage 2 스캔 결과</title>
      <style>
        body { font-family: "Malgun Gothic", Arial, sans-serif; margin: 24px; background: #f7f8fa; }
        .wrap { max-width: 1280px; margin: 0 auto; }
        h1 { margin-top: 0; }
        .meta { color: #555; margin-bottom: 12px; line-height: 1.6; }
        .pill-wrap { display: flex; flex-wrap: wrap; gap: 8px; margin: 16px 0; }
        .pill { background: #1a5fb4; color: #fff; padding: 6px 12px; border-radius: 20px; font-size: 0.9rem; }
        .pill small { opacity: 0.9; }
        .diff { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 24px; }
        @media (max-width: 900px) { .diff { grid-template-columns: 1fr; } }
        .diff-box { background: #fff; border-radius: 10px; padding: 14px; border: 1px solid #ddd; }
        .diff-box h2 { margin: 0 0 10px 0; font-size: 1.05rem; }
        .diff-box.add h2 { color: #0a6e0a; }
        .diff-box.drop h2 { color: #a30f0f; }
        .diff-box ul { margin: 0; padding-left: 18px; }
        .diff-box li { margin: 4px 0; }
        .sector { margin-top: 28px; }
        .sector h2 { font-size: 1.1rem; color: #333; border-bottom: 2px solid #1a5fb4; padding-bottom: 6px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 14px; margin-top: 12px; }
        .card { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 10px; }
        .card h3 { margin: 0 0 6px 0; font-size: 0.95rem; }
        .card .sec { font-size: 0.8rem; color: #666; margin-bottom: 6px; }
        .card img { width: 100%; border-radius: 6px; border: 1px solid #eee; }
        .btn { display: inline-block; margin-top: 12px; margin-right: 8px; text-decoration: none;
               padding: 8px 12px; border: 1px solid #888; border-radius: 6px; color: #222; background: #fafafa; }
        .empty { background: #fff; padding: 20px; border-radius: 8px; border: 1px dashed #bbb; color: #666; }
        .note { font-size: 0.85rem; color: #777; margin-top: 16px; }
        .summary { background: #fff; border: 1px solid #ddd; border-radius: 10px; padding: 16px; margin-bottom: 20px; }
        .summary h2 { margin: 0 0 12px 0; font-size: 1.1rem; color: #222; }
        .summary h3 { margin: 18px 0 8px 0; font-size: 0.98rem; color: #444; }
        .sum-table-wrap { overflow-x: auto; margin-top: 8px; }
        .sum-table { width: 100%; border-collapse: collapse; font-size: 0.88rem; }
        .sum-table th, .sum-table td { border: 1px solid #ddd; padding: 8px 10px; text-align: left; }
        .sum-table th { background: #f0f4fa; color: #333; }
        .sum-table td.num { text-align: right; font-variant-numeric: tabular-nums; }
        .sum-table tr:nth-child(even) { background: #fafbfc; }
        .chart-section-title { margin-top: 28px; font-size: 1.15rem; color: #333; }
        .index-banner { margin: 0 0 16px 0; padding: 12px 14px; border-radius: 8px; font-size: 0.95rem; line-height: 1.5; }
        .index-banner .ib-title { font-weight: 700; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.04em; margin-bottom: 4px; opacity: 0.85; }
        .index-banner .ib-sub { font-size: 0.8rem; opacity: 0.8; margin-top: 4px; }
        .ib-stage2 { background: #e8f5e9; border: 1px solid #1b5e20; color: #1b5e20; }
        .ib-bear { background: #ffebee; border: 1px solid #b71c1c; color: #7f1010; }
        .ib-caution { background: #fff3e0; border: 1px solid #e65100; color: #8a4800; }
        .ib-weak { background: #f0f0f0; border: 1px solid #9e9e9e; color: #444; }
        .ib-unknown { background: #f5f5f5; border: 1px solid #ccc; color: #555; }
      </style>
    </head>
    <body>
      <div class="wrap">
        <h1>Stage 2 스캔 결과 <small style="color:#888">{{ mode_label }}</small></h1>
        {% if index and index.get('headline') %}
        <div class="index-banner ib-{{ index.get('tone') or 'unknown' }}">
          <div class="ib-title">시장 지수 (스탠·와인슈타인: 2단계가 우선)</div>
          <div>{{ index.headline }}</div>
          {% if index.as_of %}
          <div class="ib-sub">봉 기준일 {{ index.as_of }}{% if index.last_close is not none %} · 종가 {{ index.last_close }}{% endif %}{% if index.ma50 is not none %} · MA50 {{ index.ma50 }}{% endif %}{% if index.ma200 is not none %} · MA200 {{ index.ma200 }}{% endif %}</div>
          {% endif %}
        </div>
        {% else %}
        <div class="index-banner ib-unknown">
          <div class="ib-title">시장 지수 (코스닥 ^KQ11)</div>
          <div><code>run_local_export</code>로 최신 results_web.json을 넣으면, 지수 2단계(상승) 여부·약세/조정 힌트가 여기에 표시됩니다.</div>
        </div>
        {% endif %}
        <div class="meta">
          페이지 갱신: {{ now }}<br/>
          마지막 분석: {{ last_analysis_time or "-" }}<br/>
          현재 2단계 <b>{{ matches|length }}</b>개 / 후보 {{ candidate_count }}개
          {% if scoring %}<br/><span style="font-size:0.88rem">순위·가점: {{ scoring.description }}{% if scoring.max_trend_charts %} (차트 최대 {{ scoring.max_trend_charts }}종{% if scoring.summary_table_rows is defined %} · 요약표 {{ scoring.summary_table_rows }}행{% endif %}){% else %} (차트 전 종목){% endif %}</span>{% endif %}
        </div>

        {% if sector_summary %}
        <div class="pill-wrap">
          {% for sec, cnt in sector_summary %}
          <span class="pill">{{ sec }} <small>({{ cnt }})</small></span>
          {% endfor %}
        </div>
        {% endif %}

        {% if sector_score_table or top_table %}
        <div class="summary">
          <h2>종합 요약</h2>
          {% if sector_score_table %}
          <h3>섹터별 선정 수 · 점수</h3>
          <p style="margin:0 0 8px 0;font-size:0.85rem;color:#666">2단계에 포함된 전 종목 기준. 평균/최고는 해당 섹터 내 총점 기준입니다.</p>
          <div class="sum-table-wrap">
            <table class="sum-table">
              <thead><tr><th>섹터</th><th class="num">종목 수</th><th class="num">평균 점수</th><th class="num">최고 점수</th></tr></thead>
              <tbody>
                {% for r in sector_score_table %}
                <tr><td>{{ r.sector }}</td><td class="num">{{ r.count }}</td><td class="num">{{ "%.2f"|format(r.avg_score) }}</td><td class="num">{{ "%.2f"|format(r.max_score) }}</td></tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          {% endif %}
          {% if top_table %}
          <h3>총점 상위 {{ top_table|length }}개</h3>
          <div class="sum-table-wrap">
            <table class="sum-table">
              <thead><tr><th class="num">순위</th><th>종목명</th><th>티커</th><th>섹터</th><th class="num">총점</th><th>가점(진입/RS/Vol/시총/이익률)</th><th>진입일</th></tr></thead>
              <tbody>
                {% for r in top_table %}
                <tr>
                  <td class="num">{{ r.rank }}</td>
                  <td><b>{{ r.name }}</b></td>
                  <td>{{ r.ticker }}</td>
                  <td>{{ r.sector }}</td>
                  <td class="num">{{ "%.2f"|format(r.score) }}</td>
                  <td>{% if r.score_breakdown %}{{ "%.0f"|format(r.score_breakdown.recency|default(0)) }}/{{ "%.0f"|format(r.score_breakdown.rs|default(0)) }}/{{ "%.0f"|format(r.score_breakdown.volume|default(0)) }}/{{ "%.0f"|format(r.score_breakdown.mcap|default(0)) }}/{{ "%.0f"|format(r.score_breakdown.opm|default(0)) }}{% else %}-{% endif %}</td>
                  <td>{{ r.entry }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </div>
          {% endif %}
        </div>
        {% endif %}

        <div class="diff">
          <div class="diff-box add">
            <h2>신규 포착 (직전 실행 대비)</h2>
            {% if last_diff_added %}
            <ul>{% for x in last_diff_added %}
              <li><b>{{ x.name }}</b> {{ x.ticker }} — {{ x.sector }}{% if 'rank' in x and 'score' in x %} · #{{ x.rank }} / {{ "%.1f"|format(x.score) }}점{% endif %} · 진입 {{ x.entry }}{% if 'rs_ratio' in x and x.rs_ratio is not none %} · RS {{ "%.2f"|format(x.rs_ratio) }}{% endif %}{% if 'vol_20_vs_prev20' in x and x.vol_20_vs_prev20 is not none %} · Vol20 {{ "%.2f"|format(x.vol_20_vs_prev20) }}×{% endif %}</li>
            {% endfor %}</ul>
            {% else %}<p>없음</p>{% endif %}
          </div>
          <div class="diff-box drop">
            <h2>탈락 (직전에는 있었으나 이번엔 없음)</h2>
            {% if last_diff_removed %}
            <ul>{% for x in last_diff_removed %}
              <li><b>{{ x.name }}</b> {{ x.ticker }} — {{ x.sector }} (이전 진입 {{ x.entry }})</li>
            {% endfor %}</ul>
            {% else %}<p>없음</p>{% endif %}
          </div>
        </div>

        {% if sector_blocks %}
        <h2 class="chart-section-title">추세 차트 (총점 상위, 섹터별)</h2>
        {% for block in sector_blocks %}
        <div class="sector">
          <h2>{{ block.sector }} <span style="font-weight:normal;color:#666">({{ block.entries|length }}개)</span></h2>
          <div class="grid">
            {% for m in block.entries %}
            <div class="card">
              <h3>{% if 'rank' in m %}<span style="color:#1a5fb4">#{{ m.rank }}</span> {% endif %}{{ m.name }} ({{ m.ticker }}){% if 'score' in m and m.score is not none %} <span style="color:#0a5c0a;font-weight:600">{{ "%.1f"|format(m.score) }}점</span>{% endif %}</h3>
              <div class="sec">진입(이번 2단계 구간 시작) {{ m.entry }}{% if 'bars_since_stage2_entry' in m and m.bars_since_stage2_entry is not none %} · 진입 후 {{ m.bars_since_stage2_entry }}거래일{% endif %}{% if 'score_breakdown' in m and m.score_breakdown %} · 가점 진입{{ "%.0f"|format(m.score_breakdown.recency|default(0)) }}/RS{{ "%.0f"|format(m.score_breakdown.rs|default(0)) }}/Vol{{ "%.0f"|format(m.score_breakdown.volume|default(0)) }}/시총{{ "%.0f"|format(m.score_breakdown.mcap|default(0)) }}/이익률{{ "%.0f"|format(m.score_breakdown.opm|default(0)) }}{% endif %}{% if 'rs_ratio' in m and m.rs_ratio is not none %} · RS(63d) {{ "%.2f"|format(m.rs_ratio) }}{% endif %}{% if 'ret_3m_pct' in m and m.ret_3m_pct is not none %} · 3M {{ "%.1f"|format(m.ret_3m_pct) }}%{% endif %}{% if 'vol_5_vs_20' in m and m.vol_5_vs_20 is not none %} · 5d/20d거래량 {{ "%.2f"|format(m.vol_5_vs_20) }}×{% endif %}{% if 'vol_20_vs_prev20' in m and m.vol_20_vs_prev20 is not none %} · 20d거래량추세 {{ "%.2f"|format(m.vol_20_vs_prev20) }}×{% endif %}</div>
              {% if m.chart %}<img src="/image/{{ m.chart }}" alt="{{ m.ticker }}" />{% else %}<p class="sec" style="margin:8px 0">차트 없음(순위 밖이거나 미생성)</p>{% endif %}
            </div>
            {% endfor %}
          </div>
        </div>
        {% endfor %}
        {% elif matches %}
        <div class="empty">2단계 종목은 있으나 추세 차트가 없습니다. MAX_TREND_CHARTS·동기화를 확인하세요.</div>
        {% else %}
        <div class="empty">조건을 만족한 종목이 없거나, 아직 결과물이 동기화되지 않았습니다.</div>
        {% endif %}

        <a class="btn" href="/">새로고침</a>
        {% if show_rerun %}
        <a class="btn" href="/run-analysis">전체 재분석 (로컬 전용)</a>
        {% endif %}
        <p class="note">{{ footer_note }}</p>
      </div>
    </body>
    </html>
    """

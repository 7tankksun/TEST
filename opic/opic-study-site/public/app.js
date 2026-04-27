const DATA_URL = "data/materials.json";
const LIBRARY_URL = "data/library.json";
const IT_NEWS_URL = "data/it-news.json";
const TRAVEL_URL = "data/travel.json";

let data = null;
let itNews = null;
let travel = null;
let library = null;
let libQuoteIndex = 0;
let qaOrder = [];
let qaIndex = 0;
let drillFileId = null;
let lastDrillKey = null;

function englishScore(text) {
  if (!text) return 0;
  const m = text.match(/[A-Za-z]/g);
  return m ? m.length / text.length : 0;
}

function isUsableDrillLine(line) {
  if (line.length < 50) return false;
  if (/^[\d*.)]+\s*$/u.test(line)) return false;
  if (line.startsWith("(") && line.length < 30) return false;
  return englishScore(line) > 0.2;
}

function splitForDrill(line) {
  const words = line.split(/\s+/);
  if (words.length < 6) {
    const mid = Math.floor(line.length / 2);
    return { front: line.slice(0, mid).trim() + " …", back: line.slice(mid).trim() };
  }
  const cut = Math.floor(words.length * 0.45);
  return {
    front: words.slice(0, cut).join(" ") + " …",
    back: words.slice(cut).join(" "),
  };
}

function shuffle(arr) {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

async function loadData() {
  const res = await fetch(DATA_URL);
  if (!res.ok) throw new Error("materials.json을 불러올 수 없습니다.");
  data = await res.json();
}

const emptyLibrary = () => ({
  title: "글·책·인용",
  intro: "public/data/library.json 파일을 만들면 여기에 표시됩니다.",
  quotes: [],
  books: [],
  notes: [],
});

async function loadLibrary() {
  try {
    const res = await fetch(LIBRARY_URL);
    if (!res.ok) throw new Error("no library");
    library = await res.json();
  } catch {
    library = emptyLibrary();
  }
  if (!library.quotes) library.quotes = [];
  if (!library.books) library.books = [];
  if (!library.notes) library.notes = [];
}

async function loadItNews() {
  try {
    const res = await fetch(IT_NEWS_URL);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

async function loadTravel() {
  try {
    const res = await fetch(TRAVEL_URL);
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  }
}

const TRAVEL_KIND = {
  country: "국가",
  region: "지역",
  state: "주(美)",
  city: "도시",
};

function renderTravel() {
  const root = document.getElementById("travel-destinations");
  const empty = document.getElementById("travel-empty");
  const disc = document.getElementById("travel-disclaimer");
  if (!travel || !travel.destinations) {
    root.innerHTML = "";
    empty.hidden = false;
    document.getElementById("travel-title").textContent = "가족 여행";
    return;
  }
  empty.hidden = true;
  document.getElementById("travel-title").textContent = travel.title || "가족 여행";
  document.getElementById("travel-intro").textContent = travel.intro || "";
  const sn = document.getElementById("travel-sort-note");
  if (travel.sortNote) {
    sn.textContent = travel.sortNote;
    sn.hidden = false;
  } else {
    sn.hidden = true;
  }
  disc.textContent = travel.disclaimer || "";
  disc.hidden = !travel.disclaimer;
  root.innerHTML = "";
  for (const d of travel.destinations) {
    const art = document.createElement("article");
    art.className = "travel-card";
    const head = document.createElement("header");
    head.className = "travel-card-head";
    const rank = document.createElement("span");
    rank.className = "travel-rank";
    rank.textContent = String(d.rank);
    const kind = document.createElement("span");
    kind.className = "travel-kind";
    kind.textContent = TRAVEL_KIND[d.kind] || d.kind || "";
    const h3 = document.createElement("h3");
    h3.className = "travel-name";
    h3.appendChild(document.createTextNode(d.name || ""));
    if (d.nameEn) {
      h3.appendChild(document.createTextNode(" "));
      const sub = document.createElement("span");
      sub.className = "travel-name-en";
      sub.textContent = d.nameEn;
      h3.appendChild(sub);
    }
    head.appendChild(rank);
    head.appendChild(kind);
    art.appendChild(head);
    art.appendChild(h3);
    if (d.summary) {
      const p = document.createElement("p");
      p.className = "travel-summary";
      p.textContent = d.summary;
      art.appendChild(p);
    }
    if (d.withKids) {
      const sec = elTravelSection("7세·5세 동행");
      const p = document.createElement("p");
      p.className = "travel-body";
      p.textContent = d.withKids;
      sec.appendChild(p);
      art.appendChild(sec);
    }
    if (d.budget) {
      const sec = elTravelSection("경비(참고)");
      if (d.budget.familyWeekKrw) {
        const p = document.createElement("p");
        p.className = "travel-body";
        p.textContent = d.budget.familyWeekKrw;
        sec.appendChild(p);
      }
      if (d.budget.breakdown) {
        const p = document.createElement("p");
        p.className = "travel-budget-line";
        p.textContent = d.budget.breakdown;
        sec.appendChild(p);
      }
      if (d.budget.tips && d.budget.tips.length) {
        sec.appendChild(elTravelList(d.budget.tips));
      }
      art.appendChild(sec);
    }
    if (d.bestTime) {
      const sec = elTravelSection("가기 좋은 시기");
      if (d.bestTime.recommended) {
        const p = document.createElement("p");
        const s1 = document.createElement("strong");
        s1.textContent = "추천: ";
        p.appendChild(s1);
        p.appendChild(document.createTextNode(d.bestTime.recommended));
        sec.appendChild(p);
      }
      if (d.bestTime.avoid) {
        const p = document.createElement("p");
        p.className = "travel-avoid";
        const s2 = document.createElement("strong");
        s2.textContent = "피하거나 점검: ";
        p.appendChild(s2);
        p.appendChild(document.createTextNode(d.bestTime.avoid));
        sec.appendChild(p);
      }
      art.appendChild(sec);
    }
    if (d.festivals && d.festivals.length) {
      const sec = elTravelSection("축제·행사");
      const ul = document.createElement("ul");
      ul.className = "travel-fest";
      for (const f of d.festivals) {
        const li = document.createElement("li");
        const title = f.name + (f.when ? " — " + f.when : "");
        li.appendChild(document.createTextNode(title));
        if (f.where || f.tip) {
          li.appendChild(document.createElement("br"));
          const small = document.createElement("span");
          small.className = "travel-fest-meta";
          small.textContent = [f.where, f.tip].filter(Boolean).join(" · ");
          li.appendChild(small);
        }
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      art.appendChild(sec);
    }
    if (d.food && d.food.length) {
      const sec = elTravelSection("맛·식사");
      const ul = document.createElement("ul");
      ul.className = "travel-food";
      for (const x of d.food) {
        const li = document.createElement("li");
        li.appendChild(document.createTextNode((x.name || "") + (x.note ? " — " + x.note : "")));
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      art.appendChild(sec);
    }
    if (d.attractions && d.attractions.length) {
      const sec = elTravelSection("가족·동선 팁(명소)");
      const ul = document.createElement("ul");
      ul.className = "travel-attr";
      for (const x of d.attractions) {
        const li = document.createElement("li");
        li.appendChild(document.createTextNode((x.name || "") + (x.note ? " — " + x.note : "")));
        ul.appendChild(li);
      }
      sec.appendChild(ul);
      art.appendChild(sec);
    }
    if (d.itinerary && d.itinerary.days && d.itinerary.days.length) {
      const det = document.createElement("details");
      det.className = "travel-itinerary";
      const sum = document.createElement("summary");
      const focus = d.itinerary.focus || "";
      sum.appendChild(document.createTextNode("베스트 후기 기반 일정"));
      if (focus) {
        sum.appendChild(document.createTextNode(" — "));
        const em = document.createElement("span");
        em.className = "travel-itinerary-focus";
        em.textContent = focus;
        sum.appendChild(em);
      }
      det.appendChild(sum);
      if (d.itinerary.blurb) {
        const p = document.createElement("p");
        p.className = "travel-itinerary-blurb";
        p.textContent = d.itinerary.blurb;
        det.appendChild(p);
      }
      const ol = document.createElement("ol");
      ol.className = "travel-itinerary-days";
      for (const day of d.itinerary.days) {
        const li = document.createElement("li");
        li.className = "travel-itin-day";
        const line = document.createElement("p");
        line.className = "travel-itin-line";
        const dLabel = day.d != null ? `${day.d}일차` : "일정";
        const t = (day.title || "").trim();
        line.appendChild(document.createTextNode(t ? `${dLabel} — ${t}` : dLabel));
        li.appendChild(line);
        if (day.items && day.items.length) {
          const ul = document.createElement("ul");
          ul.className = "travel-itin-items";
          for (const it of day.items) {
            const ii = document.createElement("li");
            ii.textContent = it;
            ul.appendChild(ii);
          }
          li.appendChild(ul);
        }
        ol.appendChild(li);
      }
      det.appendChild(ol);
      art.appendChild(det);
    }
    if (d.extraNotes) {
      const sec = elTravelSection("기타");
      const p = document.createElement("p");
      p.className = "travel-extra";
      p.textContent = d.extraNotes;
      sec.appendChild(p);
      art.appendChild(sec);
    }
    root.appendChild(art);
  }
}

function elTravelSection(title) {
  const s = document.createElement("div");
  s.className = "travel-sub";
  const h4 = document.createElement("h4");
  h4.className = "travel-subtitle";
  h4.textContent = title;
  s.appendChild(h4);
  return s;
}

function elTravelList(strs) {
  const ul = document.createElement("ul");
  ul.className = "travel-tips";
  for (const t of strs) {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  }
  return ul;
}

function safeHttpUrl(s) {
  if (!s) return "#";
  try {
    const u = new URL(s, window.location.origin);
    return u.protocol === "http:" || u.protocol === "https:" ? s : "#";
  } catch {
    return "#";
  }
}

function renderItNews() {
  const list = document.getElementById("itnews-list");
  const empty = document.getElementById("itnews-empty");
  const meta = document.getElementById("itnews-meta");
  if (!itNews || !itNews.items || !itNews.items.length) {
    list.innerHTML = "";
    empty.hidden = false;
    meta.textContent = "";
    return;
  }
  empty.hidden = true;
  const when = itNews.fetchedAt ? new Date(itNews.fetchedAt).toLocaleString("ko-KR") : "";
  const sources = (itNews.feeds || []).join(" · ");
  meta.textContent = `마지막 갱신: ${when} · 출처: ${sources}`;
  list.innerHTML = "";
  for (const item of itNews.items) {
    const li = document.createElement("li");
    li.className = "itnews-item";
    const h = document.createElement("h3");
    h.className = "itnews-title";
    h.textContent = item.title || "(제목 없음)";
    li.appendChild(h);
    const sub = document.createElement("div");
    sub.className = "itnews-sub";
    const pub = item.published ? new Date(item.published).toLocaleDateString("ko-KR") : "";
    const eng = item.engagement;
    const engStr =
      eng && (eng.points > 0 || eng.comments > 0)
        ? ` · HN ${eng.points}↑ / 댓글 ${eng.comments}`
        : "";
    sub.textContent = [item.source, pub].filter(Boolean).join(" · ") + engStr;
    li.appendChild(sub);
    const bodyText = (item.body != null && item.body !== "" ? item.body : item.summary) || "";
    if (bodyText) {
      const main = document.createElement("div");
      main.className = "itnews-body";
      main.textContent = bodyText;
      li.appendChild(main);
    }
    const a = document.createElement("a");
    a.className = "itnews-external";
    a.rel = "noopener noreferrer";
    a.target = "_blank";
    a.href = safeHttpUrl(item.link);
    a.textContent = "원문 페이지 열기 (RSS에 본문이 짧을 때만 필요)";
    li.appendChild(a);
    list.appendChild(li);
  }
}

function renderSpotlight() {
  const el = document.getElementById("lib-spotlight");
  const qs = library.quotes || [];
  if (!qs.length) {
    el.hidden = true;
    el.innerHTML = "";
    return;
  }
  libQuoteIndex = Math.floor(Math.random() * qs.length);
  const q = qs[libQuoteIndex];
  el.innerHTML = `<p class="lib-q"></p><p class="lib-src"></p>`;
  el.querySelector(".lib-q").textContent = `“${q.text}”`;
  if (q.source) el.querySelector(".lib-src").textContent = "— " + q.source;
  else el.querySelector(".lib-src").textContent = "";
  el.hidden = false;
}

function renderLibrary() {
  document.getElementById("lib-title").textContent = library.title || "글·책·인용";
  document.getElementById("lib-intro").textContent = library.intro || "";

  const qUl = document.getElementById("lib-quotes");
  qUl.innerHTML = "";
  (library.quotes || []).forEach((q) => {
    const li = document.createElement("li");
    li.innerHTML = `<blockquote>“${escapeHtml(q.text)}”</blockquote><div class="lib-src"></div>`;
    if (q.source) li.querySelector(".lib-src").textContent = "— " + q.source;
    else li.querySelector(".lib-src").remove();
    qUl.appendChild(li);
  });

  const books = document.getElementById("lib-books");
  books.innerHTML = "";
  (library.books || []).forEach((b) => {
    const d = document.createElement("div");
    d.className = "lib-book";
    d.innerHTML = `<h4></h4><div class="author"></div><p class="note"></p>`;
    d.querySelector("h4").textContent = b.title || "(제목 없음)";
    const au = d.querySelector(".author");
    if (b.author) au.textContent = b.author;
    else au.remove();
    const note = d.querySelector(".note");
    if (b.note) note.textContent = b.note;
    else note.remove();
    books.appendChild(d);
  });

  const nUl = document.getElementById("lib-notes");
  nUl.innerHTML = "";
  (library.notes || []).forEach((n) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong></strong><p class="body"></p>`;
    li.querySelector("strong").textContent = n.title || "";
    li.querySelector(".body").textContent = n.body || "";
    nUl.appendChild(li);
  });

  renderSpotlight();
  document.getElementById("lib-shuffle").style.display = (library.quotes || []).length > 1 ? "inline-block" : "none";
}

function escapeHtml(s) {
  if (!s) return "";
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function showView(name) {
  for (const el of document.querySelectorAll(".view")) {
    const on = el.id === `view-${name}`;
    el.hidden = !on;
    el.classList.toggle("is-visible", on);
  }
  for (const btn of document.querySelectorAll(".tab")) {
    const on = btn.dataset.view === name;
    btn.classList.toggle("is-active", on);
    btn.setAttribute("aria-selected", on ? "true" : "false");
  }
}

function fillHome() {
  document.getElementById("meta-blurb").textContent = data.meta.blurb;
  const ul = document.getElementById("meta-tips");
  ul.innerHTML = "";
  for (const t of data.meta.tips) {
    const li = document.createElement("li");
    li.textContent = t;
    ul.appendChild(li);
  }
  const g = data.meta.generatedAt;
  document.getElementById("meta-generated").textContent = g
    ? `자료 생성 시각: ${new Date(g).toLocaleString("ko-KR")}`
    : "";
}

function fillFileSelects() {
  const sel = document.getElementById("file-select");
  const drill = document.getElementById("drill-file");
  sel.innerHTML = "";
  drill.innerHTML = "";
  for (const f of data.files) {
    const o = document.createElement("option");
    o.value = f.id;
    o.textContent = `${f.title} (${f.sourceFile})`;
    sel.appendChild(o);
    const o2 = o.cloneNode(true);
    drill.appendChild(o2);
  }
  if (data.files[0]) {
    drillFileId = data.files[0].id;
    drill.value = drillFileId;
  }
}

function getFileById(id) {
  return data.files.find((f) => f.id === id);
}

/**
 * 앞: 한글 힌트 + 뒤: 영어 본문. (대문자뿐 아니 well / ok / in fact 처럼 소문자로 이어지는 경우 포함)
 * 한 음절 이상의 한글이 나온 뒤, 그 다음 첫 a-z·A-z 위치에서 분리.
 */
function splitKoreanHint(line) {
  const t = (line || "").trim();
  if (t.length < 2) return { keyword: null, body: t };
  if (!/[\uac00-\ud7af]/.test(t) || !/[a-zA-Z]/.test(t)) return { keyword: null, body: t };
  let seenHang = false;
  for (let i = 0; i < t.length; i++) {
    const ch = t[i];
    if (/[\uac00-\ud7af]/.test(ch)) seenHang = true;
    if (!seenHang) continue;
    if (!/[a-zA-Z]/.test(ch)) continue;
    const lead = t.slice(0, i).trim();
    const rest = t.slice(i).trim();
    if (lead.length < 1 || rest.length < 2) return { keyword: null, body: t };
    if (englishScore(lead) > 0.55) return { keyword: null, body: t };
    return { keyword: lead, body: rest };
  }
  return { keyword: null, body: t };
}

/**
 * OPIC docx: 영문 질문 줄 (물음표 또는 Tell me/Describe… 패턴)
 * 연속된 질문 줄은 앞(대체 지문)과 한 블록으로 합침.
 */
function isQuestionLine(s) {
  const t = (s || "").trim();
  if (t.length < 10) return false;
  const hint = splitKoreanHint(t);
  if (hint.keyword && /[\uac00-\ud7af]{2,}/.test(hint.keyword) && hint.body.length >= 8) {
    const b = hint.body.trim();
    const bodyLooksLikeExaminerQ =
      /^(Can you|Describe|Talk about|Tell me|What |When |Where |How |Who |Why |Could you|Do you|Is |Are )/i.test(b) ||
      /^(I['\u2019]d like|I would like)/i.test(b);
    if (!bodyLooksLikeExaminerQ && englishScore(hint.body) > 0.1) {
      return false;
    }
  }
  if (/\n/.test(t) && /\?/s.test(t) && englishScore(t) > 0.06) return true;
  if (/^\*.*\?/s.test(t)) return true;
  if (/\?/.test(t) && englishScore(t) > 0.08) return true;
  if (/^Q1or2:/i.test(t)) return true;
  if (
    /^(\d+)[\.\):][\s]*(Can you|Describe|Talk|Tell me|I\u2019d like|I['\u2019]d like|I would|When|What|How|Do you|Is |Are |Could |Your friend)/i.test(
      t
    )
  )
    return true;
  if (/^(\d+):[\s]*(Describe|Talk|Tell me|Could you|Talk about)/i.test(t)) return true;
  if (
    /^(\d+)[\.\):][\s]*I\u2019m sorry/i.test(t) ||
    /^(\d+)[\.\):][\s]*I['\u2019]m sorry/i.test(t) ||
    /^(\d+)[\.\):][\s]*That\u2019s the end/i.test(t) ||
    /^(\d+)[\.\):][\s]*I\u2019d like/i.test(t)
  )
    return true;
  if (/^(\d+)[.][\s]*I['\u2019]m sorry/i.test(t) || /^2\.[ \t]*I['\u2019]m sorry/i.test(t)) return true;
  if (/^Tell me about .+\?/i.test(t) && t.length < 500) return true;
  if (/^Describe .+\?/i.test(t) && t.length < 500) return true;
  if (/^Can you (describe|tell)/i.test(t) && t.length < 500) return true;
  return false;
}

function isKoreanSectionTitle(s) {
  const t = (s || "").trim();
  if (t.length < 4 || t.length > 120) return false;
  if (/\?/.test(t) && englishScore(t) > 0.2) return false;
  if (isQuestionLine(t)) return false;
  if (englishScore(t) > 0.35) return false;
  if (!/[\uac00-\ud7af]{2,}/.test(t)) return false;
  return true;
}

/**
 * @returns {Array<{type:'loose'|'ktitle'|'q', text?:string, question?:string, segments?:{keyword:string|null, text:string}[]}>}
 */
function buildDocBlocks(paragraphs, enOnly) {
  const blocks = [];
  let currentQ = null;

  function flushQ() {
    if (currentQ && (currentQ.segments.length > 0 || (currentQ.question && currentQ.question.trim()))) {
      blocks.push({ type: "q", question: currentQ.question.trim(), segments: currentQ.segments });
    }
    currentQ = null;
  }

  for (const raw of paragraphs) {
    const p = (raw || "").trim();
    if (!p) continue;
    if (enOnly && englishScore(p) < 0.12) {
      const asKw = splitKoreanHint(p).keyword;
      if (!isQuestionLine(p) && !isKoreanSectionTitle(p) && !asKw) continue;
    }

    if (isKoreanSectionTitle(p)) {
      flushQ();
      blocks.push({ type: "ktitle", text: p });
      continue;
    }

    if (isQuestionLine(p)) {
      if (currentQ && currentQ.segments.length === 0) {
        currentQ.question = (currentQ.question || "") + (currentQ.question ? "\n\n" : "") + p;
      } else {
        flushQ();
        currentQ = { question: p, segments: [] };
      }
      continue;
    }

    const seg = splitKoreanHint(p);
    const textBody = seg.keyword ? seg.body : p;
    if (currentQ) {
      currentQ.segments.push({ keyword: seg.keyword, text: textBody });
    } else {
      blocks.push({ type: "loose", text: p });
    }
  }
  flushQ();
  return blocks;
}

function elDocLoose(text) {
  const wrap = document.createElement("div");
  wrap.className = "doc-loose";
  const p = document.createElement("p");
  p.textContent = text;
  wrap.appendChild(p);
  return wrap;
}

function renderDoc() {
  const id = document.getElementById("file-select").value;
  const f = getFileById(id);
  const enOnly = document.getElementById("en-filter").checked;
  document.getElementById("doc-title").textContent = f.title;
  const flow = document.getElementById("doc-flow");
  flow.innerHTML = "";
  const blocks = buildDocBlocks(f.paragraphs || [], enOnly);

  for (const b of blocks) {
    if (b.type === "loose") {
      flow.appendChild(elDocLoose(b.text));
    } else if (b.type === "ktitle") {
      const h = document.createElement("div");
      h.className = "doc-ktitle";
      h.textContent = b.text;
      flow.appendChild(h);
    } else if (b.type === "q") {
      const section = document.createElement("section");
      section.className = "doc-q-block";
      const label = document.createElement("span");
      label.className = "q-label";
      label.textContent = "질문 / 상황";
      section.appendChild(label);
      const qq = document.createElement("p");
      qq.className = "doc-question";
      qq.textContent = b.question;
      section.appendChild(qq);
      const answers = document.createElement("div");
      answers.className = "doc-answer";
      for (const seg of b.segments || []) {
        const row = document.createElement("div");
        row.className = "doc-seg" + (seg.keyword ? "" : " is-plain");
        if (seg.keyword) {
          const kw = document.createElement("span");
          kw.className = "kw";
          kw.textContent = seg.keyword;
          row.appendChild(kw);
        }
        const body = document.createElement("p");
        body.className = "body";
        body.textContent = seg.text;
        row.appendChild(body);
        answers.appendChild(row);
      }
      section.appendChild(answers);
      flow.appendChild(section);
    }
  }
}

function initQa() {
  qaOrder = shuffle(data.questionCards || []);
  qaIndex = 0;
  if (!qaOrder.length) {
    document.getElementById("qa-question").textContent =
      "질문 카드가 없습니다. DOCX에 물음표(?)가 있는 질문 문장을 추가한 뒤 build 스크립트를 다시 실행하세요.";
    document.getElementById("qa-reveal").disabled = true;
    return;
  }
  showQa();
}

function showQa() {
  const card = qaOrder[qaIndex];
  document.getElementById("qa-counter").textContent = `${qaIndex + 1} / ${qaOrder.length}`;
  document.getElementById("qa-question").textContent = card.q;
  const ans = document.getElementById("qa-answer");
  const ul = document.getElementById("qa-hints");
  ul.innerHTML = "";
  for (const h of card.answerHints) {
    const li = document.createElement("li");
    li.textContent = h;
    ul.appendChild(li);
  }
  ans.hidden = true;
  document.getElementById("qa-reveal").disabled = false;
}

function pickDrill() {
  const fileId = document.getElementById("drill-file").value;
  drillFileId = fileId;
  const f = getFileById(fileId);
  const lines = f.paragraphs.filter(isUsableDrillLine);
  if (!lines.length) {
    document.getElementById("drill-front").textContent = "이 문서에서 쓸 만한 영문 단락이 짧습니다. 자료 보기에서 그대로 읽어 보세요.";
    document.getElementById("drill-back").textContent = "";
    document.getElementById("drill-back").hidden = true;
    return;
  }
  let line;
  for (let k = 0; k < 20; k++) {
    const cand = lines[Math.floor(Math.random() * lines.length)];
    if (cand !== lastDrillKey || lines.length === 1) {
      line = cand;
      break;
    }
  }
  lastDrillKey = line;
  const { front, back } = splitForDrill(line);
  document.getElementById("drill-front").textContent = front;
  const backEl = document.getElementById("drill-back");
  backEl.textContent = back;
  backEl.hidden = true;
  document.getElementById("drill-reveal").textContent = "뒤 문장 보기";
}

function onTab(e) {
  const v = e.target?.dataset?.view;
  if (!v) return;
  showView(v);
  if (v === "docs") renderDoc();
  if (v === "qa" && !qaOrder.length) initQa();
  if (v === "drill" && !document.getElementById("drill-front").textContent) pickDrill();
  if (v === "library" && library) renderLibrary();
  if (v === "itnews") renderItNews();
  if (v === "travel") renderTravel();
}

function main() {
  document.querySelectorAll(".tab").forEach((b) => b.addEventListener("click", onTab));

  document.getElementById("file-select").addEventListener("change", renderDoc);
  document.getElementById("en-filter").addEventListener("change", renderDoc);

  document.getElementById("qa-next").addEventListener("click", () => {
    if (!qaOrder.length) return;
    qaIndex = (qaIndex + 1) % qaOrder.length;
    showQa();
  });
  document.getElementById("qa-prev").addEventListener("click", () => {
    if (!qaOrder.length) return;
    qaIndex = (qaIndex - 1 + qaOrder.length) % qaOrder.length;
    showQa();
  });
  document.getElementById("qa-shuffle").addEventListener("click", () => {
    qaOrder = shuffle(qaOrder);
    qaIndex = 0;
    showQa();
  });
  document.getElementById("qa-reveal").addEventListener("click", () => {
    const a = document.getElementById("qa-answer");
    a.hidden = !a.hidden;
  });

  document.getElementById("drill-file").addEventListener("change", pickDrill);
  document.getElementById("drill-random").addEventListener("click", pickDrill);
  document.getElementById("drill-reveal").addEventListener("click", () => {
    const b = document.getElementById("drill-back");
    b.hidden = !b.hidden;
  });

  document.getElementById("lib-shuffle").addEventListener("click", () => {
    if (!library || !(library.quotes || []).length) return;
    const qs = library.quotes;
    let i = libQuoteIndex;
    if (qs.length > 1) {
      do {
        i = Math.floor(Math.random() * qs.length);
      } while (i === libQuoteIndex);
    }
    libQuoteIndex = i;
    const el = document.getElementById("lib-spotlight");
    const q = qs[libQuoteIndex];
    const qp = el.querySelector(".lib-q");
    const sp = el.querySelector(".lib-src");
    if (qp) qp.textContent = `“${q.text}”`;
    if (sp) sp.textContent = q.source ? "— " + q.source : "";
  });

  Promise.all([loadLibrary(), loadData(), loadItNews(), loadTravel()])
    .then(([, , it, tr]) => {
      itNews = it;
      travel = tr;
      fillHome();
      fillFileSelects();
      renderDoc();
      initQa();
      pickDrill();
      renderLibrary();
    })
    .catch((err) => {
      document.querySelector("main").innerHTML = `<div class="card"><h2>불러오기 실패</h2><p>${err.message}</p><p>로컬 서버로 열어 주세요. (OPIC 자료 materials.json)</p></div>`;
    });
}

main();

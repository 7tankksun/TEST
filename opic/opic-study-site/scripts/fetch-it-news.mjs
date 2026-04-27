/**
 * IT 뉴스 RSS + (필요 시) r.jina.ai 로 본문 보강 → public/data/it-news.json
 * 링크만 있거나 본문이 짧은 항목은 Jina로 읽을 수 있을 때만 유지(요청 한도: MAX_JINA)
 *
 *   node scripts/fetch-it-news.mjs
 *   IT_NEWS_NO_JINA=1  … Jina 생략(디버그)
 */
import { mkdirSync, writeFileSync } from "fs";
import { dirname, join } from "path";
import { fileURLToPath } from "url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const OUT = join(__dirname, "..", "public", "data", "it-news.json");

const FEEDS = [
  { name: "The Verge", url: "https://www.theverge.com/rss/index.xml" },
  { name: "Ars Technica", url: "https://feeds.arstechnica.com/arstechnica/technology-lab" },
  { name: "TechCrunch", url: "https://techcrunch.com/feed/" },
  { name: "BBC Technology", url: "https://feeds.bbci.co.uk/news/technology/rss.xml" },
  { name: "ZDNet Korea", url: "https://zdnet.co.kr/feed/" },
  { name: "Hacker News (front)", url: "https://hnrss.org/frontpage" },
];

const MAX_ITEMS = 32;
const MAX_BODY_CHARS = 20000;
const MAX_JINA = Number(process.env.IT_NEWS_MAX_JINA || 36);
const MIN_BODY_LEN = Number(process.env.IT_NEWS_MIN_BODY || 200);
const JINA_GAP_MS = Number(process.env.IT_NEWS_JINA_MS || 450);
const USE_JINA = process.env.IT_NEWS_NO_JINA !== "1";

const UA = "opic-study-site/1.0 (it-news fetch; contact: self-hosted)";

function sleep(ms) {
  return new Promise((r) => setTimeout(r, ms));
}

function decodeXml(s) {
  if (!s) return "";
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&apos;/g, "\u0027")
    .replace(/&quot;/g, "\u0022")
    .replace(/&#([0-9]+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)))
    .replace(/&#x([0-9A-Fa-f]+);/gi, (_, h) => String.fromCodePoint(parseInt(h, 16)));
}

function stripCdata(s) {
  if (!s) return "";
  return s.replace(/<!\[CDATA\[/g, "").replace(/\]\]>/g, "");
}

function extractTag(block, localName) {
  const esc = localName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const t = new RegExp(`<${esc}[^>]*>([\\s\\S]*?)</${esc}>`, "i");
  const m = block.match(t);
  if (!m) return "";
  return m[1].trim();
}

function extractAtomLink(block) {
  const m = block.match(/<link[^>]+href=["']([^"']+)["'][^>]*\/?>/i);
  if (m) return m[1].trim();
  const m2 = block.match(/<link>([^<]*)<\/link>/i);
  return m2 ? m2[1].trim() : "";
}

function htmlToText(html) {
  if (!html) return "";
  let s = html
    .replace(/<script[\s\S]*?<\/script>/gi, "")
    .replace(/<style[\s\S]*?<\/style>/gi, "");
  s = s.replace(/<\/(p|div|section|article|h[1-6]|tr|li)\s*>/gi, "\n");
  s = s.replace(/<br\s*\/?>\s*/gi, "\n");
  s = s.replace(/<\/table>/gi, "\n");
  s = s.replace(/<[^>]+>/g, " ");
  s = stripCdata(s);
  s = decodeXml(s);
  s = s
    .replace(/[ \t\u00a0]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n");
  return s.trim();
}

function pickLongestHtml(...candidates) {
  const cleaned = candidates.map((c) => stripCdata(decodeXml(c || "")));
  return cleaned.reduce((a, b) => (b.length > a.length ? b : a), "");
}

function trimSyndicationFooter(text) {
  if (!text) return "";
  return text
    .replace(/\n+Read the full story[^\n]*/gi, "")
    .replace(/\n+The post .* appeared first on[\s\S]*$/i, "")
    .replace(/\n+Continue reading[^\n]*/gi, "")
    .replace(/\n+from TechCrunch[\s\S]*$/i, "")
    .trim();
}

function parseDate(s) {
  if (!s) return 0;
  const t = Date.parse(s);
  return Number.isNaN(t) ? 0 : t;
}

function parseHnMetaFromBody(body) {
  if (!body || !/^Article URL:/m.test(body)) {
    return { points: 0, comments: 0, articleUrl: null, isHn: false };
  }
  const p = body.match(/Points:\s*(\d+)/i);
  const c = body.match(/#\s*Comments:\s*(\d+)/i) || body.match(/Comments:\s*(\d+)/i);
  const a = body.match(/Article URL:\s*(\S+)/m) || body.match(/Article URL:\s*(https?:\/\/[^\s]+)/im);
  return {
    points: p ? +p[1] : 0,
    comments: c ? +c[1] : 0,
    articleUrl: a ? a[1].replace(/&amp;/g, "&").trim() : null,
    isHn: true,
  };
}

function isMostlyUrlOnlyBody(body) {
  const t = (body || "").trim();
  if (t.length < 40) return true;
  const noWs = t.replace(/\s/g, "");
  if (/^https?:\/\/\S+$/i.test(t)) return true;
  if ((noWs.match(/https?:\/\//g) || []).length >= 2 && t.length < 200) return true;
  return false;
}

async function jinaRead(url) {
  if (!USE_JINA) return "";
  if (!url || !url.startsWith("http")) return "";
  // Jina: 전체 URL을 path에 둡니다(일부 API는 encode 없이 http(s)://… 형태를 가정)
  const u = "https://r.jina.ai/" + encodeURIComponent(url);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), 25000);
  try {
    const r = await fetch(u, {
      signal: ctrl.signal,
      headers: { "User-Agent": UA, Accept: "text/plain,text/markdown,*/*" },
    });
    if (!r.ok) return "";
    const t = (await r.text()).trim();
    if (t.startsWith("failed") && t.length < 80) return "";
    return t.slice(0, MAX_BODY_CHARS);
  } catch {
    return "";
  } finally {
    clearTimeout(timer);
  }
}

function needsJinaForItem(body, meta) {
  if (meta.isHn && meta.articleUrl) return "hn";
  if (meta.isHn && !meta.articleUrl) return "short";
  if ((body || "").trim().length >= MIN_BODY_LEN && !isMostlyUrlOnlyBody(body)) return null;
  if (isMostlyUrlOnlyBody(body) && (body || "").length < MIN_BODY_LEN) return "short";
  if ((body || "").trim().length < MIN_BODY_LEN) return "short";
  return null;
}

function scoreItem(published, body, points, comments) {
  const now = Date.now();
  const pub = published > 0 ? published : now - 7 * 86400000;
  const ageH = (now - pub) / 3600000;
  const recency = Math.exp(-ageH / 72);

  const hasEng = points + comments > 0;
  const eng = hasEng
    ? Math.log(1 + points) * 1.15 + Math.log(1 + comments) * 0.65
    : Math.log(1 + (body || "").length) * 0.2;

  const substance = Math.log(1 + (body || "").length) * 0.5;

  return recency * 1.8 + eng + substance;
}

function parseRss2(xml, sourceName) {
  const out = [];
  const re = /<item>([\s\S]*?)<\/item>/gi;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const block = m[1];
    let title = extractTag(block, "title");
    let link = extractTag(block, "link");
    if (!link) {
      const l = block.match(/<link[^>]*\/>/i) || block.match(/<link[^>]*>([^<]*)<\/link>/i);
      if (l) link = l[1] ? l[1].trim() : extractAtomLink(block);
    }
    if (!link) {
      const g = block.match(/<guid[^>]*isPermaLink=["']true["'][^>]*>([^<]+)<\/guid>/i);
      if (g) link = g[1].trim();
    }
    const pub = extractTag(block, "pubDate") || extractTag(block, "dc:date");
    const rawHtml = pickLongestHtml(
      extractTag(block, "content:encoded"),
      extractTag(block, "description")
    );
    title = stripCdata(decodeXml(title.replace(/<!\[CDATA\[|\]\]>/g, "")));
    link = (link || "").replace(/<!\[CDATA\[|\]\]>/g, "").trim();
    if (!title || !link) continue;
    const body = trimSyndicationFooter(htmlToText(rawHtml)).slice(0, MAX_BODY_CHARS);
    out.push({
      title,
      link: link.replace(/&amp;/g, "&"),
      source: sourceName,
      published: parseDate(pub),
      body,
    });
  }
  return out;
}

function parseAtom(xml, sourceName) {
  const out = [];
  const re = /<entry>([\s\S]*?)<\/entry>/gi;
  let m;
  while ((m = re.exec(xml)) !== null) {
    const block = m[1];
    const title = stripCdata(decodeXml(extractTag(block, "title").replace(/<!\[CDATA\[|\]\]>/g, "")));
    let link = extractAtomLink(block);
    if (!link) {
      const alt = block.match(/<link[^>]+rel=["']alternate["'][^>]+href=["']([^"']+)["']/i);
      if (alt) link = alt[1];
    }
    const updated = extractTag(block, "updated");
    const rawHtml = pickLongestHtml(extractTag(block, "content"), extractTag(block, "summary"));
    if (!title || !link) continue;
    const body = trimSyndicationFooter(htmlToText(rawHtml)).slice(0, MAX_BODY_CHARS);
    out.push({
      title,
      link: link.replace(/&amp;/g, "&"),
      source: sourceName,
      published: parseDate(updated),
      body,
    });
  }
  return out;
}

function parseFeed(xml, sourceName) {
  const lower = xml.slice(0, 500).toLowerCase();
  if (lower.includes('xmlns="http://www.w3.org/2005/atom"') || lower.includes("<entry>")) {
    return parseAtom(xml, sourceName);
  }
  return parseRss2(xml, sourceName);
}

async function fetchFeed({ name, url }) {
  const res = await fetch(url, {
    headers: { "User-Agent": UA, Accept: "application/rss+xml, application/xml, text/xml, */*" },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const xml = await res.text();
  return parseFeed(xml, name);
}

function dedupeKey(item) {
  try {
    const u = new URL(item.link);
    return u.hostname + u.pathname;
  } catch {
    return item.link;
  }
}

async function main() {
  const raw = [];
  const seen = new Set();
  for (const feed of FEEDS) {
    try {
      const items = await fetchFeed(feed);
      for (const it of items) {
        const k = dedupeKey(it);
        if (seen.has(k)) continue;
        seen.add(k);
        raw.push(it);
      }
      console.log(`OK ${feed.name}: ${items.length} items`);
    } catch (e) {
      console.warn(`Skip ${feed.name}:`, e.message);
    }
  }

  raw.sort((a, b) => b.published - a.published);

  let jinaUsed = 0;
  const enriched = [];
  for (const it of raw) {
    let body = (it.body || "").trim();
    const meta0 = parseHnMetaFromBody(body);
    let points = meta0.points;
    let comments = meta0.comments;
    const readUrl = (meta0.articleUrl && meta0.articleUrl.startsWith("http") ? meta0.articleUrl : it.link) || it.link;
    const reason = needsJinaForItem(body, meta0);

    if (USE_JINA && reason && jinaUsed < MAX_JINA) {
      const fromJina = await jinaRead(readUrl);
      jinaUsed++;
      if (fromJina.length > 0) {
        if (fromJina.length > body.length || reason === "hn") {
          body = trimSyndicationFooter(fromJina);
        }
      }
      await sleep(JINA_GAP_MS);
    }

    if (parseHnMetaFromBody(body).isHn) {
      continue;
    }
    if (!body || body.length < MIN_BODY_LEN) {
      continue;
    }

    const sc = scoreItem(it.published, body, points, comments);
    const row = {
      title: it.title,
      link: it.link,
      source: it.source,
      published: it.published,
      body: body.slice(0, MAX_BODY_CHARS),
    };
    if (points + comments > 0) row.engagement = { points, comments };
    enriched.push({ row, score: sc });
  }

  enriched.sort((a, b) => b.score - a.score);
  const top = enriched.slice(0, MAX_ITEMS).map((e) => e.row);

  const payload = {
    description: "RSS + 필요 시 r.jina.ai 본문 보강, 관심·최신 가중 정렬. IT_NEWS_NO_JINA=1 이면 Jina 생략",
    feeds: FEEDS.map((f) => f.name),
    fetchedAt: new Date().toISOString(),
    items: top,
  };
  mkdirSync(dirname(OUT), { recursive: true });
  writeFileSync(OUT, JSON.stringify(payload, null, 2), "utf8");
  console.log("Wrote", OUT, "items:", top.length, "jina calls:", jinaUsed);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});

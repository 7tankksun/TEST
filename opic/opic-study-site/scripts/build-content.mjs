/**
 * OPIC 폴더의 .docx → public/data/materials.json
 * 외부 패키지 없음. Windows/macOS/Linux에서 tar로 docx(Zip)를 풉니다.
 */
import { mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync, mkdirSync } from "fs";
import { execFileSync } from "child_process";
import { join, dirname, basename } from "path";
import { fileURLToPath } from "url";
import os from "os";
import { randomUUID } from "crypto";

const __dirname = dirname(fileURLToPath(import.meta.url));
const ROOT = join(__dirname, "..");
const OPIC_DIR = join(ROOT, "..");
const OUT_DIR = join(ROOT, "public", "data");
const OUT_FILE = join(OUT_DIR, "materials.json");

function unescapeXml(s) {
  if (!s) return "";
  return s
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&apos;/g, "'")
    .replace(/&quot;/g, '"')
    .replace(/&#x([0-9A-Fa-f]+);/g, (_, h) => String.fromCodePoint(parseInt(h, 16)))
    .replace(/&#([0-9]+);/g, (_, d) => String.fromCodePoint(parseInt(d, 10)));
}

/**
 * w:p 단위로 나눈 뒤, 각 문단의 w:t 텍스트를 이어붙임.
 */
function docxXmlToParagraphs(xml) {
  const parts = xml.split(/<\/w:p>/i);
  const out = [];
  for (const part of parts) {
    const texts = [];
    const re = /<w:t[^>]*>([^<]*)<\/w:t>/g;
    let m;
    while ((m = re.exec(part)) !== null) {
      texts.push(unescapeXml(m[1]));
    }
    const line = texts.join("").replace(/\r/g, "").replace(/\u00a0/g, " ").trim();
    if (line.length) out.push(line);
  }
  return out;
}

function extractDocxToParagraphs(docxPath) {
  const tmp = mkdtempSync(join(os.tmpdir(), "opic-docx-"));
  try {
    // Windows: tar는 기본 설치, .docx = zip
    execFileSync("tar", ["-xf", docxPath, "-C", tmp], { stdio: "ignore" });
    const docXml = join(tmp, "word", "document.xml");
    const xml = readFileSync(docXml, "utf8");
    return docxXmlToParagraphs(xml);
  } finally {
    try {
      rmSync(tmp, { recursive: true, force: true });
    } catch {
      /* ignore */
    }
  }
}

function slugify(name) {
  return basename(name, ".docx")
    .toLowerCase()
    .replace(/[^a-z0-9\uac00-\ud7af]+/g, "-")
    .replace(/^-|-$/g, "") || "doc";
}

function guessTitle(paragraphs, filename) {
  const p0 = paragraphs[0] || "";
  if (p0.length > 0 && p0.length < 120) return p0;
  return basename(filename, ".docx");
}

/** 한글 키워드 바로 뒤에 영문이 붙은 경우(소고기Ok) 읽기 좋게 공백 삽입 */
function beautifyKeywordGlue(line) {
  const s = (line || "").trim();
  if (!s || !/[\uac00-\ud7af]/.test(s) || !/[a-zA-Z]/.test(s)) return s;
  return s.replace(/^([\uac00-\ud7af][\uac00-\ud7af0-9·/\s:()\-]*)([a-zA-Z"'])/u, "$1 $2");
}

/** 단락 한 줄: 키워드·오타 붙음 정리(여러 번 순회) */
function polishLine(line) {
  let s = beautifyKeywordGlue(line);
  for (let pass = 0; pass < 4; pass++) {
    const prev = s;
    s = s.replace(/(\d)\.(?=[\uac00-\ud7af0-9])/g, "$1. ");
    s = s.replace(/\):\s*([A-Za-z*])/g, "): $1");
    s = s.replace(/(?<![\d\s]):([A-Z][a-z])/g, ": $1");
    s = s.replace(/([a-z?!])\.\s*([A-Z][a-z]*)\b/g, "$1. $2");
    s = s.replace(/\?([A-Za-z가-힣])/g, "? $1");
    s = s.replace(/~([A-Za-z\uac00-\ud7af])/g, "~ $1");
    s = s.replace(/,([A-Za-z가-힣])/g, ", $1");
    s = s.replace(/\band Well, it\b/gi, "and well, it");
    s = s.replace(
      /([\uac00-\ud7af]{2,})so\s*(they['\u2019]re|they )/gi,
      "$1 so $2"
    );
    s = s.replace(/\b(and|or|but|so|it)([A-Z][a-z]{2,})\b/g, "$1 $2");
    s = s.replace(/\b(most|some|many|all)([A-Z][a-z]{2,})\b/g, "$1 $2");
    s = s.replace(/([가-힣])(Actually|Traditionally|On weekends|On weekday)/g, "$1 $2");
    s = s.replace(
      /([\uac00-\ud7af])so(they'?re|it was|we |I |you |the )/gi,
      "$1 so $2"
    );
    s = s.replace(/([\uac00-\ud7af]{2,})([a-z][a-z]{2,})\b/g, (m, hang, eng) => {
      if (/^(the|and|for|you|not|are|was|but|our|out|who|how|why|can|may|new|now|all|any|get|got|her|him|his|she|its|let|way|too|two|use|day|try|see|own|say|she|too|who|boy|did|let|put|end|why|ask|men|run|set|ago|off|old|far|lot|big|bad|yes|yet|own|red|top|sit|six|ten|dog|eat|cut|low|win|won|sat|die|hit|hot|nor|ice|ill|lay|led|may|mix|pay|per|pop|ran|rid|rod|sea|sin|sir|son|sun|tea|tie|ton|toy|van|war|wet|won|yes|yet|zip)$/i.test(eng))
        return m;
      return `${hang} ${eng}`;
    });
    s = s.replace(/\bgrillright\b/gi, "grill right");
    s = s.replace(/\bmostKorean\b/g, "most Korean");
    if (s === prev) break;
  }
  return s.replace(/  +/g, " ").trim();
}

function isAnswerMarkerLine(line) {
  return /^답변\s*:/u.test((line || "").trim());
}

/** '답변:' 없이 이어지는 지문(가족친구 Q1or2 등)에서 질문 단락 수집 중단 */
function looksLikeAnswerStart(line) {
  const t = (line || "").trim();
  if (!t) return false;
  if (/^[\uac00-\ud7af]{1,24}\s*\([^)]{1,40}\)\s*:/u.test(t)) return true;
  if (/^(Actually|On weekends|After cleaning|Finally,|Well~|Then,|Last year|Since |But I|So I|Yeah~|In the end|Soon,|For dinner|Hi,|My |When it|But honestly|So yeah)/i.test(t)) return true;
  if (/^I(\s|'|’|ʼ)/i.test(t)) return true;
  if (/^\*Now,/i.test(t) || /^\*Tell me/i.test(t)) return true;
  if (/^\(최근/i.test(t)) return true;
  return false;
}

/** DOCX에서 "1.질문:", "2.3 질문:", "Q1or2: 질문:", "3: 질문:" 으로 시작하는 블록 */
function isQuestionBlockStart(line) {
  const t = (line || "").trim();
  if (t.length < 6) return false;
  if (/^Q\d+or\d+\s*:\s*질문\s*:/iu.test(t)) return true;
  if (/^\d+(?:\.\d+)?\.\s*질문\s*:/u.test(t)) return true;
  if (/^\d+(?:\.\d+)?\s+질문\s*:/u.test(t)) return true;
  if (/^\d+\s*:\s*질문\s*:/u.test(t)) return true;
  return false;
}

function stripLeadingQuestionLabel(line) {
  const t = (line || "").trim();
  let rest = t
    .replace(/^Q\d+or\d+\s*:\s*질문\s*:\s*/iu, "")
    .replace(/^\d+(?:\.\d+)?\.\s*질문\s*:\s*/u, "")
    .replace(/^\d+(?:\.\d+)?\s+질문\s*:\s*/u, "")
    .replace(/^\d+\s*:\s*질문\s*:\s*/u, "");
  return rest.trim();
}

/**
 * 워드에서 편집한 질문:/답변: 구조를 자료 보기용 단락 배열로 정규화.
 * - 같은 질문 블록(한글 지시 + 영문 지문 여러 줄)을 한 단락으로 합침
 * - "답변:" 줄은 제거
 * - 키워드+영문 붙은 줄은 공백으로 분리
 */
function normalizeDocParagraphs(paragraphs) {
  const out = [];
  let i = 0;
  const n = paragraphs.length;

  while (i < n) {
    const raw = paragraphs[i];
    const L = (raw || "").trim();
    if (!L) {
      i++;
      continue;
    }

    if (isQuestionBlockStart(L)) {
      const parts = [];
      const first = stripLeadingQuestionLabel(L);
      if (first) parts.push(first);
      i++;
      while (i < n) {
        const P = (paragraphs[i] || "").trim();
        if (!P) {
          i++;
          continue;
        }
        if (isAnswerMarkerLine(P)) {
          i++;
          break;
        }
        if (isQuestionBlockStart(P)) break;
        if (looksLikeAnswerStart(P)) break;
        parts.push(P);
        i++;
      }
      const qBlock = parts.map((p) => polishLine(p)).join("\n\n").trim();
      if (qBlock) out.push(qBlock);
      continue;
    }

    if (isAnswerMarkerLine(L)) {
      i++;
      continue;
    }

    out.push(polishLine(L));
    i++;
  }
  return out;
}

/**
 * OPIC 2급: 질문(영문 물음표)과 그 다음 단락을 묶어 카드 후보 생성
 */
function buildCards(id, paragraphs) {
  const cards = [];
  for (let i = 0; i < paragraphs.length; i++) {
    const t = paragraphs[i];
    if (t.length < 15) continue;
    const hasQmark = /\?/.test(t);
    const multilineQ = t.includes("\n\n") && hasQmark;
    if (
      !hasQmark &&
      !multilineQ &&
      !/^(describe|talk about|can you|tell me|what |how |when |where |who )/im.test(t)
    ) {
      continue;
    }
    // 앞뒤 짧은 질문만 카드; 샘플 답이 이어질 수 있음
    const after = [];
    for (let j = i + 1; j < Math.min(i + 12, paragraphs.length); j++) {
      const p = paragraphs[j];
      if (p.length < 20) continue;
      if (/^(\d+[\.\)]\s*|[Qq]\d)/.test(p) && p.length < 200) {
        if (/\?/.test(p)) break;
      }
      const nextIsQ =
        (/\?/.test(p) && p.length > 40 && /[a-zA-Z]{12,}/.test(p)) ||
        (p.includes("\n\n") && /\?/.test(p));
      if (nextIsQ) break;
      after.push(p);
      if (after.length >= 3) break;
    }
    if (after.length === 0) {
      if (i + 1 < paragraphs.length && paragraphs[i + 1].length > 30) {
        after.push(paragraphs[i + 1]);
      }
    }
    if (after.length) {
      const qShort = t.length > 520 ? t.slice(0, 520) + "…" : t;
      cards.push({
        id: randomUUID(),
        fileId: id,
        q: qShort,
        answerHints: after,
      });
    }
  }
  // 너무 많은 중복 질문 제거(동일 q 앞 80자)
  const seen = new Set();
  return cards.filter((c) => {
    const k = c.q.slice(0, 80);
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

function main() {
  const docxNames = readdirSync(OPIC_DIR).filter((f) => f.toLowerCase().endsWith(".docx"));
  if (!docxNames.length) {
    console.warn("OPIC 폴더에 .docx가 없습니다:", OPIC_DIR);
  }

  const files = [];
  const allCards = [];

  for (const name of docxNames) {
    const full = join(OPIC_DIR, name);
    let paragraphs;
    try {
      paragraphs = extractDocxToParagraphs(full);
    } catch (e) {
      console.error("읽기 실패:", name, e.message);
      continue;
    }
    paragraphs = normalizeDocParagraphs(paragraphs);
    const id = slugify(name) + "-" + String(files.length);
    const title = guessTitle(paragraphs, name);
    files.push({ id, sourceFile: name, title, paragraphs });
    const c = buildCards(id, paragraphs);
    allCards.push(...c);
  }

  mkdirSync(OUT_DIR, { recursive: true });
  const payload = {
    meta: {
      levelGoal: 2,
      blurb:
        "OPIC 2급은 일상 토픽에 대해 짧고 또렷한 문장으로 말할 수 있으면 됩니다. First, Then, Finally 같은 연결어로 두세 문장씩 늘려 보세요.",
      tips: [
        "2분 롤: 질문이 들리면 5초 쉬고, 골자( who / what / when / why )를 한 문장으로 먼저 잡는다.",
        "답이 길지 않을 때: 예시 한 가지(구체적 단어) + 감정 한 마디(I felt ~ / It was ~).",
        "모를 때: Honestly, I don't know much about it, but + 비슷한 경험으로 연결.",
      ],
      generatedAt: new Date().toISOString(),
    },
    files,
    questionCards: allCards,
  };
  writeFileSync(OUT_FILE, JSON.stringify(payload, null, 2), "utf8");
  console.log("작성:", OUT_FILE);
  console.log("문서:", files.length, "개, 질문 카드:", allCards.length, "개");
}

main();

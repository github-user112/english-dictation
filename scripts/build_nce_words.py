"""拔 ncego.com 新概念1-4单词页 → wordlists/nce{1..4}.json (带课次)

用法: python3 scripts/build_nce_words.py [html目录]   # 默认 /tmp, 需含 nce1.html..nce4.html
页面结构: <h3 ...><a>Lesson N 标题</a></h3> 分课 (nce1 为 "Lesson 1&2" 双课, 取首个课号);
每词一个块: <a href="/word/xxx">word</a> + <em class="phonetic">/</em>音标<em>/</em>
+ 若干组 <span class="badge...">词性</span><small>释义</small>。
跨课重复的词只保留首次出现的课。
"""
import html as html_mod
import json
import re
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SRC_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp")

HEADER_RE = re.compile(r'<h3 class="h4 my-3[^"]*">\s*<a[^>]*>([^<]+)</a>')
LESSON_NUM_RE = re.compile(r"Lesson\s+(\d+)")
BLOCK_RE = re.compile(
    r'<a href="/word/[^"]*"[^>]*>(?P<word>[^<]+)</a>(?P<body>.*?)'
    r'(?=<a href="/word/|</div>\s*</div>|<h3)', re.S)
PHON_RE = re.compile(r'<em class="phonetic">/</em>(.*?)<em\s+class="phonetic">/</em>', re.S)
SENSE_RE = re.compile(
    r'<span class="badge[^"]*">\s*(?P<pos>[^<]*?)\s*</span>\s*<small class="text-gray">(?P<zh>[^<]*)</small>',
    re.S)


def clean(s):
    return html_mod.unescape(re.sub(r"\s+", " ", s)).strip()


def parse_book(n):
    text = (SRC_DIR / f"nce{n}.html").read_text(encoding="utf-8")
    headers = [(m.start(), int(LESSON_NUM_RE.search(html_mod.unescape(m.group(1))).group(1)))
               for m in HEADER_RE.finditer(text) if LESSON_NUM_RE.search(html_mod.unescape(m.group(1)))]
    words, seen = [], set()
    for idx, (pos, lesson) in enumerate(headers):
        end = headers[idx + 1][0] if idx + 1 < len(headers) else len(text)
        for m in BLOCK_RE.finditer(text, pos, end):
            word = clean(m.group("word"))
            body = m.group("body")
            if not word or word.lower() in seen:
                continue
            seen.add(word.lower())
            ph = PHON_RE.search(body)
            phonetic = f"/{clean(ph.group(1)).strip(';')}/" if ph and clean(ph.group(1)) else ""
            senses = [(clean(s.group("pos")), clean(s.group("zh"))) for s in SENSE_RE.finditer(body)]
            meaning = "；".join(f"{p} {z}".strip() for p, z in senses if p or z)
            # 兜底：BLOCK_RE 偶发把 HTML 属性混进 word 字段，取最后一个 > 之后的内容
            if "class=" in word:
                m2 = re.search(r'">(.+)$', word)
                if m2:
                    word = m2.group(1)
            words.append({"word": word, "phonetic": phonetic, "meaning": meaning, "lesson": lesson})

    out = BASE / "wordlists" / f"nce{n}.json"
    out.write_text(json.dumps(
        {"name": f"NCE{n}", "type": "words", "words": words},
        ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    no_phon = sum(1 for w in words if not w["phonetic"])
    no_mean = sum(1 for w in words if not w["meaning"])
    lessons = len({w["lesson"] for w in words})
    print(f"nce{n}: {len(words)} 词 / {lessons} 课 → {out}  (缺音标 {no_phon}, 缺释义 {no_mean})")


if __name__ == "__main__":
    for n in (1, 2, 3, 4):
        parse_book(n)

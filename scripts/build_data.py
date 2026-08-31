"""拉取并转换词库/句子素材为统一 JSON 格式"""
import json
import os
import string
import sys
import time
import urllib.request
import urllib.parse
from pathlib import Path


def _atomic_write(path, data):
    """原子写入：先写临时文件再 os.replace，避免中断留下损坏 JSON。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)

BASE = Path(__file__).resolve().parent.parent
WORDLIST_DIR = BASE / "wordlists"
SENTENCE_DIR = BASE / "sentences"

RAWDATA = "https://raw.githubusercontent.com"

REPO = "vxiaozhi/vocabulary-book-by-deepseek/main/data"

# key: (输出名, 子路径, 两种格式: alpha=按字母分 / single=单文件)
WORD_SOURCES = {
    "cet4": f"{REPO}/cet4",
    "cet6": f"{REPO}/cet6",
    "kaoyan": f"{REPO}/kaoyan",
    "tuofu": f"{REPO}/tuofu",
}
WORD_FILES = {
    "cet6": "cet6_words.json",
    "kaoyan": "kaoyan-words.json",
    "tuofu": "tuofu-words.json",
}


def fetch(url, retries=3):
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def dedup_words(words):
    seen = {}
    dropped = 0
    out = []
    for w in words:
        key = w["word"]
        if key in seen:
            dropped += 1
            if w["meaning"] and w["meaning"] not in seen[key]["meaning"].split(" / "):
                seen[key]["meaning"] += " / " + w["meaning"]
            if w["phonetic"] and not seen[key]["phonetic"]:
                seen[key]["phonetic"] = w["phonetic"]
        else:
            seen[key] = w
            out.append(w)
    if dropped:
        print(f"  去重: 合并/移除 {dropped} 个重复词")
    return out


def fetch_wordlist(key, path):
    if key in WORD_FILES:
        url = f"{RAWDATA}/{path}/{WORD_FILES[key]}"
        items = json.loads(fetch(url))
        words = []
        for it in items:
            ts = it.get("translations") or []
            meaning = "; ".join(
                f"{t.get('type', '')}.{t['translation']}" if t.get("type") else t["translation"]
                for t in ts
            )
            words.append({
                "word": it["word"].strip().lower(),
                "phonetic": "",
                "meaning": meaning,
            })
        print(f"  {key}: {len(words)} 词 (单文件)")
        return dedup_words([w for w in words if w["word"]])

    words = []
    for letter in string.ascii_uppercase:
        url = f"{RAWDATA}/{path}/{letter}.json"
        data = fetch(url)
        items = json.loads(data)
        for it in items:
            words.append({
                "word": it["word"].strip().lower(),
                "phonetic": (it.get("phonetic_symbol") or "").strip(),
                "meaning": (it.get("mean") or "").strip(),
            })
        print(f"  {key} {letter}: {len(items)}")
    return dedup_words([w for w in words if w["word"]])


def fetch_oral900():
    path = (f"{RAWDATA}/drizzletown/English900/master/"
            f"%E6%96%B0%E6%97%B6%E4%BB%A3%E8%8B%B1%E8%AF%AD900%E5%8F%A5_"
            f"%E7%BA%AF%E6%96%87%E6%9C%AC900%E8%A1%8C.txt")
    text = fetch(path).decode("utf-8")
    sentences, current_module = [], ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        import re
        m = re.match(r"^(\d{2})-(\d{3})\.\s*(.*?)\s*——\s*(.*)$", line)
        if m:
            mod, idx, en, zh = m.groups()
            if mod != current_module and mod:
                current_module = mod
            sentences.append({
                "id": f"oral900-{m.group(1)}-{m.group(2)}",
                "lesson": int(mod),
                "module": int(mod),
                "en": en.strip(),
                "zh": zh.strip(),
            })
        else:
            print("  SKIP:", line[:60])
    return sentences


def main():
    force = "--force" in sys.argv
    WORDLIST_DIR.mkdir(exist_ok=True)
    SENTENCE_DIR.mkdir(exist_ok=True)

    for key, path in WORD_SOURCES.items():
        out = WORDLIST_DIR / f"{key}.json"
        if out.exists() and not force:
            print(f"{key}: 已存在，跳过 ({out.stat().st_size} bytes)")
            continue
        print(f"拉取 {key} ...")
        try:
            words = fetch_wordlist(key, path)
        except Exception as e:
            print(f"  {key} 失败: {e}")
            continue
        data = {"name": key.upper(), "type": "words", "words": words}
        _atomic_write(out, data)
        print(f"  {key}: {len(words)} 词 -> {out.name}")

    out = SENTENCE_DIR / "oral900.json"
    if out.exists() and not force:
        print(f"oral900: 已存在，跳过")
    else:
        try:
            sentences = fetch_oral900()
            data = {"name": "口语900句", "type": "sentences", "items": sentences}
            _atomic_write(out, data)
            print(f"oral900: {len(sentences)} 句 -> {out.name}")
        except Exception as e:
            print(f"  oral900 失败: {e}")


if __name__ == "__main__":
    main()
"""拉取新概念英语 1-4 册逐句中英对照（iChochy/NCE 的 LRC 数据）并转换为统一句子格式

用法:
  build_nce.py         生成 sentences/nc1.json ~ nc4.json（已存在则跳过）
  build_nce.py --force 重新生成
"""
import argparse
import json
import re
import sys
import os
import time
import urllib.parse
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
OUT = BASE / "sentences"
ROOT = "https://nce.mleo.site"


def _atomic_write(path, data):
    """原子写入：先写临时文件再 os.replace，避免中断留下损坏 JSON。"""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), "utf-8")
    os.replace(tmp, path)

TITLES = {1: "新概念英语1册", 2: "新概念英语2册", 3: "新概念英语3册", 4: "新概念英语4册"}


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


def parse_lrc(text):
    """[00:02.71]英文 | 中文"""
    items = []
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"^\[\d{1,2}:\d{2}\.\d{2,3}\](.*)$", line)
        if not m:
            continue
        body = m.group(1).strip()
        if not body or body.startswith("["):
            continue
        parts = [p.strip() for p in body.split("|", 1)]
        en, zh = (parts + [""])[:2]
        if not en:
            continue
        items.append({"en": en, "zh": zh})
    return items


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(exist_ok=True)

    for book in (1, 2, 3, 4):
        out = OUT / f"nc{book}.json"
        if out.exists() and not args.force:
            print(f"nc{book}: 已存在，跳过")
            continue
        meta = json.loads(fetch(f"{ROOT}/NCE{book}/book.json"))
        items = []
        for idx, unit in enumerate(meta["units"], 1):
            url = f"{ROOT}/NCE{book}/" + urllib.parse.quote(unit["filename"]) + ".lrc"
            lrc = fetch(url).decode("utf-8")
            for j, it in enumerate(parse_lrc(lrc), 1):
                if re.match(r"^Lesson\s+\d+$", it["en"]):
                    continue
                items.append({**it, "id": f"nce{book}-{idx}-{j}", "lesson": idx})
            print(f"  NCE{book} 单元 {idx}/{len(meta['units'])} 累计 {len(items)} 句")
        data = {"name": TITLES[book], "type": "sentences", "items": items}
        _atomic_write(out, data)
        print(f"nc{book}: {len(items)} 句 -> {out.name}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
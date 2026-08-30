"""下载新概念原生美音 MP3+LRC（tangx/New-Concept-English），按句生成媒体片段映射

产出:
  audio/<list_key>/nce{book}_*.mp3       整课 MP3（本地同源托管）
  audio/<list_key>/nce_audio_map.json    {item_id: {file, start, end}}，供后端 audio_url / 切分脚本使用

各册仓库目录与命名差异:
  nc1: NCE1-美音-(MP3+LRC)/NNN&NNN.mp3   每文件含 2 课（001&002=第1课, 003&004=第2课,...）
  nc2: NCE2-美音-(MP3+LRC)/NN－标题.mp3   每文件 1 课（NN=课号）
  nc3: NCE3-美音-(MP3+LRC)/NN－标题.mp3   每文件 1 课
  nc4: NCE4-美音-(MP3+LRC)/NN－标题.mp3   每文件 1 课

用法:
  ingest_nce_audio.py --list nc2           下载 nc2 并生成映射
  ingest_nce_audio.py --list nc2 --dry-run 只打印匹配率
  ingest_nce_audio.py --list nc1 --force   强制重下 nc1
"""
import argparse
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SENT_DIR = BASE / "sentences"
REPO = "tangx/New-Concept-English"
BOOK_DIR = {
    "nc1": ("新概念英语第1册美音（MP3+LRC）", "NCE1-美音-(MP3+LRC)"),
    "nc2": ("新概念英语第2册美音（MP3+LRC）", "NCE2-美音-(MP3+LRC)"),
    "nc3": ("新概念英语第3册美音（MP3+LRC）", "NCE3-美音-(MP3+LRC)"),
    "nc4": ("新概念英语第4册美音（MP3+LRC）", "NCE4-美音-(MP3+LRC)"),
}

# 文件名 → (a, b) 数字元组；lesson 号；整课 mp3 本地文件名
NAME_PATTERNS = {
    "nc1": {"re": r"^(\d+)&(\d+)", "lesson": lambda a, b: (int(a) + 1) // 2,
            "slug": lambda a, b: f"nce1_{a}_{b}.mp3"},
    "nc2": {"re": r"^(\d+)\uFF0D", "lesson": lambda a, b: int(a),
            "slug": lambda a, b: f"nce2_{int(a):02d}.mp3"},
    "nc3": {"re": r"^(\d+)\uFF0D", "lesson": lambda a, b: int(a),
            "slug": lambda a, b: f"nce3_{int(a):02d}.mp3"},
    "nc4": {"re": r"^(\d+)\uFF0D", "lesson": lambda a, b: int(a),
            "slug": lambda a, b: f"nce4_{int(a):02d}.mp3"},
}

TAIL_PAD = 0.3   # 每句结束前提前裁剪秒数，避免带入下一句开头/播报


def fetch(url, binary=False, retries=3):
    for i in range(retries):
        try:
            is_api = url.startswith("https://api.github.com")
            req = urllib.request.Request(url, headers={
                "User-Agent": "curl/8",
                "Accept": "application/vnd.github+json" if is_api else "*/*",
            })
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read()
                return data if binary else data.decode("utf-8")
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(2 * (i + 1))


def parse_lrc(text):
    out = []
    for line in text.splitlines():
        m = re.match(r"^\[(\d{1,2}):(\d{2}(?:\.\d+)?)\](.*)$", line)
        if not m:
            continue
        t = int(m.group(1)) * 60 + float(m.group(2))
        txt = m.group(3).strip()
        if not txt:
            continue
        out.append((t, txt))
    return out


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def find_match(lines, ptr, en):
    """在 lines[ptr:] 前 8 行内找与句子匹配的行。

    先精确匹配（norm 相等），再模糊匹配（SequenceMatcher >= 0.86）。
    返回 (行号, 相似度)；找不到返回 (None, 0.0)。
    """
    n = norm(en)
    best_i, best_s = None, 0.0
    for j in range(ptr, min(len(lines), ptr + 8)):
        m = norm(lines[j][1])
        if m == n:
            return j, 1.0
        r = SequenceMatcher(None, m, n).ratio()
        if r > best_s:
            best_i, best_s = j, r
    if best_s >= 0.86:
        return best_i, best_s
    return None, 0.0


def enc_url(url):
    """对原始（未编码）URL 的路径部分做百分号编码，兼容文件名里的空格/&/全角符号"""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, urllib.parse.quote(p.path), p.query, p.fragment))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", dest="list_key", choices=sorted(BOOK_DIR), default="nc1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--manifest", help="本地文件清单 json（dir/subdir/files），避免 GitHub API 限流")
    args = ap.parse_args()

    book_dir, sub_dir = BOOK_DIR[args.list_key]
    pat = NAME_PATTERNS[args.list_key]
    audio_dir = BASE / "audio" / args.list_key
    audio_dir.mkdir(parents=True, exist_ok=True)
    data = json.loads((SENT_DIR / f"{args.list_key}.json").read_text("utf-8"))

    by_lesson = defaultdict(list)
    for it in data["items"]:
        by_lesson[it.get("lesson")].append(it)

    if args.manifest:
        man = json.loads(Path(args.manifest).read_text("utf-8"))[args.list_key]
        entries = [{"type": "file", "name": f} for f in man["files"]]
        raw_base = f"https://raw.githubusercontent.com/{REPO}/main"
        for e in entries:
            e["download_url"] = f"{raw_base}/{man['dir']}/{man['subdir']}/{e['name']}"
    else:
        repo_dir = urllib.parse.quote(f"{book_dir}/{sub_dir}")
        entries = json.loads(fetch(f"https://api.github.com/repos/{REPO}/contents/{repo_dir}"))
    mp3, lrc = {}, {}
    for e in entries:
        if e.get("type") != "file":
            continue
        m = re.match(pat["re"], e["name"])
        if not m:
            continue
        if e["name"].endswith(".mp3"):
            mp3[m.group(1)] = e["download_url"]
        elif e["name"].endswith(".lrc"):
            lrc[m.group(1)] = e["download_url"]
    print(f"{args.list_key}: 发现 mp3={len(mp3)} lrc={len(lrc)}")

    mapping, total, matched = {}, 0, 0
    for num, lrc_url in sorted(lrc.items(), key=lambda kv: int(kv[0])):
        lines = parse_lrc(fetch(enc_url(lrc_url)))
        if not lines:
            print(f"  警告: {num} 的 lrc 为空")
            continue
        lesson = pat["lesson"](num, 0)
        slug = pat["slug"](num, 0)
        if not args.dry_run:
            dst = audio_dir / slug
            if args.force or not dst.exists():
                raw = fetch(enc_url(mp3[num]), binary=True)
                dst.write_bytes(raw)
                print(f"  下载 {slug} ({len(raw) // 1024}KB)")
        ptr = 0
        seen = {}   # norm文本 -> 已匹配的 (start, end)，用于同课重复句复用
        for it in by_lesson.get(lesson, []):
            total += 1
            en = it["en"]
            j, score = find_match(lines, ptr, en)
            if j is None and norm(en) in seen:
                # 同课内与前面句子文本完全相同（如标题问题在文中复现）：复用同一段音频
                mapping[it["id"]] = {"file": slug, **seen[norm(en)]}
                matched += 1
                continue
            if j is None:
                continue
            start = lines[j][0]
            end = lines[j + 1][0] if j + 1 < len(lines) else start + 2.5
            # LRC 下一行时间戳是下一句起音点，录音里起音常略早于时间戳，
            # 直接取整段会带入下一句开头；减去尾部余量避免串句。
            end = max(end - TAIL_PAD, start + 0.2)
            mapping[it["id"]] = {"file": slug, "start": round(start, 2), "end": round(end, 2)}
            matched += 1
            ptr = j + 1
            if score >= 0.99:
                seen[norm(en)] = {"start": round(start, 2), "end": round(end, 2)}

    print(f"匹配率: {matched}/{total} ({matched * 100 // max(1, total)}%)")
    if args.dry_run:
        return
    (audio_dir / "nce_audio_map.json").write_text(
        json.dumps(mapping, ensure_ascii=False, indent=1), "utf-8")
    print(f"映射已写: audio/{args.list_key}/nce_audio_map.json ({len(mapping)} 条)")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
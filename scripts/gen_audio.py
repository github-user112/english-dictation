"""edge-tts 批量预生成音频

用法:
  gen_audio.py                      全部素材（顺带补缺）
  gen_audio.py --lists cet4,oral900 只生成指定素材
  gen_audio.py --voice en-US-GuyNeural  指定音色(默认美音女声)

并发 4 路，失败自动重试 3 次，已存在的文件跳过。
"""
import argparse
import asyncio
import hashlib
import json
import logging
import sys
from pathlib import Path

import edge_tts

BASE = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "en-US-JennyNeural"
CONCURRENCY = 4
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("gen_audio")


def safe_name(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def load_items(list_key: str):
    """返回 [(文件名, 朗读文本), ...]"""
    wpath = BASE / "wordlists" / f"{list_key}.json"
    spath = BASE / "sentences" / f"{list_key}.json"
    items = []
    if wpath.exists():
        data = json.loads(wpath.read_text("utf-8"))
        for w in data["words"]:
            items.append((safe_name(w["word"]), w["word"]))
    elif spath.exists():
        data = json.loads(spath.read_text("utf-8"))
        for s in data["items"]:
            items.append((safe_name(s["en"]), s["en"]))
    return items


async def synth_one(voice, out_path: Path, text: str):
    for attempt in range(3):
        try:
            com = edge_tts.Communicate(text, voice)
            await com.save(str(out_path))
            return True
        except Exception as e:
            log.warning(f"重试 {attempt+1}/3 {out_path.name}: {e}")
            await asyncio.sleep(1.5 * (attempt + 1))
    return False


async def generate(list_key: str, voice: str):
    audio_dir = BASE / "audio" / list_key
    audio_dir.mkdir(parents=True, exist_ok=True)
    items = load_items(list_key)
    if not items:
        log.info(f"{list_key}: 无素材")
        return 0, 0
    pending = [(n, t) for n, t in items if not (audio_dir / f"{n}.mp3").exists()]
    log.info(f"{list_key}: 共{len(items)} 缺{len(pending)}")

    sem = asyncio.Semaphore(CONCURRENCY)
    ok = 0
    total = len(pending)

    async def worker(name, text):
        nonlocal ok
        async with sem:
            result = await synth_one(voice, audio_dir / f"{name}.mp3", text)
            if result:
                ok += 1
            done = ok
            log.info(f"[{list_key}] {done}/{total} {text[:40]}")
            return result

    results = await asyncio.gather(*[worker(n, t) for n, t in pending])
    return sum(results), len(pending)


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--lists", default=None, help="逗号分隔的素材名")
    parser.add_argument("--voice", default=DEFAULT_VOICE)
    args = parser.parse_args()

    if args.lists:
        lists = [s.strip() for s in args.lists.split(",")]
    else:
        lists = ["cet4", "cet6", "kaoyan", "tuofu", "oral900"]
        log.info(f"全部素材按优先级依次处理: {lists}")

    for lk in lists:
        done_n, pend_n = await generate(lk, args.voice)
        log.info(f"{lk}: 完成 {done_n}/{pend_n}，全部素材生成完毕")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
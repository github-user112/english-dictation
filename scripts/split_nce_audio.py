"""按 nce_audio_map.json 将整课 MP3 切成每句一个小文件

产出:
  audio/<list_key>/<item_id>.mp3   每句一个切分后的 mp3（从整课原生音频裁出）

说明:
  - 文件名用 item_id 而非文本 hash：同一句话在不同课/语境下时间不同，不能共用文件
  - 起点/终点取 map 中的 start/end（end 已含 TAIL_PAD 尾部裁剪），不额外调整
  - 采样率保持 44100 单声道，按 64kbps 重编码（语音足够清晰，单句 ~20-40KB）
  - 已存在目标文件则跳过（幂等，可重复运行）
  - --prune-hash: 删除 map 覆盖项对应的旧 hash TTS 文件（回收空间）

用法:
  split_nce_audio.py [--list nc1] [--dry-run] [--prune-hash] [--workers 2]
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
FFMPEG = None


def get_ffmpeg():
    global FFMPEG
    if FFMPEG:
        return FFMPEG
    try:
        import imageio_ffmpeg
        FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        FFMPEG = shutil.which("ffmpeg")
    if not FFMPEG or not os.path.exists(FFMPEG):
        sys.exit("未找到 ffmpeg：请先 pip install imageio-ffmpeg 或安装系统 ffmpeg")
    return FFMPEG


def cut(args, item_id, entry):
    lesson = BASE / "audio" / args.list_key / entry["file"]
    out = BASE / "audio" / args.list_key / f"{item_id}.mp3"
    if out.exists():
        return item_id, out, None, True
    tmp = out.with_name(f".tmp_{out.stem}.mp3")
    cmd = [
        get_ffmpeg(), "-y", "-v", "error",
        "-i", str(lesson),
        "-ss", f"{entry['start']:.3f}",
        "-to", f"{entry['end']:.3f}",
        "-map", "0:a:0",
        "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "44100", "-ac", "1",
        str(tmp),
    ]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return item_id, out, "ffmpeg 超时", False

    # libmp3lame 有时在结尾报 “Error encoding a frame” 但产物完整可用；
    # 只要文件存在且能完整解码就当作成功。
    if proc.returncode != 0:
        if tmp.exists() and tmp.stat().st_size > 1024:
            chk = subprocess.run([get_ffmpeg(), "-v", "error", "-i", str(tmp), "-f", "null", "-"],
                                 capture_output=True)
            if chk.returncode == 0:
                os.replace(tmp, out)
                os.chmod(out, 0o644)
                return item_id, out, None, False
        tmp.unlink(missing_ok=True)
        return item_id, out, proc.stderr.decode(errors="replace")[-300:], False

    os.replace(tmp, out)
    os.chmod(out, 0o644)
    return item_id, out, None, False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", dest="list_key", default="nc1")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prune-hash", action="store_true")
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    audio_dir = BASE / "audio" / args.list_key
    map_path = audio_dir / "nce_audio_map.json"
    if not map_path.exists():
        sys.exit(f"缺少 {map_path}")

    mapping = json.loads(map_path.read_text("utf-8"))
    total = len(mapping)
    print(f"{args.list_key}: {total} 句待切分")

    if args.dry_run:
        for item_id, entry in list(mapping.items())[:5]:
            print(f"  示例 {item_id}: {entry['file']} [{entry['start']} -> {entry['end']}] "
                  f"-> {item_id}.mp3")
        print(f"  共 {total} 句，目标目录 {audio_dir}")
        return

    ok = skipped = failed = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(cut, args, i, e): i for i, e in mapping.items()}
        for i, fut in enumerate(as_completed(futs), 1):
            item_id, out, err, skip = fut.result()
            if err:
                failed += 1
                print(f"  [失败] {item_id}: {err}")
            elif skip:
                skipped += 1
            else:
                ok += 1
            if i % 200 == 0:
                print(f"  进度 {i}/{total} ok={ok} skip={skipped} fail={failed} "
                      f"elapsed={time.time()-start:.0f}s")

    print(f"完成: 新切 {ok} 跳过 {skipped} 失败 {failed} 用时 {time.time()-start:.0f}s")

    if args.prune_hash and failed == 0:
        sys.path.insert(0, str(BASE))
        from backend import materials as m
        # 仍需 TTS 兜底（id 不在 map 中）的文本，其 hash 文件必须保留
        keep_texts = {it["text"] for it in m.load_material(args.list_key)
                      if it["id"] not in mapping}
        removed = 0
        for it in m.load_material(args.list_key):
            if it["id"] not in mapping:
                continue
            fname = m.audio_filename(it["text"])
            p = audio_dir / fname
            if p.exists() and it["text"] not in keep_texts:
                p.unlink()
                removed += 1
        print(f"已清理旧 hash TTS 文件: {removed}（保留 {len(keep_texts)} 个 TTS 兜底文本）")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
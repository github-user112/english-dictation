"""修复课末句切分：补全被 2.2s 兜底截断的句子，并去掉尾随的下一课播报

原理:
  - 课末句（每课 start 最大的项）在 ingest 时无下一行 LRC，用了 start+2.5 兜底，
    常把句子切短（丢尾音）或把下一课播报切进来。
  - 真实句尾 = 「最后一个其后仍跟着话音的 >=0.8s 静音起点」+ 0.1s 余量；
    无播报的文件则取最后一个话音区间末尾。
  - 仅重切 map 中 dur<=2.5 的课末句，并同步更新 nce_audio_map.json。

用法:
  fix_nce_last_sentences.py [--list nc1] [--dry-run]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
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
        sys.exit("未找到 ffmpeg")
    return FFMPEG


def file_duration(f):
    p = subprocess.run([get_ffmpeg(), "-hide_banner", "-i", str(f)], capture_output=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", p.stderr.decode(errors="replace"))
    if not m:
        return 0.0
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))


def silences(f):
    p = subprocess.run(
        [get_ffmpeg(), "-i", str(f), "-af", "silencedetect=noise=-38dB:d=0.3", "-f", "null", "-"],
        capture_output=True,
    )
    out = p.stderr.decode(errors="replace")
    starts = [float(x) for x in re.findall(r"silence_start:\s*([\d.]+)", out)]
    ends = [float(x) for x in re.findall(r"silence_end:\s*([\d.]+)", out)]
    return list(zip(starts, ends))


def true_sentence_end(f, start):
    """返回课末句的真实结束时间（秒）。"""
    dur = file_duration(f)
    evts = silences(f)
    # 最后一个「其后仍跟着话音」的 >=0.8s 静音 = 句子与播报/结尾的分界
    for s, e in evts[::-1]:
        if e - s >= 0.8 and e < dur - 0.3:
            return round(s + 0.1, 2)
    # 无播报：句尾 = 最后一个话音区间结束（= 最后一个静音事件之前）
    if evts:
        return round(evts[-1][0] + 0.1, 2)
    return round(min(dur, start + 15), 2)


def cut_segment(lesson, item_id, start, end):
    audio_dir = lesson.parent
    out = audio_dir / f"{item_id}.mp3"
    tmp = out.with_name(f".tmp_{out.stem}.mp3")
    cmd = [
        get_ffmpeg(), "-y", "-v", "error",
        "-i", str(lesson),
        "-ss", f"{start:.3f}", "-to", f"{end:.3f}",
        "-map", "0:a:0",
        "-c:a", "libmp3lame", "-b:a", "64k", "-ar", "44100", "-ac", "1",
        str(tmp),
    ]
    proc = subprocess.run(cmd, capture_output=True, timeout=60)
    if proc.returncode != 0:
        if tmp.exists() and tmp.stat().st_size > 1024:
            chk = subprocess.run([get_ffmpeg(), "-v", "error", "-i", str(tmp), "-f", "null", "-"],
                                 capture_output=True)
            if chk.returncode == 0:
                os.replace(tmp, out)
                os.chmod(out, 0o644)
                return True
        tmp.unlink(missing_ok=True)
        return False
    os.replace(tmp, out)
    os.chmod(out, 0o644)
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", dest="list_key", default="nc1")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    audio_dir = BASE / "audio" / args.list_key
    map_path = audio_dir / "nce_audio_map.json"
    if not map_path.exists():
        sys.exit(f"缺少 {map_path}")
    mapping = json.loads(map_path.read_text("utf-8"))

    byfile = defaultdict(list)
    for item_id, entry in mapping.items():
        byfile[entry["file"]].append(item_id)
    last_items = {f: max(ids, key=lambda i: mapping[i]["start"]) for f, ids in byfile.items()}

    changed = []
    for f, item_id in sorted(last_items.items()):
        entry = mapping[item_id]
        if entry["end"] - entry["start"] > 2.5:
            continue  # 非兜底，跳过
        lesson = audio_dir / entry["file"]
        new_end = true_sentence_end(lesson, entry["start"])
        old_end = entry["end"]
        if abs(new_end - old_end) < 0.15:
            continue
        changed.append((item_id, entry, new_end, old_end))

    print(f"待修复课末句: {len(changed)}")
    if args.dry_run:
        for item_id, entry, new_end, old_end in changed:
            print(f"  {item_id}: end {old_end} -> {new_end}")
        return

    ok = 0
    for item_id, entry, new_end, old_end in changed:
        if cut_segment(audio_dir / entry["file"], item_id, entry["start"], new_end):
            entry["end"] = new_end
            ok += 1
            print(f"  [OK] {item_id}: {old_end} -> {new_end}")
        else:
            print(f"  [FAIL] {item_id}")
    map_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), "utf-8")
    print(f"完成: 重切 {ok}/{len(changed)}，map 已更新")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(1)
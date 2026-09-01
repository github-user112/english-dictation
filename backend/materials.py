"""素材加载：词库/句子 JSON → 统一条目；音频 URL"""
import hashlib
import json
import urllib.parse
from functools import lru_cache

from .config import AUDIO, BASE, MATERIALS


class MaterialUnavailable(RuntimeError):
    """素材文件缺失、损坏或结构不符合预期。"""


@lru_cache(maxsize=None)
def load_material(list_key):
    meta = MATERIALS.get(list_key)
    if not meta:
        return []
    try:
        items = []
        if meta["type"] == "words":
            path = BASE / "wordlists" / f"{list_key}.json"
            data = json.loads(path.read_text("utf-8"))
            for word in data["words"]:
                items.append({
                    "id": word["word"],
                    "text": word["word"],
                    "phonetic": word.get("phonetic") or "",
                    "meaning": word.get("meaning") or "",
                    "kind": "word",
                })
        else:
            path = BASE / "sentences" / f"{list_key}.json"
            # 每日新闻由后台任务生成：文件尚未生成时按空素材处理，不拖垮目录页
            if list_key == "news" and not path.exists():
                return []
            data = json.loads(path.read_text("utf-8"))
            for sentence in data["items"]:
                items.append({
                    "id": str(sentence["id"]),
                    "text": sentence["en"],
                    "phonetic": "",
                    "meaning": sentence.get("zh") or "",
                    "kind": "sentence",
                    "lesson": sentence.get("lesson"),
                    "module": sentence.get("module"),
                })
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise MaterialUnavailable(f"{list_key} 素材不可用") from exc

    counts = {}
    for item in items:
        base_id = item["id"]
        counts[base_id] = counts.get(base_id, 0) + 1
        item["id"] = base_id if counts[base_id] == 1 else f"{base_id}~{counts[base_id]}"
    return items


@lru_cache(maxsize=None)
def _material_index(list_key):
    """id → item 字典，O(1) 查找，依赖 load_material 的缓存。"""
    return {i["id"]: i for i in load_material(list_key)}


def iter_material(list_key, lesson=None):
    for item in load_material(list_key):
        if lesson is None or item.get("lesson") == lesson:
            yield item


def find_item(list_key, item_id):
    return _material_index(list_key).get(item_id)


def audio_url(list_key, item_id, text):
    mp = _load_nce_map(list_key).get(item_id)
    if mp:
        # 优先返回切分后的单句小文件；未切分时回落到整课 #t= 片段
        fname = f"{item_id}.mp3"
        if (AUDIO / list_key / fname).exists():
            return f"/audio/{list_key}/{urllib.parse.quote(fname)}"
        return f"/audio/{list_key}/{urllib.parse.quote(mp['file'])}#t={mp['start']:.2f},{mp['end']:.2f}"
    fname = audio_filename(text)
    if (AUDIO / list_key / fname).exists():
        return f"/audio/{list_key}/{fname}"
    return f"/audio/lazy/{fname}"


_NCE_MAP_CACHE = {}


def _load_nce_map(list_key):
    """新概念原生音频片段映射：item_id -> {file, start, end}。命中即返回 #t= 片段 URL。"""
    if list_key not in _NCE_MAP_CACHE:
        p = AUDIO / list_key / "nce_audio_map.json"
        _NCE_MAP_CACHE[list_key] = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    return _NCE_MAP_CACHE[list_key]


def audio_filename(text):
    """返回音频文件名：基于文本内容的 md5 hash（TTS 生成与音频 URL 共享同一算法）"""
    return hashlib.md5(text.encode()).hexdigest() + ".mp3"

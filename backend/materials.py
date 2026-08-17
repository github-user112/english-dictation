"""素材加载：词库/句子 JSON → 统一条目；音频 URL"""
import hashlib
import json
from functools import lru_cache

from .config import AUDIO, BASE, MATERIALS


@lru_cache(maxsize=None)
def load_material(list_key):
    meta = MATERIALS.get(list_key)
    if not meta:
        return []
    items = []
    if meta["type"] == "words":
        p = BASE / "wordlists" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for w in data["words"]:
            items.append({
                "id": w["word"],
                "text": w["word"],
                "phonetic": w.get("phonetic") or "",
                "meaning": w.get("meaning") or "",
                "kind": "word",
            })
    else:
        p = BASE / "sentences" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for s in data["items"]:
            items.append({
                "id": str(s["id"]),
                "text": s["en"],
                "phonetic": "",
                "meaning": s.get("zh") or "",
                "kind": "sentence",
                "lesson": s.get("lesson"),
                "module": s.get("module"),
            })
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
    fname = audio_filename(text)
    if (AUDIO / list_key / fname).exists():
        return f"/audio/{list_key}/{fname}"
    return f"/audio/lazy/{fname}"


def audio_filename(text):
    """返回音频文件名：基于文本内容的 md5 hash（TTS 生成与音频 URL 共享同一算法）"""
    return hashlib.md5(text.encode()).hexdigest() + ".mp3"

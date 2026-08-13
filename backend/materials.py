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
    return items


def iter_material(list_key, lesson=None):
    for item in load_material(list_key):
        if lesson is None or item.get("lesson") == lesson:
            yield item


def find_item(list_key, item_id):
    for m in load_material(list_key):
        if m["id"] == item_id:
            return m
    return None


def audio_url(list_key, item_id, text):
    if list_key == "oral900":
        fname = f"{item_id}.mp3"
    else:
        fname = hashlib.md5(text.encode()).hexdigest() + ".mp3"
    if (AUDIO / list_key / fname).exists():
        return f"/audio/{list_key}/{fname}"
    return f"/audio/lazy/{list_key}/{fname}"

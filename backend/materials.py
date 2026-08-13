"""素材加载：词库/句子 JSON → 统一条目；音频 URL"""
import hashlib
import json

from .config import AUDIO, BASE, MATERIALS


def iter_material(list_key):
    meta = MATERIALS.get(list_key)
    if not meta:
        return None
    if meta["type"] == "words":
        p = BASE / "wordlists" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for w in data["words"]:
            yield {
                "id": w["word"],
                "text": w["word"],
                "phonetic": w.get("phonetic") or "",
                "meaning": w.get("meaning") or "",
                "kind": "word",
            }
    else:
        p = BASE / "sentences" / f"{list_key}.json"
        data = json.loads(p.read_text("utf-8"))
        for s in data["items"]:
            yield {
                "id": str(s["id"]),
                "text": s["en"],
                "phonetic": "",
                "meaning": s.get("zh") or "",
                "kind": "sentence",
            }


def find_item(list_key, item_id):
    for m in iter_material(list_key):
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

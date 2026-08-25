"""我的文章：粘贴英文文本 → 自动分句 → 私有句子集，直接进入听打流程。

存储在 SQLite（custom_material 表），句子以 JSON 内嵌；练习复用
PracticePage 的 dict_custom 注入通道，不走素材注册表。
"""
import json
import re
import uuid

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
from .db import db

bp = Blueprint("custom", __name__)

MAX_TEXT = 20000          # 单次导入字符上限
MAX_SENTENCES = 300       # 句子数上限
MAX_SENTENCE_LEN = 280    # 单句长度上限（超出按标点二次切分）
MIN_SENTENCE_LEN = 2      # 过短的碎片丢弃

_SENT_SPLIT = re.compile(r"(?<=[.!?…。；;])\s+")
_SOFT_SPLIT = re.compile(r"(?<=[,，:：—-])\s+")


def split_sentences(text):
    """把英文文本切成听写用句子：先按句末标点切，超长句再按软标点兜底。"""
    text = (text or "").replace("\r\n", "\n").strip()
    pieces = []
    for para in re.split(r"\n{1,}", text):
        para = para.strip()
        if not para:
            continue
        pieces.extend(_SENT_SPLIT.split(para))
    out = []
    for p in pieces:
        p = p.strip()
        if not p:
            continue
        if len(p) > MAX_SENTENCE_LEN:
            for q in _SOFT_SPLIT.split(p):
                q = q.strip()
                if len(q) >= MIN_SENTENCE_LEN:
                    out.append(q)
        elif len(p) >= MIN_SENTENCE_LEN:
            out.append(p)
    return out[:MAX_SENTENCES]


@bp.get("/api/materials/custom")
def api_custom_list():
    user = get_user()
    with db() as conn:
        rows = conn.execute(
            "SELECT id,title,sentence_count,created_at FROM custom_material "
            "WHERE user=? ORDER BY created_at DESC", (user,)).fetchall()
    return resp({"items": [
        {"id": r["id"], "title": r["title"],
         "count": r["sentence_count"] or 0, "created_at": r["created_at"]}
        for r in rows
    ]})


@bp.post("/api/materials/custom")
def api_custom_create():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    title = (data.get("title") or "").strip()[:60] or "未命名文章"
    text = data.get("text") or ""
    if not isinstance(text, str) or len(text.strip()) < 10:
        return jsonify({"error": "文本太短，至少 10 个字符"}), 400
    if len(text) > MAX_TEXT:
        return jsonify({"error": f"文本过长，最多 {MAX_TEXT} 字符"}), 400
    sents = split_sentences(text)
    if len(sents) < 3:
        return jsonify({"error": "至少需要切分出 3 个句子（检查是否有句末标点）"}), 400
    items = [{"id": f"s{i}", "text": t, "kind": "sentence",
              "phonetic": "", "meaning": "", "audio": ""}
             for i, t in enumerate(sents)]
    mid = uuid.uuid4().hex[:12]
    with db() as conn:
        total = conn.execute(
            "SELECT COUNT(*) c FROM custom_material WHERE user=?", (user,)).fetchone()["c"]
        if total >= 50:
            return jsonify({"error": "最多保存 50 篇文章，请先删除旧的"}), 400
        conn.execute(
            "INSERT INTO custom_material(id,user,title,sentences,sentence_count,created_at) "
            "VALUES(?,?,?,?,?,?)",
            (mid, user, title, json.dumps(items, ensure_ascii=False), len(items),
             now()))   # 完整时间戳：同日多篇也能按导入先后稳定排序
    return resp({"id": mid, "title": title, "count": len(items)})


@bp.get("/api/materials/custom/<mid>")
def api_custom_detail(mid):
    user = get_user()
    with db() as conn:
        row = conn.execute(
            "SELECT id,title,sentences FROM custom_material WHERE id=? AND user=?",
            (mid, user)).fetchone()
    if not row:
        return jsonify({"error": "文章不存在"}), 404
    return resp({"id": row["id"], "title": row["title"],
                 "sentences": json.loads(row["sentences"])})


@bp.delete("/api/materials/custom/<mid>")
def api_custom_delete(mid):
    user = get_user()
    with db() as conn:
        cur = conn.execute(
            "DELETE FROM custom_material WHERE id=? AND user=?", (mid, user))
        if cur.rowcount == 0:
            return jsonify({"error": "文章不存在"}), 404
    return resp({"ok": True})

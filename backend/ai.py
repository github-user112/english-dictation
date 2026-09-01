"""AI 错词串记：把错词本里的词编成情境小故事（CF2OpenAI，OpenAI 兼容代理）。

词集由服务端从错词本取（错次数最多的前 12 个），客户端不能自定义输入——
这个端点不是通用 LLM 代理。结果按 (user, 词集hash) 落 ai_cache，
同一批错词只生成一次；强制重生成 ?fresh=1 每日每用户限 5 次（push_meta 计数）。
"""
import hashlib
import json
import os
import urllib.request
from datetime import date

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
from .db import db

bp = Blueprint("ai", __name__)

AI_BASE = os.environ.get("ENGLISH_DICTATION_AI_BASE", "https://ai.mi9.cc.cd/v1")
AI_KEY = os.environ.get("ENGLISH_DICTATION_AI_KEY", "sk-68ea76a10152ad7c046e166c4159d62c")
AI_MODEL = os.environ.get("ENGLISH_DICTATION_AI_MODEL", "llama-3.3-70b-instruct-fp8-fast")

MAX_WORDS = 12
FRESH_PER_DAY = 5


def _wrong_words(conn, user):
    rows = conn.execute(
        "SELECT list,item_id FROM word_state WHERE user=? AND wrong_count>0 "
        "ORDER BY wrong_count DESC, last_seen DESC LIMIT 40", (user,)).fetchall()
    from .materials import find_item
    words = []
    for r in rows:
        item = find_item(r["list"], r["item_id"])
        if item and item["kind"] == "word" and item["text"] not in words:
            words.append(item["text"])
        if len(words) >= MAX_WORDS:
            break
    return words


def _chat(prompt):
    body = json.dumps({
        "model": AI_MODEL,
        "messages": [
            {"role": "system", "content":
             "你是英语老师，用简单的英语帮学生记单词。只输出故事正文和中文大意，不要解释。"},
            {"role": "user", "content": prompt},
        ],
        "max_tokens": 600,
        "temperature": 0.8,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{AI_BASE}/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {AI_KEY}",
                 # Cloudflare  zone 拦 python-urllib 默认 UA（403），换成显式标识
                 "User-Agent": "english-dictation/3.0 (+https://mi2.cc.cd)"})
    with urllib.request.urlopen(req, timeout=45) as r:
        data = json.loads(r.read())
    return data["choices"][0]["message"]["content"].strip()


def _story_prompt(words):
    return (
        f"把下面这些英语单词编成一段 80~120 词的简单英文小故事（CEFR A2 水平），"
        f"每个单词至少出现一次，并用 **单词** 的形式加粗；故事结束后换行写一句中文大意。"
        f"单词：{', '.join(words)}")


def _mnemonic_prompt(word, phonetic, meaning):
    return (
        f"为英语单词 {word}（音标 {phonetic or '无'}，释义：{meaning or '无'}）写中文助记，共两行：\n"
        f"第一行：词根词缀拆解或谐音助记（一句话，以「助记：」开头）\n"
        f"第二行：与它最常见的 1~2 个易混词的辨析（一句话对比，以「辨析：」开头）\n"
        f"只输出这两行，不要其他内容。")


@bp.get("/api/ai/mnemonic")
def api_ai_mnemonic():
    """单词助记 + 易混词辨析。内容与用户无关，缓存全站共享（user='shared'）。"""
    get_user()
    list_key = request.args.get("list", "")
    item_id = request.args.get("id", "")
    from .materials import find_item
    item = find_item(list_key, item_id)
    if not item or item["kind"] != "word":
        return jsonify({"error": "词条不存在"}), 404
    key = f"{list_key}|{item_id}"
    with db() as conn:
        row = conn.execute(
            "SELECT content FROM ai_cache WHERE user='shared' AND kind='mnemonic' AND key=?",
            (key,)).fetchone()
    if row:
        return resp({"text": row["content"], "cached": True})
    try:
        text = _chat(_mnemonic_prompt(item["text"], item.get("phonetic"), item.get("meaning")))
    except Exception as exc:
        return jsonify({"error": f"AI 生成失败：{exc}"}), 502
    with db() as conn:
        conn.execute(
            "INSERT INTO ai_cache(user,kind,key,content,created_at) VALUES('shared','mnemonic',?,?,?) "
            "ON CONFLICT(user,kind,key) DO UPDATE SET content=excluded.content",
            (key, text, now()))
    return resp({"text": text, "cached": False})


@bp.get("/api/ai/story")
def api_ai_story():
    user = get_user()
    fresh = request.args.get("fresh") == "1"
    with db() as conn:
        words = _wrong_words(conn, user)
    if len(words) < 2:
        return jsonify({"error": "错词本里的单词太少，先去听打积累几个错词吧"}), 400

    key = hashlib.md5("|".join(words).encode()).hexdigest()
    with db() as conn:
        row = conn.execute(
            "SELECT content FROM ai_cache WHERE kind='story' AND user=? AND key=?",
            (user, key)).fetchone()
        if row and not fresh:
            return resp({"words": words, "story": row["content"], "cached": True})

        # 重生成限流：每日每用户 FRESH_PER_DAY 次（首次生成不占额度）
        if fresh:
            today = date.today().isoformat()
            counter = f"ai_fresh|{user}|{today}"
            conn.execute("BEGIN IMMEDIATE")
            r = conn.execute("SELECT value FROM push_meta WHERE name=?", (counter,)).fetchone()
            used = int(r["value"]) if r else 0
            if used >= FRESH_PER_DAY:
                return jsonify({"error": "今天重新生成次数用完了，明天再来"}), 429
            conn.execute(
                "INSERT INTO push_meta(name,value) VALUES(?,?) "
                "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (counter, str(used + 1)))

    try:
        story = _chat(_story_prompt(words))
    except Exception as exc:
        return jsonify({"error": f"AI 生成失败：{exc}"}), 502
    with db() as conn:
        conn.execute(
            "INSERT INTO ai_cache(user,kind,key,content,created_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(user,kind,key) DO UPDATE SET content=excluded.content",
            (user, "story", key, story, now()))
    return resp({"words": words, "story": story, "cached": False})

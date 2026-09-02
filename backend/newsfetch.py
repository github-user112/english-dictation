"""每日新闻听写素材：简易英语新闻 RSS → sentences/news.json + TTS 音频。

源：https://www.newsinlevels.com/feed/ —— 分级简易英语新闻，每日更新
（VOA 慢速英语 2025-03 已停更，BBC 无慢速文本 feed，故选此源）。
同一新闻分 level 1/2/3 三条，取 level 1/2 的摘要段分句；摘要尾部被截断的
半句丢弃。news.json 只增不减：每日按文本去重 append，旧句自然沉淀为复习池。

刷新由 push.py 的应用内守护线程每日触发（claim 行防多 worker 重跑）；
成功后给 gunicorn master 发 SIGHUP，新 worker 重建素材缓存。
"""
import asyncio
import json
import os
import re
import signal
import urllib.request
import xml.etree.ElementTree as ET
from html import unescape
from pathlib import Path

from .db import db

FEED_URL = os.environ.get(
    "ENGLISH_DICTATION_NEWS_FEED", "https://www.newsinlevels.com/feed/")
VOICE = "en-US-JennyNeural"
MAX_NEW_PER_DAY = 20                 # 控制每日 TTS 量

BASE = Path(__file__).resolve().parent.parent
NEWS_JSON = BASE / "sentences" / "news.json"
AUDIO_DIR = BASE / "audio" / "news"

_UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) english-dictation/3.0"}
_TAG_RE = re.compile(r"<[^>]+>")
_DATE_PREFIX_RE = re.compile(r"^\d{2}-\d{2}-\d{4}\s+\d{2}:\d{2}\s*")
_SENT_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\"'])")
_WORD_RE = re.compile(r"[A-Za-z']+")


def fetch_feed(url=FEED_URL):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def _clean_description(raw):
    """RSS description → 纯文本：去 HTML、去日期前缀、去站方签名段。"""
    text = unescape(_TAG_RE.sub(" ", raw or ""))
    text = " ".join(text.split())          # 先归一空白，日期前缀才锚得住行首
    text = _DATE_PREFIX_RE.sub("", text)
    cut = text.find("The post ")
    if cut != -1:
        text = text[:cut]
    return text.strip()


def split_sentences(text):
    """粗分句并过滤：4~30 个英文词、以终止标点结尾（…截断的尾巴不要）。"""
    out = []
    for sent in _SENT_SPLIT_RE.split(text):
        sent = sent.strip()
        if not sent or sent[-1] not in ".!?" or sent.endswith(("...", "…")):
            continue
        words = _WORD_RE.findall(sent)
        if 4 <= len(words) <= 30:
            out.append(sent)
    return out


def parse_feed(xml_bytes):
    """返回 level 1/2 条目的句子列表（按 feed 顺序）。"""
    sentences = []
    root = ET.fromstring(xml_bytes)
    for item in root.findall(".//item"):
        title = item.findtext("title") or ""
        if not re.search(r"level [12]\b", title):
            continue
        sentences.extend(split_sentences(_clean_description(item.findtext("description"))))
    return sentences


def build(xml_bytes, max_new=MAX_NEW_PER_DAY):
    """把 feed 里的新句 append 进 news.json，返回新增句子列表。"""
    existing = {"items": []}
    if NEWS_JSON.exists():
        existing = json.loads(NEWS_JSON.read_text("utf-8"))
    seen = {" ".join(s["en"].lower().split()) for s in existing["items"]}
    next_id = max((int(s["id"]) for s in existing["items"]), default=0) + 1

    fresh = []
    for sent in parse_feed(xml_bytes):
        key = " ".join(sent.lower().split())
        if key in seen:
            continue
        seen.add(key)
        existing["items"].append({"id": next_id, "en": sent, "zh": ""})
        next_id += 1
        fresh.append(sent)
        if len(fresh) >= max_new:
            break
    if fresh:
        NEWS_JSON.write_text(json.dumps(existing, ensure_ascii=False, indent=1), "utf-8")
    return fresh


async def _synth_all(sentences):
    from backend.materials import audio_filename
    import edge_tts
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)

    async def one(sem, text):
        out = AUDIO_DIR / audio_filename(text)
        if out.exists():
            return
        async with sem:
            for attempt in range(3):
                try:
                    await edge_tts.Communicate(text, VOICE).save(str(out))
                    return
                except Exception as exc:
                    print(f"news tts 重试 {attempt + 1}/3 {out.name}: {exc}", flush=True)
                    await asyncio.sleep(1.5 * (attempt + 1))
            print(f"news tts 放弃: {text[:50]}", flush=True)

    sem = asyncio.Semaphore(3)
    await asyncio.gather(*(one(sem, s) for s in sentences))


def refresh():
    """抓 feed → 更新素材与音频。返回新增句数；无新增返回 0，抛异常视为失败。"""
    fresh = build(fetch_feed())
    if fresh:
        asyncio.run(_synth_all(fresh))
    return len(fresh)


def maybe_refresh():
    """每日一轮：push_meta.last_news 认领防多 worker 重跑；成功后 HUP 重载素材缓存。"""
    from datetime import date
    today = date.today().isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM push_meta WHERE name='last_news'").fetchone()
        if row and row["value"] >= today:
            return False
        # 先认领再干活：抓 feed + TTS 要几十秒，握着写锁做会把全站写请求堵死
        conn.execute(
            "INSERT INTO push_meta(name,value) VALUES('last_news',?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (today,))
    try:
        n = refresh()
    except Exception as exc:
        # 失败撤认领：下个 tick（30 分钟后）重试
        with db() as conn:
            conn.execute("DELETE FROM push_meta WHERE name='last_news' AND value=?", (today,))
        print(f"news refresh 失败（下轮重试）: {exc}", flush=True)
        return False
    print(f"news refresh: +{n} 句", flush=True)
    if n:
        _reload_workers()
    return True


def _reload_workers():
    """素材是进程内 lru_cache：HUP 让 gunicorn 平滑重启 worker 重建缓存。"""
    if os.getppid() > 1:
        os.kill(os.getppid(), signal.SIGHUP)

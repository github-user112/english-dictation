"""每日新闻素材：feed 解析 / 分句 / 去重 append / 每日认领。"""
import json

from backend import newsfetch
from backend.db import db

def _esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


FEED = f"""<?xml version="1.0"?>
<rss version="2.0"><channel>
<item><title>Big storm hits coast – level 1</title>
<description>{_esc("<p>01-09-2026 08:00 A big storm hit the coast last night. Many people left their homes. The rain stopped this morning. Roads are closed but no one was hur...</p>")
+ _esc("<p>The post <a href='https://x'>x</a> appeared first on <a href='https://y'>y</a>.</p>")}</description></item>
<item><title>Big storm hits coast – level 3</title>
<description>{_esc("<p>01-09-2026 08:00 Level three text should be skipped entirely here.</p>")}</description></item>
<item><title>New library opens – level 2</title>
<description>{_esc("<p>01-09-2026 09:00 A new library opened in the city center on Monday. It has ten thousand books. Children can read there for free.</p>")}</description></item>
</channel></rss>""".encode("utf-8")


def test_parse_feed_filters_levels_and_truncation():
    sents = newsfetch.parse_feed(FEED)
    assert "A big storm hit the coast last night." in sents
    assert "Many people left their homes." in sents
    # level 3 不取；截断的半句（…结尾无终止标点）不取
    assert not any("Level three" in s for s in sents)
    assert not any("no one was hur" in s for s in sents)
    # 日期前缀已剥掉
    assert not any(s[0].isdigit() for s in sents)
    assert "It has ten thousand books." in sents


def test_build_appends_and_dedupes(tmp_path, monkeypatch):
    target = tmp_path / "news.json"
    monkeypatch.setattr(newsfetch, "NEWS_JSON", target)
    fresh = newsfetch.build(FEED)
    assert len(fresh) == 6
    # 第二轮全量重复 → 0 新增
    assert newsfetch.build(FEED) == []
    data = json.loads(target.read_text("utf-8"))
    ids = [s["id"] for s in data["items"]]
    assert ids == list(range(1, len(ids) + 1))   # 连续递增 id


def test_maybe_refresh_claims_once_per_day(client, tmp_path, monkeypatch):
    monkeypatch.setattr(newsfetch, "NEWS_JSON", tmp_path / "news.json")
    monkeypatch.setattr(newsfetch, "AUDIO_DIR", tmp_path / "audio")
    monkeypatch.setattr(newsfetch, "fetch_feed", lambda: FEED)
    async def fake_synth(sentences):
        return None
    monkeypatch.setattr(newsfetch, "_synth_all", fake_synth)
    monkeypatch.setattr(newsfetch, "_reload_workers", lambda: None)   # 别把 HUP 发给 pytest 的父 shell

    assert newsfetch.maybe_refresh() is True
    assert newsfetch.maybe_refresh() is False     # 今日已认领

    # 抓取失败：不认领，下轮可重试
    def boom():
        raise OSError("network down")
    monkeypatch.setattr(newsfetch, "fetch_feed", boom)
    with db() as conn:
        conn.execute("DELETE FROM push_meta WHERE name='last_news'")
    assert newsfetch.maybe_refresh() is False
    monkeypatch.setattr(newsfetch, "fetch_feed", lambda: FEED)
    assert newsfetch.maybe_refresh() is True

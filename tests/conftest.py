"""pytest 共享夹具：所有后端导入前固定到临时数据库。"""
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
from flask.testing import FlaskClient

# 必须在导入 backend 前设置：backend.config 会在导入期绑定 DB 路径。
_SUITE_DIR = Path(tempfile.mkdtemp(prefix="english-dictation-tests-"))
os.environ["ENGLISH_DICTATION_DB"] = str(_SUITE_DIR / "bootstrap.db")

from backend import create_app
from backend.config import BASE, DB
from backend.materials import _material_index, load_material


@pytest.fixture(scope="session", autouse=True)
def protect_project_database():
    """回归防护：测试绝不能指向开发者的真实学习数据库。"""
    project_data = (BASE / "data").resolve()
    assert project_data not in DB.resolve().parents
    yield


@pytest.fixture(autouse=True)
def clear_material_cache():
    """每个测试前清除素材和索引缓存，避免跨夹具污染。"""
    load_material.cache_clear()
    _material_index.cache_clear()


@pytest.fixture
def app(tmp_path):
    """使用临时数据库、素材和静态产物的 Flask 应用。"""
    db_path = tmp_path / "test.db"
    audio_path = tmp_path / "audio"
    audio_path.mkdir()
    wordlists = tmp_path / "wordlists"
    wordlists.mkdir()
    sentences = tmp_path / "sentences"
    sentences.mkdir()
    static_dir = tmp_path / "static"
    assets = static_dir / "assets"
    assets.mkdir(parents=True)
    (static_dir / "index.html").write_text('<script src="/assets/test.js"></script>', "utf-8")
    (assets / "test.js").write_text("window.__test_asset = true;", "utf-8")

    test_materials = {
        "test_words": {"type": "words", "title": "Test Words"},
        "test_sents": {"type": "sentences", "title": "Test Sentences"},
    }

    word_data = {"name": "Test", "words": [
        {"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "int. 你好"},
        {"word": "world", "phonetic": "/wɜːrld/", "meaning": "n. 世界"},
        {"word": "apple", "phonetic": "/ˈæp.əl/", "meaning": "n. 苹果"},
        {"word": "abandon", "phonetic": "/əˈbændən/", "meaning": "v. 放弃"},
        {"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "int. 问候"},
    ]}
    (wordlists / "test_words.json").write_text(json.dumps(word_data), "utf-8")

    sent_data = {"items": [
        {"id": 1, "en": "Hello world", "zh": "你好世界", "lesson": 1},
        {"id": 2, "en": "This is a test", "zh": "这是一个测试", "lesson": 1},
        {"id": 3, "en": "Lesson two starts", "zh": "第二课开始", "lesson": 2},
        {"id": 4, "en": "Practice every day", "zh": "每天练习", "lesson": 2},
    ]}
    (sentences / "test_sents.json").write_text(json.dumps(sent_data), "utf-8")

    (audio_path / "test_words").mkdir(exist_ok=True)
    hello_hash = "5d41402abc4b2a76b9719d911017c592"  # md5("hello")
    (audio_path / "test_words" / f"{hello_hash}.mp3").touch()

    test_config = {
        "new_per_day": 10, "max_review": 30, "known_threshold": 3,
        "memorize_batch": 20, "memorize_threshold": 2, "memorize_review_days": 7,
        "tts_allowed_voices": {"en-US-JennyNeural", "en-US-GuyNeural"},
        "tts_default_voice": "en-US-JennyNeural", "tts_rate_limit_per_hour": 30,
        "tts_max_concurrency": 2, "tts_lazy_max_files": 5000,
    }
    patches = [
        patch("backend.config.DB", db_path),
        patch("backend.config.AUDIO", audio_path),
        patch("backend.config.BASE", tmp_path),
        patch("backend.config.MATERIALS", test_materials),
        patch("backend.config.CONFIG", test_config),
        patch("backend.db.DB", db_path),
        patch("backend.materials.BASE", tmp_path),
        patch("backend.materials.AUDIO", audio_path),
        patch("backend.materials.MATERIALS", test_materials),
        patch("backend.catalog.AUDIO", audio_path),
        patch("backend.catalog.MATERIALS", test_materials),
        patch("backend.catalog.CONFIG", test_config),
        patch("backend.memorize.MATERIALS", test_materials),
        patch("backend.memorize.CONFIG", test_config),
        patch("backend.misc.AUDIO", audio_path),
        patch("backend.misc.CONFIG", test_config),
    ]
    for p in patches:
        p.start()
    application = create_app(static_dir=static_dir)
    application.config["TESTING"] = True
    yield application
    for p in reversed(patches):
        p.stop()


class CsrfClient(FlaskClient):
    """模拟浏览器：写请求自动携带前一响应签发的 CSRF token。"""
    def open(self, *args, **kwargs):
        method = kwargs.get("method", "GET").upper()
        if method in {"POST", "PUT", "PATCH", "DELETE"}:
            token = self.get_cookie("dict_csrf")
            if token:
                headers = dict(kwargs.get("headers") or {})
                headers.setdefault("X-CSRF-Token", token.value)
                kwargs["headers"] = headers
        return super().open(*args, **kwargs)


@pytest.fixture
def client(app):
    app.test_client_class = CsrfClient
    browser = app.test_client()
    browser.get("/api/auth/me")
    return browser

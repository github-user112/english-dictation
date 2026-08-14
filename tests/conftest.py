"""pytest 共享夹具"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from backend import create_app
from backend.materials import load_material


@pytest.fixture(autouse=True)
def clear_material_cache():
    """每个测试前清除素材加载缓存，避免跨 fixture 污染"""
    load_material.cache_clear()


@pytest.fixture
def app():
    """使用临时数据库的测试 Flask 应用"""
    tmp = Path(tempfile.mkdtemp())
    db_path = tmp / "test.db"
    audio_path = tmp / "audio"
    audio_path.mkdir()
    wordlists = tmp / "wordlists"
    wordlists.mkdir()
    sentences = tmp / "sentences"
    sentences.mkdir()

    test_materials = {
        "test_words": {"type": "words", "title": "Test Words"},
        "test_sents": {"type": "sentences", "title": "Test Sentences"},
    }

    # 写一个最小测试词库
    word_data = {"name": "Test", "words": [
        {"word": "hello", "phonetic": "/həˈloʊ/", "meaning": "int. 你好"},
        {"word": "world", "phonetic": "/wɜːrld/", "meaning": "n. 世界"},
        {"word": "apple", "phonetic": "/ˈæp.əl/", "meaning": "n. 苹果"},
    ]}
    (wordlists / "test_words.json").write_text(json.dumps(word_data), "utf-8")

    # 写一个最小测试句子素材
    sent_data = {"items": [
        {"id": 1, "en": "Hello world", "zh": "你好世界", "lesson": 1},
        {"id": 2, "en": "This is a test", "zh": "这是一个测试", "lesson": 1},
    ]}
    (sentences / "test_sents.json").write_text(json.dumps(sent_data), "utf-8")

    # 生成一些假音频文件
    (audio_path / "test_words").mkdir(exist_ok=True)
    hello_hash = "5d41402abc4b2a76b9719d911017c592"  # md5("hello")
    (audio_path / "test_words" / f"{hello_hash}.mp3").touch()

    test_config = {
        "new_per_day": 10, "max_review": 30, "known_threshold": 3,
        "memorize_batch": 20, "memorize_threshold": 2, "memorize_review_days": 7,
    }
    patches = [
        patch("backend.config.DB", db_path),
        patch("backend.config.AUDIO", audio_path),
        patch("backend.config.BASE", tmp),
        patch("backend.config.MATERIALS", test_materials),
        patch("backend.config.CONFIG", test_config),
        patch("backend.db.DB", db_path),
        patch("backend.materials.BASE", tmp),
        patch("backend.materials.AUDIO", audio_path),
        patch("backend.materials.MATERIALS", test_materials),
        patch("backend.catalog.AUDIO", audio_path),
        patch("backend.catalog.MATERIALS", test_materials),
        patch("backend.catalog.CONFIG", test_config),
        patch("backend.memorize.MATERIALS", test_materials),
        patch("backend.misc.AUDIO", audio_path),
    ]
    for p in patches:
        p.start()
    application = create_app()
    application.config["TESTING"] = True
    yield application
    for p in patches:
        p.stop()


@pytest.fixture
def client(app):
    return app.test_client()
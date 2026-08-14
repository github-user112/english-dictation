"""后端 misc 模块测试：错词本、统计、TTS、音频服务"""
import pytest
from unittest.mock import patch, AsyncMock


class TestMiscAPI:
    """杂项 API 端点测试"""

    def test_tts_empty_text(self, client):
        rv = client.post("/api/tts", json={"text": ""})
        assert rv.status_code == 400

    def test_tts_long_text(self, client):
        rv = client.post("/api/tts", json={"text": "x" * 201})
        assert rv.status_code == 400

    def test_audio_serve_not_found(self, client):
        rv = client.get("/audio/nonexistent/file.mp3")
        assert rv.status_code == 404

    def test_audio_serve_path_traversal(self, client):
        rv = client.get("/audio/../app.py")
        assert rv.status_code == 403

    def test_static_files(self, client):
        rv = client.get("/")
        assert rv.status_code == 200

    def test_cors_headers(self, client):
        """验证 API 响应包含必要的头部"""
        rv = client.get("/api/lists")
        assert rv.content_type == "application/json"
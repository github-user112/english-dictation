"""后端 misc 模块测试：错词本、统计、TTS、音频服务"""
import os
from unittest.mock import patch


class TestMiscAPI:
    """杂项 API 端点测试"""

    def test_tts_empty_text(self, client):
        rv = client.post("/api/tts", json={"text": ""})
        assert rv.status_code == 400

    def test_tts_long_text(self, client):
        rv = client.post("/api/tts", json={"text": "x" * 201})
        assert rv.status_code == 400

    def test_tts_rejects_unapproved_voice(self, client):
        rv = client.post("/api/tts", json={"text": "hello", "voice": "unsupported-voice"})
        assert rv.status_code == 400

    def test_tts_returns_cached_default_voice_audio(self, client):
        from backend.misc import AUDIO
        from backend.materials import audio_filename

        lazy = AUDIO / "lazy"
        lazy.mkdir()
        filename = audio_filename("hello")
        (lazy / filename).write_bytes(b"fake-mp3")
        rv = client.post("/api/tts", json={"text": "hello"})
        assert rv.status_code == 200
        assert rv.json == {"url": f"/audio/lazy/{filename}", "cached": True}

    def test_tts_caches_each_allowed_voice_separately(self, client):
        class FakeCommunicate:
            def __init__(self, text, voice):
                self.text = text
                self.voice = voice

            async def save(self, path):
                from pathlib import Path
                Path(path).write_bytes(f"{self.voice}:{self.text}".encode())

        with patch("backend.misc.edge_tts.Communicate", FakeCommunicate):
            default = client.post("/api/tts", json={"text": "hello"})
            alternate = client.post("/api/tts", json={"text": "hello", "voice": "en-US-GuyNeural"})
        assert default.status_code == alternate.status_code == 200
        assert default.json["cached"] is False
        assert alternate.json["cached"] is False
        assert default.json["url"] != alternate.json["url"]

    def test_tts_generated_audio_is_web_readable(self, client):
        class FakeCommunicate:
            def __init__(self, text, voice):
                pass

            async def save(self, path):
                from pathlib import Path
                Path(path).write_bytes(b"fake-mp3")

        previous_umask = os.umask(0o027)
        try:
            with patch("backend.misc.edge_tts.Communicate", FakeCommunicate):
                response = client.post("/api/tts", json={"text": "web-readable"})
        finally:
            os.umask(previous_umask)

        from backend.misc import AUDIO
        generated = AUDIO / response.json["url"].removeprefix("/audio/")
        assert generated.stat().st_mode & 0o777 == 0o644

    def test_audio_serve_not_found(self, client):
        rv = client.get("/audio/nonexistent/file.mp3")
        assert rv.status_code == 404

    def test_audio_serve_path_traversal(self, client):
        rv = client.get("/audio/../app.py")
        assert rv.status_code == 403

    def test_static_files(self, client):
        rv = client.get("/")
        assert rv.status_code == 200

    def test_api_response_is_json(self, client):
        rv = client.get("/api/lists")
        assert rv.content_type == "application/json"

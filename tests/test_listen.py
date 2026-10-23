"""按课听录音接口测试：整课区间推导、逐句时间轴、降级模式、校验。

关键回归：当多个课的时间戳落在同一个音频文件里（当前四册都是一课一文件，
属防御性用例），第 1 课的播放区间必须只取本课句子的时间戳。
"""
import json

import backend.config
import backend.materials

USER = "b" * 32


def get(client, path):
    sep = "&" if "?" in path else "?"
    return client.get(f"{path}{sep}u={USER}")


def write_map(entries, mp3=True):
    audio_dir = backend.config.AUDIO / "test_sents"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "nce_audio_map.json").write_text(json.dumps(entries), "utf-8")
    if mp3:
        for seg in entries.values():
            (audio_dir / seg["file"]).touch()
    backend.materials._NCE_MAP_CACHE.pop("test_sents", None)


def test_listen_file_mode_clamps_to_lesson(client):
    # 第 1、2 课的时间戳落在同一个音频文件里——课的区间只取本课句子
    write_map({
        "1": {"file": "lesson.mp3", "start": 2.0, "end": 5.0},
        "2": {"file": "lesson.mp3", "start": 5.5, "end": 9.0},
        "3": {"file": "lesson.mp3", "start": 60.0, "end": 63.0},
        "4": {"file": "lesson.mp3", "start": 63.5, "end": 66.0},
    })
    r = get(client, "/api/listen/session?list=test_sents&lesson=1")
    assert r.status_code == 200
    d = r.get_json()
    assert d["mode"] == "file"
    assert d["file"] == "/audio/test_sents/lesson.mp3"
    assert d["start"] == 2.0 and d["end"] == 9.0   # 不含第 2 课时间戳
    assert [i["text"] for i in d["items"]] == ["Hello world", "This is a test"]
    assert all(i["audio"] and i["zh"] for i in d["items"])
    assert [i["start"] for i in d["items"]] == [2.0, 5.5]


def test_listen_missing_timestamp_keeps_file_mode(client):
    # 个别句子缺时间轴（生产数据里 nc1/nc3/nc4 共 8 句），不破坏整课原声模式
    write_map({
        "1": {"file": "lesson.mp3", "start": 2.0, "end": 5.0},
        # 第 2 句缺
        "3": {"file": "lesson.mp3", "start": 60.0, "end": 63.0},
        "4": {"file": "lesson.mp3", "start": 63.5, "end": 66.0},
    })
    d = get(client, "/api/listen/session?list=test_sents&lesson=1").get_json()
    assert d["mode"] == "file"
    assert d["start"] == 2.0 and d["end"] == 5.0
    assert d["items"][1]["start"] is None and d["items"][1]["end"] is None
    assert d["items"][1]["audio"]   # 无时间轴也有逐句音频兜底


def test_listen_sentences_mode_without_map(client):
    d = get(client, "/api/listen/session?list=test_sents&lesson=1").get_json()
    assert d["mode"] == "sentences"
    assert "file" not in d
    assert all(i["audio"] for i in d["items"])
    assert all(i["start"] is None for i in d["items"])


def test_listen_unmapped_sentence_prefers_id_named_file(client):
    # 口语900句这类素材没有 nce_audio_map.json，逐句原声按 <id>.mp3 命名。
    # 必须返回真录音，别回落成可能不存在的 /audio/lazy/<md5> 懒生成地址。
    audio_dir = backend.config.AUDIO / "test_sents"
    audio_dir.mkdir(parents=True, exist_ok=True)
    (audio_dir / "1.mp3").touch()
    (audio_dir / "2.mp3").touch()
    d = get(client, "/api/listen/session?list=test_sents&lesson=1").get_json()
    assert d["mode"] == "sentences"
    assert [i["audio"] for i in d["items"]] == [
        "/audio/test_sents/1.mp3", "/audio/test_sents/2.mp3"]


def test_listen_file_missing_falls_back_to_sentences(client):
    # 时间轴写好了，但音频文件不在磁盘上——退回逐句串播，不报坏播放器
    write_map({
        "1": {"file": "lesson.mp3", "start": 2.0, "end": 5.0},
        "2": {"file": "lesson.mp3", "start": 5.5, "end": 9.0},
    }, mp3=False)
    d = get(client, "/api/listen/session?list=test_sents&lesson=1").get_json()
    assert d["mode"] == "sentences"
    assert "file" not in d


def test_listen_validation(client):
    assert get(client, "/api/listen/session?list=test_words&lesson=1").status_code == 400   # 词汇素材不收
    assert get(client, "/api/listen/session?list=nope&lesson=1").status_code == 404         # 未知素材
    assert get(client, "/api/listen/session?list=test_sents").status_code == 400            # 必须带课号
    assert get(client, "/api/listen/session?list=test_sents&lesson=abc").status_code == 400
    assert get(client, "/api/listen/session?list=test_sents&lesson=99").status_code == 404  # 课号不存在

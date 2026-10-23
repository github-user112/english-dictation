"""听读模式：按课顺序出句，跟读打分在浏览器端完成（Web Speech API），服务端只供题。

完成记账（/api/shadow/done）：语音识别没有服务端重放的可能，所以只把
"良好句数"记进 daily_practice_log.review_count（零经验列）——喂今日动线的
跟读环与 streak/浇水，但客户端断言的成绩永远不该变成 XP。
"""
from urllib.parse import quote

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import AUDIO, MATERIALS
from .db import db
from .materials import audio_segment, audio_url, iter_material
from .misc import local_today

bp = Blueprint("shadow", __name__)


@bp.get("/api/shadow/session")
def api_shadow_session():
    get_user()   # 与其它 session 端点一致：确保游客 cookie 下发
    list_key = request.args.get("list", "nc1")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "sentences":
        return jsonify({"error": "听读仅支持句子素材"}), 400
    raw = request.args.get("lesson")
    try:
        lesson = int(raw) if raw else None
    except ValueError:
        return jsonify({"error": "课号无效"}), 400
    items = [{
        "id": it["id"], "text": it["text"], "zh": it.get("meaning") or "",
        "audio": audio_url(list_key, it["id"], it["text"]),
    } for it in iter_material(list_key, lesson)]
    if not items:
        return jsonify({"error": "课程不存在"}), 404
    return resp({"list": list_key, "lesson": lesson, "items": items, "total": len(items)})


@bp.get("/api/listen/session")
def api_listen_session():
    """按课听录音：整课原声 + 逐句时间轴。只读、不判分、不记账。

    课的播放区间 = 该课"有时间轴"句子的 min(start) ~ max(end)。只有这些
    句子全部落在同一个音频文件才给整课文件（否则逐句串播）；个别句子缺
    时间轴时仍给整课文件，前端把那几句降级成单句音频。这样若素材将来把
    一课拆到两个文件、或把一课放进多课文件，都会安全降级而不是播错区间。
    无时间轴的素材（口语900句）退化为逐句音频，前端按句串播。
    """
    get_user()   # 与其它 session 端点一致：确保游客 cookie 下发
    list_key = request.args.get("list", "nc1")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "sentences":
        return jsonify({"error": "听录音仅支持句子素材"}), 400
    raw = request.args.get("lesson")
    try:
        lesson = int(raw) if raw else None
    except ValueError:
        return jsonify({"error": "课号无效"}), 400
    if lesson is None:
        return jsonify({"error": "请指定课号"}), 400
    items = list(iter_material(list_key, lesson))
    if not items:
        return jsonify({"error": "课程不存在"}), 404

    sentences = []
    files = set()
    for it in items:
        seg = audio_segment(list_key, it["id"])
        if seg:
            files.add(seg["file"])
        sentences.append({
            "id": it["id"], "text": it["text"], "zh": it.get("meaning") or "",
            "start": seg["start"] if seg else None,
            "end": seg["end"] if seg else None,
            "audio": audio_url(list_key, it["id"], it["text"]),
        })
    payload = {"list": list_key, "lesson": lesson, "items": sentences, "total": len(sentences)}
    timed = [s for s in sentences if s["start"] is not None]
    if len(files) == 1 and timed:
        fname = next(iter(files))
        if (AUDIO / list_key / fname).exists():
            payload.update({
                "mode": "file",
                "file": f"/audio/{list_key}/{quote(fname)}",
                "start": min(s["start"] for s in timed),
                "end": max(s["end"] for s in timed),
            })
    payload.setdefault("mode", "sentences")
    return resp(payload)


@bp.post("/api/shadow/done")
def api_shadow_done():
    """跟读完成记账：good（≥85 分句数）落 review_count，幂等按 (日,用户,模式) 累加。

    校验只做范围钳制（good ≤ total ≤ 该课实际句数）——分数本身无法服务端核验，
    所以本端点不产生任何 XP，伪造它只能骗到自己的打卡环。
    """
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    list_key = data.get("list")
    if list_key not in MATERIALS:
        return jsonify({"error": "未知素材"}), 404
    if MATERIALS[list_key]["type"] != "sentences":
        return jsonify({"error": "听读仅支持句子素材"}), 400
    lesson = data.get("lesson")
    if lesson is not None and (isinstance(lesson, bool) or not isinstance(lesson, int)):
        return jsonify({"error": "课号无效"}), 400
    good, total = data.get("good"), data.get("total")
    expected = sum(1 for _ in iter_material(list_key, lesson))
    if expected == 0:
        return jsonify({"error": "课程不存在"}), 404
    if isinstance(good, bool) or not isinstance(good, int) \
            or isinstance(total, bool) or not isinstance(total, int) \
            or not 0 <= good <= total or total > expected:
        return jsonify({"error": "句数无效"}), 400

    today = local_today().isoformat()
    with db() as conn:
        conn.execute(
            """INSERT INTO daily_practice_log(day,user,practice_mode,new_count,review_count,
                   first_right_count,first_wrong_count,final_right_count,skipped_count)
               VALUES(?,?,'shadow',0,?,0,0,0,0)
               ON CONFLICT(day,user,practice_mode) DO UPDATE SET
                   review_count=review_count+excluded.review_count""",
            (today, user, good))
    return resp({"recorded": True, "good": good})

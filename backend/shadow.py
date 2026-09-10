"""听读模式：按课顺序出句，跟读打分在浏览器端完成（Web Speech API），服务端只供题。"""
from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import MATERIALS
from .materials import audio_url, iter_material

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

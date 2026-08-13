"""用户识别：URL ?u= 优先，cookie 兜底"""
import uuid as uuid_mod

from flask import jsonify, make_response, request

from .config import COOKIE


def get_user():
    u = request.args.get("u")
    if u and len(u) == 32 and u.isalnum():
        return u
    u = request.cookies.get(COOKIE)
    if u and len(u) == 32 and u.isalnum():
        return u
    return uuid_mod.uuid4().hex


def resp(obj):
    """将 user 写入响应（cookie 记住 + JSON 返回，前端拼到 URL 后面）"""
    u = get_user()
    r = make_response(jsonify({**obj, "user": u}))
    r.set_cookie(COOKIE, u, max_age=31536000, httponly=False, samesite="Lax")
    return r

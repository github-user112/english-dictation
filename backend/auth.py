"""用户识别：URL ?u= 优先，cookie 兜底。
（公开站点无密码；接口限流由 nginx 负责，见 dictation.conf。）"""
import uuid as uuid_mod

from flask import g, jsonify, make_response, request

from .config import COOKIE


def get_user():
    if hasattr(g, "dict_user"):
        return g.dict_user
    u = request.args.get("u")
    if u and len(u) == 32 and u.isalnum():
        g.dict_user = u
    else:
        u = request.cookies.get(COOKIE)
        g.dict_user = u if u and len(u) == 32 and u.isalnum() else uuid_mod.uuid4().hex
    return g.dict_user


def resp(obj):
    """将 user 写入响应（cookie 记住 + JSON 返回，前端拼到 URL 后面）"""
    u = get_user()
    r = make_response(jsonify({**obj, "user": u}))
    r.set_cookie(COOKIE, u, max_age=31536000, httponly=False, samesite="Lax")
    return r

"""Flask 应用工厂"""
from pathlib import Path

from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

from . import (achievements, ai, arrange, auth_routes, boss, catalog, challenge, custom,
               daily, db as dbmod, friends, goal, groups, leaderboard, match, memorize,
               misc, pk, profile, push)
from .auth import csrf_valid, legacy_account_protected
from .config import STATIC_DIR
from .materials import MaterialUnavailable


def create_app(*, static_dir=None):
    """创建应用；测试可传入隔离的静态目录。"""
    asset_root = Path(static_dir) if static_dir is not None else STATIC_DIR
    app = Flask(__name__, static_folder=str(asset_root))
    dbmod.init_db()
    dbmod.migrate()
    for mod in (achievements, ai, arrange, auth_routes, boss, catalog, challenge, custom,
                daily, friends, goal, groups, leaderboard, match, memorize, misc, pk,
                profile, push):
        app.register_blueprint(mod.bp)
    # WebSocket 路由挂在独立 Sock 蓝图上，须在业务蓝图之后 init_app
    pk.init_app(app)
    # 每日提醒守护线程（进程内只起一次；多 worker 由 DB 认领保证只发一轮）
    push.start_reminder_thread()

    @app.before_request
    def protect_api_requests():
        if not request.path.startswith("/api/"):
            return None
        if not request.path.startswith("/api/auth/") and legacy_account_protected():
            return jsonify({"error": "该学习档案已受账户保护，请登录", "account_protected": True}), 401
        if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
            return None
        origin = request.headers.get("Origin")
        if origin and urlparse(origin).netloc != request.host:
            return jsonify({"error": "请求来源不受信任"}), 403
        if request.path not in {"/api/auth/login", "/api/auth/register"} and not csrf_valid():
            return jsonify({"error": "请求验证已过期，请刷新后重试"}), 403
        return None

    @app.errorhandler(MaterialUnavailable)
    def unavailable_material(error):
        return jsonify({"error": str(error)}), 503

    @app.get("/")
    def index():
        return send_from_directory(app.static_folder, "index.html")

    @app.get("/static/<path:filename>")
    def static_files(filename):
        return send_from_directory(app.static_folder, filename)

    @app.get("/favicon.ico")
    @app.get("/favicon.png")
    def favicon():
        return send_from_directory(app.static_folder, request.path.lstrip("/"))

    @app.get("/sw.js")
    def service_worker():
        # Service Worker 必须在根路径下注册才能拿到 "/" 作用域（Web Push 提醒用）
        return send_from_directory(app.static_folder, "sw.js")

    @app.get("/assets/<path:filename>")
    def asset_files(filename):
        return send_from_directory(asset_root / "assets", filename)

    return app

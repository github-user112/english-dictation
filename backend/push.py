"""Web Push 每日提醒：VAPID 订阅管理、到期目标查询与定时发送。

私钥存 data/vapid_key.pem（gitignore），公钥现算后缓存。
提醒发送由应用内守护线程驱动（本机 /home 只读挂不进 cron/systemd timer）：
每 30 分钟醒一次，20 点后若今日未发过则发——push_meta.last_remind 行
用 BEGIN IMMEDIATE 抢锁认领，多 worker 也只有一个会真正发送。
"""
import base64
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .catalog import now
from .db import db

bp = Blueprint("push", __name__)

VAPID_KEY_FILE = Path(os.environ.get(
    "ENGLISH_DICTATION_VAPID_KEY",
    Path(__file__).resolve().parent.parent / "data" / "vapid_key.pem"))
VAPID_SUB = os.environ.get("ENGLISH_DICTATION_VAPID_SUB", "mailto:admin@pjgg2023.eu.org")

_pub_cache = None


def vapid_public_key():
    """base64url 应用服务器公钥（P-256 未压缩点），供前端 pushManager.subscribe。"""
    global _pub_cache
    if _pub_cache is None:
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        from py_vapid import Vapid
        v = Vapid.from_pem(VAPID_KEY_FILE.read_bytes())
        raw = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
        _pub_cache = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    return _pub_cache


def due_reminders(conn):
    """今天还没完成背诵目标的用户：[{user, list, missing}]。cron 脚本据此发推送。"""
    from .goal import _goal_view
    due = []
    rows = conn.execute("SELECT * FROM study_goal").fetchall()
    for row in rows:
        view = _goal_view(conn, row["user"], row["list"], row)
        missing = view["daily_new"] - view["today_done"]
        if not view["done"] and missing > 0:
            due.append({"user": row["user"], "list": row["list"], "missing": missing})
    return due


def subscriptions_for(conn, user):
    return conn.execute(
        "SELECT endpoint,p256dh,auth FROM push_subscription WHERE user=?", (user,)).fetchall()


REMIND_HOUR = 20          # 本地时间 20 点后才提醒
_TICK_SECONDS = 30 * 60


def send_payload(sub, payload):
    """发一条推送。返回 True=送达或临时失败（保留订阅），False=订阅失效（应删除）。"""
    from pywebpush import WebPushException, webpush
    try:
        webpush(
            subscription_info={"endpoint": sub["endpoint"],
                               "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=str(VAPID_KEY_FILE),
            vapid_claims={"sub": VAPID_SUB},
            timeout=15,
        )
        return True
    except WebPushException as exc:
        code = exc.response.status_code if exc.response is not None else 0
        if code in (404, 410):
            return False
        print(f"push warn: {sub['endpoint'][:60]}… -> {code} {exc}", flush=True)
        return True


def remind_today(now_dt=None, force=False):
    """给今日未达标用户发提醒。返回是否执行了发送轮（已被认领/未到点返回 False）。"""
    now = now_dt or datetime.now()
    if not force and now.hour < REMIND_HOUR:
        return False
    if not VAPID_KEY_FILE.exists():
        return False
    today = now.date().isoformat()
    with db() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT value FROM push_meta WHERE name='last_remind'").fetchone()
        if not force and row and row["value"] >= today:
            return False
        conn.execute(
            "INSERT INTO push_meta(name,value) VALUES('last_remind',?) "
            "ON CONFLICT(name) DO UPDATE SET value=excluded.value", (today,))
        due = due_reminders(conn)
        subs = {u: subscriptions_for(conn, u) for u in {d["user"] for d in due}}
        stale = []
        for item in due:
            for sub in subs.get(item["user"], []):
                if not send_payload(sub, {
                        "title": "📖 今天的目标还没完成",
                        "body": f"今日计划还差 {item['missing']} 个词，点我接着背",
                        "url": f"/#/memorize?list={item['list']}"}):
                    stale.append(sub["endpoint"])
        for endpoint in stale:
            conn.execute("DELETE FROM push_subscription WHERE endpoint=?", (endpoint,))
    print(f"push remind: due={len(due)} stale_removed={len(stale)}", flush=True)
    return True


_thread_started = False


def start_reminder_thread():
    """应用内提醒调度：半小时一拍，到点且未被认领则发一轮。进程内幂等。"""
    global _thread_started
    if _thread_started:
        return
    _thread_started = True

    def loop():
        while True:
            time.sleep(_TICK_SECONDS)
            for task in (remind_today, _news_tick):
                try:
                    task()
                except Exception as exc:   # 网络/DB 抖动不杀线程
                    print(f"scheduled task error: {exc}", flush=True)
    threading.Thread(target=loop, daemon=True, name="push-remind").start()


def _news_tick():
    from . import newsfetch
    newsfetch.maybe_refresh()


@bp.get("/api/push/key")
def api_push_key():
    if not VAPID_KEY_FILE.exists():
        return jsonify({"error": "推送服务未配置"}), 503
    return resp({"public_key": vapid_public_key()})


@bp.post("/api/push/subscribe")
def api_push_subscribe():
    user = get_user()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "请求体无效"}), 400
    endpoint = data.get("endpoint")
    keys = data.get("keys") or {}
    p256dh, auth = keys.get("p256dh"), keys.get("auth")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 500 \
            or not isinstance(p256dh, str) or not 10 <= len(p256dh) <= 200 \
            or not isinstance(auth, str) or not 10 <= len(auth) <= 100:
        return jsonify({"error": "订阅参数无效"}), 400
    with db() as conn:
        # endpoint 即主键：同一浏览器换账号登录时归属跟着最新身份走
        conn.execute(
            """INSERT INTO push_subscription(endpoint,user,p256dh,auth,created_at) VALUES(?,?,?,?,?)
               ON CONFLICT(endpoint) DO UPDATE SET user=excluded.user,
                   p256dh=excluded.p256dh, auth=excluded.auth""",
            (endpoint, user, p256dh, auth, now()))
    return resp({"ok": True})


@bp.delete("/api/push/subscribe")
def api_push_unsubscribe():
    user = get_user()
    data = request.get_json(silent=True)
    endpoint = isinstance(data, dict) and data.get("endpoint") or ""
    with db() as conn:
        conn.execute("DELETE FROM push_subscription WHERE endpoint=? AND user=?", (endpoint, user))
    return resp({"ok": True})

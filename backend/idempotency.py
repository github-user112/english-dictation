"""计分接口幂等 + 单日上限：防重放刷经验。

每个计分写接口接收客户端提交的 attempt_id（页级生成，常含题目 id 前缀以区分
会话内各题）。服务端以 (user, endpoint, attempt_id) 三元组做去重——已存则
返回 "duplicate" 不再加分；未存则先查当日累计是否超上限，再放行，由调用方
在业务逻辑完成后调用 mark_done() 落 attempt 记录。

memorize 接口已有专属 memorize_attempt 表，走同套路但沿用其表（不改生产数据）。
这里覆盖：legacy result (sprint/quiz/wrong) / match / boss / arrange。
"""
from datetime import date, datetime, timezone

from flask import jsonify

# 与 catalog.now() 同口径（UTC ISO 带时区）。
# 定义在此处而非从 catalog 导入：idempotency 是 catalog 的依赖模块，
# 反向 import 会形成循环；本 helper 只有 6 行，自包含更安全。
def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

SCORE_CAPS = {
    "result": 300,
    "match": 30,
    "boss": 20,
    "arrange": 200,
}


def validate_attempt_id(attempt_id):
    """返回 (attempt_id, error_or_None)。error=None 表示合法。"""
    if not attempt_id:
        return None, None
    if not isinstance(attempt_id, str) or not 1 <= len(attempt_id) <= 128:
        return None, ("attempt_id 无效", 400)
    cleaned = attempt_id.replace("-", "")
    if not cleaned.isalnum():
        return None, ("attempt_id 无效", 400)
    return attempt_id, None


def check_and_mark(conn, user, endpoint, attempt_id):
    """幂等检查 + 当日封顶，返回状态串 / 元组：

      "duplicate"           已有记录 → 调用方直接 return duplicate 响应
      "capped"              当日超上限 → 调用方 return (json, 429)
      (json, 429)           capped 时附带的错误响应
      "ok"                  放行 → 调用方做业务逻辑后调 mark_done()
    """
    row = conn.execute(
        "SELECT 1 FROM score_attempt WHERE user=? AND endpoint=? AND attempt_id=?",
        (user, endpoint, attempt_id),
    ).fetchone()
    if row:
        return "duplicate", None
    today = date.today().isoformat()
    count = conn.execute(
        "SELECT COUNT(*) c FROM score_attempt WHERE user=? AND endpoint=? AND day=?",
        (user, endpoint, today),
    ).fetchone()["c"]
    cap = SCORE_CAPS.get(endpoint, 200)
    if count >= cap:
        return "capped", (jsonify({"error": "今日次数已达上限"}), 429)
    return "ok", None


def mark_done(conn, user, endpoint, attempt_id):
    """放行后落 attempt 记录，供后续重放/上限计数。与 check_and_mark 同事务。"""
    today = date.today().isoformat()
    conn.execute(
        "INSERT INTO score_attempt(user, endpoint, attempt_id, day, created_at) "
        "VALUES(?,?,?,?,?)",
        (user, endpoint, attempt_id, today, now()),
    )

"""数据库：连接 / 建表 / 迁移"""
import json
import sqlite3
from contextlib import contextmanager

from .config import DB


@contextmanager
def db(immediate=False):
    """连接上下文：成功提交、异常回滚、退出关闭。

    sqlite3 连接自身的 with 只提交不关闭，长期运行会依赖 GC 兜底回收 fd；
    这里显式 close，事务语义与原先 `with sqlite3.connect(...)` 完全一致。
    immediate=True 用 BEGIN IMMEDIATE 开事务：先取写锁再读，供读-改-写
    路径（PK 判分）在 gunicorn 多 worker 下不丢更新。
    """
    conn = sqlite3.connect(str(DB))
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        if immediate:
            conn.execute("BEGIN IMMEDIATE")
        with conn:
            yield conn
    finally:
        conn.close()


def init_db():
    DB.parent.mkdir(exist_ok=True)
    with db() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS word_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL DEFAULT 'default',
            list TEXT NOT NULL,
            item_id TEXT NOT NULL,
            kind TEXT DEFAULT 'word',
            status TEXT DEFAULT 'new',
            wrong_count INTEGER DEFAULT 0,
            right_count INTEGER DEFAULT 0,
            consecutive_right INTEGER DEFAULT 0,
            last_seen TEXT,
            next_review TEXT,
            memorized INTEGER DEFAULT 0,
            memorize_count INTEGER DEFAULT 0,
            last_memorize TEXT,
            UNIQUE(user, list, item_id)
        );
        CREATE TABLE IF NOT EXISTS daily_log (
            day TEXT NOT NULL,
            user TEXT NOT NULL DEFAULT 'default',
            new_count INTEGER DEFAULT 0,
            review_count INTEGER DEFAULT 0,
            right_count INTEGER DEFAULT 0,
            wrong_count INTEGER DEFAULT 0,
            memorize_right INTEGER DEFAULT 0,
            memorize_wrong INTEGER DEFAULT 0,
            PRIMARY KEY(day, user)
        );
        CREATE TABLE IF NOT EXISTS daily_plan (
            day TEXT NOT NULL, user TEXT NOT NULL, list TEXT NOT NULL,
            new_quota INTEGER NOT NULL, allocated_new INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            PRIMARY KEY(day, user, list)
        );
        CREATE TABLE IF NOT EXISTS study_session (
            id TEXT PRIMARY KEY, user TEXT NOT NULL, list TEXT NOT NULL,
            practice_mode TEXT NOT NULL, scope TEXT NOT NULL DEFAULT 'all',
            strategy TEXT NOT NULL DEFAULT 'daily', lesson INTEGER,
            assigned_day TEXT NOT NULL, requested_new INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL, completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS study_session_item (
            session_id TEXT NOT NULL, seq INTEGER NOT NULL, item_id TEXT NOT NULL,
            kind TEXT NOT NULL, phase TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending',
            first_right INTEGER, final_right INTEGER,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            first_answer_at TEXT, answered_at TEXT, first_typed TEXT,
            PRIMARY KEY(session_id, item_id), UNIQUE(session_id, seq),
            FOREIGN KEY(session_id) REFERENCES study_session(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS daily_practice_log (
            day TEXT NOT NULL, user TEXT NOT NULL, practice_mode TEXT NOT NULL,
            new_count INTEGER NOT NULL DEFAULT 0, review_count INTEGER NOT NULL DEFAULT 0,
            first_right_count INTEGER NOT NULL DEFAULT 0,
            first_wrong_count INTEGER NOT NULL DEFAULT 0,
            final_right_count INTEGER NOT NULL DEFAULT 0,
            skipped_count INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(day, user, practice_mode)
        );
        CREATE TABLE IF NOT EXISTS account (
            user_id TEXT PRIMARY KEY,
            username TEXT NOT NULL COLLATE NOCASE UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL,
            last_login_at TEXT,
            disabled_at TEXT
        );
        CREATE TABLE IF NOT EXISTS auth_session (
            token_hash TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            csrf_token TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES account(user_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS auth_rate_limit (
            scope TEXT NOT NULL,
            key TEXT NOT NULL,
            window_started_at INTEGER NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(scope, key)
        );
        CREATE TABLE IF NOT EXISTS memorize_attempt (
            user TEXT NOT NULL, attempt_id TEXT NOT NULL,
            list TEXT NOT NULL, item_id TEXT NOT NULL, right INTEGER NOT NULL,
            memorized INTEGER NOT NULL, memorize_count INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user, attempt_id)
        );
        CREATE TABLE IF NOT EXISTS score_attempt (
            user TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            attempt_id TEXT NOT NULL,
            day TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user, endpoint, attempt_id)
        );
        CREATE INDEX IF NOT EXISTS idx_score_attempt_user_day
            ON score_attempt(user, endpoint, day);
        CREATE TABLE IF NOT EXISTS sprint_best (
            user TEXT PRIMARY KEY,
            score INTEGER NOT NULL DEFAULT 0,
            combo INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS custom_material (
            id TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            title TEXT NOT NULL,
            sentences TEXT NOT NULL,
            sentence_count INTEGER,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_custom_material_user
            ON custom_material(user, created_at);
        CREATE TABLE IF NOT EXISTS sprint_challenge (
            id TEXT PRIMARY KEY,
            owner_user TEXT NOT NULL,
            owner_name TEXT NOT NULL DEFAULT '',
            list_key TEXT NOT NULL,
            items TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sprint_challenge_score (
            challenge_id TEXT NOT NULL,
            user TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL DEFAULT 0,
            combo INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(challenge_id, user)
        );
        CREATE TABLE IF NOT EXISTS daily_challenge (
            day TEXT NOT NULL,
            user TEXT NOT NULL,
            list_key TEXT NOT NULL,
            score INTEGER NOT NULL DEFAULT 0,
            total INTEGER NOT NULL DEFAULT 0,
            detail TEXT NOT NULL DEFAULT '[]',
            completed_at TEXT NOT NULL,
            PRIMARY KEY(day, user)
        );
        CREATE INDEX IF NOT EXISTS idx_daily_challenge_user
            ON daily_challenge(user, day);
        CREATE INDEX IF NOT EXISTS idx_auth_session_user_expiry
            ON auth_session(user_id, expires_at);
        CREATE INDEX IF NOT EXISTS idx_word_state_review
            ON word_state(user, list, status, next_review);
        CREATE INDEX IF NOT EXISTS idx_word_state_memorize
            ON word_state(user, list, memorized, last_memorize);
        CREATE INDEX IF NOT EXISTS idx_word_state_wrong
            ON word_state(user, wrong_count, last_seen);
        CREATE INDEX IF NOT EXISTS idx_study_session_user_state
            ON study_session(user, state, created_at);
        CREATE INDEX IF NOT EXISTS idx_study_session_active_lookup
            ON study_session(user, list, practice_mode, scope, strategy, lesson, state, updated_at);
        CREATE INDEX IF NOT EXISTS idx_session_item_pending
            ON study_session_item(session_id, state, seq);
        CREATE INDEX IF NOT EXISTS idx_daily_practice_user_day
            ON daily_practice_log(user, day);
        CREATE INDEX IF NOT EXISTS idx_daily_log_user
            ON daily_log(user, day);
        CREATE TABLE IF NOT EXISTS friend_relation (
            user_a TEXT NOT NULL,
            user_b TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            requested_by TEXT,       -- pending 方向：谁发起的申请
            created_at TEXT NOT NULL,
            updated_at TEXT,
            PRIMARY KEY(user_a, user_b),
            CHECK(user_a < user_b)   -- 双向请求规范化到同一行，杜绝 A→B 与 B→A 并存
        );
        CREATE INDEX IF NOT EXISTS idx_friend_relation_b ON friend_relation(user_b, status);
        CREATE TABLE IF NOT EXISTS friend_activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            kind TEXT NOT NULL,      -- sprint_record | daily_complete | level_up | friend_join
            detail TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_friend_activity_user
            ON friend_activity(user, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_friend_activity_created ON friend_activity(created_at);
        -- 升级推送的基线记账（内部状态，不随动态下发给前端）
        CREATE TABLE IF NOT EXISTS friend_level_seen (
            user TEXT PRIMARY KEY,
            level INTEGER NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS study_group (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            creator TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS group_member (
            group_id TEXT NOT NULL,
            user TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'member',   -- owner | member
            joined_at TEXT NOT NULL,
            PRIMARY KEY(group_id, user),
            FOREIGN KEY(group_id) REFERENCES study_group(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_group_member_user ON group_member(user);
        CREATE TABLE IF NOT EXISTS group_challenge (
            id TEXT PRIMARY KEY,
            group_id TEXT NOT NULL,
            creator TEXT NOT NULL,
            kind TEXT NOT NULL,      -- daily（每日挑战同题比分）| words_target（窗口内累计答对词数）
            config TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            FOREIGN KEY(group_id) REFERENCES study_group(id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_group_challenge_group
            ON group_challenge(group_id, expires_at);
        CREATE TABLE IF NOT EXISTS pk_room (
            code TEXT PRIMARY KEY,
            creator TEXT NOT NULL,
            opponent TEXT,
            list_key TEXT NOT NULL,
            items TEXT NOT NULL,     -- JSON 词流，双方同一份
            state TEXT NOT NULL DEFAULT 'waiting',  -- waiting | playing | finished
            version INTEGER NOT NULL DEFAULT 0,     -- 每次状态/比分变更 +1，长连接轮询据此增量推送
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_pk_room_creator ON pk_room(creator, state);
        CREATE TABLE IF NOT EXISTS study_goal (
            user TEXT NOT NULL,
            list TEXT NOT NULL,
            target_days INTEGER NOT NULL,
            start_day TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user, list)
        );
        CREATE TABLE IF NOT EXISTS ai_cache (
            user TEXT NOT NULL,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY(user, kind, key)
        );
        CREATE TABLE IF NOT EXISTS push_meta (
            name TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS push_subscription (
            endpoint TEXT PRIMARY KEY,
            user TEXT NOT NULL,
            p256dh TEXT NOT NULL,
            auth TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS pk_result (
            room_code TEXT NOT NULL,
            user TEXT NOT NULL,
            name TEXT NOT NULL DEFAULT '',
            score INTEGER NOT NULL DEFAULT 0,
            combo INTEGER NOT NULL DEFAULT 0,
            answered INTEGER NOT NULL DEFAULT 0,
            answers TEXT,              -- JSON {index: bool}，服务端校验后的逐词结果
            finished_at TEXT,
            PRIMARY KEY(room_code, user),
            FOREIGN KEY(room_code) REFERENCES pk_room(code) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_pk_result_user ON pk_result(user, finished_at);
        CREATE TABLE IF NOT EXISTS wordtest_result (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user TEXT NOT NULL,
            level INTEGER NOT NULL,
            questions_answered INTEGER NOT NULL,
            correct_count INTEGER NOT NULL,
            cefr TEXT NOT NULL,
            word_count INTEGER NOT NULL,
            detail TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wordtest_user ON wordtest_result(user, created_at DESC);
        """)


def migrate():
    """旧库（无 user 列 / 无背诵列）迁移"""
    with db() as conn:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(word_state)").fetchall()]
        if "user" not in cols:
            conn.executescript("""
            ALTER TABLE word_state RENAME TO word_state_old;
            CREATE TABLE word_state (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user TEXT NOT NULL DEFAULT 'default',
                list TEXT NOT NULL, item_id TEXT NOT NULL, kind TEXT DEFAULT 'word',
                status TEXT DEFAULT 'new', wrong_count INTEGER DEFAULT 0,
                right_count INTEGER DEFAULT 0, consecutive_right INTEGER DEFAULT 0,
                last_seen TEXT, next_review TEXT,
                UNIQUE(user, list, item_id)
            );
            INSERT INTO word_state (user, list, item_id, kind, status, wrong_count, right_count,
                                    consecutive_right, last_seen, next_review)
            SELECT 'default', list, item_id, kind, status, wrong_count, right_count,
                   consecutive_right, last_seen, next_review FROM word_state_old;
            DROP TABLE word_state_old;
            """)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(daily_log)").fetchall()]
        if "user" not in cols:
            conn.executescript("""
            ALTER TABLE daily_log RENAME TO daily_log_old;
            CREATE TABLE daily_log (
                day TEXT NOT NULL, user TEXT NOT NULL DEFAULT 'default',
                new_count INTEGER DEFAULT 0, review_count INTEGER DEFAULT 0,
                right_count INTEGER DEFAULT 0, wrong_count INTEGER DEFAULT 0,
                memorize_right INTEGER DEFAULT 0, memorize_wrong INTEGER DEFAULT 0,
                PRIMARY KEY(day, user)
            );
            INSERT INTO daily_log (day, user, new_count, review_count, right_count, wrong_count)
            SELECT day, 'default', new_count, review_count, right_count, wrong_count FROM daily_log_old;
            DROP TABLE daily_log_old;
            """)
        for col in ("memorized", "memorize_count", "last_memorize"):
            if col not in [r["name"] for r in conn.execute("PRAGMA table_info(word_state)").fetchall()]:
                conn.execute(f"ALTER TABLE word_state ADD COLUMN {col} " + {
                    "memorized": "INTEGER DEFAULT 0",
                    "memorize_count": "INTEGER DEFAULT 0",
                    "last_memorize": "TEXT",
                }[col])
        for col in ("memorize_right", "memorize_wrong"):
            if col not in [r["name"] for r in conn.execute("PRAGMA table_info(daily_log)").fetchall()]:
                conn.execute(f"ALTER TABLE daily_log ADD COLUMN {col} INTEGER DEFAULT 0")
        # 打字速度曲线：记录每道完成题的作答耗时（毫秒）
        if "duration_ms" not in [r["name"] for r in conn.execute("PRAGMA table_info(study_session_item)").fetchall()]:
            conn.execute("ALTER TABLE study_session_item ADD COLUMN duration_ms INTEGER")
        # FSRS 记忆状态（听打复习调度）与错拼采集
        ws_cols = [r["name"] for r in conn.execute("PRAGMA table_info(word_state)").fetchall()]
        if "stability" not in ws_cols:
            conn.execute("ALTER TABLE word_state ADD COLUMN stability REAL")
        if "difficulty" not in ws_cols:
            conn.execute("ALTER TABLE word_state ADD COLUMN difficulty REAL")
        if "last_typed" not in [r["name"] for r in conn.execute("PRAGMA table_info(study_session_item)").fetchall()]:
            conn.execute("ALTER TABLE study_session_item ADD COLUMN last_typed TEXT")
        # 首次敲入快照：completed 行的 last_typed 会被改对重输覆盖，
        # 易混词挖掘需要"第一次的错拼"，故单独落列不可覆盖
        if "first_typed" not in [r["name"] for r in conn.execute("PRAGMA table_info(study_session_item)").fetchall()]:
            conn.execute("ALTER TABLE study_session_item ADD COLUMN first_typed TEXT")
        # 我的文章：句子数落列，目录页列表不再为计数反序列化整篇 JSON
        cm_cols = [r["name"] for r in conn.execute("PRAGMA table_info(custom_material)").fetchall()]
        if "sentence_count" not in cm_cols:
            conn.execute("ALTER TABLE custom_material ADD COLUMN sentence_count INTEGER")
            for row in conn.execute("SELECT id,sentences FROM custom_material").fetchall():
                try:
                    n = len(json.loads(row["sentences"]))
                except (ValueError, TypeError):
                    n = 0
                conn.execute("UPDATE custom_material SET sentence_count=? WHERE id=?", (n, row["id"]))
        # PK 对战：服务端校验后的逐词答案记录
        pk_cols = [r["name"] for r in conn.execute("PRAGMA table_info(pk_result)").fetchall()]
        if "answers" not in pk_cols:
            conn.execute("ALTER TABLE pk_result ADD COLUMN answers TEXT")
        # 计分接口幂等：跨 sprint/quiz/wrong/match/boss/arrange 的去重+封顶
        if "score_attempt" not in [r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]:
            conn.execute("""
                CREATE TABLE score_attempt (
                    user TEXT NOT NULL,
                    endpoint TEXT NOT NULL,
                    attempt_id TEXT NOT NULL,
                    day TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(user, endpoint, attempt_id)
                )""")
            conn.execute("CREATE INDEX idx_score_attempt_user_day ON score_attempt(user, endpoint, day)")
        print("migrate ok")

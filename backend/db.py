"""数据库：连接 / 建表 / 迁移"""
import sqlite3

from .config import DB


def db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


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
            first_answer_at TEXT, answered_at TEXT,
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
        print("migrate ok")

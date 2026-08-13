"""数据库：连接 / 建表 / 迁移"""
import sqlite3

from .config import DB


def db():
    conn = sqlite3.connect(str(DB))
    conn.row_factory = sqlite3.Row
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

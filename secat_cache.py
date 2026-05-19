import json
import os
import time
from datetime import datetime, timezone, timedelta

CACHE_DIR = "cache"

OFFERINGS_CACHE_SECONDS  = 60 * 60 * 24 * 7     # 7 days
SECAT_DATA_CACHE_SECONDS = 60 * 60 * 24 * 30    # 30 days
MARKET_CACHE_SECONDS     = 60 * 60 * 24 * 7     # 7 days

DATABASE_URL = os.environ.get("DATABASE_URL")

_pool             = None
_pool_init_failed = False


# ---------------------------------------------------------------------------
# Connection pool
# ---------------------------------------------------------------------------

def _get_pool():
    global _pool, _pool_init_failed

    if _pool_init_failed or DATABASE_URL is None:
        return None

    if _pool is not None:
        return _pool

    try:
        import psycopg2.pool

        url = DATABASE_URL
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)

        _pool = psycopg2.pool.ThreadedConnectionPool(1, 5, url)

        conn = _pool.getconn()
        try:
            _ensure_schema(conn)
            conn.commit()
        finally:
            _pool.putconn(conn)

        print("[DB] PostgreSQL cache pool initialized")
        return _pool

    except Exception as e:
        print(f"[DB] Pool init failed: {e}")
        _pool_init_failed = True
        return None


def _ensure_schema(conn):
    with conn.cursor() as cur:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            SERIAL PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id               INT  PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                balance               REAL NOT NULL DEFAULT 500,
                best_streak           INT  NOT NULL DEFAULT 0,
                total_coins_earned    REAL NOT NULL DEFAULT 0,
                biggest_market_profit REAL NOT NULL DEFAULT 0,
                total_bets_placed     INT  NOT NULL DEFAULT 0
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS user_achievements (
                user_id        INT  NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                achievement_id TEXT NOT NULL,
                unlocked_at    TIMESTAMPTZ DEFAULT NOW(),
                PRIMARY KEY (user_id, achievement_id)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS course_offerings (
                course_code TEXT    NOT NULL,
                course_name TEXT    NOT NULL DEFAULT '',
                sem         INTEGER NOT NULL,
                year        INTEGER NOT NULL,
                label       TEXT    NOT NULL,
                cached_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (course_code, sem, year)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS secat_data (
                course_code       TEXT    NOT NULL,
                sem               INTEGER NOT NULL,
                year              INTEGER NOT NULL,
                question_name     TEXT    NOT NULL,
                answer            TEXT    NOT NULL,
                value             INTEGER NOT NULL,
                percent_answer    REAL    NOT NULL,
                answered_question INTEGER NOT NULL,
                cached_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (course_code, sem, year, question_name, answer)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prediction_markets (
                course_code        TEXT    NOT NULL,
                question_num       INTEGER NOT NULL,
                answer_num         INTEGER NOT NULL,
                max_history        INTEGER NOT NULL DEFAULT 5,
                before_year        INTEGER NOT NULL DEFAULT -1,
                before_sem         INTEGER NOT NULL DEFAULT -1,
                course_name        TEXT    NOT NULL DEFAULT '',
                question_name      TEXT    NOT NULL DEFAULT '',
                answer             TEXT    NOT NULL DEFAULT '',
                initial_prediction REAL    NOT NULL,
                confidence         REAL    NOT NULL,
                history_count      INTEGER NOT NULL,
                upcoming_course    TEXT    NOT NULL DEFAULT '',
                upcoming_name      TEXT    NOT NULL DEFAULT '',
                upcoming_sem       INTEGER NOT NULL,
                upcoming_year      INTEGER NOT NULL,
                upcoming_label     TEXT    NOT NULL DEFAULT '',
                upcoming_basis     TEXT    NOT NULL DEFAULT '',
                upcoming_reason    TEXT    NOT NULL DEFAULT '',
                cached_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (course_code, question_num, answer_num, max_history, before_year, before_sem)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS markets (
                id                 SERIAL PRIMARY KEY,
                course_code        TEXT    NOT NULL,
                question_num       INT     NOT NULL,
                answer_num         INT     NOT NULL,
                question_name      TEXT    NOT NULL DEFAULT '',
                answer             TEXT    NOT NULL DEFAULT '',
                initial_prediction REAL    NOT NULL,
                confidence         REAL    NOT NULL,
                upcoming_sem       INT     NOT NULL,
                upcoming_year      INT     NOT NULL,
                current_price      REAL    NOT NULL,
                status             TEXT    NOT NULL DEFAULT 'open',
                resolution_result  REAL,
                resolution_side    TEXT,
                created_at         TIMESTAMPTZ DEFAULT NOW(),
                resolved_at        TIMESTAMPTZ,
                UNIQUE (course_code, question_num, answer_num, upcoming_sem, upcoming_year)
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS market_positions (
                id          SERIAL PRIMARY KEY,
                market_id   INT     NOT NULL REFERENCES markets(id),
                user_id     INT     REFERENCES users(id),
                bot_name    TEXT,
                side        TEXT    NOT NULL,
                stake       REAL    NOT NULL,
                price_cents REAL    NOT NULL,
                shares      REAL    NOT NULL,
                status      TEXT    NOT NULL DEFAULT 'open',
                payout      REAL,
                profit      REAL,
                created_at  TIMESTAMPTZ DEFAULT NOW(),
                settled_at  TIMESTAMPTZ
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS prediction_market_history (
                course_code      TEXT    NOT NULL,
                question_num     INTEGER NOT NULL,
                answer_num       INTEGER NOT NULL,
                max_history      INTEGER NOT NULL DEFAULT 5,
                before_year      INTEGER NOT NULL DEFAULT -1,
                before_sem       INTEGER NOT NULL DEFAULT -1,
                position         INTEGER NOT NULL,
                offering_display TEXT    NOT NULL DEFAULT '',
                offering_course  TEXT    NOT NULL DEFAULT '',
                offering_name    TEXT    NOT NULL DEFAULT '',
                offering_sem     INTEGER NOT NULL,
                offering_year    INTEGER NOT NULL,
                percent          REAL    NOT NULL,
                count            INTEGER NOT NULL,
                answered         INTEGER NOT NULL,
                PRIMARY KEY (course_code, question_num, answer_num, max_history, before_year, before_sem, position),
                FOREIGN KEY (course_code, question_num, answer_num, max_history, before_year, before_sem)
                    REFERENCES prediction_markets (course_code, question_num, answer_num, max_history, before_year, before_sem)
                    ON DELETE CASCADE
            )
        """)


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def _acquire():
    """Returns (pool, conn) or (None, None) if the database is unavailable."""
    db = _get_pool()
    if db is None:
        return None, None
    try:
        return db, db.getconn()
    except Exception as e:
        print(f"[DB] Could not acquire connection: {e}")
        return None, None


def _release(db, conn, commit=False):
    """Commit or rollback then return the connection to the pool."""
    if db is None or conn is None:
        return
    try:
        if commit:
            conn.commit()
        else:
            conn.rollback()
    except Exception:
        pass
    db.putconn(conn)


def _sentinel(val, default=-1):
    return default if val is None else val


# ---------------------------------------------------------------------------
# DB — course_offerings
# ---------------------------------------------------------------------------

def _db_get_offerings(course_code: str):
    db, conn = _acquire()
    if conn is None:
        return None
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=OFFERINGS_CACHE_SECONDS)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT course_name, sem, year, label
                FROM course_offerings
                WHERE course_code = %s AND cached_at > %s
                ORDER BY year DESC, sem DESC
                """,
                (course_code, cutoff),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return [
            {"course": course_code, "name": name, "sem": sem, "year": year, "label": label}
            for name, sem, year, label in rows
        ]
    except Exception as e:
        print(f"[DB] offerings read error ({course_code}): {e}")
        return None
    finally:
        _release(db, conn)


def _db_set_offerings(course_code: str, offerings: list) -> bool:
    db, conn = _acquire()
    if conn is None:
        return False
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM course_offerings WHERE course_code = %s",
                (course_code,),
            )
            for o in offerings:
                cur.execute(
                    """
                    INSERT INTO course_offerings (course_code, course_name, sem, year, label)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (course_code, o.get("name", ""), o["sem"], o["year"], o["label"]),
                )
        commit = True
        return True
    except Exception as e:
        print(f"[DB] offerings write error ({course_code}): {e}")
        return False
    finally:
        _release(db, conn, commit=commit)


# ---------------------------------------------------------------------------
# DB — secat_data
# ---------------------------------------------------------------------------

def _db_get_secat_data(course_code: str, sem: int, year: int):
    db, conn = _acquire()
    if conn is None:
        return None
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=SECAT_DATA_CACHE_SECONDS)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT question_name, answer, value, percent_answer, answered_question
                FROM secat_data
                WHERE course_code = %s AND sem = %s AND year = %s AND cached_at > %s
                """,
                (course_code, sem, year, cutoff),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        return [
            {
                "QUESTION_NAME":     q_name,
                "ANSWER":            answer,
                "VALUE":             value,
                "PERCENT_ANSWER":    pct,
                "ANSWERED_QUESTION": answered,
            }
            for q_name, answer, value, pct, answered in rows
        ]
    except Exception as e:
        print(f"[DB] secat_data read error ({course_code} S{sem} {year}): {e}")
        return None
    finally:
        _release(db, conn)


def _db_set_secat_data(course_code: str, sem: int, year: int, data: list) -> bool:
    db, conn = _acquire()
    if conn is None:
        return False
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM secat_data WHERE course_code = %s AND sem = %s AND year = %s",
                (course_code, sem, year),
            )
            for item in data:
                cur.execute(
                    """
                    INSERT INTO secat_data
                        (course_code, sem, year, question_name, answer, value, percent_answer, answered_question)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        course_code, sem, year,
                        item["QUESTION_NAME"],
                        item["ANSWER"],
                        item["VALUE"],
                        item["PERCENT_ANSWER"],
                        item["ANSWERED_QUESTION"],
                    ),
                )
        commit = True
        return True
    except Exception as e:
        print(f"[DB] secat_data write error ({course_code} S{sem} {year}): {e}")
        return False
    finally:
        _release(db, conn, commit=commit)


# ---------------------------------------------------------------------------
# DB — prediction_markets + prediction_market_history
# ---------------------------------------------------------------------------

def _db_get_market(
    course_code: str,
    question_num: int,
    answer_num: int,
    max_history: int,
    before_year=None,
    before_sem=None,
):
    db, conn = _acquire()
    if conn is None:
        return None
    by = _sentinel(before_year)
    bs = _sentinel(before_sem)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=MARKET_CACHE_SECONDS)
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT course_name, question_name, answer,
                       initial_prediction, confidence, history_count,
                       upcoming_course, upcoming_name, upcoming_sem, upcoming_year,
                       upcoming_label, upcoming_basis, upcoming_reason
                FROM prediction_markets
                WHERE course_code = %s AND question_num = %s AND answer_num = %s
                  AND max_history = %s AND before_year = %s AND before_sem = %s
                  AND cached_at > %s
                """,
                (course_code, question_num, answer_num, max_history, by, bs, cutoff),
            )
            row = cur.fetchone()

            if row is None:
                return None

            (
                course_name, question_name, answer,
                initial_prediction, confidence, history_count,
                upcoming_course, upcoming_name, upcoming_sem, upcoming_year,
                upcoming_label, upcoming_basis, upcoming_reason,
            ) = row

            cur.execute(
                """
                SELECT offering_display, offering_course, offering_name,
                       offering_sem, offering_year, percent, count, answered
                FROM prediction_market_history
                WHERE course_code = %s AND question_num = %s AND answer_num = %s
                  AND max_history = %s AND before_year = %s AND before_sem = %s
                ORDER BY position ASC
                """,
                (course_code, question_num, answer_num, max_history, by, bs),
            )
            history_rows = cur.fetchall()

        history = [
            {
                "offering": off_display,
                "course":   off_course,
                "name":     off_name,
                "sem":      off_sem,
                "year":     off_year,
                "percent":  pct,
                "count":    count,
                "answered": answered,
            }
            for off_display, off_course, off_name, off_sem, off_year, pct, count, answered
            in history_rows
        ]

        upcoming_display = (
            f"{upcoming_label} - {upcoming_name}" if upcoming_name else upcoming_label
        )

        return {
            "course":             course_code,
            "name":               course_name,
            "question_num":       question_num,
            "answer_num":         answer_num,
            "question_name":      question_name,
            "answer":             answer,
            "initial_prediction": initial_prediction,
            "confidence":         confidence,
            "history_count":      history_count,
            "upcoming_offering": {
                "course":  upcoming_course,
                "name":    upcoming_name,
                "sem":     upcoming_sem,
                "year":    upcoming_year,
                "label":   upcoming_label,
                "basis":   upcoming_basis,
                "reason":  upcoming_reason,
                "display": upcoming_display,
            },
            "history": history,
        }

    except Exception as e:
        print(f"[DB] market read error ({course_code} Q{question_num} A{answer_num}): {e}")
        return None
    finally:
        _release(db, conn)


def _db_set_market(
    course_code: str,
    question_num: int,
    answer_num: int,
    max_history: int,
    market: dict,
    before_year=None,
    before_sem=None,
) -> bool:
    db, conn = _acquire()
    if conn is None:
        return False
    by = _sentinel(before_year)
    bs = _sentinel(before_sem)
    commit = False
    try:
        upcoming = market["upcoming_offering"]
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO prediction_markets (
                    course_code, question_num, answer_num, max_history, before_year, before_sem,
                    course_name, question_name, answer,
                    initial_prediction, confidence, history_count,
                    upcoming_course, upcoming_name, upcoming_sem, upcoming_year,
                    upcoming_label, upcoming_basis, upcoming_reason
                ) VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s, %s,%s,%s, %s,%s,%s,%s, %s,%s,%s)
                ON CONFLICT (course_code, question_num, answer_num, max_history, before_year, before_sem)
                DO UPDATE SET
                    course_name        = EXCLUDED.course_name,
                    question_name      = EXCLUDED.question_name,
                    answer             = EXCLUDED.answer,
                    initial_prediction = EXCLUDED.initial_prediction,
                    confidence         = EXCLUDED.confidence,
                    history_count      = EXCLUDED.history_count,
                    upcoming_course    = EXCLUDED.upcoming_course,
                    upcoming_name      = EXCLUDED.upcoming_name,
                    upcoming_sem       = EXCLUDED.upcoming_sem,
                    upcoming_year      = EXCLUDED.upcoming_year,
                    upcoming_label     = EXCLUDED.upcoming_label,
                    upcoming_basis     = EXCLUDED.upcoming_basis,
                    upcoming_reason    = EXCLUDED.upcoming_reason,
                    cached_at          = NOW()
                """,
                (
                    course_code, question_num, answer_num, max_history, by, bs,
                    market.get("name", ""),
                    market.get("question_name", ""),
                    market.get("answer", ""),
                    market["initial_prediction"],
                    market["confidence"],
                    market["history_count"],
                    upcoming["course"],
                    upcoming.get("name", ""),
                    upcoming["sem"],
                    upcoming["year"],
                    upcoming["label"],
                    upcoming["basis"],
                    upcoming["reason"],
                ),
            )

            cur.execute(
                """
                DELETE FROM prediction_market_history
                WHERE course_code = %s AND question_num = %s AND answer_num = %s
                  AND max_history = %s AND before_year = %s AND before_sem = %s
                """,
                (course_code, question_num, answer_num, max_history, by, bs),
            )

            for pos, item in enumerate(market.get("history", [])):
                cur.execute(
                    """
                    INSERT INTO prediction_market_history (
                        course_code, question_num, answer_num, max_history, before_year, before_sem,
                        position, offering_display, offering_course, offering_name,
                        offering_sem, offering_year, percent, count, answered
                    ) VALUES (%s,%s,%s,%s,%s,%s, %s,%s,%s,%s, %s,%s,%s,%s,%s)
                    """,
                    (
                        course_code, question_num, answer_num, max_history, by, bs,
                        pos,
                        item.get("offering", ""),
                        item.get("course", ""),
                        item.get("name", ""),
                        item["sem"],
                        item["year"],
                        item["percent"],
                        item["count"],
                        item["answered"],
                    ),
                )
        commit = True
        return True

    except Exception as e:
        print(f"[DB] market write error ({course_code} Q{question_num} A{answer_num}): {e}")
        return False
    finally:
        _release(db, conn, commit=commit)


# ---------------------------------------------------------------------------
# File fallback
# ---------------------------------------------------------------------------

def _ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def _file_path(key: str) -> str:
    _ensure_cache_dir()
    safe = (
        key.replace("/", "_").replace("\\", "_")
           .replace(":", "_").replace(",", "_").replace(" ", "_")
    )
    return os.path.join(CACHE_DIR, safe + ".json")


def _file_read(path: str, max_age_seconds: int):
    if not os.path.exists(path):
        return None
    if (time.time() - os.path.getmtime(path)) > max_age_seconds:
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _file_write(path: str, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def _file_get_offerings(course_code: str):
    return _file_read(_file_path(f"offerings_{course_code}"), OFFERINGS_CACHE_SECONDS)


def _file_set_offerings(course_code: str, offerings: list):
    _file_write(_file_path(f"offerings_{course_code}"), offerings)


def _file_get_secat_data(course_code: str, sem: int, year: int):
    return _file_read(
        _file_path(f"secat_data_{course_code}_sem{sem}_{year}"),
        SECAT_DATA_CACHE_SECONDS,
    )


def _file_set_secat_data(course_code: str, sem: int, year: int, data: list):
    _file_write(_file_path(f"secat_data_{course_code}_sem{sem}_{year}"), data)


def _file_market_key(course_code, question_num, answer_num, max_history, before_year, before_sem):
    before_part = "latest"
    if before_year is not None and before_sem is not None:
        before_part = f"before_sem{before_sem}_{before_year}"
    return f"market_{course_code}_q{question_num}_a{answer_num}_h{max_history}_{before_part}"


def _file_get_market(course_code, question_num, answer_num, max_history, before_year, before_sem):
    return _file_read(
        _file_path(_file_market_key(course_code, question_num, answer_num, max_history, before_year, before_sem)),
        MARKET_CACHE_SECONDS,
    )


def _file_set_market(course_code, question_num, answer_num, max_history, market, before_year, before_sem):
    _file_write(
        _file_path(_file_market_key(course_code, question_num, answer_num, max_history, before_year, before_sem)),
        market,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_cached_offerings(course_code: str):
    result = _db_get_offerings(course_code)
    if result is not None:
        return result
    return _file_get_offerings(course_code)


def set_cached_offerings(course_code: str, offerings: list):
    if not _db_set_offerings(course_code, offerings):
        _file_set_offerings(course_code, offerings)


def get_cached_secat_data(course_code: str, sem: int, year: int):
    result = _db_get_secat_data(course_code, sem, year)
    if result is not None:
        return result
    return _file_get_secat_data(course_code, sem, year)


def set_cached_secat_data(course_code: str, sem: int, year: int, data: list):
    if not _db_set_secat_data(course_code, sem, year, data):
        _file_set_secat_data(course_code, sem, year, data)


def get_cached_market(
    course_code: str,
    question_num: int,
    answer_num: int,
    max_history: int,
    before_year=None,
    before_sem=None,
):
    result = _db_get_market(course_code, question_num, answer_num, max_history, before_year, before_sem)
    if result is not None:
        return result
    return _file_get_market(course_code, question_num, answer_num, max_history, before_year, before_sem)


def set_cached_market(
    course_code: str,
    question_num: int,
    answer_num: int,
    max_history: int,
    market: dict,
    before_year=None,
    before_sem=None,
):
    if not _db_set_market(course_code, question_num, answer_num, max_history, market, before_year, before_sem):
        _file_set_market(course_code, question_num, answer_num, max_history, market, before_year, before_sem)


# ---------------------------------------------------------------------------
# User accounts
# ---------------------------------------------------------------------------

def db_available() -> bool:
    return _get_pool() is not None


def create_user(username: str, password_hash: str):
    db, conn = _acquire()
    if conn is None:
        return None
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO users (username, password_hash) VALUES (%s, %s) RETURNING id",
                (username, password_hash),
            )
            user_id = cur.fetchone()[0]
            cur.execute("INSERT INTO user_state (user_id) VALUES (%s)", (user_id,))
        commit = True
        return user_id
    except Exception as e:
        print(f"[DB] create_user error: {e}")
        return None
    finally:
        _release(db, conn, commit=commit)


def get_user_by_username(username: str):
    db, conn = _acquire()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username, password_hash FROM users WHERE username = %s",
                (username,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {"id": row[0], "username": row[1], "password_hash": row[2]}
    except Exception as e:
        print(f"[DB] get_user_by_username error: {e}")
        return None
    finally:
        _release(db, conn)


def get_user_by_id(user_id: int):
    db, conn = _acquire()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, username FROM users WHERE id = %s",
                (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        return {"id": row[0], "username": row[1]}
    except Exception as e:
        print(f"[DB] get_user_by_id error: {e}")
        return None
    finally:
        _release(db, conn)


def get_user_state(user_id: int) -> dict:
    db, conn = _acquire()
    if conn is None:
        return _default_state()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT balance, best_streak, total_coins_earned,
                       biggest_market_profit, total_bets_placed
                FROM user_state WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
        if row is None:
            return _default_state()
        return {
            "balance":               row[0],
            "best_streak":           row[1],
            "total_coins_earned":    row[2],
            "biggest_market_profit": row[3],
            "total_bets_placed":     row[4],
        }
    except Exception as e:
        print(f"[DB] get_user_state error: {e}")
        return _default_state()
    finally:
        _release(db, conn)


def _default_state() -> dict:
    return {
        "balance": 500,
        "best_streak": 0,
        "total_coins_earned": 0,
        "biggest_market_profit": 0,
        "total_bets_placed": 0,
    }


def add_to_balance(user_id: int, delta: float):
    db, conn = _acquire()
    if conn is None:
        return None
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_state
                SET balance = GREATEST(0, balance + %s)
                WHERE user_id = %s
                RETURNING balance
                """,
                (delta, user_id),
            )
            row = cur.fetchone()
        commit = True
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] add_to_balance error: {e}")
        return None
    finally:
        _release(db, conn, commit=commit)


def get_user_achievements(user_id: int) -> list:
    db, conn = _acquire()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT achievement_id FROM user_achievements WHERE user_id = %s",
                (user_id,),
            )
            rows = cur.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        print(f"[DB] get_user_achievements error: {e}")
        return []
    finally:
        _release(db, conn)


def unlock_user_achievement(user_id: int, achievement_id: str) -> bool:
    db, conn = _acquire()
    if conn is None:
        return False
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_achievements (user_id, achievement_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (user_id, achievement_id),
            )
            newly_inserted = cur.rowcount > 0
        commit = True
        return newly_inserted
    except Exception as e:
        print(f"[DB] unlock_user_achievement error: {e}")
        return False
    finally:
        _release(db, conn, commit=commit)


_STAT_SQL = {
    "best_streak": (
        "UPDATE user_state SET best_streak = GREATEST(best_streak, %s) WHERE user_id = %s"
    ),
    "biggest_market_profit": (
        "UPDATE user_state SET biggest_market_profit = GREATEST(biggest_market_profit, %s) WHERE user_id = %s"
    ),
    "total_coins_earned": (
        "UPDATE user_state SET total_coins_earned = total_coins_earned + %s WHERE user_id = %s"
    ),
    "total_bets_placed": (
        "UPDATE user_state SET total_bets_placed = total_bets_placed + %s WHERE user_id = %s"
    ),
}


def update_user_stat(user_id: int, field: str, value: float):
    sql = _STAT_SQL.get(field)
    if sql is None:
        return
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql, (value, user_id))
        commit = True
    except Exception as e:
        print(f"[DB] update_user_stat error ({field}): {e}")
    finally:
        _release(db, conn, commit=commit)


def reset_user_achievements(user_id: int):
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM user_achievements WHERE user_id = %s", (user_id,)
            )
        commit = True
    except Exception as e:
        print(f"[DB] reset_user_achievements error: {e}")
    finally:
        _release(db, conn, commit=commit)


def reset_user_stats(user_id: int):
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_state
                SET best_streak=0, total_coins_earned=0,
                    biggest_market_profit=0, total_bets_placed=0
                WHERE user_id = %s
                """,
                (user_id,),
            )
        commit = True
    except Exception as e:
        print(f"[DB] reset_user_stats error: {e}")
    finally:
        _release(db, conn, commit=commit)


# ---------------------------------------------------------------------------
# Markets
# ---------------------------------------------------------------------------

def _market_row_to_dict(row) -> dict:
    (id_, course_code_, question_num, answer_num, question_name, answer,
     initial_prediction, confidence, upcoming_sem, upcoming_year,
     current_price, status, resolution_result, resolution_side,
     created_at, resolved_at) = row
    return {
        "id": id_,
        "course_code": course_code_,
        "question_num": question_num,
        "answer_num": answer_num,
        "question_name": question_name,
        "answer": answer,
        "initial_prediction": initial_prediction,
        "confidence": confidence,
        "upcoming_sem": upcoming_sem,
        "upcoming_year": upcoming_year,
        "current_price": current_price,
        "status": status,
        "resolution_result": resolution_result,
        "resolution_side": resolution_side,
        "created_at": created_at.isoformat() if created_at else None,
        "resolved_at": resolved_at.isoformat() if resolved_at else None,
    }


_MARKET_COLS = (
    "id, course_code, question_num, answer_num, question_name, answer, "
    "initial_prediction, confidence, upcoming_sem, upcoming_year, "
    "current_price, status, resolution_result, resolution_side, "
    "created_at, resolved_at"
)


def create_market(
    course_code_: str,
    question_num: int,
    answer_num: int,
    question_name: str,
    answer: str,
    initial_prediction: float,
    confidence: float,
    upcoming_sem: int,
    upcoming_year: int,
) -> "int | None":
    db, conn = _acquire()
    if conn is None:
        return None
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO markets
                    (course_code, question_num, answer_num, question_name, answer,
                     initial_prediction, confidence, upcoming_sem, upcoming_year, current_price)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (course_code, question_num, answer_num, upcoming_sem, upcoming_year)
                DO UPDATE SET
                    question_name      = EXCLUDED.question_name,
                    answer             = EXCLUDED.answer,
                    initial_prediction = EXCLUDED.initial_prediction,
                    confidence         = EXCLUDED.confidence
                RETURNING id
                """,
                (
                    course_code_, question_num, answer_num, question_name, answer,
                    initial_prediction, confidence, upcoming_sem, upcoming_year,
                    initial_prediction,
                ),
            )
            row = cur.fetchone()
        commit = True
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] create_market error: {e}")
        return None
    finally:
        _release(db, conn, commit=commit)


def get_market(market_id: int) -> "dict | None":
    db, conn = _acquire()
    if conn is None:
        return None
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {_MARKET_COLS} FROM markets WHERE id = %s",
                (market_id,),
            )
            row = cur.fetchone()
        return _market_row_to_dict(row) if row else None
    except Exception as e:
        print(f"[DB] get_market error: {e}")
        return None
    finally:
        _release(db, conn)


def get_or_create_market(
    course_code_: str,
    question_num: int,
    answer_num: int,
    question_name: str,
    answer: str,
    initial_prediction: float,
    confidence: float,
    upcoming_sem: int,
    upcoming_year: int,
) -> "dict | None":
    market_id = create_market(
        course_code_, question_num, answer_num, question_name, answer,
        initial_prediction, confidence, upcoming_sem, upcoming_year,
    )
    if market_id is None:
        return None
    return get_market(market_id)


def update_market_price(market_id: int, new_price: float):
    clamped = max(5.0, min(95.0, new_price))
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE markets SET current_price = %s WHERE id = %s",
                (clamped, market_id),
            )
        commit = True
    except Exception as e:
        print(f"[DB] update_market_price error: {e}")
    finally:
        _release(db, conn, commit=commit)


def resolve_market(market_id: int, result_percent: float, winning_side: str):
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE markets
                SET status = 'resolved',
                    resolution_result = %s,
                    resolution_side   = %s,
                    resolved_at       = NOW()
                WHERE id = %s
                """,
                (result_percent, winning_side, market_id),
            )
        commit = True
    except Exception as e:
        print(f"[DB] resolve_market error: {e}")
    finally:
        _release(db, conn, commit=commit)


def get_open_markets(limit: int = 20) -> list:
    db, conn = _acquire()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT {_MARKET_COLS} FROM markets
                WHERE status = 'open'
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()
        return [_market_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] get_open_markets error: {e}")
        return []
    finally:
        _release(db, conn)


def recompute_market_price(market_id: int) -> "float | None":
    """
    Price = higher_shares / (higher_shares + lower_shares) * 100, clamped [5, 95].
    Falls back to current_price if no positions exist.
    """
    db, conn = _acquire()
    if conn is None:
        return None
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    COALESCE(SUM(shares) FILTER (WHERE side = 'higher'), 0) AS h,
                    COALESCE(SUM(shares) FILTER (WHERE side = 'lower'),  0) AS l
                FROM market_positions
                WHERE market_id = %s AND status = 'open'
                """,
                (market_id,),
            )
            h_shares, l_shares = cur.fetchone()
            total = h_shares + l_shares
            if total > 0:
                new_price = max(5.0, min(95.0, h_shares / total * 100))
            else:
                cur.execute("SELECT current_price FROM markets WHERE id = %s", (market_id,))
                row = cur.fetchone()
                new_price = row[0] if row else 50.0

            cur.execute(
                "UPDATE markets SET current_price = %s WHERE id = %s",
                (new_price, market_id),
            )
        commit = True
        return round(new_price, 2)
    except Exception as e:
        print(f"[DB] recompute_market_price error: {e}")
        return None
    finally:
        _release(db, conn, commit=commit)


# ---------------------------------------------------------------------------
# Market positions
# ---------------------------------------------------------------------------

def add_position(
    market_id: int,
    user_id: "int | None",
    bot_name: "str | None",
    side: str,
    stake: float,
    price_cents: float,
    shares: float,
) -> "int | None":
    db, conn = _acquire()
    if conn is None:
        return None
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO market_positions
                    (market_id, user_id, bot_name, side, stake, price_cents, shares)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (market_id, user_id, bot_name, side, stake, price_cents, shares),
            )
            row = cur.fetchone()
        commit = True
        return row[0] if row else None
    except Exception as e:
        print(f"[DB] add_position error: {e}")
        return None
    finally:
        _release(db, conn, commit=commit)


def get_positions_for_market(market_id: int, user_id: "int | None" = None) -> list:
    db, conn = _acquire()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            if user_id is not None:
                cur.execute(
                    """
                    SELECT id, market_id, user_id, bot_name, side, stake, price_cents,
                           shares, status, payout, profit, created_at, settled_at
                    FROM market_positions
                    WHERE market_id = %s AND user_id = %s
                    ORDER BY created_at DESC
                    """,
                    (market_id, user_id),
                )
            else:
                cur.execute(
                    """
                    SELECT id, market_id, user_id, bot_name, side, stake, price_cents,
                           shares, status, payout, profit, created_at, settled_at
                    FROM market_positions
                    WHERE market_id = %s
                    ORDER BY created_at DESC
                    """,
                    (market_id,),
                )
            rows = cur.fetchall()
        return [_position_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[DB] get_positions_for_market error: {e}")
        return []
    finally:
        _release(db, conn)


def get_positions_for_user(user_id: int) -> list:
    db, conn = _acquire()
    if conn is None:
        return []
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT p.id, p.market_id, p.user_id, p.bot_name, p.side,
                       p.stake, p.price_cents, p.shares, p.status,
                       p.payout, p.profit, p.created_at, p.settled_at,
                       m.course_code, m.question_num, m.answer_num,
                       m.question_name, m.answer, m.initial_prediction,
                       m.upcoming_sem, m.upcoming_year, m.current_price,
                       m.status AS market_status, m.resolution_result, m.resolution_side
                FROM market_positions p
                JOIN markets m ON m.id = p.market_id
                WHERE p.user_id = %s
                ORDER BY p.created_at DESC
                """,
                (user_id,),
            )
            rows = cur.fetchall()
        result = []
        for r in rows:
            pos = _position_row_to_dict(r[:13])
            pos.update({
                "course_code":        r[13],
                "question_num":       r[14],
                "answer_num":         r[15],
                "question_name":      r[16],
                "answer":             r[17],
                "initial_prediction": r[18],
                "upcoming_sem":       r[19],
                "upcoming_year":      r[20],
                "current_price":      r[21],
                "market_status":      r[22],
                "resolution_result":  r[23],
                "resolution_side":    r[24],
            })
            result.append(pos)
        return result
    except Exception as e:
        print(f"[DB] get_positions_for_user error: {e}")
        return []
    finally:
        _release(db, conn)


def _position_row_to_dict(row) -> dict:
    (id_, market_id, user_id, bot_name, side, stake, price_cents,
     shares, status, payout, profit, created_at, settled_at) = row
    return {
        "id":          id_,
        "market_id":   market_id,
        "user_id":     user_id,
        "bot_name":    bot_name,
        "side":        side,
        "stake":       stake,
        "price_cents": price_cents,
        "shares":      shares,
        "status":      status,
        "payout":      payout,
        "profit":      profit,
        "created_at":  created_at.isoformat() if created_at else None,
        "settled_at":  settled_at.isoformat() if settled_at else None,
    }


def settle_positions(market_id: int, winning_side: str, resolution_result: float):
    """
    Marks positions won/lost/refunded, computes payouts, and credits user balances.
    """
    db, conn = _acquire()
    if conn is None:
        return
    commit = False
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, side, stake, shares
                FROM market_positions
                WHERE market_id = %s AND status = 'open'
                """,
                (market_id,),
            )
            rows = cur.fetchall()

            for pos_id, user_id, side, stake, shares in rows:
                if winning_side == "push":
                    new_status = "refunded"
                    payout = stake
                    profit = 0.0
                elif side == winning_side:
                    new_status = "won"
                    payout = shares
                    profit = shares - stake
                else:
                    new_status = "lost"
                    payout = 0.0
                    profit = -stake

                cur.execute(
                    """
                    UPDATE market_positions
                    SET status = %s, payout = %s, profit = %s, settled_at = NOW()
                    WHERE id = %s
                    """,
                    (new_status, payout, profit, pos_id),
                )

                if user_id is not None and payout > 0:
                    cur.execute(
                        """
                        UPDATE user_state
                        SET balance = GREATEST(0, balance + %s)
                        WHERE user_id = %s
                        """,
                        (payout, user_id),
                    )
        commit = True
    except Exception as e:
        print(f"[DB] settle_positions error: {e}")
    finally:
        _release(db, conn, commit=commit)

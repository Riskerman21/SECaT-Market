import json
import os
import queue
import random
import threading
import time
from datetime import timedelta

from flask import Flask, Response, jsonify, render_template, request, session, stream_with_context
from werkzeug.security import check_password_hash, generate_password_hash

import secat_cache
from game import prepare_round, get_course_group_list, prepare_challenger
from prediction_market import get_course_list
from bots import create_bots, run_bot_round, summarise_trades

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)


def _current_user_id():
    return session.get("user_id")

# SSE trade feed
_trade_log   = []
_subscribers = []
_feed_lock   = threading.Lock()

# One shared bot roster — bots persist balance across ticks
_bots = create_bots()
_bots_lock = threading.Lock()



def _publish(event_data: dict):
    payload = "data: " + json.dumps(event_data) + "\n\n"
    with _feed_lock:
        dead = []
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except queue.Full:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def _bot_loop():
    """Background loop — runs bot ticks on random open DB markets every 2-5 s."""
    while True:
        time.sleep(random.uniform(2, 5))

        if not secat_cache.db_available():
            continue

        open_markets = secat_cache.get_open_markets(limit=20)
        if not open_markets:
            continue

        market_row = random.choice(open_markets)
        market_id  = market_row["id"]
        current    = market_row["current_price"]
        stub       = _stub_market_from_db(market_row)

        with _bots_lock:
            trades = run_bot_round(_bots, stub, current)

        for trade in trades:
            stake  = float(trade["size"])
            shares = stake / (current / 100) if current > 0 else stake
            secat_cache.add_position(
                market_id, None, trade["bot"],
                trade["direction"].lower(), stake, current, shares,
            )

        new_price = secat_cache.recompute_market_price(market_id)
        if new_price is None:
            new_price = current

        summary = summarise_trades(trades) if trades else {
            "implied_price": 50.0, "sentiment": "neutral"
        }

        implied = summary["implied_price"]
        if   implied >= 70: sentiment = "strongly bullish"
        elif implied >= 55: sentiment = "bullish"
        elif implied >= 45: sentiment = "neutral"
        elif implied >= 30: sentiment = "bearish"
        else:               sentiment = "strongly bearish"

        event = {
            "course":        market_row["course_code"],
            "name":          market_row["course_code"],
            "prediction":    market_row["initial_prediction"],
            "confidence":    market_row["confidence"],
            "implied_price": implied,
            "sentiment":     sentiment,
            "ts":            time.time(),
        }

        with _feed_lock:
            _trade_log.append(event)
            if len(_trade_log) > 200:
                _trade_log.pop(0)

        _publish(event)


threading.Thread(target=_bot_loop, daemon=True).start()


# Routes

# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def _db_required():
    if not secat_cache.db_available():
        return jsonify({"error": "Accounts require a database connection. Continue as guest."}), 503
    return None


def _user_payload(user_id: int, username: str) -> dict:
    state = secat_cache.get_user_state(user_id)
    achievements = secat_cache.get_user_achievements(user_id)
    return {"id": user_id, "username": username, "achievements": achievements, **state}


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route("/api/auth/register", methods=["POST"])
def api_register():
    err = _db_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters."}), 400
    if len(username) > 30:
        return jsonify({"error": "Username must be 30 characters or fewer."}), 400
    if len(password) < 6:
        return jsonify({"error": "Password must be at least 6 characters."}), 400

    user_id = secat_cache.create_user(username, generate_password_hash(password))
    if user_id is None:
        return jsonify({"error": "Username already taken."}), 409

    session.permanent = True
    session["user_id"] = user_id
    return jsonify(_user_payload(user_id, username)), 201


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    err = _db_required()
    if err:
        return err

    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""

    user = secat_cache.get_user_by_username(username)
    if user is None or not check_password_hash(user["password_hash"], password):
        return jsonify({"error": "Invalid username or password."}), 401

    session.permanent = True
    session["user_id"] = user["id"]
    return jsonify(_user_payload(user["id"], user["username"]))


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route("/api/auth/me")
def api_me():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"user": None})

    user = secat_cache.get_user_by_id(uid)
    if user is None:
        session.clear()
        return jsonify({"user": None})

    return jsonify({"user": _user_payload(uid, user["username"])})


# ---------------------------------------------------------------------------
# User-state routes (all require a valid session)
# ---------------------------------------------------------------------------

@app.route("/api/user/balance", methods=["POST"])
def api_user_balance():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    delta = float(data.get("delta", 0))
    new_balance = secat_cache.add_to_balance(uid, delta)
    if new_balance is None:
        return jsonify({"error": "Could not update balance."}), 500
    return jsonify({"balance": new_balance})


@app.route("/api/user/achievement", methods=["POST"])
def api_user_achievement():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    achievement_id = data.get("id", "")
    newly_unlocked = secat_cache.unlock_user_achievement(uid, achievement_id)
    return jsonify({"newly_unlocked": newly_unlocked})


@app.route("/api/user/stat", methods=["PATCH"])
def api_user_stat():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401

    data = request.get_json(silent=True) or {}
    field = data.get("field", "")
    value = data.get("value", 0)

    allowed = {"best_streak", "total_coins_earned", "biggest_market_profit", "total_bets_placed"}
    if field not in allowed:
        return jsonify({"error": "Invalid field."}), 400

    secat_cache.update_user_stat(uid, field, float(value))
    return jsonify({"ok": True})


@app.route("/api/user/achievements", methods=["DELETE"])
def api_reset_achievements():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401
    secat_cache.reset_user_achievements(uid)
    return jsonify({"ok": True})


@app.route("/api/user/stats", methods=["DELETE"])
def api_reset_stats():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401
    secat_cache.reset_user_stats(uid)
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.route("/")
def landing_page():
    return render_template("main.html")


@app.route("/higher-lower")
def home():
    return render_template("index.html")


@app.route("/prediction")
def prediction_page():
    return render_template("prediction.html")


@app.route("/api/trade-feed")
def trade_feed():
    q = queue.Queue(maxsize=50)
    with _feed_lock:
        _subscribers.append(q)
        history = list(_trade_log[-20:])

    def generate():
        for event in history:
            yield "data: " + json.dumps(event) + "\n\n"
        while True:
            try:
                msg = q.get(timeout=25)
                yield msg
            except queue.Empty:
                yield ": keepalive\n\n"
            except GeneratorExit:
                break
        with _feed_lock:
            try:
                _subscribers.remove(q)
            except ValueError:
                pass

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _stub_market_from_db(market_row: dict) -> dict:
    """Build minimal market dict bots need from a DB market row."""
    return {
        "course":             market_row["course_code"],
        "question_num":       market_row["question_num"],
        "answer_num":         market_row["answer_num"],
        "initial_prediction": market_row["initial_prediction"],
        "history":            [{"percent": market_row["initial_prediction"]}],
        "confidence":         market_row["confidence"],
    }


# ---------------------------------------------------------------------------
# Market routes (Phase 2a)
# ---------------------------------------------------------------------------

@app.route("/api/markets")
def api_get_markets():
    if not secat_cache.db_available():
        return jsonify({"markets": []})
    return jsonify({"markets": secat_cache.get_all_markets()})


@app.route("/api/markets", methods=["POST"])
def api_create_market():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Login required to create a market."}), 401

    data = request.get_json(silent=True) or {}

    course_code   = data.get("course_code", "")
    question_num  = int(data.get("question_num", 1))
    answer_num    = int(data.get("answer_num", 1))
    question_name = data.get("question_name", "")
    answer        = data.get("answer", "")
    initial_pred  = float(data.get("initial_prediction", 50))
    confidence    = float(data.get("confidence", 50))
    upcoming_sem  = int(data.get("upcoming_sem", 1))
    upcoming_year = int(data.get("upcoming_year", 2025))

    if not course_code:
        return jsonify({"error": "course_code required"}), 400

    if not secat_cache.db_available():
        return jsonify({"error": "Database unavailable — markets require a DB connection."}), 503

    market = secat_cache.get_or_create_market(
        course_code, question_num, answer_num, question_name, answer,
        initial_pred, confidence, upcoming_sem, upcoming_year,
    )
    if market is None:
        return jsonify({"error": "Could not create market."}), 500

    return jsonify(market)


@app.route("/api/markets/<int:market_id>")
def api_get_market(market_id: int):
    if not secat_cache.db_available():
        return jsonify({"error": "Database unavailable."}), 503
    market = secat_cache.get_market(market_id)
    if market is None:
        return jsonify({"error": "Market not found."}), 404
    return jsonify(market)


@app.route("/api/markets/open")
def api_open_markets():
    if not secat_cache.db_available():
        return jsonify({"markets": []})
    return jsonify({"markets": secat_cache.get_open_markets()})


@app.route("/api/markets/<int:market_id>/bot-tick", methods=["POST"])
def api_bot_tick(market_id: int):
    if not secat_cache.db_available():
        return jsonify({"error": "Database unavailable."}), 503

    market_row = secat_cache.get_market(market_id)
    if market_row is None:
        return jsonify({"error": "Market not found."}), 404
    if market_row["status"] != "open":
        return jsonify({"error": "Market is closed."}), 400

    current = market_row["current_price"]
    stub    = _stub_market_from_db(market_row)

    with _bots_lock:
        trades = run_bot_round(_bots, stub, current)

    for trade in trades:
        price_cents = current
        stake       = float(trade["size"])
        shares      = stake / (price_cents / 100) if price_cents > 0 else stake
        secat_cache.add_position(
            market_id, None, trade["bot"],
            trade["direction"].lower(), stake, price_cents, shares,
        )

    new_price = secat_cache.recompute_market_price(market_id)
    if new_price is None:
        new_price = current

    return jsonify({
        "bot_trades":    trades,
        "current_price": round(new_price, 2),
    })


@app.route("/api/markets/<int:market_id>/trade", methods=["POST"])
def api_market_trade(market_id: int):
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Login required to place a trade."}), 401

    if not secat_cache.db_available():
        return jsonify({"error": "Database unavailable."}), 503

    market_row = secat_cache.get_market(market_id)
    if market_row is None:
        return jsonify({"error": "Market not found."}), 404
    if market_row["status"] != "open":
        return jsonify({"error": "Market is closed."}), 400

    data      = request.get_json(silent=True) or {}
    direction = (data.get("direction") or "higher").lower()
    stake     = float(data.get("stake", 0))

    if direction not in ("higher", "lower"):
        return jsonify({"error": "direction must be 'higher' or 'lower'"}), 400
    if stake <= 0:
        return jsonify({"error": "stake must be positive"}), 400

    current     = market_row["current_price"]
    price_cents = current if direction == "higher" else (100 - current)
    price_frac  = price_cents / 100
    shares      = stake / price_frac if price_frac > 0 else stake

    state = secat_cache.get_user_state(uid)
    if state["balance"] < stake:
        return jsonify({"error": "Insufficient balance."}), 400

    new_balance = secat_cache.add_to_balance(uid, -stake)
    if new_balance is None:
        return jsonify({"error": "Could not update balance."}), 500

    secat_cache.add_position(
        market_id, uid, None, direction, stake, price_cents, shares,
    )

    stub = _stub_market_from_db(market_row)
    with _bots_lock:
        bot_trades = run_bot_round(_bots, stub, current)

    for trade in bot_trades:
        bp     = current
        bstake = float(trade["size"])
        bshares = bstake / (bp / 100) if bp > 0 else bstake
        secat_cache.add_position(
            market_id, None, trade["bot"],
            trade["direction"].lower(), bstake, bp, bshares,
        )

    new_price = secat_cache.recompute_market_price(market_id)
    if new_price is None:
        new_price = current

    return jsonify({
        "new_price":   round(new_price, 2),
        "bot_trades":  bot_trades,
        "new_balance": new_balance,
        "position": {
            "side":        direction,
            "stake":       stake,
            "price_cents": price_cents,
            "shares":      shares,
        },
    })


@app.route("/api/user/positions")
def api_user_positions():
    uid = _current_user_id()
    if uid is None:
        return jsonify({"error": "Not logged in."}), 401
    if not secat_cache.db_available():
        return jsonify({"positions": []})
    positions = secat_cache.get_positions_for_user(uid)
    return jsonify({"positions": positions})


@app.route("/api/markets/<int:market_id>/settle", methods=["POST"])
def api_settle_market(market_id: int):
    if not secat_cache.db_available():
        return jsonify({"error": "Database unavailable."}), 503

    market_row = secat_cache.get_market(market_id)
    if market_row is None:
        return jsonify({"error": "Market not found."}), 404
    if market_row["status"] == "resolved":
        return jsonify({"settled": True, "already_resolved": True, **market_row})

    from request_secat_data import getCourseData
    from game import extract_json_data

    course_code  = market_row["course_code"]
    question_num = market_row["question_num"]
    answer_num   = market_row["answer_num"]
    sem          = market_row["upcoming_sem"]
    year         = market_row["upcoming_year"]

    cached = secat_cache.get_cached_secat_data(course_code, sem, year)
    if cached is not None:
        course_data = cached
    else:
        resp = getCourseData(course_code, sem, year)
        if resp.get("error"):
            return jsonify({"settled": False, "reason": "Data not published yet."}), 202
        try:
            course_data = extract_json_data(resp["data"])
        except (ValueError, KeyError):
            return jsonify({"settled": False, "reason": "Could not parse SECaT data."}), 202
        secat_cache.set_cached_secat_data(course_code, sem, year, course_data)

    import re
    target_percent = None
    for item in course_data:
        qname = item.get("QUESTION_NAME", "")
        m = re.match(r"Q(\d+):", qname)
        if not m:
            continue
        if int(m.group(1)) != question_num:
            continue
        if item.get("VALUE") == answer_num:
            target_percent = float(item["PERCENT_ANSWER"])
            break

    if target_percent is None:
        return jsonify({"settled": False, "reason": "Question/answer not found in published data."}), 202

    initial = market_row["initial_prediction"]
    if target_percent > initial:
        winning_side = "higher"
    elif target_percent < initial:
        winning_side = "lower"
    else:
        winning_side = "push"

    secat_cache.resolve_market(market_id, target_percent, winning_side)
    secat_cache.settle_positions(market_id, winning_side, target_percent)

    return jsonify({
        "settled":        True,
        "result_percent": target_percent,
        "winning_side":   winning_side,
        "market_id":      market_id,
    })


@app.route("/api/round")
def api_round():
    selected_groups_raw = request.args.get("groups", "")
    course_groups = [g.strip() for g in selected_groups_raw.split(",") if g.strip()]
    round_data = prepare_round(course_groups=course_groups)
    if round_data is None:
        return jsonify({"error": "Could not prepare a valid round. Please try again."}), 500
    return jsonify(round_data)


@app.route("/api/courses")
def api_courses():
    return jsonify({"courses": get_course_list()})


@app.route("/api/course-groups")
def api_course_groups():
    return jsonify({"groups": get_course_group_list()})


@app.route("/api/challenger")
def api_challenger():
    course      = request.args.get("course")
    name        = request.args.get("name", "")
    label       = request.args.get("label")
    sem         = request.args.get("sem", type=int)
    year        = request.args.get("year", type=int)
    question_num = request.args.get("question_num", type=int)
    answer_num   = request.args.get("answer_num", type=int)
    groups_raw   = request.args.get("groups", "")
    used_raw     = request.args.get("used", "")

    if not course or not label or sem is None or year is None:
        return jsonify({"error": "Missing required parameters."}), 400

    current_offering = {
        "course": course,
        "name":   name,
        "label":  label,
        "sem":    sem,
        "year":   year,
    }

    course_groups = [g.strip() for g in groups_raw.split(",") if g.strip()]

    # `used` is a ||-delimited, URL-encoded list of already-seen offering labels
    used_labels = [
        label.strip()
        for label in used_raw.split("||")
        if label.strip()
    ]

    challenger = prepare_challenger(
        current_offering=current_offering,
        question_num=question_num,
        answer_num=answer_num,
        course_groups=course_groups,
        used_labels=used_labels,
    )

    if challenger is None:
        return jsonify({"error": "Could not find a challenger. Try again."}), 500

    return jsonify(challenger)

if __name__ == "__main__":
    app.run()
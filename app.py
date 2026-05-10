import json
import queue
import random
import threading
import time

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

from game import prepare_round, get_course_group_list, prepare_challenger
from prediction_market import (
    create_random_prediction_market,
    create_prediction_market_for_course_code,
    get_course_list,
)
from bots import create_bots, run_bot_round, summarise_trades

app = Flask(__name__)

# SSE trade feed
_trade_log   = []
_subscribers = []
_feed_lock   = threading.Lock()

# Per-market price state
_market_prices      = {}
_market_prices_lock = threading.Lock()

# One shared bot roster — bots persist balance across ticks
_bots = create_bots()
_bots_lock = threading.Lock()


def _get_price(market_key: str, base: float) -> float:
    with _market_prices_lock:
        if market_key not in _market_prices:
            _market_prices[market_key] = float(base)
        return _market_prices[market_key]


def _set_price(market_key: str, price: float):
    with _market_prices_lock:
        _market_prices[market_key] = max(5.0, min(95.0, price))


def _apply_price_impact(current: float, trades: list[dict]) -> float:
    """Move price based on net buy/sell pressure from a list of bot trades."""
    for trade in trades:
        impact = trade["size"] * 0.25 * (1 if trade["direction"] == "HIGHER" else -1)
        current += impact + random.gauss(0, 0.3)
    return max(5.0, min(95.0, current))


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
    """Background SSE loop — generates crowd-sentiment events every 2-5 s."""
    while True:
        time.sleep(random.uniform(2, 5))
        market = create_random_prediction_market()
        if market is None:
            continue

        base_price  = float(market["initial_prediction"])
        market_key  = f"{market['course']}_q{market['question_num']}_a{market['answer_num']}"
        current     = _get_price(market_key, base_price)

        with _bots_lock:
            trades = run_bot_round(_bots, market, current)

        new_price = _apply_price_impact(current, trades)
        _set_price(market_key, new_price)

        # summarise_trades takes a list of trade dicts from run_bot_round
        summary = summarise_trades(trades) if trades else {
            "implied_price": 50.0, "sentiment": "neutral"
        }

        # Attach sentiment label if not already present (bots.py doesn't add it)
        implied = summary["implied_price"]
        if   implied >= 70: sentiment = "strongly bullish"
        elif implied >= 55: sentiment = "bullish"
        elif implied >= 45: sentiment = "neutral"
        elif implied >= 30: sentiment = "bearish"
        else:               sentiment = "strongly bearish"

        event = {
            "course":        market["course"],
            "name":          market["name"],
            "prediction":    base_price,
            "confidence":    market["confidence"],
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


@app.route("/api/bot-activity")
def api_bot_activity():
    market_key = request.args.get("market_key", "")
    base_price = float(request.args.get("base_price", 50))
    course     = request.args.get("course", "UNKNOWN")
    q_num      = request.args.get("question_num", "1")
    a_num      = request.args.get("answer_num",   "1")

    if not market_key:
        market_key = f"{course}_q{q_num}_a{a_num}"

    current = _get_price(market_key, base_price)

    # Build a minimal market dict so bots can form beliefs without a DB hit
    stub_market = {
        "course":             course,
        "question_num":       q_num,
        "answer_num":         a_num,
        "initial_prediction": base_price,
        "history":            [{"percent": base_price}],
        "confidence":         50,
    }

    with _bots_lock:
        trades = run_bot_round(_bots, stub_market, current)

    new_price = _apply_price_impact(current, trades)
    _set_price(market_key, new_price)

    # Format for the frontend (which expects bot, personality, direction, size)
    return jsonify({
        "bot_trades":    trades,
        "current_price": round(new_price, 2),
    })


@app.route("/api/trade", methods=["POST"])
def api_trade():
    data       = request.get_json(silent=True) or {}
    market_key = data.get("market_key", "default")
    base_price = float(data.get("base_price", 50))
    direction  = data.get("direction", "HIGHER").upper()
    size       = int(data.get("size", 50))

    if not market_key:
        market_key = "default"

    current = _get_price(market_key, base_price)
    # Player's own trade moves price
    impact  = size * 0.3 * (1 if direction == "HIGHER" else -1)
    current = max(5.0, min(95.0, current + impact))
    _set_price(market_key, current)

    # Reactive bot response
    stub_market = {
        "course":             data.get("course", "?"),
        "question_num":       data.get("question_num", 1),
        "answer_num":         data.get("answer_num", 1),
        "initial_prediction": base_price,
        "history":            [{"percent": base_price}],
        "confidence":         50,
    }

    with _bots_lock:
        bot_trades = run_bot_round(_bots, stub_market, current)

    new_price = _apply_price_impact(current, bot_trades)
    _set_price(market_key, new_price)

    return jsonify({"new_price": round(new_price, 2), "bot_trades": bot_trades})


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


@app.route("/api/prediction-market")
def api_prediction_market():
    selected_course = request.args.get("course")
    question_num    = request.args.get("question_num", type=int)
    answer_num      = request.args.get("answer_num",  type=int)
    if selected_course:
        market = create_prediction_market_for_course_code(
            selected_course,
            question_num=question_num,
            answer_num=answer_num,
        )
    else:
        market = create_random_prediction_market()
    if market is None:
        return jsonify({"error": "Could not create a prediction market."}), 500
    
    
    return jsonify(market)

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
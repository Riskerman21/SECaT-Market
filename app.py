from flask import Flask, render_template, jsonify, request
import os
from game import prepare_round, get_course_group_list
from prediction_market import (
    create_random_prediction_market,
    create_prediction_market_for_course_code,
    get_course_list,
    make_market_cache_key,      # NEW: needed to key the price state
)
from bots import create_bots, run_bot_round, summarise_trades  # NEW

app = Flask(__name__)

# Bot roster — created once at startup so balances persist across rounds.
_bots = create_bots()

# Dynamic price state.
#
# Tracks cumulative HIGHER / LOWER share counts per market so the price
# moves as bots and users trade.  Keyed by the market's cache key string.
# In production you would store this in a database or Redis; for the demo
# an in-process dict is fine.
# ---------------------------------------------------------------------------
_market_shares: dict[str, dict] = {}   # { market_key: {"higher": int, "lower": int} }


def get_market_price(market_key: str, base_price: float) -> float:
    """
    Return the current live price for a market.

    Formula: base prediction + (net HIGHER pressure / sensitivity).
    Every 10 net HIGHER shares moves the price up ~1 percentage point.
    Clamps to [1, 99] so the price never hits an impossible extreme.
    """
    shares = _market_shares.get(market_key, {"higher": 0, "lower": 0})
    net_pressure = shares["higher"] - shares["lower"]
    sensitivity = 10.0
    shift = net_pressure / sensitivity
    return max(1.0, min(99.0, base_price + shift))


def record_trade(market_key: str, direction: str, size: int) -> None:
    """Persist one trade into the in-memory price state."""
    if market_key not in _market_shares:
        _market_shares[market_key] = {"higher": 0, "lower": 0}
    if direction == "HIGHER":
        _market_shares[market_key]["higher"] += size
    else:
        _market_shares[market_key]["lower"] += size


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/prediction")
def prediction_page():
    return render_template("prediction.html")


@app.route("/api/round")
def api_round():
    selected_groups_raw = request.args.get("groups", "")
    course_groups = [
        group.strip()
        for group in selected_groups_raw.split(",")
        if group.strip()
    ]
    round_data = prepare_round(course_groups=course_groups)
    if round_data is None:
        return jsonify({
            "error": "Could not prepare a valid round. Please try again."
        }), 500
    return jsonify(round_data)


@app.route("/api/courses")
def api_courses():
    return jsonify({
        "courses": get_course_list()
    })


@app.route("/api/course-groups")
def api_course_groups():
    return jsonify({
        "groups": get_course_group_list()
    })

@app.route("/api/prediction-market")
def api_prediction_market():
    selected_course = request.args.get("course")
    question_num = request.args.get("question_num", type=int)
    answer_num = request.args.get("answer_num", type=int)

    if selected_course:
        market = create_prediction_market_for_course_code(
            selected_course,
            question_num=question_num,
            answer_num=answer_num
        )
    else:
        market = create_random_prediction_market()

    if market is None:
        return jsonify({
            "error": "Could not create a prediction market for this course/question."
        }), 500

    # Attach the live price and market key so the frontend can reference them.
    market_key = make_market_cache_key(
        market["course"],
        market["question_num"],
        market["answer_num"],
        max_history=5,
    )
    live_price = get_market_price(market_key, market["initial_prediction"])
    market["market_key"] = market_key
    market["current_price"] = round(live_price, 2)

    return jsonify(market)


# User trade endpoint
@app.route("/api/trade", methods=["POST"])
def api_trade():
    """
    Accept a trade from the user, update the price, then trigger a bot round
    so the market reacts immediately.

    Expected JSON body:
        {
            "market_key": "<string>",   // from the market object
            "base_price": <float>,      // market["initial_prediction"]
            "direction": "HIGHER"|"LOWER",
            "size": <int>
        }

    Returns:
        {
            "new_price": float,
            "bot_trades": [ ...trade records... ],
            "bot_summary": { ...summarise_trades output... }
        }
    """
    data = request.get_json(force=True)
    market_key = data.get("market_key")
    base_price = float(data.get("base_price", 50.0))
    direction = data.get("direction", "").upper()
    size = int(data.get("size", 1))

    if not market_key or direction not in ("HIGHER", "LOWER"):
        return jsonify({"error": "Invalid trade parameters."}), 400

    # 1. Record the user's trade.
    record_trade(market_key, direction, size)

    # 2. Reload (cache-hit) the market so bots have fresh data.
    #    market_key format: market_COURSECODE_qN_aN_hN_latest
    #    We need the actual market object to pass to run_bot_round.
    #    Parse the key to reconstruct the lookup.
    parts = market_key.split("_")
    # key structure: market / COURSECODE / qN / aN / hN / latest
    course_code_val = parts[1] if len(parts) > 1 else None
    question_num = int(parts[2][1:]) if len(parts) > 2 else None
    answer_num = int(parts[3][1:]) if len(parts) > 3 else None

    market = create_prediction_market_for_course_code(
        course_code_val,
        question_num=question_num,
        answer_num=answer_num,
    ) if course_code_val else None

    bot_trades = []
    if market is not None:
        # 3. Get the price AFTER the user's trade so bots react to the new level.
        price_after_user = get_market_price(market_key, base_price)

        # 4. Run one bot round at the updated price.
        bot_trades = run_bot_round(_bots, market, current_price=price_after_user)

        # 5. Record each bot's trade into the price state.
        for bt in bot_trades:
            record_trade(market_key, bt["direction"], bt["size"])

    # 6. Compute the final price after all bot trades.
    final_price = get_market_price(market_key, base_price)

    return jsonify({
        "new_price": round(final_price, 2),
        "bot_trades": bot_trades,
        "bot_summary": summarise_trades(bot_trades),
    })


# Bot activity endpoint (for polling / initial order-book population)
@app.route("/api/bot-activity")
def api_bot_activity():
    """
    Trigger a passive bot round without a user trade.
    Call this once on page load to pre-populate the order book,
    or on a slow timer (every 15–30 s) to keep activity visible.

    Query params mirror /api/prediction-market:
        course, question_num, answer_num
    """
    selected_course = request.args.get("course")
    question_num = request.args.get("question_num", type=int)
    answer_num = request.args.get("answer_num", type=int)
    market_key = request.args.get("market_key")
    base_price = request.args.get("base_price", type=float)

    if selected_course:
        market = create_prediction_market_for_course_code(
            selected_course,
            question_num=question_num,
            answer_num=answer_num,
        )
    else:
        market = create_random_prediction_market()

    if market is None:
        return jsonify({"error": "No market available."}), 500

    if market_key is None:
        market_key = make_market_cache_key(
            market["course"],
            market["question_num"],
            market["answer_num"],
            max_history=5,
        )

    if base_price is None:
        base_price = market["initial_prediction"]

    current_price = get_market_price(market_key, base_price)
    bot_trades = run_bot_round(_bots, market, current_price=current_price)

    for bt in bot_trades:
        record_trade(market_key, bt["direction"], bt["size"])

    new_price = get_market_price(market_key, base_price)

    return jsonify({
        "bot_trades": bot_trades,
        "bot_summary": summarise_trades(bot_trades),
        "current_price": round(new_price, 2),
    })


if __name__ == "__main__":
    app.run()
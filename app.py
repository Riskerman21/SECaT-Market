from flask import Flask, render_template, jsonify, request
import os

from game import (
    prepare_round,
    prepare_challenger,
    get_course_group_list,
)

from prediction_market import (
    create_random_prediction_market,
    create_prediction_market_for_course_code,
    get_course_list,
    make_market_cache_key,
)

from bots import create_bots, run_bot_round, summarise_trades


app = Flask(__name__)

_bots = create_bots()

_market_shares: dict[str, dict] = {}


def get_market_price(market_key: str, base_price: float) -> float:
    shares = _market_shares.get(market_key, {"higher": 0, "lower": 0})
    net_pressure = shares["higher"] - shares["lower"]
    sensitivity = 10.0
    shift = net_pressure / sensitivity
    return max(1.0, min(99.0, base_price + shift))


def record_trade(market_key: str, direction: str, size: int) -> None:
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


@app.route("/api/challenger")
def api_challenger():
    course = request.args.get("course")
    name = request.args.get("name", "")
    label = request.args.get("label")
    sem = request.args.get("sem", type=int)
    year = request.args.get("year", type=int)

    question_num = request.args.get("question_num", type=int)
    answer_num = request.args.get("answer_num", type=int)

    groups_raw = request.args.get("groups", "")
    used_raw = request.args.get("used", "")

    course_groups = [
        group.strip()
        for group in groups_raw.split(",")
        if group.strip()
    ]

    used_labels = [
        used.strip()
        for used in used_raw.split("||")
        if used.strip()
    ]

    if not course or not label or sem is None or year is None:
        return jsonify({
            "error": "Missing current offering details."
        }), 400

    if question_num is None or answer_num is None:
        return jsonify({
            "error": "Missing question or answer details."
        }), 400

    current_offering = {
        "course": course,
        "name": name,
        "label": label,
        "sem": sem,
        "year": year,
    }

    challenger = prepare_challenger(
        current_offering=current_offering,
        question_num=question_num,
        answer_num=answer_num,
        course_groups=course_groups,
        used_labels=used_labels,
    )

    if challenger is None:
        return jsonify({
            "error": "Could not prepare challenger."
        }), 500

    return jsonify(challenger)


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


@app.route("/api/trade", methods=["POST"])
def api_trade():
    data = request.get_json(force=True)

    market_key = data.get("market_key")
    base_price = float(data.get("base_price", 50.0))
    direction = data.get("direction", "").upper()
    size = int(data.get("size", 1))

    if not market_key or direction not in ("HIGHER", "LOWER"):
        return jsonify({"error": "Invalid trade parameters."}), 400

    record_trade(market_key, direction, size)

    parts = market_key.split("_")

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
        price_after_user = get_market_price(market_key, base_price)

        bot_trades = run_bot_round(
            _bots,
            market,
            current_price=price_after_user
        )

        for bt in bot_trades:
            record_trade(market_key, bt["direction"], bt["size"])

    final_price = get_market_price(market_key, base_price)

    return jsonify({
        "new_price": round(final_price, 2),
        "bot_trades": bot_trades,
        "bot_summary": summarise_trades(bot_trades),
    })


@app.route("/api/bot-activity")
def api_bot_activity():
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

    bot_trades = run_bot_round(
        _bots,
        market,
        current_price=current_price
    )

    for bt in bot_trades:
        record_trade(market_key, bt["direction"], bt["size"])

    new_price = get_market_price(market_key, base_price)

    return jsonify({
        "bot_trades": bot_trades,
        "bot_summary": summarise_trades(bot_trades),
        "current_price": round(new_price, 2),
    })


if __name__ == "__main__":
    app.run(debug=True)
from flask import Flask, render_template, jsonify, request

from game import prepare_round, get_course_group_list
from prediction_market import (
    create_random_prediction_market,
    create_prediction_market_for_course_code,
    get_course_list,
)

app = Flask(__name__)


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

    return jsonify(market)


if __name__ == "__main__":
    app.run(debug=True)
from flask import Flask, render_template, jsonify
from game import prepare_round

app = Flask(__name__)


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/round")
def api_round():
    round_data = prepare_round()

    if round_data is None:
        return jsonify({
            "error": "Could not prepare a valid round. Please try again."
        }), 500

    return jsonify(round_data)


if __name__ == "__main__":
    app.run(debug=True)
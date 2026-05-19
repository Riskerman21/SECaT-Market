"""
seed_markets.py — Pre-seed one prediction market per course into the DB.

Run manually at deploy time:
    python seed_markets.py

Safe to re-run (idempotent via ON CONFLICT in get_or_create_market).
"""

import sys
import secat_cache
from game import COURSES, course_code
from prediction_market import create_prediction_market_for_course_code

QUESTION_NUM = 8  # Q8: Overall Rating
ANSWER_NUM   = 1  # 1 Strongly Agree


def seed_all_markets():
    if not secat_cache.db_available():
        print("[ERROR] Database not available. Set DATABASE_URL and try again.")
        sys.exit(1)

    successes = 0
    failures  = 0

    for course in COURSES:
        code = course_code(course)
        print(f"Seeding {code}...", end=" ", flush=True)

        try:
            market = create_prediction_market_for_course_code(
                code, question_num=QUESTION_NUM, answer_num=ANSWER_NUM
            )
            if market is None:
                print("SKIP (no historical data)")
                failures += 1
                continue

            upcoming = market.get("upcoming_offering", {})
            db_market = secat_cache.get_or_create_market(
                code,
                market["question_num"],
                market["answer_num"],
                market.get("question_name", ""),
                market.get("answer", ""),
                market["initial_prediction"],
                market["confidence"],
                upcoming.get("sem", 1),
                upcoming.get("year", 2025),
            )

            if db_market is None:
                print("FAIL (DB error)")
                failures += 1
            else:
                print(f"OK (id={db_market['id']}, price={db_market['current_price']:.1f})")
                successes += 1

        except Exception as exc:
            print(f"ERROR: {exc}")
            failures += 1

    print(f"\nDone: {successes} seeded, {failures} failed/skipped.")


if __name__ == "__main__":
    seed_all_markets()

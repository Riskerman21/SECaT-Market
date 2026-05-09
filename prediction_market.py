import random
import re
import secat_cache

from game import (
    COURSES,
    course_code,
    course_name,
    course_display,
    offering_display,
    get_available_offerings_for_course,
    get_answer_from_offering,
    answer_option_name,
)


# Keep this as [1] if you only want Strongly Agree.
# Use [1, 4] if you want Strongly Agree and Disagree.
PREDICTION_ANSWER_OPTIONS = [1]


def sort_offerings_newest_first(offerings):
    return sorted(
        offerings,
        key=lambda offering: (offering["year"], offering["sem"]),
        reverse=True
    )


def semester_index(sem: int, year: int):
    return year * 2 + sem


def next_calendar_semester(latest_sem: int, latest_year: int):
    """
    Normal calendar progression:
    S1 2025 -> S2 2025
    S2 2025 -> S1 2026
    """

    if latest_sem == 1:
        return {
            "sem": 2,
            "year": latest_year,
            "reason": "The latest offering was Semester 1, so the next calendar semester is Semester 2 of the same year."
        }

    return {
        "sem": 1,
        "year": latest_year + 1,
        "reason": "The latest offering was Semester 2, so the next calendar semester is Semester 1 of the next year."
    }


def infer_upcoming_offering(offerings):
    """
    Infers the likely next offering based on previous available offerings.

    Rules:
    - If the course appears in both Semester 1 and Semester 2 historically,
      assume it follows normal semester progression.
    - If the course only appears in Semester 1, predict next Semester 1.
    - If the course only appears in Semester 2, predict next Semester 2.
    """

    if len(offerings) == 0:
        return None

    sorted_offerings = sort_offerings_newest_first(offerings)
    latest = sorted_offerings[0]

    semesters_available = sorted(set(offering["sem"] for offering in offerings))

    latest_sem = latest["sem"]
    latest_year = latest["year"]

    if semesters_available == [1]:
        upcoming = {
            "course": latest["course"],
            "name": latest.get("name", ""),
            "sem": 1,
            "year": latest_year + 1,
            "label": f"{latest['course']}: Semester 1, {latest_year + 1}",
            "basis": "semester_1_only",
            "reason": "This course has historically only appeared in Semester 1, so the next likely offering is Semester 1 of the following year."
        }

        return upcoming

    if semesters_available == [2]:
        upcoming = {
            "course": latest["course"],
            "name": latest.get("name", ""),
            "sem": 2,
            "year": latest_year + 1,
            "label": f"{latest['course']}: Semester 2, {latest_year + 1}",
            "basis": "semester_2_only",
            "reason": "This course has historically only appeared in Semester 2, so the next likely offering is Semester 2 of the following year."
        }

        return upcoming

    next_sem = next_calendar_semester(latest_sem, latest_year)

    upcoming = {
        "course": latest["course"],
        "name": latest.get("name", ""),
        "sem": next_sem["sem"],
        "year": next_sem["year"],
        "label": f"{latest['course']}: Semester {next_sem['sem']}, {next_sem['year']}",
        "basis": "both_semesters_available",
        "reason": "This course has appeared in both Semester 1 and Semester 2 historically, so the next likely offering follows normal semester progression."
    }

    return upcoming


def get_previous_offerings(course, before_year=None, before_sem=None):
    """
    Gets previous offerings for a course.

    If before_year and before_sem are provided, only offerings before that
    target semester are used.

    If not provided, all available offerings are used as history.
    """

    code = course_code(course)
    name = course_name(course)

    offerings = get_available_offerings_for_course(code, name)

    if before_year is not None and before_sem is not None:
        target_index = semester_index(before_sem, before_year)

        offerings = [
            offering for offering in offerings
            if semester_index(offering["sem"], offering["year"]) < target_index
        ]

    return sort_offerings_newest_first(offerings)


def weighted_average(values):
    """
    Calculates a weighted average where newer values receive more weight.

    If values are:
    [most_recent, older, oldest]

    Weights become:
    [3, 2, 1]
    """

    if len(values) == 0:
        return None

    weights = []

    for i in range(len(values)):
        weights.append(len(values) - i)

    weighted_sum = 0
    total_weight = 0

    for value, weight in zip(values, weights):
        weighted_sum += value * weight
        total_weight += weight

    return weighted_sum / total_weight


def confidence_from_history(history):
    """
    Simple confidence score from 0 to 100.

    It rewards:
    - having more historical offerings
    - having stable previous percentages
    """

    if len(history) == 0:
        return 0

    percentages = [item["percent"] for item in history]

    average = sum(percentages) / len(percentages)

    variance = sum(
        (percent - average) ** 2
        for percent in percentages
    ) / len(percentages)

    standard_deviation = variance ** 0.5

    history_score = min(len(history) / 5, 1.0) * 60
    consistency_score = max(0, 40 - standard_deviation)

    confidence = history_score + consistency_score

    return round(min(confidence, 100), 1)


def predict_percentage_for_course(
    course,
    question_num,
    answer_num,
    max_history=5,
    before_year=None,
    before_sem=None,
    previous_offerings=None
):
    """
    Predicts the percentage for a course/question/answer using previous offerings.
    If previous_offerings is provided, it avoids reloading offerings again.
    """

    if previous_offerings is None:
        previous_offerings = get_previous_offerings(
            course,
            before_year=before_year,
            before_sem=before_sem
        )
    else:
        if before_year is not None and before_sem is not None:
            target_index = semester_index(before_sem, before_year)

            previous_offerings = [
                offering for offering in previous_offerings
                if semester_index(offering["sem"], offering["year"]) < target_index
            ]

        previous_offerings = sort_offerings_newest_first(previous_offerings)

    if len(previous_offerings) == 0:
        return None

    history = []

    for offering in previous_offerings:
        if len(history) >= max_history:
            break

        result = get_answer_from_offering(
            offering,
            question_num,
            answer_num
        )

        if result is None:
            continue

        history.append({
            "offering": offering,
            "percent": result["PERCENT_ANSWER"],
            "count": result["VALUE"],
            "answered": result["ANSWERED_QUESTION"],
            "question_name": result["QUESTION_NAME"],
            "answer": result["ANSWER"],
        })

    if len(history) == 0:
        return None

    percentages = [
        item["percent"]
        for item in history
    ]

    prediction = weighted_average(percentages)

    return {
        "course": course_code(course),
        "name": course_name(course),
        "question_num": question_num,
        "answer_num": answer_num,
        "answer_name": answer_option_name(answer_num),
        "prediction": round(prediction, 2),
        "history": history,
    }


def make_market_cache_key(
    course_code_value,
    question_num,
    answer_num,
    max_history,
    before_year=None,
    before_sem=None
):
    """
    Builds a stable cache key for a prediction market.
    """

    before_part = "latest"

    if before_year is not None and before_sem is not None:
        before_part = f"before_sem{before_sem}_{before_year}"

    return (
        f"market_{course_code_value.upper()}"
        f"_q{question_num}"
        f"_a{answer_num}"
        f"_h{max_history}"
        f"_{before_part}"
    )


def create_prediction_market(
    course,
    question_num=None,
    answer_num=None,
    max_history=5,
    before_year=None,
    before_sem=None,
    use_cache=True
):
    """
    Creates one prediction market for one course.

    It:
    - infers the likely upcoming semester
    - uses previous offerings as history
    - creates an initial prediction
    - caches the final market object
    """

    if question_num is None:
        question_num = random.randint(1, 8)

    if answer_num is None:
        answer_num = random.choice(PREDICTION_ANSWER_OPTIONS)

    code = course_code(course)
    name = course_name(course)

    cache_key = make_market_cache_key(
        code,
        question_num,
        answer_num,
        max_history,
        before_year=before_year,
        before_sem=before_sem
    )

    if use_cache:
        cached_market = secat_cache.get_cached_json(
            cache_key,
            secat_cache.MARKET_CACHE_SECONDS
        )

        if cached_market is not None:
            print(f"[MARKET CACHE HIT] {code} Q{question_num} A{answer_num}")
            return cached_market

    print(f"[MARKET BUILD] {code} Q{question_num} A{answer_num}")

    all_offerings = get_available_offerings_for_course(code, name)

    if len(all_offerings) == 0:
        return None

    upcoming_offering = infer_upcoming_offering(all_offerings)

    if upcoming_offering is None:
        return None

    prediction_data = predict_percentage_for_course(
        course,
        question_num,
        answer_num,
        max_history=max_history,
        before_year=before_year,
        before_sem=before_sem,
        previous_offerings=all_offerings
    )

    if prediction_data is None:
        return None

    history = prediction_data["history"]

    confidence = confidence_from_history(history)

    latest_question_name = history[0]["question_name"]
    latest_answer = history[0]["answer"]

    market = {
        "course": prediction_data["course"],
        "name": prediction_data["name"],

        "question_num": question_num,
        "answer_num": answer_num,

        "question_name": latest_question_name,
        "answer": latest_answer,

        "initial_prediction": prediction_data["prediction"],
        "confidence": confidence,

        "history_count": len(history),

        "upcoming_offering": {
            "course": upcoming_offering["course"],
            "name": upcoming_offering.get("name", ""),
            "sem": upcoming_offering["sem"],
            "year": upcoming_offering["year"],
            "label": upcoming_offering["label"],
            "basis": upcoming_offering["basis"],
            "reason": upcoming_offering["reason"],
            "display": offering_display(upcoming_offering),
        },

        "history": [
            {
                "offering": offering_display(item["offering"]),
                "course": item["offering"]["course"],
                "name": item["offering"].get("name", ""),
                "sem": item["offering"]["sem"],
                "year": item["offering"]["year"],
                "percent": round(item["percent"], 2),
                "count": item["count"],
                "answered": item["answered"],
            }
            for item in history
        ],
    }

    if use_cache:
        print(f"[MARKET CACHE SAVE] {code} Q{question_num} A{answer_num}")
        secat_cache.set_cached_json(cache_key, market)

    return market


def create_prediction_market_for_course_code(
    course_code_value,
    question_num=None,
    answer_num=None,
    max_history=5,
    before_year=None,
    before_sem=None,
    use_cache=True
):
    """
    Creates a prediction market for a specific course selected by the user.
    """

    selected_course = None

    for course in COURSES:
        if course_code(course).upper() == course_code_value.upper():
            selected_course = course
            break

    if selected_course is None:
        return None

    return create_prediction_market(
        selected_course,
        question_num=question_num,
        answer_num=answer_num,
        max_history=max_history,
        before_year=before_year,
        before_sem=before_sem,
        use_cache=use_cache
    )


def create_random_prediction_market(max_attempts=30):
    """
    Picks a random course and creates a prediction market for it.
    """

    for attempt in range(1, max_attempts + 1):
        print(f"Creating random prediction market attempt {attempt}/{max_attempts}...")

        course = random.choice(COURSES)

        market = create_prediction_market(course)

        if market is not None:
            return market

    return None


def get_course_list():
    """
    Returns all courses for the frontend dropdown.
    """

    return [
        {
            "code": course_code(course),
            "name": course_name(course),
            "display": course_display(course),
        }
        for course in COURSES
    ]


def get_questions_for_course(course_code_value):
    """
    Gets available question names for a selected course using the most recent
    available offering.

    This version loads the newest offering only once instead of loading it
    once per question.
    """

    selected_course = None

    for course in COURSES:
        if course_code(course).upper() == course_code_value.upper():
            selected_course = course
            break

    if selected_course is None:
        return []

    offerings = get_previous_offerings(selected_course)

    if len(offerings) == 0:
        return []

    newest_offering = offerings[0]

    cache_key = (
        f"secat_data_{newest_offering['course']}"
        f"_sem{newest_offering['sem']}"
        f"_{newest_offering['year']}"
    )

    cached_course_data = secat_cache.get_cached_json(
        cache_key,
        secat_cache.SECAT_DATA_CACHE_SECONDS
    )

    if cached_course_data is not None:
        print(f"[QUESTIONS CACHE HIT] {offering_display(newest_offering)}")
        course_data = cached_course_data
    else:
        print(f"[QUESTIONS LOAD ONCE] {offering_display(newest_offering)}")

        response = request_secat_data.getCourseData(
            newest_offering["course"],
            newest_offering["sem"],
            newest_offering["year"]
        )

        if response["error"] is not None:
            print(f"[QUESTIONS ERROR] {response['error']}")
            return []

        try:
            course_data = extract_json_data(response["data"])
        except ValueError:
            return []

        secat_cache.set_cached_json(cache_key, course_data)

    questions_by_num = {}

    for item in course_data:
        question_name = item.get("QUESTION_NAME", "")

        match = re.match(r"Q(\d+):", question_name)

        if not match:
            continue

        question_num = int(match.group(1))

        if question_num not in questions_by_num:
            questions_by_num[question_num] = question_name

    questions = []

    for question_num in sorted(questions_by_num.keys()):
        questions.append({
            "question_num": question_num,
            "question_name": questions_by_num[question_num],
        })

    return questions

if __name__ == "__main__":
    print()
    print("Testing prediction market")
    print("=========================")

    market = create_random_prediction_market()

    if market is None:
        print("Could not create prediction market.")
    else:
        print()
        print(f"Course: {market['course']} - {market['name']}")
        print(f"Upcoming offering: {market['upcoming_offering']['display']}")
        print(f"Upcoming basis: {market['upcoming_offering']['basis']}")
        print(f"Question: {market['question_name']}")
        print(f"Answer: {market['answer']}")
        print(f"Initial prediction: {market['initial_prediction']}%")
        print(f"Confidence: {market['confidence']} / 100")
        print()
        print("Previous semester history:")

        for item in market["history"]:
            print(
                f"- {item['offering']}: "
                f"{item['percent']}% "
                f"({item['count']}/{item['answered']})"
            )
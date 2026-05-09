import json
import re
import random
import request_secat_data
import secat_cache


COURSES = [
    # CSSE courses
    {"code": "CSSE2310", "name": "Computer Systems Principles and Programming"},
    {"code": "CSSE4010", "name": "Digital System Design"},
    {"code": "CSSE1001", "name": "Introduction to Software Engineering"},
    {"code": "CSSE2002", "name": "Programming in the Large"},
    {"code": "CSSE2010", "name": "Introduction to Computer Systems"},
    {"code": "CSSE3010", "name": "Embedded Systems Design and Interfacing"},
    {"code": "CSSE3012", "name": "The Software Process"},
    {"code": "CSSE3100", "name": "Reasoning About Programs"},
    {"code": "CSSE4011", "name": "Advanced Embedded Systems"},
    {"code": "CSSE4630", "name": "Principles of Program Analysis"},
    {"code": "CSSE6400", "name": "Software Architecture"},

    # COMP courses
    {"code": "COMP2048", "name": "Theory of Computing"},
    {"code": "COMP4403", "name": "Compilers and Interpreters"},
    {"code": "COMP3506", "name": "Algorithms and Data Structures"},
    {"code": "COMP4500", "name": "Advanced Algorithms and Data Structures"},
    {"code": "COMP4703", "name": "Natural Language Processing"},
    {"code": "COMP1100", "name": "Introduction to Software Innovation"},
    {"code": "COMP3301", "name": "Operating Systems Architecture"},
    {"code": "COMP3400", "name": "Functional and Logic Programming"},
    {"code": "COMP3710", "name": "Pattern Recognition and Analysis"},
    {"code": "COMP4702", "name": "Machine Learning"},

    # DECO courses
    {"code": "DECO1400", "name": "Introduction to Web Design"},
    {"code": "DECO2500", "name": "Human-Computer Interaction"},
    {"code": "DECO3800", "name": "Design Computing Studio 3 - Proposal"},
    {"code": "DECO3801", "name": "Design Computing Studio 3 - Build"},
    {"code": "DECO6500", "name": "Advanced Human-Computer Interaction"},

    {"code": "COMS3200", "name":"Computer Networks I"},
    {"code": "COMS6200", "name":"Computer Networks II"}
]


FUN_ANSWER_OPTIONS = [1]


def course_code(course):
    if isinstance(course, dict):
        return course["code"]
    return course


def course_name(course):
    if isinstance(course, dict):
        return course.get("name", "")
    return ""


def course_display(course):
    code = course_code(course)
    name = course_name(course)

    if name:
        return f"{code} - {name}"

    return code


def offering_display(offering):
    if offering.get("name"):
        return f"{offering['label']} - {offering['name']}"

    return offering["label"]


def answer_option_name(answer_num: int):
    names = {
        1: "Strongly Agree",
        4: "Disagree",
    }

    return names.get(answer_num, "Unknown")


def extract_json_data(raw_data: str):
    match = re.search(
        r"courseSECATData\s*=\s*(\[.*?\])\s*;",
        raw_data,
        re.DOTALL
    )

    if not match:
        raise ValueError("Could not find courseSECATData array")

    return json.loads(match.group(1))


def parse_offering(offering_text: str, name: str = ""):
    match = re.search(
        r"([A-Z]{4}\d{4}): Semester (\d), (\d{4})",
        offering_text
    )

    if not match:
        return None

    return {
        "course": match.group(1),
        "name": name,
        "sem": int(match.group(2)),
        "year": int(match.group(3)),
        "label": offering_text.strip(),
    }


def semester_index(sem: int, year: int):
    return year * 2 + sem


def offering_distance(offering_a, offering_b):
    index_a = semester_index(offering_a["sem"], offering_a["year"])
    index_b = semester_index(offering_b["sem"], offering_b["year"])

    return abs(index_a - index_b)


def get_available_offerings_for_course(course_code_value: str, name: str = ""):
    """
    Gets available offerings for a course.
    Uses cache first.
    """

    course_code_value = course_code_value.upper()
    cache_key = f"offerings_{course_code_value}"

    cached = secat_cache.get_cached_json(
        cache_key,
        secat_cache.OFFERINGS_CACHE_SECONDS
    )

    if cached is not None:
        print(f"[OFFERINGS CACHE HIT] {course_code_value}")
        return cached

    print(f"[OFFERINGS LOAD] Checking available offerings for {course_code_value}...")

    response = request_secat_data.getCourseData(course_code_value)

    if response["error"] is not None:
        print(f"Could not load offerings for {course_code_value}: {response['error']}")
        return []

    available_offerings = response["available_offerings"]

    parsed_offerings = []

    for offering_text in available_offerings:
        parsed = parse_offering(offering_text, name)

        if parsed is not None:
            parsed_offerings.append(parsed)

    print(f"[OFFERINGS SAVE] {course_code_value}: {len(parsed_offerings)} usable offering(s)")
    secat_cache.set_cached_json(cache_key, parsed_offerings)

    return parsed_offerings


def get_random_course_offering(courses):
    shuffled_courses = courses.copy()
    random.shuffle(shuffled_courses)

    for course in shuffled_courses:
        code = course_code(course)
        name = course_name(course)

        print(f"Trying random course A: {course_display(course)}")

        offerings = get_available_offerings_for_course(code, name)

        if len(offerings) == 0:
            continue

        return random.choice(offerings)

    return None


def get_closest_course_offering(courses, target_offering):
    shuffled_courses = courses.copy()
    random.shuffle(shuffled_courses)

    for course in shuffled_courses:
        code = course_code(course)
        name = course_name(course)

        if code == target_offering["course"]:
            continue

        print(f"Trying course B close to course A: {course_display(course)}")

        offerings = get_available_offerings_for_course(code, name)

        if len(offerings) == 0:
            continue

        closest = min(
            offerings,
            key=lambda offering: offering_distance(target_offering, offering)
        )

        return closest

    return None


def get_answer_from_offering(offering, question_num: int, answer_num: int):
    """
    Gets one answer row from one offering.
    Uses cached full SECaT data first.
    """

    cache_key = (
        f"secat_data_{offering['course']}"
        f"_sem{offering['sem']}"
        f"_{offering['year']}"
    )

    cached_course_data = secat_cache.get_cached_json(
        cache_key,
        secat_cache.SECAT_DATA_CACHE_SECONDS
    )

    if cached_course_data is not None:
        print(f"[DATA CACHE HIT] {offering_display(offering)}")
        course_data = cached_course_data

    else:
        print(f"[DATA LOAD] Loading SECaT data for {offering_display(offering)}...")

        response = request_secat_data.getCourseData(
            offering["course"],
            offering["sem"],
            offering["year"]
        )

        if response["error"] is not None:
            print(f"Could not load SECaT data: {response['error']}")
            return None

        try:
            course_data = extract_json_data(response["data"])
        except ValueError as error:
            print(f"Could not parse SECaT data: {error}")
            return None

        print(f"[DATA SAVE] Saving SECaT data for {offering_display(offering)}")
        secat_cache.set_cached_json(cache_key, course_data)

    matching_results = [
        item for item in course_data
        if item["QUESTION_NAME"].startswith(f"Q{question_num}:")
        and item["ANSWER"].startswith(str(answer_num))
    ]

    if len(matching_results) == 0:
        return None

    return matching_results[0]


def prepare_round(max_attempts: int = 20):
    """
    Creates one complete website round.
    Returns a dictionary suitable for JSON.
    """

    for attempt in range(1, max_attempts + 1):
        print(f"Preparing website round attempt {attempt}/{max_attempts}...")

        question_num = random.randint(1, 8)
        answer_num = random.choice(FUN_ANSWER_OPTIONS)

        offering_a = get_random_course_offering(COURSES)

        if offering_a is None:
            continue

        offering_b = get_closest_course_offering(COURSES, offering_a)

        if offering_b is None:
            continue

        if offering_a["label"] == offering_b["label"]:
            continue

        data_a = get_answer_from_offering(
            offering_a,
            question_num,
            answer_num
        )

        data_b = get_answer_from_offering(
            offering_b,
            question_num,
            answer_num
        )

        if data_a is None or data_b is None:
            continue

        percent_a = data_a["PERCENT_ANSWER"]
        percent_b = data_b["PERCENT_ANSWER"]

        if percent_b > percent_a:
            correct_answer = "higher"
        elif percent_b < percent_a:
            correct_answer = "lower"
        else:
            correct_answer = "same"

        return {
            "question_name": data_a["QUESTION_NAME"],
            "answer_option": data_a["ANSWER"],

            "left": {
                "course": offering_a["course"],
                "name": offering_a["name"],
                "label": offering_a["label"],
                "display": offering_display(offering_a),
                "count": data_a["VALUE"],
                "percent": round(percent_a, 2),
            },

            "right": {
                "course": offering_b["course"],
                "name": offering_b["name"],
                "label": offering_b["label"],
                "display": offering_display(offering_b),
                "count": data_b["VALUE"],
                "percent": round(percent_b, 2),
            },

            "correct_answer": correct_answer,
        }

    return None
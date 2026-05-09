import time
import argparse

import request_secat_data
import secat_cache

from game import (
    COURSES,
    FUN_ANSWER_OPTIONS,
    course_code,
    course_name,
    course_display,
    offering_display,
    parse_offering,
    extract_json_data,
    get_answer_from_offering,
)

from prediction_market import (
    PREDICTION_ANSWER_OPTIONS,
    create_prediction_market,
)


QUESTION_NUMBERS = list(range(1, 9))


def preload_offerings_for_course(course, force=False):
    code = course_code(course)
    name = course_name(course)

    cache_key = f"offerings_{code}"

    cached = secat_cache.get_cached_json(
        cache_key,
        secat_cache.OFFERINGS_CACHE_SECONDS
    )

    if cached is not None and not force:
        print(f"[OFFERINGS CACHE HIT] {course_display(course)}")
        return cached

    print()
    print(f"[OFFERINGS LOAD] {course_display(course)}")
    print("------------------------------------")

    response = request_secat_data.getCourseData(code)

    if response["error"] is not None:
        print(f"[ERROR] Could not load offerings for {code}: {response['error']}")
        return []

    parsed_offerings = []

    for offering_text in response["available_offerings"]:
        parsed = parse_offering(offering_text, name)

        if parsed is not None:
            parsed_offerings.append(parsed)

    print(f"[OFFERINGS FOUND] {code}: {len(parsed_offerings)} usable offering(s)")
    print(f"[OFFERINGS SAVE] Saving offerings for {code} to cache")

    secat_cache.set_cached_json(cache_key, parsed_offerings)

    return parsed_offerings


def preload_secat_data_for_offering(offering, force=False):
    cache_key = f"secat_data_{offering['course']}_sem{offering['sem']}_{offering['year']}"

    cached = secat_cache.get_cached_json(
        cache_key,
        secat_cache.SECAT_DATA_CACHE_SECONDS
    )

    if cached is not None and not force:
        print(f"[DATA CACHE HIT] {offering_display(offering)}")
        return True

    print()
    print(f"[DATA LOAD] {offering_display(offering)}")
    print("------------------------------------")

    response = request_secat_data.getCourseData(
        offering["course"],
        offering["sem"],
        offering["year"]
    )

    if response["error"] is not None:
        print(f"[ERROR] Could not load SECaT data for {offering_display(offering)}")
        print(f"        {response['error']}")
        return False

    try:
        course_data = extract_json_data(response["data"])
    except ValueError as error:
        print(f"[ERROR] Could not parse SECaT data for {offering_display(offering)}")
        print(f"        {error}")
        return False

    print(f"[DATA FOUND] {len(course_data)} response rows")
    print(f"[DATA SAVE] Saving SECaT data for {offering_display(offering)}")

    secat_cache.set_cached_json(cache_key, course_data)

    return True


def preload_prediction_markets_for_course(
    course,
    force=False,
    max_history=5,
    question_numbers=None,
    answer_options=None
):
    code = course_code(course)

    if question_numbers is None:
        question_numbers = QUESTION_NUMBERS

    if answer_options is None:
        answer_options = PREDICTION_ANSWER_OPTIONS

    total_built = 0
    total_failed = 0
    total_hit_or_saved = 0

    print()
    print(f"[MARKET PRELOAD] {course_display(course)}")
    print("------------------------------------")

    for question_num in question_numbers:
        for answer_num in answer_options:
            print()
            print(f"[MARKET CHECK] {code} Q{question_num} answer {answer_num}")

            try:
                market = create_prediction_market(
                    course,
                    question_num=question_num,
                    answer_num=answer_num,
                    max_history=max_history,
                    use_cache=not force
                )

                if market is None:
                    print(f"[MARKET FAILED] No usable market for {code} Q{question_num} A{answer_num}")
                    total_failed += 1
                    continue

                # If force=True, create_prediction_market bypasses cache read
                # but still saves if use_cache=True only. So we manually save by
                # calling it again with cache enabled is not ideal.
                # Better approach: if force=True, call again with use_cache=True
                # is avoided to prevent double work. Instead, users should normally
                # run without --force for market cache.
                print(
                    f"[MARKET READY] {code} Q{question_num} A{answer_num} "
                    f"-> {market['initial_prediction']}%"
                )

                total_hit_or_saved += 1
                total_built += 1

            except Exception as error:
                print(f"[MARKET ERROR] {code} Q{question_num} A{answer_num}: {error}")
                total_failed += 1

    return {
        "built": total_built,
        "failed": total_failed,
        "available": total_hit_or_saved,
    }


def build_cache(
    delay_seconds=1.0,
    max_courses=None,
    max_offerings_per_course=None,
    force=False,
    preload_data=True,
    preload_markets=True,
    max_history=5
):
    print()
    print("Starting SECaT cache preloader")
    print("==============================")
    print(f"Courses available: {len(COURSES)}")
    print(f"Delay between offering loads: {delay_seconds} second(s)")
    print(f"Force refresh: {force}")
    print(f"Preload SECaT data: {preload_data}")
    print(f"Preload prediction markets: {preload_markets}")
    print(f"Market history length: {max_history}")
    print()

    courses_to_process = COURSES

    if max_courses is not None:
        courses_to_process = COURSES[:max_courses]

    total_offerings_seen = 0
    total_data_loaded = 0
    total_data_failed = 0
    total_markets_ready = 0
    total_markets_failed = 0

    for course_index, course in enumerate(courses_to_process, start=1):
        print()
        print("====================================================")
        print(f"Course {course_index}/{len(courses_to_process)}")
        print(f"{course_display(course)}")
        print("====================================================")

        offerings = preload_offerings_for_course(course, force=force)

        if len(offerings) == 0:
            print(f"[SKIP] No offerings available for {course_display(course)}")
            continue

        if max_offerings_per_course is not None:
            offerings = offerings[:max_offerings_per_course]

        print(f"[COURSE QUEUE] {len(offerings)} offering(s) to check")

        if preload_data:
            for offering_index, offering in enumerate(offerings, start=1):
                print()
                print(
                    f"Offering {offering_index}/{len(offerings)} "
                    f"for {course_code(course)}"
                )

                total_offerings_seen += 1

                success = preload_secat_data_for_offering(
                    offering,
                    force=force
                )

                if success:
                    total_data_loaded += 1
                else:
                    total_data_failed += 1

                print()
                print("[DATA PROGRESS]")
                print(f"  Offerings checked: {total_offerings_seen}")
                print(f"  Data cached/available: {total_data_loaded}")
                print(f"  Failed: {total_data_failed}")

                if delay_seconds > 0:
                    print(f"Sleeping for {delay_seconds} second(s)...")
                    time.sleep(delay_seconds)

        if preload_markets:
            market_result = preload_prediction_markets_for_course(
                course,
                force=False,
                max_history=max_history,
                question_numbers=QUESTION_NUMBERS,
                answer_options=PREDICTION_ANSWER_OPTIONS
            )

            total_markets_ready += market_result["available"]
            total_markets_failed += market_result["failed"]

            print()
            print("[MARKET PROGRESS]")
            print(f"  Markets cached/available: {total_markets_ready}")
            print(f"  Markets failed: {total_markets_failed}")

    print()
    print("Cache preload complete")
    print("======================")
    print(f"Offerings checked: {total_offerings_seen}")
    print(f"SECaT data cached/available: {total_data_loaded}")
    print(f"SECaT data failed: {total_data_failed}")
    print(f"Prediction markets cached/available: {total_markets_ready}")
    print(f"Prediction markets failed: {total_markets_failed}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Preload SECaT offerings, SECaT data, and prediction markets into the local cache."
    )

    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="Delay in seconds between SECaT data loads. Default: 1.0"
    )

    parser.add_argument(
        "--max-courses",
        type=int,
        default=None,
        help="Only preload the first N courses. Useful for testing."
    )

    parser.add_argument(
        "--max-offerings-per-course",
        type=int,
        default=None,
        help="Only preload the first N offerings per course. Useful for testing."
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force refresh offerings and SECaT data even if cached data already exists."
    )

    parser.add_argument(
        "--no-data",
        action="store_true",
        help="Skip preloading raw SECaT offering data."
    )

    parser.add_argument(
        "--no-markets",
        action="store_true",
        help="Skip preloading prediction markets."
    )

    parser.add_argument(
        "--max-history",
        type=int,
        default=5,
        help="Number of previous offerings used for each prediction market. Default: 5"
    )

    args = parser.parse_args()

    build_cache(
        delay_seconds=args.delay,
        max_courses=args.max_courses,
        max_offerings_per_course=args.max_offerings_per_course,
        force=args.force,
        preload_data=not args.no_data,
        preload_markets=not args.no_markets,
        max_history=args.max_history
    )
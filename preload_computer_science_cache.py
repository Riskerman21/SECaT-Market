import os
import time

import request_secat_data
import secat_cache
from game import extract_json_data


# Only preload the past 4 years.
# Based on your current data, this means 2022, 2023, 2024, 2025.
MIN_YEAR = 2022

# Safety limit so one course does not take forever.
MAX_OFFERINGS_PER_COURSE = 8

# Be gentle on the UQ SECaT site.
SLEEP_BETWEEN_REQUESTS = 0.5


COURSES = [

    # Computer Science / Software / Design Computing

    "CSSE2310",

    "CSSE4010",

    "CSSE1001",

    "CSSE2002",

    "CSSE2010",

    "CSSE3010",

    "CSSE3012",

    "CSSE3100",

    "CSSE4011",

    "CSSE4630",

    "CSSE6400",

    "COMP2048",

    "COMP4403",

    "COMP3506",

    "COMP4500",

    "COMP4703",

    "COMP1100",

    "COMP3301",

    "COMP3400",

    "COMP3710",

    "COMP4702",

    "DECO1400",

    "DECO2500",

    "DECO3800",

    "DECO3801",

    "DECO6500",

    "COMS3200",

    "COMS6200",

    # Engineering

    "ENGG1300",

    "ENGG1001",

    "ENGG1100",

    "ENGG1500",

    "ENGG1700",

    # Electrical Engineering

    "ELEC2300",

    "ELEC4410",

    "ELEC2400",

    "ELEC3100",

    "ELEC3310",

    "ELEC4302",

    "ELEC2004",

    # Mechanical Engineering

    "MECH2410",

    "MECH2210",

    "MECH3780",

    "MECH3100",

    "MECH3410",

    "MECH2100",

    "MECH2300",

    "MECH2310",

    "MECH2700",

    "MECH3301",

    # Psychology

    "PSYC1030",

    "PSYC2381",

    "PSYC3020",

    "PSYC4221",

    "PSYC1020",

    "PSYC1040",

    "PSYC2010",

    "PSYC3032",

    "PSYC3082",

    # Information Systems

    "INFS1200",

    "INFS2200",

    "INFS3200",

    "INFS3202",

    "INFS3208",

    "INFS4203",

    "INFS4205",

]


def db_has_data(code: str, sem: int, year: int) -> bool:
    """
    Return True if DigitalOcean PostgreSQL already has SECaT rows
    for this course offering.
    """
    return secat_cache._db_get_secat_data(code, sem, year) is not None


def preload_course(code: str):
    code = code.upper()
    print(f"\n=== {code} ===")

    offerings = secat_cache._db_get_offerings(code)

    if not offerings:
        print(f"[NO DB OFFERINGS] {code}")
        return

    offerings = sorted(
        offerings,
        key=lambda x: (x["year"], x["sem"]),
        reverse=True,
    )

    offerings = [
        offering for offering in offerings
        if offering["year"] >= MIN_YEAR
    ]

    offerings = offerings[:MAX_OFFERINGS_PER_COURSE]

    print(f"[OFFERINGS TO CHECK] {code}: {len(offerings)}")

    for offering in offerings:
        sem = offering["sem"]
        year = offering["year"]

        if db_has_data(code, sem, year):
            print(f"[SKIP DB DATA EXISTS] {code} S{sem} {year}")
            continue

        # First try uploading from your local file cache.
        local_data = secat_cache._file_get_secat_data(code, sem, year)

        if local_data:
            print(
                f"[UPLOAD LOCAL CACHE] {code} S{sem} {year}: "
                f"{len(local_data)} rows"
            )

            ok = secat_cache._db_set_secat_data(code, sem, year, local_data)

            if ok:
                print(f"[SAVED DB DATA] {code} S{sem} {year}")
            else:
                print(f"[DB SAVE FAILED] {code} S{sem} {year}")

            continue

        # If no local cache, scrape live.
        print(f"[SCRAPE] {code} S{sem} {year}")

        response = request_secat_data.getCourseData(code, sem, year)

        if response.get("error"):
            print(f"[FAILED] {code} S{sem} {year}: {response['error']}")
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue

        try:
            data = extract_json_data(response["data"])
        except Exception as e:
            print(f"[PARSE FAILED] {code} S{sem} {year}: {e}")
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue

        if not data:
            print(f"[EMPTY DATA] {code} S{sem} {year}")
            time.sleep(SLEEP_BETWEEN_REQUESTS)
            continue

        ok = secat_cache._db_set_secat_data(code, sem, year, data)

        if ok:
            print(f"[SAVED DB DATA] {code} S{sem} {year}: {len(data)} rows")
        else:
            print(f"[DB SAVE FAILED] {code} S{sem} {year}")

        time.sleep(SLEEP_BETWEEN_REQUESTS)


def main():
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "DATABASE_URL is not set. Run export DATABASE_URL=... first."
        )

    print("Starting missing SECaT data preload...")
    print(f"Minimum year: {MIN_YEAR}")
    print(f"Courses: {len(COURSES)}")

    for code in COURSES:
        try:
            preload_course(code)
        except KeyboardInterrupt:
            print("\nStopped by user.")
            break
        except Exception as e:
            print(f"[COURSE ERROR] {code}: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
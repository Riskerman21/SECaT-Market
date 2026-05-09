import json
import os
import time


CACHE_DIR = "cache"

# Cache expiry times
OFFERINGS_CACHE_SECONDS = 60 * 60 * 24 * 7      # 7 days
SECAT_DATA_CACHE_SECONDS = 60 * 60 * 24 * 30    # 30 days
MARKET_CACHE_SECONDS = 60 * 60 * 24 * 7


def ensure_cache_dir():
    if not os.path.exists(CACHE_DIR):
        os.makedirs(CACHE_DIR)


def safe_filename(value: str):
    return (
        value.replace("/", "_")
        .replace("\\", "_")
        .replace(":", "_")
        .replace(",", "_")
        .replace(" ", "_")
    )


def cache_path(key: str):
    ensure_cache_dir()
    return os.path.join(CACHE_DIR, safe_filename(key) + ".json")


def is_cache_valid(path: str, max_age_seconds: int):
    if not os.path.exists(path):
        return False

    modified_time = os.path.getmtime(path)
    age = time.time() - modified_time

    return age <= max_age_seconds


def get_cached_json(key: str, max_age_seconds: int):
    path = cache_path(key)

    if not is_cache_valid(path, max_age_seconds):
        return None

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return None


def set_cached_json(key: str, data):
    path = cache_path(key)

    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2)
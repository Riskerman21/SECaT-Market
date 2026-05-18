# SECaT-Market
SECaT Arcade turns real UQ student survey data into games. Higher or Lower lets players guess historical course satisfaction results. Coins earned there can be used in a fake prediction market where players bet on future course outcomes using previous semester trends.

The project was built for gamejam2026

---

## Project Structure

```text
.
├── prediction_market.py
├── preload_computer_science_cache.py
├── Procfile
├── README.md
├── request_secat_data.py
├── requirements.txt
├── secat_cache.py
├── static
│   ├── audio
│   │   ├── challenger-found.mp3
│   │   ├── correct.mp3
│   │   ├── count-up.mp3
│   │   ├── looking-for-challenger.mp3
│   │   └── wrong.mp3
│   ├── css
│   │   ├── common.css
│   │   ├── higher-lower.css
│   │   ├── main.css
│   │   └── prediction.css
│   ├── higher-or-lower-logo.png
│   └── js
│       ├── common.js
│       ├── higher-lower.js
│       └── prediction.js
└── templates
    ├── index.html
    ├── main.html
    └── prediction.html
```

---

## Caching

The app caches three types of data to avoid redundant web scraping:

| Cache type | Key format | TTL |
|---|---|---|
| Available offerings for a course | `offerings_{COURSE_CODE}` | 7 days |
| Raw SECaT data for one offering | `secat_data_{COURSE}_sem{SEM}_{YEAR}` | 30 days |
| Prediction market result | `market_{COURSE}_q{Q}_a{A}_h{H}_latest` | 7 days |

### PostgreSQL (recommended for deployment)

Set the `DATABASE_URL` environment variable to a PostgreSQL connection string and the app will use a `cache_entries` table automatically created on first run:

```text
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

Heroku and Railway set `DATABASE_URL` automatically when you provision a Postgres add-on. Note that Heroku uses a `postgres://` prefix — the app rewrites it to `postgresql://` internally so psycopg2 accepts it.

The table schema created at startup:

```sql
CREATE TABLE IF NOT EXISTS cache_entries (
    key TEXT PRIMARY KEY,
    data JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### File-based cache (local dev fallback)

If `DATABASE_URL` is not set (or the database is unreachable), the app falls back to writing JSON files in the `cache/` directory. This works out of the box for local development with no extra setup.

---

## Setup

### 1. Clone the repository

```bash
git clone https://github.com/GuardianCoding/SECaT-Market
cd SECaT-Market
```

### 2. Create a virtual environment

```bash
python -m venv venv
```

Activate it:

```bash
source venv/bin/activate
```

On Windows:

```bash
venv\Scripts\activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Also install Playwright's browser binaries (required for scraping):

```bash
playwright install chromium
```

### 4. (Optional) Configure a PostgreSQL database

Skip this step to use the file-based cache instead.

**Local Postgres:**

```bash
createdb secat_cache
export DATABASE_URL=postgresql://localhost/secat_cache
```

**Heroku / Railway:**

Add a Postgres add-on from the dashboard — `DATABASE_URL` is set for you automatically.

### 5. Run the Flask app

```bash
python app.py
```

The app should start locally at:

```text
http://127.0.0.1:5000
```

---

## Testing the PostgreSQL cache

### 1. Verify the table was created

After starting the app (with `DATABASE_URL` set), connect to your database and check:

```sql
SELECT * FROM cache_entries LIMIT 5;
```

You should see rows appear after the first cache miss (i.e. the first time a course is looked up).

### 2. Confirm cache hits in the server logs

On first load of a course the server prints lines like:

```
[OFFERINGS LOAD] Checking available offerings for COMP3506...
[OFFERINGS SAVE] COMP3506: 8 usable offering(s)
[DB] PostgreSQL cache pool initialized
```

On subsequent requests within the TTL you will see:

```
[OFFERINGS CACHE HIT] COMP3506
[DATA CACHE HIT] COMP3506: Semester 2, 2024
```

### 3. Test the fallback

Unset `DATABASE_URL` (or point it at an unreachable host) and restart the app. You should see:

```
[DB] Pool init failed: ...
```

The app should continue working normally, writing to the `cache/` directory instead.

### 4. Force a cache miss

Delete a row from the table to trigger a fresh scrape:

```sql
DELETE FROM cache_entries WHERE key = 'offerings_COMP3506';
```

Then visit a page that uses that course — you should see a `[OFFERINGS LOAD]` log line again.

---

## Static Files

The higher or lower image is from the website https://www.higherorlowergame.com.
The game is inspired by it too.

---

## Notes

This project uses real UQ SECaT-style data for educational and entertainment purposes. It is not intended to offend, ridicule, or evaluate teaching staff. The prediction market uses fake currency only and has no real-money value.

## Credits

By Abdallah Azazy and Youssef Hassan.

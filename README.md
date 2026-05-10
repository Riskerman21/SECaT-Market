# SECaT-Market
SECaT Arcade turns real UQ student survey data into games. Higher or Lower lets players guess historical course satisfaction results. Coins earned there can be used in a fake prediction market where players bet on future course outcomes using previous semester trends.

---

## Project Structure

```text
.
├── app.py
├── game.py
├── prediction_market.py
├── bots.py
├── request_secat_data.py
├── secat_cache.py
├── preload_cache.py
├── cache/
├── static/
│   └── higher-or-lower-logo.png
└── templates/
    ├── main.html
    ├── index.html
    └── prediction.html
```

--- 

## Setup

### 1. Clone the repository

```bash
git clone <your-repository-url>
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

### 4. Run the Flask app

```bash
python app.py
```

The app should start locally at:

```text
http://127.0.0.1:5000
```
---

## Static Files

The higher or lower image is from the website https://www.higherorlowergame.com
The game is inspired by it too.

---

## Notes

This project uses real UQ SECaT-style data for educational and entertainment purposes. It is not intended to offend, ridicule, or evaluate teaching staff. The prediction market uses fake currency only and has no real-money value.

## Credits

By Abdallah Azazy and Youssef Hassan.

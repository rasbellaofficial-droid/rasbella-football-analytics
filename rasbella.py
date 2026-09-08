rasbella.py
import time
import requests
from datetime import datetime, timedelta

# ============================================================
# RASBELLA FOOTBALL ANALYTICS
# Automated Daily Scanner
# ============================================================

API_KEY = os.environ["API_KEY"]
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
CHAT_ID = os.environ["CHAT_ID"]

API_URL = "https://v3.football.api-sports.io"

# API-Football Free plan protection
MAX_PREDICTION_CHECKS = 40
REQUEST_DELAY = 6.5

session = requests.Session()
session.headers.update({
    "x-apisports-key": API_KEY
})


# ============================================================
# API REQUEST
# ============================================================

def api_get(endpoint, params):
    time.sleep(REQUEST_DELAY)

    try:
        response = session.get(
            f"{API_URL}/{endpoint}",
            params=params,
            timeout=30
        )

        data = response.json()

        if data.get("errors"):
            print("API ERROR:", data["errors"])
            return {}

        return data

    except Exception as e:
        print("REQUEST ERROR:", e)
        return {}


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"

    try:
        response = requests.post(
            url,
            data={
                "chat_id": CHAT_ID,
                "text": message
            },
            timeout=30
        )

        print("Telegram:", response.json())

    except Exception as e:
        print("Telegram error:", e)


# ============================================================
# ODDS HELPERS
# ============================================================

def get_odds(entries, market_names, value_names=None):
    if not isinstance(entries, list):
        return []

    results = []

    for item in entries:
        market = str(item.get("market", "")).strip().lower()
        value = str(item.get("value", "")).strip().lower()

        if not any(name in market for name in market_names):
            continue

        if value_names:
            if not any(name in value for name in value_names):
                continue

        try:
            odd = float(item.get("odd"))
        except:
            continue

        results.append(odd)

    return results


def exact_odd(entries, market, value, target, tolerance=0.011):
    odds = get_odds(
        entries,
        [market.lower()],
        [value.lower()]
    )

    return any(abs(odd - target) <= tolerance for odd in odds)


def odd_range(entries, market_names, value_names, low, high):
    odds = get_odds(
        entries,
        [x.lower() for x in market_names],
        [x.lower() for x in value_names]
    )

    return any(low <= odd <= high for odd in odds)


# ============================================================
# RECENT FORM
# ============================================================

def recent_form(team_id, season, today):
    yesterday = today - timedelta(days=1)

    data = api_get(
        "fixtures",
        {
            "team": team_id,
            "season": season,
            "from": (yesterday - timedelta(days=90)).strftime("%Y-%m-%d"),
            "to": yesterday.strftime("%Y-%m-%d"),
            "status": "FT"
        }
    )

    fixtures = data.get("response", [])

    fixtures = sorted(
        fixtures,
        key=lambda x: x.get("fixture", {}).get("date", ""),
        reverse=True
    )[:5]

    wins = 0
    win_by_2 = 0
    btts_over25 = 0

    for match in fixtures:

        teams = match.get("teams", {})
        goals = match.get("goals", {})

        home = teams.get("home", {})
        away = teams.get("away", {})

        home_id = home.get("id")
        away_id = away.get("id")

        home_goals = goals.get("home")
        away_goals = goals.get("away")

        if home_goals is None or away_goals is None:
            continue

        is_home = home_id == team_id

        team_goals = home_goals if is_home else away_goals
        opponent_goals = away_goals if is_home else home_goals

        # Criterion 7
        if team_goals > opponent_goals:
            wins += 1

            # Criterion 8
            if team_goals - opponent_goals >= 2:
                win_by_2 += 1

        # Criterion 9
        total_goals = home_goals + away_goals

        if (
            home_goals >= 1
            and away_goals >= 1
            and total_goals >= 3
        ):
            btts_over25 += 1

    return {
        "matches": len(fixtures),
        "wins": wins,
        "win_by_2": win_by_2,
        "btts_over25": btts_over25
    }


# ============================================================
# MAIN SCANNER
# ============================================================

def main():

    now = datetime.now()
    today = now.date()

    print("=" * 70)
    print("RASBELLA DAILY FOOTBALL SCAN")
    print("Date:", today)
    print("=" * 70)

    # --------------------------------------------------------
    # 1. TODAY'S FIXTURES
    # --------------------------------------------------------

    fixture_data = api_get(
        "fixtures",
        {
            "date": today.strftime("%Y-%m-%d"),
            "timezone": "Africa/Addis_Ababa"
        }
    )

    fixtures = fixture_data.get("response", [])

    print("Today's fixtures:", len(fixtures))

    if not fixtures:
        print("No fixtures found.")
        return

    # --------------------------------------------------------
    # 2. PREDICTIONS
    # --------------------------------------------------------

    candidates = []

    print()
    print("Checking prediction confidence...")

    for index, match in enumerate(fixtures[:MAX_PREDICTION_CHECKS], 1):

        fixture_id = match.get("fixture", {}).get("id")

        if not fixture_id:
            continue

        prediction_data = api_get(
            "predictions",
            {
                "fixture": fixture_id
            }
        )

        prediction_response = prediction_data.get("response", [])

        if not prediction_response:
            continue

        prediction = prediction_response[0].get("predictions", {})

        percent = prediction.get("percent", {})

        try:
            home_conf = float(
                str(percent.get("home", "0")).replace("%", "")
            )
        except:
            home_conf = 0

        try:
            draw_conf = float(
                str(percent.get("draw", "0")).replace("%", "")
            )
        except:
            draw_conf = 0

        try:
            away_conf = float(
                str(percent.get("away", "0")).replace("%", "")
            )
        except:
            away_conf = 0

        confidence = max(
            home_conf,
            draw_conf,
            away_conf
        )

        home_name = match["teams"]["home"]["name"]
        away_name = match["teams"]["away"]["name"]

        print(
            f"{index:02d} | {home_name} vs {away_name} | "
            f"Confidence: {confidence:.0f}%"
        )

        # Criterion 10 must pass before spending more API requests
        if confidence >= 75:

            match["prediction_data"] = prediction_data
            match["confidence"] = confidence

            candidates.append(match)

    print()
    print("75%+ candidates:", len(candidates))

    # --------------------------------------------------------
    # 3. CHECK ODDS + FORM
    # --------------------------------------------------------

    qualified = []

    for match in candidates:

        fixture_id = match["fixture"]["id"]

        home = match["teams"]["home"]
        away = match["teams"]["away"]

        home_name = home["name"]
        away_name = away["name"]

        print()
        print("-" * 70)
        print(home_name, "vs", away_name)

        # ----------------------------------------------------
        # ODDS
        # ----------------------------------------------------

        odds_data = api_get(
            "odds",
            {
                "fixture": fixture_id
            }
        )

        odds_response = odds_data.get("response", [])

        parsed_odds = []

        for bookmaker_block in odds_response:

            bookmaker = bookmaker_block.get("bookmaker", {})
            bookmaker_name = bookmaker.get("name", "")

            for bet in bookmaker_block.get("bets", []):

                market = bet.get("name", "")

                for value_item in bet.get("values", []):

                    value = value_item.get("value", "")
                    odd = value_item.get("odd")

                    try:
                        odd = float(odd)
                    except:
                        continue

                    parsed_odds.append({
                        "bookmaker": bookmaker_name,
                        "market": market,
                        "value": value,
                        "odd": odd
                    })

        # ----------------------------------------------------
        # CRITERION 1
        # BTTS = 1.40
        # ----------------------------------------------------

        c1 = exact_odd(
            parsed_odds,
            "both teams score",
            "yes",
            1.40
        )

        # ----------------------------------------------------
        # CRITERION 2
        # BTTS + Over 2.5 = 1.60 - 1.75
        # ----------------------------------------------------

        c2 = odd_range(
            parsed_odds,
            ["results/both teams score"],
            ["home/yes", "draw/yes", "away/yes"],
            1.60,
            1.75
        )

        # ----------------------------------------------------
        # CRITERION 3
        # Over 2.5 = 1.45 - 1.60
        # ----------------------------------------------------

        c3 = odd_range(
            parsed_odds,
            ["goals over/under"],
            ["over 2.5"],
            1.45,
            1.60
        )

        # ----------------------------------------------------
        # CRITERION 4
        # Over 1.5 = 1.14
        # ----------------------------------------------------

        c4 = exact_odd(
            parsed_odds,
            "goals over/under",
            "over 1.5",
            1.14
        )

        # ----------------------------------------------------
        # CRITERION 5
        # BTTS + Team Win = 1.80 - 2.20
        # ----------------------------------------------------

        c5 = odd_range(
            parsed_odds,
            ["results/both teams score"],
            ["home/yes", "away/yes"],
            1.80,
            2.20
        )

        # ----------------------------------------------------
        # CRITERION 6
        # Team Total Over 1.5 = 1.40 - 1.50
        # ----------------------------------------------------

        c6 = odd_range(
            parsed_odds,
            [
                "home team total goals",
                "away team total goals"
            ],
            ["over 1.5"],
            1.40,
            1.50
        )

        # ----------------------------------------------------
        # RECENT FORM
        # ----------------------------------------------------

        season = match.get("league", {}).get("season")

        home_form = recent_form(
            home["id"],
            season,
            today
        )

        away_form = recent_form(
            away["id"],
            season,
            today
        )

        # ----------------------------------------------------
        # CRITERION 7
        # Winning Team = 4 wins in last 5
        # ----------------------------------------------------

        c7 = (
            home_form["matches"] == 5
            and home_form["wins"] >= 4
        ) or (
            away_form["matches"] == 5
            and away_form["wins"] >= 4
        )

        # ----------------------------------------------------
        # CRITERION 8
        # 3 wins by 2+ goals in last 5
        # ----------------------------------------------------

        c8 = (
            home_form["matches"] == 5
            and home_form["win_by_2"] >= 3
        ) or (
            away_form["matches"] == 5
            and away_form["win_by_2"] >= 3
        )

        # ----------------------------------------------------
        # CRITERION 9
        # BTTS + Over 2.5 in at least 3 of last 5
        # ----------------------------------------------------

        c9 = (
            home_form["matches"] == 5
            and home_form["btts_over25"] >= 3
        ) or (
            away_form["matches"] == 5
            and away_form["btts_over25"] >= 3
        )

        # ----------------------------------------------------
        # CRITERION 10
        # Prediction confidence >= 75%
        # ----------------------------------------------------

        c10 = match["confidence"] >= 75

        criteria = [
            c1, c2, c3, c4, c5,
            c6, c7, c8, c9, c10
        ]

        score = sum(criteria)

        print()
        print("CRITERIA:")
        for i, result in enumerate(criteria, 1):
            print(
                f"{i:02d}. {'PASS' if result else 'FAIL'}"
            )

        print()
        print(
            f"SCORE: {score}/10"
        )

        if score == 10:
            qualified.append({
                "home": home_name,
                "away": away_name,
                "confidence": match["confidence"]
            })

    # ========================================================
    # TELEGRAM ALERT
    # ========================================================

    print()
    print("=" * 70)

    if not qualified:

        print("NO MATCH PASSED ALL 10 CRITERIA.")
        print("No Telegram alert will be sent.")

        return

    message = "🔥 RASBELLA FOOTBALL ALERT 🔥\n\n"
    message += "Matches passing ALL 10 criteria:\n\n"

    for number, match in enumerate(qualified, 1):

        message += (
            f"{number}. {match['home']} vs {match['away']}\n"
            f"Prediction confidence: "
            f"{match['confidence']:.0f}%\n\n"
        )

    message += "✅ All 10 criteria passed."

    send_telegram(message)

    print("Telegram alert sent.")
    print("Qualified:", len(qualified))

    print("=" * 70)


if __name__ == "__main__":
    main()

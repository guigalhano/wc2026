"""
WC 2026 Analytics — Data Fetcher
Fetches: odds, results, weather, news
Saves everything to data/live_data.json
"""
import json, os, urllib.request, urllib.parse, ssl
from datetime import datetime, timezone, timedelta

ODDS_API_KEY = os.environ.get("ODDS_API_KEY","")
WEATHER_BASE = "https://api.open-meteo.com/v1/forecast"
SSL_CTX = ssl.create_default_context()

# WC 2026 venue coordinates + names
VENUES = {
    "New York":      {"lat":40.8135,"lon":-74.0745,"name":"MetLife Stadium, New Jersey"},
    "Los Angeles":   {"lat":33.9534,"lon":-118.3392,"name":"SoFi Stadium, Los Angeles"},
    "Dallas":        {"lat":32.7473,"lon":-97.0945,"name":"AT&T Stadium, Arlington"},
    "San Francisco": {"lat":37.4034,"lon":-121.9696,"name":"Levi's Stadium, Santa Clara"},
    "Miami":         {"lat":25.9580,"lon":-80.2389,"name":"Hard Rock Stadium, Miami"},
    "Atlanta":       {"lat":33.7553,"lon":-84.4006,"name":"Mercedes-Benz Stadium, Atlanta"},
    "Seattle":       {"lat":47.5952,"lon":-122.3316,"name":"Lumen Field, Seattle"},
    "Houston":       {"lat":29.6847,"lon":-95.4107,"name":"NRG Stadium, Houston"},
    "Kansas City":   {"lat":39.0489,"lon":-94.4839,"name":"Arrowhead Stadium, Kansas City"},
    "Philadelphia":  {"lat":39.9008,"lon":-75.1675,"name":"Lincoln Financial Field, Philadelphia"},
    "Boston":        {"lat":42.0909,"lon":-71.2643,"name":"Gillette Stadium, Boston"},
    "Vancouver":     {"lat":49.2767,"lon":-123.1292,"name":"BC Place, Vancouver"},
    "Toronto":       {"lat":43.6333,"lon":-79.5893,"name":"BMO Field, Toronto"},
    "Guadalajara":   {"lat":20.6853,"lon":-103.4018,"name":"Estadio Akron, Guadalajara"},
    "Mexico City":   {"lat":19.3031,"lon":-99.1506,"name":"Estadio Azteca, Mexico City"},
    "Monterrey":     {"lat":25.6693,"lon":-100.3107,"name":"Estadio BBVA, Monterrey"},
}

def fetch_url(url, timeout=15):
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"WC2026Bot/1.0"})
        r = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
        return json.loads(r.read().decode())
    except Exception as e:
        print(f"  ⚠ fetch error {url[:60]}: {e}")
        return None

def fetch_odds():
    print("📊 Fetching odds...")
    sport_keys = ["soccer_fifa_world_cup","soccer_fifa_world_cup_2026","soccer_world_cup"]
    games = []
    sport_used = None
    for key in sport_keys:
        url = (f"https://api.the-odds-api.com/v4/sports/{key}/odds"
               f"?apiKey={ODDS_API_KEY}&regions=eu,uk&markets=h2h,totals,btts"
               f"&oddsFormat=decimal&dateFormat=iso")
        data = fetch_url(url)
        if data and isinstance(data, list) and len(data) > 0:
            games = data
            sport_used = key
            print(f"  ✓ {len(games)} games from {key}")
            break
    result = []
    for g in games:
        home, away = g.get("home_team",""), g.get("away_team","")
        h2h, totals, btts_yes = {}, {}, None
        best = {}
        for bm in g.get("bookmakers",[]):
            for mkt in bm.get("markets",[]):
                mk = mkt.get("key","")
                for o in mkt.get("outcomes",[]):
                    k = f"{mk}_{o['name']}"
                    if k not in best or o.get("price",0) > best[k]["price"]:
                        best[k] = {"market":mk,"outcome":o["name"],"price":o.get("price",0),"bm":bm.get("title","")}
        for k,v in best.items():
            m,o,p = v["market"],v["outcome"],v["price"]
            if m=="h2h":
                if o==home: h2h["home"]=p
                elif o==away: h2h["away"]=p
                elif o=="Draw": h2h["draw"]=p
            elif m=="totals":
                if "Over" in o: totals["over25"]=p
                elif "Under" in o: totals["under25"]=p
            elif m=="btts" and o=="Yes": btts_yes=p
        result.append({
            "id": g.get("id",""),
            "home_team": home, "away_team": away,
            "commence_time": g.get("commence_time",""),
            "h2h": h2h, "totals": totals, "btts_yes": btts_yes,
            "bookmakers_count": len(g.get("bookmakers",[])),
            "sport_key": sport_used
        })
    return result

def fetch_weather():
    print("🌡 Fetching weather for venues...")
    results = {}
    for city, v in VENUES.items():
        url = (f"{WEATHER_BASE}?latitude={v['lat']}&longitude={v['lon']}"
               f"&current=temperature_2m,apparent_temperature,precipitation_probability,"
               f"wind_speed_10m,relative_humidity_2m,weather_code"
               f"&daily=temperature_2m_max,apparent_temperature_max,precipitation_probability_max"
               f"&forecast_days=3&timezone=auto")
        data = fetch_url(url)
        if data and "current" in data:
            c = data["current"]
            d = data.get("daily",{})
            results[city] = {
                "venue": v["name"],
                "temp_c": c.get("temperature_2m"),
                "feels_like": c.get("apparent_temperature"),
                "humidity": c.get("relative_humidity_2m"),
                "wind": c.get("wind_speed_10m"),
                "rain_prob": c.get("precipitation_probability"),
                "weather_code": c.get("weather_code"),
                "max_tomorrow": d.get("apparent_temperature_max",[None,None])[1] if d else None,
                "extreme_heat": (c.get("apparent_temperature") or 0) >= 38,
                "utci_risk": "extreme" if (c.get("apparent_temperature") or 0) >= 46 else
                             "high" if (c.get("apparent_temperature") or 0) >= 38 else "moderate"
            }
        else:
            results[city] = {"venue": v["name"], "error": "unavailable"}
    ok = sum(1 for v in results.values() if "temp_c" in v)
    print(f"  ✓ Weather for {ok}/{len(VENUES)} venues")
    return results

def fetch_news_headlines():
    """Fetch recent WC 2026 headlines via web search (DuckDuckGo instant API)."""
    print("📰 Fetching news headlines...")
    queries = [
        "FIFA World Cup 2026 team news injury",
        "Copa do Mundo 2026 escalação lesão",
        "World Cup 2026 results scores today",
    ]
    headlines = []
    for q in queries:
        encoded = urllib.parse.quote(q)
        url = f"https://api.duckduckgo.com/?q={encoded}&format=json&no_html=1&skip_disambig=1"
        data = fetch_url(url)
        if data:
            if data.get("Abstract"):
                headlines.append({"title": data.get("Heading",""), "text": data.get("Abstract",""), "url": data.get("AbstractURL","")})
            for r in data.get("RelatedTopics",[])[:3]:
                if isinstance(r,dict) and r.get("Text"):
                    headlines.append({"title": r.get("Text","")[:100], "text": r.get("Text",""), "url": r.get("FirstURL","")})
    print(f"  ✓ {len(headlines)} headlines")
    return headlines[:12]

def main():
    now = datetime.now(timezone.utc)
    print(f"\n🚀 WC 2026 Data Fetch — {now.isoformat()}\n")
    os.makedirs("data", exist_ok=True)

    odds = fetch_odds()
    weather = fetch_weather()
    news = fetch_news_headlines()

    # Get today's and tomorrow's games
    today = now.date()
    tomorrow = today + timedelta(days=1)
    todays_games = [g for g in odds if g.get("commence_time","")[:10] == str(today)]
    tomorrows_games = [g for g in odds if g.get("commence_time","")[:10] == str(tomorrow)]

    output = {
        "updated_at": now.isoformat(),
        "updated_at_brt": (now - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M BRT"),
        "games_count": len(odds),
        "games": odds,
        "todays_games": todays_games,
        "tomorrows_games": tomorrows_games,
        "weather": weather,
        "news": news,
    }

    with open("data/live_data.json","w") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    print(f"\n✅ Saved data/live_data.json ({len(odds)} games, {len(weather)} venues)")

if __name__ == "__main__":
    main()

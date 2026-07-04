"""
WC 2026 Analytics — AI Content Generator
Uses Claude to generate:
  - Daily value bets
  - Match previews for today's/tomorrow's games
  - Updated tactical notes
Saves to data/ai_content.json
"""
import json, os, urllib.request, urllib.error, ssl, time
from datetime import datetime, timezone, timedelta

CLAUDE_API_KEY = os.environ.get("CLAUDE_API_KEY","")
CLAUDE_MODEL   = "claude-sonnet-4-6"  # fixed: old snapshot claude-sonnet-4-20250514 was returning HTTP 404
SSL_CTX = ssl.create_default_context()

# Scout data (static baseline — updated manually each match day)
SCOUTS = {
    "Spain":{"rating":100,"xG":2.95,"xGA":0.88,"pos":63.6,"gm":3.00,"gs":0.90,"style":"Posse dominante, pressing alto, Lamine Yamal","threat_index":8.18},
    "Argentina":{"rating":97.1,"xG":2.40,"xGA":2.00,"pos":63.9,"gm":1.70,"gs":0.60,"style":"Mentalidade campeã, comete poucos erros, Messi decisivo","threat_index":7.8},
    "France":{"rating":95.3,"xG":2.52,"xGA":0.98,"pos":62.3,"gm":2.35,"gs":1.00,"style":"Elenco profundo, transições rápidas, Mbappé","threat_index":8.1},
    "England":{"rating":91.9,"xG":2.59,"xGA":0.26,"pos":74.4,"gm":2.80,"gs":0.00,"style":"Rice-Kane-Bellingham, defesa sólida sob Tuchel","threat_index":7.9},
    "Brazil":{"rating":90.1,"xG":4.50,"xGA":1.90,"pos":62.1,"gm":1.30,"gs":0.90,"style":"Transição profunda Ancelotti, isolar Vinícius Jr","threat_index":8.95},
    "Portugal":{"rating":89.9,"xG":2.75,"xGA":1.07,"pos":64.3,"gm":2.75,"gs":1.15,"style":"Frenesi de cruzamentos, Vitinha-Neves-Fernandes","threat_index":7.6},
    "Colombia":{"rating":89.5,"xG":3.60,"xGA":1.60,"pos":56.8,"gm":1.60,"gs":1.00,"style":"Luis Díaz nas alas, ataque prolífico","threat_index":7.4},
    "Netherlands":{"rating":87.7,"xG":2.30,"xGA":1.11,"pos":62.2,"gm":2.85,"gs":1.00,"style":"Pressing estruturado Koeman, divisão clara de espaços","threat_index":7.5},
    "Germany":{"rating":86.6,"xG":2.51,"xGA":1.05,"pos":67.0,"gm":2.55,"gs":0.85,"style":"Wirtz-Musiala, 1/3 gols em bolas paradas","threat_index":8.87},
    "Norway":{"rating":86.2,"xG":3.36,"xGA":0.53,"pos":57.5,"gm":4.60,"gs":0.60,"style":"Dependência total de Haaland, ritmo brutal","threat_index":8.2},
    "Croatia":{"rating":85.7,"xG":2.42,"xGA":1.05,"pos":58.8,"gm":2.30,"gs":0.90,"style":"Posse inteligente de Modric, mentalidade eliminatória","threat_index":7.32},
    "Japan":{"rating":85.6,"xG":None,"xGA":None,"pos":69.2,"gm":3.40,"gs":0.20,"style":"Alta intensidade com Kubo, sem Mitoma","threat_index":7.1},
    "Turkey":{"rating":85.6,"xG":1.69,"xGA":1.39,"pos":54.7,"gm":2.40,"gs":1.50,"style":"Gegenpressing com laterais ofensivos","threat_index":6.8},
    "Belgium":{"rating":84.6,"xG":2.48,"xGA":1.11,"pos":62.5,"gm":2.30,"gs":1.20,"style":"De Bruyne e Doku no ataque, defesa frágil","threat_index":7.3},
    "Morocco":{"rating":81,"xG":1.52,"xGA":0.55,"pos":60.3,"gm":2.05,"gs":0.30,"style":"Imposição física, evolução de posse sob Lamouchi","threat_index":6.5},
    "Mexico":{"rating":None,"xG":1.16,"xGA":None,"pos":None,"gm":None,"gs":None,"style":"Altitude Azteca, Aguirre pragmático, Raúl Jiménez","threat_index":6.2},
    "United States":{"rating":None,"xG":None,"xGA":None,"pos":None,"gm":None,"gs":None,"style":"Copa em casa, versatilidade no meio-campo","threat_index":6.0},
    "Canada":{"rating":None,"xG":None,"xGA":None,"pos":None,"gm":None,"gs":None,"style":"4-4-2, Alphonso Davies, pressão alta","threat_index":6.1},
}

def call_claude(prompt, max_tokens=800):
    """Call Claude API and return text response."""
    if not CLAUDE_API_KEY:
        return "Claude API key not configured."
    body = json.dumps({
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "messages": [{"role":"user","content": prompt}]
    }).encode()
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "Content-Type": "application/json",
            "x-api-key": CLAUDE_API_KEY,
            "anthropic-version": "2023-06-01"
        },
        method="POST"
    )
    try:
        r = urllib.request.urlopen(req, timeout=30, context=SSL_CTX)
        data = json.loads(r.read().decode())
        return data.get("content",[])[0].get("text","") if data.get("content") else ""
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        print(f"  ⚠ Claude HTTP error: {e.code} {e.reason} — {body}")
        return f"Erro na geração: HTTP {e.code} — {body}"
    except Exception as e:
        print(f"  ⚠ Claude error: {e}")
        return f"Erro na geração: {e}"

def get_scout(team_name):
    """Fuzzy match team name to scout data."""
    name = team_name.lower()
    for k, v in SCOUTS.items():
        if k.lower() in name or name in k.lower():
            return k, v
    return team_name, {}

def generate_match_preview(game, weather_city=None, weather=None):
    """Generate AI preview for a single match."""
    home, away = game["home_team"], game["away_team"]
    h2h = game.get("h2h",{})
    totals = game.get("totals",{})
    btts = game.get("btts_yes")
    dt = game.get("commence_time","")[:16].replace("T"," ")

    _, hs = get_scout(home)
    _, as_ = get_scout(away)

    odds_str = ""
    if h2h:
        odds_str = f"Odds: {home} {h2h.get('home','–')} | Empate {h2h.get('draw','–')} | {away} {h2h.get('away','–')}"
        if totals.get("over25"): odds_str += f" | Over 2.5: {totals['over25']}"
        if btts: odds_str += f" | BTTS: {btts}"

    weather_str = ""
    if weather_city and weather and weather_city in weather:
        w = weather[weather_city]
        if "temp_c" in w:
            weather_str = f"Condições: {w['temp_c']}°C (sensação {w['feels_like']}°C), Umidade {w['humidity']}%, Vento {w['wind']}km/h"
            if w.get("extreme_heat"): weather_str += " ⚠️ CALOR EXTREMO"

    scout_h = f"Rating {hs.get('rating','?')}, xG {hs.get('xG','?')}, xGA {hs.get('xGA','?')}, Estilo: {hs.get('style','?')}" if hs else "Dados limitados"
    scout_a = f"Rating {as_.get('rating','?')}, xG {as_.get('xG','?')}, xGA {as_.get('xGA','?')}, Estilo: {as_.get('style','?')}" if as_ else "Dados limitados"

    prompt = f"""Você é um analista de apostas esportivas especializado em futebol. Gere uma prévia concisa e objetiva para apostas.

JOGO: {home} vs {away} — {dt} UTC
{odds_str}
{weather_str}

DADOS SCOUT:
- {home}: {scout_h}
- {away}: {scout_a}

Responda em português com exatamente este formato JSON (sem markdown, sem texto fora do JSON):
{{
  "resumo": "2 frases sobre o confronto e cenário esperado",
  "aposta_principal": "mercado e odd recomendada",
  "justificativa": "2-3 linhas justificando com dados",
  "apostas_alternativas": ["aposta 2 com odd", "aposta 3 com odd"],
  "risco": "1 frase sobre o risco principal",
  "confianca": "alta|media|baixa"
}}"""

    raw = call_claude(prompt, max_tokens=500)
    try:
        # Extract JSON from response
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except:
        pass
    return {"resumo": raw[:200] if raw else "N/D", "aposta_principal":"N/D","justificativa":"","apostas_alternativas":[],"risco":"","confianca":"media"}

def generate_value_bets(games, weather):
    """Generate daily value bets summary."""
    if not games:
        return {"summary":"Nenhum jogo hoje.", "bets":[], "tip_of_day":None}

    games_str = ""
    for g in games[:8]:  # limit to save tokens
        h2h = g.get("h2h",{})
        games_str += f"- {g['home_team']} vs {g['away_team']}: {h2h.get('home','–')} / {h2h.get('draw','–')} / {h2h.get('away','–')}\n"

    # Top heat warning
    hot_venues = [f"{city} ({w.get('feels_like')}°C)" for city,w in weather.items() if isinstance(w,dict) and (w.get("feels_like") or 0) >= 38]
    heat_str = f"⚠️ Calor extremo: {', '.join(hot_venues)}" if hot_venues else ""

    prompt = f"""Analista de apostas especializado em Copa do Mundo. Hoje são {len(games)} jogos da Copa 2026.

JOGOS E ODDS:
{games_str}
{heat_str}

Baseado nos dados, identifique as 3 melhores apostas de value do dia.
Responda SOMENTE com JSON válido:
{{
  "summary": "Resumo do dia de apostas em 2 frases",
  "tip_of_day": {{
    "jogo": "Time A vs Time B",
    "aposta": "mercado específico",
    "odd": 0.00,
    "justificativa": "razão em 1-2 frases"
  }},
  "bets": [
    {{"jogo":"","aposta":"","odd":0.00,"edge_estimado":"","confianca":"alta|media|baixa","razao":""}},
    {{"jogo":"","aposta":"","odd":0.00,"edge_estimado":"","confianca":"alta|media|baixa","razao":""}},
    {{"jogo":"","aposta":"","odd":0.00,"edge_estimado":"","confianca":"alta|media|baixa","razao":""}}
  ]
}}"""

    raw = call_claude(prompt, max_tokens=600)
    try:
        import re
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            return json.loads(m.group(0))
    except:
        pass
    return {"summary": raw[:300] if raw else "N/D", "bets":[], "tip_of_day":None}

def main():
    now = datetime.now(timezone.utc)
    print(f"\n🤖 WC 2026 AI Generator — {now.isoformat()}\n")

    # Load live data
    try:
        with open("data/live_data.json") as f:
            live = json.load(f)
    except FileNotFoundError:
        print("⚠ data/live_data.json not found. Run fetch_data.py first.")
        live = {"games":[],"todays_games":[],"tomorrows_games":[],"weather":{}}

    weather = live.get("weather",{})
    todays_games = live.get("todays_games",[])
    tomorrows_games = live.get("tomorrows_games",[])
    all_games = todays_games + tomorrows_games

    ai_output = {
        "generated_at": now.isoformat(),
        "generated_at_brt": (now - timedelta(hours=3)).strftime("%d/%m/%Y %H:%M BRT"),
        "value_bets_today": None,
        "match_previews": [],
        "tactical_notes": {},
    }

    # 1. Daily value bets
    print("💰 Generating value bets...")
    if todays_games or tomorrows_games:
        ai_output["value_bets_today"] = generate_value_bets(all_games[:10], weather)
        print("  ✓ Value bets generated")
    else:
        ai_output["value_bets_today"] = {"summary":"Nenhum jogo da Copa encontrado para hoje/amanhã.","bets":[],"tip_of_day":None}

    # 2. Match previews
    print(f"📋 Generating previews for {len(all_games[:6])} matches...")
    for g in all_games[:6]:  # limit to 6 to control costs
        print(f"  → {g['home_team']} vs {g['away_team']}")
        preview = generate_match_preview(g, weather_city=None, weather=weather)
        ai_output["match_previews"].append({
            "game_id": g.get("id",""),
            "home": g["home_team"],
            "away": g["away_team"],
            "time": g.get("commence_time",""),
            "h2h": g.get("h2h",{}),
            "totals": g.get("totals",{}),
            "btts_yes": g.get("btts_yes"),
            "preview": preview
        })
        time.sleep(0.5)

    # Save
    with open("data/ai_content.json","w") as f:
        json.dump(ai_output, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Saved data/ai_content.json")
    print(f"   {len(ai_output['match_previews'])} previews")

if __name__ == "__main__":
    main()

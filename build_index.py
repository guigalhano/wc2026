"""
WC 2026 Analytics — Index Builder
Reads data/live_data.json + data/ai_content.json
Injects dynamic content into index_template.html
Outputs index.html (served by GitHub Pages)
"""
import json, os, re
from datetime import datetime, timezone, timedelta

def weather_icon(code):
    if code is None: return "🌤"
    if code == 0: return "☀️"
    if code <= 3: return "⛅"
    if code <= 48: return "🌫"
    if code <= 67: return "🌧"
    if code <= 77: return "❄️"
    if code <= 82: return "🌦"
    return "⛈"

def build_weather_html(weather):
    if not weather: return ""
    cards = []
    for city, w in list(weather.items())[:8]:
        if "error" in w: continue
        temp = w.get("temp_c","?")
        feels = w.get("feels_like","?")
        icon = weather_icon(w.get("weather_code"))
        risk_color = "#E24B4A" if w.get("utci_risk")=="extreme" else "#BA7517" if w.get("utci_risk")=="high" else "#1D9E75"
        heat_badge = f'<span style="color:{risk_color};font-size:10px;font-weight:600">{"🔥 EXTREMO" if w.get("utci_risk")=="extreme" else "⚠️ ALTO" if w.get("utci_risk")=="high" else "✓ OK"}</span>'
        cards.append(f'''<div class="weather-card">
          <div class="wc-city">{city}</div>
          <div class="wc-venue">{w.get("venue","")}</div>
          <div class="wc-temp">{icon} {temp}°C</div>
          <div class="wc-feels">Sensação: {feels}°C · {w.get("humidity","?")}% umidade</div>
          {heat_badge}
        </div>''')
    return '\n'.join(cards)

def build_value_bets_html(vb):
    if not vb: return "<p style='color:var(--tx3)'>Nenhuma aposta gerada ainda.</p>"
    html = f'<p style="font-size:13px;color:var(--tx2);margin-bottom:1rem">{vb.get("summary","")}</p>'
    # Tip of day
    tip = vb.get("tip_of_day")
    if tip:
        html += f'''<div style="background:var(--gn-bg);border:1.5px solid var(--gn);border-radius:var(--rl);padding:.9rem 1.1rem;margin-bottom:1rem">
          <div style="font-size:10px;font-weight:700;color:var(--gn-tx);text-transform:uppercase;letter-spacing:.05em;margin-bottom:5px">⭐ APOSTA DO DIA</div>
          <div style="font-size:14px;font-weight:600;margin-bottom:3px">{tip.get("jogo","")}</div>
          <div style="font-size:13px;color:var(--gn-tx);font-weight:600">{tip.get("aposta","")} @ <strong>{tip.get("odd","")}</strong></div>
          <div style="font-size:12px;color:var(--tx2);margin-top:5px">{tip.get("justificativa","")}</div>
        </div>'''
    # Other bets
    for b in vb.get("bets",[]):
        conf = b.get("confianca","media")
        color = "var(--gn)" if conf=="alta" else "var(--am)" if conf=="media" else "var(--tx3)"
        html += f'''<div style="background:var(--sf);border:1px solid var(--bd);border-radius:var(--r);padding:.75rem .9rem;margin-bottom:8px;display:flex;justify-content:space-between;align-items:flex-start;gap:10px">
          <div style="flex:1">
            <div style="font-size:12px;font-weight:600;margin-bottom:2px">{b.get("jogo","")} — {b.get("aposta","")}</div>
            <div style="font-size:11px;color:var(--tx2)">{b.get("razao","")}</div>
          </div>
          <div style="text-align:right;flex-shrink:0">
            <div style="font-size:15px;font-weight:700;font-family:'Space Grotesk',sans-serif">{b.get("odd","")}</div>
            <div style="font-size:10px;color:{color};font-weight:600">{conf.upper()}</div>
            <div style="font-size:10px;color:var(--tx3)">{b.get("edge_estimado","")}</div>
          </div>
        </div>'''
    return html

def build_previews_html(previews):
    if not previews: return "<p style='color:var(--tx3);font-size:13px'>Nenhum jogo hoje. Prévia disponível amanhã.</p>"
    html = ""
    for p in previews:
        home, away = p.get("home",""), p.get("away","")
        h2h = p.get("h2h",{})
        pv = p.get("preview",{})
        dt_str = p.get("time","")
        if dt_str:
            try:
                dt = datetime.fromisoformat(dt_str.replace("Z","+00:00"))
                brt = dt - timedelta(hours=3)
                dt_str = brt.strftime("%d/%m %H:%M BRT")
            except: pass
        conf = pv.get("confianca","media")
        conf_color = "var(--gn)" if conf=="alta" else "var(--am)" if conf=="media" else "var(--tx3)"
        alts = "".join([f'<div style="font-size:11px;color:var(--tx2);padding:2px 0">• {a}</div>' for a in pv.get("apostas_alternativas",[])])
        html += f'''<div style="background:var(--sf);border:1px solid var(--bd);border-radius:var(--rl);padding:1rem 1.25rem;margin-bottom:12px;box-shadow:var(--sh)">
          <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:.75rem;flex-wrap:wrap;gap:6px">
            <div style="font-size:14px;font-weight:700;font-family:'Space Grotesk',sans-serif">{home} vs {away}</div>
            <div style="font-size:11px;color:var(--tx3)">{dt_str}</div>
          </div>
          <div style="display:flex;gap:7px;margin-bottom:.75rem">
            <div style="flex:1;text-align:center;padding:6px;background:var(--sf2);border-radius:var(--r)"><div style="font-size:10px;color:var(--tx3)">1 {home.split()[0]}</div><div style="font-size:16px;font-weight:700;font-family:'Space Grotesk',sans-serif">{h2h.get("home","–")}</div></div>
            <div style="flex:1;text-align:center;padding:6px;background:var(--sf2);border-radius:var(--r)"><div style="font-size:10px;color:var(--tx3)">X</div><div style="font-size:16px;font-weight:700;font-family:'Space Grotesk',sans-serif">{h2h.get("draw","–")}</div></div>
            <div style="flex:1;text-align:center;padding:6px;background:var(--sf2);border-radius:var(--r)"><div style="font-size:10px;color:var(--tx3)">2 {away.split()[0]}</div><div style="font-size:16px;font-weight:700;font-family:'Space Grotesk',sans-serif">{h2h.get("away","–")}</div></div>
          </div>
          <div style="font-size:12px;color:var(--tx2);margin-bottom:.6rem;line-height:1.5">{pv.get("resumo","")}</div>
          <div style="background:{'var(--gn-bg)' if conf=='alta' else 'var(--am-bg)' if conf=='media' else 'var(--sf2)'};border-radius:var(--r);padding:.6rem .8rem;margin-bottom:.5rem">
            <div style="font-size:10px;font-weight:600;color:var(--tx3);text-transform:uppercase;margin-bottom:3px">APOSTA PRINCIPAL · <span style="color:{conf_color}">{conf.upper()}</span></div>
            <div style="font-size:13px;font-weight:600">{pv.get("aposta_principal","N/D")}</div>
            <div style="font-size:11px;color:var(--tx2);margin-top:3px">{pv.get("justificativa","")}</div>
          </div>
          {f'<div style="margin-top:.4rem">{alts}</div>' if alts else ''}
          {f'<div style="font-size:11px;color:var(--rd-tx);margin-top:.4rem">⚠️ {pv.get("risco","")}</div>' if pv.get("risco") else ''}
        </div>'''
    return html

def main():
    print("\n🔨 Building index.html...\n")

    # Load data
    try:
        with open("data/live_data.json") as f: live = json.load(f)
    except: live = {"games":[],"weather":{},"news":[],"updated_at_brt":"N/D","games_count":0}

    try:
        with open("data/ai_content.json") as f: ai = json.load(f)
    except: ai = {"value_bets_today":None,"match_previews":[],"tactical_notes":{},"generated_at_brt":"N/D"}

    # Load template
    with open("index_template.html") as f:
        template = f.read()

    # Build dynamic blocks
    now_brt = live.get("updated_at_brt", ai.get("generated_at_brt","N/D"))
    weather_html = build_weather_html(live.get("weather",{}))
    value_bets_html = build_value_bets_html(ai.get("value_bets_today"))
    previews_html = build_previews_html(ai.get("match_previews",[]))

    # News ticker
    news = live.get("news",[])
    news_html = " &nbsp;|&nbsp; ".join([f'📰 {n.get("title","")[:80]}' for n in news[:6]]) or "Copa do Mundo 2026 · Análises atualizadas 2x ao dia"

    # Embed data as JSON for the JS dashboard
    live_json = json.dumps(live, ensure_ascii=False)
    ai_json = json.dumps(ai, ensure_ascii=False)

    # Inject into template
    result = template
    result = result.replace("{{UPDATED_AT}}", now_brt)
    result = result.replace("{{GAMES_COUNT}}", str(live.get("games_count",0)))
    result = result.replace("{{WEATHER_HTML}}", weather_html)
    result = result.replace("{{VALUE_BETS_HTML}}", value_bets_html)
    result = result.replace("{{PREVIEWS_HTML}}", previews_html)
    result = result.replace("{{NEWS_TICKER}}", news_html)
    result = result.replace("{{LIVE_DATA_JSON}}", live_json)
    result = result.replace("{{AI_DATA_JSON}}", ai_json)

    with open("index.html","w") as f:
        f.write(result)

    size = os.path.getsize("index.html")
    print(f"✅ index.html built ({size:,} bytes)")
    print(f"   Updated: {now_brt}")
    print(f"   Games: {live.get('games_count',0)}")
    print(f"   Previews: {len(ai.get('match_previews',[]))}")

if __name__ == "__main__":
    main()

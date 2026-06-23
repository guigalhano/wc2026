#!/usr/bin/env python3
"""
WC2026 Performance Tracker + Match Narratives
Generates data/wc2026_perf.json with per-match stats summaries and
model deviation analysis (why a game went well or badly vs prediction).

Data sources:
- results + standings: football-data.org (via live_data.json)
- xG, match events, player names, possession/shots: mominullptr/FIFA-World-Cup-2026-Dataset
"""
import json, math, os, urllib.request, ssl, csv, io
from datetime import datetime, timezone

FIFA_TO_OUR = {
    'MEX':'MEX','RSA':'AFS','KOR':'COR','CZE':'TCH','CAN':'CAN','BIH':'BOS',
    'QAT':'CAT','SUI':'SUI','BRA':'BRA','MAR':'MAR','HAI':'HAI','SCO':'ESC',
    'USA':'EUA','PAR':'PAR','AUS':'AUS','TUR':'TUR','GER':'ALE','CUW':'CUR',
    'CIV':'CDM','ECU':'EQU','NED':'HOL','JPN':'JAP','SWE':'SUE','TUN':'TUN',
    'BEL':'BEL','EGY':'EGI','IRN':'IRA','NZL':'NZE','ESP':'ESP','CPV':'CAB',
    'KSA':'ARS','URU':'URU','FRA':'FRA','SEN':'SEN','IRQ':'IRQ','NOR':'NOR',
    'ARG':'ARG','ALG':'AGL','AUT':'AUT','JOR':'JOR','POR':'POR','COD':'RDC',
    'UZB':'UZB','COL':'COL','ENG':'ING','CRO':'CRO','GHA':'GAN','PAN':'PAN',
}

ELO = {
    'ESP':2010,'FRA':2009,'ING':1993,'ARG':1976,'BRA':1955,'POR':1945,'ALE':1926,
    'HOL':1894,'NOR':1880,'BEL':1878,'COL':1878,'MAR':1874,'CRO':1852,'SEN':1848,
    'MEX':1834,'URU':1831,'EQU':1829,'EUA':1826,'JAP':1825,'SUI':1812,'AUS':1772,
    'COR':1760,'SUE':1752,'IRA':1747,'CAN':1740,'CDM':1732,'TUR':1731,'AUT':1718,
    'AGL':1704,'EGI':1695,'PAR':1681,'TUN':1680,'ESC':1663,'GAN':1659,'ARS':1657,
    'TCH':1651,'RDC':1650,'UZB':1633,'PAN':1615,'BOS':1602,'IRQ':1599,'CAB':1599,
    'CAT':1592,'AFS':1591,'NZE':1591,'JOR':1548,'CUR':1548,'HAI':1537,
}
HOME_BONUS = {'MEX': 100, 'EUA': 100, 'CAN': 80}
DC_RHO = -0.13

TEAM_NAMES = {
    'ESP':'Spain','ARG':'Argentina','FRA':'France','ING':'England','BRA':'Brazil',
    'POR':'Portugal','COL':'Colombia','HOL':'Netherlands','EQU':'Ecuador','ALE':'Germany',
    'NOR':'Norway','CRO':'Croatia','JAP':'Japan','TUR':'Turkey','SUI':'Switzerland',
    'URU':'Uruguay','BEL':'Belgium','SEN':'Senegal','PAR':'Paraguay','AUT':'Austria',
    'MAR':'Morocco','AUS':'Australia','ESC':'Scotland','IRA':'Iran','AGL':'Algeria',
    'COR':'South Korea','TCH':'Czechia','PAN':'Panama','UZB':'Uzbekistan','SUE':'Sweden',
    'EGI':'Egypt','JOR':'Jordan','CDM':'Ivory Coast','RDC':'DR Congo','TUN':'Tunisia',
    'IRQ':'Iraq','BOS':'Bosnia & Herzegovina','CAB':'Cape Verde','ARS':'Saudi Arabia',
    'NZE':'New Zealand','HAI':'Haiti','AFS':'South Africa','GAN':'Ghana','CUR':'Curaçao',
    'CAT':'Qatar','MEX':'Mexico','CAN':'Canada','EUA':'USA',
}

SSL_CTX = ssl.create_default_context()

def fetch_csv(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=20, context=SSL_CTX)
    return list(csv.DictReader(io.StringIO(r.read().decode())))

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=20, context=SSL_CTX)
    return json.loads(r.read().decode())

def poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    p = math.exp(-lam)
    for i in range(1, k+1): p *= lam / i
    return p

def dc_tau(a, b, lam, mu):
    if a==0 and b==0: return 1 - lam*mu*DC_RHO
    if a==0 and b==1: return 1 + lam*DC_RHO
    if a==1 and b==0: return 1 + mu*DC_RHO
    if a==1 and b==1: return 1 - DC_RHO
    return 1.0

def match_prob(hC, aC):
    rH = ELO.get(hC, 1650); rA = ELO.get(aC, 1650)
    hb = HOME_BONUS.get(hC, 0) - HOME_BONUS.get(aC, 0)
    lam = max(0.3, min(3.5, 1.35 + ((rH+hb) - rA) / 400))
    mu  = max(0.3, min(3.5, 1.35 + (rA - (rH+hb/2)) / 400))
    pH = pD = pA = 0.0
    for a in range(9):
        pa = poisson_pmf(a, lam)
        for b in range(9):
            p = pa * poisson_pmf(b, mu) * dc_tau(a, b, lam, mu)
            if a > b: pH += p
            elif a < b: pA += p
            else: pD += p
    t = pH + pD + pA
    return pH/t, pD/t, pA/t, lam, mu

def build_narrative(hC, aC, g1, g2, pH, pD, pA, lam, mu,
                    hxg, axg, goals, reds, pens,
                    hposs, aposs, hshots, ashots, hsot, asot,
                    has_stats):
    """Build a concise structured narrative explaining the match result vs model."""
    n = TEAM_NAMES
    h, a = n.get(hC, hC), n.get(aC, aC)

    pred = 'H' if pH >= pD and pH >= pA else ('A' if pA >= pH and pA >= pD else 'D')
    real = 'H' if g1 > g2 else ('A' if g2 > g1 else 'D')
    surprise = pred != real

    lines = []

    # 1. Match result vs model verdict
    pred_label = {'H': f'{h} win', 'D': 'draw', 'A': f'{a} win'}
    real_label  = {'H': f'{h} {g1}–{g2} {a}', 'D': f'{h} {g1}–{g2} {a} (draw)', 'A': f'{a} won {g2}–{g1}'}

    if surprise:
        conf = pH if pred=='H' else (pA if pred=='A' else pD)
        lines.append(f"🚨 **Upset**: model predicted {pred_label[pred]} ({conf*100:.0f}% confidence) but ended {g1}–{g2}.")
    else:
        conf = pH if real=='H' else (pA if real=='A' else pD)
        lines.append(f"✅ **Result matched prediction** ({conf*100:.0f}% confidence). Final: {g1}–{g2}.")

    # 2. xG story
    if hxg > 0 or axg > 0:
        if g1 > hxg + 0.8:
            lines.append(f"⚡ {h} outscored their xG significantly ({g1} goals vs {hxg:.1f} xG) — clinical finishing.")
        elif g1 < hxg - 0.8:
            lines.append(f"🧱 {h} underperformed xG ({g1} goals vs {hxg:.1f} xG) — poor finishing or great goalkeeping.")
        if g2 > axg + 0.8:
            lines.append(f"⚡ {a} outscored their xG ({g2} goals vs {axg:.1f} xG) — clinical finishing.")
        elif g2 < axg - 0.8:
            lines.append(f"🧱 {a} underperformed xG ({g2} goals vs {axg:.1f} xG) — poor finishing or great goalkeeping.")
        if abs(g1-g2) <= 1 and abs(hxg-axg) > 1.2:
            dom = h if hxg > axg else a
            lines.append(f"📊 xG suggests {dom} dominated but score doesn't reflect it.")

    # 3. Red cards
    if reds:
        for min_, team, player in reds:
            side = h if team==hC else a
            lines.append(f"🟥 {side} reduced to 10 men ({player}, {min_}') — impacted the game dynamics.")

    # 4. Possession/shots
    if has_stats and hposs and aposs:
        dom = h if float(hposs) > float(aposs) else a
        dom_poss = max(float(hposs), float(aposs))
        if dom_poss > 60:
            lines.append(f"🎯 {dom} controlled possession ({dom_poss:.0f}%) but {['efficiency was the difference','could not convert'][int(dom==h and g1<g2 or dom==a and g2<g1)]}.")

    # 5. Shots efficiency
    if has_stats and hshots and ashots:
        if float(hshots or 0) > 0 and float(ashots or 0) > 0:
            h_conv = g1 / float(hshots) if float(hshots) > 0 else 0
            a_conv = g2 / float(ashots) if float(ashots) > 0 else 0
            if h_conv > 0.25:
                lines.append(f"💥 {h} were clinical: {g1} goals from {hshots} shots ({h_conv*100:.0f}% conversion).")
            if a_conv > 0.25:
                lines.append(f"💥 {a} were clinical: {g2} goals from {ashots} shots ({a_conv*100:.0f}% conversion).")

    # 6. Scoreline vs model xG
    model_diff = lam - mu
    actual_diff = g1 - g2
    if abs(actual_diff) > 3:
        lines.append(f"📉 Scoreline ({g1}–{g2}) was far more one-sided than the model expected (projected ~{lam:.1f}–{mu:.1f}).")

    return lines

# ── ELO auto-update from real WC2026 results ──────────────────────────────
ELO_BASE = {
    'ESP':2010,'FRA':2009,'ING':1993,'ARG':1976,'BRA':1955,'POR':1945,'ALE':1926,
    'HOL':1894,'NOR':1880,'BEL':1878,'COL':1878,'MAR':1874,'CRO':1852,'SEN':1848,
    'MEX':1834,'URU':1831,'EQU':1829,'EUA':1826,'JAP':1825,'SUI':1812,'AUS':1772,
    'COR':1760,'SUE':1752,'IRA':1747,'CAN':1740,'CDM':1732,'TUR':1731,'AUT':1718,
    'AGL':1704,'EGI':1695,'PAR':1681,'TUN':1680,'ESC':1663,'GAN':1659,'ARS':1657,
    'TCH':1651,'RDC':1650,'UZB':1633,'PAN':1615,'BOS':1602,'IRQ':1599,'CAB':1599,
    'CAT':1592,'AFS':1591,'NZE':1591,'JOR':1548,'CUR':1548,'HAI':1537,
}
ELO_K = 55

def compute_live_elo(played_matches):
    """Recalculate ELO from base values using all played WC2026 matches (K=55)."""
    elo = dict(ELO_BASE)
    for m in sorted(played_matches, key=lambda x: x.get('date', '')):
        hC = m.get('home_code', '')
        aC = m.get('away_code', '')
        hg = m.get('home_score')
        ag = m.get('away_score')
        if not hC or not aC or hg is None or ag is None:
            continue
        rH = elo.get(hC, 1600)
        rA = elo.get(aC, 1600)
        pH_exp = 1 / (1 + 10**((rA - rH) / 400))
        ah = 1.0 if hg > ag else (0.5 if hg == ag else 0.0)
        dH = ELO_K * (ah - pH_exp)
        elo[hC] = round(elo.get(hC, 1600) + dH)
        elo[aC] = round(elo.get(aC, 1600) - dH)
    return elo


def main():
    print("WC2026 Performance Tracker v2 — with match narratives")

    # Load real results
    with open('data/live_data.json') as f:
        live = json.load(f)

    wc = live.get('wc_results') or {}
    played = [m for m in wc.get('matches', []) if m.get('home_score') is not None]
    print(f"  {len(played)} played matches")
    if not played:
        return

    # Load mominullptr data
    BASE = "https://raw.githubusercontent.com/mominullptr/FIFA-World-Cup-2026-Dataset/main"
    print("  Fetching mominullptr data...")
    md_rows = fetch_csv(f"{BASE}/matches_detailed.csv")
    evt_rows = fetch_csv(f"{BASE}/match_events.csv")
    match_rows = fetch_csv(f"{BASE}/matches.csv")
    team_rows = fetch_csv(f"{BASE}/teams.csv")
    squad_rows = fetch_csv(f"{BASE}/squads_and_players.csv")
    stats_rows = fetch_csv(f"{BASE}/match_team_stats.csv")

    team_id_to_our = {t['team_id']: FIFA_TO_OUR.get(t['fifa_code'], t['fifa_code']) for t in team_rows}
    player_id_to_name = {s['player_id']: s['player_name'] for s in squad_rows}
    match_id_map = {m['match_id']: m for m in match_rows}

    # index: (date, hC, aC) -> match_detailed row
    det_by_key = {}
    for r in md_rows:
        hc = FIFA_TO_OUR.get(r['home_fifa_code'], r['home_fifa_code'])
        ac = FIFA_TO_OUR.get(r['away_fifa_code'], r['away_fifa_code'])
        det_by_key[(r['date'], hc, ac)] = r

    # events by match_id
    evts_by_mid = {}
    for e in evt_rows:
        evts_by_mid.setdefault(e['match_id'], []).append(e)

    # real xG by (date, hC, aC)
    real_xg_map = {}
    for r in md_rows:
        if r.get('status') != 'Completed': continue
        hc = FIFA_TO_OUR.get(r['home_fifa_code'], '')
        ac = FIFA_TO_OUR.get(r['away_fifa_code'], '')
        try:
            real_xg_map[(r['date'], hc, ac)] = (float(r['home_xg']), float(r['away_xg']))
        except (ValueError, TypeError): pass

    # stats by (mid, tid)
    stats_map = {}
    for s in stats_rows:
        stats_map[(s['match_id'], s['team_id'])] = s

    teams_out = {}
    matches_out = []
    real_xg_used = 0
    narratives_built = 0

    for m in played:
        hC = m.get('home_code', ''); aC = m.get('away_code', '')
        if not hC or not aC: continue
        g1, g2 = m['home_score'], m['away_score']
        date = m.get('date', '')
        pH, pD, pA, lam, mu = match_prob(hC, aC)

        # Real xG
        rxg = real_xg_map.get((date, hC, aC))
        if rxg:
            hxg, axg = rxg; real_xg_used += 1
        else:
            hxg, axg = lam, mu

        # Events
        det = det_by_key.get((date, hC, aC))
        mid = det['match_id'] if det else None
        base = match_id_map.get(mid, {}) if mid else {}
        evts = evts_by_mid.get(mid, []) if mid else []
        goals = [(e['minute'], team_id_to_our.get(e['team_id'],'?'), player_id_to_name.get(e['player_id'],'?'))
                 for e in evts if e['event_type']=='Goal']
        reds  = [(e['minute'], team_id_to_our.get(e['team_id'],'?'), player_id_to_name.get(e['player_id'],'?'))
                 for e in evts if e['event_type']=='Red Card']
        pens  = [e for e in evts if 'Penalty' in e.get('event_type','')]

        # Stats
        h_tid = base.get('home_team_id','')
        a_tid = base.get('away_team_id','')
        hs = stats_map.get((mid, h_tid), {}) if mid else {}
        as_ = stats_map.get((mid, a_tid), {}) if mid else {}

        def n(d, k): return float(d[k]) if d.get(k) else None
        hposs=n(hs,'possession_pct'); aposs=n(as_,'possession_pct')
        hshots=n(hs,'total_shots'); ashots=n(as_,'total_shots')
        hsot=n(hs,'shots_on_target'); asot=n(as_,'shots_on_target')
        has_stats = bool(hs or as_)

        # Generate narrative
        narr = build_narrative(hC,aC,g1,g2,pH,pD,pA,lam,mu,
                               hxg,axg,goals,reds,pens,
                               hposs,aposs,hshots,ashots,hsot,asot,has_stats)
        if narr: narratives_built += 1

        match_entry = {
            'date': date, 'home': hC, 'away': aC, 'g1': g1, 'g2': g2,
            'pH': round(pH,3), 'pD': round(pD,3), 'pA': round(pA,3),
            'lam': round(lam,2), 'mu': round(mu,2),
            'home_xg': round(hxg,2), 'away_xg': round(axg,2),
            'real_xg': bool(rxg),
            'goals': goals, 'reds': reds,
            'home_poss': hposs, 'away_poss': aposs,
            'home_shots': hshots, 'away_shots': ashots,
            'home_sot': hsot, 'away_sot': asot,
            'has_stats': has_stats,
            'narrative': narr,
            'stadium': det.get('stadium_name','') if det else '',
            'city': det.get('city','') if det else '',
            'referee': det.get('referee_name','') if det else '',
        }
        matches_out.append(match_entry)

        for code, opp, gf, ga, p_win, p_draw, p_loss, xgf, xga in [
            (hC,aC,g1,g2,pH,pD,pA,hxg,axg),
            (aC,hC,g2,g1,pA,pD,pH,axg,hxg),
        ]:
            if code not in teams_out:
                teams_out[code] = {'code':code,'name':TEAM_NAMES.get(code,code),
                    'games':0,'goals_for':0,'goals_against':0,'xg_for':0.,'xg_against':0.,
                    'wins':0,'draws':0,'losses':0,'points':0,
                    'expected_points':0.,'matches':[]}
            t = teams_out[code]
            t['games']+=1; t['goals_for']+=gf; t['goals_against']+=ga
            t['xg_for']+=xgf; t['xg_against']+=xga
            t['expected_points']+=p_win*3+p_draw
            if gf>ga: t['wins']+=1; t['points']+=3; result='W'
            elif gf<ga: t['losses']+=1; result='L'
            else: t['draws']+=1; t['points']+=1; result='D'
            me = {'vs':opp,'date':date,'gf':gf,'ga':ga,'xgf':round(xgf,2),'xga':round(xga,2),
                  'result':result,'p_win':round(p_win,3)}
            # attach per-team stats
            s_ref = hs if code==hC else as_
            if s_ref:
                if s_ref.get('possession_pct'): me['real_poss']=float(s_ref['possession_pct'])
                if s_ref.get('total_shots'): me['real_shots']=float(s_ref['total_shots'])
                if s_ref.get('shots_on_target'): me['real_sot']=float(s_ref['shots_on_target'])
                if s_ref.get('corners'): me['real_corners']=float(s_ref['corners'])
            t['matches'].append(me)

    for code, t in teams_out.items():
        t['xpts'] = round(t['expected_points'], 2)
        t['delta_pts'] = round(t['points'] - t['expected_points'], 2)
        t['xgf'] = round(t['xg_for']/t['games'], 2) if t['games'] else 0
        t['xga'] = round(t['xg_against']/t['games'], 2) if t['games'] else 0
        poss_vals = [m['real_poss'] for m in t['matches'] if 'real_poss' in m]
        shots_vals = [m['real_shots'] for m in t['matches'] if 'real_shots' in m]
        if poss_vals: t['real_possession_avg'] = round(sum(poss_vals)/len(poss_vals),1)
        if shots_vals: t['real_shots_avg'] = round(sum(shots_vals)/len(shots_vals),1)

    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'teams': sorted(teams_out.values(), key=lambda x: -x['delta_pts']),
        'matches': sorted(matches_out, key=lambda x: x['date']),
        'real_xg_games': real_xg_used,
        'narratives_built': narratives_built,
        'source': 'football-data.org + mominullptr/FIFA-World-Cup-2026-Dataset',
    }
    # Store live ELO back into live_data.json for build_index.py to inject
    try:
        with open('data/live_data.json') as lf:
            ld = json.load(lf)
        live_elo = compute_live_elo(played)
        ld['live_elo'] = live_elo
        ld['live_elo_games'] = len(played)
        ld['live_elo_updated'] = datetime.now(timezone.utc).isoformat()
        with open('data/live_data.json', 'w') as lf:
            json.dump(ld, lf, ensure_ascii=False, separators=(',', ':'))
        print(f"  Live ELO updated: {len(live_elo)} teams from {len(played)} games")
    except Exception as e:
        print(f"  WARNING: could not update live ELO: {e}")

    os.makedirs('data', exist_ok=True)
    with open('data/wc2026_perf.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"  Saved: {len(teams_out)} teams, {len(matches_out)} matches, {narratives_built} narratives, {real_xg_used} real xG")
    print(f"\nSample narratives:")
    for m in matches_out[:3]:
        print(f"  {m['home']} {m['g1']}-{m['g2']} {m['away']}:")
        for line in m.get('narrative',[])[:2]:
            print(f"    • {line}")

if __name__ == '__main__':
    main()

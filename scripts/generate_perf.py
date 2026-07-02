#!/usr/bin/env python3
"""
WC2026 Performance Tracker — v3
Sources:
  - results/standings : football-data.org (via live_data.json)
  - xG/events/stats  : mominullptr/FIFA-World-Cup-2026-Dataset  (primary, 32 matches)
  - shot maps/xG/BC  : nlbair/wc2026-events  (supplement — 39 matches, WhoScored)
  - ELO auto-update  : computed from all played matches (K=55)
"""
import json, math, os, urllib.request, ssl, csv, io, re
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

# Our code → WhoScored filename slug (nlbair/wc2026-events)
OUR_TO_NLBAIR = {
    'MEX':'mexico','AFS':'south_africa','COR':'republic_of_korea','TCH':'czechia',
    'CAN':'canada','BOS':'bosnia_and_herzegovina','CAT':'qatar','SUI':'switzerland',
    'BRA':'brazil','MAR':'morocco','HAI':'haiti','ESC':'scotland','EUA':'usa',
    'PAR':'paraguay','AUS':'australia','TUR':'turkiye','ALE':'germany','CUR':'curacao',
    'CDM':'ivory_coast','EQU':'ecuador','HOL':'netherlands','JAP':'japan',
    'SUE':'sweden','TUN':'tunisia','BEL':'belgium','EGI':'egypt','IRA':'iran',
    'NZE':'new_zealand','ESP':'spain','CAB':'cabo_verde','ARS':'saudi_arabia',
    'URU':'uruguay','FRA':'france','SEN':'senegal','IRQ':'iraq','NOR':'norway',
    'ARG':'argentina','AGL':'algeria','AUT':'austria','JOR':'jordan','POR':'portugal',
    'RDC':'dr_congo','UZB':'uzbekistan','COL':'colombia','ING':'england',
    'CRO':'croatia','GAN':'ghana','PAN':'panama',
}

ELO_BASE = {
    'ESP':2010,'FRA':2009,'ING':1993,'ARG':1976,'BRA':1955,'POR':1945,'ALE':1926,
    'HOL':1894,'NOR':1880,'BEL':1878,'COL':1878,'MAR':1874,'CRO':1852,'SEN':1848,
    'MEX':1834,'URU':1831,'EQU':1829,'EUA':1826,'JAP':1825,'SUI':1812,'AUS':1772,
    'COR':1760,'SUE':1752,'IRA':1747,'CAN':1740,'CDM':1732,'TUR':1731,'AUT':1718,
    'AGL':1704,'EGI':1695,'PAR':1681,'TUN':1680,'ESC':1663,'GAN':1659,'ARS':1657,
    'TCH':1651,'RDC':1650,'UZB':1633,'PAN':1615,'BOS':1602,'IRQ':1599,'CAB':1599,
    'CAT':1592,'AFS':1591,'NZE':1591,'JOR':1548,'CUR':1548,'HAI':1537,
}
HOME_BONUS = {'MEX':100,'EUA':100,'CAN':80}
# Backtested 2026-07-02 on 82 played matches (out-of-sample validated on knockouts):
#   multiplicative goal model (GOAL_BASE/GOAL_SCALE) + MOV-scaled K=40 + rho=-0.18
#   logloss 0.837 -> 0.80, RPS 0.154 -> 0.140 vs previous additive formula.
DC_RHO = -0.18          # aligned with frontend simulator (was -0.13 here, -0.18 in JS)
ELO_K = 40              # base K; effective K scales with margin of victory (mov_mult)
GOAL_BASE  = 1.25       # expected goals per team when ratings are equal
GOAL_SCALE = 460        # ELO points for a 10x goal-ratio swing (per 2*scale)

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

def fetch_csv(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
    return list(csv.DictReader(io.StringIO(r.read().decode('utf-8','replace'))))

def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=20, context=SSL_CTX)
    return json.loads(r.read().decode())

EFI_BASE = "https://raw.githubusercontent.com/Bustami/efi-fifa-data-wc-2026/master/data"

def _f(row, key):
    try:
        v = row.get(key, '')
        return float(v) if v not in (None, '', 'NA', 'N/A') else 0.0
    except (TypeError, ValueError):
        return 0.0

def fetch_efi_stats():
    """
    Fetch FIFA's official EFI (Enhanced Football Intelligence) player-match data
    from Bustami/efi-fifa-data-wc-2026 and roll it up to team-level per-game averages.
    Note: the EFI CSV's own 'team_name' column is already a FIFA 3-letter code
    (maps directly via FIFA_TO_OUR), and its 'match_id' joins to matches.csv's
    'result_id' (NOT its 'match_id' column — the two files use different keys).
    Returns { our_code: {efi dict} }, or {} if the source is unavailable.
    """
    try:
        efi_rows = fetch_csv(f"{EFI_BASE}/wc2026_efi.csv")
    except Exception as e:
        print(f"  WARNING EFI fetch: {e}")
        return {}

    # (match_id, our_code) -> summed team totals for that match
    per_match = {}
    for r in efi_rows:
        mid = r.get('match_id')
        code = FIFA_TO_OUR.get(r.get('team_name', ''))
        if not code:
            continue
        key = (mid, code)
        agg = per_match.setdefault(key, {
            'xg':0.0,'passes':0.0,'passes_completed':0.0,'total_distance':0.0,
            'sprints':0.0,'forced_turnovers':0.0,'linebreaks_completed':0.0,
            'linebreaks_attempted':0.0,'top_speed':0.0,'players':0,
            'attempts':0.0,'attempts_on_target':0.0,
        })
        agg['xg'] += _f(r,'xg')
        agg['passes'] += _f(r,'passes')
        agg['passes_completed'] += _f(r,'passes_completed')
        agg['total_distance'] += _f(r,'total_distance')
        agg['sprints'] += _f(r,'sprints')
        agg['forced_turnovers'] += _f(r,'forced_turnovers')
        agg['linebreaks_completed'] += _f(r,'linebreaks_attempted_completed')
        agg['linebreaks_attempted'] += _f(r,'linebreaks_attempted')
        agg['attempts'] += _f(r,'attempt_at_goal')
        agg['attempts_on_target'] += _f(r,'attempt_at_goal_on_target')
        agg['top_speed'] = max(agg['top_speed'], _f(r,'top_speed'))
        if _f(r,'time_played') > 0:
            agg['players'] += 1

    # roll per-match team totals up to season (per-game average) per team
    by_team = {}
    for (mid, code), agg in per_match.items():
        by_team.setdefault(code, []).append(agg)

    out = {}
    for code, games in by_team.items():
        n = len(games)
        if not n: continue
        sum_xg      = sum(g['xg'] for g in games)
        sum_pass    = sum(g['passes'] for g in games)
        sum_passc   = sum(g['passes_completed'] for g in games)
        sum_dist    = sum(g['total_distance'] for g in games)
        sum_players = sum(g['players'] for g in games) or 1
        sum_sprints = sum(g['sprints'] for g in games)
        sum_fturn   = sum(g['forced_turnovers'] for g in games)
        sum_lbc     = sum(g['linebreaks_completed'] for g in games)
        sum_lba     = sum(g['linebreaks_attempted'] for g in games)
        sum_att     = sum(g['attempts'] for g in games)
        sum_att_ot  = sum(g['attempts_on_target'] for g in games)
        out[code] = {
            'games': n,
            'xg_official': round(sum_xg/n, 2),
            'pass_accuracy': round(sum_passc/sum_pass*100, 1) if sum_pass else None,
            # total_distance from EFI is in metres per player; average per player per game, in km
            'avg_distance_km': round(sum_dist/sum_players/1000, 2) if sum_players else None,
            'sprints': round(sum_sprints/n, 1),
            'forced_turnovers': round(sum_fturn/n, 1),
            'linebreaks_completed': round(sum_lbc/n, 1),
            'linebreaks_attempted': round(sum_lba/n, 1),
            'top_speed': round(max(g['top_speed'] for g in games), 1) or None,
            'shot_accuracy': round(sum_att_ot/sum_att*100, 1) if sum_att else None,
        }
    return out

def poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k==0 else 0.0
    p = math.exp(-lam)
    for i in range(1, k+1): p *= lam/i
    return p

def dc_tau(a, b, lam, mu):
    if a==0 and b==0: return 1-lam*mu*DC_RHO
    if a==0 and b==1: return 1+lam*DC_RHO
    if a==1 and b==0: return 1+mu*DC_RHO
    if a==1 and b==1: return 1-DC_RHO
    return 1.0

def real_goals(m):
    """
    football-data.org folds the penalty-shootout tally into home_score/away_score
    for matches decided on penalties (e.g. 1-1 + pens 3-4 arrives as '4-5').
    Strip the shootout kicks so goals, ELO and W/D/L use actual match goals.
    A shootout match counts as a DRAW for ratings/table purposes; the bracket
    winner is preserved separately via 'match_winner'/'went_pens'.
    """
    hg, ag = m.get('home_score'), m.get('away_score')
    if hg is None or ag is None: return hg, ag
    if m.get('went_pens'):
        hg -= (m.get('home_score_pen') or 0)
        ag -= (m.get('away_score_pen') or 0)
    return hg, ag

def mov_mult(gd):
    """World-Football-Elo margin-of-victory multiplier."""
    gd = abs(gd)
    if gd <= 1: return 1.0
    if gd == 2: return 1.5
    return (11 + gd) / 8

def match_prob(hC, aC, elo=None):
    E = elo or ELO_BASE
    rH = E.get(hC,1650); rA = E.get(aC,1650)
    hb = HOME_BONUS.get(hC,0)-HOME_BONUS.get(aC,0)
    # Multiplicative goal expectation: totals grow with mismatch (unlike the old
    # additive form, where lam+mu was constant regardless of quality gap).
    d = (rH + hb) - rA
    lam = max(0.15, min(4.5, GOAL_BASE * 10 ** ( d / (2*GOAL_SCALE))))
    mu  = max(0.15, min(4.5, GOAL_BASE * 10 ** (-d / (2*GOAL_SCALE))))
    pH=pD=pA=0.0
    for a in range(10):
        pa = poisson_pmf(a, lam)
        for b in range(10):
            p = pa*poisson_pmf(b,mu)*dc_tau(a,b,lam,mu)
            if a>b: pH+=p
            elif a<b: pA+=p
            else: pD+=p
    t=pH+pD+pA
    return pH/t, pD/t, pA/t, lam, mu

def elo_update(elo, hC, aC, hg, ag):
    """Single-match ELO update: MOV-scaled K, home bonus in the expectation."""
    rH, rA = elo.get(hC,1650), elo.get(aC,1650)
    hb = HOME_BONUS.get(hC,0)-HOME_BONUS.get(aC,0)
    eH = 1/(1+10**((rA-(rH+hb))/400))
    ah = 1.0 if hg>ag else (0.5 if hg==ag else 0.0)
    d = ELO_K * mov_mult(hg-ag) * (ah-eH)
    elo[hC] = rH + d
    elo[aC] = rA - d

def compute_live_elo(played_matches):
    elo = dict(ELO_BASE)
    for m in sorted(played_matches, key=lambda x: x.get('date','')):
        hC,aC = m.get('home_code',''), m.get('away_code','')
        hg,ag = real_goals(m)
        if not hC or not aC or hg is None: continue
        elo_update(elo, hC, aC, hg, ag)
    return {k: round(v) for k,v in elo.items()}

# ── nlbair xG model (zone-based, calibrated) ─────────────────────────────────
XG_ZONES = {
    'qual_SmallBoxCentre': 0.42,
    'qual_BoxCentre':      0.12,
    'qual_BoxLeft':        0.08,
    'qual_BoxRight':       0.08,
    'qual_DeepBoxRight':   0.07,
    'qual_OutOfBoxCentre': 0.05,
    'qual_LowCentre':      0.10,
    'qual_LowRight':       0.06,
    'qual_LowLeft':        0.06,
    'qual_HighCentre':     0.04,
    'qual_HighRight':      0.03,
    'qual_HighLeft':       0.03,
}

def shot_xg(row):
    if row.get('qual_Penalty') == 'True': return 0.79
    base = 0.07  # default (unknown zone)
    for zone, val in XG_ZONES.items():
        if row.get(zone) == 'True':
            base = val; break
    if row.get('qual_Head') == 'True': base *= 0.70
    if row.get('qual_BigChance') == 'True': base = max(base, 0.40)
    return round(min(0.96, base), 3)

def fetch_nlbair_stats(hC, aC, date):
    """Fetch match stats from nlbair/wc2026-events. Returns dict or None."""
    hs = OUR_TO_NLBAIR.get(hC); as_ = OUR_TO_NLBAIR.get(aC)
    if not hs or not as_: return None
    fname = f"wc2026_{hs}_vs_{as_}_{date}_events.csv"
    url = f"https://raw.githubusercontent.com/nlbair/wc2026-events/main/data/raw/{fname}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
        r = urllib.request.urlopen(req, timeout=25, context=SSL_CTX)
        rows = list(csv.DictReader(io.StringIO(r.read().decode('utf-8','replace'))))
        if not rows: return None
        home_ws = rows[0].get('home_team','')
        away_ws = rows[0].get('away_team','')
        out = {}
        for side, tname in [('home', home_ws), ('away', away_ws)]:
            tr = [r for r in rows if r.get('team')==tname]
            sr = [r for r in tr if r.get('isShot')=='True']
            gr = [r for r in tr if r.get('isGoal')=='True']
            bc = [r for r in sr if r.get('qual_BigChance')=='True']
            sot = sum(1 for r in sr if r.get('event') in ('Goal','SavedShot','ShotOnPost'))
            touches = sum(1 for r in tr if r.get('isTouch')=='True')
            xg = round(sum(shot_xg(r) for r in sr), 2)
            goals_info = [{'player': r.get('player','?'), 'minute': r.get('minute','?'),
                           'type': 'penalty' if r.get('qual_Penalty')=='True' else 'regular'}
                          for r in gr]
            out[side] = {
                'shots': len(sr), 'sot': sot, 'goals': len(gr),
                'big_chances': len(bc), 'xg': xg, 'touches': touches,
                'goals_info': goals_info,
            }
        total_t = out.get('home',{}).get('touches',0) + out.get('away',{}).get('touches',0)
        if total_t > 0:
            out['home']['poss'] = round(out['home']['touches']/total_t*100, 1)
            out['away']['poss'] = round(out['away']['touches']/total_t*100, 1)
        out['source'] = 'nlbair'
        out['file'] = fname
        return out
    except Exception as e:
        return None

def build_narrative(hC, aC, g1, g2, pH, pD, pA, lam, mu,
                    hxg, axg, goals, reds, pens,
                    hposs, aposs, hshots, ashots, hbc, abc):
    n = TEAM_NAMES
    h, a = n.get(hC,hC), n.get(aC,aC)
    pred = 'H' if pH>=pD and pH>=pA else ('A' if pA>=pH and pA>=pD else 'D')
    real = 'H' if g1>g2 else ('A' if g2>g1 else 'D')
    lines = []
    if pred != real:
        conf = pH if pred=='H' else (pA if pred=='A' else pD)
        pred_lbl = {'H':f'{h} win','D':'draw','A':f'{a} win'}
        lines.append(f"🚨 **Upset**: model predicted {pred_lbl[pred]} ({conf*100:.0f}%) but ended {g1}–{g2}.")
    else:
        conf = pH if real=='H' else (pA if real=='A' else pD)
        lines.append(f"✅ **Result matched prediction** ({conf*100:.0f}%). Final: {g1}–{g2}.")
    if hxg>0 or axg>0:
        for code,gf,xg,name in [(hC,g1,hxg,h),(aC,g2,axg,a)]:
            if gf>xg+0.8: lines.append(f"⚡ {name} outscored xG ({gf} goals vs {xg:.1f} xG) — clinical finishing.")
            elif gf<xg-0.8: lines.append(f"🧱 {name} underperformed xG ({gf} goals vs {xg:.1f} xG).")
    if hbc or abc:
        if hbc: lines.append(f"💥 {h} created {hbc} big chance{'s' if hbc>1 else ''}.")
        if abc: lines.append(f"💥 {a} created {abc} big chance{'s' if abc>1 else ''}.")
    for min_,team,player in (reds or []):
        side = h if team==hC else a
        lines.append(f"🟥 {side} down to 10 men ({player}, {min_}').")
    if hposs and aposs:
        dom = h if hposs>aposs else a
        dom_p = max(hposs,aposs)
        if dom_p>60: lines.append(f"🎯 {dom} dominated possession ({dom_p:.0f}%).")
    if hshots and ashots and (hshots+ashots)>0:
        for gf,shots,name in [(g1,hshots,h),(g2,ashots,a)]:
            if shots>0 and gf/shots>0.28: lines.append(f"🎯 {name}: {gf} goals from {int(shots)} shots ({gf/shots*100:.0f}% conversion).")
    if abs(g1-g2)>3: lines.append(f"📉 Scoreline ({g1}–{g2}) far more one-sided than model expected (~{lam:.1f}–{mu:.1f}).")
    return lines

def main():
    print("WC2026 Performance Tracker v3 — mominullptr + nlbair/wc2026-events")

    with open('data/live_data.json') as f:
        live = json.load(f)
    wc = live.get('wc_results') or {}
    played = [m for m in wc.get('matches',[]) if m.get('home_score') is not None and m.get('home_code') and m.get('away_code')]
    print(f"  {len(played)} played matches")

    # Compute live ELO (final, for future-match predictions elsewhere)
    live_elo = compute_live_elo(played)
    # Sequential tracker for honest pre-match evaluation inside the loop below
    seq_elo = dict(ELO_BASE)
    played.sort(key=lambda x: x.get('date',''))

    # ── mominullptr data ────────────────────────────────────────────────────
    BASE = "https://raw.githubusercontent.com/mominullptr/FIFA-World-Cup-2026-Dataset/main"
    print("  Fetching mominullptr...")
    try:
        md_rows   = fetch_csv(f"{BASE}/matches_detailed.csv")
        evt_rows  = fetch_csv(f"{BASE}/match_events.csv")
        match_rows= fetch_csv(f"{BASE}/matches.csv")
        team_rows = fetch_csv(f"{BASE}/teams.csv")
        squad_rows= fetch_csv(f"{BASE}/squads_and_players.csv")
        stats_rows= fetch_csv(f"{BASE}/match_team_stats.csv")
        momi_ok = True
    except Exception as e:
        print(f"  WARNING mominullptr: {e}")
        md_rows=evt_rows=match_rows=team_rows=squad_rows=stats_rows=[]; momi_ok=False

    tid_to_our    = {t['team_id']: FIFA_TO_OUR.get(t['fifa_code'],t['fifa_code']) for t in team_rows}
    pid_to_name   = {s['player_id']: s['player_name'] for s in squad_rows}
    match_id_map  = {m['match_id']: m for m in match_rows}
    det_by_key    = {}
    for r in md_rows:
        hc = FIFA_TO_OUR.get(r['home_fifa_code'], r['home_fifa_code'])
        ac = FIFA_TO_OUR.get(r['away_fifa_code'], r['away_fifa_code'])
        det_by_key[(r['date'],hc,ac)] = r
    real_xg_map = {}
    for r in md_rows:
        if r.get('status')!='Completed': continue
        hc = FIFA_TO_OUR.get(r.get('home_fifa_code',''),'')
        ac = FIFA_TO_OUR.get(r.get('away_fifa_code',''),'')
        try: real_xg_map[(r['date'],hc,ac)] = (float(r['home_xg']),float(r['away_xg']))
        except (KeyError, ValueError, TypeError): pass
    evts_by_mid = {}
    for e in evt_rows:
        evts_by_mid.setdefault(e['match_id'],[]).append(e)
    stats_map = {}
    for s in stats_rows:
        stats_map[(s['match_id'],s['team_id'])] = s

    teams_out = {}
    matches_out = []
    real_xg_used = nlbair_used = narratives_built = 0

    for m in played:
        hC,aC = m['home_code'], m['away_code']
        g1,g2 = real_goals(m)                       # pens-stripped actual goals
        date  = m.get('date','')
        went_pens = bool(m.get('went_pens'))
        pens_score = (m.get('home_score_pen'), m.get('away_score_pen')) if went_pens else None
        # Pre-match ratings — evaluate the model with what was known BEFORE the
        # game, then update. (Previously used final ELO for all matches, which
        # leaked future results into expected_points/delta_pts.)
        pH,pD,pA,lam,mu = match_prob(hC, aC, seq_elo)
        elo_update(seq_elo, hC, aC, g1, g2)

        # ── Stats priority: nlbair > mominullptr ──────────────────────────
        nlb = fetch_nlbair_stats(hC, aC, date)
        if nlb:
            nlbair_used += 1
            hxg    = nlb['home']['xg']
            axg    = nlb['away']['xg']
            hshots = nlb['home']['shots']
            ashots = nlb['away']['shots']
            hsot   = nlb['home']['sot']
            asot   = nlb['away']['sot']
            hposs  = nlb['home'].get('poss')
            aposs  = nlb['away'].get('poss')
            hbc    = nlb['home']['big_chances']
            abc    = nlb['away']['big_chances']
            # If mominullptr has real xG, prefer it (more validated)
            rxg = real_xg_map.get((date,hC,aC))
            if rxg: hxg,axg = rxg; real_xg_used+=1
        else:
            rxg = real_xg_map.get((date,hC,aC))
            if rxg: hxg,axg=rxg; real_xg_used+=1
            else:   hxg,axg=lam,mu
            det = det_by_key.get((date,hC,aC))
            mid = det['match_id'] if det else None
            base = match_id_map.get(mid,{}) if mid else {}
            hs = stats_map.get((mid, base.get('home_team_id','')),{}) if mid else {}
            as_ = stats_map.get((mid, base.get('away_team_id','')),{}) if mid else {}
            def n_(d,k): return float(d[k]) if d.get(k) else None
            hposs=n_(hs,'possession_pct'); aposs=n_(as_,'possession_pct')
            hshots=n_(hs,'total_shots');   ashots=n_(as_,'total_shots')
            hsot=n_(hs,'shots_on_target'); asot=n_(as_,'shots_on_target')
            hbc=abc=None

        # ── Events (mominullptr) ──────────────────────────────────────────
        det = det_by_key.get((date,hC,aC))
        mid = det['match_id'] if det else None
        base2 = match_id_map.get(mid,{}) if mid else {}
        evts = evts_by_mid.get(mid,[]) if mid else []
        goals = [(e['minute'],tid_to_our.get(e['team_id'],'?'),pid_to_name.get(e['player_id'],'?'))
                 for e in evts if e.get('event_type')=='Goal']
        reds  = [(e['minute'],tid_to_our.get(e['team_id'],'?'),pid_to_name.get(e['player_id'],'?'))
                 for e in evts if e.get('event_type')=='Red Card']

        # Merge nlbair goal info (better names) if available
        if nlb:
            h_goals = [{'min':g['minute'],'player':g['player'],'type':g['type']}
                       for g in nlb['home']['goals_info']]
            a_goals = [{'min':g['minute'],'player':g['player'],'type':g['type']}
                       for g in nlb['away']['goals_info']]
        else:
            h_goals = [{'min':g[0],'player':g[2],'type':'regular'} for g in goals if g[1]==hC]
            a_goals = [{'min':g[0],'player':g[2],'type':'regular'} for g in goals if g[1]==aC]

        narr = build_narrative(hC,aC,g1,g2,pH,pD,pA,lam,mu,
                               hxg,axg,goals,reds,[],
                               hposs or 0, aposs or 0,
                               hshots or 0, ashots or 0, hbc or 0, abc or 0)
        if narr: narratives_built+=1

        matches_out.append({
            'date':date,'home':hC,'away':aC,'g1':g1,'g2':g2,
            'pH':round(pH,3),'pD':round(pD,3),'pA':round(pA,3),
            'lam':round(lam,2),'mu':round(mu,2),
            'home_xg':round(hxg,2),'away_xg':round(axg,2),
            'real_xg':bool(rxg),
            'home_shots':hshots,'away_shots':ashots,
            'home_sot':hsot,'away_sot':asot,
            'home_poss':hposs,'away_poss':aposs,
            'home_big_chances':hbc,'away_big_chances':abc,
            'home_goals':h_goals,'away_goals':a_goals,
            'reds':reds,'has_stats':bool(nlb or rxg),
            'went_pens':went_pens,
            'pens':{'home':pens_score[0],'away':pens_score[1]} if pens_score else None,
            'winner':m.get('match_winner'),
            'narrative':narr,'nlbair':bool(nlb),
            'stadium':det.get('stadium_name','') if det else '',
            'city':det.get('city','') if det else '',
        })

        for code,opp,gf,ga,p_win,p_draw,p_loss,xgf,xga,shots,bc in [
            (hC,aC,g1,g2,pH,pD,pA,hxg,axg,hshots,hbc),
            (aC,hC,g2,g1,pA,pD,pH,axg,hxg,ashots,abc),
        ]:
            if code not in teams_out:
                teams_out[code]={'code':code,'name':TEAM_NAMES.get(code,code),
                    'games':0,'goals_for':0,'goals_against':0,'xg_for':0.,'xg_against':0.,
                    'wins':0,'draws':0,'losses':0,'points':0,
                    'expected_points':0.,'big_chances_created':0,'big_chances_conceded':0,'matches':[]}
            t=teams_out[code]
            t['games']+=1; t['goals_for']+=gf; t['goals_against']+=ga
            t['xg_for']+=xgf; t['xg_against']+=xga
            t['expected_points']+=p_win*3+p_draw
            if bc: t['big_chances_created']+=bc
            if gf>ga: t['wins']+=1; t['points']+=3; result='W'
            elif gf<ga: t['losses']+=1; result='L'
            else: t['draws']+=1; t['points']+=1; result='D'
            t['matches'].append({'vs':opp,'date':date,'gf':gf,'ga':ga,
                'xgf':round(xgf,2),'xga':round(xga,2),'result':result,'p_win':round(p_win,3)})

    for t in teams_out.values():
        g = t['games'] or 1
        t['xpts']=round(t['expected_points'],2)
        t['delta_pts']=round(t['points']-t['expected_points'],2)
        t['xgf']=round(t['xg_for']/g,2); t['xga']=round(t['xg_against']/g,2)

    # ── FIFA EFI (official physical/technical data) ───────────────────────
    print("  Fetching FIFA EFI (Bustami)...")
    try:
        efi_by_team = fetch_efi_stats()
        efi_matched = 0
        for code, efi in efi_by_team.items():
            t = teams_out.get(code)
            if not t: continue
            t['efi'] = efi
            t['dgf_efi'] = round((t['goals_for']/(t['games'] or 1)) - efi['xg_official'], 2)
            efi_matched += 1
        print(f"  EFI: {len(efi_by_team)} teams fetched, {efi_matched} matched to played teams")
    except Exception as e:
        print(f"  WARNING EFI: {e}")

    # Save live ELO to live_data.json
    try:
        with open('data/live_data.json') as lf: ld=json.load(lf)
        ld['live_elo']=live_elo; ld['live_elo_games']=len(played)
        ld['live_elo_updated']=datetime.now(timezone.utc).isoformat()
        with open('data/live_data.json','w') as lf:
            json.dump(ld,lf,ensure_ascii=False,separators=(',',':'))
        print(f"  ELO updated: {len(live_elo)} teams from {len(played)} games")
    except Exception as e:
        print(f"  WARNING ELO: {e}")

    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'teams': sorted(teams_out.values(), key=lambda x: -x['delta_pts']),
        'matches': sorted(matches_out, key=lambda x: x['date']),
        'real_xg_games': real_xg_used,
        'nlbair_games': nlbair_used,
        'narratives_built': narratives_built,
        'source': 'football-data.org + mominullptr + nlbair/wc2026-events',
    }
    os.makedirs('data',exist_ok=True)
    with open('data/wc2026_perf.json','w',encoding='utf-8') as f:
        json.dump(output,f,ensure_ascii=False,indent=2)
    print(f"  Saved: {len(teams_out)} teams, {len(matches_out)} matches")
    print(f"  nlbair: {nlbair_used} matches | mominullptr xG: {real_xg_used} | narratives: {narratives_built}")

    # ── Tactical style profiles (depends on wc2026_perf.json just written above) ──
    try:
        import subprocess
        subprocess.run(['python3', 'scripts/generate_tactics.py'], check=False)
    except Exception as e:
        print(f"  WARNING tactics: {e}")

if __name__=='__main__':
    main()

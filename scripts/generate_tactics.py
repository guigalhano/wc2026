#!/usr/bin/env python3
"""
WC2026 Tactical Style Profiles — per-team attacking identity + defensive record.
Sources:
  - attacking style : Bustami/efi-fifa-data-wc-2026 (player-match EFI data, shot-creation
                       source, pressing, distribution, physical output)
  - defensive record : data/wc2026_perf.json (already-validated goals_against/xGA pipeline —
                        EFI's own 'goals_conceded' field is only ~38% populated, too sparse to use)
Output: data/wc2026_tactics.json, consumed by index.html's Confronto "Style comparison" card.
"""
import csv, json, io, os, urllib.request, ssl

SSL_CTX = ssl.create_default_context()
EFI_BASE = "https://raw.githubusercontent.com/Bustami/efi-fifa-data-wc-2026/master/data"

# duplicated from generate_perf.py's FIFA_TO_OUR / TEAM_NAMES so this script can run standalone
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

SHOT_SRC = {
    'pass':'attempt_at_goal_from_pass', 'cross':'attempt_at_goal_from_cross',
    'corner':'attempt_at_goal_from_corner', 'freekick':'attempt_at_goal_from_free_kicks',
    'progression':'attempt_at_goal_from_ball_progression', 'rebound':'attempt_at_goal_from_rebound',
    'penalty':'attempt_at_goal_from_penalty', 'other':'attempt_at_goal_from_other',
}
ROUTE_LABELS = {
    'pass':'Combination play (pass-created)', 'cross':'Wide crossing',
    'corner':'Corners', 'freekick':'Direct free kicks',
    'progression':'Individual carrying/dribbling', 'rebound':'Second balls/rebounds',
    'penalty':'Penalties', 'other':'Transition/other',
}

def fnum(r, k):
    v = r.get(k, '')
    try:
        return float(v) if v not in (None, '', 'NA') else 0.0
    except (TypeError, ValueError):
        return 0.0

def fetch_csv(url, timeout=25):
    req = urllib.request.Request(url, headers={"User-Agent":"Mozilla/5.0"})
    r = urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX)
    return list(csv.DictReader(io.StringIO(r.read().decode('utf-8','replace'))))

def pct_rank(vals, x):
    s = sorted(vals)
    below = sum(1 for v in s if v < x)
    return below/len(s)*100 if s else 50

def main():
    print("WC2026 Tactical Style Profiles")
    try:
        rows = fetch_csv(f"{EFI_BASE}/wc2026_efi.csv")
    except Exception as e:
        print(f"  WARNING: could not fetch EFI data: {e}")
        return

    try:
        with open('data/wc2026_perf.json') as f:
            perf = json.load(f)
        perf_by_code = {t['code']: t for t in perf['teams']}
    except Exception as e:
        print(f"  WARNING: could not load wc2026_perf.json for defensive record: {e}")
        perf_by_code = {}

    for r in rows:
        r['_code'] = FIFA_TO_OUR.get(r.get('team_name',''))

    teams = sorted(set(r['_code'] for r in rows if r['_code']))
    profiles = {}
    for code in teams:
        trows = [r for r in rows if r['_code']==code]
        matches = sorted(set(r['match_id'] for r in trows))
        n = len(matches)
        if n == 0: continue

        def team_sum(col):
            return sum(fnum(r,col) for r in trows)

        shot_src = {k: team_sum(v) for k,v in SHOT_SRC.items()}
        total_shots = sum(shot_src.values()) or 1
        shot_src_pct = {k: round(v/total_shots*100,1) for k,v in shot_src.items()}

        goals         = team_sum('goals')
        goals_in_box  = team_sum('goals_inside_the_penalty_area')
        goals_out_box = team_sum('goals_outside_the_penalty_area')
        goals_fk      = team_sum('goals_from_direct_free_kicks')
        pens_scored   = team_sum('penalties_scored')

        passes        = team_sum('passes')
        passes_c      = team_sum('passes_completed')
        dist_press    = team_sum('distributions_under_pressure')
        dist_press_c  = team_sum('distributions_completed_under_pressure')
        crosses       = team_sum('crosses')
        corners       = team_sum('corners')
        takeons_c     = team_sum('take_ons_completed')
        bp_att        = team_sum('attempted_ball_progressions')
        bp_c          = team_sum('completed_ball_progressions')
        switches_att  = team_sum('attempted_switches_of_play')

        def_press        = team_sum('defensive_pressures_applied')
        def_press_direct = team_sum('direct_defensive_pressures_applied')
        forced_to        = team_sum('forced_turnovers')
        fouls_for        = team_sum('fouls_for')

        total_dist     = team_sum('total_distance')
        sprints        = team_sum('sprints')
        top_speed      = max((fnum(r,'top_speed') for r in trows), default=0)
        players_played = sum(1 for r in trows if fnum(r,'time_played')>0) or 1

        pt = perf_by_code.get(code, {})

        profiles[code] = {
            'name': TEAM_NAMES.get(code, code),
            'games': n,
            'goals_per_game': round(goals/n,2),
            'shot_source_pct': shot_src_pct,
            'goal_zone': {
                'in_box_pct': round(goals_in_box/goals*100,1) if goals else None,
                'out_box_pct': round(goals_out_box/goals*100,1) if goals else None,
                'freekick_goals': int(goals_fk), 'penalty_goals': int(pens_scored),
            },
            'pass_accuracy': round(passes_c/passes*100,1) if passes else None,
            'composure_under_pressure': round(dist_press_c/dist_press*100,1) if dist_press else None,
            'crosses_per_game': round(crosses/n,1),
            'corners_per_game': round(corners/n,1),
            'takeons_completed_per_game': round(takeons_c/n,1),
            'progressions_per_game': round(bp_att/n,1),
            'progression_success_pct': round(bp_c/bp_att*100,1) if bp_att else None,
            'switches_per_game': round(switches_att/n,1),
            'defensive_pressures_per_game': round(def_press/n,1),
            'direct_pressures_per_game': round(def_press_direct/n,1),
            'forced_turnovers_per_game': round(forced_to/n,1),
            'fouls_for_per_game': round(fouls_for/n,1),
            'avg_distance_km': round(total_dist/players_played/1000,2),
            'sprints_per_game': round(sprints/n,1),
            'top_speed_kmh': round(top_speed,1),
            'goals_against_per_game': round(pt['goals_against']/pt['games'],2) if pt.get('games') else None,
            'xga_per_game': pt.get('xga'),
            'delta_pts': pt.get('delta_pts'),
        }

    if not profiles:
        print("  No profiles built, aborting.")
        return

    # ── percentile-based tags (league-relative, not editorial) ─────────────
    metrics = ['forced_turnovers_per_game','crosses_per_game','progressions_per_game',
               'sprints_per_game','defensive_pressures_per_game','corners_per_game',
               'switches_per_game','pass_accuracy','direct_pressures_per_game']
    dist = {m: [p[m] for p in profiles.values() if p.get(m) is not None] for m in metrics}
    xga_vals = [p['xga_per_game'] for p in profiles.values() if p.get('xga_per_game') is not None]

    for code, p in profiles.items():
        pr = {m: pct_rank(dist[m], p[m]) for m in metrics if p.get(m) is not None}

        src = {k:v for k,v in p['shot_source_pct'].items() if k != 'other'}
        route = max(src, key=src.get) if src else 'other'
        route_pct = src.get(route, 0)
        src2 = {k:v for k,v in src.items() if k != route}
        route2 = max(src2, key=src2.get) if src2 else None

        tags = []
        press_score = (pr.get('forced_turnovers_per_game',50) + pr.get('defensive_pressures_per_game',50)) / 2
        if press_score >= 70: tags.append('High press')
        elif press_score <= 30: tags.append('Low block')
        else: tags.append('Mid block')

        if pr.get('pass_accuracy',50) >= 75: tags.append('Possession-based')
        elif pr.get('pass_accuracy',50) <= 25: tags.append('Direct style')

        if pr.get('crosses_per_game',0) >= 75: tags.append('Wide/crossing-heavy')
        if pr.get('progressions_per_game',0) >= 75: tags.append('Carries the ball a lot')
        if pr.get('switches_per_game',0) >= 80: tags.append('Switches play frequently')
        if pr.get('corners_per_game',0) >= 75 or (p['shot_source_pct'].get('corner',0)+p['shot_source_pct'].get('freekick',0)) >= 20:
            tags.append('Set-piece threat')
        if pr.get('sprints_per_game',0) >= 80: tags.append('High-intensity running')
        if pr.get('direct_pressures_per_game',0) >= 80: tags.append('Aggressive counter-press')

        if p.get('xga_per_game') is not None and xga_vals:
            xga_pr = pct_rank(xga_vals, p['xga_per_game'])
            if xga_pr >= 75: tags.append('Leaky defense')
            elif xga_pr <= 25: tags.append('Miserly defense')

        p['primary_route'] = {'type': route, 'label': ROUTE_LABELS.get(route,route), 'pct': route_pct}
        p['secondary_route'] = {'type': route2, 'label': ROUTE_LABELS.get(route2,route2), 'pct': src2[route2]} if route2 else None
        p['tags'] = tags
        p['percentiles'] = {k: round(v,0) for k,v in pr.items()}

    os.makedirs('data', exist_ok=True)
    with open('data/wc2026_tactics.json','w',encoding='utf-8') as f:
        json.dump(profiles, f, ensure_ascii=False, separators=(',',':'))
    print(f"  Saved {len(profiles)} team tactical profiles")

if __name__=='__main__':
    main()

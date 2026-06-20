#!/usr/bin/env python3
"""
WC2026 Performance Tracker
Generates data/wc2026_perf.json in the exact structure expected by renderTracking()
in the dashboard. Uses real results from data/live_data.json (football-data.org)
combined with the Dixon-Coles model to compute over/underperformance per team.
"""
import json
import math
import os
from datetime import datetime, timezone

# ── ELO ratings (calibrated, same as fetch_wc2026.py) ──────────────────────
ELO = {
    'ESP':2074,'ARG':2064,'FRA':2060,'BRA':1994,'ING':2010,'POR':1970,
    'ALE':1927,'HOL':1930,'BEL':1895,'CRO':1880,'COL':1875,'URU':1870,
    'MEX':1850,'SEN':1830,'MAR':1825,'SUI':1820,'AUT':1815,'JAP':1810,
    'NOR':1800,'TUR':1795,'EQU':1785,'AUS':1780,'ESC':1775,'COR':1770,
    'EUA':1760,'CAN':1755,'SUE':1740,'AGL':1740,'EGI':1730,'CAT':1720,
    'ARS':1715,'TCH':1710,'IRA':1725,'RDC':1700,'CDM':1700,'IRQ':1690,
    'JOR':1685,'PAN':1650,'BOS':1760,'GAN':1680,'HAI':1650,'CAB':1620,
    'CUR':1640,'PAR':1660,'AFS':1720,'NZE':1600,'TUN':1695,'UZB':1670,
}
HOME_BONUS = {'MEX': 100, 'EUA': 100, 'CAN': 80}
DC_RHO = -0.13

# ── Team names (PT) ──────────────────────────────────────────────────────
TEAM_NAMES = {
    'ESP':'Espanha','ARG':'Argentina','FRA':'França','ING':'Inglaterra','BRA':'Brasil',
    'POR':'Portugal','COL':'Colômbia','HOL':'Holanda','EQU':'Equador','ALE':'Alemanha',
    'NOR':'Noruega','CRO':'Croácia','JAP':'Japão','TUR':'Turquia','SUI':'Suíça',
    'URU':'Uruguai','BEL':'Bélgica','SEN':'Senegal','PAR':'Paraguai','AUT':'Áustria',
    'MAR':'Marrocos','AUS':'Austrália','ESC':'Escócia','IRA':'Irã','AGL':'Argélia',
    'COR':'Coreia do Sul','TCH':'República Tcheca','PAN':'Panamá','UZB':'Uzbequistão',
    'SUE':'Suécia','EGI':'Egito','JOR':'Jordânia','CDM':'Costa do Marfim','RDC':'RD Congo',
    'TUN':'Tunísia','IRQ':'Iraque','BOS':'Bósnia e Herzegovina','CAB':'Cabo Verde',
    'ARS':'Arábia Saudita','NZE':'Nova Zelândia','HAI':'Haiti','AFS':'África do Sul',
    'GAN':'Gana','CUR':'Curaçao','CAT':'Catar','CAN':'Canadá','MEX':'México','EUA':'Estados Unidos',
}


def poisson_pmf(k, lam):
    if lam <= 0:
        return 1.0 if k == 0 else 0.0
    p = math.exp(-lam)
    for i in range(1, k + 1):
        p *= lam / i
    return p


def dc_tau(a, b, lam, mu):
    if a == 0 and b == 0: return 1 - lam * mu * DC_RHO
    if a == 0 and b == 1: return 1 + lam * DC_RHO
    if a == 1 and b == 0: return 1 + mu * DC_RHO
    if a == 1 and b == 1: return 1 - DC_RHO
    return 1.0


def match_prob(code_a, code_b, neutral=True):
    rA = ELO.get(code_a, 1650)
    rB = ELO.get(code_b, 1650)
    hb = 0 if neutral else (HOME_BONUS.get(code_a, 0) - HOME_BONUS.get(code_b, 0))
    lam = max(0.3, min(3.5, 1.35 + ((rA + hb) - rB) / 400))
    mu = max(0.3, min(3.5, 1.35 + (rB - (rA + hb / 2)) / 400))
    wA = dr = wB = 0.0
    for a in range(9):
        pA = poisson_pmf(a, lam)
        for b in range(9):
            tau = dc_tau(a, b, lam, mu)
            p = pA * poisson_pmf(b, mu) * tau
            if a > b: wA += p
            elif a < b: wB += p
            else: dr += p
    tot = wA + dr + wB
    return {'winA': wA / tot, 'draw': dr / tot, 'winB': wB / tot, 'lam': lam, 'mu': mu}


def main():
    print("WC2026 Performance Tracker — generating data/wc2026_perf.json")

    # Load real results from live_data.json (football-data.org)
    with open('data/live_data.json') as f:
        live = json.load(f)

    wc = live.get('wc_results') or {}
    raw_matches = wc.get('matches', [])
    played = [m for m in raw_matches if m.get('home_score') is not None and m.get('away_score') is not None]
    print(f"  Found {len(played)} played matches in live_data.json")

    if not played:
        print("  No played matches found — aborting (keeping existing file)")
        return

    teams = {}
    matches_out = []

    for m in played:
        hc = m.get('home_code', '')
        ac = m.get('away_code', '')
        if not hc or not ac:
            continue
        g1, g2 = m['home_score'], m['away_score']
        date = m.get('date', '')

        pred = match_prob(hc, ac, neutral=True)

        matches_out.append({
            'date': date, 'home': hc, 'away': ac, 'g1': g1, 'g2': g2,
            'wA': pred['winA'], 'dr': pred['draw'], 'wB': pred['winB'],
            'lam': pred['lam'], 'mu': pred['mu'],
        })

        for code, opp, gf, ga, p_win, p_draw, p_loss, xgf, xga in [
            (hc, ac, g1, g2, pred['winA'], pred['draw'], pred['winB'], pred['lam'], pred['mu']),
            (ac, hc, g2, g1, pred['winB'], pred['draw'], pred['winA'], pred['mu'], pred['lam']),
        ]:
            if code not in teams:
                teams[code] = {
                    'code': code, 'name': TEAM_NAMES.get(code, code),
                    'games': 0, 'goals_for': 0, 'goals_against': 0,
                    'xg_for': 0.0, 'xg_against': 0.0,
                    'wins': 0, 'draws': 0, 'losses': 0, 'points': 0,
                    'expected_wins': 0.0, 'expected_draws': 0.0, 'expected_losses': 0.0,
                    'expected_points': 0.0, 'matches': [],
                }
            t = teams[code]
            t['games'] += 1
            t['goals_for'] += gf
            t['goals_against'] += ga
            t['xg_for'] += xgf
            t['xg_against'] += xga
            t['expected_wins'] += p_win
            t['expected_draws'] += p_draw
            t['expected_losses'] += p_loss
            t['expected_points'] += (p_win * 3 + p_draw * 1)

            if gf > ga:
                result = 'W'; t['wins'] += 1; t['points'] += 3
            elif gf < ga:
                result = 'L'; t['losses'] += 1
            else:
                result = 'D'; t['draws'] += 1; t['points'] += 1

            t['matches'].append({
                'vs': opp, 'date': date, 'gf': gf, 'ga': ga,
                'xgf': round(xgf, 2), 'xga': round(xga, 2),
                'result': result, 'p_win': round(p_win, 3),
            })

    # Compute derived fields
    for code, t in teams.items():
        t['xpts'] = round(t['expected_points'], 2)
        t['delta_pts'] = round(t['points'] - t['expected_points'], 2)
        t['xgf'] = round(t['xg_for'] / t['games'], 2) if t['games'] else 0
        t['xga'] = round(t['xg_against'] / t['games'], 2) if t['games'] else 0
        t['dgf'] = round((t['goals_for'] / t['games']) - t['xgf'], 2) if t['games'] else 0
        t['dga'] = round((t['goals_against'] / t['games']) - t['xga'], 2) if t['games'] else 0

    output = {
        'updated_at': datetime.now(timezone.utc).isoformat(),
        'teams': sorted(teams.values(), key=lambda x: -x['delta_pts']),
        'matches': sorted(matches_out, key=lambda x: x['date']),
        'real_xg_source': 'football-data.org',
        'real_xg_updated_at': live.get('updated_at', ''),
    }

    os.makedirs('data', exist_ok=True)
    with open('data/wc2026_perf.json', 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"  Saved data/wc2026_perf.json")
    print(f"  Teams: {len(teams)} | Matches: {len(matches_out)}")
    over = [t for t in teams.values() if t['delta_pts'] > 0.8]
    under = [t for t in teams.values() if t['delta_pts'] < -0.8]
    print(f"  Overperforming: {len(over)} | Underperforming: {len(under)}")
    for t in sorted(teams.values(), key=lambda x: -x['delta_pts'])[:5]:
        print(f"    {t['code']}: pts={t['points']} xpts={t['xpts']} delta={t['delta_pts']:+.2f}")


if __name__ == '__main__':
    main()

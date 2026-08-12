#!/usr/bin/env python3
"""
Report surf Cote sauvage - Penthievre & Sainte-Barbe
Source de donnees : Open-Meteo (Marine API + Forecast API), gratuit, sans cle.

Usage :
    python surf_report.py            -> calcule, envoie l'email
    python surf_report.py --dry-run  -> calcule, ecrit report.html sans envoyer
    python surf_report.py --demo     -> donnees factices, pour tester la mise en page
"""

import os
import sys
import json
import smtplib
import argparse
from datetime import datetime, timedelta
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from urllib.request import urlopen
from urllib.parse import urlencode
from web_page import render_web

# ---------------------------------------------------------------------------
# CONFIGURATION
# ---------------------------------------------------------------------------

# shore_normal_deg = direction vers laquelle la plage regarde (d'ou vient la houle).
# 250 deg = ouest-sud-ouest. A ajuster si tu constates que l'offshore est mal detecte.
SPOTS = [
    {"name": "Penthievre",    "lat": 47.5394, "lon": -3.1391, "shore_normal_deg": 250},
    {"name": "Sainte-Barbe",  "lat": 47.5980, "lon": -3.1512, "shore_normal_deg": 250},
]

DAYS_AHEAD = 5
DAYLIGHT = (7, 20)        # on ignore les creneaux hors de cette plage horaire
TIMEZONE = "Europe/Paris"

# Profil debutant. Modifie ces bornes quand tu progresses.
WAVE_IDEAL = (0.6, 1.1)   # metres : la zone confortable
WAVE_HARD = 1.6           # au-dela, on considere que c'est trop pour un debutant
PERIOD_GOOD = 8.0         # secondes : au-dela, vraie houle
WIND_CALM = 12.0          # km/h : en dessous, le vent ne gene pas
WIND_STRONG = 22.0        # km/h : au-dela, ca hache la surface

MIN_SCORE_TO_MENTION = 4.0  # en dessous, on ne recommande pas le creneau


# ---------------------------------------------------------------------------
# RECUPERATION DES DONNEES
# ---------------------------------------------------------------------------

def _get_json(url, params):
    full = url + "?" + urlencode(params)
    with urlopen(full, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_spot(spot):
    """Recupere houle + vent pour un spot, fusionnes par horodatage."""
    marine = _get_json(
        "https://marine-api.open-meteo.com/v1/marine",
        {
            "latitude": spot["lat"],
            "longitude": spot["lon"],
            "hourly": "wave_height,wave_period,wave_direction,"
                      "swell_wave_height,swell_wave_period",
            "timezone": TIMEZONE,
            "forecast_days": DAYS_AHEAD,
        },
    )
    weather = _get_json(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": spot["lat"],
            "longitude": spot["lon"],
            "hourly": "wind_speed_10m,wind_direction_10m,temperature_2m",
            "timezone": TIMEZONE,
            "forecast_days": DAYS_AHEAD,
        },
    )

    wind_by_time = {}
    w = weather["hourly"]
    for i, t in enumerate(w["time"]):
        wind_by_time[t] = {
            "wind_speed": w["wind_speed_10m"][i],
            "wind_dir": w["wind_direction_10m"][i],
            "air_temp": w["temperature_2m"][i],
        }

    slots = []
    m = marine["hourly"]
    for i, t in enumerate(m["time"]):
        if t not in wind_by_time:
            continue
        hour = int(t[11:13])
        if not (DAYLIGHT[0] <= hour <= DAYLIGHT[1]):
            continue
        if hour % 3 != 0:          # on garde un point toutes les 3h
            continue
        slot = {
            "time": t,
            "wave_height": m["wave_height"][i],
            "wave_period": m["wave_period"][i],
            "wave_dir": m["wave_direction"][i],
            "swell_height": m["swell_wave_height"][i],
            "swell_period": m["swell_wave_period"][i],
        }
        slot.update(wind_by_time[t])
        if slot["wave_height"] is None or slot["wind_speed"] is None:
            continue
        slots.append(slot)
    return slots


# ---------------------------------------------------------------------------
# VENT : OFFSHORE / ONSHORE
# ---------------------------------------------------------------------------

def wind_relation(wind_dir, shore_normal):
    """
    wind_dir = direction D'OU vient le vent (convention meteo).
    Le vent offshore vient de la terre, soit shore_normal + 180.
    Retourne (libelle, facteur 0-1 ou 1 = offshore parfait).
    """
    offshore_source = (shore_normal + 180) % 360
    diff = abs((wind_dir - offshore_source + 180) % 360 - 180)
    if diff <= 45:
        return "offshore", 1.0 - diff / 90
    if diff >= 135:
        return "onshore", 0.0
    return "cross-shore", 0.5 - abs(diff - 90) / 180


def compass(deg):
    pts = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
           "S", "SSO", "SO", "OSO", "O", "ONO", "NO", "NNO"]
    return pts[int((deg + 11.25) % 360 // 22.5)]


# ---------------------------------------------------------------------------
# NOTATION
# ---------------------------------------------------------------------------

def fr(x, dec=1):
    """Nombre au format francais (virgule decimale)."""
    return f"{x:.{dec}f}".replace(".", ",")


def score_slot(slot, shore_normal):
    """
    Retourne (note sur 10, dict des contributions, liste de facteurs lisibles).
    Chaque facteur porte un signe : + bon, ~ neutre, - penalisant, -- redhibitoire.

    Principe : chaque critere donne une qualite entre 0 et 1, on pondere,
    puis on applique des plafonds. Le plafond est la partie importante :
    une bonne taille ne doit jamais rattraper une periode de 5 s.
    """
    factors = []
    caps = [10.0]

    # --- Taille ------------------------------------------------------------
    h = slot["wave_height"]
    lo, hi = WAVE_IDEAL
    if lo <= h <= hi:
        q_size = 1.0
        factors.append(("+", "taille", f"{fr(h)} m, pile la zone confortable", "bonne taille"))
    elif h < lo:
        q_size = max(0.0, 1 - (lo - h) * 3.5)
        if h < 0.4:
            caps.append(4.0)
            factors.append(("--", "taille", f"{fr(h)} m, trop petit pour se faire pousser", "trop petit"))
        else:
            caps.append(7.0)
            factors.append(("-", "taille", f"{fr(h)} m, un peu petit", "un peu petit"))
    else:
        q_size = max(0.0, 1 - (h - hi) * 1.3)
        if h >= WAVE_HARD:
            caps.append(3.5)
            factors.append(("--", "taille", f"{fr(h)} m, trop gros pour debuter", "trop gros"))
        else:
            factors.append(("-", "taille", f"{fr(h)} m, ca commence a etre costaud", "un peu gros"))

    # --- Periode -----------------------------------------------------------
    p = slot["wave_period"] or 0
    if p >= 10:
        q_period = 1.0
        factors.append(("+", "periode", f"{p:.0f} s, belle houle bien formee", "belle houle"))
    elif p >= PERIOD_GOOD:
        q_period = 0.8 + (p - PERIOD_GOOD) * 0.1
        factors.append(("+", "periode", f"{p:.0f} s, vraie houle", "houle correcte"))
    elif p >= 6.5:
        q_period = 0.45 + (p - 6.5) * 0.23
        caps.append(6.0)
        factors.append(("~", "periode", f"{p:.0f} s, houle courte, vagues qui cassent sec", "houle courte"))
    else:
        q_period = max(0.0, p / 6.5 * 0.4)
        caps.append(4.5)
        factors.append(("-", "periode", f"{p:.0f} s, clapot de vent, vagues molles", "clapot de vent"))

    # --- Vent --------------------------------------------------------------
    rel, alignment = wind_relation(slot["wind_dir"], shore_normal)
    v = slot["wind_speed"]
    card = compass(slot["wind_dir"])

    if rel == "offshore":
        q_wind = 0.75 + 0.25 * alignment
        if v > 18:
            q_wind *= max(0.35, 1 - (v - 18) * 0.035)
    elif rel == "cross-shore":
        q_wind = 0.5
        if v > 15:
            q_wind *= max(0.3, 1 - (v - 15) * 0.045)
    else:
        q_wind = 0.45
        if v > WIND_CALM:
            q_wind *= max(0.15, 1 - (v - WIND_CALM) * 0.055)

    if v <= 8:
        q_wind = max(q_wind, 0.85)

    # Libelle du vent
    if v <= 8:
        factors.append(("+", "vent", f"{v:.0f} km/h de {card}, mer d'huile", "mer d'huile"))
    elif rel == "offshore" and v >= 26:
        caps.append(6.5)
        factors.append(("-", "vent", f"{v:.0f} km/h offshore de {card}, "
                                     "ca tient les vagues mais ca pousse au large", "offshore fort"))
    elif rel == "offshore":
        factors.append(("+", "vent", f"{v:.0f} km/h offshore de {card}, surface lissee", "offshore"))
    elif rel == "cross-shore" and v >= WIND_STRONG:
        factors.append(("-", "vent", f"{v:.0f} km/h de travers ({card}), ca deforme", "vent de travers"))
    elif rel == "cross-shore":
        factors.append(("~", "vent", f"{v:.0f} km/h de travers ({card})", "vent de travers"))
    elif v >= WIND_STRONG:
        caps.append(4.0)
        factors.append(("--", "vent", f"{v:.0f} km/h onshore de {card}, mer hachee", "onshore fort"))
    else:
        factors.append(("-", "vent", f"{v:.0f} km/h onshore de {card}", "onshore"))

    total = 10 * (0.40 * q_size + 0.25 * q_period + 0.35 * q_wind)
    total = min(total, min(caps))

    parts = {"taille": round(q_size, 2), "periode": round(q_period, 2),
             "vent": round(q_wind, 2)}
    slot["wind_rel"] = rel
    return round(max(0.0, total), 1), parts, factors

def cap_first(s):
    """Majuscule initiale sans ecraser le reste (contrairement a .capitalize())."""
    return s[0].upper() + s[1:] if s else s



def short_why(score, factors):
    """Version courte pour la grille : une clause, jamais deux phrases."""
    pos = [f for f in factors if f[0] == "+"]
    neutral = [f for f in factors if f[0] == "~"]
    neg = [f for f in factors if f[0] == "-"]
    blocking = [f for f in factors if f[0] == "--"]

    if blocking:
        return cap_first(blocking[0][3])
    if score >= 7.5 and pos:
        return cap_first(", ".join(f[3] for f in pos[:2]))
    if score >= 5.5:
        base = pos[0][3] if pos else (neutral[0][3] if neutral else None)
        if base and neg:
            return cap_first(f"{base}, mais {neg[0][3]}")
        if base:
            return cap_first(base)
    if neg:
        return cap_first(" et ".join(f[3] for f in neg[:2]))
    if neutral:
        return cap_first(neutral[0][3])
    return "Conditions moyennes"


def why_sentence(score, factors):
    """Construit la phrase d'explication a partir des facteurs dominants."""
    pos = [f for f in factors if f[0] == "+"]
    neutral = [f for f in factors if f[0] == "~"]
    neg = [f for f in factors if f[0] == "-"]
    blocking = [f for f in factors if f[0] == "--"]

    # Un facteur neutre vaut mieux qu'une phrase vide.
    if not pos and neutral:
        pos = neutral[:1]

    if blocking:
        raison = " et ".join(f[2] for f in blocking[:2])
        return cap_first(raison) + " : a passer son tour."

    if score >= 7.5:
        good = ", ".join(f[2] for f in pos[:2])
        if neg:
            return f"{cap_first(good)}. Seul bemol : {neg[0][2]}."
        return cap_first(good) + "."

    if score >= 5.5:
        if pos and neg:
            return f"{cap_first(pos[0][2])}, mais {neg[0][2]}."
        if pos:
            return cap_first(pos[0][2]) + "."
        return "Conditions moyennes, rien de redhibitoire."

    if neg:
        raisons = " et ".join(f[2] for f in neg[:2])
        return f"Mediocre : {raisons}."
    return "Rien d'exploitable sur ce creneau."


# ---------------------------------------------------------------------------
# CONSTRUCTION DU REPORT
# ---------------------------------------------------------------------------

JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janv.", "fevr.", "mars", "avril", "mai", "juin",
        "juil.", "aout", "sept.", "oct.", "nov.", "dec."]


def label_slot(t):
    d = datetime.fromisoformat(t)
    return f"{JOURS[d.weekday()]} {d.hour:02d}h"


def build_report():
    report = []
    for spot in SPOTS:
        slots = fetch_spot(spot)
        scored = []
        for s in slots:
            score, parts, factors = score_slot(s, spot["shore_normal_deg"])
            scored.append({**s, "score": score, "parts": parts,
                           "factors": factors, "why": why_sentence(score, factors),
                           "short": short_why(score, factors)})
        scored.sort(key=lambda x: x["time"])
        report.append({"spot": spot["name"], "slots": scored})
    return report


def best_overall(report):
    allslots = [(r["spot"], s) for r in report for s in r["slots"]]
    if not allslots:
        return None
    return max(allslots, key=lambda x: x[1]["score"])


def top_per_day(slots, n=1):
    """Meilleur creneau de chaque jour."""
    by_day = {}
    for s in slots:
        day = s["time"][:10]
        by_day.setdefault(day, []).append(s)
    out = []
    for day in sorted(by_day):
        best = max(by_day[day], key=lambda x: x["score"])
        out.append(best)
    return out[:5]


# ---------------------------------------------------------------------------
# EMAIL HTML
# ---------------------------------------------------------------------------

SITE_URL = os.environ.get("SITE_URL", "")
SITE_NAME = os.environ.get("SITE_NAME", "Surf de la semaine")

# Tables imbriquees et styles inline : c'est la seule mise en page qui tienne
# a la fois dans Gmail, Apple Mail et Outlook (moteur Word, pas de flexbox,
# pas de border-radius, pas de float fiable).
TD = 'style="font-family:Helvetica,Arial,sans-serif;color:#16232B;"'


def subject_line(report):
    """L'objet porte deja le verdict : decidable sans ouvrir le mail."""
    best = best_overall(report)
    if not best or best[1]["score"] < MIN_SCORE_TO_MENTION:
        return "Surf - rien de bon cette semaine"
    spot, s = best
    d = datetime.fromisoformat(s["time"])
    return f"Surf - {JOURS[d.weekday()]} {d.hour}h a {spot}, {fr(s['score'])}/10"


def preheader(report):
    """Ligne d'apercu affichee sous l'objet dans la boite de reception."""
    best = best_overall(report)
    if not best or best[1]["score"] < MIN_SCORE_TO_MENTION:
        return "Aucun creneau ne passe la barre sur les deux spots."
    s = best[1]
    return (f"{fr(s['wave_height'])} m, {s['wave_period']:.0f} s, "
            f"{s['wind_speed']:.0f} km/h {s.get('wind_rel', '')}.")


def render_email(report):
    """
    Version email : le verdict, cinq lignes, un lien. Rien d'autre.
    Tables imbriquees et styles inline : c'est la seule mise en page qui tienne
    a la fois dans Gmail, Apple Mail et Outlook (moteur Word).
    """
    from web_page import best_per_day, tone

    best = best_overall(report)
    # Memes noms que la maquette. Seul "bon" est colore, comme sur la page ;
    # le lavande est assombri pour rester lisible sur fond blanc.
    TONES = {"bon": ("#5348C7", "#EEECFB"),
             "moyen": ("#4A5058", "#EFEFEC"),
             "mauvais": ("#9AA1A6", "#F2F2EF")}
    F = "font-family:Helvetica,Arial,sans-serif;"

    p = ['<body style="margin:0;padding:0;background:#F4F5F2;">',
         f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">'
         f'{preheader(report)}</div>',
         '<table width="100%" cellpadding="0" cellspacing="0" border="0" '
         'style="background:#F4F5F2;padding:26px 12px;"><tr><td align="center">'
         '<table width="480" cellpadding="0" cellspacing="0" border="0" '
         'style="max-width:480px;width:100%;">']

    # Bandeau lien
    if SITE_URL:
        p.append('<tr><td align="center" style="padding-bottom:16px;">'
                 f'<a href="{SITE_URL}" style="{F}font-size:13px;font-weight:bold;'
                 'letter-spacing:1.5px;color:#697782;text-decoration:none;">'
                 f'{SITE_NAME.upper()}</a></td></tr>')

    # Verdict
    if best and best[1]["score"] >= MIN_SCORE_TO_MENTION:
        spot, s = best
        d = datetime.fromisoformat(s["time"])
        fg, bg = TONES[tone(s["score"])]
        p.append(
            f'<tr><td style="background:#ffffff;padding:30px 26px 26px;{F}">'
            f'<div style="font-size:13px;color:#697782;padding-bottom:10px;">'
            'Le meilleur moment de la semaine</div>'
            f'<div style="font-size:34px;font-weight:bold;color:#141C24;'
            f'line-height:1.1;">{JOURS[d.weekday()].capitalize()} {d.hour}h</div>'
            f'<div style="font-size:19px;color:#697782;padding-top:4px;">{spot}</div>'
            '<table cellpadding="0" cellspacing="0" border="0" '
            'style="margin-top:16px;"><tr>'
            f'<td style="background:{bg};padding:6px 14px;{F}font-size:14px;'
            f'font-weight:bold;color:{fg};">{fr(s["score"])} / 10</td>'
            '</tr></table>'
            f'<div style="font-size:15px;color:#141C24;padding-top:16px;'
            f'line-height:1.55;">{s["why"]}</div>'
            f'<div style="font-size:14px;color:#697782;padding-top:12px;">'
            f'{fr(s["wave_height"])} m &middot; {s["wave_period"]:.0f} s &middot; '
            f'{s["wind_speed"]:.0f} km/h {s.get("wind_rel", "")}</div>'
            '</td></tr>'
        )
    else:
        p.append(f'<tr><td style="background:#ffffff;padding:30px 26px;{F}">'
                 '<div style="font-size:26px;font-weight:bold;color:#141C24;">'
                 'Rien cette semaine</div>'
                 '<div style="font-size:15px;color:#697782;padding-top:10px;">'
                 'Aucun creneau ne passe la barre sur les deux spots.</div>'
                 '</td></tr>')

    # Une ligne par jour
    p.append('<tr><td style="height:10px;"></td></tr>')
    for spot, s in best_per_day(report):
        d = datetime.fromisoformat(s["time"])
        fg, _ = TONES[tone(s["score"])]
        p.append(
            '<tr><td style="background:#ffffff;padding:14px 26px;">'
            '<table width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td width="46" style="{F}font-size:15px;font-weight:bold;'
            f'color:#141C24;">{JOURS_COURTS[d.weekday()]}</td>'
            f'<td style="{F}font-size:15px;color:#141C24;">{spot} '
            f'<span style="color:#697782;">&middot; {d.hour}h</span></td>'
            f'<td align="right" style="{F}font-size:17px;font-weight:bold;'
            f'color:{fg};">{fr(s["score"])}</td>'
            '</tr></table></td></tr>'
            '<tr><td style="height:6px;"></td></tr>'
        )

    # Bouton
    if SITE_URL:
        p.append('<tr><td align="center" style="padding:14px 0 6px;">'
                 '<table cellpadding="0" cellspacing="0" border="0"><tr>'
                 '<td style="background:#141C24;padding:13px 28px;">'
                 f'<a href="{SITE_URL}" style="{F}font-size:14px;color:#ffffff;'
                 'text-decoration:none;font-weight:bold;">Voir le detail</a>'
                 '</td></tr></table></td></tr>')

    p.append(f'<tr><td align="center" style="{F}font-size:11.5px;color:#98A0A6;'
             'padding-top:16px;line-height:1.6;">'
             'Marees non prises en compte &mdash; verifie le coefficient.'
             '</td></tr>')
    p.append('</table></td></tr></table></body>')
    return "".join(p)


def send_email(html, subject):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", 587))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASSWORD"]
    # MAIL_TO accepte plusieurs adresses separees par des virgules.
    # L'en-tete To listera tout le monde ; chacun voit les autres destinataires.
    recipients = [a.strip() for a in os.environ["MAIL_TO"].split(",") if a.strip()]
    if not recipients:
        raise ValueError("MAIL_TO est vide")
    # Chez Gmail, identifiant de connexion et adresse d'expedition sont
    # confondus. Chez un relais comme Brevo, l'identifiant est technique
    # (7xxxxx@smtp-brevo.com) et l'expediteur doit etre une adresse verifiee.
    sender = os.environ.get("MAIL_FROM", user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html, "html", "utf-8"))

    with smtplib.SMTP(host, port) as server:
        server.starttls()
        server.login(user, password)
        server.send_message(msg, to_addrs=recipients)
    print(f"Email envoye a {len(recipients)} destinataire(s) : {', '.join(recipients)}")


# ---------------------------------------------------------------------------

def demo_report():
    """Donnees factices pour tester la mise en page sans reseau."""
    import random
    random.seed(7)
    base = datetime.now().replace(hour=6, minute=0, second=0, microsecond=0)
    report = []
    for spot in SPOTS:
        slots = []
        for d in range(DAYS_AHEAD):
            for hour in (9, 12, 15, 18):
                t = (base + timedelta(days=d)).replace(hour=hour)
                s = {
                    "time": t.isoformat(timespec="minutes"),
                    "wave_height": round(random.uniform(0.4, 1.5), 2),
                    "wave_period": round(random.uniform(5, 11), 1),
                    "wave_dir": 260,
                    "swell_height": 0.5, "swell_period": 8,
                    "wind_speed": round(random.uniform(5, 30)),
                    "wind_dir": random.choice([70, 90, 250, 200, 300]),
                    "air_temp": 20,
                }
                score, parts, factors = score_slot(s, spot["shore_normal_deg"])
                slots.append({**s, "score": score, "parts": parts,
                              "factors": factors, "why": why_sentence(score, factors),
                           "short": short_why(score, factors)})
        report.append({"spot": spot["name"], "slots": slots})
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="ecrit les fichiers sans envoyer d'email")
    ap.add_argument("--demo", action="store_true", help="donnees factices")
    ap.add_argument("--out", default="site",
                    help="dossier de sortie pour la page web (defaut: site)")
    args = ap.parse_args()

    report = demo_report() if args.demo else build_report()
    best = best_overall(report)

    # 1. La page web : c'est elle qui porte le design.
    os.makedirs(args.out, exist_ok=True)
    page = render_web(report, best, site_title=SITE_NAME)
    with open(os.path.join(args.out, "index.html"), "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Page web ecrite dans {args.out}/index.html")

    # 2. L'email : sobre, avec le lien en tete.
    mail = render_email(report)
    with open("email-preview.html", "w", encoding="utf-8") as f:
        f.write(mail)

    if args.dry_run or args.demo:
        print("Apercu email dans email-preview.html (rien envoye)")
        print(f"Objet : {subject_line(report)}")
    else:
        send_email(mail, subject_line(report))


if __name__ == "__main__":
    main()

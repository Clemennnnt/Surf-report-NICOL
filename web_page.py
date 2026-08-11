"""
Rendu de la page web du report surf.

Le CSS provient d'une maquette faite dans Claude Design : theme sombre,
accent lavande sur les bonnes notes, tout en poids typographiques legers.
Il est repris tel quel ci-dessous — ne pas le reecrire, seulement l'ajuster.

Produit un fichier HTML autonome : aucune dependance, aucun build.
"""

from datetime import datetime

JOURS_COURTS = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
JOURS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS = ["janvier", "fevrier", "mars", "avril", "mai", "juin",
        "juillet", "aout", "septembre", "octobre", "novembre", "decembre"]


def fr(x, dec=1):
    return f"{x:.{dec}f}".replace(".", ",")


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def best_per_day(report):
    """Un creneau par jour, tous spots confondus. Sert au mail."""
    by_day = {}
    for r in report:
        for s in r["slots"]:
            day = s["time"][:10]
            cur = by_day.get(day)
            if cur is None or s["score"] > cur[1]["score"]:
                by_day[day] = (r["spot"], s)
    return [by_day[d] for d in sorted(by_day)]


def days_of_spot(spot_report):
    """Le meilleur creneau de chaque jour, pour un spot donne."""
    by_day = {}
    for s in spot_report["slots"]:
        day = s["time"][:10]
        if day not in by_day or s["score"] > by_day[day]["score"]:
            by_day[day] = s
    return [by_day[d] for d in sorted(by_day)]


def tone(score):
    """Trois niveaux. Les noms de classes viennent de la maquette."""
    if score >= 7.5:
        return "bon"
    if score >= 5.5:
        return "moyen"
    return "mauvais"


# CSS repris de la maquette Claude Design, inchange.
CSS = """
:root{
  --bg:#161826;
  --text:#e9e9ed;
  --text-soft:rgba(233,233,237,.72);
  --text-mute:rgba(233,233,237,.45);
  --text-faint:rgba(233,233,237,.36);
  --bon:#d2cefd;
  --moyen:rgba(233,233,237,.80);
  --mauvais:rgba(233,233,237,.42);
  --gut:clamp(24px,6vw,72px);
}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{
  margin:0;
  background:var(--bg);
  color:var(--text);
  font-family:Inter,ui-sans-serif,system-ui,-apple-system,"Segoe UI",Helvetica,Arial,sans-serif;
  font-size:15px;
  line-height:1.55;
  font-weight:400;
  -webkit-font-smoothing:antialiased;
}
a{color:var(--bon);text-decoration:none}
a:hover{color:var(--text)}
::selection{background:rgba(145,132,217,.35)}
.page{max-width:960px;margin:0 auto;padding:clamp(28px,5vw,64px) var(--gut) clamp(48px,7vw,80px)}

/* 1. en-tête */
.head{display:flex;align-items:baseline;justify-content:space-between;gap:16px}
.brand{font-size:13px;font-weight:500;letter-spacing:.01em}
.date{font-size:13px;color:var(--text-mute);white-space:nowrap}

/* 2. verdict */
.verdict{margin-top:clamp(56px,11vw,104px);max-width:44ch}
.kicker{font-size:11px;letter-spacing:.14em;text-transform:uppercase;color:var(--text-faint)}
.verdict h1{
  margin:clamp(12px,2vw,18px) 0 0;
  font-size:clamp(32px,8vw,54px);
  line-height:1.08;
  font-weight:400;
  letter-spacing:-.022em;
  text-wrap:balance;
}
.verdict h1 .spot{font-weight:300;color:rgba(233,233,237,.52)}
.lede{
  margin:clamp(16px,2.4vw,22px) 0 0;
  font-size:clamp(17px,2.4vw,19px);
  line-height:1.5;
  font-weight:300;
  color:var(--text-soft);
  text-wrap:pretty;
}
.metrics{margin-top:12px;font-size:13px;color:var(--text-mute);font-variant-numeric:tabular-nums}

/* 3. spots */
.spots{
  display:grid;
  grid-template-columns:repeat(2,minmax(0,1fr));
  gap:clamp(40px,6vw,72px);
  margin-top:clamp(64px,12vw,112px);
}
.spot-name{
  font-size:11px;letter-spacing:.14em;text-transform:uppercase;
  color:var(--text-faint);
  margin:0 0 clamp(24px,3.4vw,32px);
  font-weight:400;
}
.days{display:flex;flex-direction:column;gap:clamp(28px,3.6vw,34px)}
.day-top{display:flex;align-items:baseline;justify-content:space-between;gap:14px}
.when{font-size:17px;line-height:1.25}
.score{
  font-size:24px;line-height:1.1;font-weight:400;
  font-variant-numeric:tabular-nums;
  white-space:nowrap;
}
.score.bon{color:var(--bon)}
.score.moyen{color:var(--moyen)}
.score.mauvais{color:var(--mauvais)}
.day-metrics{margin-top:5px;font-size:13px;color:var(--text-mute);font-variant-numeric:tabular-nums;text-wrap:pretty}
.day-why{margin-top:7px;font-size:14px;line-height:1.45;font-weight:300;color:var(--text-soft);text-wrap:pretty}

/* 4. avertissement */
.note{
  margin:clamp(64px,11vw,104px) 0 0;
  max-width:46ch;
  font-size:13px;line-height:1.65;font-weight:300;
  color:rgba(233,233,237,.58);
  text-wrap:pretty;
}

@media (max-width:640px){
  .spots{grid-template-columns:minmax(0,1fr);gap:clamp(48px,12vw,64px)}
}
"""


def render_web(report, best, site_title="Surf de la semaine"):
    today = datetime.now()
    date_str = (f"{JOURS_COURTS[today.weekday()].lower()} {today.day} "
                f"{MOIS[today.month - 1]}")

    h = ['<!DOCTYPE html><html lang="fr"><head><meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width, initial-scale=1">',
         f'<title>{esc(site_title)} &mdash; {date_str}</title>',
         # La maquette appelle Inter sans la charger : sans ce lien, le
         # navigateur retombe sur la police systeme et le rendu change.
         '<link rel="preconnect" href="https://fonts.googleapis.com">',
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
         '<link href="https://fonts.googleapis.com/css2?'
         'family=Inter:wght@300;400;500&display=swap" rel="stylesheet">',
         f'<style>{CSS}</style></head><body>',
         '<main class="page">']

    # --- 1. en-tete ---------------------------------------------------------
    h.append('<header class="head">'
             f'<span class="brand">{esc(site_title)}</span>'
             f'<span class="date">{date_str}</span>'
             '</header>')

    # --- 2. verdict ---------------------------------------------------------
    h.append('<section class="verdict">')
    if best and best[1]["score"] >= 4:
        spot, s = best
        d = datetime.fromisoformat(s["time"])
        h.append('<p class="kicker">Le creneau de la semaine</p>')
        h.append(f'<h1>{JOURS[d.weekday()].capitalize()} {d.hour}h '
                 f'<span class="spot">{esc(spot)}</span> '
                 f'<span class="score {tone(s["score"])}" '
                 f'style="font-size:inherit">{fr(s["score"])}</span></h1>')
        h.append(f'<p class="lede">{esc(s["why"])}</p>')
        h.append(f'<p class="metrics">{fr(s["wave_height"])} m &middot; '
                 f'{s["wave_period"]:.0f} s &middot; '
                 f'{s["wind_speed"]:.0f} km/h {esc(s.get("wind_rel", ""))}</p>')
    else:
        # Etat vide : la maquette ne le prevoyait pas, meme grammaire visuelle.
        h.append('<p class="kicker">Le creneau de la semaine</p>')
        h.append('<h1>Aucun <span class="spot">cette semaine</span></h1>')
        h.append('<p class="lede">Rien ne passe la barre sur les deux spots. '
                 'Le detail reste ci-dessous.</p>')
    h.append('</section>')

    # --- 3. spots -----------------------------------------------------------
    h.append('<section class="spots">')
    for r in report:
        h.append('<div>')
        h.append(f'<h2 class="spot-name">{esc(r["spot"])}</h2>')
        h.append('<div class="days">')
        for s in days_of_spot(r):
            d = datetime.fromisoformat(s["time"])
            h.append('<article>')
            h.append('<div class="day-top">'
                     f'<span class="when">{JOURS[d.weekday()].capitalize()} '
                     f'{d.hour}h</span>'
                     f'<span class="score {tone(s["score"])}">'
                     f'{fr(s["score"])}</span></div>')
            h.append(f'<p class="day-metrics">{fr(s["wave_height"])} m &middot; '
                     f'{s["wave_period"]:.0f} s &middot; '
                     f'{s["wind_speed"]:.0f} km/h '
                     f'{esc(s.get("wind_rel", ""))}</p>')
            h.append(f'<p class="day-why">{esc(s.get("short", ""))}</p>')
            h.append('</article>')
        h.append('</div></div>')
    h.append('</section>')

    # --- 4. avertissement ---------------------------------------------------
    h.append('<footer><p class="note">Les marees ne sont pas dans la note. '
             'Verifie le coefficient avant de partir : au-dela de 90, les '
             'courants tirent fort sur la cote sauvage.</p></footer>')

    h.append('</main></body></html>')
    return "".join(h)

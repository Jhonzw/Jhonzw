#!/usr/bin/env python3
"""Gera os SVGs do perfil (hero + card de atividade) a partir da API do GitHub.

Os cards ficam versionados em assets/ — nada de serviço de terceiro que sai do ar
ou estoura rate limit. Rode local com GH_TOKEN=... ou deixe o workflow rodar sozinho.

    GH_TOKEN=xxx python3 scripts/render_cards.py
"""

from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import urllib.request

LOGIN = os.environ.get("PROFILE_LOGIN", "Jhonzw")
ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ── paleta ────────────────────────────────────────────────────────────────────
DARK = {
    "bg": "#0D1117",
    "panel": "#0F141A",
    "hairline": "#20272F",
    "grid": "#8FB4C8",
    "grid_op": 0.045,
    "accent": "#22D3EE",
    "accent_soft": "#0E7490",
    "text": "#E6EDF3",
    "muted": "#7D8792",
    "heat": ["#161B22", "#0E4E5E", "#0E7490", "#22A7C4", "#5EE7F7"],
    "ramp": ["#22D3EE", "#22A7C4", "#1B7F96", "#155E6E", "#123F49"],
    "glow": 0.13,
}

LIGHT = {
    "bg": "#F7F9FB",
    "panel": "#FFFFFF",
    "hairline": "#D6DEE6",
    "grid": "#3E6B80",
    "grid_op": 0.055,
    "accent": "#0E7490",
    "accent_soft": "#67C7DA",
    "text": "#0D1117",
    "muted": "#5B6873",
    "heat": ["#E8EDF1", "#BEE3EC", "#7FC7DA", "#3B9CB5", "#0E7490"],
    "ramp": ["#0E7490", "#1B93AE", "#4FB3C9", "#8FD1DF", "#C6E7EE"],
    "glow": 0.09,
}

SANS = "'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,'SF Mono','Cascadia Mono','JetBrains Mono',Menlo,Consolas,monospace"

MESES = "jan fev mar abr mai jun jul ago set out nov dez".split()

# ── dados ─────────────────────────────────────────────────────────────────────
QUERY = """
query($login:String!){
  user(login:$login){
    name createdAt
    repositories(first:100, ownerAffiliations:OWNER, isFork:false){
      totalCount
      nodes{
        languages(first:12, orderBy:{field:SIZE, direction:DESC}){
          edges{ size node{ name } }
        }
      }
    }
    contributionsCollection{
      contributionCalendar{
        totalContributions
        weeks{ contributionDays{ date contributionCount } }
      }
    }
  }
}
"""


def fetch() -> dict:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("defina GH_TOKEN (ou GITHUB_TOKEN) no ambiente")
    body = json.dumps({"query": QUERY, "variables": {"login": LOGIN}}).encode()
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": f"{LOGIN}-profile-cards",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.load(resp)
    if payload.get("errors"):
        raise SystemExit(f"GraphQL: {payload['errors']}")
    return payload["data"]["user"]


def collect(user: dict) -> dict:
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks_raw = cal["weeks"]
    days = [d for w in weeks_raw for d in w["contributionDays"]]

    langs: dict[str, int] = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            langs[name] = langs.get(name, 0) + edge["size"]
    total_bytes = sum(langs.values()) or 1
    ranked = sorted(langs.items(), key=lambda kv: -kv[1])

    # cor por posição numa rampa de ciano — o arco-íris padrão do GitHub brigaria
    # com a identidade do card
    top = ranked[:4]
    outros = sum(v for _, v in ranked[4:])
    bar = [(k, v / total_bytes * 100, i) for i, (k, v) in enumerate(top)]
    if outros:
        bar.append(("Outros", outros / total_bytes * 100, len(bar)))

    # sequências (dias consecutivos com contribuição)
    longest = current = 0
    for day in days:
        if day["contributionCount"] > 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0

    criado = dt.date.fromisoformat(user["createdAt"][:10])

    return {
        "contribs": cal["totalContributions"],
        "repos": user["repositories"]["totalCount"],
        "anos": (dt.date.today() - criado).days // 365,
        "ativos": sum(1 for d in days if d["contributionCount"] > 0),
        "longest": longest,
        "bar": bar,
        "days": days,
        "semanal": [sum(d["contributionCount"] for d in w["contributionDays"])
                    for w in weeks_raw],
    }


# ── helpers de svg ────────────────────────────────────────────────────────────
def br(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def text(x, y, s, *, size=14, fill="#fff", weight=400, spacing=0,
         anchor="start", family=SANS, opacity=1.0):
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    op = f' opacity="{opacity}"' if opacity != 1.0 else ""
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}{op}>'
            f'{esc(s)}</text>')


def grid(t: dict, w: int, h: int, step: int = 40) -> str:
    lines = []
    for x in range(step, w, step):
        lines.append(f'<path d="M{x} 0V{h}"/>')
    for y in range(step, h, step):
        lines.append(f'<path d="M0 {y}H{w}"/>')
    return (f'<g stroke="{t["grid"]}" stroke-width="1" opacity="{t["grid_op"]}">'
            + "".join(lines) + "</g>")


def sparkline(t: dict, vals: list[int], x: int, y: int, w: int, h: int) -> str:
    """Contribuições por semana, como área + linha."""
    if not vals:
        return ""
    peak = max(vals) or 1
    n = len(vals)
    pts = [(x + i * w / (n - 1), y + h - (v / peak) * h) for i, v in enumerate(vals)]
    line = "M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in pts)
    area = f"{line} L{x + w} {y + h} L{x} {y + h} Z"
    last_x, last_y = pts[-1]
    return f'''<g>
  <path d="{area}" fill="url(#spark)"/>
  <path d="{line}" fill="none" stroke="{t['accent']}" stroke-width="1.8"
        stroke-linejoin="round" stroke-linecap="round"/>
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="{t['accent']}"/>
  <circle cx="{last_x:.1f}" cy="{last_y:.1f}" r="3.5" fill="none"
          stroke="{t['accent']}" stroke-width="1.5" opacity="0.6">
    <animate attributeName="r" values="3.5;11;3.5" dur="2.6s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="0.6;0;0.6" dur="2.6s" repeatCount="indefinite"/>
  </circle>
</g>'''


# ── hero ──────────────────────────────────────────────────────────────────────
def hero(t: dict, d: dict) -> str:
    W, H = 1000, 300
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" role="img" '
         f'aria-label="João Vitor — Analista de Negócios e Desenvolvedor Full Stack">']

    p.append(f'''<defs>
  <linearGradient id="rule" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{t['accent']}"/>
    <stop offset="100%" stop-color="{t['accent']}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="spark" x1="0" y1="0" x2="0" y2="1">
    <stop offset="0%" stop-color="{t['accent']}" stop-opacity="0.30"/>
    <stop offset="100%" stop-color="{t['accent']}" stop-opacity="0"/>
  </linearGradient>
  <radialGradient id="glow" cx="0.80" cy="0.22" r="0.60">
    <stop offset="0%" stop-color="{t['accent']}" stop-opacity="{t['glow']}"/>
    <stop offset="100%" stop-color="{t['accent']}" stop-opacity="0"/>
  </radialGradient>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="12"/></clipPath>
</defs>''')

    p.append('<g clip-path="url(#frame)">')
    p.append(f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>')
    p.append(grid(t, W, H))
    p.append(f'<rect width="{W}" height="{H}" fill="url(#glow)"/>')

    x = 60

    # sparkline das 52 semanas
    p.append(sparkline(t, d["semanal"], 596, 96, 336, 78))
    p.append(text(596, 84, "contribuições · 52 semanas", size=10.5, fill=t["muted"],
                  family=MONO, spacing=0.4))
    p.append(f'<rect x="596" y="186" width="336" height="1" fill="{t["hairline"]}"/>')

    # eyebrow em mono, cara de shell
    p.append(text(x, 66, "$", size=12, fill=t["accent"], family=MONO, weight=700))
    p.append(text(x + 14, 66, "whoami  ·  goiânia · brasil", size=12,
                  fill=t["muted"], family=MONO, spacing=0.5))

    # nome + cursor piscando
    p.append(text(x, 137, "JOÃO VITOR", size=56, fill=t["text"], weight=700, spacing=1))
    p.append(f'<rect x="{x + 398}" y="99" width="12" height="39" fill="{t["accent"]}">'
             f'<animate attributeName="opacity" values="1;1;0;0" dur="1.15s" '
             f'repeatCount="indefinite"/></rect>')

    p.append(f'<rect x="{x}" y="157" width="360" height="2" fill="url(#rule)"/>')

    p.append(text(x, 191, "Analista de Negócios  ·  Desenvolvedor Full Stack",
                  size=19, fill=t["text"], weight=500))
    p.append(text(x, 216, "ERP Protheus  ·  SQL & BI  ·  Automação de processos",
                  size=13, fill=t["muted"], family=MONO, spacing=0.2))

    # chips em mono com colchetes
    chips = [f"{d['anos']} anos", f"{d['repos']} repos",
             f"{br(d['contribs'])} contribuições/ano"]
    cx = x
    p.append(f'<rect x="{x}" y="243" width="480" height="1" fill="{t["hairline"]}"/>')
    for chip in chips:
        wid = len(chip) * 7.0 + 22
        p.append(f'<rect x="{cx}" y="258" width="{wid:.0f}" height="24" rx="4" '
                 f'fill="none" stroke="{t["hairline"]}"/>')
        p.append(text(cx + 9, 274, chip, size=11.5, fill=t["muted"], family=MONO))
        cx += wid + 8

    p.append("</g>")
    p.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" '
             f'fill="none" stroke="{t["hairline"]}"/>')
    p.append("</svg>")
    return "\n".join(p)


# ── card de atividade ─────────────────────────────────────────────────────────
def stats(t: dict, d: dict) -> str:
    W, H = 1000, 400
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" role="img" aria-label="Atividade no GitHub">']
    p.append(f'''<defs>
  <linearGradient id="hr" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{t['accent']}" stop-opacity="0.7"/>
    <stop offset="100%" stop-color="{t['accent']}" stop-opacity="0"/>
  </linearGradient>
  <clipPath id="cardframe"><rect width="{W}" height="{H}" rx="12"/></clipPath>
</defs>''')
    p.append('<g clip-path="url(#cardframe)">')
    p.append(f'<rect width="{W}" height="{H}" fill="{t["panel"]}"/>')
    p.append(grid(t, W, H, 50))
    p.append("</g>")
    p.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="12" '
             f'fill="none" stroke="{t["hairline"]}"/>')

    M = 44
    hoje = dt.date.today()
    p.append(f'<rect x="{M}" y="38" width="3" height="13" fill="{t["accent"]}"/>')
    p.append(text(M + 13, 49, "ATIVIDADE", size=11, fill=t["accent"], weight=700,
                  spacing=2.6, family=MONO))
    p.append(text(W - M, 49, f"atualizado em {hoje.day:02d} {MESES[hoje.month - 1]} {hoje.year}",
                  size=11, fill=t["muted"], anchor="end", family=MONO))
    p.append(f'<rect x="{M}" y="64" width="{W - 2 * M}" height="1" fill="url(#hr)"/>')

    metrics = [
        (br(d["contribs"]), "contribuições · 12 meses"),
        (br(d["repos"]), "repositórios próprios"),
        (br(d["ativos"]), "dias com commit"),
        (br(d["longest"]), "maior sequência (dias)"),
    ]
    col = (W - 2 * M) / 4
    for i, (big, label) in enumerate(metrics):
        cx = M + col * i
        if i:
            p.append(f'<rect x="{cx - 14:.0f}" y="92" width="1" height="52" '
                     f'fill="{t["hairline"]}"/>')
        p.append(text(cx, 130, big, size=38, fill=t["text"], weight=600,
                      family=MONO, spacing=-1))
        p.append(text(cx, 152, label, size=11.5, fill=t["muted"], weight=400,
                      family=MONO))

    p.append(f'<rect x="{M}" y="182" width="{W - 2 * M}" height="1" fill="{t["hairline"]}"/>')

    # linguagens
    p.append(f'<rect x="{M}" y="207" width="3" height="11" fill="{t["accent"]}"/>')
    p.append(text(M + 13, 217, "LINGUAGENS", size=10.5, fill=t["muted"], weight=700,
                  spacing=2.4, family=MONO))
    bar_w, bar_x, bar_y = 400, M, 232
    off = 0.0
    for i, (name, pct, ci) in enumerate(d["bar"]):
        w = max(bar_w * pct / 100, 2)
        r = 'rx="2"' if i == 0 or i == len(d["bar"]) - 1 else ""
        p.append(f'<rect x="{bar_x + off:.1f}" y="{bar_y}" width="{w:.1f}" height="10" '
                 f'{r} fill="{t["ramp"][ci]}"/>')
        off += w + 1.5

    ly = 269
    for i, (name, pct, ci) in enumerate(d["bar"]):
        lx = bar_x + (i % 2) * 205
        if i and i % 2 == 0:
            ly += 25
        p.append(f'<rect x="{lx}" y="{ly - 12}" width="9" height="9" rx="1.5" '
                 f'fill="{t["ramp"][ci]}"/>')
        p.append(text(lx + 16, ly, name, size=12.5, fill=t["text"], weight=500))
        p.append(text(lx + 190, ly, f"{pct:.1f}%", size=12.5, fill=t["muted"],
                      anchor="end", family=MONO))

    # heatmap — últimas 26 semanas
    hx, hy = 545, 232
    cell, gap = 12, 3.2
    days = d["days"]
    start = len(days) % 7
    weeks: list[list[dict]] = []
    week: list[dict] = []
    for day in days[start:]:
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week)
    weeks = weeks[-26:]

    p.append(f'<rect x="{hx}" y="207" width="3" height="11" fill="{t["accent"]}"/>')
    p.append(text(hx + 13, 217, "ÚLTIMOS 6 MESES", size=10.5, fill=t["muted"],
                  weight=700, spacing=2.4, family=MONO))

    peak = max((day["contributionCount"] for w in weeks for day in w), default=1) or 1
    for wi, w in enumerate(weeks):
        for di, day in enumerate(w):
            n = day["contributionCount"]
            if n == 0:
                idx = 0
            else:
                ratio = n / peak
                idx = 1 if ratio <= 0.15 else 2 if ratio <= 0.4 else 3 if ratio <= 0.7 else 4
            p.append(f'<rect x="{hx + wi * (cell + gap):.1f}" y="{hy + di * (cell + gap):.1f}" '
                     f'width="{cell}" height="{cell}" rx="2" fill="{t["heat"][idx]}"/>')

    lg_y = hy + 7 * (cell + gap) + 16
    p.append(text(hx, lg_y, "menos", size=10.5, fill=t["muted"], family=MONO))
    for i, c in enumerate(t["heat"]):
        p.append(f'<rect x="{hx + 48 + i * 15}" y="{lg_y - 9}" width="11" height="11" '
                 f'rx="2" fill="{c}"/>')
    p.append(text(hx + 48 + 5 * 15 + 6, lg_y, "mais", size=10.5, fill=t["muted"],
                  family=MONO))

    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    data = collect(fetch())
    ASSETS.mkdir(exist_ok=True)
    for suffix, theme in (("dark", DARK), ("light", LIGHT)):
        (ASSETS / f"hero-{suffix}.svg").write_text(hero(theme, data), encoding="utf-8")
        (ASSETS / f"stats-{suffix}.svg").write_text(stats(theme, data), encoding="utf-8")
    print(f"ok — {data['contribs']} contribuições, {data['repos']} repos, "
          f"{len(data['semanal'])} semanas no sparkline")


if __name__ == "__main__":
    main()

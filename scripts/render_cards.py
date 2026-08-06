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
import urllib.error
import urllib.request

LOGIN = os.environ.get("PROFILE_LOGIN", "Jhonzw")
ROOT = pathlib.Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# ── paleta ────────────────────────────────────────────────────────────────────
DARK = {
    "bg": "#0B0D10",
    "panel": "#0F1317",
    "hairline": "#1E242B",
    "gold": "#D4A24C",
    "gold_bright": "#F2D398",
    "gold_deep": "#8A6B34",
    "text": "#EDEAE5",
    "muted": "#8A9099",
    "heat": ["#151A20", "#4A3A1C", "#8A6B34", "#C2913C", "#F2D398"],
    "ramp": ["#F2D398", "#D0A055", "#A87F30", "#7A5E2E", "#4E3F22"],
    "glow": 0.10,
}

LIGHT = {
    "bg": "#FBF9F6",
    "panel": "#FFFFFF",
    "hairline": "#E6E0D6",
    "gold": "#9A6C1F",
    "gold_bright": "#C2913C",
    "gold_deep": "#D8C6A2",
    "text": "#15130F",
    "muted": "#6B6558",
    "heat": ["#EDE8DE", "#E0CDA4", "#C9A868", "#A87F30", "#79571A"],
    "ramp": ["#7A571A", "#A87F30", "#C7A05A", "#DCC191", "#EBDFC5"],
    "glow": 0.07,
}

SANS = "'Segoe UI',Roboto,Ubuntu,'Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "ui-monospace,'SF Mono','Cascadia Mono',Menlo,Consolas,monospace"

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
          edges{ size node{ name color } }
        }
      }
    }
    contributionsCollection{
      totalCommitContributions
      restrictedContributionsCount
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
    days = [d for w in cal["weeks"] for d in w["contributionDays"]]

    langs: dict[str, int] = {}
    for repo in user["repositories"]["nodes"]:
        for edge in repo["languages"]["edges"]:
            name = edge["node"]["name"]
            langs[name] = langs.get(name, 0) + edge["size"]
    total_bytes = sum(langs.values()) or 1
    ranked = sorted(langs.items(), key=lambda kv: -kv[1])

    # cor por posição, numa rampa dourada — o arco-íris padrão do GitHub brigaria
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
    streak_now = 0
    for day in reversed(days):
        if day["date"] > dt.date.today().isoformat():
            continue
        if day["contributionCount"] > 0:
            streak_now += 1
        elif streak_now or day["date"] < dt.date.today().isoformat():
            break

    criado = dt.date.fromisoformat(user["createdAt"][:10])
    anos = (dt.date.today() - criado).days // 365

    return {
        "contribs": cal["totalContributions"],
        "repos": user["repositories"]["totalCount"],
        "anos": anos,
        "desde": criado.year,
        "ativos": sum(1 for d in days if d["contributionCount"] > 0),
        "longest": longest,
        "streak_now": streak_now,
        "bar": bar,
        "days": days,
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


def diamond(cx, cy, r, fill, opacity=1.0):
    return (f'<path d="M{cx} {cy - r}L{cx + r} {cy}L{cx} {cy + r}L{cx - r} {cy}Z" '
            f'fill="{fill}" opacity="{opacity}"/>')


# ── hero ──────────────────────────────────────────────────────────────────────
def hero(t: dict, d: dict) -> str:
    W, H = 1000, 300
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
             f'viewBox="0 0 {W} {H}" role="img" '
             f'aria-label="João Vitor — Analista de Negócios e Desenvolvedor Full Stack">')

    p.append(f'''<defs>
  <linearGradient id="rule" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{t['gold']}"/>
    <stop offset="35%" stop-color="{t['gold_bright']}"/>
    <stop offset="100%" stop-color="{t['gold']}" stop-opacity="0"/>
  </linearGradient>
  <linearGradient id="shine" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0%" stop-color="{t['gold_bright']}" stop-opacity="0"/>
    <stop offset="50%" stop-color="{t['gold_bright']}"/>
    <stop offset="100%" stop-color="{t['gold_bright']}" stop-opacity="0"/>
  </linearGradient>
  <radialGradient id="glow" cx="0.82" cy="0.18" r="0.62">
    <stop offset="0%" stop-color="{t['gold']}" stop-opacity="{t['glow']}"/>
    <stop offset="100%" stop-color="{t['gold']}" stop-opacity="0"/>
  </radialGradient>
  <clipPath id="frame"><rect width="{W}" height="{H}" rx="16"/></clipPath>
</defs>''')

    p.append(f'<g clip-path="url(#frame)">')
    p.append(f'<rect width="{W}" height="{H}" fill="{t["bg"]}"/>')
    p.append(f'<rect width="{W}" height="{H}" fill="url(#glow)"/>')

    # ornamento: arcos concêntricos à direita
    for i, r in enumerate((92, 128, 164, 200, 236)):
        p.append(f'<circle cx="838" cy="150" r="{r}" fill="none" '
                 f'stroke="{t["gold"]}" stroke-width="1" opacity="{0.16 - i * 0.025:.3f}"/>')
    # monograma fantasma
    p.append(f'<text x="838" y="196" font-family="{SANS}" font-size="150" font-weight="700" '
             f'fill="{t["gold"]}" opacity="0.07" text-anchor="middle" letter-spacing="6">JV</text>')
    p.append(f'<circle cx="838" cy="150" r="56" fill="none" stroke="{t["gold"]}" '
             f'stroke-width="1" opacity="0.5"/>')
    p.append(f'<circle cx="838" cy="150" r="56" fill="none" stroke="{t["gold_bright"]}" '
             f'stroke-width="1.5" stroke-dasharray="26 326" stroke-linecap="round" opacity="0.9">'
             f'<animateTransform attributeName="transform" type="rotate" '
             f'from="0 838 150" to="360 838 150" dur="14s" repeatCount="indefinite"/></circle>')

    x = 64
    # sobrelinha
    p.append(diamond(x + 3, 63, 3.5, t["gold"]))
    p.append(text(x + 18, 67, "GOIÂNIA · BRASIL", size=11, fill=t["muted"],
                  weight=600, spacing=3.4))

    # nome
    p.append(text(x, 138, "JOÃO VITOR", size=62, fill=t["text"], weight=300, spacing=5))

    # filete dourado + brilho que passa
    p.append(f'<rect x="{x}" y="157" width="380" height="2" fill="url(#rule)"/>')
    p.append(f'<rect x="{x}" y="157" width="110" height="2" fill="url(#shine)" opacity="0.95">'
             f'<animate attributeName="x" values="{x};{x + 270};{x}" dur="6s" '
             f'repeatCount="indefinite" calcMode="spline" '
             f'keySplines="0.4 0 0.2 1;0.4 0 0.2 1" keyTimes="0;0.5;1"/></rect>')

    # cargo
    p.append(text(x, 191, "Analista de Negócios  ·  Desenvolvedor Full Stack",
                  size=19, fill=t["text"], weight=500))
    p.append(text(x, 216, "ERP Protheus  ·  SQL & BI  ·  Automação de processos",
                  size=13.5, fill=t["muted"], weight=400, spacing=0.8))

    # chips de números
    chips = [
        (f"{t_anos} anos no GitHub" if (t_anos := d["anos"]) != 1 else "1 ano no GitHub"),
        f"{d['repos']} repositórios",
        f"{br(d['contribs'])} contribuições em 12 meses",
    ]
    cx = x
    p.append(f'<rect x="{x}" y="242" width="700" height="1" fill="{t["hairline"]}"/>')
    for i, chip in enumerate(chips):
        if i:
            p.append(diamond(cx + 9, 268, 3, t["gold"], 0.85))
            cx += 26
        p.append(text(cx, 272, chip, size=12.5, fill=t["muted"], weight=500, spacing=0.4))
        cx += len(chip) * 6.55 + 8

    p.append("</g>")
    p.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" '
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
    <stop offset="0%" stop-color="{t['gold']}" stop-opacity="0.75"/>
    <stop offset="100%" stop-color="{t['gold']}" stop-opacity="0"/>
  </linearGradient>
</defs>''')
    p.append(f'<rect width="{W}" height="{H}" rx="16" fill="{t["panel"]}"/>')
    p.append(f'<rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" '
             f'fill="none" stroke="{t["hairline"]}"/>')

    M = 44
    hoje = dt.date.today()
    p.append(diamond(M + 3, 45, 3.5, t["gold"]))
    p.append(text(M + 18, 49, "ATIVIDADE", size=11, fill=t["gold"], weight=700, spacing=3.4))
    p.append(text(W - M, 49, f"atualizado em {hoje.day:02d} {MESES[hoje.month - 1]} {hoje.year}",
                  size=11, fill=t["muted"], anchor="end", spacing=0.6))
    p.append(f'<rect x="{M}" y="64" width="{W - 2 * M}" height="1" fill="url(#hr)"/>')

    # métricas
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
        p.append(text(cx, 130, big, size=40, fill=t["text"], weight=300, spacing=-0.5))
        p.append(text(cx, 152, label, size=11.5, fill=t["muted"], weight=500, spacing=0.5))

    p.append(f'<rect x="{M}" y="182" width="{W - 2 * M}" height="1" fill="{t["hairline"]}"/>')

    # linguagens
    p.append(diamond(M + 3, 213, 3, t["gold"], 0.9))
    p.append(text(M + 16, 217, "LINGUAGENS", size=10.5, fill=t["muted"],
                  weight=700, spacing=3))
    bar_w, bar_x, bar_y = 400, M, 232
    off = 0.0
    for i, (name, pct, ci) in enumerate(d["bar"]):
        w = max(bar_w * pct / 100, 2)
        r = 'rx="5"' if i == 0 or i == len(d["bar"]) - 1 else ""
        p.append(f'<rect x="{bar_x + off:.1f}" y="{bar_y}" width="{w:.1f}" height="10" '
                 f'{r} fill="{t["ramp"][ci]}"/>')
        off += w + 1.5

    ly = 269
    for i, (name, pct, ci) in enumerate(d["bar"]):
        lx = bar_x + (i % 2) * 205
        if i and i % 2 == 0:
            ly += 25
        p.append(f'<rect x="{lx}" y="{ly - 12}" width="9" height="9" rx="2" '
                 f'fill="{t["ramp"][ci]}"/>')
        p.append(text(lx + 16, ly, name, size=12.5, fill=t["text"], weight=500))
        p.append(text(lx + 190, ly, f"{pct:.1f}%", size=12.5, fill=t["muted"],
                      anchor="end", family=MONO))

    # heatmap — últimas 26 semanas
    hx, hy = 545, 232
    cell, gap = 12, 3.2
    weeks: list[list[dict]] = []
    days = d["days"]
    start = len(days) % 7
    week: list[dict] = []
    for day in days[start:]:
        week.append(day)
        if len(week) == 7:
            weeks.append(week)
            week = []
    if week:
        weeks.append(week)
    weeks = weeks[-26:]

    p.append(diamond(hx + 3, 213, 3, t["gold"], 0.9))
    p.append(text(hx + 16, 217, "ÚLTIMOS 6 MESES", size=10.5, fill=t["muted"],
                  weight=700, spacing=3))

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
                     f'width="{cell}" height="{cell}" rx="2.5" fill="{t["heat"][idx]}"/>')

    lg_y = hy + 7 * (cell + gap) + 16
    p.append(text(hx, lg_y, "menos", size=10.5, fill=t["muted"]))
    for i, c in enumerate(t["heat"]):
        p.append(f'<rect x="{hx + 44 + i * 15}" y="{lg_y - 9}" width="11" height="11" '
                 f'rx="2.5" fill="{c}"/>')
    p.append(text(hx + 44 + 5 * 15 + 6, lg_y, "mais", size=10.5, fill=t["muted"]))

    p.append("</svg>")
    return "\n".join(p)


def main() -> None:
    data = collect(fetch())
    ASSETS.mkdir(exist_ok=True)
    for suffix, theme in (("dark", DARK), ("light", LIGHT)):
        (ASSETS / f"hero-{suffix}.svg").write_text(hero(theme, data), encoding="utf-8")
        (ASSETS / f"stats-{suffix}.svg").write_text(stats(theme, data), encoding="utf-8")
    print(f"ok — {data['contribs']} contribuições, {data['repos']} repos, "
          f"{len(data['bar'])} linguagens no gráfico")


if __name__ == "__main__":
    main()

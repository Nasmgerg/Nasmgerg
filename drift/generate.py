"""
Contribution drift – a GitHub contribution-gráfodon egy piros autó halad végig
soronként, a sorok végén driftelve fordul, és felszedi a cellákat.

Használat:
  GITHUB_TOKEN=... python drift/generate.py <felhasználónév> <kimeneti mappa>
  python drift/generate.py --demo <kimeneti mappa>   (minta adatokkal, token nélkül)

Két fájlt készít: drift-dark.svg és drift-light.svg.
Csak a Python standard könyvtárát használja.
"""
import datetime as dt
import json
import math
import os
import random
import sys
import urllib.request

# ---------------------------------------------------------------- beállítások
P = 20            # cella + rés (px)
CS = 16           # cella mérete (px)
X0, Y0 = 80, 86   # a rács bal felső sarka
E = 16            # ennyit fut túl a rácson fordulás előtt
R = 10            # fordulási sugár (fél sortávolság)
SPEED = 420       # px/s egyenesen
TT = 0.6          # egy fordulás ideje (s)
END = 1.6         # a kör végi kifutás (s)
FPS = 25          # mintavételezés az autó mozgásához

MONTHS_HU = ["Jan", "Feb", "Már", "Ápr", "Máj", "Jún", "Júl", "Aug", "Szep", "Okt", "Nov", "Dec"]
LEVELS = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}

THEMES = {
    "dark": dict(bg="#110b0f", muted="#a08890", accent="#f4a7b9",
                 levels=["#221a22", "#4d2236", "#8c2f55", "#d2497a", "#ff9cb8"],
                 mark="#4a3239", puff="#e6d6dc", puff_a=0.42, beam=0.32),
    "light": dict(bg="#ffffff", muted="#6f5960", accent="#a81d4b",
                  levels=["#f1e9eb", "#f7c6d4", "#ec8fae", "#d2497a", "#951c46"],
                  mark="#d4c2c8", puff="#9a8a90", puff_a=0.35, beam=0.22),
}

QUERY = """query($login:String!){user(login:$login){contributionsCollection{contributionCalendar{
totalContributions weeks{contributionDays{contributionLevel date weekday}}}}}}"""


# ---------------------------------------------------------------- adatok
def fetch(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json",
                 "User-Agent": "contribution-drift"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if "errors" in data:
        raise SystemExit(f"GitHub API hiba: {data['errors']}")
    cal = data["data"]["user"]["contributionsCollection"]["contributionCalendar"]
    weeks = []
    for w in cal["weeks"]:
        col = [None] * 7
        for d in w["contributionDays"]:
            col[d["weekday"]] = (LEVELS[d["contributionLevel"]], d["date"])
        weeks.append(col)
    return weeks, cal["totalContributions"]


def demo():
    rnd = random.Random(7)
    start = dt.date.today() - dt.timedelta(days=364)
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)  # vasárnapra
    weeks, total = [], 0
    for c in range(53):
        col = []
        for r in range(7):
            day = start + dt.timedelta(days=c * 7 + r)
            if day > dt.date.today():
                col.append(None)
                continue
            lvl = rnd.choice([0, 0, 0, 1, 1, 2, 3, 4]) if c > 36 else (1 if rnd.random() < 0.04 else 0)
            total += [0, 1, 3, 6, 10][lvl]
            col.append((lvl, day.isoformat()))
        weeks.append(col)
    return weeks, total


# ---------------------------------------------------------------- mozgás
class Track:
    def __init__(self, cols):
        self.cols = cols
        self.xA = self.cx(0) - E
        self.xB = self.cx(cols - 1) + E
        self.L = self.xB - self.xA
        self.TS = self.L / SPEED
        self.total = 7 * self.TS + 6 * TT + END

    @staticmethod
    def cx(c):
        return X0 + c * P + CS / 2

    @staticmethod
    def cy(r):
        return Y0 + r * P + CS / 2

    def at(self, t):
        """Az autó állapota t másodpercnél: x, y, szög, sor, fordul-e, füstöl-e, fázis."""
        time = t
        for r in range(7):
            if time < self.TS:
                k = time / self.TS
                d = 1 if r % 2 == 0 else -1
                slip, smoke = 0.0, False
                if r > 0 and time < 0.45:
                    u = time / 0.45
                    sign = 1 if (r - 1) % 2 == 0 else -1
                    slip = sign * 18 * math.exp(-4 * u) * math.cos(2 * math.pi * u)
                    smoke = time < 0.25
                x = self.xA + self.L * k if d > 0 else self.xB - self.L * k
                return dict(x=x, y=self.cy(r), a=(0 if d > 0 else 180) + slip, row=r,
                            turning=False, smoke=smoke, phase="run")
            time -= self.TS
            if r < 6:
                if time < TT:
                    u = time / TT
                    if r % 2 == 0:
                        cxx, th, heading, sg = self.xB, -90 + 180 * u, 180 * u, 1
                    else:
                        cxx, th, heading, sg = self.xA, -90 - 180 * u, 180 - 180 * u, -1
                    tr = math.radians(th)
                    return dict(x=cxx + R * math.cos(tr), y=self.cy(r) + R + R * math.sin(tr),
                                a=heading + sg * 40 * math.sin(math.pi * 0.85 * u), row=r,
                                turning=True, smoke=True, phase="run")
                time -= TT
        return dict(x=self.xB + SPEED * time, y=self.cy(6), a=0, row=7,
                    turning=False, smoke=False, phase="end")

    def pass_time(self, c, r):
        """Mikor halad át az autó a (c, r) cella közepén."""
        start = r * (self.TS + TT)
        k = (self.cx(c) - self.xA) / self.L
        if r % 2 == 1:
            k = 1 - k
        return start + k * self.TS


# ---------------------------------------------------------------- SVG
def f(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


def render(weeks, total, theme):
    th = THEMES[theme]
    cols = len(weeks)
    tr = Track(cols)
    T = tr.total
    W = X0 + cols * P + 60
    H = 280
    refill = (T - 0.7) / T
    out = []
    o = out.append

    o(f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" '
      f'role="img" aria-label="Contribution-gráf: {total} hozzájárulás az elmúlt évben">')
    o('<style>text{font-family:"JetBrains Mono",ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}'
      '@media (prefers-reduced-motion:reduce){.car,.fx{display:none}}</style>')
    o(f'<rect width="{W}" height="{H}" rx="10" fill="{th["bg"]}"/>')

    # fejléc + jelmagyarázat
    o(f'<text x="{X0}" y="38" font-size="12" letter-spacing="3.4" fill="{th["accent"]}">CONTRIBUTION DRIFT</text>')
    lx = W - 76 - 5 * 16 - 64
    o(f'<text x="{lx - 8}" y="38" font-size="11" fill="{th["muted"]}" text-anchor="end">Kevesebb</text>')
    for i, col in enumerate(th["levels"]):
        o(f'<rect x="{lx + i * 16}" y="28" width="12" height="12" rx="2" fill="{col}"/>')
    o(f'<text x="{lx + 5 * 16 + 4}" y="38" font-size="11" fill="{th["muted"]}">Több</text>')

    # hónapok és napok
    labels, last_m = [], None
    for c, col in enumerate(weeks):
        day = next((d for d in col if d), None)
        if not day:
            continue
        m = int(day[1][5:7])
        if m != last_m:
            labels.append((c, m))
            last_m = m
    if len(labels) > 1 and labels[1][0] - labels[0][0] < 3:
        labels.pop(0)  # a csonka első hónap neve ne lógjon rá a következőre
    for c, m in labels:
        if c <= cols - 3:
            o(f'<text x="{X0 + c * P}" y="74" font-size="11" fill="{th["muted"]}">{MONTHS_HU[m - 1]}</text>')
    for r, lbl in ((1, "H"), (3, "Sze"), (5, "P")):
        o(f'<text x="34" y="{f(tr.cy(r) + 4)}" font-size="11" fill="{th["muted"]}">{lbl}</text>')

    # cellák: a felszedettek az autó áthaladásakor kiürülnek, a kör végén visszatöltődnek
    for c, col in enumerate(weeks):
        for r, d in enumerate(col):
            if d is None:
                continue
            lvl = d[0]
            x, y = X0 + c * P, Y0 + r * P
            base = th["levels"][lvl]
            if lvl == 0:
                o(f'<rect x="{x}" y="{y}" width="{CS}" height="{CS}" rx="3" fill="{base}"/>')
                continue
            k = tr.pass_time(c, r) / T
            o(f'<rect x="{x}" y="{y}" width="{CS}" height="{CS}" rx="3" fill="{base}">'
              f'<animate attributeName="fill" values="{base};{th["levels"][0]};{base}" '
              f'keyTimes="0;{k:.4f};{refill:.4f}" dur="{f(T)}s" repeatCount="indefinite" calcMode="discrete"/>'
              f'</rect>')

    # keréknyomok és füst a fordulókban
    marks, puffs = [], []
    t = 0.0
    while t < T:
        s = tr.at(t)
        if s["smoke"]:
            rad = math.radians(s["a"])
            rx, ry = s["x"] - math.cos(rad) * 10, s["y"] - math.sin(rad) * 10
            puffs.append((t, rx, ry))
            if s["turning"]:
                px, py = -math.sin(rad) * 5, math.cos(rad) * 5
                marks += [(t, rx + px, ry + py), (t, rx - px, ry - py)]
        t += 0.05
    o('<g class="fx">')
    for t0, x, y in marks:
        k = t0 / T
        o(f'<rect x="{f(x - 1)}" y="{f(y - 1)}" width="2" height="2" fill="{th["mark"]}" opacity="0">'
          f'<animate attributeName="opacity" values="0;1;0" keyTimes="0;{k:.4f};0.995" dur="{f(T)}s" '
          f'repeatCount="indefinite" calcMode="discrete"/></rect>')
    life = 0.9 / T
    for t0, x, y in puffs:
        k0 = t0 / T
        k1 = min(k0 + life, 0.999)
        o(f'<circle cx="{f(x)}" cy="{f(y)}" r="3" fill="{th["puff"]}" opacity="0">'
          f'<animate attributeName="opacity" values="0;0;{th["puff_a"]};0;0" keyTimes="0;{k0:.4f};{k0 + 0.0005:.4f};{k1:.4f};1" '
          f'dur="{f(T)}s" repeatCount="indefinite"/>'
          f'<animate attributeName="r" values="3;3;12;12" keyTimes="0;{k0:.4f};{k1:.4f};1" '
          f'dur="{f(T)}s" repeatCount="indefinite"/></circle>')
    o('</g>')

    # az autó: mintavételezett pozíció + szög
    xs, angs, keys = [], [], []
    n = int(T * FPS)
    for i in range(n + 1):
        t = T * i / n
        s = tr.at(t)
        xs.append(f'{f(s["x"])},{f(s["y"])}')
        angs.append(f(s["a"]))
        keys.append(f"{i / n:.4f}")
    kt = ";".join(keys)
    o('<g class="car">')
    o(f'<animateTransform attributeName="transform" type="translate" values="{";".join(xs)}" '
      f'keyTimes="{kt}" dur="{f(T)}s" repeatCount="indefinite"/>')
    o('<g>')
    o(f'<animateTransform attributeName="transform" type="rotate" values="{";".join(angs)}" '
      f'keyTimes="{kt}" dur="{f(T)}s" repeatCount="indefinite"/>')
    o('<g transform="translate(-12,-7)">'
      f'<polygon points="24,5.3 76,-6 76,20 24,8.7" fill="#ffbe5a" opacity="{th["beam"]}"/>'
      '<rect x="4" y="-1" width="5" height="3" rx="1" fill="#0a0607"/>'
      '<rect x="4" y="12" width="5" height="3" rx="1" fill="#0a0607"/>'
      '<rect x="16" y="-1" width="5" height="3" rx="1" fill="#0a0607"/>'
      '<rect x="16" y="12" width="5" height="3" rx="1" fill="#0a0607"/>'
      '<rect x="0" y="1" width="24" height="12" rx="3.5" fill="#d01936"/>'
      '<rect x="4" y="3" width="4" height="8" rx="1" fill="#2a1218"/>'
      '<rect x="8" y="2.5" width="7" height="9" rx="1" fill="#b3142e"/>'
      '<rect x="15" y="2.5" width="4" height="9" rx="1" fill="#2a1218"/>'
      '<rect x="22" y="2" width="2" height="3" fill="#ffd27a"/>'
      '<rect x="22" y="9" width="2" height="3" fill="#ffd27a"/>'
      '<rect x="0" y="2" width="2" height="3" fill="#ff2a3d"/>'
      '<rect x="0" y="9" width="2" height="3" fill="#ff2a3d"/>'
      '</g></g></g>')

    o(f'<text x="{X0}" y="{H - 18}" font-size="11" fill="{th["muted"]}">{total} hozzájárulás az elmúlt évben</text>')
    o('</svg>')
    return "\n".join(out)


def main():
    args = sys.argv[1:]
    if len(args) != 2:
        raise SystemExit(__doc__)
    who, outdir = args
    if who == "--demo":
        weeks, total = demo()
    else:
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise SystemExit("Hiányzik a GITHUB_TOKEN környezeti változó.")
        weeks, total = fetch(who, token)
    os.makedirs(outdir, exist_ok=True)
    for theme in THEMES:
        path = os.path.join(outdir, f"drift-{theme}.svg")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(render(weeks, total, theme))
        print("kész:", path)


if __name__ == "__main__":
    main()

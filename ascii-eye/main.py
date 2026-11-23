"""ASCII-Auge -> Zoom in die Pupille -> Weltraum mit Planet.

Ein tkinter-Fenster, in dem jede Zelle ein farbiges ASCII-Zeichen ist.
Das Bild wird pro Frame prozedural mit numpy berechnet; auf dem Canvas
werden nur die Zeilen neu aufgebaut, in denen sich etwas geaendert hat.

Start:   pip install numpy
         python main.py

Tasten:  Leertaste / R = neu starten      Esc = beenden
"""

import math
import time
import tkinter as tk
from tkinter import font as tkfont

import numpy as np

# ----------------------------------------------------------------- Einstellungen
COLS, ROWS = 110, 44      # Raster in Zeichen
FONT_PX = 13              # Schrifthoehe in Pixeln
FPS = 30
LOOP = False              # True = nach dem Ende automatisch von vorn

# Zeichen von "dunkel" nach "hell"
RAMP = " .'`^\",:;Il!i><~+_-?][}{1)(|\\/tfjrxnuvczXYUJCLQ0OZmwqpdbkhao*#MW&8%B@$"

# ----------------------------------------------------------------- Zeitablauf (s)
T_REVEAL = 0.9            # Bild baut sich von oben nach unten auf
T_OPEN0, T_OPEN1 = 0.9, 2.6   # Auge oeffnet sich
T_ZOOM0, T_ZOOM1 = 4.0, 23.5  # Zoom in die Pupille
T_END = 30.0
LN_ZOOM = 2.8             # ln des Zoomfaktors bei T_ZOOM1 (~16x)

# ----------------------------------------------------------------- Szene
EYE_A = 1.22              # halbe Augenbreite (Bildhoehe = 2 Einheiten)
LID_UP, LID_LO = 0.36, 0.23   # Oeffnung nach oben / unten (klein = schmales "Hunter Eye")
LID_MID = 0.06            # Lidspalte liegt etwas unter der Pupillenmitte
TILT = 0.11               # Neigung: aeusserer Augenwinkel hoeher als der innere
LASH_UP, LASH_LO = 0.36, 0.14 # Wimpernlaenge oben / unten
BROW_Y, BROW_H, BROW_TILT = -0.76, 0.125, 0.07   # Augenbraue: Hoehe, halbe Dicke, Neigung
R_IRIS = 0.33
R_PUPIL = 0.11
R_PLANET = 0.0176
N_STARS = 380

SKIN = np.array([236.0, 130.0, 94.0])
SCLERA = np.array([250.0, 246.0, 240.0])
CORNER = np.array([232.0, 150.0, 140.0])
BROW = np.array([66.0, 34.0, 18.0])
IRIS_U = [0.00, 0.06, 0.22, 0.55, 0.86, 1.00]
IRIS_RGB = np.array([[40, 18, 6], [255, 214, 60], [250, 170, 30],
                     [226, 110, 18], [120, 52, 14], [38, 16, 8]], float)
MAGENTA = np.array([232.0, 36.0, 140.0])
PINK = np.array([255.0, 226.0, 240.0])


def smooth(u):
    u = np.clip(u, 0.0, 1.0)
    return u * u * (3.0 - 2.0 * u)


def ln_zoom(t):
    """Logarithmus des Zoomfaktors: langsam anfahren, am Ende weich auslaufen."""
    if t <= T_ZOOM0:
        return 0.0
    span = T_ZOOM1 - T_ZOOM0
    if t <= T_ZOOM1:
        u = (t - T_ZOOM0) / span
        return LN_ZOOM * u * u * (1.5 - 0.5 * u)
    speed = LN_ZOOM * 1.5 / span          # Geschwindigkeit bei T_ZOOM1
    tau = 1.5
    return LN_ZOOM + speed * tau * (1.0 - math.exp(-(t - T_ZOOM1) / tau))


class Scene:
    """Berechnet pro Frame Zeichen-Index und Farb-Index fuer jede Zelle."""

    def __init__(self, cols, rows, cw, ch):
        self.cols, self.rows = cols, rows
        w, h = cols * cw, rows * ch
        self.half_w = w / h
        sx = ((np.arange(cols) + 0.5) * cw - w / 2) / (h / 2)
        sy = ((np.arange(rows) + 0.5) * ch - h / 2) / (h / 2)
        self.SX, self.SY = np.meshgrid(sx, sy)
        self.unit_c = (h / 2) / cw        # Szenen-Einheit -> Spalten
        self.unit_r = (h / 2) / ch        # Szenen-Einheit -> Zeilen

        rng = np.random.default_rng(7)
        self.noise = rng.random((64, 64))
        self.reveal = np.arange(rows)[:, None] + rng.random((rows, cols)) * 5.0

        # Sterne: Position, Typ (0 klein, 1 mittel, 2 gross mit Strahlen), Farbe, Funkeln
        self.sx = rng.uniform(-self.half_w, self.half_w, N_STARS)
        self.sy = rng.uniform(-1.0, 1.0, N_STARS)
        self.skind = rng.choice(3, N_STARS, p=[0.62, 0.22, 0.16])
        tints = np.array([[255, 255, 255], [190, 212, 255], [255, 228, 186]], float)
        self.scol = tints[rng.choice(3, N_STARS, p=[0.6, 0.25, 0.15])]
        self.sfreq = rng.uniform(0.6, 2.2, N_STARS)
        self.sphase = rng.uniform(0, 6.283, N_STARS)
        self.sarm = rng.integers(2, 5, N_STARS)

        self.i_dot = RAMP.index(".")
        self.i_plus = RAMP.index("+")
        self.i_star = RAMP.index("*")
        self.i_dash = RAMP.index("-")
        self.i_bar = RAMP.index("|")

    def vnoise(self, x, y):
        """Weiches, kachelbares Rauschen (bilinear aus einer 64x64-Tabelle)."""
        xi = np.floor(x).astype(np.int64)
        yi = np.floor(y).astype(np.int64)
        fx, fy = x - xi, y - yi
        fx = fx * fx * (3 - 2 * fx)
        fy = fy * fy * (3 - 2 * fy)
        n = self.noise
        x0, x1, y0, y1 = xi & 63, (xi + 1) & 63, yi & 63, (yi + 1) & 63
        top = n[y0, x0] * (1 - fx) + n[y0, x1] * fx
        bot = n[y1, x0] * (1 - fx) + n[y1, x1] * fx
        return top * (1 - fy) + bot * fy

    def lashes(self, lx, d, spacing, width, lean0, lean1, length):
        """Wimpern als geschwungene Straehnen; d = Abstand zur Lidkante (>0 = ausserhalb)."""
        bend = d + 2.2 * d * d                       # weiter draussen staerker geneigt
        root = lx - (lean0 + lean1 * lx / EYE_A) * bend      # wo die Wimper am Lid sitzt
        n = root / spacing
        i = np.floor(n)
        k = root / EYE_A
        rnd = self.noise[i.astype(np.int64) & 63, 11]        # jede Wimper etwas anders
        full = length(k) * (0.75 + 0.5 * rnd) * np.clip(1.0 - k * k, 0.0, 1.0) ** 0.2
        rel = np.clip(d / np.maximum(full, 1e-6), 0.0, 1.0)  # 0 = Wurzel, 1 = Spitze
        thick = 0.5 * width * (1.0 - rel ** 2) ** 0.8        # laeuft erst am Ende spitz zu
        return smooth((thick - np.abs(n - i - 0.5)) / 0.03 + 0.5) * (d > 0) * (rel < 1.0)

    @staticmethod
    def quant(rgb):
        """RGB (0..255) -> 12-Bit-Farbindex (4 Bit pro Kanal)."""
        v = np.clip(rgb, 0, 255).astype(np.uint16) >> 4
        return (v[..., 0] << 8) | (v[..., 1] << 4) | v[..., 2]

    def render(self, t):
        lz = ln_zoom(t)
        zoom = math.exp(lz)
        calm = (1.0 - min(lz / LN_ZOOM, 1.0)) ** 2   # Augenbewegung klingt beim Zoom ab
        x, y = self.SX / zoom, self.SY / zoom
        r = np.hypot(x, y)

        # --- Lider (leicht gegen die Iris verschoben = Blickbewegung)
        lx = x + 0.035 * math.sin(0.9 * t) * calm
        ly = y + 0.012 * math.sin(1.4 * t + 1.0) * calm
        opened = float(smooth((t - T_OPEN0) / (T_OPEN1 - T_OPEN0)))
        kx = lx / EYE_A                              # -1 innerer .. +1 aeusserer Augenwinkel
        f = np.clip(1.0 - kx ** 2, 0.0, 1.0)
        mid = LID_MID - TILT * lx                    # aeusserer Winkel sitzt hoeher
        up = mid - LID_UP * (1.0 - 0.15 * kx) * f ** 0.6 * opened
        lo = mid + LID_LO * f ** 0.9 * opened
        eye = (ly > up) & (ly < lo) & (f > 0)
        du, dl = up - ly, ly - lo                    # Abstand ueber / unter dem Lid

        # --- Haut
        shade = 0.80 + 0.20 * self.vnoise(lx * 3 + 7, ly * 3 + 3)
        shade += 0.10 * (self.vnoise(lx * 14, ly * 14) - 0.5)
        edge = smooth(f / 0.12)
        above = du > 0
        shade *= 1.0 - 0.16 * f * np.exp(-np.maximum(du, 0) / 0.30) * above          # tiefliegendes Auge
        shade *= 1.0 - 0.95 * edge * np.exp(-np.maximum(du, 0) / 0.022) * above      # Wimpernkranz
        shade *= 1.0 - 0.60 * edge * np.exp(-np.maximum(dl, 0) / 0.020) * (dl >= 0)
        shade *= 1.0 - 0.22 * f * np.exp(-((du - 0.08 * f - 0.03) / 0.03) ** 2)      # Schlupflid-Falte
        grow = 0.3 + 0.7 * opened
        shade *= 1.0 - 0.97 * self.lashes(lx, du, 0.150, 0.50, 0.12, 0.68,
                                          lambda k: (LASH_UP + 0.5 * LASH_UP * k) * grow)
        shade *= 1.0 - 0.85 * self.lashes(lx, dl, 0.170, 0.36, 0.10, 0.60,
                                          lambda k: LASH_LO * smooth((k + 0.75) / 0.5) * grow)
        col = SKIN * shade[..., None]

        # --- Augenbraue: tief, gerade, zum aeusseren Ende hin duenner
        hair = self.vnoise((lx - 0.9 * ly) * 42, (0.9 * lx + ly) * 7)
        half = BROW_H * smooth((lx + 1.30) / 0.25) * (1.0 - 0.6 * smooth((lx - 0.2) / 1.0))
        brow = smooth((half * (0.65 + 0.6 * hair) - np.abs(ly - (BROW_Y - BROW_TILT * lx))) / 0.03)
        brow = (brow * (0.80 + 0.20 * hair))[..., None]
        col = col * (1.0 - brow) + BROW * (0.5 + 1.0 * hair)[..., None] * brow

        # --- Augenweiss
        lid_shadow = 1.0 - 0.45 * np.exp(-np.maximum(ly - up, 0) / 0.05)
        k = np.abs(lx) / EYE_A
        white = (1.0 - 0.32 * k ** 2.2) * lid_shadow * (1.0 - 0.25 * np.exp(-np.maximum(lo - ly, 0) / 0.05))
        mixc = (k ** 4)[..., None]
        sclera = (SCLERA * (1 - mixc) + CORNER * mixc) * white[..., None]
        col = np.where(eye[..., None], sclera, col)

        # --- Iris
        rp = R_PUPIL * (1.0 + 0.05 * math.sin(1.1 * t) * calm)
        u = np.clip((r - rp) / (R_IRIS - rp), 0.0, 1.0)
        ang = np.arctan2(y, x) / (2 * math.pi)
        fib = 0.6 * self.vnoise(ang * 64, r * 9) + 0.4 * self.vnoise(ang * 128 + 5, r * 5)
        iris = np.stack([np.interp(u, IRIS_U, IRIS_RGB[:, i]) for i in range(3)], -1)
        iris *= ((0.60 + 0.80 * fib) * lid_shadow)[..., None]
        in_iris = eye & (r < R_IRIS)
        col = np.where(in_iris[..., None], iris, col)

        # --- Pupille = Fenster in den Weltraum
        pupil = eye & (r < rp)
        col[pupil] = 0.0

        # --- Planet
        vis = float(smooth((zoom - 1.8) / 1.5))
        if vis > 0:
            d = r / R_PLANET
            nx, ny = x / R_PLANET, y / R_PLANET
            nz = np.sqrt(np.clip(1.0 - d * d, 0.0, 1.0))
            lam = np.clip(-0.30 * nx - 0.35 * ny + 0.89 * nz, 0.0, 1.0)
            band = 0.5 + 0.5 * np.sin(ny * 7 + 1.2 * np.sin(nx * 2.5 + t * 0.35) + t * 0.1)
            mixp = np.clip(0.75 * band * lam + 0.55 * lam ** 2, 0, 1)[..., None]
            planet = (MAGENTA * (1 - mixp) + PINK * mixp) * (0.22 + 0.95 * lam)[..., None]
            glow = MAGENTA * (0.55 * np.exp(-np.maximum(d - 1.0, 0) / 0.18))[..., None]
            body = np.where((d < 1.0)[..., None], planet, glow) * vis
            col = np.where(pupil[..., None], body, col)

        # --- Lichtreflex auf der Hornhaut (verschwindet beim Zoom)
        hl = np.exp(-(((x - 0.085) / 0.05) ** 2 + ((y + 0.075) / 0.04) ** 2))
        hl *= 1.0 - float(smooth((zoom - 3.0) / 3.0))
        col += (255.0 * hl * eye)[..., None]

        # --- Helligkeit -> Zeichen, Farbe -> Farbindex
        col = np.clip(col, 0.0, 255.0)
        lum = (col @ np.array([0.299, 0.587, 0.114])) / 255.0
        idx = (lum ** 0.85 * (len(RAMP) - 1) + 0.5).astype(np.uint8)
        idx[lum < 0.035] = 0
        q = self.quant(270.0 * (col / 255.0) ** 0.6)

        self.stars(t, zoom, idx, q, pupil & (idx == 0))

        if t < T_REVEAL + 0.3:                       # Aufbau von oben nach unten
            idx[self.reveal > t / T_REVEAL * (self.rows + 5)] = 0
        return idx, q

    def stars(self, t, zoom, idx, q, space):
        """Sterne in alle freien Zellen der Pupille stempeln."""
        fade = float(smooth((zoom - 1.4) / 1.2))     # anfangs ist die Pupille einfach schwarz
        if fade == 0.0 or not space.any():
            return
        spread = zoom ** 0.22                        # Sterne driften langsam nach aussen
        c = np.floor((self.sx * spread + self.half_w) * self.unit_c).astype(np.int64)
        r = np.floor((self.sy * spread + 1.0) * self.unit_r).astype(np.int64)
        tw = 0.62 + 0.38 * np.sin(t * self.sfreq + self.sphase)
        level = np.round(tw * 3) / 3 * fade          # grob gestuft -> wenige Updates

        def stamp(sel, dr, dc, char_idx, gain):
            rr, cc = r[sel] + dr, c[sel] + dc
            ok = (rr >= 0) & (rr < self.rows) & (cc >= 0) & (cc < self.cols)
            rr, cc = rr[ok], cc[ok]
            free = space[rr, cc]
            rr, cc = rr[free], cc[free]
            idx[rr, cc] = char_idx
            q[rr, cc] = self.quant(self.scol[sel][ok][free] * (level[sel][ok][free] * gain)[:, None])

        small, medium, big = self.skind == 0, self.skind == 1, self.skind == 2
        stamp(small, 0, 0, self.i_dot, 0.9)
        stamp(medium & (tw < 0.6), 0, 0, self.i_dot, 1.2)
        stamp(medium & (tw >= 0.6), 0, 0, self.i_plus, 1.0)
        arm = np.round(self.sarm * level).astype(np.int64)
        for k in range(1, 5):
            reach = big & (arm >= k)
            fade = 1.0 - 0.18 * k
            stamp(reach, 0, k, self.i_dash, fade)
            stamp(reach, 0, -k, self.i_dash, fade)
            if k <= 2:
                tall = big & (arm >= 2 * k)
                stamp(tall, k, 0, self.i_bar, fade)
                stamp(tall, -k, 0, self.i_bar, fade)
        stamp(big & (tw >= 0.6), 0, 0, self.i_star, 1.3)
        stamp(big & (tw < 0.6), 0, 0, self.i_plus, 1.3)


def pick_font(root):
    have = set(tkfont.families(root))
    for name in ("Consolas", "Cascadia Mono", "Menlo", "DejaVu Sans Mono",
                 "Liberation Mono", "Courier New"):
        if name in have:
            return tkfont.Font(root=root, family=name, size=-FONT_PX, weight="bold")
    return tkfont.Font(root=root, family="Courier", size=-FONT_PX, weight="bold")


def main():
    root = tk.Tk()
    root.title("ASCII Eye")
    root.resizable(False, False)
    fnt = pick_font(root)
    CW = fnt.measure("M" * 100) / 100.0              # Zeichenbreite (kann gebrochen sein)
    CH = fnt.metrics("linespace") + 1
    cv = tk.Canvas(root, width=round(COLS * CW), height=ROWS * CH, bg="black", highlightthickness=0)
    cv.pack()

    scene = Scene(COLS, ROWS, CW, CH)
    palette = ["#%x%x%x%x%x%x" % (r, r, g, g, b, b)
               for r in range(16) for g in range(16) for b in range(16)]
    ramp = np.frombuffer(RAMP.encode("ascii"), np.uint8)
    col_no = np.arange(COLS)
    # Pro Zeile ein Vorrat an Text-Items: jedes zeigt einen gleichfarbigen Abschnitt.
    items = [[] for _ in range(ROWS)]
    shown = [[] for _ in range(ROWS)]                # was jedes Item gerade anzeigt
    d_idx = np.zeros((ROWS, COLS), np.uint8)         # was gerade auf dem Canvas steht
    d_q = np.zeros((ROWS, COLS), np.uint16)
    st = {"t0": time.perf_counter()}
    configure, widget = cv.tk.call, cv._w            # direkter Tcl-Aufruf, schneller als itemconfig

    def restart(_event=None):
        st["t0"] = time.perf_counter()

    def draw_row(r_, line, qrow):
        """Zeile in Abschnitte gleicher Farbe zerlegen und auf die Items verteilen."""
        cuts = (np.flatnonzero(qrow[1:] != qrow[:-1]) + 1).tolist()
        row_items, row_shown = items[r_], shown[r_]
        y = (r_ + 0.5) * CH
        k = 0
        for s, e in zip([0] + cuts, cuts + [COLS]):
            seg = line[s:e]
            if seg.isspace():
                continue
            new = (s, seg, palette[qrow[s]])
            if k == len(row_items):
                row_items.append(cv.create_text(s * CW, y, text=seg, fill=new[2],
                                                font=fnt, anchor="w"))
                row_shown.append(new)
            elif row_shown[k] != new:
                old = row_shown[k]
                if old is None or old[0] != s:
                    configure(widget, "coords", row_items[k], s * CW, y)
                configure(widget, "itemconfigure", row_items[k], "-text", seg, "-fill", new[2])
                row_shown[k] = new
            k += 1
        for k in range(k, len(row_items)):           # uebrige Items leeren
            if row_shown[k] is not None:
                configure(widget, "itemconfigure", row_items[k], "-text", "")
                row_shown[k] = None

    def tick():
        start = time.perf_counter()
        t = start - st["t0"]
        if LOOP and t > T_END + 2.0:
            restart()
            t = 0.0
        idx, q = scene.render(t)

        # Leerzeichen uebernehmen die Farbe ihres linken Nachbarn -> laengere Abschnitte
        src = np.maximum.accumulate(np.where(idx != 0, col_no, 0), axis=1)
        q = np.take_along_axis(q, src, axis=1)

        # nur Zeilen neu aufbauen, in denen sich etwas geaendert hat
        dirty = np.flatnonzero(((idx != d_idx) | (q != d_q)).any(axis=1)).tolist()
        if dirty:
            text = ramp[idx].tobytes().decode("ascii")
            for r_ in dirty:
                draw_row(r_, text[r_ * COLS:(r_ + 1) * COLS], q[r_])
            d_idx[dirty] = idx[dirty]
            d_q[dirty] = q[dirty]

        root.update_idletasks()                      # jetzt zeichnen, damit die Zeitmessung stimmt
        wait = 1.0 / FPS - (time.perf_counter() - start)
        root.after(max(1, int(wait * 1000)), tick)

    root.bind("<space>", restart)
    root.bind("r", restart)
    root.bind("<Escape>", lambda _e: root.destroy())
    root.after(100, tick)
    root.mainloop()


if __name__ == "__main__":
    main()

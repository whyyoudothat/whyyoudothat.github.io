"""Zeichen-Auge -> Zoom in die Pupille -> Weltraum mit Ringplanet.

Jede Zelle des Bildes ist eine Ziffer oder ein Sonderzeichen, das staendig
flackert. Das Bild wird pro Frame mit numpy berechnet, aus vorgerenderten
Zeichen-Bitmaps zusammengesetzt und als Ganzes ins tkinter-Fenster kopiert.

Start:   Windows: Doppelklick auf start.bat (installiert alles und startet)
         sonst:   python -m pip install numpy pillow
                  python main.py

Tasten:  Leertaste / R = neu starten      Esc = beenden
"""

import math
import time
import tkinter as tk

try:
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk
except ImportError:                                  # verstaendliche Meldung statt Sofort-Absturz
    from tkinter import messagebox
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror("Pakete fehlen", "numpy und/oder pillow sind nicht installiert.\n\n"
                         "Starte die Datei start.bat oder fuehre im Terminal aus:\n\n"
                         "    python -m pip install numpy pillow")
    raise SystemExit(1)

# ----------------------------------------------------------------- Einstellungen
COLS, ROWS = 116, 46      # Raster in Zeichen
CELL_W, CELL_H = 8, 15    # Zellengroesse in Pixeln (Fenster = COLS*CELL_W x ROWS*CELL_H)
FPS = 60
LOOP = False              # True = nach dem Ende automatisch von vorn

# Zeichenvorrat: nur Ziffern und Sonderzeichen, keine Buchstaben
CHARS = "0123456789.,:;!?-_+=*/\\|()[]{}<>#%&$@^~'\""
LEVELS = 22               # Helligkeitsstufen
VARIANTS = 6              # aehnlich helle Zeichen pro Stufe, zwischen denen es flackert
FLUTTER = 5.0             # wie oft pro Sekunde eine Zelle ihr Zeichen wechselt
GLOW = 0.20               # Hintergrundleuchten der Zellen (0 = aus)
SCANLINES = 0.82          # Helligkeit jeder zweiten Pixelzeile (1 = aus)
FRINGE = 0.55             # Staerke des Farbsaums um die Zeichen (0 = aus)

# ----------------------------------------------------------------- Zeitablauf (s)
T_RAIN = 1.3              # Zeichenregen legt das Bild frei
T_OPEN0, T_OPEN1 = 1.5, 2.9   # Auge oeffnet sich
T_BLINK = 3.7             # kurzes Blinzeln
T_ZOOM0, T_ZOOM1 = 4.3, 23.0  # Zoom in die Pupille
T_END = 31.0
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
R_PLANET = 0.0150
N_STARS = 300

SKIN = np.array([236.0, 130.0, 94.0])
BROW = np.array([66.0, 34.0, 18.0])
SCLERA = np.array([250.0, 246.0, 240.0])
CORNER = np.array([232.0, 150.0, 140.0])
IRIS_U = [0.00, 0.06, 0.22, 0.55, 0.86, 1.00]
IRIS_RGB = np.array([[40, 18, 6], [255, 224, 80], [255, 176, 30],
                     [232, 108, 16], [120, 50, 14], [38, 16, 8]], float)
CYAN = np.array([90.0, 225.0, 255.0])
MAGENTA = np.array([232.0, 36.0, 140.0])
PINK = np.array([255.0, 226.0, 240.0])
RING = np.array([255.0, 214.0, 170.0])
MOON = np.array([190.0, 235.0, 255.0])
VIOLET = np.array([150.0, 60.0, 255.0])
TEAL = np.array([20.0, 170.0, 190.0])
RAIN = np.array([170.0, 255.0, 225.0])
LUMA = np.array([0.299, 0.587, 0.114])


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


class Glyphs:
    """Vorgerenderte Zeichen-Bitmaps, nach Helligkeit in Stufen sortiert."""

    def __init__(self, cw, ch):
        self.cw, self.ch = cw, ch
        font = self.load_font(cw, ch)
        chars = " " + CHARS
        self.ids = {c: i for i, c in enumerate(chars)}
        atlas = np.zeros((len(chars), ch, cw), np.float64)
        for i, c in enumerate(chars):
            img = Image.new("L", (cw, ch), 0)
            try:
                ImageDraw.Draw(img).text((cw / 2, ch / 2), c, fill=255, font=font, anchor="mm")
            except (ValueError, TypeError):          # Ersatzschrift ohne Anker
                ImageDraw.Draw(img).text((0, 0), c, fill=255, font=font)
            atlas[i] = np.asarray(img)

        # Stufen: zu jeder Zielhelligkeit die VARIANTS aehnlichsten Zeichen
        cover = atlas.mean(axis=(1, 2))
        cover = cover / cover.max()
        self.table = np.zeros((LEVELS, VARIANTS), np.int16)
        for lv in range(1, LEVELS):
            near = np.argsort(np.abs(cover[1:] - lv / (LEVELS - 1)))[:VARIANTS] + 1
            self.table[lv] = near

        # Alles, was pro Pixel gleich bleibt, wird gleich mit eingebacken:
        atlas = 255.0 * (atlas / 255.0) ** 0.45      # duenne Striche kraeftiger machen
        atlas[:, 1::2, :] *= SCANLINES               # Scanlines
        rgb = np.stack([np.maximum(atlas, FRINGE * np.roll(atlas, 1, axis=2)), atlas,    # Farbsaum: rot
                        np.maximum(atlas, FRINGE * np.roll(atlas, -1, axis=2))], axis=-1)  # rechts, blau links
        lit = np.maximum(rgb, 255.0 * GLOW)          # Hintergrundleuchten der Zelle
        self.plain = len(chars)                      # ab hier: dieselben Zeichen ohne Leuchten
        self.atlas = np.concatenate([lit, rgb]).astype(np.uint8)

    @staticmethod
    def load_font(cw, ch):
        names = ("consolab.ttf", "consola.ttf", "CascadiaMono.ttf", "lucon.ttf", "courbd.ttf",
                 "DejaVuSansMono-Bold.ttf", "LiberationMono-Bold.ttf", "Menlo.ttc")
        for name in names:
            for size in range(ch + 2, 5, -1):        # groesste Schrift, die in die Zelle passt
                try:
                    font = ImageFont.truetype(name, size)
                except OSError:
                    break
                if font.getlength("0") <= cw + 0.6:
                    return font
        return ImageFont.load_default()

    def compose(self, glyph, col):
        """Zeichen-Bitmaps x Zellenfarbe -> fertiges Bild."""
        rows, cols = glyph.shape
        size = (cols * self.cw, rows * self.ch)
        mask = self.atlas[glyph].transpose(0, 2, 1, 3, 4).reshape(size[1], size[0], 3)
        mask = Image.frombuffer("RGB", size, mask, "raw", "RGB", 0, 1)
        tint = Image.frombuffer("RGB", (cols, rows), col, "raw", "RGB", 0, 1).resize(size, Image.NEAREST)
        return ImageChops.multiply(mask, tint)


class Scene:
    """Berechnet pro Frame Helligkeitsstufe, Farbe und Sonderzeichen jeder Zelle."""

    def __init__(self, cols, rows, cw, ch, ids):
        self.cols, self.rows = cols, rows
        w, h = cols * cw, rows * ch
        self.half_w = w / h
        sx = ((np.arange(cols) + 0.5) * cw - w / 2) / (h / 2)
        sy = ((np.arange(rows) + 0.5) * ch - h / 2) / (h / 2)
        self.SX, self.SY = np.meshgrid(sx.astype(np.float32), sy.astype(np.float32))   # float32 = schneller
        self.SR = np.hypot(self.SX, self.SY)
        self.sr_max = float(self.SR.max())
        self.unit_c = (h / 2) / cw        # Szenen-Einheit -> Spalten
        self.unit_r = (h / 2) / ch        # Szenen-Einheit -> Zeilen
        self.row_no = np.arange(rows)[:, None]

        rng = np.random.default_rng(7)
        self.rng = rng
        self.noise = rng.random((64, 64)).astype(np.float32)
        self.spark = np.zeros((rows, cols), np.float32)
        self.rain_delay = rng.uniform(0.0, 0.35, cols)
        self.rain_speed = rows / rng.uniform(0.55, 0.9, cols)

        # Sterne fliegen beim Zoom strahlenfoermig aus der Mitte heraus
        ang = rng.uniform(0, 2 * math.pi, N_STARS)
        self.s_cos, self.s_sin = np.cos(ang), np.sin(ang)
        self.s_rho = rng.random(N_STARS)
        self.s_rate = rng.uniform(0.25, 1.5, N_STARS)
        self.s_kind = rng.choice(3, N_STARS, p=[0.58, 0.24, 0.18])   # klein, mittel, gross
        tints = np.array([[255, 255, 255], [180, 215, 255], [255, 226, 180], [255, 170, 230]], float)
        self.s_col = tints[rng.choice(4, N_STARS, p=[0.5, 0.25, 0.15, 0.10])]
        self.s_freq = rng.uniform(0.8, 3.0, N_STARS)
        self.s_phase = rng.uniform(0, 6.283, N_STARS)
        self.s_arm = rng.integers(2, 5, N_STARS)
        sector = np.round((ang % math.pi) / (math.pi / 4)).astype(int) % 4
        self.s_streak = np.array([ids["-"], ids["\\"], ids["|"], ids["/"]])[sector]

        self.g_dot, self.g_plus, self.g_star = ids["."], ids["+"], ids["*"]
        self.g_dash, self.g_bar = ids["-"], ids["|"]
        self.g_slash, self.g_back = ids["/"], ids["\\"]

        # Zeitpunkt, an dem die Pupille das ganze Bild fuellt (Schockwelle, Stoerung)
        self.t_cross = next(t / 50 for t in range(int(T_END * 50))
                            if R_PUPIL * math.exp(ln_zoom(t / 50)) > 1.25)
        self.glitches = [(T_OPEN0 + 0.2, 0.9, 0.16), (7.4, 0.45, 0.09), (12.2, 0.55, 0.09),
                         (16.8, 0.5, 0.09), (self.t_cross, 1.0, 0.22),
                         (self.t_cross + 4.1, 0.4, 0.08), (self.t_cross + 7.6, 0.5, 0.09)]

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

    def glitch(self, t):
        return max(amp * math.exp(-((t - t0) / width) ** 2) for t0, amp, width in self.glitches)

    def render(self, t, dt):
        lz = ln_zoom(t)
        zoom = math.exp(lz)
        zspeed = (ln_zoom(t + 0.05) - ln_zoom(t - 0.05)) / 0.1
        calm = (1.0 - min(lz / LN_ZOOM, 1.0)) ** 2   # Augenbewegung klingt beim Zoom ab
        x, y = self.SX / zoom, self.SY / zoom
        r = np.hypot(x, y)
        glitch = self.glitch(t)
        jitter = np.full((self.rows, self.cols), 0.6 * glitch)   # zusaetzliches Zeichen-Flackern

        # --- Auge; faellt weg, sobald die Pupille das ganze Bild fuellt
        if R_PUPIL * zoom * 0.88 > self.sr_max:
            col = np.zeros((self.rows, self.cols, 3))
            pupil = np.ones((self.rows, self.cols), bool)
        else:
            col, pupil = self.eye(t, x, y, r, zoom, calm)

        # --- Pupille = Fenster in den Weltraum
        solid = np.zeros_like(pupil)                 # Zellen, die Planet/Ring/Mond bedecken
        vis = float(smooth((zoom - 1.8) / 1.5))
        if vis > 0:
            body, solid = self.space(t, x, y, r, zoom)
            col = np.where(pupil[..., None], body * vis, col)

        # --- Schockwelle und Blitz beim Durchflug durch die Pupille
        tw = t - self.t_cross
        if 0.0 < tw < 1.2:
            ring = np.exp(-((self.SR - 2.3 * tw) / 0.09) ** 2) * (1.0 - tw / 1.2)
            col += CYAN * (1.6 * ring)[..., None]
            col *= 1.0 + 1.2 * math.exp(-tw / 0.12)
            jitter += ring

        # --- Funken: einzelne Zellen blitzen kurz weiss auf
        self.spark *= math.exp(-dt / 0.10)
        self.spark[self.rng.random(self.spark.shape) < 0.03 * dt] = 1.0
        lit = (self.spark * (col.sum(-1) > 60))[..., None]
        col += (255.0 - col) * 0.85 * lit

        # --- Vignette
        col *= (1.0 - 0.30 * np.clip(self.SR / 1.6, 0, 1) ** 2.5)[..., None]

        # --- Helligkeit -> Stufe, Farbe aufhellen
        col = np.clip(col, 0.0, 255.0)
        lum = (col @ LUMA) / 255.0
        level = (lum ** 0.70 * (LEVELS - 1) + 0.5).astype(np.int64)
        level[lum < 0.035] = 0
        col = np.minimum(270.0 * (col / 255.0) ** 0.6, 255.0)
        over = np.full((self.rows, self.cols), -1, np.int16)     # feste Zeichen (Sterne usw.)

        fade = float(smooth((zoom - 1.4) / 1.2))     # anfangs ist die Pupille einfach schwarz
        space = pupil & ~solid
        if fade > 0.0 and space.any():
            self.stars(t, lz, zspeed, fade, space, over, col)
            self.meteor(t, space, over, col)

        # --- Zeichenregen: faellt von oben und legt das Bild frei
        if t < T_RAIN + 0.5:
            behind = (t - self.rain_delay) * self.rain_speed - self.row_no   # >0: Kopf schon vorbei
            hidden = behind < 0
            trail = np.clip(1.0 - behind / 9.0, 0.0, 1.0) * ~hidden
            col = col * (1.0 - trail[..., None]) + RAIN * trail[..., None]
            level = np.maximum(level, (trail * (LEVELS - 1)).astype(np.int64))
            level[hidden] = 0
            col[hidden] = 0.0
            jitter += trail

        return level, col.astype(np.uint8), over, jitter, glitch

    def eye(self, t, x, y, r, zoom, calm):
        """Haut, Wimpern, Braue, Augenweiss und Iris; liefert Farbe und Pupillen-Maske."""
        # --- Lider (leicht gegen die Iris verschoben = Blickbewegung)
        lx = x + 0.035 * math.sin(0.9 * t) * calm
        ly = y + 0.012 * math.sin(1.4 * t + 1.0) * calm
        opened = float(smooth((t - T_OPEN0) / (T_OPEN1 - T_OPEN0)))
        opened *= 1.0 - 0.93 * math.exp(-((t - T_BLINK) / 0.10) ** 2)    # Blinzeln
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

        # --- Zielring um die Iris: zwei rotierende Bogenstuecke
        ang = np.arctan2(y, x) / (2 * math.pi)
        arc = np.exp(-((r - 1.14 * R_IRIS) / 0.026) ** 2) * (np.sin((ang * 3 + 0.11 * t) * 2 * math.pi) > 0.2)
        arc += np.exp(-((r - 1.36 * R_IRIS) / 0.018) ** 2) * (np.sin((ang * 5 - 0.07 * t) * 2 * math.pi) > 0.55)
        arc = (arc * eye * float(smooth((t - T_OPEN1) / 0.6)))[..., None]
        col = col * (1.0 - 0.85 * arc) + CYAN * arc

        # --- Iris: langsam drehende Fasern, nach aussen laufende Wellen, pulsierende Pupille
        beat = math.exp(-((t * 1.15) % 1.0) * 6.0)
        rp = R_PUPIL * (1.0 + (0.05 * math.sin(1.1 * t) + 0.07 * beat) * calm)
        u = np.clip((r - rp) / (R_IRIS - rp), 0.0, 1.0)
        spin = ang + 0.006 * t
        fib = 0.6 * self.vnoise(spin * 64, r * 9) + 0.4 * self.vnoise(spin * 128 + 5, r * 5)
        iris = np.stack([np.interp(u, IRIS_U, IRIS_RGB[:, i]) for i in range(3)], -1)
        wave = 1.0 + 0.30 * np.sin(u * 20.0 - t * 5.0) * np.exp(-u * 1.6)
        ember = 1.0 + 0.25 * (self.vnoise(spin * 64 + 9, t * 2.5 + r * 3) - 0.5)
        iris *= ((0.60 + 0.80 * fib) * wave * ember * lid_shadow)[..., None]
        in_iris = eye & (r < R_IRIS)
        col = np.where(in_iris[..., None], iris, col)

        # --- Lichtreflex auf der Hornhaut (verschwindet beim Zoom)
        hl = np.exp(-(((x - 0.085) / 0.05) ** 2 + ((y + 0.075) / 0.04) ** 2))
        hl *= 1.0 - float(smooth((zoom - 3.0) / 3.0))
        col += (255.0 * hl * eye)[..., None]

        pupil = eye & (r < rp)
        col[pupil] = 0.0
        return col, pupil

    def space(self, t, x, y, r, zoom):
        """Nebel, Ringplanet und Mond hinter der Pupille."""
        # Nebel bewegt sich nur wenig mit dem Zoom (weit weg)
        far = zoom ** 0.18
        nx_, ny_ = self.SX / far, self.SY / far
        n1 = self.vnoise(nx_ * 2.3 + 11 + 0.02 * t, ny_ * 2.3 + 5)
        n2 = self.vnoise(nx_ * 5.1 + 3, ny_ * 5.1 + 9 - 0.03 * t)
        n3 = self.vnoise(nx_ * 1.4 + 40, ny_ * 1.4 + 23)
        cloud = smooth((0.6 * n1 + 0.4 * n2 - 0.42) / 0.40)
        body = (VIOLET * (cloud * n3)[..., None] + TEAL * (cloud * (1 - n3))[..., None]) * 0.42

        # Planet mit rotierenden Baendern
        d = r / R_PLANET
        nx, ny = x / R_PLANET, y / R_PLANET
        nz = np.sqrt(np.clip(1.0 - d * d, 0.0, 1.0))
        lam = np.clip(-0.30 * nx - 0.35 * ny + 0.89 * nz, 0.0, 1.0)
        lon = np.arctan2(nx, nz + 1e-6) + 0.45 * t
        band = 0.5 + 0.5 * np.sin(ny * 8 + 1.1 * np.sin(lon * 3) + 0.6 * np.sin(lon * 7 + ny * 4))
        mixp = np.clip(0.75 * band * lam + 0.55 * lam ** 2, 0, 1)[..., None]
        planet = (MAGENTA * (1 - mixp) + PINK * mixp) * (0.22 + 0.95 * lam)[..., None]
        pulse = 0.55 + 0.15 * math.sin(2.2 * t)
        glow = MAGENTA * (pulse * np.exp(-np.maximum(d - 1.0, 0) / 0.20))[..., None]
        disc = d < 1.0
        body = np.where(disc[..., None], planet, body + glow)

        # Ring: schraege, flache Ellipse; vorn vor dem Planeten, hinten dahinter
        ca, sa = math.cos(-0.35), math.sin(-0.35)
        rx, ry = nx * ca + ny * sa, (-nx * sa + ny * ca) / 0.30
        rr = np.hypot(rx, ry)
        in_ring = (rr > 1.50) & (rr < 2.35) & ~((rr > 1.90) & (rr < 2.02)) & ((ry > 0) | ~disc)
        ring = RING * (0.80 + 0.20 * np.sin(rr * 26.0))[..., None]
        body = np.where(in_ring[..., None], ring, body)

        # Mond auf einer Umlaufbahn
        phase = 0.7 * t
        mx, my = 3.3 * math.cos(phase) * ca - 0.9 * math.sin(phase) * sa, 3.3 * math.cos(phase) * sa + 0.9 * math.sin(phase) * ca
        dm = np.hypot(nx - mx, ny - my) / 0.22
        in_moon = (dm < 1.0) & ((math.sin(phase) > 0) | ~disc)
        moon = MOON * (0.35 + 0.65 * np.clip(1.0 - dm * dm, 0, 1) ** 0.5)[..., None]
        body = np.where(in_moon[..., None], moon, body)
        return body, disc | in_ring | in_moon

    def put(self, rr, cc, colors, glyph, space, over, col):
        """Feste Zeichen in freie Weltraum-Zellen schreiben."""
        glyph = np.broadcast_to(glyph, rr.shape)
        ok = (rr >= 0) & (rr < self.rows) & (cc >= 0) & (cc < self.cols)
        rr, cc, colors, glyph = rr[ok], cc[ok], colors[ok], glyph[ok]
        free = space[rr, cc]
        rr, cc = rr[free], cc[free]
        over[rr, cc] = glyph[free]
        col[rr, cc] = np.clip(colors[free], 0, 255)

    def cell(self, px, py):
        c = np.floor((px + self.half_w) * self.unit_c).astype(np.int64)
        r = np.floor((py + 1.0) * self.unit_r).astype(np.int64)
        return r, c

    def stars(self, t, lz, zspeed, fade, space, over, col):
        """Sterne: funkeln im Stand, werden beim Zoom zu Lichtstreifen."""
        rho = (self.s_rho + self.s_rate * lz * 0.45 + 0.004 * t) % 1.0
        rad = 0.04 + 1.85 * rho ** 1.3
        tw = 0.62 + 0.38 * np.sin(t * self.s_freq + self.s_phase)
        bright = tw * smooth(rho / 0.12) * smooth((1.0 - rho) / 0.05) * fade
        tint = self.s_col * bright[:, None]
        r, c = self.cell(self.s_cos * rad, self.s_sin * rad)
        streak = np.clip(zspeed * self.s_rate * 26.0, 0.0, 7.0)          # Laenge in Zellen
        fast = streak >= 1.0
        slow = ~fast

        for j in range(7, 0, -1):                    # Schweif zeigt zur Mitte
            sel = fast & (streak >= j)
            rj, cj = self.cell(self.s_cos[sel] * (rad[sel] - 0.03 * j), self.s_sin[sel] * (rad[sel] - 0.03 * j))
            self.put(rj, cj, tint[sel] * (1.0 - j / 8.0), self.s_streak[sel], space, over, col)
        self.put(r[fast], c[fast], tint[fast] * 1.3, self.g_star, space, over, col)

        small, medium, big = (slow & (self.s_kind == k) for k in range(3))
        self.put(r[small], c[small], tint[small] * 0.9, self.g_dot, space, over, col)
        dim = medium & (tw < 0.6)
        self.put(r[dim], c[dim], tint[dim] * 1.2, self.g_dot, space, over, col)
        lit = medium & (tw >= 0.6)
        self.put(r[lit], c[lit], tint[lit], self.g_plus, space, over, col)
        arm = np.round(self.s_arm * tw).astype(np.int64)
        for k in range(1, 5):                        # Strahlenkreuz der grossen Sterne
            reach = big & (arm >= k)
            for dc in (k, -k):
                self.put(r[reach], c[reach] + dc, tint[reach] * (1.0 - 0.18 * k), self.g_dash, space, over, col)
            if k <= 2:
                tall = big & (arm >= 2 * k)
                for dr in (k, -k):
                    self.put(r[tall] + dr, c[tall], tint[tall] * (1.0 - 0.18 * k), self.g_bar, space, over, col)
        self.put(r[big], c[big], tint[big] * 1.3, np.where(tw[big] >= 0.6, self.g_star, self.g_plus), space, over, col)

    def meteor(self, t, space, over, col):
        """Alle knapp zwei Sekunden eine Sternschnuppe."""
        since = t - self.t_cross - 0.8
        if since < 0:
            return
        n, age = divmod(since, 1.9)
        if age > 0.75:
            return
        rnd = np.random.default_rng(1000 + int(n))
        start = np.array([rnd.uniform(-0.9, 0.9) * self.half_w, rnd.uniform(-0.95, -0.2)])
        going_right = rnd.random() < 0.5
        move = np.array([1.0 if going_right else -1.0, rnd.uniform(0.45, 0.8)])
        move /= np.hypot(*move)
        j = np.arange(16)
        px = start[0] + move[0] * (age * 2.4 - 0.028 * j)
        py = start[1] + move[1] * (age * 2.4 - 0.028 * j)
        r, c = self.cell(px, py)
        glow = (1.0 - j / 16.0) * math.sin(math.pi * age / 0.75)
        glyph = np.where(j == 0, self.g_star, self.g_back if going_right else self.g_slash)
        self.put(r, c, np.array([255.0, 250.0, 235.0]) * glow[:, None], glyph, space, over, col)


def distort(img, glitch, rng):
    """Bildstoerung: Farbkanaele reissen auseinander, Streifen verrutschen."""
    k = int(round(glitch * 6))
    if k > 0:
        red, green, blue = img.split()
        img = Image.merge("RGB", (ImageChops.offset(red, k, 0), green, ImageChops.offset(blue, -k, 0)))
    width, height = img.size
    for _ in range(int(glitch * 8)):
        y0 = int(rng.integers(0, height - 4))
        box = (0, y0, width, min(height, y0 + int(rng.integers(3, 46))))
        img.paste(ImageChops.offset(img.crop(box), int(rng.integers(-70, 71) * glitch), 0), box)
    return img


def main():
    root = tk.Tk()
    root.title("ASCII Eye")
    root.resizable(False, False)
    root.configure(bg="black")

    width, height = COLS * CELL_W, ROWS * CELL_H
    glyphs = Glyphs(CELL_W, CELL_H)
    scene = Scene(COLS, ROWS, CELL_W, CELL_H, glyphs.ids)
    photo = ImageTk.PhotoImage(Image.new("RGB", (width, height)))
    tk.Label(root, image=photo, bd=0, highlightthickness=0).pack()

    rng = np.random.default_rng()
    variant = rng.integers(0, VARIANTS, (ROWS, COLS))            # welches Zeichen der Stufe
    st = {"t0": time.perf_counter(), "last": time.perf_counter()}

    def restart(_event=None):
        st["t0"] = time.perf_counter()

    def tick():
        start = time.perf_counter()
        t = start - st["t0"]
        dt = min(start - st["last"], 0.1)
        st["last"] = start
        if LOOP and t > T_END + 2.0:
            restart()
            t = 0.0
        level, col, over, jitter, glitch = scene.render(t, dt)

        # Flackern: Zellen wuerfeln ihr Zeichen innerhalb der Helligkeitsstufe neu
        swap = rng.random((ROWS, COLS)) < (1.0 - math.exp(-FLUTTER * dt)) + jitter
        variant[swap] = rng.integers(0, VARIANTS, int(swap.sum()))
        glyph = glyphs.table[level, variant]
        np.copyto(glyph, over + glyphs.plain, where=over >= 0)

        img = glyphs.compose(glyph, col)
        if glitch > 0.05:
            img = distort(img, glitch, rng)
        photo.paste(img)

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

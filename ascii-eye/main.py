"""Zeichen-Auge -> Zielerfassung -> Flug durch die Pupille -> Weltraum mit Sonnenaufgang.

Jede Zelle des Bildes ist ein Zeichen aus einem grossen, wilden Vorrat, das
staendig wechselt. Ein eigener Thread berechnet die Szene mit numpy und setzt
sie aus vorgerenderten Zeichen-Bitmaps zusammen; das Fenster zeigt nur noch an.

Start:   Windows: Doppelklick auf start.bat (installiert alles und startet)
         sonst:   python -m pip install numpy pillow
                  python main.py

Tasten:  Leertaste / R = neu starten      Esc = beenden
"""

import math
import queue
import sys
import threading
import time
import tkinter as tk
import traceback

try:
    import numpy as np
    from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageTk
except ImportError:                                  # verstaendliche Meldung statt Sofort-Absturz
    from tkinter import messagebox
    _root = tk.Tk()
    _root.withdraw()
    messagebox.showerror("Pakete fehlen", "numpy und/oder pillow sind nicht installiert.\n\n"
                         "Starte die Datei start.bat oder fuehre im Terminal aus:\n\n"
                         "    python -m pip install numpy pillow")
    raise SystemExit(1)

# ----------------------------------------------------------------- Einstellungen
COLS, ROWS = 132, 52      # Raster in Zeichen
CELL_H = 0                # Zellenhoehe in Pixeln; 0 = passend zum Bildschirm waehlen
FPS = 60
LOOP = False              # True = nach dem Ende automatisch von vorn
HUD = True                # Scanner-Einblendungen (Zielrahmen, Texte)

# Zeichenvorrat. Was die Schrift nicht kennt, wird automatisch aussortiert.
CHARS = ("0123456789" "!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~"
         "ABCDEFGHIJKLMNOPQRSTUVWXYZ" "abcdefghijklmnopqrstuvwxyz"
         "¡¢£¥§©«¬®°±²³µ¶·»¼½¾¿×÷ØøÞþßÆæ"
         "ΓΔΘΛΞΠΣΦΨΩαβγδεζηθλμξπρστφχψω"
         "БГДЖЗИЛПФЦЧШЩЫЭЮЯбгджзилфцчшщыэюя"
         "∂∆∏∑√∞∫≈≠≤≥●"
         "─│┌┐└┘├┤┬┴┼═║╔╗╚╝╬")
LEVELS = 24               # Helligkeitsstufen
VARIANTS = 32             # Zeichen pro Stufe, zwischen denen es wechselt
FLUTTER = 4.0             # wie oft pro Sekunde eine Zelle ihr Zeichen wechselt
VIVID = 0.40              # Farbkraft: klein = alles leuchtet, 1 = Helligkeit auch ueber die Farbe
GLOW = 0.07               # Grundleuchten hinter den Zeichen (0 = aus)
BLOOM = 0.70              # Ueberstrahlen gleissender Stellen: Sonne, Sterne, Reflexe (0 = aus)
SCANLINES = 0.90          # Helligkeit jeder zweiten Pixelzeile (1 = aus)

# ----------------------------------------------------------------- Zeitablauf (s)
T_RAIN = 0.9              # Zeichenregen legt das Bild frei
T_OPEN0, T_OPEN1 = 1.0, 1.9   # Auge oeffnet sich
T_LOCK = 2.9              # Zielrahmen rastet ein
T_BLINK = 3.25            # kurzes Blinzeln
T_ZOOM0, T_ZOOM1 = 3.5, 13.5  # Zoom in die Pupille
T_SUN = 3.0               # Sekunden nach dem Durchflug bis zum Sonnenaufgang
T_END = 22.0
LN_ZOOM = 2.8             # ln des Zoomfaktors bei T_ZOOM1 (~16x)

# ----------------------------------------------------------------- Szene
EYE_A = 1.22              # halbe Augenbreite (Bildhoehe = 2 Einheiten)
LID_UP, LID_LO = 0.36, 0.22   # Oeffnung nach oben / unten (klein = schmales "Hunter Eye")
LID_MID = 0.06            # Lidspalte liegt etwas unter der Pupillenmitte
TILT = 0.11               # Neigung: aeusserer Augenwinkel hoeher als der innere
LASH_UP, LASH_LO = 0.34, 0.12 # Wimpernlaenge oben / unten
BROW_Y, BROW_H, BROW_TILT = -0.74, 0.115, 0.07   # Augenbraue: Hoehe, halbe Dicke, Neigung
R_IRIS = 0.33
R_PUPIL = 0.105
R_PLANET = 0.0150
SUN_DIR = (0.12, -0.99)   # Richtung, in der die Sonne hinter dem Planeten aufgeht
N_STARS = 320


def rgb(*v):
    return np.array(v, np.float32)


SKIN, ROSY, RIM = rgb(246, 178, 146), rgb(232, 124, 108), rgb(246, 186, 176)
BROW = rgb(50, 28, 18)
SCLERA, CORNER, VEIN = rgb(250, 246, 242), rgb(232, 150, 140), rgb(214, 92, 86)
IRIS_U = [0.00, 0.05, 0.25, 0.55, 0.85, 1.00]
IRIS_RGB = np.array([[70, 34, 10], [255, 208, 86], [242, 162, 40],
                     [206, 110, 24], [112, 54, 16], [30, 14, 8]], np.float32)
CYAN, LOCK, RED, WHITE = rgb(90, 225, 255), rgb(120, 255, 190), rgb(255, 70, 70), rgb(255, 255, 255)
MAGENTA, PINK = rgb(232, 36, 140), rgb(255, 226, 240)
RING, MOON = rgb(255, 214, 170), rgb(190, 235, 255)
VIOLET, TEAL, GALAXY = rgb(150, 60, 255), rgb(20, 170, 190), rgb(170, 190, 255)
SUN, FLARE = rgb(255, 236, 196), rgb(120, 180, 255)
RAIN = rgb(170, 255, 225)
LUMA = rgb(0.299, 0.587, 0.114)


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
    tau = 1.2
    return LN_ZOOM + speed * tau * (1.0 - math.exp(-(t - T_ZOOM1) / tau))


class Glyphs:
    """Vorgerenderte Zeichen-Bitmaps plus Tabelle: Helligkeitsstufe -> passende Zeichen."""

    def __init__(self, cw, ch):
        self.cw, self.ch = cw, ch
        font = self.load_font(cw, ch)

        def draw(c):
            img = Image.new("L", (cw, ch), 0)
            try:
                ImageDraw.Draw(img).text((cw / 2, ch / 2), c, fill=255, font=font, anchor="mm")
            except (ValueError, TypeError):          # Ersatzschrift ohne Anker
                ImageDraw.Draw(img).text((0, 0), c, fill=255, font=font)
            return np.asarray(img, np.float32)

        # Zeichen aussortieren, die leer sind, doppelt aussehen oder der Schrift fehlen
        missing = draw("￿")
        self.ids, bitmaps, seen = {" ": 0}, [np.zeros((ch, cw), np.float32)], set()
        for c in dict.fromkeys(CHARS):
            bmp = draw(c)
            if bmp.max() < 60 or bmp.tobytes() in seen or np.array_equal(bmp, missing):
                continue
            seen.add(bmp.tobytes())
            self.ids[c] = len(bitmaps)
            bitmaps.append(bmp)
        atlas = 255.0 * (np.stack(bitmaps) / 255.0) ** 0.45      # duenne Striche kraeftiger
        atlas[:, 1::2, :] *= SCANLINES
        self.atlas = atlas.astype(np.uint8)

        # Zu jeder Stufe alle Zeichen, deren Deckung in der Naehe liegt. Der Rest wird
        # ueber die Farbe ausgeglichen (gain), so bleibt die Flaeche trotz Vielfalt ruhig.
        cover = atlas.mean(axis=(1, 2))[1:] / 255.0
        ref = np.percentile(cover, 88)
        self.table = np.zeros((LEVELS, VARIANTS), np.int16)
        self.gain = np.ones((LEVELS, VARIANTS), np.float32)
        for lv in range(1, LEVELS):
            target = ref * lv / (LEVELS - 1)
            dist = np.abs(np.log(cover / target))
            order = np.argsort(dist)
            pick = order[:max(4, min(VARIANTS, int((dist < math.log(2.3)).sum())))]
            pick = np.resize(pick, VARIANTS)
            self.table[lv] = pick + 1
            self.gain[lv] = np.clip(target / cover[pick], 0.35, 1.7)

        self.glow = bytes(int(i * GLOW) for i in range(256)) * 3

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

    def compose(self, glyph, tint, col, shine):
        """Zeichen in ihrer Farbe vor einem weich leuchtenden Hintergrund."""
        rows, cols = glyph.shape
        size = (cols * self.cw, rows * self.ch)
        mask = np.ascontiguousarray(self.atlas[glyph].transpose(0, 2, 1, 3)).reshape(size[1], size[0])
        mask = Image.frombuffer("L", size, mask, "raw", "L", 0, 1)
        front = Image.frombuffer("RGB", (cols, rows), tint, "raw", "RGB", 0, 1).resize(size, Image.NEAREST)
        small = Image.frombuffer("RGB", (cols, rows), col, "raw", "RGB", 0, 1)
        halo = Image.frombuffer("RGB", (cols, rows), shine, "raw", "RGB", 0, 1)
        back = ImageChops.add(small.point(self.glow), halo.filter(ImageFilter.GaussianBlur(2.0)))
        back = back.resize((size[0] // 4, size[1] // 4), Image.BILINEAR).resize(size, Image.NEAREST)
        return Image.composite(front, back, mask)


class Scene:
    """Berechnet pro Frame Helligkeitsstufe, Farbe und feste Zeichen jeder Zelle."""

    def __init__(self, cols, rows, cw, ch, ids):
        self.cols, self.rows, self.ids = cols, rows, ids
        w, h = cols * cw, rows * ch
        self.half_w = w / h
        sx = ((np.arange(cols) + 0.5) * cw - w / 2) / (h / 2)
        sy = ((np.arange(rows) + 0.5) * ch - h / 2) / (h / 2)
        self.SX, self.SY = np.meshgrid(sx.astype(np.float32), sy.astype(np.float32))
        self.SR = np.hypot(self.SX, self.SY)
        self.sr_max = float(self.SR.max())
        self.cell = 2.0 / rows            # Zellenhoehe in Szenen-Einheiten
        self.unit_c = (h / 2) / cw        # Szenen-Einheit -> Spalten
        self.unit_r = (h / 2) / ch        # Szenen-Einheit -> Zeilen
        self.row_no = np.arange(rows)[:, None]

        rng = np.random.default_rng(7)
        self.rng = rng
        self.tex = self.noise_texture(rng)
        self.strand = rng.random(256).astype(np.float32)         # Zufall pro Wimper
        self.gaze_xy = rng.uniform(-1, 1, (64, 2)) * (0.045, 0.014)
        self.spark = np.zeros((rows, cols), np.float32)
        self.glare = np.zeros((rows, cols), np.float32)
        self.rain_delay = rng.uniform(0.0, 0.28, cols)
        self.rain_speed = rows / rng.uniform(0.35, 0.6, cols)

        # Sterne fliegen beim Zoom strahlenfoermig aus der Mitte heraus
        ang = rng.uniform(0, 2 * math.pi, N_STARS)
        self.s_cos, self.s_sin = np.cos(ang), np.sin(ang)
        self.s_rho = rng.random(N_STARS)
        self.s_rate = rng.uniform(0.25, 1.5, N_STARS)
        self.s_kind = rng.choice(3, N_STARS, p=[0.58, 0.24, 0.18])   # klein, mittel, gross
        tints = np.array([[255, 255, 255], [180, 215, 255], [255, 226, 180], [255, 170, 230]], np.float32)
        self.s_col = tints[rng.choice(4, N_STARS, p=[0.5, 0.25, 0.15, 0.10])]
        self.s_freq = rng.uniform(0.8, 3.0, N_STARS)
        self.s_phase = rng.uniform(0, 6.283, N_STARS)
        self.s_arm = rng.integers(2, 5, N_STARS)
        sector = np.round((ang % math.pi) / (math.pi / 4)).astype(int) % 4
        self.s_streak = np.array([ids["-"], ids["\\"], ids["|"], ids["/"]])[sector]

        # Zeitpunkt, an dem die Pupille das ganze Bild fuellt (Schockwelle, Stoerung)
        self.t_cross = next(t / 100 for t in range(int(T_END * 100))
                            if R_PUPIL * math.exp(ln_zoom(t / 100)) > 1.25)
        self.t_sun = self.t_cross + T_SUN
        self.glitches = [(T_OPEN0 + 0.15, 0.8, 0.12), (T_LOCK, 0.35, 0.05),
                         (self.t_cross, 1.0, 0.20), (self.t_sun + 2.2, 0.35, 0.06)]

    @staticmethod
    def noise_texture(rng, size=512, period=64):
        """Weiches, kachelbares Rauschen als fertige Textur (8 Texel pro Einheit)."""
        base = rng.random((period, period)).astype(np.float32)
        p = np.arange(size, dtype=np.float32) * period / size
        i = p.astype(int)
        f = p - i
        f = f * f * (3 - 2 * f)
        j = (i + 1) % period
        top = base[i][:, i] * (1 - f) + base[i][:, j] * f
        bot = base[j][:, i] * (1 - f) + base[j][:, j] * f
        return top * (1 - f[:, None]) + bot * f[:, None]

    def tn(self, x, y):
        """Rauschen 0..1 an den Stellen (x, y); wiederholt sich alle 64 Einheiten."""
        return self.tex[(y * 8 + 4096).astype(np.int32) & 511, (x * 8 + 4096).astype(np.int32) & 511]

    def lashes(self, lx, d, spacing, width, lean0, lean1, length, seed):
        """Wimpern als geschwungene Straehnen; d = Abstand zur Lidkante (>0 = ausserhalb)."""
        bend = d + 2.4 * d * d                       # weiter draussen staerker geneigt
        root = lx - (lean0 + lean1 * lx / EYE_A) * bend      # wo die Wimper am Lid sitzt
        n = root / spacing + 0.9 * self.tn(root * 5 + seed, d * 0 + seed)    # ungleichmaessig gesetzt
        i = np.floor(n)
        k = root / EYE_A
        rnd = self.strand[(i.astype(np.int32) + seed) & 255]
        full = length(k) * (0.65 + 0.6 * rnd) * np.clip(1.0 - k * k, 0.0, 1.0) ** 0.2
        rel = np.clip(d / np.maximum(full, 1e-6), 0.0, 1.0)  # 0 = Wurzel, 1 = Spitze
        thick = 0.5 * width * (1.0 - rel ** 2) ** 0.8        # laeuft erst am Ende spitz zu
        return smooth((thick - np.abs(n - i - 0.5)) / 0.05 + 0.5) * (d > 0) * (rel < 1.0)

    def glitch(self, t):
        return max(amp * math.exp(-((t - t0) / width) ** 2) for t0, amp, width in self.glitches)

    def gaze(self, t):
        """Blickspruenge: alle 0,8 s ein neues Ziel, schnell angesteuert."""
        n, u = divmod(t / 0.8, 1.0)
        a, b = self.gaze_xy[int(n) % 64], self.gaze_xy[(int(n) + 1) % 64]
        return a + (b - a) * float(smooth((u - 0.86) / 0.14))

    # ------------------------------------------------------------------ Frame
    def render(self, t, dt):
        lz = ln_zoom(t)
        zoom = math.exp(lz)
        zspeed = (ln_zoom(t + 0.05) - ln_zoom(t - 0.05)) / 0.1
        calm = (1.0 - min(lz / LN_ZOOM, 1.0)) ** 2   # Augenbewegung klingt beim Zoom ab
        glitch = self.glitch(t)
        cross = t - self.t_cross
        shake = 0.012 * glitch + 0.05 * math.exp(-(cross / 0.25) ** 2) + 0.004 * zspeed
        x = (self.SX + shake * math.sin(t * 71.0)) / zoom        # Kamerawackeln
        y = (self.SY + shake * math.cos(t * 93.0)) / zoom
        r = np.hypot(x, y)
        jitter = np.full((self.rows, self.cols), 0.6 * glitch, np.float32)   # Extra-Flackern

        # --- Auge; faellt weg, sobald die Pupille das ganze Bild fuellt
        if R_PUPIL * zoom * 0.85 > self.sr_max:
            col = np.zeros((self.rows, self.cols, 3), np.float32)
            hole = np.ones((self.rows, self.cols), np.float32)
        else:
            col, hole = self.eye(t, x, y, r, zoom, calm)

        # --- Pupille = Fenster in den Weltraum
        pupil = hole > 0.5
        solid = np.zeros_like(pupil)                 # Zellen, die Planet/Ring/Mond bedecken
        vis = float(smooth((zoom - 1.7) / 1.4))
        if vis > 0:
            body, solid = self.space(t, x, y, r, zoom)
            col += body * (hole * vis)[..., None]

        # --- Scanstrahl faehrt einmal von oben nach unten ueber das Auge
        beam = -1.15 + 2.3 * (t - T_OPEN1) / (T_LOCK - T_OPEN1 - 0.15)
        if HUD and -1.2 < beam < 1.2:
            line = np.exp(-((self.SY - beam) / 0.035) ** 2)
            wake = 0.25 * np.exp(-np.maximum(beam - self.SY, 0) / 0.22) * (self.SY < beam)
            col = col * (1.0 - 0.6 * line[..., None]) + CYAN * (1.3 * line + wake * 0.4)[..., None]
            jitter += line + 0.3 * wake

        # --- Schockwelle und Blitz beim Durchflug durch die Pupille
        if 0.0 < cross < 1.2:
            ring = np.exp(-((self.SR - 2.3 * cross) / 0.09) ** 2) * (1.0 - cross / 1.2)
            col += CYAN * (1.6 * ring)[..., None]
            col *= 1.0 + 1.4 * math.exp(-cross / 0.12)
            jitter += ring

        # --- Funken: einzelne Zellen blitzen kurz weiss auf
        self.spark *= math.exp(-dt / 0.09)
        self.spark[self.rng.random(self.spark.shape) < 0.022 * dt] = 1.0
        lit = (self.spark * (col.sum(-1) > 60))[..., None]
        col += (255.0 - col) * 0.8 * lit

        # --- Flacker-Welle: laeuft alle paar Sekunden quer durchs Bild
        sweep = (t * 0.55) % 2.4 - 0.6
        jitter += 0.5 * np.exp(-((self.SX * 0.35 + self.SY * 0.2 + 0.5 - sweep) / 0.07) ** 2)

        # --- Vignette
        col *= (1.0 - 0.22 * np.clip(self.SR / 1.6, 0, 1) ** 2.5)[..., None]

        # --- Helligkeit -> Stufe, Farbe aufhellen
        col = np.clip(col, 0.0, 255.0)
        lum = (col @ LUMA) / 255.0
        self.glare = smooth((lum - 0.93) / 0.07) * (0.35 + 0.65 * hole)  # nur Gleissendes strahlt ueber
        level = (lum ** 0.80 * (LEVELS - 1) + 0.5).astype(np.int64)
        level[lum < 0.03 + 0.06 * hole] = 0          # im All bleibt Dunkles wirklich schwarz
        peak = np.maximum(col.max(-1, keepdims=True), 1.0) / 255.0
        vivid = (VIVID + (0.62 - VIVID) * hole)[..., None]
        col = np.minimum(col * (1.06 * peak ** (vivid - 1.0)), 255.0)    # Farbton behalten, kraeftig aufhellen
        over = np.full((self.rows, self.cols), -1, np.int16)     # feste Zeichen (Sterne, Texte)

        fade = float(smooth((zoom - 1.4) / 1.2))     # anfangs ist die Pupille einfach schwarz
        free = pupil & ~solid
        if fade > 0.0 and free.any():
            self.stars(t, lz, zspeed, fade, free, over, col)
            self.meteor(t, free, over, col)
        if HUD:
            self.hud(t, zoom, lz, over, col)

        # --- Zeichenregen: faellt von oben und legt das Bild frei
        if t < T_RAIN + 0.4:
            behind = (t - self.rain_delay) * self.rain_speed - self.row_no   # >0: Kopf schon vorbei
            hidden = behind < 0
            trail = np.clip(1.0 - behind / 10.0, 0.0, 1.0) * ~hidden
            col = col * (1.0 - trail[..., None]) + RAIN * trail[..., None]
            level = np.maximum(level, (trail * (LEVELS - 1)).astype(np.int64))
            level[hidden] = 0
            col[hidden] = 0.0
            over[hidden | (trail > 0)] = -1
            jitter += trail

        return level, col, over, jitter, glitch, self.glare

    # ------------------------------------------------------------------ Auge
    def eye(self, t, x, y, r, zoom, calm):
        """Haut, Wimpern, Braue, Augapfel und Iris; liefert Farbe und Pupillen-Maske (0..1)."""
        tn = self.tn
        aa = 1.3 * self.cell / zoom                  # Kanten ueber eine Zellenhoehe glaetten
        gx, gy = self.gaze(t) * calm
        lx, ly = x + gx, y + gy                      # Lider verschieben sich gegen die Iris
        opened = float(smooth((t - T_OPEN0) / (T_OPEN1 - T_OPEN0)))
        opened *= 1.0 - 0.94 * math.exp(-((t - T_BLINK) / 0.085) ** 2)   # Blinzeln
        if R_IRIS * zoom * 0.90 > self.sr_max:       # nur noch Iris im Bild: Haut und Augapfel sparen
            col = np.zeros((self.rows, self.cols, 3), np.float32)
            inside = lid_shadow = np.float32(1.0)
            return self.iris(t, x, y, r, zoom, calm, opened, aa, col, inside, lid_shadow)

        kx = lx / EYE_A                              # -1 innerer .. +1 aeusserer Augenwinkel
        f = np.clip(1.0 - kx * kx, 0.0, 1.0)
        mid = LID_MID - TILT * lx + 0.05 * smooth((-kx - 0.72) / 0.28)   # Traenenwinkel haengt etwas
        up = mid - LID_UP * (1.0 - 0.18 * kx) * f ** 0.6 * opened
        lo = mid + LID_LO * (1.0 + 0.10 * kx) * f ** 0.9 * opened
        inside = smooth((ly - up) / aa + 0.5) * smooth((lo - ly) / aa + 0.5) * (f > 0)
        du, dl = up - ly, ly - lo                    # Abstand ueber / unter dem Lid
        above, below = du > 0, dl > 0
        edge = smooth(f / 0.10)

        # --- Haut: plastisch ausgeleuchtet statt flach
        shade = 0.96 + 0.06 * tn(lx * 2.2 + 7, ly * 2.2 + 3) + 0.04 * (tn(lx * 26, ly * 26) - 0.5)
        shade *= 1.0 - 0.07 * kx                                     # Licht kommt von links oben
        crease = 0.035 + 0.075 * f                                   # Abstand der Lidfalte
        lid = np.exp(-((du / crease - 0.5) / 0.30) ** 2) * above * (du < crease)
        shade *= 1.0 + 0.17 * lid * f                                # Glanz auf dem Oberlid
        shade *= 1.0 - 0.45 * f * np.exp(-((du - crease) / 0.022) ** 2)              # Lidfalte
        orbit = np.exp(-np.maximum(du - crease, 0) / 0.22) * (du > crease)
        shade *= 1.0 - (0.13 + 0.14 * smooth(-kx)) * orbit * f       # Augenhoehle, nasenseitig tiefer
        shade *= 1.0 + 0.10 * np.exp(-((ly - (BROW_Y + 0.24 - BROW_TILT * lx)) / 0.07) ** 2) * smooth((kx + 0.2) / 0.6)
        shade *= 1.0 - 0.20 * f * np.exp(-((dl - 0.10) / 0.05) ** 2)                 # Traenenrinne
        shade *= 1.0 + 0.08 * np.exp(-((dl - 0.30) / 0.14) ** 2)                     # Wangenglanz
        shade *= 1.0 - 0.26 * smooth((-lx - 0.95) / 0.4)                             # Nasenschatten
        shade *= 1.0 - 0.93 * edge * np.exp(-np.maximum(du, 0) / 0.020) * above      # Wimpernkranz
        shade *= 1.0 - 0.45 * edge * np.exp(-((dl - 0.030) / 0.012) ** 2)            # untere Wimpernlinie
        near = np.exp(-np.minimum(np.abs(du), np.abs(dl)) / 0.13) * edge
        col = (SKIN + (ROSY - SKIN) * (0.30 * near)[..., None]) * shade[..., None]   # ums Auge roetlicher
        wet = (edge * smooth(1.0 - dl / 0.026) * below)[..., None]                   # feuchter Lidrand
        col = col * (1.0 - 0.8 * wet) + RIM * 0.8 * wet

        if zoom < 3.8:                               # danach sind die Lider aus dem Bild
            # --- Wimpern: zwei versetzte Reihen oben, eine kurze unten
            grow = 0.3 + 0.7 * opened
            hair = self.lashes(lx, du, 0.085, 0.44, 0.10, 0.70, lambda k: (LASH_UP + 0.5 * LASH_UP * k) * grow, 0)
            hair = np.maximum(hair, 0.85 * self.lashes(lx, du, 0.123, 0.36, 0.18, 0.55,
                                                       lambda k: (0.7 * LASH_UP + 0.3 * LASH_UP * k) * grow, 91))
            hair = np.maximum(hair, 0.8 * self.lashes(lx, dl, 0.115, 0.34, 0.08, 0.60,
                                                      lambda k: LASH_LO * smooth((k + 0.8) / 0.5) * grow, 37))
            col *= (1.0 - 0.96 * hair)[..., None]

        if zoom < 1.9:
            # --- Augenbraue aus einzelnen Haerchen
            yb = BROW_Y - BROW_TILT * lx - 0.07 * np.exp(-((kx - 0.35) / 0.45) ** 2)
            half = BROW_H * smooth((lx + 1.34) / 0.22) * (1.0 - 0.62 * smooth((kx - 0.25) / 0.75))
            v = (ly - yb) / np.maximum(half, 1e-4)
            strands = tn((lx * 0.90 + ly * 0.42) * 7.0, (ly * 0.90 - lx * 0.42) * 62.0)
            brow = smooth((1.0 - np.abs(v) - 0.55 * (strands - 0.35)) / 0.45) * (half > 0.004)
            brow = (brow * (0.72 + 0.28 * strands))[..., None]
            col = col * (1.0 - brow) + BROW * (0.6 + 0.9 * strands)[..., None] * brow

        # --- Augapfel: Kugelschatten, Lidschatten, Aederchen, Traenenwaerzchen
        k = np.abs(kx)
        lid_shadow = 1.0 - 0.42 * np.exp(-np.maximum(ly - up, 0) / 0.05)
        ball = (1.0 - 0.26 * k * k) * lid_shadow * (1.0 - 0.20 * np.exp(-np.maximum(lo - ly, 0) / 0.04))
        white = SCLERA + (CORNER - SCLERA) * (k ** 4)[..., None]
        vein = smooth((0.030 - np.abs(tn(lx * 7 + 1.3, ly * 17 + 2.1) - 0.5)) / 0.03) * smooth((k - 0.38) / 0.45)
        white = white + (VEIN - white) * (0.38 * vein)[..., None]
        duct = np.exp(-(((lx + 1.09) / 0.085) ** 2 + ((ly - mid - 0.01) / 0.06) ** 2))[..., None]
        white = white + (ROSY - white) * (0.85 * duct)
        col += (white * ball[..., None] - col) * inside[..., None]

        return self.iris(t, x, y, r, zoom, calm, opened, aa, col, inside, lid_shadow)

    def iris(self, t, x, y, r, zoom, calm, opened, aa, col, inside, lid_shadow):
        """Iris, Pupille und Lichtreflexe auf die bisherige Farbe legen."""
        tn = self.tn
        # --- Iris: Fasern, Krause, Krypten, dunkler Rand, Licht sammelt sich gegenueber dem Reflex
        beat = math.exp(-((t * 1.15) % 1.0) * 6.0)
        rp = R_PUPIL * (1.0 + (0.05 * math.sin(1.1 * t) + 0.06 * beat) * calm - 0.10 * (1.0 - opened))
        u = np.clip((r - rp) / (R_IRIS - rp), 0.0, 1.0)
        ang = np.arctan2(y, x) / (2 * math.pi)
        fibre = 0.55 * tn(ang * 192 + 3, u * 3.0 + 5) + 0.45 * tn(ang * 64, u * 1.5)
        frill = np.exp(-((u - 0.30 - 0.07 * (tn(ang * 64 + 17, u * 0 + 0.5) - 0.5)) / 0.06) ** 2)
        crypt = smooth((tn(ang * 64 + 40, u * 6 + 9) - 0.70) / 0.12) * (u > 0.36)
        iris = np.stack([np.interp(u, IRIS_U, IRIS_RGB[:, i]) for i in range(3)], -1).astype(np.float32)
        pool = 1.0 + 0.45 * np.clip((0.6 * x + 0.8 * y) / R_IRIS, 0.0, 1.0)
        wave = 1.0 + 0.16 * np.sin(u * 20.0 - t * 5.0) * np.exp(-u * 1.6)
        iris *= ((0.52 + 0.95 * fibre) * (1.0 + 0.40 * frill) * (1.0 - 0.45 * crypt) * pool * wave * lid_shadow)[..., None]
        col += (iris - col) * (inside * smooth((R_IRIS - r) / aa + 0.5))[..., None]

        # --- Pupille und Fensterreflexe auf der Hornhaut (verschwinden beim Zoom)
        hole = inside * smooth((rp - r) / aa + 0.5)
        col *= (1.0 - hole)[..., None]
        wx, wy = (x + 0.105) / 0.060, (y + 0.115) / 0.048
        glint = smooth((1.0 - (wx ** 4 + wy ** 4)) / 0.6) * (1.0 - 0.55 * np.exp(-(wx / 0.13) ** 2))
        glint += 0.55 * np.exp(-(((x - 0.10) / 0.024) ** 2 + ((y - 0.085) / 0.020) ** 2))
        glint = np.clip(glint * inside * (1.0 - float(smooth((zoom - 2.5) / 3.0))), 0.0, 1.0)
        col += (255.0 - col) * glint[..., None]
        return col, hole * (1.0 - glint)

    # ------------------------------------------------------------------ Weltraum
    def space(self, t, x, y, r, zoom):
        """Nebel, Galaxie, Ringplanet, Mond und der Sonnenaufgang hinter dem Planeten."""
        tn = self.tn
        far = zoom ** 0.18                           # weit weg: zoomt kaum mit
        fx, fy = self.SX / far, self.SY / far
        cloud = smooth((0.6 * tn(fx * 2.3 + 11 + 0.02 * t, fy * 2.3 + 5)
                        + 0.4 * tn(fx * 5.1 + 3, fy * 5.1 + 9 - 0.03 * t) - 0.56) / 0.28)
        mixn = tn(fx * 1.4 + 40, fy * 1.4 + 23)
        body = (VIOLET * (cloud * mixn)[..., None] + TEAL * (cloud * (1 - mixn))[..., None]) * 0.55

        # Spiralgalaxie im Hintergrund
        gx, gy = fx - 0.52, fy + 0.40
        ga, gb = gx * 0.88 + gy * 0.47, (gy * 0.88 - gx * 0.47) / 0.42
        rg = np.hypot(ga, gb)
        arms = 0.5 + 0.5 * np.cos(2.0 * np.arctan2(gb, ga) - 6.5 * np.log(rg + 0.02) + 0.2 * t)
        gal = np.exp(-rg / 0.11) * (0.10 + 0.90 * arms ** 2) + 1.4 * np.exp(-(rg / 0.035) ** 2)
        body += GALAXY * (1.3 * gal)[..., None]

        # Planet mit rotierenden Baendern
        d = r / R_PLANET
        nx, ny = x / R_PLANET, y / R_PLANET
        nz = np.sqrt(np.clip(1.0 - d * d, 0.0, 1.0))
        lam = np.clip(-0.30 * nx - 0.35 * ny + 0.89 * nz, 0.0, 1.0)
        lon = np.arctan2(nx, nz + 1e-6) + 0.45 * t
        band = 0.5 + 0.5 * np.sin(ny * 8 + 1.1 * np.sin(lon * 3) + 0.6 * np.sin(lon * 7 + ny * 4))
        mixp = np.clip(0.60 * band * lam + 0.20 * lam ** 2, 0, 1)[..., None]
        planet = (MAGENTA * (1 - mixp) + PINK * mixp) * (0.25 + 0.95 * lam)[..., None]
        pulse = 0.55 + 0.15 * math.sin(2.2 * t)
        disc = d < 1.0
        halo = MAGENTA * (pulse * np.exp(-np.maximum(d - 1.0, 0) / 0.12))[..., None]
        body = np.where(disc[..., None], planet, body + halo)

        # Sonnenaufgang: die Sonne schiebt sich links oben hinter dem Planeten hervor
        ts = t - self.t_sun
        core = np.zeros_like(disc)
        if ts > 0:
            power = float(smooth(ts / 2.2)) * (1.0 + 0.06 * math.sin(9.0 * t))
            sx, sy = (c * (0.80 + 0.50 * float(smooth(ts / 3.2))) for c in SUN_DIR)
            ds = np.hypot(nx - sx, ny - sy)
            light = 4.0 * smooth((0.50 - ds) / 0.12) + 0.9 * np.exp(-ds / 0.30)              # Scheibe + Korona
            light += 1.2 * np.exp(-np.abs(nx - sx) / 0.04) * np.exp(-np.abs(ny - sy) / 1.1)   # senkrechter Strahl
            streak = 1.6 * np.exp(-np.abs(ny - sy) / 0.05) * np.exp(-np.abs(nx - sx) / 3.5)   # Lichtstreifen
            ghost = 0.30 * np.exp(-((np.hypot(nx + 0.7 * sx, ny + 0.7 * sy) - 0.26) / 0.035) ** 2)
            ghost += 0.22 * np.exp(-(np.hypot(nx + 1.7 * sx, ny + 1.7 * sy) / 0.20) ** 2)
            rim = np.exp(-(1.0 - np.minimum(d, 1.0)) / 0.09) * np.clip(nx * SUN_DIR[0] + ny * SUN_DIR[1], 0, 1) ** 1.5
            body += power * np.where(disc[..., None], SUN * (1.5 * rim)[..., None],
                                     SUN * light[..., None] + FLARE * (streak + ghost)[..., None])
            core = ~disc & (ds < 0.75) & (power > 0.2)

        # Ring: schraege, flache Ellipse; vorn vor dem Planeten, hinten dahinter
        ca, sa = math.cos(-0.35), math.sin(-0.35)
        rx, ry = nx * ca + ny * sa, (-nx * sa + ny * ca) / 0.30
        rr = np.hypot(rx, ry)
        in_ring = (rr > 1.50) & (rr < 2.35) & ~((rr > 1.90) & (rr < 2.02)) & ((ry > 0) | ~disc)
        body = np.where(in_ring[..., None], RING * (0.80 + 0.20 * np.sin(rr * 26.0))[..., None], body)

        # Mond auf einer Umlaufbahn
        phase = 0.7 * t
        mx = 3.3 * math.cos(phase) * ca - 0.9 * math.sin(phase) * sa
        my = 3.3 * math.cos(phase) * sa + 0.9 * math.sin(phase) * ca
        dm = np.hypot(nx - mx, ny - my) / 0.22
        in_moon = (dm < 1.0) & ((math.sin(phase) > 0) | ~disc)
        ball = MOON * (0.35 + 0.65 * np.clip(1.0 - dm * dm, 0, 1) ** 0.5)[..., None]
        body = np.where(in_moon[..., None], ball, body)
        return body, disc | in_ring | in_moon | core

    def put(self, rr, cc, colors, glyph, free, over, col):
        """Feste Zeichen in freie Weltraum-Zellen schreiben."""
        glyph = np.broadcast_to(glyph, rr.shape)
        ok = (rr >= 0) & (rr < self.rows) & (cc >= 0) & (cc < self.cols)
        rr, cc, colors, glyph = rr[ok], cc[ok], colors[ok], glyph[ok]
        keep = free[rr, cc]
        rr, cc = rr[keep], cc[keep]
        over[rr, cc] = glyph[keep]
        col[rr, cc] = np.clip(colors[keep], 0, 255)
        self.glare[rr, cc] = np.clip(colors[keep].max(-1) / 255.0 - 0.35, 0.0, 1.0)

    def to_cell(self, px, py):
        c = np.floor((px + self.half_w) * self.unit_c).astype(np.int64)
        r = np.floor((py + 1.0) * self.unit_r).astype(np.int64)
        return r, c

    def stars(self, t, lz, zspeed, fade, free, over, col):
        """Sterne: funkeln im Stand, werden beim Zoom zu Lichtstreifen."""
        ids = self.ids
        rho = (self.s_rho + self.s_rate * lz * 0.45 + 0.004 * t) % 1.0
        rad = 0.04 + 1.85 * rho ** 1.3
        tw = 0.62 + 0.38 * np.sin(t * self.s_freq + self.s_phase)
        bright = tw * smooth(rho / 0.12) * smooth((1.0 - rho) / 0.05) * fade
        tint = self.s_col * bright[:, None]
        r, c = self.to_cell(self.s_cos * rad, self.s_sin * rad)
        streak = np.clip(zspeed * self.s_rate * 15.0, 0.0, 7.0)          # Laenge in Zellen
        fast = streak >= 1.0
        slow = ~fast

        for j in range(7, 0, -1):                    # Schweif zeigt zur Mitte
            sel = fast & (streak >= j)
            rj, cj = self.to_cell(self.s_cos[sel] * (rad[sel] - 0.03 * j), self.s_sin[sel] * (rad[sel] - 0.03 * j))
            self.put(rj, cj, tint[sel] * (1.0 - j / 8.0), self.s_streak[sel], free, over, col)
        self.put(r[fast], c[fast], tint[fast] * 1.3, ids["*"], free, over, col)

        small, medium, big = (slow & (self.s_kind == k) for k in range(3))
        self.put(r[small], c[small], tint[small] * 0.9, ids["."], free, over, col)
        dim = medium & (tw < 0.6)
        self.put(r[dim], c[dim], tint[dim] * 1.2, ids["."], free, over, col)
        lit = medium & (tw >= 0.6)
        self.put(r[lit], c[lit], tint[lit], ids["+"], free, over, col)
        arm = np.round(self.s_arm * tw).astype(np.int64)
        for k in range(1, 5):                        # Strahlenkreuz der grossen Sterne
            reach = big & (arm >= k)
            for dc in (k, -k):
                self.put(r[reach], c[reach] + dc, tint[reach] * (1.0 - 0.18 * k), ids["-"], free, over, col)
            if k <= 2:
                tall = big & (arm >= 2 * k)
                for dr in (k, -k):
                    self.put(r[tall] + dr, c[tall], tint[tall] * (1.0 - 0.18 * k), ids["|"], free, over, col)
        self.put(r[big], c[big], tint[big] * 1.3, np.where(tw[big] >= 0.6, ids["*"], ids["+"]), free, over, col)

    def meteor(self, t, free, over, col):
        """Alle anderthalb Sekunden eine Sternschnuppe."""
        since = t - self.t_cross - 0.6
        if since < 0:
            return
        n, age = divmod(since, 1.5)
        if age > 0.6:
            return
        rnd = np.random.default_rng(1000 + int(n))
        start = np.array([rnd.uniform(-0.9, 0.9) * self.half_w, rnd.uniform(-0.95, -0.2)])
        going_right = rnd.random() < 0.5
        move = np.array([1.0 if going_right else -1.0, rnd.uniform(0.45, 0.8)])
        move /= np.hypot(*move)
        j = np.arange(18)
        r, c = self.to_cell(start[0] + move[0] * (age * 3.0 - 0.028 * j), start[1] + move[1] * (age * 3.0 - 0.028 * j))
        glow = (1.0 - j / 18.0) * math.sin(math.pi * age / 0.6)
        glyph = np.where(j == 0, self.ids["*"], self.ids["\\"] if going_right else self.ids["/"])
        self.put(r, c, rgb(255, 250, 235) * glow[:, None], glyph, free, over, col)

    # ------------------------------------------------------------------ Einblendungen
    def text(self, row, start, string, color, over, col):
        if not 0 <= row < self.rows:
            return
        for i, c in enumerate(string):
            if c != " " and 0 <= start + i < self.cols:
                over[row, start + i] = self.ids.get(c, self.ids["+"])
                col[row, start + i] = color

    def hud(self, t, zoom, lz, over, col):
        """Scanner-Overlay: Zielrahmen um die Iris, Statuszeilen in den Ecken."""
        show = float(smooth((t - T_OPEN1) / 0.3))
        if show <= 0.0:
            return
        rows, cols = self.rows, self.cols
        locked = t >= T_LOCK
        flash = math.exp(-max(t - T_LOCK, 0.0) / 0.12) if locked else 0.0
        tone = (LOCK + (WHITE - LOCK) * flash if locked else CYAN) * show
        dim = tone * 0.7

        # Statuszeilen
        deep = t > self.t_cross
        state = "DEEP SPACE" if deep else "TRANSIT" if lz > 1.6 else "DIVE" if lz > 0 else "LOCKED" if locked else "SCANNING"
        if (t * 2.0) % 1.0 < 0.6:
            self.text(1, 2, "●", RED * show, over, col)
        self.text(1, 4, "REC", dim, over, col)
        self.text(1, cols - 11, "T+%06.2f" % t, dim, over, col)
        self.text(rows - 2, 2, "ZOOM x%05.2f" % zoom, dim, over, col)
        done = int(18 * min(lz / LN_ZOOM, 1.0))
        self.text(rows - 2, 15, "[" + "=" * done + "·" * (18 - done) + "]", dim, over, col)
        self.text(rows - 2, cols - 2 - len(state), state, tone, over, col)

        # Zielrahmen: zieht sich zusammen, rastet ein und waechst dann mit der Iris aus dem Bild
        size = R_IRIS * 1.25 * zoom * (1.0 + 1.6 * (1.0 - float(smooth((t - T_OPEN1) / (T_LOCK - T_OPEN1)))))
        hy, hx = int(round(size * self.unit_r)), int(round(size * self.unit_c))
        cy, cx = rows // 2, cols // 2
        if hy < cy - 1 and hx < cx - 2:
            for sy, sx, corner in ((-1, -1, "┌"), (-1, 1, "┐"), (1, -1, "└"), (1, 1, "┘")):
                row, column = cy + sy * hy, cx + sx * hx
                self.text(row, column, corner, tone, over, col)
                for k in range(1, 7):
                    self.text(row, column - sx * k, "─", tone, over, col)
                for k in range(1, 4):
                    self.text(row - sy * k, column, "│", tone, over, col)
            for k in (-1, 1):                        # Markierungen an den Seitenmitten
                self.text(cy, cx + k * hx, "┼", dim, over, col)
                self.text(cy + k * hy, cx, "┼", dim, over, col)
            hexa = "".join("0123456789ABCDEF"[i] for i in self.rng.integers(0, 16, 8))
            label = "IRIS LOCK" if locked else "SCANNING" + "." * (int(t * 6) % 4)
            code = "7F3A-C91E" if locked else hexa[:4] + "-" + hexa[4:]
            self.text(cy - hy - 2, cx + hx - 8, label, tone, over, col)
            self.text(cy + hy + 2, cx - hx, "ID " + code, dim, over, col)

        # Beschriftung des Planeten
        since = t - self.t_cross - 1.6
        if since > 0:
            fade = WHITE * (0.85 * float(smooth(since / 0.5)))
            row, column = int(rows * 0.80), int(cols * 0.66)
            shown = int(since * 30)
            self.text(row, column, "──── OBJ-01 · RINGED GIANT"[:shown], fade, over, col)
            self.text(row + 1, column + 5, "ΔV 12.4 km/s · R 58 232 km"[:max(shown - 10, 0)], fade * 0.7, over, col)


def distort(img, glitch, rng):
    """Bildstoerung: Farbkanaele reissen auseinander, Streifen verrutschen."""
    k = int(round(glitch * 6))
    if k > 0:
        red, green, blue = img.split()
        img = Image.merge("RGB", (ImageChops.offset(red, k, 0), green, ImageChops.offset(blue, -k, 0)))
    width, height = img.size
    for _ in range(int(glitch * 7)):
        y0 = int(rng.integers(0, height - 4))
        box = (0, y0, width, min(height, y0 + int(rng.integers(3, 40))))
        img.paste(ImageChops.offset(img.crop(box), int(rng.integers(-60, 61) * glitch), 0), box)
    return img


class Renderer:
    """Fliessband aus zwei Hintergrund-Threads: einer rechnet die Szene, einer baut das Bild.

    So arbeiten Szene, Bildaufbau und Anzeige gleichzeitig statt nacheinander.
    """

    def __init__(self, cell_w, cell_h):
        self.glyphs = Glyphs(cell_w, cell_h)
        self.scene = Scene(COLS, ROWS, cell_w, cell_h, self.glyphs.ids)
        self.cells = queue.Queue(maxsize=2)          # Szene -> Bildaufbau
        self.frames = queue.Queue(maxsize=2)         # Bildaufbau -> Fenster
        self.t0 = time.perf_counter()
        self.running = True

    def start(self):
        for job in (self.simulate, self.build):
            threading.Thread(target=self.guard, args=(job,), daemon=True).start()

    def guard(self, job):
        try:
            job()
        except Exception:                            # Fehler ans Fenster melden statt still zu sterben
            self.frames.put(traceback.format_exc())

    def build(self):
        rng = np.random.default_rng()
        while self.running:
            glyph, tint, col, shine, glitch = self.cells.get()
            img = self.glyphs.compose(glyph, tint, col, shine)
            if glitch > 0.05:
                img = distort(img, glitch, rng)
            self.frames.put(img)

    def simulate(self):
        glyphs, scene = self.glyphs, self.scene
        rng = np.random.default_rng()
        variant = rng.integers(0, VARIANTS, (ROWS, COLS))        # welches Zeichen der Stufe
        last = time.perf_counter()
        while self.running:
            now = time.perf_counter()
            dt, last = min(now - last, 0.1), now
            if LOOP and now - self.t0 > T_END + 1.5:
                self.t0 = now
            level, col, over, jitter, glitch, glare = scene.render(now - self.t0, dt)

            # Zeichenwechsel: Zellen wuerfeln ihr Zeichen innerhalb der Helligkeitsstufe neu
            swap = rng.random((ROWS, COLS)) < (1.0 - math.exp(-FLUTTER * dt)) + jitter
            variant[swap] = rng.integers(0, VARIANTS, int(swap.sum()))
            glyph = glyphs.table[level, variant]
            gain = glyphs.gain[level, variant]
            fixed = over >= 0
            glyph[fixed] = over[fixed]
            gain[fixed] = 1.0
            tint = np.minimum(col * gain[..., None], 255.0).astype(np.uint8)
            shine = (col * (BLOOM * glare)[..., None]).astype(np.uint8)
            self.cells.put((glyph, tint, col.astype(np.uint8), shine, glitch))


def tune_windows():
    """Scharfes Bild trotz Bildschirm-Skalierung und ein 1-ms-Timer fuer ruhige Bildfolge."""
    if sys.platform != "win32":
        return
    import ctypes
    for call in (lambda: ctypes.windll.shcore.SetProcessDpiAwareness(1),
                 lambda: ctypes.windll.winmm.timeBeginPeriod(1)):
        try:
            call()
        except Exception:
            pass


def main():
    tune_windows()
    root = tk.Tk()
    root.title("ASCII Eye")
    root.resizable(False, False)
    root.configure(bg="black")

    cell_h = CELL_H or max(11, min(16, int(0.70 * root.winfo_screenheight() / ROWS)))
    cell_w = round(cell_h / 2)
    photo = ImageTk.PhotoImage(Image.new("RGB", (COLS * cell_w, ROWS * cell_h)))
    tk.Label(root, image=photo, bd=0, highlightthickness=0).pack()
    root.update()

    worker = Renderer(cell_w, cell_h)
    worker.start()
    st = {"due": time.perf_counter()}

    def restart(_event=None):
        worker.t0 = time.perf_counter()

    def pump():
        try:
            img = worker.frames.get_nowait()
        except queue.Empty:                          # Bild noch nicht fertig: gleich nochmal schauen
            root.after(1, pump)
            return
        if isinstance(img, str):
            from tkinter import messagebox
            messagebox.showerror("Fehler im Skript", img[-1500:])
            root.destroy()
            return
        photo.paste(img)
        root.update_idletasks()
        now = time.perf_counter()
        st["due"] = max(st["due"] + 1.0 / FPS, now - 0.05)       # festes Raster, ohne aufzuholen
        root.after(max(1, int((st["due"] - now) * 1000)), pump)

    def close(_event=None):
        worker.running = False
        root.destroy()

    root.bind("<space>", restart)
    root.bind("r", restart)
    root.bind("<Escape>", close)
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(10, pump)
    root.mainloop()


if __name__ == "__main__":
    main()

"""Feature Puzzles promo video, with voice-over.

The method part is the project page's two flowcharts, built up element by
element: boxes fade in, connectors draw themselves, then the dashes flow.
Narration comes from macOS `say`; each step lasts as long as its sentence.

usage:
  FFMPEG=<ffmpeg> python -I make_promo.py SITE_DIR OUT_DIR [--voice NAME] [--rate WPM] [segment ...]
  (segments: tts, then any of ORDER, then 'final' to concatenate and mux)
"""
import json, math, os, re, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FF = os.environ["FFMPEG"]
args = sys.argv[1:]
VOICE, RATE = "Samantha", 172
if "--voice" in args: i = args.index("--voice"); VOICE = args[i + 1]; del args[i:i + 2]
if "--rate" in args: i = args.index("--rate"); RATE = int(args[i + 1]); del args[i:i + 2]
SITE, OUT = args[0], args[1]
ONLY = args[2:]
W, H, FPS, SR = 1920, 1080, 30, 48000
for sub in ("seg", "vo"): os.makedirs(os.path.join(OUT, sub), exist_ok=True)
MAN = json.load(open(os.path.join(SITE, "data/manifest.json")))

BG = (8, 9, 12); CARD = (18, 20, 27); LINE = (34, 38, 47)
FG = (233, 236, 242); DIM = (154, 163, 181); FAINT = (106, 114, 133)
ACC = (111, 157, 255); ACC_HI = (147, 182, 255)
GOLD_T = (240, 207, 138); PINK_T = (242, 189, 234)

# ── narration: id -> (spoken, subtitle) ────────────────────────────────────
VO = {
    "title": ("Feature Puzzles: single-image supervision for multi-view, 3D-aware segmentation.", None),
    "mot1": ("We easily recognize the same object from any viewpoint.", None),
    "mot2": ("Teaching a model to do this usually takes videos, or calibrated multi-view captures.", None),
    "mot3": ("We show that single images are enough.", None),
    "ch1": ("First, Feature Puzzles: multi-view supervision from a single image.", None),
    "fa0": ("We start from one single image.", None),
    "fa1": ("We cut it into overlapping crops. Each crop becomes a view, tied to the parent image by a map we chose, so no camera pose is ever estimated.", None),
    "fa2": ("Optionally, estimated depth lifts the crops into 3D, adding real parallax.", None),
    "fa3": ("Labels are computed only once, on the parent image: SAM instance masks, and dense DINO features.", None),
    "fa4": ("We pull the masks back into every view. Each instance is the same object in every crop, so no matching is needed.", None),
    "fa5": ("Features are pulled back the same way, giving every view consistent targets.", None),
    "fa6": ("Wherever two views overlap, they read the same parent label. Consistency holds by construction.", None),
    "ch2": ("Next, the network.", None),
    "nb0": ("A pretrained VGGT Omega backbone encodes the unposed images, with low-rank adapters on its late blocks.",
            "A pretrained VGGT-Omega backbone encodes the unposed images, with low-rank adapters on its late blocks."),
    "nb1": ("Its geometry decoder still predicts camera poses and the point cloud.", None),
    "nb2": ("A mask decoder turns mask, point, or box prompts into masks on every view.", None),
    "nb3": ("A feature decoder predicts dense, multi-view consistent features.", None),
    "nb4": ("Matched against a text prompt, they give open-vocabulary 3D segmentation.", None),
    "ch3": ("Promptable multi-view segmentation. A prompt on one view reaches every view, in a single forward pass.", None),
    "p1": ("Prompts on one frame of an AI-generated video segment the whole reconstruction.", None),
    "p2": ("These clips come with no depth and no poses. The geometry is the backbone's own.", None),
    "p3": ("On ScanNet, every object keeps one identity across all views.", None),
    "p4": ("There is no per-scene optimization, no tracking, and no pairwise matching.", None),
    "p5": ("The same holds on ScanNet plus plus.", "The same holds on ScanNet++."),
    "p6": ("Even cluttered offices stay consistent from view to view.", None),
    "p7": ("In dynamic scenes, a person and the floor are tracked through the whole video.", None),
    "pgrid": ("More scenes, all from one model trained on single images.", None),
    "ch4": ("Open-vocabulary 3D segmentation.", None),
    "o1": ("Text queries are matched against the distilled features, and fused into 3D instances.", None),
    "o2": ("Each object is found once, and consistently, across all views.", None),
    "o3": ("On ScanNet plus plus, the features transfer zero-shot.", "On ScanNet++, the features transfer zero-shot."),
    "o4": ("Every query returns instances in 3D, not just in single frames.", None),
    "o5": ("At building scale, it finds hundreds of instances from free-form queries.", None),
    "ogrid": ("From single rooms to whole buildings.", None),
    "outro": ("Feature Puzzles. More results are on our project page.", None),
}
def subtitle(k): s, d = VO[k]; return d or s

def tts():
    for k, (spoken, _) in VO.items():
        aiff = os.path.join(OUT, "vo", k + ".aiff"); wav = os.path.join(OUT, "vo", k + ".wav")
        subprocess.run(["say", "-v", VOICE, "-r", str(RATE), "-o", aiff, spoken], check=True)
        subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", aiff, "-ac", "1", "-ar", str(SR),
                        "-af", "silenceremove=start_periods=1:start_threshold=-50dB,areverse,silenceremove=start_periods=1:start_threshold=-50dB,areverse",
                        wav], check=True)
        os.remove(aiff)
    print("tts:", {k: round(vo_len(k), 2) for k in VO})

def read_wav(path):
    p = subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-i", path, "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                       capture_output=True, check=True)
    return np.frombuffer(p.stdout, np.float32)
_len = {}
def vo_len(k):
    if k not in _len: _len[k] = len(read_wav(os.path.join(OUT, "vo", k + ".wav"))) / SR
    return _len[k]

# ── fonts / easing ─────────────────────────────────────────────────────────
_fc = {}
FONT_DIR = os.environ.get("PROMO_FONTS", os.path.join(os.path.dirname(os.path.abspath(__file__)), "fonts"))
MATH_FONT = "/System/Library/Fonts/Supplemental/STIXTwoMath.otf"
MATH_CHARS = set("ℓ∘π−")
def serif(size, w="Medium", italic=False):
    """Newsreader, as on the page; optical size follows the pixel size."""
    key = ("s", size, w, italic)
    if key not in _fc:
        op = 72 if size >= 40 else 16
        if italic: fn = f"nr{op}_400i.ttf"
        else: fn = f"nr{op}_" + {"Regular": "400", "Medium": "500", "Semibold": "600"}[w] + ".ttf"
        _fc[key] = ImageFont.truetype(os.path.join(FONT_DIR, fn), size)
    return _fc[key]
def sans(size, face="Regular"):
    """Inter, as on the page."""
    key = ("a", size, face)
    if key not in _fc:
        fn = {"Bold": "in_600", "Demi": "in_600", "Italic": "in_400i", "Medium": "in_500", "Regular": "in_400"}[face]
        _fc[key] = ImageFont.truetype(os.path.join(FONT_DIR, fn + ".ttf"), size)
    return _fc[key]
def mathf(size):
    key = ("m", size)
    if key not in _fc: _fc[key] = ImageFont.truetype(MATH_FONT, size)
    return _fc[key]
def ease(t): t = min(max(t, 0.0), 1.0); return t * t * (3 - 2 * t)
def ramp(t, a, b): return ease((t - a) / max(b - a, 1e-6))

# ── encoder ────────────────────────────────────────────────────────────────
class Seg:
    def __init__(self, name):
        self.name = name; self.path = os.path.join(OUT, "seg", name + ".mp4"); self.vo = []
        self.p = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-x264-params", "aq-mode=3", "-pix_fmt", "yuv420p",
            "-g", "60", "-r", str(FPS), self.path], stdin=subprocess.PIPE)
        self.n = 0
    def say(self, key, at): self.vo.append((round(at, 3), key))
    def put(self, arr):
        if arr.dtype != np.uint8: arr = np.clip(arr, 0, 255).astype(np.uint8)
        self.p.stdin.write(arr.tobytes()); self.n += 1
    def close(self):
        self.p.stdin.close(); self.p.wait()
        json.dump({"frames": self.n, "vo": self.vo}, open(self.path[:-4] + ".json", "w"))
        print(f"  {self.name}: {self.n / FPS:.1f}s", flush=True)

def clip_frames(path, start, dur, w, h):
    vf = f"fps={FPS},scale={w}:{h}:flags=lanczos,setsar=1"
    p = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", path,
                          "-t", str(dur + 0.2), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    need, size, last, out = int(round(dur * FPS)), w * h * 3, None, []
    while len(out) < need:
        b = p.stdout.read(size)
        if len(b) < size: break
        last = np.frombuffer(b, np.uint8).reshape(h, w, 3); out.append(last)
    p.stdout.close(); p.wait()
    if last is None: last = np.zeros((h, w, 3), np.uint8)
    while len(out) < need: out.append(last)
    return out

def probe_aspect(path):
    out = subprocess.run([FF, "-hide_banner", "-i", path], capture_output=True, text=True).stderr
    m = re.search(r"(\d{3,4})x(\d{3,4})", out.split("Video:")[1]); return int(m.group(1)) / int(m.group(2))

# ── 2D helpers ─────────────────────────────────────────────────────────────
def layer(): return Image.new("RGBA", (W, H), (0, 0, 0, 0))
def to_f(img):
    a = np.asarray(img).astype(np.float32); return a[..., :3], a[..., 3:4] / 255.0
def over(base, rgb_a, k=1.0):
    rgb, a = rgb_a
    if k <= 0: return base
    a = a * k; return base * (1 - a) + rgb * a
def rounded_mask(w, h, r):
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], r * 4, fill=255)
    return np.asarray(m.resize((w, h), Image.LANCZOS)).astype(np.float32)[..., None] / 255.0
def paste(base, img, x, y, mask=None, k=1.0):
    h, w = img.shape[:2]; reg = base[y:y + h, x:x + w]
    a = (mask if mask is not None else 1.0) * k
    base[y:y + h, x:x + w] = reg * (1 - a) + img * a; return base
def panel_frame(x, y, w, h, r=14):
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle(
        [x - 2, y + 6, x + w + 2, y + h + 14], r + 4, fill=(0, 0, 0, 150))
    L = sh.filter(ImageFilter.GaussianBlur(14)); d = ImageDraw.Draw(L)
    d.rounded_rectangle([x - 1, y - 1, x + w, y + h], r, outline=LINE + (255,), width=2); return L
def spaced(d, xy, s, font, fill, anchor="la", spacing=0):
    x, y = xy
    total = sum(d.textlength(c, font=font) for c in s) + spacing * (len(s) - 1)
    if anchor[0] == "m": x -= total / 2
    for c in s:
        d.text((x, y), c, font=font, fill=fill, anchor="l" + anchor[1]); x += d.textlength(c, font=font) + spacing
def wrap(d, s, font, width):
    words, lines, cur = s.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= width or not cur: cur = t
        else: lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines
def bg_base():
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = np.exp(-(((xx - W * 0.5) / (W * 0.55)) ** 2 + ((yy + H * 0.1) / (H * 0.7)) ** 2))
    base = np.empty((H, W, 3), np.float32); base[:] = BG
    base += g[..., None] * np.array([10, 16, 34], np.float32); return base
BASE = bg_base()
def fade_k(t, dur, fin=0.45, fout=0.45): return min(ramp(t, 0, fin), 1 - ramp(t, dur - fout, dur))

_subs = {}
def subtitle_layer(key, y0=968, width=1640, size=34):
    if key in _subs: return _subs[key]
    L = layer(); d = ImageDraw.Draw(L); f = sans(size, "Medium")
    lines = wrap(d, subtitle(key), f, width)
    y = y0 - (len(lines) - 1) * 23
    for ln in lines:
        d.text((W / 2 + 2, y + 2), ln, font=f, fill=(0, 0, 0, 160), anchor="mm")
        d.text((W / 2, y), ln, font=f, fill=FG + (255,), anchor="mm"); y += 46
    _subs[key] = to_f(L); return _subs[key]

def chip_row(d, x, y, items, font, maxw):
    cx, cy, hgt = x, y, font.size + 22
    for name, col, n in items:
        label = f"{name}" + (f"  {n}" if n is not None else "")
        tw = d.textlength(label, font=font) + 40
        if cx + tw > x + maxw: cx, cy = x, cy + hgt + 10
        c = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
        d.rounded_rectangle([cx, cy, cx + tw, cy + hgt], hgt // 2, fill=c + (235,))
        d.text((cx + 20, cy + hgt / 2), label, font=font, fill=(255, 255, 255, 255), anchor="lm"); cx += tw + 10
    return cy + hgt

# ── cards ──────────────────────────────────────────────────────────────────
AUTHORS = [("Jiahao Ma", "1"), ("Qiang Zhang", "2"), ("Miaomiao Liu", "1"),
           ("David Ahmedt-Aristizabal", "3"), ("Chuong Nguyen", "3")]
AFFIL = [("1", "Australian National University"), ("2", "University of Science and Technology of China"), ("3", "CSIRO’s Data61")]
def sup_line(d, cy, parts, font, sup, fill):
    total = sum(d.textlength(t, font=sup if s else font) for t, s in parts); x = W / 2 - total / 2
    for t, s in parts:
        f = sup if s else font
        d.text((x, cy - (font.size * 0.38 if s else 0)), t, font=f, fill=fill, anchor="lm"); x += d.textlength(t, font=f)

def seg_title():
    s = Seg("00_title"); dur = max(6.0, vo_len("title") + 2.2)
    L2, L3, L4 = layer(), layer(), layer()
    ImageDraw.Draw(L2).text((W / 2, 420), "Feature Puzzles", font=serif(132, "Medium"), fill=FG, anchor="mm")
    ImageDraw.Draw(L3).text((W / 2, 540), "Single-Image Supervision for Multi-View 3D-Aware Segmentation",
                            font=serif(46, italic=True), fill=DIM, anchor="mm")
    d4 = ImageDraw.Draw(L4); parts = []
    for i, (n, sp) in enumerate(AUTHORS):
        parts += [(n, False), (sp, True)] + ([("     ", False)] if i < len(AUTHORS) - 1 else [])
    sup_line(d4, 670, parts, sans(32, "Medium"), sans(20, "Medium"), FG)
    parts = []
    for i, (sp, n) in enumerate(AFFIL):
        parts += [(sp, True), (n, False)] + ([("      ", False)] if i < len(AFFIL) - 1 else [])
    sup_line(d4, 728, parts, sans(24), sans(16), FAINT)
    Ls = [to_f(x) for x in (L2, L3, L4)]
    s.say("title", 0.6)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for j, l in enumerate(Ls): f = over(f, l, ramp(t, 0.2 + 0.5 * j, 1.0 + 0.5 * j))
        s.put(f * (1 - ramp(t, dur - 0.5, dur)))
    s.close()

def seg_motivation():
    s = Seg("01_motivation")
    t1 = 0.3; t2 = t1 + vo_len("mot1") + 0.35; t3 = t2 + vo_len("mot2") + 0.5; dur = t3 + vo_len("mot3") + 1.4
    L1, L2, L3 = layer(), layer(), layer()
    ImageDraw.Draw(L1).text((W / 2, 400), "We easily recognize the same object from any viewpoint.", font=serif(46, "Regular"), fill=DIM, anchor="mm")
    ImageDraw.Draw(L2).text((W / 2, 490), "Models usually need videos or calibrated multi-view captures.", font=serif(46, "Regular"), fill=DIM, anchor="mm")
    ImageDraw.Draw(L3).text((W / 2, 630), "Single images are enough.", font=serif(64, "Medium", italic=True), fill=ACC_HI, anchor="mm")
    Ls = [to_f(x) for x in (L1, L2, L3)]
    for k, tt in zip(("mot1", "mot2", "mot3"), (t1, t2, t3)): s.say(k, tt)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for l, tt in zip(Ls, (t1, t2, t3)): f = over(f, l, ramp(t, tt - 0.1, tt + 0.6))
        s.put(f * fade_k(t, dur, 0.3, 0.5))
    s.close()

def seg_chapter(name, key, kicker, title, sub):
    s = Seg(name); dur = max(3.0, vo_len(key) + 1.3)
    L = layer(); d = ImageDraw.Draw(L)
    spaced(d, (W / 2, 430), kicker, sans(24, "Demi"), ACC_HI, "mm", spacing=7)
    d.line([W / 2 - 60, 470, W / 2 + 60, 470], fill=ACC + (180,), width=2)
    d.text((W / 2, 525), title, font=serif(84, "Medium"), fill=FG, anchor="mm")
    d.text((W / 2, 625), sub, font=serif(40, italic=True), fill=DIM, anchor="mm")
    l = to_f(L); s.say(key, 0.35)
    for i in range(int(dur * FPS)):
        t = i / FPS; s.put(over(BASE.copy(), l, fade_k(t, dur, 0.5, 0.5)))
    s.close()

def seg_outro():
    s = Seg("99_outro"); dur = max(6.5, vo_len("outro") + 3.0)
    L1, L2 = layer(), layer(); d = ImageDraw.Draw(L1)
    d.text((W / 2, 420), "Feature Puzzles", font=serif(112, "Medium"), fill=FG, anchor="mm")
    d.text((W / 2, 525), "Single-Image Supervision for Multi-View 3D-Aware Segmentation", font=serif(40, italic=True), fill=DIM, anchor="mm")
    ImageDraw.Draw(L2).text((W / 2, 660), "featurepuzzles.github.io", font=sans(42, "Demi"), fill=ACC_HI, anchor="mm")
    a, b = to_f(L1), to_f(L2); s.say("outro", 0.5)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = over(BASE.copy(), a, ramp(t, 0.2, 1.0)); f = over(f, b, ramp(t, 1.2, 2.0))
        s.put(f * (1 - ramp(t, dur - 0.9, dur)))
    s.close()

# ── flowchart engine ───────────────────────────────────────────────────────
# Diagram units are the project page's SVG units; colours are the page's CSS.
STY = {
    "blue": ((111, 157, 255, 26), (111, 157, 255, 184)),
    "gold": ((232, 188, 98, 33), (232, 188, 98, 209)),
    "pink": ((232, 140, 214, 31), (232, 140, 214, 199)),
    "grey": ((233, 236, 242, 10), (233, 236, 242, 82)),
}
FONTS = {  # key -> (factory, size_units, colour, anchor-x)
    "ptitle": (lambda z: sans(z, "Demi"), 15, ACC_HI),
    "lbl":    (lambda z: serif(z, "Semibold"), 20.5, FG),
    "sub":    (lambda z: sans(z, "Italic"), 15.5, (132, 140, 158)),
    "clbl":   (lambda z: sans(z, "Regular"), 15.5, DIM),
    "rlbl":   (lambda z: sans(z, "Demi"), 13.5, DIM),
    "quote":  (lambda z: serif(z, "Regular", italic=True), 20, FG),
    "blbl":   (lambda z: serif(z, "Semibold"), 20, FG),
    "blbl_hi": (lambda z: serif(z, "Semibold"), 20, GOLD_T),
    "blbl_pk": (lambda z: serif(z, "Semibold"), 20, PINK_T),
    "blbl_sm": (lambda z: serif(z, "Semibold"), 17.5, FG),
    "vlbl":   (lambda z: sans(z, "Demi"), 13, GOLD_T),
}
SPACING = {"ptitle": 0.2, "rlbl": 0.1, "vlbl": 0.14}

def runs_of(s):
    """'known map π_{n}' -> [(text, 'n'|'sub'|'sup')]"""
    out, i = [], 0
    for m in re.finditer(r"([_^])\{([^}]*)\}", s):
        if m.start() > i: out.append((s[i:m.start()], "n"))
        out.append((m.group(2), "sub" if m.group(1) == "_" else "sup")); i = m.end()
    if i < len(s): out.append((s[i:], "n"))
    return out

def poly_bezier(p0, c1, c2, p1, n=40):
    pts = []
    for k in range(n + 1):
        u = k / n
        x = (1 - u) ** 3 * p0[0] + 3 * (1 - u) ** 2 * u * c1[0] + 3 * (1 - u) * u * u * c2[0] + u ** 3 * p1[0]
        y = (1 - u) ** 3 * p0[1] + 3 * (1 - u) ** 2 * u * c1[1] + 3 * (1 - u) * u * u * c2[1] + u ** 3 * p1[1]
        pts.append((x, y))
    return pts

def parse_path(d):
    """Subset of SVG path syntax: M, H, V, L, C (absolute). Returns list of polylines."""
    toks = re.findall(r"[MHVLC]|-?\d+(?:\.\d+)?", d)
    polys, cur, pos, i = [], None, (0, 0), 0
    while i < len(toks):
        c = toks[i]; i += 1
        if c == "M":
            pos = (float(toks[i]), float(toks[i + 1])); i += 2; cur = [pos]; polys.append(cur)
        elif c == "H": pos = (float(toks[i]), pos[1]); i += 1; cur.append(pos)
        elif c == "V": pos = (pos[0], float(toks[i])); i += 1; cur.append(pos)
        elif c == "L": pos = (float(toks[i]), float(toks[i + 1])); i += 2; cur.append(pos)
        elif c == "C":
            c1 = (float(toks[i]), float(toks[i + 1])); c2 = (float(toks[i + 2]), float(toks[i + 3]))
            p1 = (float(toks[i + 4]), float(toks[i + 5])); i += 6
            cur.extend(poly_bezier(pos, c1, c2, p1)[1:]); pos = p1
    return polys

class Flow:
    def __init__(self, vw, vh, box):
        self.vw, self.vh = vw, vh
        bx, by, bw, bh = box
        self.S = min(bw / vw, bh / vh); self.SS = 2
        self.ox = bx + (bw - vw * self.S) / 2; self.oy = by
        self.pw, self.ph = round(vw * self.S), round(vh * self.S)
        self.els = []; self.step = 0
    def u(self, v): return v * self.S * self.SS
    def add(self, kind, **kw): kw["kind"] = kind; kw["step"] = self.step; self.els.append(kw); return kw
    def next(self): self.step += 1

    # drawing primitives (all with alpha multiplier a and vertical offset dy in units)
    def _col(self, c, a): return tuple(c[:3]) + (int((c[3] if len(c) > 3 else 255) * a),)
    def draw_text(self, d, img, x, y, s, key, a, anchor="m", dy=0):
        fac, size, col = FONTS[key]
        U = self.u(size)
        fonts = {"n": fac(round(U)), "sub": fac(round(U * 0.7)), "sup": fac(round(U * 0.6))}
        mfont = {"n": mathf(round(U * 1.05)), "sub": mathf(round(U * 0.72)), "sup": mathf(round(U * 0.62))}
        sp = SPACING.get(key, 0) * U
        pieces = []
        for t, k in runs_of(s):
            buf, ism = "", None
            for ch in t:
                m = ch in MATH_CHARS
                if ism is not None and m != ism: pieces.append((buf, k, ism)); buf = ""
                buf += ch; ism = m
            if buf: pieces.append((buf, k, ism))
        def fnt(k, m): return (mfont if m else fonts)[k]
        def adv(t, f): return sum(d.textlength(ch, font=f) + sp for ch in t) if sp else d.textlength(t, font=f)
        total = sum(adv(t, fnt(k, m)) for t, k, m in pieces)
        X = self.u(x) - (total / 2 if anchor == "m" else 0); Y = self.u(y + dy)
        fill = self._col(col, a)
        for t, k, m in pieces:
            f = fnt(k, m)
            yy = Y + (U * 0.22 if k == "sub" else (-U * 0.42 if k == "sup" else 0))
            if sp:
                for ch in t: d.text((X, yy), ch, font=f, fill=fill, anchor="ls"); X += d.textlength(ch, font=f) + sp
            else:
                d.text((X, yy), t, font=f, fill=fill, anchor="ls"); X += d.textlength(t, font=f)

    def draw_el(self, d, img, e, p, t):
        a = ease(p); dy = (1 - ease(p)) * 10
        k = e["kind"]; u = self.u
        if k == "panel":
            d.rounded_rectangle([u(e["x"]), u(e["y"]), u(e["x"] + e["w"]), u(e["y"] + e["h"])], u(14),
                                fill=self._col((14, 16, 21, 235), a), outline=self._col(LINE, a), width=max(2, int(u(1))))
        elif k == "box":
            fill, stroke = STY[e["style"]]
            x0, y0 = u(e["x"]), u(e["y"] + dy)
            d.rounded_rectangle([x0, y0, x0 + u(e["w"]), y0 + u(e["h"])], u(e.get("r", 16)),
                                fill=self._col((14, 16, 21, 255), a), outline=None)
            d.rounded_rectangle([x0, y0, x0 + u(e["w"]), y0 + u(e["h"])], u(e.get("r", 16)),
                                fill=self._col(fill, a), outline=self._col(stroke, a), width=max(2, int(u(1.4))))
            for (tx, ty, s, key) in e.get("texts", []):
                if key == "vlbl": self._vtext(img, tx, ty + dy, s, a)
                else: self.draw_text(d, img, tx, ty, s, key, a, "m", dy)
        elif k == "ghost":
            d.rounded_rectangle([u(e["x"]), u(e["y"] + dy), u(e["x"] + e["w"]), u(e["y"] + e["h"] + dy)], u(8),
                                fill=self._col(CARD, a), outline=self._col((233, 236, 242, 51), a), width=max(2, int(u(1))))
        elif k == "img":
            im = e["_im"]
            if a < 1:
                arr = np.asarray(im).copy(); arr[..., 3] = (arr[..., 3] * a).astype(np.uint8); im = Image.fromarray(arr)
            img.alpha_composite(im, (int(u(e["x"])), int(u(e["y"] + dy))))
            col = (166, 136, 75, int(255 * a)) if e.get("dash") else (233, 236, 242, int(77 * a))
            x0, y0, x1, y1 = u(e["x"]), u(e["y"] + dy), u(e["x"] + e["w"]), u(e["y"] + e["h"] + dy)
            if e.get("dash"): self._dash_rect(d, x0, y0, x1, y1, col)
            else: d.rounded_rectangle([x0, y0, x1, y1], u(e.get("r", 6)), outline=col, width=max(2, int(u(1))))
        elif k == "text":
            self.draw_text(d, img, e["x"], e["y"], e["s"], e["key"], a, e.get("anchor", "m"), dy)
        elif k == "dashrect":
            x0, y0, x1, y1 = u(e["x"]), u(e["y"]), u(e["x"] + e["w"]), u(e["y"] + e["h"])
            self._dash_rect(d, x0, y0, x1, y1, (232, 188, 98, int(191 * a)), dash=u(6), gap=u(5))
        elif k == "oplus":
            cx, cy, r = u(e["cx"]), u(e["cy"]), u(14)
            d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=self._col(CARD, a), outline=self._col(ACC_HI, a), width=max(2, int(u(1.6))))
            q = u(11); w_ = max(2, int(u(1.8)))
            d.line([cx, cy - q, cx, cy + q], fill=self._col(ACC_HI, a), width=w_); d.line([cx - q, cy, cx + q, cy], fill=self._col(ACC_HI, a), width=w_)
        elif k == "path":
            self._path(d, e, p, t)

    def _vtext(self, img, x, y, s, a):
        fac, size, col = FONTS["vlbl"]; f = fac(round(self.u(size)))
        sp = SPACING["vlbl"] * self.u(size)
        tw = int(sum(ImageDraw.Draw(img).textlength(c, font=f) + sp for c in s)) + 4
        th = int(self.u(size) * 1.6)
        t_im = Image.new("RGBA", (tw, th), (0, 0, 0, 0)); td = ImageDraw.Draw(t_im)
        spaced(td, (tw / 2, th / 2), s, f, self._col(col, a), "mm", spacing=sp)
        r = t_im.rotate(90, expand=True)
        img.alpha_composite(r, (int(self.u(x) - r.width / 2), int(self.u(y) - r.height / 2)))

    def _dash_rect(self, d, x0, y0, x1, y1, col, dash=None, gap=None):
        dash = dash or self.u(5); gap = gap or self.u(4); w_ = max(2, int(self.u(1.6)))
        for (ax, ay, bx, by) in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
            L = math.hypot(bx - ax, by - ay); s_ = 0
            while s_ < L:
                e_ = min(s_ + dash, L)
                d.line([ax + (bx - ax) * s_ / L, ay + (by - ay) * s_ / L, ax + (bx - ax) * e_ / L, ay + (by - ay) * e_ / L], fill=col, width=w_)
                s_ += dash + gap

    def _path(self, d, e, p, t):
        polys = e["_polys"]; solid = e.get("solid"); arrow = e.get("arrow", True)
        total = sum(e["_lens"]); drawn = total * ease(p)
        col = (147, 182, 255, int(255 * (0.75 if solid else 1.0)))
        w_ = max(2, int(self.u(1.6)))
        dash, gap = self.u(5), self.u(5)
        off = (t * self.u(20) / 1.1) % (dash + gap)
        acc = 0
        tip = None
        for poly, L in zip(polys, e["_lens"]):
            if acc >= drawn: break
            avail = drawn - acc
            pts = [(self.u(x), self.u(y)) for x, y in poly]
            # walk the polyline up to `avail` (in units -> px)
            remaining = self.u(avail); s_cur = 0
            for (ax, ay), (bx, by) in zip(pts[:-1], pts[1:]):
                seg = math.hypot(bx - ax, by - ay)
                if seg == 0: continue
                use = min(seg, remaining)
                ex, ey = ax + (bx - ax) * use / seg, ay + (by - ay) * use / seg
                if solid:
                    d.line([ax, ay, ex, ey], fill=col, width=w_)
                else:
                    # dashes positioned by global arc length so they flow continuously
                    s0 = s_cur
                    k0 = math.floor((s0 + off) / (dash + gap)) - 1
                    while True:
                        ds = k0 * (dash + gap) - off; de = ds + dash; k0 += 1
                        if ds > s0 + use: break
                        a_ = max(ds, s0); b_ = min(de, s0 + use)
                        if b_ > a_:
                            fa, fb = (a_ - s0) / seg, (b_ - s0) / seg
                            d.line([ax + (bx - ax) * fa, ay + (by - ay) * fa, ax + (bx - ax) * fb, ay + (by - ay) * fb], fill=col, width=w_)
                tip = (ex, ey, bx - ax, by - ay)
                s_cur += use; remaining -= use
                if remaining <= 0: break
            acc += L
        if arrow and tip and p > 0.9:
            ex, ey, dx, dy_ = tip; n = math.hypot(dx, dy_) or 1; dx, dy_ = dx / n, dy_ / n
            L, Hh = self.u(6.5), self.u(4.5)
            bx, by = ex - dx * L, ey - dy_ * L
            ca = (147, 182, 255, int(255 * ramp(p, 0.9, 1.0)))
            d.line([bx - dy_ * Hh, by + dx * Hh, ex, ey], fill=ca, width=w_); d.line([bx + dy_ * Hh, by - dx * Hh, ex, ey], fill=ca, width=w_)

    def prepare(self):
        for e in self.els:
            if e["kind"] == "img":
                w, h = int(self.u(e["w"])), int(self.u(e["h"]))
                im = Image.open(os.path.join(SITE, e["src"])).convert("RGB")
                # cover-fit
                sc = max(w / im.width, h / im.height); im = im.resize((math.ceil(im.width * sc), math.ceil(im.height * sc)), Image.LANCZOS)
                l, t_ = (im.width - w) // 2, (im.height - h) // 2; im = im.crop((l, t_, l + w, t_ + h)).convert("RGBA")
                m = Image.new("L", (w, h), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w - 1, h - 1], int(self.u(e.get("r", 6))), fill=255)
                im.putalpha(m); e["_im"] = im
            if e["kind"] == "path":
                e["_polys"] = parse_path(e["d"])
                e["_lens"] = [sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pl[:-1], pl[1:])) for pl in e["_polys"]]

def seg_flow(name, flow, keys, tail=1.2):
    """Render a Flow; step k is narrated by keys[k]."""
    flow.prepare()
    s = Seg(name)
    nsteps = max(e["step"] for e in flow.els) + 1
    assert nsteps == len(keys), (nsteps, len(keys))
    starts, t = [], 0.4
    for k in range(nsteps):
        els = [e for e in flow.els if e["step"] == k]
        vl = vo_len(keys[k])
        stagger = min(0.24, max(0.08, vl * 0.65 / max(len(els), 1)))
        for i, e in enumerate(els):
            e["_t0"] = t + 0.1 + i * stagger
            e["_dur"] = 0.6 if e["kind"] == "path" else 0.5
        end_anim = max(e["_t0"] + e["_dur"] for e in els)
        starts.append(t); s.say(keys[k], t + 0.15)
        t = max(t + vl + 0.75, end_anim + 0.4)
    dur = t + tail
    starts.append(dur)
    SS = flow.SS
    cw, ch = int(flow.u(flow.vw)), int(flow.u(flow.vh))
    static, static_set = Image.new("RGBA", (cw, ch), (0, 0, 0, 0)), set()
    for i in range(int(dur * FPS)):
        tt = i / FPS
        done = [j for j, e in enumerate(flow.els) if e["kind"] != "path" and tt >= e["_t0"] + e["_dur"]]
        if set(done) != static_set:
            static = Image.new("RGBA", (cw, ch), (0, 0, 0, 0)); sd = ImageDraw.Draw(static, "RGBA")
            for j in done: flow.draw_el(sd, static, flow.els[j], 1.0, tt)
            static_set = set(done)
        img = static.copy(); d = ImageDraw.Draw(img, "RGBA")
        for j, e in enumerate(flow.els):
            if j in static_set: continue
            p = (tt - e["_t0"]) / e["_dur"]
            if p <= 0: continue
            flow.draw_el(d, img, e, min(p, 1.0), tt)
        small = img.resize((flow.pw, flow.ph), Image.BOX)
        arr = np.asarray(small).astype(np.float32)
        f = BASE.copy()
        x0, y0 = int(flow.ox), int(flow.oy)
        reg = f[y0:y0 + flow.ph, x0:x0 + flow.pw]; a = arr[..., 3:4] / 255.0
        f[y0:y0 + flow.ph, x0:x0 + flow.pw] = reg * (1 - a) + arr[..., :3] * a
        k = max(j for j in range(nsteps) if tt >= starts[j] or j == 0)
        lt = tt - starts[k]
        if k > 0 and lt < 0.35: f = over(f, subtitle_layer(keys[k - 1]), 1 - ramp(lt, 0, 0.3))
        f = over(f, subtitle_layer(keys[k]), ramp(lt, 0.05, 0.4))
        s.put(f * fade_k(tt, dur, 0.4, 0.5))
    s.close()

def flow_puzzles():
    F = Flow(1400, 640, (40, 26, 1840, 860))
    F.add("panel", x=10, y=10, w=1380, h=620)
    F.add("text", x=34, y=46, s="FEATURE PUZZLES  ·  ONE IMAGE, MANY CONSISTENT VIEWS", key="ptitle", anchor="l")
    F.add("img", src="media/method/parent.jpg", x=40, y=76, w=300, h=227, r=8)
    F.add("text", x=190, y=332, s="Parent image", key="lbl")
    F.add("text", x=190, y=354, s="one RGB(-D) image", key="sub")
    F.next()  # 1: crops -> views
    F.add("img", src="media/method/parent_crops.jpg", x=40, y=76, w=300, h=227, r=8)
    F.add("path", d="M340 187H380")
    F.add("box", style="gold", x=384, y=120, w=176, h=134,
          texts=[(472, 176, "Crop & warp", "blbl_hi"), (472, 204, "known map π_{n}", "sub"), (472, 226, "no pose estimation", "sub")])
    F.add("path", d="M560 187C628 187 628 156 690 156")
    F.add("text", x=700, y=88, s="VIEWS  x_{1} … x_{N}", key="rlbl", anchor="l")
    for j, (n, x) in enumerate(zip((1, 2, 3, 4, 6, 7), (700, 812, 924, 1036, 1148, 1260))):
        F.add("img", src=f"media/method/tile_rgb_{n}.jpg", x=x, y=104, w=104, h=104, r=5)
    F.next()  # 2: optional 3D
    F.add("path", d="M472 254V278")
    F.add("img", src="media/method/aug3d.jpg", x=392, y=284, w=160, h=133, r=6, dash=True)
    F.add("text", x=472, y=440, s="optional: depth + 6-DoF", key="sub")
    F.add("text", x=472, y=460, s="3D augmentation", key="sub")
    F.next()  # 3: labels on the parent
    F.add("text", x=40, y=404, s="labelled once, on the parent", key="clbl", anchor="l")
    F.add("img", src="media/method/sam.jpg", x=40, y=418, w=144, h=109, r=6)
    F.add("text", x=112, y=552, s="SAM masks", key="sub")
    F.add("img", src="media/method/dino.jpg", x=196, y=418, w=144, h=109, r=6)
    F.add("text", x=268, y=552, s="DINO features", key="sub")
    F.next()  # 4: pull back masks
    F.add("path", d="M340 472C362 472 362 536 380 536")
    F.add("box", style="pink", x=384, y=486, w=176, h=100,
          texts=[(472, 530, "Pull back", "blbl_pk"), (472, 558, "ℓ ∘ π_{n} into each view", "sub")])
    F.add("path", d="M560 522C630 522 630 320 690 320")
    F.add("text", x=700, y=252, s="MASKS  ·  instance m is the same object in every view", key="rlbl", anchor="l")
    for n, x in zip((1, 2, 3, 4, 6, 7), (700, 812, 924, 1036, 1148, 1260)):
        F.add("img", src=f"media/method/tile_mask_{n}.jpg", x=x, y=268, w=104, h=104, r=5)
    F.next()  # 5: pull back features
    F.add("path", d="M560 550C630 550 630 484 690 484")
    F.add("text", x=700, y=416, s="FEATURES  ·  DINO targets from the parent", key="rlbl", anchor="l")
    for n, x in zip((1, 2, 3, 4, 6, 7), (700, 812, 924, 1036, 1148, 1260)):
        F.add("img", src=f"media/method/tile_feat_{n}.jpg", x=x, y=432, w=104, h=104, r=5)
    F.next()  # 6: consistency
    for y in (99, 263, 427): F.add("dashrect", x=695, y=y, w=114, h=114)
    F.add("text", x=1032, y=596, s="ℓ_{i}(π_{i}^{−1}(p)) = ℓ_{j}(π_{j}^{−1}(p)) = ℓ(p)   ·   every overlap agrees by construction", key="quote")
    return F

def flow_network():
    F = Flow(1400, 700, (40, 22, 1840, 862))
    F.add("panel", x=10, y=10, w=1380, h=680)
    F.add("text", x=34, y=46, s="NETWORK  ·  ONE BACKBONE, THREE DECODERS", key="ptitle", anchor="l")
    F.add("ghost", x=68, y=186, w=156, h=151); F.add("ghost", x=58, y=196, w=156, h=151)
    F.add("img", src="media/method/net_input.jpg", x=48, y=206, w=156, h=151, r=8)
    F.add("text", x=130, y=392, s="Unposed images", key="lbl")
    F.add("path", d="M210 282H246")
    F.add("box", style="blue", x=250, y=192, w=150, h=180, texts=[(325, 276, "Image", "blbl"), (325, 300, "Encoder", "blbl")])
    F.add("path", d="M400 282H416")
    F.add("box", style="blue", x=420, y=192, w=150, h=180, texts=[(495, 278, "Aggregator", "blbl"), (495, 304, "cross-view", "sub")])
    F.add("box", style="gold", x=578, y=192, w=22, h=180, r=6, texts=[(589, 282, "LoRA", "vlbl")])
    F.add("text", x=425, y=174, s="pretrained VGGT-Omega backbone", key="sub")
    F.next()  # 1: geometry
    F.add("path", d="M600 282H640V100H676", solid=False)
    F.add("box", style="grey", x=680, y=58, w=210, h=84, r=14, texts=[(785, 96, "Geometry Decoder", "blbl"), (785, 122, "unchanged", "sub")])
    F.add("path", d="M890 100H926")
    F.add("img", src="media/method/net_pointcloud.jpg", x=930, y=28, w=236, h=144, r=8)
    F.add("text", x=1290, y=94, s="Camera poses", key="lbl"); F.add("text", x=1290, y=118, s="& point cloud", key="lbl")
    F.next()  # 2: mask
    F.add("path", d="M640 282V270H676")
    F.add("box", style="pink", x=680, y=228, w=210, h=84, r=14, texts=[(785, 276, "Mask Decoder", "blbl_pk")])
    F.add("box", style="blue", x=680, y=334, w=210, h=60, r=12, texts=[(785, 360, "Prompt Encoder", "blbl_sm"), (785, 382, "mask · points · box", "sub")])
    F.add("path", d="M785 334V316")
    F.add("path", d="M890 270H926")
    for x, n in zip((930, 1028, 1126), (1, 2, 3)): F.add("img", src=f"media/method/net_mask_{n}.jpg", x=x, y=225, w=90, h=90, r=6)
    F.add("text", x=1300, y=264, s="Prompted masks", key="lbl"); F.add("text", x=1300, y=288, s="every view, one pass", key="sub")
    F.next()  # 3: feature
    F.add("path", d="M640 282V462H676")
    F.add("box", style="pink", x=680, y=420, w=210, h=84, r=14, texts=[(785, 468, "Feature Decoder", "blbl_pk")])
    F.add("path", d="M890 462H926")
    for x, n in zip((930, 1028, 1126), (1, 2, 3)): F.add("img", src=f"media/method/net_feat_{n}.jpg", x=x, y=417, w=90, h=90, r=6)
    F.add("text", x=1300, y=456, s="Dense features", key="lbl"); F.add("text", x=1300, y=480, s="multi-view consistent", key="sub")
    F.next()  # 4: open vocabulary
    F.add("box", style="blue", x=680, y=560, w=210, h=60, r=12, texts=[(785, 586, "Text Prompt Encoder", "blbl_sm"), (785, 608, "“sofa”", "sub")])
    F.add("path", d="M890 590H894")
    F.add("path", d="M975 507V538H912V572")
    F.add("oplus", cx=912, cy=590)
    F.add("path", d="M926 590H940")
    for x, n in zip((946, 1044, 1142), (1, 2, 3)): F.add("img", src=f"media/method/net_ov_{n}.jpg", x=x, y=545, w=90, h=90, r=6)
    F.add("text", x=1310, y=584, s="Open-vocabulary", key="lbl"); F.add("text", x=1310, y=608, s="3D masks", key="lbl")
    return F

# ── result clips ───────────────────────────────────────────────────────────
def scene(task, sid):
    for t in MAN["tasks"]:
        if t["id"] != task: continue
        for g in t["groups"]:
            for sc in g["scenes"]:
                if sc["id"] == sid: return g, sc
    raise KeyError(sid)

def head_layer(tag, title, x0):
    L = layer(); d = ImageDraw.Draw(L); tf = sans(22, "Demi")
    tw = d.textlength(tag, font=tf) + 34
    d.rounded_rectangle([x0, 46, x0 + tw, 84], 19, fill=ACC + (60,), outline=ACC + (200,), width=2)
    d.text((x0 + tw / 2, 65), tag, font=tf, fill=ACC_HI + (255,), anchor="mm")
    tfont = sans(34, "Demi") if "_" in title else serif(38, "Medium")
    d.text((x0 + tw + 20, 66), title, font=tfont, fill=FG + (255,), anchor="lm")
    return L

def seg_clip(name, key, task, sid, start, base_dur, mode="follow"):
    g, sc = scene(task, sid)
    s = Seg(name); dur = max(base_dur, vo_len(key) + 2.2)
    if task == "promptable":
        main = sc["modes"]["hl"]["bev" if mode == "bev" else "follow"]
        side = [("vid", sc["rgb"], "INPUT VIDEO")]
        if not sc["dynamic"]: side.insert(0, ("img", sc["reference"], "PROMPTED VIEW"))
        chips = [(p["name"], p["color"], None) for p in (sc.get("prompts") or [])]; chips_title = "PROMPTS" if chips else None
        title = sc["name"] if sc["family"] not in ("ScanNet", "ScanNet++") else sc["id"]
    else:
        main = sc[mode]; side = [("vid", sc["input"], "INPUT VIDEO")]
        q = sorted([(x["name"], x["color"], x["n"]) for x in sc["queries"] if x["n"] > 0], key=lambda z: -z[2])
        chips = q[:14]; chips_title = "TEXT QUERIES  ·  INSTANCES"
        title = sc["id"] if g["id"] != "farm" else f"Building scale  ·  {sc['stats']['instances']} instances"
    aspect = probe_aspect(os.path.join(SITE, main))
    mh = 790; mw = round(mh * aspect); mx, my = 40, 116
    sx = mx + mw + 30; sw = W - 40 - sx
    mmask = rounded_mask(mw, mh, 14)
    main_f = clip_frames(os.path.join(SITE, main), start, dur, mw, mh)
    layers = [to_f(panel_frame(mx, my, mw, mh))]
    items, y, labels = [], my + 30, []
    for kind, path, lab in side:
        if kind == "img":
            im = Image.open(os.path.join(SITE, path)).convert("RGB"); asp = im.width / im.height
        else: asp = probe_aspect(os.path.join(SITE, path))
        ww = sw; hh = round(ww / asp); maxh = 430 if len(side) == 1 else 330
        if hh > maxh: hh = maxh; ww = round(hh * asp)
        xx = sx + (sw - ww) // 2; labels.append((xx, y - 12, lab))
        arr = np.asarray(im.resize((ww, hh), Image.LANCZOS)).astype(np.float32) if kind == "img" else None
        frames = clip_frames(os.path.join(SITE, path), start, dur, ww, hh) if kind == "vid" else None
        items.append((xx, y, ww, hh, rounded_mask(ww, hh, 10), arr, frames))
        layers.append(to_f(panel_frame(xx, y, ww, hh, 10))); y += hh + 58
    L = head_layer(g["label"] if g["id"] != "farm" else "FARM-Scenes", title, mx); d = ImageDraw.Draw(L)
    for (x, yy, t_) in labels: d.text((x, yy), t_, font=sans(20, "Demi"), fill=DIM + (255,), anchor="ls")
    if chips:
        d.text((sx, y - 26), chips_title, font=sans(20, "Demi"), fill=DIM + (255,), anchor="ls")
        chip_row(d, sx, y - 12, chips, sans(21, "Demi"), sw)
    lab = to_f(L); sub = subtitle_layer(key, y0=995)
    s.say(key, 0.6)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for l in layers: f = over(f, l)
        paste(f, main_f[i].astype(np.float32), mx, my, mmask)
        for (xx, yy, ww, hh, mk, arr, frames) in items:
            paste(f, arr if frames is None else frames[i].astype(np.float32), xx, yy, mk)
        f = over(f, lab); f = over(f, sub, ramp(t, 0.4, 0.8))
        s.put(f * fade_k(t, dur, 0.4, 0.4))
    s.close()

def seg_grid(name, key, task, picks, start, dur, heading):
    s = Seg(name); dur = max(dur, vo_len(key) + 2.0)
    tiles = []
    first = scene(task, picks[0][0])[1]
    asp = probe_aspect(os.path.join(SITE, first["modes"]["hl"]["bev"] if task == "promptable" else first["bev"]))
    tw = 590 if asp > 1.5 else 520; th = round(tw / asp); gap = 22
    gx = (W - 3 * tw - 2 * gap) // 2; gy = 120 if asp > 1.5 else 106
    L = layer(); d = ImageDraw.Draw(L)
    d.text((W / 2, 66), heading, font=serif(40, "Medium"), fill=FG + (255,), anchor="mm")
    sh = []
    for i, (sid, mode) in enumerate(picks):
        g, sc = scene(task, sid)
        path = sc["modes"]["hl"][mode] if task == "promptable" else sc[mode]
        x = gx + (i % 3) * (tw + gap); y = gy + (i // 3) * (th + gap)
        tiles.append((x, y, clip_frames(os.path.join(SITE, path), start, dur, tw, th)))
        sh.append(to_f(panel_frame(x, y, tw, th, 12)))
        lab = (sc["name"] if sc["family"] not in ("ScanNet", "ScanNet++") else sc["id"]) if task == "promptable" else sc["id"]
        tag = g["label"] if g["id"] != "farm" else "FARM"
        f_ = sans(19, "Demi"); txt = f"{tag}  ·  {lab}"; w_ = d.textlength(txt, font=f_) + 26
        d.rounded_rectangle([x + 12, y + th - 46, x + 12 + w_, y + th - 14], 16, fill=(8, 9, 12, 190))
        d.text((x + 25, y + th - 30), txt, font=f_, fill=FG + (255,), anchor="lm")
    mask = rounded_mask(tw, th, 12); lab_l = to_f(L); sub = subtitle_layer(key, y0=1012 if asp > 1.5 else 1020)
    s.say(key, 0.6)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for l in sh: f = over(f, l)
        for k, (x, y, fr) in enumerate(tiles):
            paste(f, fr[i].astype(np.float32), x, y, mask, ramp(t, 0.1 * k, 0.1 * k + 0.5))
        f = over(f, lab_l); f = over(f, sub, ramp(t, 0.4, 0.8))
        s.put(f * fade_k(t, dur, 0.4, 0.5))
    s.close()

# ── assembly ───────────────────────────────────────────────────────────────
def final():
    names = [n for n in ORDER_NAMES]
    t, vo_events = 0.0, []
    lst = os.path.join(OUT, "list.txt")
    with open(lst, "w") as fh:
        for n in names:
            meta = json.load(open(os.path.join(OUT, "seg", n + ".json")))
            fh.write(f"file '{os.path.join(OUT, 'seg', n + '.mp4')}'\n")
            for at, k in meta["vo"]: vo_events.append((t + at, k))
            t += meta["frames"] / FPS
    total = t
    audio = np.zeros(int(total * SR) + SR, np.float32)
    for at, k in vo_events:
        w = read_wav(os.path.join(OUT, "vo", k + ".wav")); i0 = int(at * SR)
        audio[i0:i0 + len(w)] += w[:len(audio) - i0]
    pk = np.abs(audio).max() or 1; audio *= 0.89 / pk
    wav = os.path.join(OUT, "voiceover.wav")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
                    "-c:a", "pcm_s16le", wav], input=audio[:int(total * SR)].tobytes(), check=True)
    silent = os.path.join(OUT, "video_silent.mp4")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", silent], check=True)
    outp = os.path.join(OUT, "feature_puzzles_promo.mp4")
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-i", silent, "-i", wav, "-map", "0:v", "-map", "1:a",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ac", "2", "-shortest", "-movflags", "+faststart", outp], check=True)
    subprocess.run([FF, "-hide_banner", "-loglevel", "error", "-y", "-ss", "3.0", "-i", outp, "-frames:v", "1",
                    "-vf", "scale=1280:-2", "-q:v", "3", os.path.join(OUT, "poster.jpg")], check=True)
    print(f"final: {total:.1f}s, {len(vo_events)} narration clips -> {outp}")

PG = [("atlas_living_room", "bev"), ("marble_edit_kitchen_counters", "bev"), ("marble_chisel_bedroom_tuscany", "bev"),
      ("scene0553_00", "bev"), ("02a980c994", "bev"), ("02f25e5fee", "bev")]
OG = [("grandtour_2024-11-25_warehouse", "bev"), ("grandtour_2024-12-09_raw_lidar_s20", "bev"), ("odin1_SDH4and7_0413", "bev"),
      ("scene0389_00", "bev"), ("0452249a1e", "bev"), ("02c2ddee2a", "bev")]
JOBS = [
    ("00_title", seg_title),
    ("01_motivation", seg_motivation),
    ("02_ch1", lambda: seg_chapter("02_ch1", "ch1", "STEP 1  ·  DATA", "Feature Puzzles", "Turning one image into multi-view supervision")),
    ("03_flow_puzzles", lambda: seg_flow("03_flow_puzzles", flow_puzzles(), ["fa0", "fa1", "fa2", "fa3", "fa4", "fa5", "fa6"])),
    ("04_ch2", lambda: seg_chapter("04_ch2", "ch2", "STEP 2  ·  NETWORK", "One backbone, three decoders", "Geometry, promptable masks and open-vocabulary features")),
    ("05_flow_network", lambda: seg_flow("05_flow_network", flow_network(), ["nb0", "nb1", "nb2", "nb3", "nb4"], tail=1.0)),
    ("06_ch3", lambda: seg_chapter("06_ch3", "ch3", "RESULTS", "Promptable Multi-View Segmentation", "Prompt one view, get every view in a single forward pass")),
    ("07_p1", lambda: seg_clip("07_p1", "p1", "promptable", "marble_i2w_living_room", 0, 12)),
    ("08_p2", lambda: seg_clip("08_p2", "p2", "promptable", "marble_chisel_bedroom_scandinavian", 9, 10)),
    ("09_p3", lambda: seg_clip("09_p3", "p3", "promptable", "scene0316_00", 0, 11)),
    ("10_p4", lambda: seg_clip("10_p4", "p4", "promptable", "scene0616_00", 17, 10)),
    ("11_p5", lambda: seg_clip("11_p5", "p5", "promptable", "0373d65cce", 0, 11)),
    ("12_p6", lambda: seg_clip("12_p6", "p6", "promptable", "036bce3393", 15, 10)),
    ("13_p7", lambda: seg_clip("13_p7", "p7", "promptable", "EMDB_35", 2, 10, mode="bev")),
    ("14_pgrid", lambda: seg_grid("14_pgrid", "pgrid", "promptable", PG, 9, 9, "More promptable results")),
    ("15_ch4", lambda: seg_chapter("15_ch4", "ch4", "RESULTS", "Open-Vocabulary 3D Segmentation", "Text queries become 3D instances, from rooms to buildings")),
    ("16_o1", lambda: seg_clip("16_o1", "o1", "openvocab", "scene0000_01", 0.5, 10)),
    ("17_o2", lambda: seg_clip("17_o2", "o2", "openvocab", "scene0616_00", 1.5, 10)),
    ("18_o3", lambda: seg_clip("18_o3", "o3", "openvocab", "0373d65cce", 1.0, 10)),
    ("19_o4", lambda: seg_clip("19_o4", "o4", "openvocab", "00dd871005", 1.0, 10)),
    ("20_o5", lambda: seg_clip("20_o5", "o5", "openvocab", "grandtour_2024-11-11_raw_lidar_s20", 3.0, 11)),
    ("21_ogrid", lambda: seg_grid("21_ogrid", "ogrid", "openvocab", OG, 4, 9, "More open-vocabulary results")),
    ("99_outro", seg_outro),
]
ORDER_NAMES = [n for n, _ in JOBS]

if __name__ == "__main__":
    want = ONLY or ["tts"] + ORDER_NAMES + ["final"]
    if "tts" in want: tts()
    for n, fn in JOBS:
        if n in want or any(n.startswith(w + "_") or n.split("_", 1)[1] == w for w in want):
            print("render", n, flush=True); fn()
    if "final" in want: final()

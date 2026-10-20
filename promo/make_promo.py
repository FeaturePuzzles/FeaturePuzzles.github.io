"""Feature Puzzles promo video.

Every frame is composed in Python and piped to ffmpeg, one mp4 per segment;
the segments share encoder settings and are concatenated losslessly at the end.

usage: python -I promo.py SITE_DIR PAPER_FIG_DIR OUT_DIR [segment ...]
"""
import json, math, os, subprocess, sys
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

FF = os.environ["FFMPEG"]
SITE, FIGS, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
ONLY = set(sys.argv[4:])
W, H, FPS = 1920, 1080, 30
os.makedirs(os.path.join(OUT, "seg"), exist_ok=True)

BG = (8, 9, 12); CARD = (18, 20, 27); LINE = (34, 38, 47)
FG = (233, 236, 242); DIM = (154, 163, 181); FAINT = (106, 114, 133)
ACC = (111, 157, 255); ACC_HI = (147, 182, 255)

def serif(size, w="Medium", italic=False):
    f = ImageFont.truetype("/System/Library/Fonts/NewYork%s.ttf" % ("Italic" if italic else ""), size)
    try: f.set_variation_by_name((w + " Italic") if italic and w != "Regular" else (w if not italic else "Regular Italic"))
    except Exception: pass
    return f
def sans(size, face="Regular"):
    idx = {"Bold": 0, "Demi": 2, "Italic": 4, "Medium": 5, "Regular": 7}[face]
    return ImageFont.truetype("/System/Library/Fonts/Avenir Next.ttc", size, index=idx)

def ease(t):
    t = min(max(t, 0.0), 1.0); return t * t * (3 - 2 * t)
def ramp(t, a, b):
    return ease((t - a) / max(b - a, 1e-6))

# ── encoder ────────────────────────────────────────────────────────────────
class Seg:
    def __init__(self, name):
        self.path = os.path.join(OUT, "seg", name + ".mp4")
        self.p = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
            "-c:v", "libx264", "-preset", "slow", "-crf", "20", "-pix_fmt", "yuv420p",
            "-g", "60", "-r", str(FPS), "-movflags", "+faststart", self.path], stdin=subprocess.PIPE)
        self.n = 0
    def put(self, arr):
        if arr.dtype != np.uint8: arr = np.clip(arr, 0, 255).astype(np.uint8)
        self.p.stdin.write(arr.tobytes()); self.n += 1
    def close(self):
        self.p.stdin.close(); self.p.wait()
        print(f"  {os.path.basename(self.path)}: {self.n / FPS:.1f}s", flush=True)

def clip_frames(path, start, dur, w, h, fit="stretch"):
    """Decode [start, start+dur) at 30 fps, scaled to w x h; holds the last frame if short."""
    vf = f"fps={FPS},scale={w}:{h}:flags=lanczos,setsar=1"
    p = subprocess.Popen([FF, "-hide_banner", "-loglevel", "error", "-ss", str(start), "-i", path,
                          "-t", str(dur), "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         stdout=subprocess.PIPE)
    need, size, last, out = int(round(dur * FPS)), w * h * 3, None, []
    while len(out) < need:
        b = p.stdout.read(size)
        if len(b) < size: break
        last = np.frombuffer(b, np.uint8).reshape(h, w, 3); out.append(last)
    p.stdout.close(); p.wait()
    while len(out) < need: out.append(last)
    return out

# ── drawing helpers ────────────────────────────────────────────────────────
def layer():
    return Image.new("RGBA", (W, H), (0, 0, 0, 0))
def to_f(img):
    a = np.asarray(img).astype(np.float32); return a[..., :3], a[..., 3:4] / 255.0
def over(base, rgb_a, k=1.0):
    rgb, a = rgb_a
    if k <= 0: return base
    a = a * k
    return base * (1 - a) + rgb * a

def text(d, xy, s, font, fill, anchor="la", spacing=0):
    if spacing:
        x, y = xy
        total = sum(d.textlength(c, font=font) for c in s) + spacing * (len(s) - 1)
        if anchor[0] == "m": x -= total / 2
        for c in s:
            d.text((x, y), c, font=font, fill=fill, anchor="l" + anchor[1]); x += d.textlength(c, font=font) + spacing
    else:
        d.text(xy, s, font=font, fill=fill, anchor=anchor)

def wrap(d, s, font, width):
    words, lines, cur = s.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=font) <= width or not cur: cur = t
        else: lines.append(cur); cur = w_
    if cur: lines.append(cur)
    return lines

def rounded_mask(w, h, r):
    m = Image.new("L", (w * 4, h * 4), 0)
    ImageDraw.Draw(m).rounded_rectangle([0, 0, w * 4 - 1, h * 4 - 1], r * 4, fill=255)
    return np.asarray(m.resize((w, h), Image.LANCZOS)).astype(np.float32)[..., None] / 255.0

def paste(base, img, x, y, mask=None, k=1.0):
    h, w = img.shape[:2]
    reg = base[y:y + h, x:x + w]
    a = (mask if mask is not None else 1.0) * k
    base[y:y + h, x:x + w] = reg * (1 - a) + img * a
    return base

def panel_frame(x, y, w, h, r=14):
    """A faint border + soft shadow layer around a panel."""
    L = layer(); d = ImageDraw.Draw(L)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); ImageDraw.Draw(sh).rounded_rectangle(
        [x - 2, y + 6, x + w + 2, y + h + 14], r + 4, fill=(0, 0, 0, 150))
    sh = sh.filter(ImageFilter.GaussianBlur(14))
    L = Image.alpha_composite(sh, L); d = ImageDraw.Draw(L)
    d.rounded_rectangle([x - 1, y - 1, x + w, y + h], r, outline=LINE + (255,), width=2)
    return L

def bg_base():
    """Dark background with a soft blue glow, like the page hero."""
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    g = np.exp(-(((xx - W * 0.5) / (W * 0.55)) ** 2 + ((yy + H * 0.1) / (H * 0.7)) ** 2))
    base = np.empty((H, W, 3), np.float32); base[:] = BG
    base += g[..., None] * np.array([10, 16, 34], np.float32)
    return base
BASE = bg_base()

def fade_k(t, dur, fin=0.45, fout=0.45):
    return min(ramp(t, 0, fin), 1 - ramp(t, dur - fout, dur))

def chip_row(d, x, y, items, font, maxw):
    """Colored query chips; returns the y after the last row."""
    cx, cy, hgt = x, y, font.size + 22
    for name, col, n in items:
        label = f"{name}" + (f"  {n}" if n is not None else "")
        tw = d.textlength(label, font=font) + 40
        if cx + tw > x + maxw: cx, cy = x, cy + hgt + 10
        c = tuple(int(col[i:i + 2], 16) for i in (1, 3, 5))
        d.rounded_rectangle([cx, cy, cx + tw, cy + hgt], hgt // 2, fill=c + (235,))
        d.text((cx + 20, cy + hgt / 2), label, font=font, fill=(255, 255, 255, 255), anchor="lm")
        cx += tw + 10
    return cy + hgt

# ── segments: cards ────────────────────────────────────────────────────────
AUTHORS = [("Jiahao Ma", "1"), ("Qiang Zhang", "2"), ("Miaomiao Liu", "1"),
           ("David Ahmedt-Aristizabal", "3"), ("Chuong Nguyen", "3")]
AFFIL = [("1", "Australian National University"), ("2", "University of Science and Technology of China"), ("3", "CSIRO")]

def author_line(d, cy, font, sup, fill):
    parts = []
    for i, (n, s) in enumerate(AUTHORS):
        parts.append((n, font)); parts.append((s, sup))
        if i < len(AUTHORS) - 1: parts.append(("     ", font))
    total = sum(d.textlength(t, font=f) for t, f in parts)
    x = W / 2 - total / 2
    for t, f in parts:
        dy = -font.size * 0.38 if f is sup else 0
        d.text((x, cy + dy), t, font=f, fill=fill, anchor="lm"); x += d.textlength(t, font=f)

def affil_line(d, cy, font, sup, fill):
    parts = []
    for i, (s, n) in enumerate(AFFIL):
        parts += [(s, sup), (n, font)]
        if i < len(AFFIL) - 1: parts.append(("      ", font))
    total = sum(d.textlength(t, font=f) for t, f in parts)
    x = W / 2 - total / 2
    for t, f in parts:
        dy = -font.size * 0.38 if f is sup else 0
        d.text((x, cy + dy), t, font=f, fill=fill, anchor="lm"); x += d.textlength(t, font=f)

def seg_title():
    s = Seg("00_title"); dur = 5.5
    L1, L2, L3, L4 = layer(), layer(), layer(), layer()
    text(ImageDraw.Draw(L1), (W / 2, 330), "ICLR 2027", sans(24, "Demi"), ACC_HI, "mm", spacing=7)
    text(ImageDraw.Draw(L2), (W / 2, 440), "Feature Puzzles", serif(132, "Medium"), FG, "mm")
    text(ImageDraw.Draw(L3), (W / 2, 560), "Single-Image Supervision for Multi-View 3D-Aware Segmentation",
         serif(46, italic=True), DIM, "mm")
    d4 = ImageDraw.Draw(L4)
    author_line(d4, 690, sans(32, "Medium"), sans(20, "Medium"), FG)
    affil_line(d4, 748, sans(24), sans(16), FAINT)
    Ls = [to_f(x) for x in (L1, L2, L3, L4)]
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for j, l in enumerate(Ls):
            f = over(f, l, ramp(t, 0.2 + 0.45 * j, 1.0 + 0.45 * j))
        s.put(f * (1 - ramp(t, dur - 0.5, dur)))
    s.close()

def seg_motivation():
    s = Seg("01_motivation"); dur = 6.0
    L1, L2, L3 = layer(), layer(), layer()
    d = ImageDraw.Draw(L1)
    for k, ln in enumerate(["Recognizing the same object across viewpoints is easy for us.",
                            "Teaching it to a model usually takes videos or calibrated multi-view captures."]):
        text(d, (W / 2, 395 + k * 66), ln, serif(44, "Regular"), DIM, "mm")
    text(ImageDraw.Draw(L2), (W / 2, 590), "Can single images teach multi-view-consistent segmentation?",
         serif(52, "Medium", italic=True), FG, "mm")
    text(ImageDraw.Draw(L3), (W / 2, 680), "Feature Puzzles: yes — no video, no multi-view labels.",
         sans(32, "Demi"), ACC_HI, "mm")
    Ls = [to_f(x) for x in (L1, L2, L3)]
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        f = over(f, Ls[0], ramp(t, 0.1, 0.8)); f = over(f, Ls[1], ramp(t, 1.8, 2.6)); f = over(f, Ls[2], ramp(t, 3.2, 3.9))
        s.put(f * fade_k(t, dur, 0.3, 0.5))
    s.close()

def seg_chapter(name, kicker, title, sub, dur=3.2):
    s = Seg(name)
    L = layer(); d = ImageDraw.Draw(L)
    text(d, (W / 2, 430), kicker, sans(24, "Demi"), ACC_HI, "mm", spacing=7)
    text(d, (W / 2, 520), title, serif(84, "Medium"), FG, "mm")
    text(d, (W / 2, 620), sub, serif(40, italic=True), DIM, "mm")
    d.line([W / 2 - 60, 470, W / 2 + 60, 470], fill=ACC + (180,), width=2)
    l = to_f(L)
    for i in range(int(dur * FPS)):
        t = i / FPS
        s.put(over(BASE.copy(), l, fade_k(t, dur, 0.5, 0.5)))
    s.close()

def seg_outro():
    s = Seg("99_outro"); dur = 6.0
    L1, L2 = layer(), layer()
    d = ImageDraw.Draw(L1)
    text(d, (W / 2, 420), "Feature Puzzles", serif(112, "Medium"), FG, "mm")
    text(d, (W / 2, 525), "Single-Image Supervision for Multi-View 3D-Aware Segmentation", serif(40, italic=True), DIM, "mm")
    d2 = ImageDraw.Draw(L2)
    text(d2, (W / 2, 650), "featurepuzzles.github.io", sans(40, "Demi"), ACC_HI, "mm")
    text(d2, (W / 2, 720), "ICLR 2027", sans(24, "Demi"), FAINT, "mm", spacing=7)
    a, b = to_f(L1), to_f(L2)
    for i in range(int(dur * FPS)):
        t = i / FPS
        f = over(BASE.copy(), a, ramp(t, 0.2, 1.0)); f = over(f, b, ramp(t, 1.0, 1.8))
        s.put(f * (1 - ramp(t, dur - 0.8, dur)))
    s.close()

# ── segments: step-by-step figure walkthrough ──────────────────────────────
def seg_figure(name, fig_path, work_w, steps, kicker, step_dur=3.8, max_zoom=1.7, ghost=0.07):
    """Build a paper figure up region by region, camera easing onto each new part.

    steps: list of dicts {regions: [[x0,y0,x1,y1], ...] in figure px (or 'all'),
                          caption: str, stagger: seconds between regions, zoom: bool}
    """
    s = Seg(name)
    src = Image.open(fig_path).convert("RGB")
    sc = work_w / src.width
    fig = np.asarray(src.resize((work_w, round(src.height * sc)), Image.LANCZOS)).astype(np.float32)
    fh, fw = fig.shape[:2]
    white = np.full_like(fig, 255.0)
    # card geometry: fits the full figure, leaves room for the caption
    ch = 800; cw = round(ch * fw / fh)
    if cw > 1760: cw = 1760; ch = round(cw * fh / fw)
    cx, cy = (W - cw) // 2, 60
    cmask = rounded_mask(cw, ch, 18)
    frame_l = to_f(panel_frame(cx, cy, cw, ch, 18))
    # per-region reveal schedule
    sched = []  # (x0,y0,x1,y1, t_start)
    views = []
    for k, st in enumerate(steps):
        t0 = k * step_dur
        regs = st["regions"]
        if regs == "all": regs = [[0, 0, fw / sc, fh / sc]]
        for j, r in enumerate(regs):
            sched.append(([v * sc for v in r], t0 + 0.45 + j * st.get("stagger", 0)))
        # camera target
        if st.get("zoom", True) and st["regions"] != "all":
            xs = [v for r in regs for v in (r[0], r[2])]; ys = [v for r in regs for v in (r[1], r[3])]
            x0, x1, y0, y1 = min(xs) * sc, max(xs) * sc, min(ys) * sc, max(ys) * sc
            pad = 0.12
            bw, bh = (x1 - x0) * (1 + pad * 2), (y1 - y0) * (1 + pad * 2)
            asp = fw / fh
            vw = max(bw, bh * asp, fw / max_zoom); vh = vw / asp
            if vh > fh: vh = fh; vw = vh * asp
            mx, my = (x0 + x1) / 2, (y0 + y1) / 2
            vx = min(max(mx - vw / 2, 0), fw - vw); vy = min(max(my - vh / 2, 0), fh - vh)
            views.append((vx, vy, vw, vh))
        else:
            views.append((0, 0, fw, fh))
    total = len(steps) * step_dur + 0.6
    # captions
    caps = []
    for k, st in enumerate(steps):
        L = layer(); d = ImageDraw.Draw(L)
        fnt = sans(36, "Medium")
        lines = wrap(d, st["caption"], fnt, 1500)
        y = 932 if len(lines) == 1 else 912
        for ln in lines:
            d.text((W / 2, y), ln, font=fnt, fill=FG + (255,), anchor="mm"); y += 50
        caps.append(to_f(L))
    head = layer(); hd = ImageDraw.Draw(head)
    head_l = None
    # progress dots
    def dots(k):
        L = layer(); d = ImageDraw.Draw(L)
        n = len(steps); gap = 26; x0 = W / 2 - (n - 1) * gap / 2
        for i in range(n):
            r = 6 if i == k else 4
            col = ACC_HI if i == k else (FAINT if i < k else LINE)
            d.ellipse([x0 + i * gap - r, 1040 - r, x0 + i * gap + r, 1040 + r], fill=col + (255,))
        return to_f(L)
    dot_l = [dots(k) for k in range(len(steps))]
    yy, xx = np.mgrid[0:fh, 0:fw].astype(np.float32)
    for i in range(int(total * FPS)):
        t = i / FPS
        k = min(int(t // step_dur), len(steps) - 1)
        lt = t - k * step_dur
        # reveal mask
        a = np.full((fh, fw, 1), ghost, np.float32)
        for (x0, y0, x1, y1), ts in sched:
            v = ramp(t, ts, ts + 0.7)
            if v <= 0: continue
            xi0, yi0, xi1, yi1 = int(x0), int(y0), int(math.ceil(x1)), int(math.ceil(y1))
            a[yi0:yi1, xi0:xi1] = np.maximum(a[yi0:yi1, xi0:xi1], ghost + (1 - ghost) * v)
        comp = white * (1 - a) + fig * a
        img = Image.fromarray(comp.astype(np.uint8))
        # highlight the regions of the current step
        st = steps[k]
        if st["regions"] != "all":
            hk = ramp(lt, 0.3, 0.8) * (1 - ramp(lt, step_dur - 0.6, step_dur))
            if hk > 0:
                ov = Image.new("RGBA", img.size, (0, 0, 0, 0)); od = ImageDraw.Draw(ov)
                for r in st["regions"]:
                    x0, y0, x1, y1 = [v * sc for v in r]
                    od.rounded_rectangle([x0 + 2, y0 + 2, x1 - 2, y1 - 2], max(6, int(10 * fw / 1800)),
                                         outline=ACC + (int(235 * hk),), width=max(3, int(4 * fw / 1800)))
                img = Image.alpha_composite(img.convert("RGBA"), ov).convert("RGB")
        # camera
        pv = views[k - 1] if k > 0 else (0, 0, fw, fh)
        e = ease(lt / 0.9)
        vx, vy, vw, vh = [p + (q - p) * e for p, q in zip(pv, views[k])]
        crop = np.asarray(img.resize((cw, ch), Image.BICUBIC, box=(vx, vy, vx + vw, vy + vh))).astype(np.float32)
        f = BASE.copy()
        f = over(f, frame_l)
        paste(f, crop, cx, cy, cmask)
        # caption crossfade
        ck = ramp(lt, 0.15, 0.6)
        if k > 0 and lt < 0.4: f = over(f, caps[k - 1], 1 - ramp(lt, 0, 0.3))
        f = over(f, caps[k], ck)
        f = over(f, dot_l[k])
        f *= fade_k(t, total, 0.4, 0.5)
        s.put(f)
    s.close()

# figure 2: Feature Puzzles pipeline (1738 x 905 source px)
TX = [190 + 187.5 * i for i in range(9)]
def row(y0, y1, label=True):
    regs = ([[0, y0, 190, y1]] if label else []) + [[TX[i], y0, TX[i + 1], y1] for i in range(8)]
    return regs
FIG2_STEPS = [
    dict(regions=[[4, 4, 372, 324]], caption="Start from one single image, with depth estimated by a monocular model."),
    dict(regions=[[372, 16, 737, 324]], caption="Sample overlapping crops: a puzzle of synthetic views of the same scene."),
    dict(regions=[[737, 10, 1072, 340]], caption="Optionally lift the crops to 3D: calibrate each camera and add 6-DoF augmentation for real parallax."),
    dict(regions=row(336, 529), stagger=0.12, zoom=False, caption="Every crop becomes a view, tied to the parent image by a transform we know exactly."),
    dict(regions=[[1072, 16, 1420, 324]], caption="Label the parent image once, with noisy SAM instance masks ..."),
    dict(regions=row(529, 721), stagger=0.12, zoom=False, caption="... and pull them back into every crop: the same object keeps the same ID in every view."),
    dict(regions=[[1420, 16, 1738, 324]], caption="Dense DINO features are computed once, on the whole parent image ..."),
    dict(regions=row(721, 905), stagger=0.12, zoom=False, caption="... and pulled back the same way, so overlapping views share exactly the same targets."),
    dict(regions="all", caption="One image becomes a multi-view training sample. No video, no multi-view labels."),
]
# figure 3: network (5000 x 2757 source px; boxes measured on a 2000-wide view, x2.5)
def r3(x0, y0, x1, y1): return [x0 * 2.5, y0 * 2.5, x1 * 2.5, y1 * 2.5]
FIG3_STEPS = [
    dict(regions=[r3(50, 18, 390, 370)], caption="Input: a set of unposed images of a scene."),
    dict(regions=[r3(392, 58, 950, 292)], caption="A pretrained VGGT-Omega encoder and aggregator mix information across all views."),
    dict(regions=[r3(950, 6, 1888, 300)], caption="Its geometry decoder still returns camera poses and the point cloud: low-rank adapters switch off at inference."),
    dict(regions=[r3(950, 300, 1935, 642)], caption="Mask decoder: a mask, point or box prompt on any view returns that object's mask in every view."),
    dict(regions=[r3(950, 642, 1932, 852)], caption="Feature decoder: dense, multi-view-consistent features distilled from DINOv3."),
    dict(regions=[r3(1030, 852, 2000, 1100), r3(1932, 640, 2000, 852)], caption="Match the features against a text prompt such as \"sofa\" for open-vocabulary 3D segmentation."),
    dict(regions=[r3(18, 402, 962, 872)], caption="Both heads are light: prompt projection, cross-view attention and a pixel decoder on the backbone tokens."),
    dict(regions="all", caption="Trained only on Feature Puzzles built from single images, then run feed-forward on real multi-view input."),
]

# ── segments: result clips ────────────────────────────────────────────────
def label_layer(tag, title, caption, x0, chips=None, chips_xy=None, chips_w=600, side_labels=()):
    L = layer(); d = ImageDraw.Draw(L)
    tf = sans(22, "Demi")
    tw = d.textlength(tag, font=tf) + 34
    d.rounded_rectangle([x0, 46, x0 + tw, 84], 19, fill=ACC + (60,), outline=ACC + (200,), width=2)
    d.text((x0 + tw / 2, 65), tag, font=tf, fill=ACC_HI + (255,), anchor="mm")
    tfont = sans(34, "Demi") if "_" in title else serif(38, "Medium")
    d.text((x0 + tw + 20, 66), title, font=tfont, fill=FG + (255,), anchor="lm")
    d.text((W / 2, 1012), caption, font=sans(32, "Medium"), fill=FG + (255,), anchor="mm")
    for (x, y, s_) in side_labels:
        d.text((x, y), s_, font=sans(20, "Demi"), fill=DIM + (255,), anchor="ls")
    if chips:
        chip_row(d, chips_xy[0], chips_xy[1], chips, sans(21, "Demi"), chips_w)
    return to_f(L)

def seg_clip(name, tag, title, caption, main, start, dur, aspect, side=(), chips=None, chips_title=None):
    """main video on the left; `side` = list of (kind, path, label[, start]) stacked on the right."""
    s = Seg(name)
    mh = 820; mw = round(mh * aspect)
    mx, my = 40, 120
    sx = mx + mw + 30; sw = W - 40 - sx
    mmask = rounded_mask(mw, mh, 14)
    main_f = clip_frames(os.path.join(SITE, main), start, dur, mw, mh)
    layers = [to_f(panel_frame(mx, my, mw, mh))]
    side_items, y, side_labels = [], my + 34, []
    for item in side:
        kind, path, lab = item[:3]
        st = item[3] if len(item) > 3 else start
        if kind == "img":
            im = Image.open(os.path.join(SITE, path)).convert("RGB")
            asp = im.width / im.height
        else:
            out = subprocess.run([FF, "-hide_banner", "-i", os.path.join(SITE, path)], capture_output=True, text=True).stderr
            import re
            m = re.search(r"(\d{3,4})x(\d{3,4})", out.split("Video:")[1]); asp = int(m.group(1)) / int(m.group(2))
        ww = sw; hh = round(ww / asp)
        maxh = 440 if len(side) == 1 else 380
        if hh > maxh: hh = maxh; ww = round(hh * asp)
        xx = sx + (sw - ww) // 2
        side_labels.append((xx, y - 12, lab))
        if kind == "img":
            arr = np.asarray(im.resize((ww, hh), Image.LANCZOS)).astype(np.float32); frames = None
        else:
            frames = clip_frames(os.path.join(SITE, path), st, dur, ww, hh); arr = None
        side_items.append((xx, y, ww, hh, rounded_mask(ww, hh, 10), arr, frames))
        layers.append(to_f(panel_frame(xx, y, ww, hh, 10)))
        y += hh + 62
    chips_xy = (sx, y - 20)
    if chips_title:
        side_labels.append((sx, y - 30, chips_title)); chips_xy = (sx, y - 14)
    lab = label_layer(tag, title, caption, mx, chips, chips_xy, sw, side_labels)
    for i in range(int(dur * FPS)):
        t = i / FPS; f = BASE.copy()
        for l in layers: f = over(f, l)
        paste(f, main_f[i].astype(np.float32), mx, my, mmask)
        for (xx, yy, ww, hh, mk, arr, frames) in side_items:
            paste(f, arr if frames is None else frames[i].astype(np.float32), xx, yy, mk)
        f = over(f, lab)
        s.put(f * fade_k(t, dur, 0.4, 0.4))
    s.close()

def chips_of(scene_id, task, top=None):
    m = json.load(open(os.path.join(SITE, "data/manifest.json")))
    for t in m["tasks"]:
        if t["id"] != task: continue
        for g in t["groups"]:
            for sc in g["scenes"]:
                if sc["id"] == scene_id:
                    if task == "promptable":
                        return [(p["name"], p["color"], None) for p in (sc.get("prompts") or [])]
                    q = [(x["name"], x["color"], x["n"]) for x in sc["queries"] if x["n"] > 0]
                    q.sort(key=lambda z: -z[2])
                    return q[:top] if top else q

P = "media/promptable"; O = "media/openvocab"
JOBS = {
    "title": seg_title,
    "motivation": seg_motivation,
    "ch1": lambda: seg_chapter("02_ch1", "STEP 1  ·  DATA", "Feature Puzzles",
                               "Turning one image into multi-view supervision"),
    "fig2": lambda: seg_figure("03_fig2", os.path.join(FIGS, "FeaturePuzzlesPipeline.png"), 1738, FIG2_STEPS,
                               "Feature Puzzles", step_dur=3.9, max_zoom=1.6),
    "ch2": lambda: seg_chapter("04_ch2", "STEP 2  ·  NETWORK", "One backbone, three decoders",
                               "Geometry, promptable masks and open-vocabulary features"),
    "fig3": lambda: seg_figure("05_fig3", os.path.join(FIGS, "NetworkPipeline.jpg"), 2500, FIG3_STEPS,
                               "Network", step_dur=3.9, max_zoom=1.9),
    "ch3": lambda: seg_chapter("06_ch3", "RESULTS", "Promptable Multi-View Segmentation",
                               "Prompt one view, get every view in a single forward pass"),
    "p1": lambda: seg_clip("07_p1", "AI-generated video", "Living room",
                           "Prompts on one view become masks on the whole reconstruction.",
                           f"{P}/aivideo/marble_i2w_living_room/follow_hl.mp4", 0, 10.5, 854 / 480,
                           [("img", f"{P}/aivideo/marble_i2w_living_room/reference.jpg", "PROMPTED VIEW"),
                            ("vid", f"{P}/aivideo/marble_i2w_living_room/input.mp4", "INPUT VIDEO")]),
    "p2": lambda: seg_clip("08_p2", "ScanNet", "scene0316_00",
                           "No per-scene optimization, no tracking, no pairwise matching.",
                           f"{P}/scannet/scene0316_00/follow_hl.mp4", 0, 9.5, 854 / 480,
                           [("img", f"{P}/scannet/scene0316_00/reference.jpg", "PROMPTED VIEW"),
                            ("vid", f"{P}/scannet/scene0316_00/input.mp4", "INPUT VIDEO")]),
    "p3": lambda: seg_clip("09_p3", "ScanNet++", "0373d65cce",
                           "Every object keeps one identity across all views.",
                           f"{P}/scannetpp/0373d65cce/follow_hl.mp4", 6.5, 8.0, 854 / 480,
                           [("img", f"{P}/scannetpp/0373d65cce/reference.jpg", "PROMPTED VIEW"),
                            ("vid", f"{P}/scannetpp/0373d65cce/input.mp4", "INPUT VIDEO")]),
    "p4": lambda: seg_clip("10_p4", "Dynamic scene", "EMDB 35",
                           "Spatial tracking: a person and the floor carried through a whole video.",
                           f"{P}/dynamic/EMDB_35/bev_hl.mp4", 2.0, 8.5, 854 / 480,
                           [("vid", f"{P}/dynamic/EMDB_35/input.mp4", "INPUT VIDEO")],
                           chips=chips_of("EMDB_35", "promptable"), chips_title="PROMPTS"),
    "ch4": lambda: seg_chapter("11_ch4", "RESULTS", "Open-Vocabulary 3D Segmentation",
                               "Text queries become 3D instances, from rooms to buildings"),
    "o1": lambda: seg_clip("12_o1", "ScanNet", "scene0000_01",
                           "Text queries, fused into 3D instances across views.",
                           f"{O}/scannet/scene0000_01/follow.mp4", 0.5, 8.5, 854 / 640,
                           [("vid", f"{O}/scannet/scene0000_01/input.mp4", "INPUT VIDEO", 0.5)],
                           chips=chips_of("scene0000_01", "openvocab"), chips_title="TEXT QUERIES  ·  INSTANCES"),
    "o2": lambda: seg_clip("13_o2", "ScanNet++", "00dd871005",
                           "Zero-shot: the features were distilled from single images only.",
                           f"{O}/scannetpp/00dd871005/follow.mp4", 1.0, 8.0, 854 / 640,
                           [("vid", f"{O}/scannetpp/00dd871005/input.mp4", "INPUT VIDEO", 1.0)],
                           chips=chips_of("00dd871005", "openvocab"), chips_title="TEXT QUERIES  ·  INSTANCES"),
    "o3": lambda: seg_clip("14_o3", "FARM-Scenes", "Building scale  ·  279 instances",
                           "Building scale: hundreds of instances from free-form text queries.",
                           f"{O}/farm/grandtour_2024-11-11_raw_lidar_s20/follow.mp4", 3.0, 9.0, 854 / 640,
                           [("vid", f"{O}/farm/grandtour_2024-11-11_raw_lidar_s20/input.mp4", "INPUT VIDEO", 3.0)],
                           chips=chips_of("grandtour_2024-11-11_raw_lidar_s20", "openvocab", top=14),
                           chips_title="TEXT QUERIES  ·  INSTANCES"),
    "outro": seg_outro,
}
ORDER = ["title", "motivation", "ch1", "fig2", "ch2", "fig3", "ch3", "p1", "p2", "p3", "p4", "ch4", "o1", "o2", "o3", "outro"]

if __name__ == "__main__":
    for k in ORDER:
        if ONLY and k not in ONLY: continue
        print("render", k, flush=True); JOBS[k]()

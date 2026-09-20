#!/usr/bin/env python
"""Turn the two result trees into the assets this project page serves.

The renders themselves are MPEG-4 Part 2 (``FMP4``), which no browser will play,
so the page cannot point at them directly. This script therefore builds a
self-contained ``media/`` tree of H.264 copies next to the page, cuts a poster
from the final bird's-eye frame of every scene, and writes ``data/manifest.json``
for the front-end to read. Nothing outside this directory is written to.

    ./build_site.py                     # build whatever is missing
    ./build_site.py --only openvocab    # just one task
    ./build_site.py --force             # re-encode everything
    ./build_site.py --width 960 --crf 28    # a lighter build

Re-run it whenever more scenes finish rendering: work already done is skipped,
so a second pass only picks up what is new.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

import cv2

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent                                  # ICLR26Demo/
MULTIVIEW = RESULTS / "vggt_omega_multiprompt_static_scene"
DYNAMIC = RESULTS / "vggt_omega_multiprompt_dynamic_scene"
OPENVOCAB = RESULTS / "openvocab_3Dsegmentation"
MEDIA = HERE / "media"
POSTERS = HERE / "posters"
DATA = HERE / "data"

POSTER_WIDTH = 600
POSTER_QUALITY = 82


def ffmpeg_bin() -> str:
    local = HERE / "tools" / "ffmpeg"
    if local.exists():
        return str(local)
    found = shutil.which("ffmpeg")
    if not found:
        sys.exit("[fail] no ffmpeg: expected tools/ffmpeg or ffmpeg on PATH")
    return found


# ── naming ──────────────────────────────────────────────────────────────────

# Longest prefix wins, so `marble_chisel` is matched before `marble11`.
AIVIDEO_FAMILIES = [
    ("marble_chisel", "Marble · Chisel"),
    ("marble_edit", "Marble · Edit"),
    ("marble_expand", "Marble · Expand"),
    ("marble_mesh", "Marble · Mesh"),
    ("marble_stitched", "Marble · Stitched"),
    ("marble_mia2w", "Marble · Image→World"),
    ("marble_mim2w", "Marble · Multi-image→World"),
    ("marble_i2w", "Marble · Image→World"),
    ("marble_t2w", "Marble · Text→World"),
    ("marble11", "Marble-11"),
    ("atlas", "Atlas"),
    ("rtfm", "RTFM"),
]

# Trailing words that name a variant of a scene rather than a scene of its own.
VARIANT_WORDS = {
    "pre", "post", "orig", "layout", "scene", "grey", "lit", "shaded", "splats",
    "nomap", "cabinets", "counters", "floor", "pit", "conversation", "fantasy",
    "japanese", "mediterranean", "scandinavian", "stone", "tuscany", "a", "b",
}

WORD_FIXES = {
    "scifi": "sci-fi", "redblue": "red/blue", "nomap": "no map", "tv": "TV",
    "a": "A", "b": "B", "pingpong": "ping-pong",
}


def _words(raw: list[str]) -> str:
    return " ".join(WORD_FIXES.get(w, w) for w in raw)


def pretty_aivideo(clip: str) -> tuple[str, str]:
    """``marble_chisel_bedroom_fantasy`` -> ("Marble · Chisel", "Bedroom — fantasy")."""
    family, rest = "AI video", clip
    for prefix, label in AIVIDEO_FAMILIES:
        if clip == prefix or clip.startswith(prefix + "_"):
            family, rest = label, clip[len(prefix):].lstrip("_")
            break
    words = [w for w in rest.split("_") if w]
    if len(words) > 1 and words[-1] in VARIANT_WORDS:
        name = _words(words[:-1]) + " — " + _words(words[-1:])
    else:
        name = _words(words)
    return family, (name[:1].upper() + name[1:] if name else family)


# ── media ───────────────────────────────────────────────────────────────────

class Encoder:
    """Queues transcodes and runs them in parallel, skipping finished work."""

    def __init__(self, width: int, crf: int, force: bool, jobs: int):
        self.bin = ffmpeg_bin()
        self.width, self.crf, self.force, self.jobs = width, crf, force, jobs
        self.queue: list[tuple[list[Path], str | None, Path]] = []

    # The scale every job shares.  Written with an escaped comma rather than
    # quotes because it also has to survive -filter_complex's own parser.
    def _scale(self) -> str:
        return f"scale=min({self.width}\\,iw):-2:flags=lanczos"

    def _add(self, srcs: list[Path], vf: str | None, dst: Path) -> str:
        if self.force or not dst.exists() or dst.stat().st_size == 0:
            self.queue.append((srcs, vf, dst))
        return dst.relative_to(HERE).as_posix()

    def want(self, src: Path, dst: Path) -> str:
        """Register ``src`` -> ``dst`` and return the page-relative path of ``dst``."""
        return self._add([src], None, dst)

    def want_spliced(self, intro: Path, main: Path, dst: Path, fps: int = 30) -> str:
        """``intro`` then ``main`` as one clip, in a single encode.

        The renders are 3 fps and the intro is 30; ``fps`` conversion frame-holds
        the render onto the intro's timebase rather than speeding it up, and
        ``setpts`` restamps both halves so the concat has no gap at the join.
        Done in one pass, so the intro is not encoded twice.
        """
        sc = self._scale()
        vf = (f"[0:v]{sc},fps={fps},setsar=1,setpts=N/{fps}/TB[a];"
              f"[1:v]{sc},fps={fps},setsar=1,setpts=N/{fps}/TB[b];"
              f"[a][b]concat=n=2:v=1[v]")
        return self._add([intro, main], vf, dst)

    def want_held(self, src: Path, dst: Path, seconds: float, fps: int = 30) -> str:
        """``src`` with its first frame held for ``seconds`` in front.

        The stage plays bird's-eye, follow and input as one clip, so the input
        panel has to gain exactly as many frames as the intro added to the other
        two or the three drift apart.  ``tpad`` after the fps conversion clones
        the first frame at the target rate, which is the reference view -- the
        same frame the intro opens on.
        """
        sc = self._scale()
        vf = (f"[0:v]{sc},fps={fps},"
              f"tpad=start_duration={seconds}:start_mode=clone,"
              f"setsar=1,setpts=N/{fps}/TB[v]")
        return self._add([src], vf, dst)

    def run(self) -> None:
        if not self.queue:
            print("[media] nothing to encode")
            return
        total = len(self.queue)
        print(f"[media] encoding {total} videos with {self.jobs} workers "
              f"(H.264, max width {self.width}, crf {self.crf})")
        t0 = time.time()
        done = [0]

        def one(job):
            srcs, vf, dst = job
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_suffix(".part.mp4")
            cmd = [self.bin, "-y", "-loglevel", "error"]
            for s_ in srcs:
                cmd += ["-i", str(s_)]
            if vf is None:
                # Never upscale, and keep both dimensions even for yuv420p.
                cmd += ["-vf", f"scale='min({self.width},iw)':-2:flags=lanczos"]
            else:
                cmd += ["-filter_complex", vf, "-map", "[v]", "-r", "30"]
            cmd += [
                "-c:v", "libx264", "-preset", "medium", "-crf", str(self.crf),
                "-pix_fmt", "yuv420p", "-profile:v", "high", "-g", "24",
                # faststart puts the index up front, so playback can begin
                # before the file has finished downloading.
                "-movflags", "+faststart", "-an", str(tmp),
            ]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0 or not tmp.exists():
                tmp.unlink(missing_ok=True)
                print(f"  [warn] {srcs[0].name}: {r.stderr.strip()[:200]}", file=sys.stderr)
            else:
                tmp.replace(dst)
            done[0] += 1
            if done[0] % 20 == 0 or done[0] == total:
                print(f"  {done[0]}/{total}  ({time.time() - t0:.0f}s)", flush=True)

        with ThreadPoolExecutor(max_workers=self.jobs) as pool:
            list(pool.map(one, self.queue))
        self.queue.clear()
        print(f"[media] done in {time.time() - t0:.0f}s")


def shrink_jpg(img, out: Path) -> bool:
    h, w = img.shape[:2]
    s = min(1.0, POSTER_WIDTH / w)
    if s < 1.0:
        img = cv2.resize(img, (round(w * s), round(h * s)), interpolation=cv2.INTER_AREA)
    out.parent.mkdir(parents=True, exist_ok=True)
    return bool(cv2.imwrite(str(out), img, [cv2.IMWRITE_JPEG_QUALITY, POSTER_QUALITY]))


def poster_from_video(video: Path, out: Path, force: bool) -> bool:
    """Write the last decodable frame of ``video`` to ``out`` -- the finished result."""
    if out.exists() and not force:
        return True
    cap = cv2.VideoCapture(str(video))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frame = None
    # Seeking exactly to the last frame fails on some encodes; walk backwards.
    for idx in range(n - 1, max(n - 12, -1), -1):
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, got = cap.read()
        if ok and got is not None:
            frame = got
            break
    cap.release()
    if frame is None:
        print(f"  [warn] no decodable frame in {video.name}", file=sys.stderr)
        return False
    return shrink_jpg(frame, out)


def probe(video: Path) -> dict:
    cap = cv2.VideoCapture(str(video))
    info = {
        "w": int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
        "h": int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
        "frames": int(cap.get(cv2.CAP_PROP_FRAME_COUNT)),
        "fps": round(cap.get(cv2.CAP_PROP_FPS), 3),
    }
    cap.release()
    return info


# ── task 1: promptable multi-view segmentation ──────────────────────────────

PROMPTABLE_GROUPS = [
    {
        "id": "aivideo",
        "label": "AI-generated video",
        "kind": "aivideo",
        "note": "Generated indoor walkthroughs (Marble, Atlas, RTFM). These clips have "
                "no depth and no poses, so the geometry is VGGT-Omega's own "
                "reconstruction — the segmentation head runs on top of it unchanged.",
        # AScannet / AScannet++ are where the current runs write; the eval renders
        # are the same pipeline and stand in until those have finished.
        "dirs": ["AIVideo"],
    },
    {
        "id": "scannet",
        "label": "ScanNet",
        "kind": "scannet",
        "note": "Real RGB-D scans with sensor depth and poses. 100 views per scene, "
                "prompted once with SAM's ten largest disjoint masks on view 0.",
        "dirs": ["AScannet", "eval_iterative_excl"],
    },
    {
        "id": "scannetpp",
        "label": "ScanNet++",
        "kind": "scannet",
        "note": "High-resolution DSLR scans with mesh-rendered depth.",
        "dirs": ["AScannet++"],
    },
    {
        # Kept apart from the static datasets on purpose: every other scene on
        # the page is a still room, and this is the one where something moves.
        "id": "dynamic",
        "label": "Dynamic scene",
        "kind": "dynamic",
        "dynamic": True,
        "root": DYNAMIC,
        "note": "A person moves through the scene while a hand-held camera follows "
                "(EMDB clips from MeshMimic). Two text prompts on the first frame — "
                "\u201chuman\u201d and \u201cfloor\u201d — are propagated through "
                "every frame of the video. The floor accumulates into the "
                "reconstruction. In the bird's-eye view the human's past positions "
                "stay behind, one every 10 frames, dimmed, as its 3D track, with "
                "the current body in full colour; the follow view shows only the "
                "current body.",
        "dirs": ["MeshMimic"],
    },
]


def scan_promptable(enc: Encoder, force: bool) -> list[dict]:
    out = []
    for g in PROMPTABLE_GROUPS:
        scenes, source = [], None
        for name in g["dirs"]:
            d = g.get("root", MULTIVIEW) / name
            if not d.is_dir():
                continue
            found = [s for s in (_promptable_scene(c, g, enc, force)
                                 for c in sorted(d.iterdir()) if c.is_dir()) if s]
            if found:
                scenes, source = found, name
                break
        print(f"  promptable/{g['id']}: {len(scenes)} scenes"
              + (f"  <- {source}" if source else "  (nothing rendered yet)"))
        out.append({"id": g["id"], "label": g["label"], "note": g["note"],
                    "dynamic": bool(g.get("dynamic")), "source": source,
                    "scenes": scenes})
    return out


def _promptable_scene(d: Path, group: dict, enc: Encoder, force: bool) -> dict | None:
    if d.name == "logs":
        return None
    stem = d.name                                   # files are "<stem>_<suffix>"

    def src(suffix: str) -> Path:
        return d / f"{stem}_{suffix}.mp4"

    have = {m: (src(f"{m}_birdeye_pointcloud"), src(f"{m}_follow_pointcloud"))
            for m in ("hl", "seg")}
    rgb = src("seg_follow_pointcloud_rgb")
    if not (have["hl"][0].exists() and have["hl"][1].exists() and rgb.exists()):
        return None

    # The ray-shooting opening (../ray_shoot_scripts), spliced on the front.
    # All four are required before any of them is used: the stage plays
    # bird's-eye, follow and input as one clip and lets you toggle hl/seg
    # mid-play, so a scene with an opening on only some of them would jump.
    intro = {m: (src(f"{m}_birdeye_intro"), src(f"{m}_follow_intro"))
             for m in ("hl", "seg")}
    has_intro = all(q.exists() for pair in intro.values() for q in pair)
    intro_sec = 0.0
    if has_intro:
        info0 = probe(intro["hl"][0])
        intro_sec = round(info0["frames"] / info0["fps"], 3) if info0["fps"] else 0.0
        has_intro = intro_sec > 0

    clip = stem
    for suffix in ("_iterative_excl", "_dynamic"):
        if clip.endswith(suffix):
            clip = clip[: -len(suffix)]
    if group["kind"] == "aivideo":
        family, name = pretty_aivideo(clip)
    elif group["kind"] == "dynamic":
        family, name = "MeshMimic · EMDB", clip.replace("_", " ")
    else:
        family, name = group["label"], clip

    # Named text prompts (dynamic runs): shown as a legend instead of a count.
    prompts_p = d / f"{stem}_prompts.json"
    prompts = (json.loads(prompts_p.read_text()).get("prompts")
               if prompts_p.exists() else None)

    outdir = MEDIA / "promptable" / group["id"] / clip
    modes = {}
    for mode, (bev, follow) in have.items():
        if bev.exists() and follow.exists():
            if has_intro:
                modes[mode] = {
                    "bev": enc.want_spliced(intro[mode][0], bev, outdir / f"bev_{mode}.mp4"),
                    "follow": enc.want_spliced(intro[mode][1], follow,
                                               outdir / f"follow_{mode}.mp4"),
                }
            else:
                modes[mode] = {
                    "bev": enc.want(bev, outdir / f"bev_{mode}.mp4"),
                    "follow": enc.want(follow, outdir / f"follow_{mode}.mp4"),
                }

    poster = POSTERS / f"promptable_{group['id']}_{clip}.jpg"
    if not poster_from_video(have["hl"][0], poster, force):
        return None

    # The reference view with its prompt masks drawn on: the whole input to the run.
    ref_src = d / f"{stem}_prompt_masks_firstframe_overlay.png"
    ref = None
    if ref_src.exists():
        ref_out = outdir / "reference.jpg"
        if force or not ref_out.exists():
            img = cv2.imread(str(ref_src))
            if img is not None and shrink_jpg(img, ref_out):
                ref = ref_out.relative_to(HERE).as_posix()
        else:
            ref = ref_out.relative_to(HERE).as_posix()

    info = probe(have["hl"][0])
    return {
        "id": clip,
        "name": name,
        "family": family,
        "poster": poster.relative_to(HERE).as_posix(),
        "modes": modes,
        "rgb": (enc.want_held(rgb, outdir / "input.mp4", intro_sec) if has_intro
                else enc.want(rgb, outdir / "input.mp4")),
        "reference": ref,
        "dynamic": bool(group.get("dynamic")),
        "prompts": [{"name": q["name"], "color": q["color"]} for q in prompts]
                   if prompts else None,
        "stats": {
            # The run's own numbers, not the spliced clip's: "views" is how many
            # frames the model saw, which the opening does not change.
            "frames": info["frames"],
            "fps": info["fps"],
            "intro_seconds": intro_sec or None,
            "objects": len(list(d.glob(f"{stem}_prompt_mask_256_*.png"))) or None,
            "aspect": round(info["w"] / info["h"], 4) if info["h"] else 16 / 9,
        },
    }


# ── task 2: open-vocabulary 3D segmentation ─────────────────────────────────

OPENVOCAB_GROUPS = [
    {"id": "scannet", "label": "ScanNet",
     "note": "Five queries per scene, drawn deterministically from a twenty-word "
             "indoor vocabulary, over 120 frames with sensor depth and poses.",
     "dirs": ["scannet"]},
    {"id": "scannetpp", "label": "ScanNet++",
     "note": "DSLR scans. The ceiling is clipped away, or the bird's-eye view would "
             "look at nothing but the ceiling.",
     "dirs": ["scannetpp"]},
    {"id": "farm", "label": "FARM-Scenes",
     "note": "Large, sparse robot captures — a car museum, a warehouse, a construction "
             "site, a robotics building and an outdoor campus ramp, 1,200–15,000 m² "
             "each. Indoor furniture words find almost nothing here, so every scene "
             "is queried with its own official FARM-Scenes label set (41–97 classes).",
     "dirs": ["farm", "_stale_5prompt/farm_5prompt"]},
]


def scan_openvocab(enc: Encoder, force: bool) -> list[dict]:
    out = []
    for g in OPENVOCAB_GROUPS:
        scenes, source = [], None
        for name in g["dirs"]:
            d = OPENVOCAB / name
            if not d.is_dir():
                continue
            found = [s for s in (_openvocab_scene(c, g, enc, force)
                                 for c in sorted(d.iterdir()) if c.is_dir()) if s]
            if found:
                scenes, source = found, name
                break
        print(f"  openvocab/{g['id']}: {len(scenes)} scenes"
              + (f"  <- {source}" if source else "  (nothing rendered yet)"))
        out.append({"id": g["id"], "label": g["label"], "note": g["note"],
                    "source": source, "scenes": scenes})
    return out


def _openvocab_scene(d: Path, group: dict, enc: Encoder, force: bool) -> dict | None:
    s = d.name
    bev, follow, inp = d / f"{s}_bev.mp4", d / f"{s}_follow.mp4", d / f"{s}_input.mp4"
    if not (bev.exists() and follow.exists() and inp.exists()):
        return None

    meta_p = d / f"{s}_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    queries = [{
        "name": q.get("name", "?"),
        "color": "#%02x%02x%02x" % tuple(q.get("color_rgb", (150, 150, 150))),
        "n": q.get("n_instances", 0),
    } for q in meta.get("queries", [])]

    poster = POSTERS / f"openvocab_{group['id']}_{s}.jpg"
    if force or not poster.exists():
        shipped = d / f"{s}_bev_last.jpg"          # the run already saves this frame
        img = cv2.imread(str(shipped)) if shipped.exists() else None
        if img is None or not shrink_jpg(img, poster):
            if not poster_from_video(bev, poster, force):
                return None

    outdir = MEDIA / "openvocab" / group["id"] / s
    info = probe(bev)
    return {
        "id": s,
        "name": s,
        "family": group["label"],
        "poster": poster.relative_to(HERE).as_posix(),
        "bev": enc.want(bev, outdir / "bev.mp4"),
        "follow": enc.want(follow, outdir / "follow.mp4"),
        "input": enc.want(inp, outdir / "input.mp4"),
        "queries": queries,
        "stats": {
            "frames": meta.get("n_frames", info["frames"]),
            "fps": meta.get("fps", info["fps"]),
            "instances": len(meta.get("instances", [])) or None,
            "aspect": round(info["w"] / info["h"], 4) if info["h"] else 4 / 3,
        },
    }


# ── main ────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["promptable", "openvocab"],
                    help="rebuild one task and leave the other's entry as it is")
    ap.add_argument("--force", action="store_true", help="re-encode and re-cut everything")
    ap.add_argument("--width", type=int, default=1280, help="max video width (default 1280)")
    ap.add_argument("--crf", type=int, default=25, help="x264 quality, lower is bigger (default 25)")
    ap.add_argument("--jobs", type=int, default=8, help="parallel encodes (default 8)")
    args = ap.parse_args()

    for p in (MULTIVIEW, OPENVOCAB):
        if not p.is_dir():
            print(f"[fail] missing result tree {p}", file=sys.stderr)
            return 1

    enc = Encoder(args.width, args.crf, args.force, args.jobs)
    old = {}
    manifest_p = DATA / "manifest.json"
    if manifest_p.exists():
        old = {t["id"]: t for t in json.loads(manifest_p.read_text())["tasks"]}

    tasks = []
    for tid, title, lead, scanner in (
        ("promptable", "Promptable Multi-View Segmentation",
         "Prompts given in any subset of views propagate to every view in one "
         "forward pass — no per-scene optimization, no tracking, and no pairwise "
         "matching between views.",
         scan_promptable),
        ("openvocab", "Open-Vocabulary 3D Segmentation",
         "Open-world detections made on individual frames are carried across views by "
         "the same promptable head and fused into 3D instances, each confirmed the "
         "moment enough views agree on it.",
         scan_openvocab),
    ):
        if args.only and args.only != tid:
            if tid in old:
                tasks.append(old[tid])
                print(f"[skip] {tid} (kept from the previous manifest)")
            continue
        print(f"[scan] {title.lower()}")
        groups = scanner(enc, args.force)
        tasks.append({"id": tid, "title": title, "lead": lead, "groups": groups})

    enc.run()

    DATA.mkdir(parents=True, exist_ok=True)
    manifest_p.write_text(json.dumps(
        {"generated": datetime.now().isoformat(timespec="seconds"), "tasks": tasks},
        indent=1))

    n = sum(len(g["scenes"]) for t in tasks for g in t["groups"])
    size = sum(f.stat().st_size for f in MEDIA.rglob("*") if f.is_file()) / 2**30
    print(f"[done] {n} scenes, media {size:.2f} GiB -> data/manifest.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

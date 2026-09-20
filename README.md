# Feature Puzzles — project page

A static project page for the two demos in the paper:

- **Promptable multi-view segmentation** — `../vggt_omega_multiprompt_static_scene/`
  (`AIVideo/`, `AScannet/`, `AScannet++/`)
- **Open-vocabulary 3D segmentation** — `../openvocab_3Dsegmentation/`
  (`scannet/`, `scannetpp/`, `farm/`)

```bash
./build_site.py     # scan the results, encode web videos, write the manifest
./serve.sh          # http://localhost:8800
```

Re-run `./build_site.py` whenever more scenes finish rendering. Work already
done is skipped, so the second pass only picks up what is new — and the page
needs no other change, because it is built entirely from `data/manifest.json`.

---

## Why there is a build step

The renders are **MPEG-4 Part 2** (`FMP4`), which no browser will play; only the
older `eval_iterative_excl/` renders are H.264. So the page cannot point at the
result directories, and `build_site.py` writes a `media/` tree of H.264 copies
beside it instead (1280 px wide, CRF 25, `+faststart`). At those settings the
transcode is visually indistinguishable from the source and takes about 90 s for
the whole set on 10 workers.

The side effect is a page that is **self-contained**: `index.html`, `css/`,
`js/`, `media/`, `posters/` and `data/` are everything, with no links pointing
outside this directory. It can be copied to a web host as-is.

`tools/ffmpeg` is a static build (used in preference to any `ffmpeg` on `PATH`).

## Layout

Each task gets a **stage** and a **gallery**.

The stage follows the offline compositor in
`../multiprompt_demo_project_page/app/compose.py`: one render fills the frame,
the others float over its right edge as rounded, shadowed panels. **Click a
panel to swap it into the main slot** — the two animate past each other. Every
panel of a scene is the same frames at the same rate, so they play as one clip;
the panel in the main slot is the clock and the rest are nudged back onto it
whenever they drift more than a frame.

| | main + floating panels | toggle |
|---|---|---|
| Promptable | bird's-eye, follow camera, input video | **Highlight** (instance colours over the reconstructed colours) vs **Instance** (flat colours) |
| Open-vocabulary | bird's-eye, follow camera, input video | — |

### The ray-shooting opening

Every promptable clip opens with the 6-second title from
[`../vggt_omega_multiprompt_static_scene/ray_shoot_scripts/`](../vggt_omega_multiprompt_static_scene/ray_shoot_scripts):
the reference view, its prompt masks washing in, then the masked photograph
becoming a point cloud and the camera arcing onto the render's own opening
camera.  It is spliced on in the build, not played as a separate file, so the
opening and the render are one continuous clip.

Two things this has to get right:

- **All three panels gain the same frames.**  The stage plays bird's-eye, follow
  and input as one clip, so `Encoder.want_held` puts a matching 6 s hold of the
  input's first frame in front of the input panel — which is the reference view,
  the same frame the opening starts on.  Without it the three drift apart by
  exactly the length of the opening.
- **All four openings must exist before any is used.**  The toggle switches
  hl/seg mid-play, so a scene with an opening on `seg` but not `hl` would jump
  when toggled.  `_promptable_scene` requires all four
  (`hl`/`seg` × `birdeye`/`follow`) and falls back to the bare render otherwise.

The opening is for the three **static** groups (AI-generated video, ScanNet,
ScanNet++): it is built from a reference view, its prompt masks and the run's
reconstruction.  The **Dynamic scene** group (MeshMimic / EMDB) has none of that
and plays without an opening, at its own length — that is by design, not a
missing file.

The renders are 3 fps and the opening is 30, so the splice frame-holds the
render onto the opening's timebase: 180 frames of opening + 100 render frames
held 10x = **1180 frames at 30 fps**, 39.3 s.  The render plays at exactly its
old speed; duplicate frames cost almost nothing in H.264.  `stats.frames` in the
manifest stays at the run's own view count (100), because that is what the
"views" chip means and the opening does not change it.

The promptable stage carries one more panel: the **reference view** with its prompt
masks drawn on, pinned to the bottom-right at the same size as the floating
panels. It is a still, so it stays put instead of joining the swap order; click it
to enlarge. It is the entire input to the run — everything else on the stage is
the model propagating those masks to the other views.

Below the stage: the query legend with per-class instance counts
(open-vocabulary), and for both the run's view count, rate and prompt or
instance count.

Gallery cards are **the last frame of the bird's-eye video**, i.e. the complete
inference result for that scene, with the object or instance count in the
corner. Datasets are tabs; a dataset with nothing rendered yet is shown greyed
out rather than hidden, so it is obvious what is still coming.

Keyboard: <kbd>space</kbd> plays/pauses and <kbd>←</kbd>/<kbd>→</kbd> step one
frame, acting on whichever stage is on screen.

## Which results are shown

`build_site.py` takes the first directory of each group that has anything in it:

| group | looks in |
|---|---|
| Promptable · ScanNet | `AScannet/`, then `eval_iterative_excl/` |
| Promptable · ScanNet++ | `AScannet++/` |
| Open-vocab · FARM | `farm/`, then `_stale_5prompt/farm_5prompt/` |

So while `AScannet/` is still filling, the ScanNet tab shows whatever it has;
the `eval_iterative_excl/` renders (the same `iterative_excl` pipeline) are only
used if `AScannet/` is empty. A scene only appears once **all** of its videos
exist, so a half-written directory is skipped rather than shown broken.

## Files

```
index.html          page shell: nav, hero, abstract, two empty task sections, BibTeX
css/site.css        all styling
js/site.js          reads the manifest, builds both sections, drives the stages
build_site.py       scan -> transcode -> posters -> data/manifest.json
serve.py            static server with byte-range support (see below)
serve.sh            wrapper: ./serve.sh [port]
tools/ffmpeg        static ffmpeg used by the build
media/              generated H.264 videos + reference-view stills
posters/            generated gallery/teaser stills
data/manifest.json  generated; the only thing the page reads
```

`serve.py` exists because `python -m http.server` answers every request with the
whole file. Without `Accept-Ranges` a browser will not treat a video as
seekable, and cannot start playing a 10 MB render before it has finished
downloading; `serve.py` is the stock handler plus single-range responses.

Any other static server works too, as long as it follows ranges — e.g.
`npx serve`, nginx, or GitHub Pages.

## Build options

```bash
./build_site.py --only openvocab     # rebuild one task, keep the other's manifest entry
./build_site.py --force              # re-encode and re-cut everything
./build_site.py --width 960 --crf 28 # lighter build (~half the size)
./build_site.py --jobs 16            # more parallel encodes
```

Current build: 121 scenes, ~4.1 GiB in `media/`. Dropping to `--width 960 --crf 28`
brings that down substantially if the page has to be uploaded somewhere.

Re-running `--only promptable` after generating new openings does **not** pick
them up on its own: the spliced files keep the same names as the bare ones, so
the encoder skips them as already done.  Delete `media/promptable/` first (or
pass `--force`).

## Editing the text

The title, authors, links, abstract and BibTeX are plain HTML in `index.html`.
The per-task headline and one-line lead live in `build_site.py` (in `main()`),
and the per-dataset notes in `PROMPTABLE_GROUPS` / `OPENVOCAB_GROUPS`, because
they are written into the manifest; edit there and re-run the build.

The four hero buttons (Paper, arXiv, Code, BibTeX) are placeholders marked
`data-placeholder`, which is what renders the "· soon" suffix. Remove the
attribute and set the `href` once each link exists.

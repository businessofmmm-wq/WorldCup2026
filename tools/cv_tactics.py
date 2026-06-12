#!/usr/bin/env python
"""
Quantum Tactics Lab — computer-vision pipeline (LOCAL, BUILD-TIME ONLY).

Reads player/ball positions out of a football clip and infers each side's shape,
then writes a numeric tactical packet to data/tactics/<key>.json. The static CDN
build (viz/export.py) snapshots that JSON into the album; the deployed site and the
live http.server run NO computer vision. cv2/ultralytics are imported *lazily inside
functions*, so nothing on the serving path ever touches them — exactly like
viz/ogcard.py treats Pillow.

    python run.py cv footage/<clip>.mp4 --home "Mexico" --away "South Africa" --date 2026-06-11

GREEN-LANE: only ever point this at footage you have the right to process —
Creative-Commons / public-domain / your own / licensed clips. NEVER broadcast or
streamed match footage. See footage/README.txt. footage/ and data/tactics/ are
both gitignored: clips and CV output stay local; nothing but derived numbers ship.

Optional sidecar <clip>.points.json maps four image points to pitch metres for a
homography; without it, positions are normalised frame coordinates (0..1).
"""
from __future__ import annotations
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import config                                   # noqa: E402  (stdlib-light config)
from models.tactics import match_key            # noqa: E402  (shared key — no cv deps)

OUT_DIR = os.path.join(config.DATA_DIR, "tactics")

# How many evenly-spaced frames to sample. The detector weights / resolution / conf
# come from config (WCPA_YOLO_* env overrides) — upgraded to a high-capacity model at
# high input resolution for micro-detailed precision. Weights auto-download into the
# gitignored *.pt cache on first run.
DEFAULT_FRAMES = 60
PERSON_CLS = 0          # COCO 'person'
BALL_CLS = 32           # COCO 'sports ball'


def _require_cv():
    """Lazily import the heavy CV stack with a friendly install hint (build-time only)."""
    try:
        import cv2                                 # noqa: F401
        import numpy as np                         # noqa: F401
        from ultralytics import YOLO               # noqa: F401
        return cv2, np, YOLO
    except Exception as exc:                        # ImportError or backend load failure
        raise SystemExit(
            "The Quantum Tactics CV pipeline needs OpenCV + Ultralytics (build-time only).\n"
            "  pip install opencv-python ultralytics\n"
            f"(import failed: {exc})")


def _load_points(clip: str):
    """Read the optional <clip>.points.json homography sidecar; return (src, dst) or None."""
    side = os.path.splitext(clip)[0] + ".points.json"
    if not os.path.exists(side):
        return None
    with open(side, encoding="utf-8") as fh:
        d = json.load(fh)
    img, pitch = d.get("image"), d.get("pitch")
    if not (img and pitch and len(img) == 4 and len(pitch) == 4):
        print(f"  ignoring {os.path.basename(side)}: need 4 image+pitch points")
        return None
    return img, pitch


def _sample_indices(total: int, want: int) -> list[int]:
    if total <= 0:
        return []
    want = min(want, total)
    step = total / want
    return sorted({int(k * step) for k in range(want)})


def _kmeans2(np, feats):
    """Two-cluster k-means (pure-numpy Lloyd's, no sklearn) over an (N,3) matrix of mean
    jersey colours. Returns 0/1 labels. Run ONCE over all detections in the clip so a
    team keeps a stable label across frames (per-frame clustering flips the labels and
    smears both sides together)."""
    n = len(feats)
    if n < 2:
        return [0] * n
    rng = np.random.default_rng(7)
    cent = feats[rng.choice(n, 2, replace=False)].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(25):
        d0 = ((feats - cent[0]) ** 2).sum(1)
        d1 = ((feats - cent[1]) ** 2).sum(1)
        new = (d1 < d0).astype(int)
        if (new == labels).all():
            break
        labels = new
        for t in (0, 1):
            if (labels == t).any():
                cent[t] = feats[labels == t].mean(0)
    return labels.tolist()


def _player_nodes(np, pts, k):
    """Collapse an accumulated point cloud (one entry per detection per frame) into k
    stable player nodes via k-means (numpy Lloyd's, no sklearn). Returns the non-empty
    cluster centroids as [(x, y, weight)], weight = share of detections in that cluster
    — so 96 noisy samples become ~10 player positions, not a point smear."""
    P = np.array([[p[0], p[1]] for p in pts], dtype="float32")
    if len(P) <= k:
        return [(float(x), float(y), 1.0 / len(P)) for x, y in P]
    rng = np.random.default_rng(11)
    cent = P[rng.choice(len(P), k, replace=False)]
    labels = np.zeros(len(P), dtype=int)
    for _ in range(25):
        d = ((P[:, None, :] - cent[None, :, :]) ** 2).sum(2)   # (N,k) sq distances
        new = d.argmin(1)
        if (new == labels).all():
            break
        labels = new
        for c in range(k):
            if (labels == c).any():
                cent[c] = P[labels == c].mean(0)
    nodes = []
    for c in range(k):
        m = labels == c
        if m.any():
            nodes.append((float(cent[c][0]), float(cent[c][1]), float(m.sum()) / len(P)))
    return nodes


def _formation_from_nodes(nodes, flip: bool) -> str:
    """Read an outfield shape (e.g. '4-3-3') from player NODES. `flip` orients the team
    so depth increases from its own goal (the right-side team attacks leftward). Drops
    the deepest node as the keeper, then buckets the rest into defence/mid/attack thirds."""
    if len(nodes) < 6:
        return "?"
    depth = [(1.0 - n[0]) if flip else n[0] for n in nodes]   # distance from own goal
    order = sorted(range(len(nodes)), key=lambda i: depth[i])
    outfield = order[1:]                                       # drop keeper (deepest back)
    ds = [depth[i] for i in outfield]
    lo, hi = min(ds), max(ds)
    span = max(hi - lo, 1e-6)
    bands = [0, 0, 0]
    for i in outfield:
        b = min(2, int((depth[i] - lo) / span * 3))
        bands[b] += 1
    return "-".join(str(b) for b in bands if b) or "?"


def analyse(clip: str, key: str | None = None, frames: int = DEFAULT_FRAMES,
            verbose: bool = True) -> dict:
    """Run the CV pipeline over `clip` and return the tactical packet (also writes it
    to data/tactics/<key>.json). Deterministic given the same clip + frame count."""
    cv2, np, YOLO = _require_cv()
    if not os.path.exists(clip):
        raise SystemExit(f"clip not found: {clip}")
    key = key or match_key("home", "away", os.path.splitext(os.path.basename(clip))[0])

    homog = _load_points(clip)
    H = None
    if homog:
        src = np.array(homog[0], dtype="float32")
        dst = np.array(homog[1], dtype="float32")
        H, _ = cv2.findHomography(src, dst)

    cap = cv2.VideoCapture(clip)
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 0
    want = _sample_indices(total, frames)
    if verbose:
        print(f"  {os.path.basename(clip)}: {total} frames, sampling {len(want)}")

    model = YOLO(config.YOLO_WEIGHTS)
    classes = [PERSON_CLS] + ([BALL_CLS] if config.CV_DETECT_BALL else [])
    ball = []                     # list of (x, y) for the detected ball
    dets = []                     # (feat_bgr, x, y, conf) for every person detection
    fw = cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 1.0
    fh = cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 1.0
    analysed = 0

    def to_coords(cx, cy):
        """Map an image point to pitch metres (if a homography is set) or to
        normalised frame coords (0..1) otherwise."""
        if H is not None:
            p = cv2.perspectiveTransform(np.array([[[cx, cy]]], dtype="float32"), H)[0][0]
            return float(p[0]), float(p[1])
        return cx / fw, cy / fh

    for idx in want:
        cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = cap.read()
        if not ok:
            continue
        analysed += 1
        # High-precision detection: configurable high-capacity weights, high input
        # resolution and a low conf floor so distant/partly-occluded players are kept.
        res = model.predict(frame, classes=classes, imgsz=config.YOLO_IMGSZ,
                            conf=config.YOLO_CONF, iou=config.YOLO_IOU, verbose=False)
        for b in (res[0].boxes if res else []):
            cls = int(b.cls[0]); conf = float(b.conf[0])
            x1, y1, x2, y2 = (float(v) for v in b.xyxy[0])
            if cls == BALL_CLS:
                ball.append(to_coords((x1 + x2) / 2.0, (y1 + y2) / 2.0))
                continue
            crop = frame[int(y1):int(y2), int(x1):int(x2)]
            if crop.size == 0:
                continue
            feat = crop.reshape(-1, 3).mean(0)                   # mean BGR jersey colour
            x, y = to_coords((x1 + x2) / 2.0, y2)                # feet point
            dets.append((feat, x, y, conf))
    cap.release()
    n_person = len(dets)

    # GLOBAL team assignment: one colour k-means over ALL detections, so each team keeps
    # a stable label across frames; then name the lower-mean-x side 'home' (left). This
    # keeps each team spatially coherent — the precondition for a sane formation read.
    pos = {0: [], 1: []}
    if dets:
        labels = _kmeans2(np, np.array([d[0] for d in dets], dtype="float32"))
        grp = {0: [], 1: []}
        for (feat, x, y, conf), lab in zip(dets, labels):
            grp[int(lab)].append((x, y, conf))
        mx = {g: (sum(p[0] for p in grp[g]) / len(grp[g]) if grp[g] else 1e9)
              for g in (0, 1)}
        home_lab = 0 if mx[0] <= mx[1] else 1
        pos[0] = grp[home_lab]
        pos[1] = grp[1 - home_lab]

    metres = H is not None

    def _norm(x, y):                # → 0..1 for heatmap binning
        return (x / 105.0, y / 68.0) if metres else (x, y)

    def _heatmap(team_pts):
        nx, ny = config.CV_HEATMAP_NX, config.CV_HEATMAP_NY
        grid = [[0] * nx for _ in range(ny)]
        for x, y, _ in team_pts:
            nxr, nyr = _norm(x, y)
            cx = min(nx - 1, max(0, int(nxr * nx)))
            cy = min(ny - 1, max(0, int(nyr * ny)))
            grid[cy][cx] += 1
        return grid

    def summarise(team_pts):
        if not team_pts:
            return {"positions": [], "nodes": [], "formation": "?", "n": 0,
                    "heatmap": _heatmap([])}
        xs = [p[0] for p in team_pts]
        ys = [p[1] for p in team_pts]
        cxn = sum(xs) / len(xs)
        # estimate the squad size on screen from detections/frame, then cluster the
        # cloud into that many player nodes (clamped to a sane 7–11).
        k = max(7, min(11, round(len(team_pts) / max(1, analysed))))
        nodes = _player_nodes(np, team_pts, k)
        flip = cxn > 0.5                                    # right-side team attacks left
        formation = _formation_from_nodes(nodes, flip)
        node_out = [{"x": round(x, 4), "y": round(y, 4), "w": round(w, 3)}
                    for x, y, w in nodes]
        return {"positions": node_out, "nodes": node_out, "formation": formation,
                "centroid": [round(cxn, 4), round(sum(ys) / len(ys), 4)],
                "n": len(team_pts), "players_est": len(nodes),
                "heatmap": _heatmap(team_pts)}

    home, away = summarise(pos[0]), summarise(pos[1])
    ball_summary = {
        "positions": [[round(x, 4), round(y, 4)] for x, y in ball[:300]],
        "centroid": ([round(sum(b[0] for b in ball) / len(ball), 4),
                      round(sum(b[1] for b in ball) / len(ball), 4)] if ball else None),
        "n": len(ball),
    }
    packet = {
        "source": "cv", "key": key, "clip": os.path.basename(clip),
        "frames_analysed": analysed,
        "homography": metres,
        "coords": "pitch_metres" if metres else "normalised_frame",
        "detector": {"weights": config.YOLO_WEIGHTS, "imgsz": config.YOLO_IMGSZ,
                     "conf": config.YOLO_CONF, "detections": n_person},
        "formation_home": home["formation"], "formation_away": away["formation"],
        "home": home, "away": away, "ball": ball_summary,
        "positions": ([{"x": p["x"], "y": p["y"], "team": "home"} for p in home["positions"]] +
                      [{"x": p["x"], "y": p["y"], "team": "away"} for p in away["positions"]]),
        "confidence": round(min(1.0, analysed / max(1, len(want))) *
                            min(1.0, (home["n"] + away["n"]) / 200.0), 3),
        "license": "Derived from rights-cleared / CC footage only (green-lane).",
    }

    os.makedirs(OUT_DIR, exist_ok=True)
    out = os.path.join(OUT_DIR, f"{key}.json")
    with open(out, "w", encoding="utf-8") as fh_:
        json.dump(packet, fh_, ensure_ascii=False, separators=(",", ":"))
    if verbose:
        print(f"  wrote {out}  (formations {packet['formation_home']} vs "
              f"{packet['formation_away']}, confidence {packet['confidence']})")
    return packet


def _opt(args: list[str], name: str) -> str | None:
    if name in args:
        i = args.index(name)
        if i + 1 < len(args):
            return args[i + 1]
    return None


def main(args: list[str]) -> int:
    if not args:
        print("usage:\n"
              "  python run.py cv <clip> --home \"Mexico\" --away \"South Africa\" "
              "--date 2026-06-11   (computes the fixture key for you — preferred)\n"
              "  python run.py cv <clip> --key mexico-south-africa-2026-06-11        "
              "(pass the exact key yourself)\n"
              "  [--frames N]   how many frames to sample (default 60)")
        return 1
    clip = next((a for a in args if not a.startswith("--")), None)
    if not clip:
        print("no clip path given"); return 1

    # Prefer --home/--away/--date so the key matches the fixture exactly (the Lab
    # attaches a CV board to a match only when data/tactics/<key>.json uses the same
    # key the server derives via models.tactics.match_key). --key overrides.
    key = _opt(args, "--key")
    home, away, date = _opt(args, "--home"), _opt(args, "--away"), _opt(args, "--date")
    if not key and home and away and date:
        key = match_key(home, away, date)
        print(f"  fixture key: {key}")
    elif not key:
        print("  note: no --key/--home+--away+--date given — using a key derived from "
              "the filename; this shows as a standalone showcase, not attached to a fixture.")

    frames = DEFAULT_FRAMES
    fopt = _opt(args, "--frames")
    if fopt and fopt.isdigit():
        frames = int(fopt)
    analyse(clip, key=key, frames=frames)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

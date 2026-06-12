WCPA — Quantum Tactics Lab :: CC clip workflow
==============================================

This folder is the drop zone for the computer-vision pipeline that lights up a
match's "shape board" in the Tactics Lab. It runs LOCALLY at build time only —
the deployed CDN site and the live server run no computer vision. Only the
derived numeric JSON (no frames, no stills) ever reaches the album.


STEP 0 — install the CV stack (one-off, local only)
----------------------------------------------------
    pip install opencv-python ultralytics

(These are optional build-time deps — see requirements.txt. They are NOT needed
to run the dashboard, and never ship to the CDN. First run auto-downloads a small
YOLO weights file, yolov8n.pt, which is gitignored.)


STEP 1 — get a clip you are allowed to use (GREEN-LANE)
-------------------------------------------------------
ONLY footage you have the right to process and publish analysis from:
  * Creative-Commons / public-domain football clips
  * clips you recorded yourself / own
  * footage you have an explicit licence for

Good free / CC sources (verify the licence on each item before downloading):
  * Wikimedia Commons — search "association football" video; filter PD / CC-BY(-SA)
      https://commons.wikimedia.org/
  * Internet Archive — public-domain & CC sports reels
      https://archive.org/details/movies
  * Pexels / Pixabay / Mixkit / Coverr — royalty-free stock video ("soccer",
      "football match"); free for commercial use, check each clip's terms

DO NOT use broadcast / TV / streamed match footage, or any clip without a clear
free licence. WCPA stays inside the green lane.

Camera angle matters for the CV: a WIDE / elevated / tactical angle showing many
players at once gives the best formation read. Tight broadcast-style close-ups
produce weak shape data. A fixed camera beats a panning one.

Drop the file here, e.g.  footage/sample.mp4


STEP 2 — run the pipeline, keyed to a fixture
---------------------------------------------
Attach the board to a real 2026 fixture by giving the teams + date — the tool
computes the exact key the Lab expects:

    python run.py cv footage/sample.mp4 --home "Mexico" --away "South Africa" --date 2026-06-11

That writes data/tactics/mexico-south-africa-2026-06-11.json (gitignored).
Use the EXACT team names as they appear in the fixtures (the Match Centre list).

For a standalone demo not tied to a fixture, just give a name:
    python run.py cv footage/sample.mp4 --key my-showcase-clip
(it then appears in the Lab picker tagged "◆ showcase".)

Options:
    --frames N     how many evenly-spaced frames to sample (default 60; more = slower, steadier)


STEP 3 (optional) — accurate 2D pitch mapping via homography
------------------------------------------------------------
Without this, positions are normalised frame coordinates (0..1) — fine for a
shape impression. For true pitch placement, drop <clip>.points.json beside the
clip with four image points (pixels) mapped to pitch metres (use clear pitch
landmarks: corners, penalty-box / centre-line intersections):

    {"image": [[x1,y1],[x2,y2],[x3,y3],[x4,y4]],
     "pitch": [[0,0],[105,0],[105,68],[0,68]]}


STEP 4 — publish (the CV board flows into the static album)
-----------------------------------------------------------
    python run.py export          # snapshots data/tactics/*.json into dist/api/tactics/
    deploy.bat                    # (or your wrangler pages deploy) → wcpa26.com

Reload the Lab, pick that match: the pitch board now shows the CV-read positions
+ inferred formation alongside the model's pre-match superposition. Matches with
no CV run simply show the projection — the page always works either way.


Notes
-----
* footage/ and data/tactics/ are gitignored — clips and CV output stay local;
  only this README is committed.
* The pipeline is deterministic for a given clip + frame count, so re-runs are
  reproducible.

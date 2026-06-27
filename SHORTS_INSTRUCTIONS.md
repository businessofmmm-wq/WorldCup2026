# WCPA YouTube Shorts — Instructions

## One-time setup

**1. Install ffmpeg** (required for MP4 output) — *already installed on this PC (Gyan.FFmpeg 8.1.1)*:
```
winget install ffmpeg
```
> The renderer auto-discovers ffmpeg via PATH, the winget Links shim, or the
> winget Packages folder, so it works even before a shell restart. Override with
> `set WCPA_FFMPEG=C:\path\to\ffmpeg.exe` if needed.

**2. Fix git lock (if VS Code shows git errors)**:
```
del "C:\Users\sambo\Desktop\WorldCup2026\.git\index.lock"
```

**3. Commit tonight's changes**:
```
cd C:\Users\sambo\Desktop\WorldCup2026
git add tools/shorts_gen.py tools/shorts_pipeline.py run.py models/schedule_2026.py
git commit -m "feat: animated YouTube Shorts system + R32 schedule"
```

**4. Add R32 fixtures to the database** (double-click in File Explorer):
```
C:\Users\sambo\Desktop\WorldCup2026\add_r32.bat
```
This inserts the 16 Round of 32 matches and regenerates `dist/api/fixtures.json`.

---

## Generating Shorts manually

All commands run from `C:\Users\sambo\Desktop\WorldCup2026`:

```bash
# R32 match preview (use before each knockout game)
python run.py shorts r32 --match "Germany|Sweden"
python run.py shorts r32 --match "Spain|Austria"

# Latest completed match result
python run.py shorts result
python run.py shorts result --match "Brazil|Japan"

# Today's predictions (all upcoming fixtures today)
python run.py shorts daily

# Title odds leaderboard (who wins the World Cup?)
python run.py shorts odds
```

Output lands in: `C:\Users\sambo\Desktop\WorldCup2026\out\shorts\`

---

## Voice-over (narration)

Every Short is **narrated by default** — a themed voice-over reads the model's
read on the match, the live record, and the title race, then signs off with
`wcpa26.com` and the "entertainment only" disclaimer. It uses the built-in
Windows SAPI5 engine (no install, no API key, no extra dependency). ffmpeg muxes
the narration over the animation and the video is auto-sized to cover the audio.

```bash
# Default: voiced with the en-GB "Hazel" broadcast voice
python run.py shorts r32 --match "Spain|Austria"

# Pick a different voice (substring match: Hazel | Zira | David)
python run.py shorts daily --voice-name Zira

# Slow it down / speed it up  (-10 slow … 10 fast, default -1)
python run.py shorts odds --rate -3

# Silent (animation only, original behaviour)
python run.py shorts result --no-voice
```

Voices on this PC: **Hazel** (en-GB female, default), **Zira** (en-US female),
**David** (en-US male). The same flags work on `shorts watch`. Equivalent env
vars (handy for scheduled tasks): `WCPA_SHORTS_VOICE=0` (off),
`WCPA_SHORTS_VOICE_NAME`, `WCPA_SHORTS_VOICE_RATE`.

If SAPI5 is somehow unavailable the Short still renders — just silent.

---

## Live production pipeline (auto-mode)

Watches for new results and exports, generates Shorts automatically:

```bash
# Run in background — poll every 60 seconds
python run.py shorts watch

# Open each MP4 automatically when generated
python run.py shorts watch --auto-open

# Faster polling during match days
python run.py shorts watch --interval 30 --auto-open

# Single scan (good for a scheduled task / cron)
python run.py shorts watch --once
```

**What it auto-generates:**
- New result detected → `result` short
- First run after 06:00 UTC → `daily` short
- New export detected → `odds` short (max once per hour)

Pipeline state: `out/shorts/.pipeline_state.json`
Pipeline log:   `out/shorts/pipeline.log`

---

## Match day workflow

1. Run `python run.py ingest live` to pull latest results
2. Run `python run.py shorts r32 --match "Team A|Team B"` for the next match preview
3. After the game: `python run.py shorts result` for the result card
4. Run `python run.py refresh` to retrain + resim
5. Run `python run.py export dist` to push to Cloudflare Pages

Or just start `shorts watch --auto-open` and it handles steps 3–5 automatically.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `No completed matches` | Run `python run.py ingest live` first |
| `No R32 match found` | Run `add_r32.bat` to insert R32 fixtures |
| PNG output instead of MP4 | Install ffmpeg: `winget install ffmpeg` |
| Short has no audio | SAPI5 not found — rare on Windows; or you passed `--no-voice` |
| Voice too fast/robotic | `--rate -3` to slow down, or `--voice-name Zira` |
| Git lock error | `del "C:\Users\sambo\Desktop\WorldCup2026\.git\index.lock"` |
| DB connection refused | PostgreSQL must be running locally on port 5432 |

---

*Built 2026-06-27 · wcpa26.com*

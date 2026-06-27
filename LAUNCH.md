# WCPA — Launch Checklist

**What this is:** the public-launch playbook for *WCPA — the World Cup '26
Prediction Album*. The site is built and proven end-to-end as a **static site** (no
server, no database exposed) so it costs **$0**, scales through a traffic spike, and
has essentially no attack surface. Earliest publish: **9 June 2026, 08:00 AEST** (hard gate); live for kickoff **11 June 2026**.

---

## ✅ Already done (in the code)

- **Dashboard finished**: cover + brand, Title Odds, **Match Centre** (every fixture
  with the model's call + a live "model record" once results land), Wallchart, Groups,
  Power Rankings, Match Lab, Team Intel, Method.
- **Rebranded** to *WCPA*, every page locked to the event ("World Cup '26 ·
  Prediction Album") so a first-time visitor instantly gets what it is.
- **Share-ready**: Open Graph / Twitter cards, `og-cover.png`, favicon, sitemap, robots.
- **Monetisation wired (lean & legal)**: tip jar + "Club Shop" affiliate shelf (#Ad
  labelled), **no betting/bookmaker links** (deliberate — see Legal).
- **Legal**: `/about.html` with Disclaimer, Privacy, Terms, Affiliate disclosure;
  footer disclaimer ("model output, not gambling advice; not affiliated with FIFA").
- **Static export** (`python run.py export`) → `./dist`, with the Match Lab, rankings
  trajectories and intel filter all working offline from snapshot files.

---

## 🚀 To go live — your steps (≈1–2 hours)

1. **Domain** — `wcpa26.com` ✓ **registered** (purchased).
   *(Attach it to Cloudflare Pages in step 4.)*

2. **One-time CDN setup** (Cloudflare Pages — free):
   ```
   npm install -g wrangler
   wrangler login
   wrangler pages project create wcpa
   ```

3. **First deploy** — from this folder:
   ```
   python run.py export dist
   npx wrangler pages deploy dist --project-name=wcpa
   ```
   You'll get a live `*.pages.dev` URL immediately. (Or just run `deploy.bat`.)

4. **Attach the domain** — Cloudflare Pages → your project → *Custom domains* →
   add `wcpa26.com`. (If the domain is on Cloudflare, this is one click.)

5. **Tip jar + Stripe** — ✓ **Ko-fi wired** (`ko-fi.com/sambowey1110`) and ✓ **Stripe
   "Back the project" wired** via the **LIVE** Payment Link in `LINKS.back`
   (`viz/static/app.js`). Both are public, shareable URLs — safe to commit. The Stripe
   *secret* (`rk_`/`sk_`) and the Ko-fi *webhook token* live only in `Desktop\Session1.txt`,
   never in the repo or the static build. After any change here, re-export.

6. **Affiliate shop** — join non-gambling programs that fit the brand (retro kits,
   football culture goods — e.g. an Amazon Associates tag, or a kit retailer's program).
   Edit the `SHOP` array in `viz/static/app.js` with real links. Keep the `#Ad` label.

7. **Contact email** — set up forwarding for `hello@wcpa26.com` (used on /about).

---

## 🔁 Keeping it "live" during the tournament

The site is a snapshot, so refresh it on a schedule. `deploy.bat` does the whole
pipeline: **ingest live results → retrain → simulate 50k → export → deploy.**

- **Windows Task Scheduler** → new task → run `deploy.bat` every **30–60 min** during
  match days (your PC must be on; the DB lives here). Matches are only a few times a
  day, so hourly is plenty. The "● LIVE" countdown badge flips automatically on 11 June.

---

## ⚖️ Legal (Australia) — status

- ✅ **Not gambling advice / not betting** — the single most important guardrail. We
  show **no bookmaker links and take no betting-affiliate money** (AU *Interactive
  Gambling Act* / ACMA risk). Keep it that way.
- ✅ **#Ad disclosure** on affiliate links (ACCC).
- ✅ **Disclaimer, Privacy, Terms** live at `/about.html`. No accounts, no tracking
  cookies — privacy stays simple.
- ✅ **"Not affiliated with FIFA"** + no official emblems (trademark safety).
- ⬜ **ABN + GST**: register an ABN now; GST only once turnover passes **$75k**.
- ⬜ **W-8BEN**: only needed if you add US ad networks later (not at launch).

---

## 💡 After launch (nice-to-haves, not blockers)

- Per-match share images (auto-generate an OG card per fixture for viral sharing).
- A "premium" digital product later (printable foil wallchart / Pro stats) via Lemon
  Squeezy — your "digital products first" lane. Deliberately deferred to keep launch clean.
- Tighten news team-tagging to the 48-team field; broaden xG coverage.

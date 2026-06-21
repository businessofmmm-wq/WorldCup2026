# WCPA26 — Quick Monetisation Plan

**Context:** wcpa26.com is live *during* the 2026 World Cup — traffic is peaking now, so
speed matters more than polish. The site already has three monetisation hooks half-built:
a "Buy me a coffee" / "Back the project" support button (`tipBtn`/`backBtn` in
`index.html`), SHOP affiliate placeholders in `app.js`, and a public JSON API
(`/api/*.json`). The fastest money comes from *finishing what's already there*.

_Not financial or legal advice — gambling-affiliate and ad rules vary by country; verify
before shipping._

## Ranked by speed-to-revenue

| # | Lever | Effort | Revenue potential | Risk | Ship in |
|---|-------|--------|-------------------|------|---------|
| 1 | Tip jar (finish `tipBtn`) | ~15 min | Low | None | Today |
| 2 | Display ads (AdSense/Ezoic) | ~1–3 h + approval | Med (scales w/ traffic) | Low | 1–3 days |
| 3 | Amazon affiliate merch (SHOP) | ~1–2 h | Low–Med | Low | Today |
| 4 | Premium picks / data (Patreon or paywall) | ~1–2 days | Med–High | Low | This week |
| 5 | Sportsbook affiliate | ~1 day + approval | **High** | **High (legal/trust)** | 1–2 weeks |

## The quick wins (do these first)

**1 — Turn on the tip jar (today).** The button exists and points nowhere
(`href="#"`). Create a [Ko-fi](https://ko-fi.com) or Buy Me a Coffee page and drop the URL
into `tipBtn`. Zero new code, zero risk, live in minutes. Realistic but small — think
coffee money, not rent.

**2 — Display ads (this week, the workhorse).** Your traffic is the asset; ads convert it
directly. Google AdSense is fastest to apply for; Ezoic/Mediavine pay better RPMs once you
clear their traffic thresholds. Place one unobtrusive unit between album pages (e.g. after
the Odds page) so it doesn't wreck the "album" feel. Caveat: AdSense approval takes a few
days and needs a privacy policy + cookie notice. This is the most reliable medium-term
earner for a high-traffic info site.

**3 — Amazon Associates merch (today).** The SHOP placeholders in `app.js` are built for
exactly this. Sign up for Amazon Associates, swap the placeholder IDs for real affiliate
tags on contextual products (nation kits, balls, the official match ball, a 4K TV on the
final). Low conversion, but it's already wired and on-theme.

## The bigger plays (worth a week)

**4 — Premium predictions / data feed.** This is your real edge: a leakage-free,
RPS-tuned model nobody else is running. Package it:
- *Patreon / paid tier*: pre-match "model edge" picks, a daily title-odds email, or a
  no-ads + early-access view. The frozen pre-kickoff `predictions` table is perfect source
  material.
- *Data licensing*: you already export `/api/*.json`. Gate a richer feed (full scoreline
  grids, per-match probabilities) behind a key and sell it to fantasy/blog sites. Low
  marginal cost, recurring revenue.

**5 — Sportsbook affiliate (highest revenue, handle with care).** Your audience is
literally people weighing match outcomes, so betting affiliates pay the most per
conversion. But the trade-offs are real and worth weighing honestly:
- *Legal*: gambling-affiliate marketing is regulated and often licensed per
  jurisdiction (UK GC, US state-by-state, etc.). You must geo-gate and add responsible-
  gambling notices.
- *Trust*: a neutral "prediction album" that suddenly pushes bookmakers can read as
  conflicted — it may dent the credibility that draws people in.
- *Platform risk*: AdSense and app stores have rules about gambling content that can
  conflict with lever #2.
  If you pursue it, do it cleanly: a single clearly-labelled "odds provider" partner,
  geo-restricted, with 18+/responsible-gambling messaging — not scattered bet links.

## Recommended sequence

Today: tip jar (#1) + Amazon IDs (#3) — both already coded, zero risk, captures
World-Cup traffic immediately. This week: apply for AdSense (#2) and stand up a simple
Patreon tier (#4). Park the sportsbook decision (#5) until you've decided whether the
revenue is worth the trust/legal overhead — it's the big number, but it changes what the
site *is*.

I can wire up #1 and #3 right now (real links/IDs you provide), draft the privacy policy +
ad-slot markup for #2, or scaffold a gated premium `/api` endpoint for #4 — say which.

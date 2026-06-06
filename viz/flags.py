"""
Team -> flag + confederation lookups for the dashboard.

Flags are served as public-domain country images from flagcdn.com (no key, no
licence concern — national flags). Keys are the exact martj42 dataset team
strings so they line up with everything else in the engine. Home nations use the
GB subdivision codes flagcdn supports (gb-eng / gb-sct / gb-wls / gb-nir).

`flag_url(team)` returns an SVG flag URL (crisp at any size) or None if we do not
have a mapping; the front-end falls back to a printed team code in that case.
"""
from __future__ import annotations

# martj42 team string -> ISO 3166-1 alpha-2 (lower-case) / flagcdn subdivision.
ISO2: dict[str, str] = {
    # --- 2026 field (all 48) ------------------------------------------------
    "Mexico": "mx", "South Africa": "za", "South Korea": "kr", "Czech Republic": "cz",
    "Canada": "ca", "Bosnia and Herzegovina": "ba", "Qatar": "qa", "Switzerland": "ch",
    "Brazil": "br", "Morocco": "ma", "Haiti": "ht", "Scotland": "gb-sct",
    "United States": "us", "Paraguay": "py", "Australia": "au", "Turkey": "tr",
    "Germany": "de", "Curaçao": "cw", "Ivory Coast": "ci", "Ecuador": "ec",
    "Netherlands": "nl", "Japan": "jp", "Sweden": "se", "Tunisia": "tn",
    "Belgium": "be", "Egypt": "eg", "Iran": "ir", "New Zealand": "nz",
    "Spain": "es", "Cape Verde": "cv", "Saudi Arabia": "sa", "Uruguay": "uy",
    "France": "fr", "Senegal": "sn", "Iraq": "iq", "Norway": "no",
    "Argentina": "ar", "Algeria": "dz", "Austria": "at", "Jordan": "jo",
    "Portugal": "pt", "DR Congo": "cd", "Uzbekistan": "uz", "Colombia": "co",
    "England": "gb-eng", "Croatia": "hr", "Ghana": "gh", "Panama": "pa",
    # --- other nations that can surface in the Elo power rankings -----------
    "Italy": "it", "Denmark": "dk", "Serbia": "rs", "Ukraine": "ua",
    "Nigeria": "ng", "Cameroon": "cm", "Costa Rica": "cr", "Jamaica": "jm",
    "Bolivia": "bo", "Peru": "pe", "Chile": "cl", "Venezuela": "ve",
    "Wales": "gb-wls", "Northern Ireland": "gb-nir", "Republic of Ireland": "ie",
    "Poland": "pl", "Hungary": "hu", "Greece": "gr", "Romania": "ro",
    "Russia": "ru", "Slovakia": "sk", "Slovenia": "si", "Finland": "fi",
    "Iceland": "is", "Albania": "al", "North Macedonia": "mk", "Montenegro": "me",
    "Georgia": "ge", "Israel": "il", "Mali": "ml", "Burkina Faso": "bf",
    "Guinea": "gn", "Zambia": "zm", "Nigeria ": "ng", "Angola": "ao",
    "Gabon": "ga", "Benin": "bj", "Mauritania": "mr", "Madagascar": "mg",
    "United Arab Emirates": "ae", "Oman": "om", "Bahrain": "bh", "Kuwait": "kw",
    "China PR": "cn", "China": "cn", "Thailand": "th", "Vietnam": "vn",
    "Honduras": "hn", "El Salvador": "sv", "Guatemala": "gt", "Trinidad and Tobago": "tt",
}

# Confederation -> retro colour pair (ink, wash) used to tint sticker spines so
# the album reads by region at a glance. Confederation membership comes from
# models.field_2026.CONFED_OF.
CONFED_COLOR: dict[str, str] = {
    "UEFA": "#243b6b",       # navy
    "CONMEBOL": "#1f8a70",    # vintage teal-green
    "CONCACAF": "#c2362f",    # retro red
    "CAF": "#e6a817",         # mustard gold
    "AFC": "#d2541b",         # terracotta
    "OFC": "#6b4f8a",         # faded purple
    "?": "#5b5145",           # unknown / ink-brown
}

FLAG_CDN = "https://flagcdn.com"


def flag_url(team: str, fmt: str = "svg", width: str = "w160") -> str | None:
    """Flag image URL for a team, or None if unmapped.

    fmt='svg' -> crisp vector (default); fmt='png' -> raster at `width`
    (e.g. 'w40','w80','w160','w320').
    """
    code = ISO2.get(team)
    if not code:
        return None
    if fmt == "png":
        return f"{FLAG_CDN}/{width}/{code}.png"
    return f"{FLAG_CDN}/{code}.svg"


def iso2(team: str) -> str | None:
    return ISO2.get(team)

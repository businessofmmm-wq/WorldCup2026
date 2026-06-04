"""
Official 48-team draw for the 2026 FIFA World Cup (USA / Canada / Mexico).

The final draw was made on 5 December 2025 in Washington, D.C.; the last six
slots (four UEFA play-off paths + two inter-confederation play-off winners) were
filled by the March 2026 play-offs. `OFFICIAL_GROUPS` below is that final,
fully-resolved draw — twelve groups of four, teams listed in their drawn
position order (1..4). Team strings match the martj42 historical dataset so Elo
and Dixon-Coles ratings resolve exactly (verified: all 48 map to real ratings,
no 1500 fallbacks).

`tournament.py` consumes `OFFICIAL_GROUPS` directly as a fixed draw; `FIELD`,
`HOSTS` and `CONFED_OF` remain available for the legacy random-draw fallback.
"""

# Hosts qualify automatically and held fixed seeded slots: Mexico A1, Canada B1,
# United States D1.
HOSTS = ["Mexico", "Canada", "United States"]

# The official final draw — twelve groups, drawn position order preserved.
OFFICIAL_GROUPS = {
    "A": ["Mexico", "South Africa", "South Korea", "Czech Republic"],
    "B": ["Canada", "Bosnia and Herzegovina", "Qatar", "Switzerland"],
    "C": ["Brazil", "Morocco", "Haiti", "Scotland"],
    "D": ["United States", "Paraguay", "Australia", "Turkey"],
    "E": ["Germany", "Curaçao", "Ivory Coast", "Ecuador"],
    "F": ["Netherlands", "Japan", "Sweden", "Tunisia"],
    "G": ["Belgium", "Egypt", "Iran", "New Zealand"],
    "H": ["Spain", "Cape Verde", "Saudi Arabia", "Uruguay"],
    "I": ["France", "Senegal", "Iraq", "Norway"],
    "J": ["Argentina", "Algeria", "Austria", "Jordan"],
    "K": ["Portugal", "DR Congo", "Uzbekistan", "Colombia"],
    "L": ["England", "Croatia", "Ghana", "Panama"],
}

# Confederation membership (used only by the legacy random-draw fallback's
# spreading heuristic; the real draw above is fixed and bypasses it).
CONFEDERATION = {
    "UEFA": ["Czech Republic", "Bosnia and Herzegovina", "Switzerland", "Scotland",
             "Turkey", "Germany", "Netherlands", "Sweden", "Belgium", "Spain",
             "France", "Norway", "Austria", "Portugal", "England", "Croatia"],
    "CONMEBOL": ["Brazil", "Paraguay", "Ecuador", "Uruguay", "Argentina", "Colombia"],
    "CAF": ["South Africa", "Morocco", "Ivory Coast", "Tunisia", "Egypt",
            "Cape Verde", "Senegal", "Algeria", "DR Congo", "Ghana"],
    "AFC": ["South Korea", "Qatar", "Australia", "Japan", "Iran",
            "Saudi Arabia", "Iraq", "Uzbekistan", "Jordan"],
    "CONCACAF": ["Mexico", "Canada", "United States", "Haiti", "Panama", "Curaçao"],
    "OFC": ["New Zealand"],
}

CONFED_OF = {team: conf for conf, teams in CONFEDERATION.items() for team in teams}

# Flat field, derived from the draw (kept for the legacy fallback / callers).
FIELD = [t for teams in OFFICIAL_GROUPS.values() for t in teams]

assert len(FIELD) == 48, f"field has {len(FIELD)} teams, expected 48"
assert len(set(FIELD)) == 48, "duplicate team in the official draw"
assert all(t in CONFED_OF for t in FIELD), "a drawn team has no confederation"

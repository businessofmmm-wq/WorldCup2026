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

# --------------------------------------------------------------------------- #
# Official 2026 knockout bracket (FIFA match numbers 73-104).
#
# Group winners ("1X") and runners-up ("2X") occupy fixed slots by letter; the
# eight best third-placed teams fill the eight "T##" slots subject to the
# ALLOWED_THIRDS group constraints (FIFA Annex C: a third can only meet certain
# group winners, and never one from its own group). The bracket then flows
# deterministically R32 -> R16 -> QF -> SF -> Final, so a simulated group result
# maps to a single, real bracket path (the two top seeds sit in opposite halves,
# exactly as the published draw intends).
# --------------------------------------------------------------------------- #
R32 = [
    (73, "2A", "2B"),  (74, "1E", "T74"), (75, "1F", "2C"),  (76, "1C", "2F"),
    (77, "1I", "T77"), (78, "2E", "2I"),  (79, "1A", "T79"), (80, "1L", "T80"),
    (81, "1D", "T81"), (82, "1G", "T82"), (83, "2K", "2L"),  (84, "1H", "2J"),
    (85, "1B", "T85"), (86, "1J", "2H"),  (87, "1K", "T87"), (88, "2D", "2G"),
]

# Third-placed slot -> allowed group letters (FIFA Annex C placeholder ranges).
ALLOWED_THIRDS = {
    "T74": set("ABCDF"), "T77": set("CDFGH"), "T79": set("CEFHI"),
    "T80": set("EHIJK"), "T81": set("BEFIJ"), "T82": set("AEHIJ"),
    "T85": set("EFGIJ"), "T87": set("DEIJL"),
}

# match -> (source match 1, source match 2); the winners of the sources meet.
BRACKET = {
    89: (74, 77), 90: (73, 75), 91: (76, 78), 92: (79, 80),
    93: (83, 84), 94: (81, 82), 95: (86, 88), 96: (85, 87),   # R16
    97: (89, 90), 98: (93, 94), 99: (91, 92), 100: (95, 96),  # QF
    101: (97, 98), 102: (99, 100),                            # SF
    104: (101, 102),                                          # Final
}

# Stage a match WINNER reaches (the loser stays at the round it lost in).
WINNER_STAGE = {**{m: "r16" for m in range(73, 89)},
                **{m: "qf" for m in range(89, 97)},
                **{m: "sf" for m in range(97, 101)},
                101: "final", 102: "final", 104: "champion"}

# Flat field, derived from the draw (kept for the legacy fallback / callers).
FIELD = [t for teams in OFFICIAL_GROUPS.values() for t in teams]

assert len(FIELD) == 48, f"field has {len(FIELD)} teams, expected 48"
assert len(set(FIELD)) == 48, "duplicate team in the official draw"
assert all(t in CONFED_OF for t in FIELD), "a drawn team has no confederation"

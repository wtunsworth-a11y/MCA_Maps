"""Read the metadata that the source file names encode.

The survey exports carry their attributes in the file name rather than in the
GeoPackage fields, in two conventions that appear across the zones:

    Jethro_Akse_Asingi_Clan_Land_Boundary_Zone_2_14July2026
    └─ steward ─┘ └clan┘                  └zone┘ └─ date ─┘

    manuvoora_clan_egobeyas_kuarisi_tracks_zone_6
    └─ clan ─┘     └─── steward ────┘     └zone┘

Both put the clan name next to the word "clan", so that word anchors the
parse: whichever side holds the leftover tokens is the steward. Everything
here is a best-effort read of a human naming habit — `parse` never raises, and
falls back to leaving fields empty.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, asdict

# Tokens that are structure, not names.
NOISE = {"land", "boundary", "boundaries", "tracks", "track", "site", "sites",
         "sacred", "zone", "zn", "clan", "and", "the", "of", "road", "roads",
         "block", "blocks", "steward", "stewardship"}

DATE_PATTERN = re.compile(r"(\d{1,2})([A-Za-z]{3,9})(\d{2,4})")
ZONE_PATTERN = re.compile(r"(?:zone|zn)[_\s-]*(\d+\s*[ab]?)", re.IGNORECASE)

# Clan names confirmed by the survey team as spelling variants of one clan.
# Both pairs below were flagged first by name similarity and then corroborated
# by near-total polygon overlap (99%/78% and 71%/97%), and confirmed as typos.
# The value is the spelling kept; change it here and it changes everywhere.
CLAN_ALIASES = {
    "manuvuoora": "Manuvoora",
    "sungulkol": "Sugulkol",
}

MONTHS = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
          "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


@dataclass
class ClanRecord:
    """What a source file name tells us about the survey it holds."""

    clan: str = ""
    steward: str = ""
    zone: str = ""
    feature_type: str = "Land Boundary"
    survey_date: str = ""
    source_name: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def parse(name: str, source_path: "os.PathLike | str | None" = None) -> ClanRecord:
    """Pull clan, steward, zone, type and date out of a layer name.

    Some files omit the zone from their own name, so ``source_path`` is used as
    a fallback: they still sit inside a "Zone 2 Clan Land Boundaries" archive,
    and that is authoritative about which zone they belong to.
    """
    record = ClanRecord(source_name=name)
    working = name

    if (zone_match := ZONE_PATTERN.search(working)):
        record.zone = _tidy_zone(zone_match.group(1))
        working = working[:zone_match.start()] + " " + working[zone_match.end():]
    elif source_path and (path_match := ZONE_PATTERN.search(str(source_path))):
        record.zone = _tidy_zone(path_match.group(1))

    if (date_match := DATE_PATTERN.search(working)):
        record.survey_date = _tidy_date(date_match)
        working = working[:date_match.start()] + " " + working[date_match.end():]

    # Underscores are word characters, so \b never fires at a token edge here.
    if re.search(r"sacred", name, re.IGNORECASE):
        record.feature_type = "Sacred Site"
    elif re.search(r"(?:^|[_\s-])roads?(?:[_\s-]|$)", name, re.IGNORECASE):
        record.feature_type = "Road"
    elif re.search(r"(?:^|[_\s-])steward(?:ship)?(?:[_\s-]|$)", name,
                   re.IGNORECASE):
        record.feature_type = "Steward Block"

    tokens = [t for t in re.split(r"[_\s-]+", working) if t]
    clan_index = next((i for i, t in enumerate(tokens)
                       if t.lower() == "clan"), None)

    if clan_index is None:
        record.steward = _titlecase(_drop_noise(tokens))
        record.clan = CLAN_ALIASES.get(record.clan.lower(), record.clan)
        return record

    before = _drop_noise(tokens[:clan_index])
    after = _drop_noise(tokens[clan_index + 1:])

    # Which side of the anchor the steward sits on is decided by whether any
    # real name survives after it: "<clan> Clan <steward>" keeps names on the
    # right, "<steward> <clan> Clan Land Boundary" has only noise there.
    if after:
        # Everything before the anchor is the clan — clan names run to two
        # words ("Nupa Ora"), so taking only the last token would truncate them.
        record.clan = _titlecase(before)
        record.steward = _titlecase(after)
    elif len(before) >= 2:
        record.clan = _titlecase([before[-1]])
        record.steward = _titlecase(before[:-1])
    else:
        record.clan = _titlecase(before)

    record.clan = CLAN_ALIASES.get(record.clan.lower(), record.clan)
    return record


def _drop_noise(tokens: list[str]) -> list[str]:
    """Keep only tokens that could be part of a person's or clan's name.

    Anything containing a digit is structure or a date fragment, never a name.
    """
    return [t for t in tokens
            if t.lower() not in NOISE and not any(ch.isdigit() for ch in t)]


def _titlecase(tokens: list[str]) -> str:
    return " ".join(t[:1].upper() + t[1:] for t in tokens if t).strip()


def _tidy_zone(raw: str) -> str:
    cleaned = raw.strip().upper().replace(" ", "")
    return f"Zone {cleaned}"


def _tidy_date(match: re.Match) -> str:
    """Render 14July2026 as an ISO date, or return the text if it won't parse."""
    day, month_name, year = match.groups()
    month = MONTHS.get(month_name[:3].lower())
    if not month or len(year) < 4:
        # A two-digit year is a truncated file name, not a real date — report
        # the text as-is rather than inventing a century for it.
        return match.group(0)
    try:
        return f"{int(year):04d}-{month:02d}-{int(day):02d}"
    except ValueError:
        return match.group(0)

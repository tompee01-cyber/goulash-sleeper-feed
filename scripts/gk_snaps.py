"""Goulash Kingdom nflverse/PFR snap-count raw feed."""

import re
import statistics
import unicodedata

SNAP_SCHEMA_VERSION = "GK_SNAPS_V1"
SNAP_SOURCE_TEMPLATE = (
    "https://github.com/nflverse/nflverse-data/releases/"
    "download/snap_counts/snap_counts_{season}.csv"
)
PLAYER_IDS_URL = (
    "https://raw.githubusercontent.com/dynastyprocess/data/"
    "master/files/db_playerids.csv"
)

TEAM_ALIASES = {
    "KCC": "KC",
    "LVR": "LV",
    "SFO": "SF",
    "TBB": "TB",
    "GNB": "GB",
    "GBP": "GB",
    "JAC": "JAX",
    "NOR": "NO",
    "NOS": "NO",
    "NEP": "NE",
}


def as_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text or text.upper() in {"NA", "N/A", "NULL", "NONE"}:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def normalize_pct(value):
    number = as_number(value)
    if number is None:
        return None
    if number > 1.0:
        number /= 100.0
    return round(max(0.0, min(1.0, number)), 6)


def normalize_team(team):
    if team is None:
        return None
    text = str(team).strip().upper()
    if not text or text in {"NA", "N/A", "NONE", "NULL"}:
        return None
    return TEAM_ALIASES.get(text, text)


def normalize_name(name):
    if name is None:
        return ""
    text = unicodedata.normalize("NFKD", str(name))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower().replace(".", "")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", text)
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _int_or_none(value):
    number = as_number(value)
    return int(number) if number is not None else None


def normalize_snap_row(row):
    if not isinstance(row, dict):
        return None
    week = _int_or_none(row.get("week"))
    season = _int_or_none(row.get("season"))
    player = row.get("player")
    team = normalize_team(row.get("team"))
    if not week or not season or not player or not team:
        return None

    pfr_player_id = str(row.get("pfr_player_id") or "").strip()
    if not pfr_player_id or pfr_player_id.upper() in {"NA", "N/A", "NONE", "NULL"}:
        pfr_player_id = None

    game_type = str(row.get("game_type") or "").strip().upper() or None

    return {
        "season": season,
        "week": week,
        "game_type": game_type,
        "game_id": row.get("game_id"),
        "pfr_game_id": row.get("pfr_game_id"),
        "full_name": str(player).strip(),
        "normalized_name": normalize_name(player),
        "pfr_player_id": pfr_player_id,
        "source_position": row.get("position"),
        "team": team,
        "opponent": normalize_team(row.get("opponent")),
        "off_snaps": _int_or_none(row.get("offense_snaps")),
        "off_snap_pct": normalize_pct(row.get("offense_pct")),
        "def_snaps": _int_or_none(row.get("defense_snaps")),
        "def_snap_pct": normalize_pct(row.get("defense_pct")),
        "st_snaps": _int_or_none(row.get("st_snaps")),
        "st_snap_pct": normalize_pct(row.get("st_pct")),
    }


def _game_team_key(row):
    game_id = row.get("game_id")
    if game_id:
        return (str(row.get("season")), int(row.get("week") or 0), str(game_id), str(row.get("team")))
    return (
        str(row.get("season")),
        int(row.get("week") or 0),
        str(row.get("team")),
        str(row.get("opponent")),
    )


def attach_team_denominators(rows):
    rows = [dict(row) for row in (rows or [])]
    candidates = defaultdict(lambda: {"OFF": [], "DEF": [], "ST": []})
    unit_fields = {
        "OFF": ("off_snaps", "off_snap_pct"),
        "DEF": ("def_snaps", "def_snap_pct"),
        "ST": ("st_snaps", "st_snap_pct"),
    }

    for row in rows:
        key = _game_team_key(row)
        for unit, (snap_key, pct_key) in unit_fields.items():
            snaps = as_number(row.get(snap_key))
            pct = as_number(row.get(pct_key))
            if snaps is None or pct is None or snaps <= 0 or pct <= 0:
                continue
            estimate = snaps / pct
            if 1 <= estimate <= 250:
                candidates[key][unit].append(estimate)

    totals = {}
    for key, unit_values in candidates.items():
        totals[key] = {}
        for unit, values in unit_values.items():
            totals[key][unit] = (
                int(round(statistics.median(values)))
                if values
                else None
            )

    for row in rows:
        unit_totals = totals.get(_game_team_key(row), {})
        row["team_off_snaps"] = unit_totals.get("OFF")
        row["team_def_snaps"] = unit_totals.get("DEF")
        row["team_st_snaps"] = unit_totals.get("ST")
    return rows


import csv
import io
import urllib.request


def _fetch_text(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "goulash-sleeper-feed/3.0",
            "Accept": "text/csv,text/plain,*/*",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return response.read().decode("utf-8-sig")


def read_csv_text(text):
    return list(csv.DictReader(io.StringIO(text)))


def fetch_snap_rows(season, fetch_text=None):
    fetch_text = fetch_text or _fetch_text
    url = SNAP_SOURCE_TEMPLATE.format(season=str(season))
    rows = []
    for raw in read_csv_text(fetch_text(url)):
        record = normalize_snap_row(raw)
        if record is None:
            continue
        if record.get("game_type") not in {None, "", "REG"}:
            continue
        rows.append(record)
    if not rows:
        raise ValueError(
            "nflverse snap source returned no valid regular-season rows"
        )
    return attach_team_denominators(rows), url


def fetch_player_id_rows(fetch_text=None):
    fetch_text = fetch_text or _fetch_text
    rows = read_csv_text(fetch_text(PLAYER_IDS_URL))
    return rows, PLAYER_IDS_URL

from collections import defaultdict


def _clean_id(value):
    text = str(value or "").strip()
    return None if not text or text.upper() in {"NA", "N/A", "NONE", "NULL"} else text


def build_id_crosswalk(id_rows, valid_sleeper_ids=None):
    result = {}
    valid = (
        {str(pid) for pid in valid_sleeper_ids}
        if valid_sleeper_ids is not None
        else None
    )
    for row in id_rows or []:
        pfr_id = _clean_id(row.get("pfr_id"))
        sleeper_id = _clean_id(row.get("sleeper_id"))
        if not pfr_id or not sleeper_id:
            continue
        if valid is not None and sleeper_id not in valid:
            continue
        result[pfr_id] = sleeper_id
    return result


def build_sleeper_name_team_index(league_data):
    index = defaultdict(list)
    for pid, player in (league_data.get("players") or {}).items():
        name = normalize_name(player.get("full_name"))
        team = normalize_team(player.get("team"))
        if name and team:
            index[(name, team)].append(str(pid))
    return dict(index)


def match_snap_record(record, pfr_to_sleeper, name_team_index, aliases=None):
    out = dict(record)
    pfr_id = record.get("pfr_player_id")

    if pfr_id and pfr_id in pfr_to_sleeper:
        out["player_id"] = str(pfr_to_sleeper[pfr_id])
        out["match_quality"] = "Exact"
        return out

    aliases = aliases or {}
    alias_pid = aliases.get(pfr_id) if pfr_id else None
    if alias_pid:
        out["player_id"] = str(alias_pid)
        out["match_quality"] = "Alias"
        return out

    candidates = name_team_index.get(
        (record.get("normalized_name"), normalize_team(record.get("team"))),
        [],
    )
    if len(candidates) == 1:
        out["player_id"] = str(candidates[0])
        out["match_quality"] = "NameTeam"
    elif len(candidates) > 1:
        out["player_id"] = None
        out["match_quality"] = "Ambiguous"
    else:
        out["player_id"] = None
        out["match_quality"] = "Unmatched"
    return out

OFF_FANTASY = {"QB", "RB", "WR", "TE"}
DEF_FANTASY = {"DL", "LB", "DB"}


def primary_unit_for(player_meta):
    fantasy = {str(x).upper() for x in (player_meta.get("fantasy_positions") or [])}
    primary = str(player_meta.get("position") or "").upper()
    if primary == "K" or "K" in fantasy:
        return "ST"
    if fantasy & OFF_FANTASY or primary in OFF_FANTASY:
        return "OFF"
    if fantasy & DEF_FANTASY or primary in {
        "DE", "DT", "NT", "EDGE", "OLB", "ILB", "MLB", "CB", "S", "FS", "SS"
    }:
        return "DEF"
    return "ST"


def build_week_records(week, matched_rows, league_data):
    records = {}
    diagnostics = []
    players = league_data.get("players") or {}

    for row in matched_rows:
        if int(row.get("week") or 0) != int(week):
            continue

        pid = row.get("player_id")
        if not pid or row.get("match_quality") in {"Unmatched", "Ambiguous"}:
            diagnostics.append(dict(row))
            continue

        player_meta = players.get(str(pid))
        if not isinstance(player_meta, dict):
            diagnostic = dict(row)
            diagnostic["diagnostic_reason"] = "PlayerNotInLeagueIndex"
            diagnostics.append(diagnostic)
            continue

        unit = primary_unit_for(player_meta)
        snap_key = {"OFF": "off_snaps", "DEF": "def_snaps", "ST": "st_snaps"}[unit]
        pct_key = {
            "OFF": "off_snap_pct",
            "DEF": "def_snap_pct",
            "ST": "st_snap_pct",
        }[unit]

        record = dict(row)
        record.pop("normalized_name", None)
        record["player_id"] = str(pid)
        record["primary_unit"] = unit
        record["primary_snaps"] = row.get(snap_key)
        record["primary_snap_pct"] = row.get(pct_key)
        record["source"] = "nflverse/PFR"
        records[str(pid)] = record

    return records, diagnostics

import copy
from datetime import datetime, timezone


def determine_refresh_weeks(current_week, existing):
    current_week = int(current_week)
    all_weeks = list(range(1, current_week + 1))
    if not existing or existing.get("schema_version") != SNAP_SCHEMA_VERSION:
        return all_weeks, True

    present = {
        int(w)
        for w in (existing.get("weekly_snaps") or {})
        if str(w).isdigit()
    }
    missing = [w for w in all_weeks if w not in present]
    rolling = list(range(max(1, current_week - 2), current_week + 1))
    return sorted(set(missing + rolling)), False


def build_player_summaries(weekly_snaps):
    per_player = defaultdict(list)
    for week_key, records in (weekly_snaps or {}).items():
        try:
            week = int(week_key)
        except (TypeError, ValueError):
            continue
        for pid, record in (records or {}).items():
            pct = as_number(record.get("primary_snap_pct"))
            snaps = record.get("primary_snaps")
            if pct is not None:
                per_player[str(pid)].append((week, snaps, pct))

    summaries = {}
    for pid, games in per_player.items():
        games.sort(key=lambda item: item[0])
        last3 = games[-3:]
        summaries[pid] = {
            "player_id": pid,
            "latest_snap_week": games[-1][0],
            "latest_primary_snaps": games[-1][1],
            "latest_primary_snap_pct": round(games[-1][2], 6),
            "last3_primary_snap_pct": round(
                sum(item[2] for item in last3) / len(last3),
                6,
            ),
            "last3_weeks": [item[0] for item in last3],
        }
    return summaries


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def generate_snap_counts(league_data, existing=None, fetch_text=None, now_utc=None):
    now_utc = now_utc or datetime.now(timezone.utc)
    league_obj = league_data.get("league") or {}
    nfl_state = league_data.get("nfl_state") or {}
    season = str(league_obj.get("season") or nfl_state.get("season") or "")
    current_week = int(league_data.get("current_week") or nfl_state.get("week") or 1)
    refresh_weeks, full_rebuild = determine_refresh_weeks(current_week, existing)

    weekly_snaps = (
        {}
        if full_rebuild
        else copy.deepcopy((existing or {}).get("weekly_snaps") or {})
    )
    diagnostics = (
        {}
        if full_rebuild
        else copy.deepcopy((existing or {}).get("unmatched_diagnostics") or {})
    )

    fetch_ok = True
    errors = []
    snap_source_url = SNAP_SOURCE_TEMPLATE.format(season=season)
    id_source_url = PLAYER_IDS_URL

    try:
        source_rows, snap_source_url = fetch_snap_rows(
            season,
            fetch_text=fetch_text,
        )
        id_rows, id_source_url = fetch_player_id_rows(fetch_text=fetch_text)
    except Exception as exc:
        fetch_ok = False
        errors.append(str(exc))
        source_rows = []
        id_rows = []

    if fetch_ok:
        crosswalk = build_id_crosswalk(
            id_rows,
            valid_sleeper_ids=set((league_data.get("players") or {}).keys()),
        )
        name_index = build_sleeper_name_team_index(league_data)
        matched = [
            match_snap_record(row, crosswalk, name_index)
            for row in source_rows
        ]

        for week in refresh_weeks:
            source_week_rows = [
                row
                for row in matched
                if int(row.get("week") or 0) == int(week)
            ]
            if not source_week_rows:
                errors.append(
                    f"week {week}: no snap rows available; existing history preserved"
                )
                continue

            records, week_diagnostics = build_week_records(
                week,
                source_week_rows,
                league_data,
            )
            weekly_snaps[str(week)] = records
            diagnostics[str(week)] = week_diagnostics

    summaries = build_player_summaries(weekly_snaps)
    published_weeks = [
        int(w) for w, rows in weekly_snaps.items() if rows
    ]
    record_count = sum(len(rows) for rows in weekly_snaps.values())

    return {
        "schema_version": SNAP_SCHEMA_VERSION,
        "generated_at": _iso(now_utc),
        "league_id": str(
            league_data.get("league_id")
            or league_obj.get("league_id")
            or ""
        ),
        "season": season,
        "current_week": current_week,
        "snap_status": {
            "fetch_ok": fetch_ok,
            "source": "nflverse/PFR",
            "source_url": snap_source_url,
            "id_crosswalk_source_url": id_source_url,
            "weeks_refreshed": refresh_weeks,
            "published_week_count": len(published_weeks),
            "published_player_week_records": record_count,
            "fetch_errors": errors,
        },
        "weekly_snaps": weekly_snaps,
        "player_summaries": summaries,
        "unmatched_diagnostics": diagnostics,
    }

import argparse
import json
import os


def atomic_json_write(path, payload):
    temp = str(path) + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def _load_json_if_exists(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Build Goulash Kingdom nflverse/PFR snap history"
    )
    parser.add_argument("--league-json", required=True)
    parser.add_argument("--snap-json", required=True)
    args = parser.parse_args(argv)

    with open(args.league_json, "r", encoding="utf-8") as handle:
        league_data = json.load(handle)

    existing = _load_json_if_exists(args.snap_json)
    payload = generate_snap_counts(league_data, existing=existing)

    if not payload["snap_status"]["fetch_ok"]:
        if existing:
            print("Snap source fetch failed; preserving existing snap_counts.json.")
        else:
            print("Snap source fetch failed; snap_counts.json was not created.")
        return 1

    atomic_json_write(args.snap_json, payload)

    status = payload["snap_status"]
    print(
        f"Schema: {payload['schema_version']} | "
        f"Fetch: {status['fetch_ok']} | "
        f"Weeks: {status['published_week_count']} | "
        f"Records: {status['published_player_week_records']}"
    )
    return 0 if status["fetch_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

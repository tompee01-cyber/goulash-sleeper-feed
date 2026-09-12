"""Goulash Kingdom exact actual fantasy scoring helpers."""


def as_number(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def score_actual_stats(stats, scoring_settings):
    components = {}
    total = 0.0

    for key, raw_weight in scoring_settings.items():
        weight = as_number(raw_weight)
        value = as_number(stats.get(key))
        if weight is None or value is None:
            continue
        contribution = value * weight
        if contribution != 0:
            components[key] = round(contribution, 6)
        total += contribution

    return round(total, 2), components


def run_actual_self_tests():
    cases = [
        (
            {"pass_yd": 178, "pass_td": 1, "pass_int": 3, "rush_yd": 47},
            {"pass_yd": 0.04, "pass_td": 5.0, "pass_int": -2.0, "rush_yd": 0.1},
            10.82,
        ),
        (
            {"idp_tkl_solo": 6, "idp_int": 1, "idp_pass_def": 1},
            {"idp_tkl_solo": 2.0, "idp_int": 6.0, "idp_pass_def": 3.0},
            21.0,
        ),
        (
            {"kr_yd": 100, "pr_yd": 50},
            {"kr_yd": 0.04, "pr_yd": 0.04},
            6.0,
        ),
        (
            {"fgm_50_59": 1, "xpm": 2, "fgmiss": 1},
            {"fgm_50_59": 5.0, "xpm": 1.0, "fgmiss": -2.0},
            5.0,
        ),
    ]
    for stats, scoring, expected in cases:
        actual, _ = score_actual_stats(stats, scoring)
        if actual != expected:
            raise AssertionError(
                "Actual scorer self-test failed: "
                f"expected={expected}, actual={actual}, stats={stats}"
            )

import json
import urllib.request


STATS_URLS = (
    "https://api.sleeper.app/v1/stats/nfl/{season_type}/{season}/{week}",
    "https://api.sleeper.com/stats/nfl/{season}/{week}?season_type={season_type}",
)


def _get_json(url):
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/152.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=90) as response:
        return json.load(response)


def normalize_week_stats(payload):
    normalized = {}
    if isinstance(payload, dict):
        for pid, value in payload.items():
            if not isinstance(value, dict):
                continue
            nested = value.get("stats")
            stats = dict(nested) if isinstance(nested, dict) else dict(value)
            stats.pop("player_id", None)
            normalized[str(pid)] = stats
        return normalized

    if isinstance(payload, list):
        for item in payload:
            if not isinstance(item, dict):
                continue
            pid = item.get("player_id")
            if not pid:
                player = item.get("player")
                if isinstance(player, dict):
                    pid = player.get("player_id")
            if not pid:
                continue
            nested = item.get("stats")
            if isinstance(nested, dict):
                stats = dict(nested)
            else:
                stats = {
                    key: value
                    for key, value in item.items()
                    if key not in {"player_id", "player"}
                }
            normalized[str(pid)] = stats
    return normalized


def fetch_week_stats(season, week, season_type="regular", fetch_json=None):
    fetch_json = fetch_json or _get_json
    errors = []
    for template in STATS_URLS:
        url = template.format(
            season=str(season),
            week=int(week),
            season_type=str(season_type),
        )
        try:
            payload = fetch_json(url)
            return normalize_week_stats(payload), url, errors
        except Exception as exc:
            errors.append(f"{url}: {exc}")
    return {}, None, errors


def build_completed_team_games(schedule, week):
    result = {}
    for game in schedule or []:
        if int(game.get("week") or 0) != int(week):
            continue
        if game.get("status") != "complete":
            continue
        for team in (game.get("home"), game.get("away")):
            if team:
                result[str(team)] = game
    return result

import hashlib


ACTUAL_SCHEMA_VERSION = "GK_ACTUALS_V1"
ACTUAL_CALC_VERSION = "GK_ACTUAL_V1"
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DL", "LB", "DB"}


def stable_scoring_hash(scoring_settings):
    payload = json.dumps(scoring_settings, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def determine_refresh_weeks(current_week, existing, current_hash, calc_version):
    current_week = int(current_week)
    all_weeks = list(range(1, current_week + 1))
    if not existing:
        return all_weeks, True
    if existing.get("actual_calc_version") != calc_version:
        return all_weeks, True
    if existing.get("scoring_settings_hash") != current_hash:
        return all_weeks, True

    present = {
        int(w)
        for w in (existing.get("weekly_actuals") or {})
        if str(w).isdigit()
    }
    missing = [w for w in all_weeks if w not in present]
    rolling = list(range(max(1, current_week - 2), current_week + 1))
    return sorted(set(missing + rolling)), False


def _projection_snapshot(player_meta, week, existing_record=None):
    existing_record = existing_record or {}
    existing_value = existing_record.get("week_projection_gk_at_capture")
    existing_status = existing_record.get("projection_status_at_capture")
    if existing_value is not None:
        return existing_value, existing_status

    if int(player_meta.get("projection_week") or -1) == int(week):
        return (
            player_meta.get("week_projection_gk"),
            player_meta.get("week_projection_status"),
        )
    return None, None


def _is_relevant_player(player_meta):
    primary = player_meta.get("position")
    fantasy = set(player_meta.get("fantasy_positions") or [])
    return primary in FANTASY_POSITIONS or bool(fantasy & FANTASY_POSITIONS)


def build_week_records(
    *,
    season,
    week,
    league_data,
    week_stats,
    completed_team_games,
    scoring_settings,
    existing_records=None,
):
    records = {}
    existing_records = existing_records or {}
    players = league_data.get("players") or {}

    for pid, player_meta in players.items():
        pid = str(pid)
        if not _is_relevant_player(player_meta):
            continue
        team = player_meta.get("team")
        if not team or str(team) not in completed_team_games:
            continue

        game = completed_team_games[str(team)]
        stats = week_stats.get(pid)
        raw_present = isinstance(stats, dict)
        stats = dict(stats) if raw_present else {}
        gp = as_number(stats.get("gp"))
        game_played = bool(gp is not None and gp >= 1)

        if raw_present:
            total, components = score_actual_stats(stats, scoring_settings)
            quality = "Unverified"
        else:
            total, components = 0.0, {}
            quality = "Zero-NoRawStats"

        projection_value, projection_status = _projection_snapshot(
            player_meta,
            week,
            existing_records.get(pid),
        )

        records[pid] = {
            "player_id": pid,
            "season": str(season),
            "week": int(week),
            "team": str(team),
            "primary_position": player_meta.get("position"),
            "fantasy_positions": player_meta.get("fantasy_positions"),
            "game_status": "complete",
            "game_start_at": game.get("date"),
            "raw_stats_present": raw_present,
            "game_played": game_played,
            "gk_actual_points": total,
            "actual_quality": quality,
            "official_matchup_points": None,
            "audit_delta": None,
            "week_projection_gk_at_capture": projection_value,
            "projection_status_at_capture": projection_status,
            "scoring_components": components,
            "raw_stats": stats,
        }

    return records


def build_player_summaries(weekly_actuals):
    per_player = {}
    for week_key, records in (weekly_actuals or {}).items():
        try:
            week = int(week_key)
        except (TypeError, ValueError):
            continue
        for pid, record in (records or {}).items():
            points = record.get("gk_actual_points")
            include = (
                record.get("game_played") is True
                and record.get("actual_quality") != "Mismatch"
                and isinstance(points, (int, float))
                and not isinstance(points, bool)
            )
            if include:
                per_player.setdefault(str(pid), []).append((week, float(points)))

    summaries = {}
    for pid, games in per_player.items():
        games.sort(key=lambda item: item[0])
        points = [p for _, p in games]
        total = round(sum(points), 2)
        last3 = games[-3:]
        last3_points = [p for _, p in last3]
        summaries[pid] = {
            "player_id": pid,
            "season_games": len(games),
            "season_total_gk": total,
            "season_ppg": round(total / len(games), 2),
            "last3_avg_gk": round(sum(last3_points) / len(last3_points), 2),
            "last3_weeks": [w for w, _ in last3],
            "latest_final_week": games[-1][0],
            "last_game_gk": round(games[-1][1], 2),
        }
    return summaries

import argparse
import copy
import os
from datetime import datetime, timezone


BASE_URL = "https://api.sleeper.app/v1"
SCHEDULE_URL = "https://api.sleeper.app/schedule/nfl/{season_type}/{season}"


def official_points_index(matchups):
    result = {}
    for roster in matchups or []:
        for pid, points in (roster.get("players_points") or {}).items():
            value = as_number(points)
            if value is not None:
                result[str(pid)] = value
    return result


def audit_week_records(records, official_points, tolerance=0.01):
    audited = copy.deepcopy(records)
    for pid, record in audited.items():
        official = official_points.get(str(pid))
        if official is None:
            continue
        record["official_matchup_points"] = round(float(official), 2)
        if record.get("actual_quality") == "Zero-NoRawStats":
            continue
        local = as_number(record.get("gk_actual_points"))
        if local is None:
            continue
        delta = round(local - float(official), 2)
        record["audit_delta"] = delta
        record["actual_quality"] = (
            "Verified" if abs(delta) <= float(tolerance) else "Mismatch"
        )
    return audited


def atomic_json_write(path, payload):
    temp = str(path) + ".tmp"
    with open(temp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp, path)


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat()


def _load_json_if_exists(path):
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _fetch_schedule(season, season_type, fetch_json):
    url = SCHEDULE_URL.format(season_type=season_type, season=season)
    return fetch_json(url), url


def _fetch_matchups(league_id, week, fetch_json):
    url = f"{BASE_URL}/league/{league_id}/matchups/{int(week)}"
    return fetch_json(url), url


def _status_counts(weekly_actuals):
    verified = 0
    mismatch = 0
    record_count = 0
    nonempty_weeks = []
    for week, records in (weekly_actuals or {}).items():
        if records:
            nonempty_weeks.append(int(week))
        for record in (records or {}).values():
            record_count += 1
            if record.get("actual_quality") == "Verified":
                verified += 1
            elif record.get("actual_quality") == "Mismatch":
                mismatch += 1
    return verified, mismatch, record_count, nonempty_weeks


def generate_actuals(league_data, existing=None, fetch_json=None, now_utc=None):
    run_actual_self_tests()
    fetch_json = fetch_json or _get_json
    now_utc = now_utc or datetime.now(timezone.utc)

    league_obj = league_data.get("league") or {}
    nfl_state = league_data.get("nfl_state") or {}
    league_id = str(league_data.get("league_id") or league_obj.get("league_id") or "")
    season = str(league_obj.get("season") or nfl_state.get("season") or "")
    current_week = int(league_data.get("current_week") or nfl_state.get("week") or 1)
    season_type = str(nfl_state.get("season_type") or league_obj.get("season_type") or "regular")
    if season_type not in {"regular", "pre", "post"}:
        season_type = "regular"
    scoring_settings = league_obj.get("scoring_settings") or {}
    scoring_hash = stable_scoring_hash(scoring_settings)

    refresh_weeks, full_rebuild = determine_refresh_weeks(
        current_week,
        existing,
        scoring_hash,
        ACTUAL_CALC_VERSION,
    )

    if full_rebuild:
        weekly_actuals = {}
    else:
        weekly_actuals = copy.deepcopy((existing or {}).get("weekly_actuals") or {})

    fetch_ok = True
    fetch_errors = []
    schedule = None
    try:
        schedule, _ = _fetch_schedule(season, season_type, fetch_json)
        if not isinstance(schedule, list):
            raise ValueError("Sleeper schedule payload is not a list")
    except Exception as exc:
        fetch_ok = False
        fetch_errors.append(f"schedule: {exc}")

    if schedule is not None:
        for week in refresh_weeks:
            completed_games = build_completed_team_games(schedule, week)
            try:
                week_stats, source_url, stat_errors = fetch_week_stats(
                    season=season,
                    week=week,
                    season_type=season_type,
                    fetch_json=fetch_json,
                )
            except Exception as exc:
                week_stats, source_url, stat_errors = {}, None, [str(exc)]

            if source_url is None:
                fetch_ok = False
                fetch_errors.extend(f"week {week} stats: {err}" for err in stat_errors)
                continue
            if stat_errors:
                fetch_errors.extend(f"week {week} stats fallback: {err}" for err in stat_errors)

            existing_records = (weekly_actuals.get(str(week)) or {})
            records = build_week_records(
                season=season,
                week=week,
                league_data=league_data,
                week_stats=week_stats,
                completed_team_games=completed_games,
                scoring_settings=scoring_settings,
                existing_records=existing_records,
            )

            matchups = None
            try:
                if week == current_week and isinstance(league_data.get("matchups"), list):
                    matchups = league_data.get("matchups")
                else:
                    matchups, _ = _fetch_matchups(league_id, week, fetch_json)
                if not isinstance(matchups, list):
                    raise ValueError("Sleeper matchup payload is not a list")
            except Exception as exc:
                fetch_ok = False
                fetch_errors.append(f"week {week} matchup audit: {exc}")
                matchups = []

            records = audit_week_records(records, official_points_index(matchups))
            weekly_actuals[str(week)] = records

    player_summaries = build_player_summaries(weekly_actuals)
    verified_count, mismatch_count, record_count, nonempty_weeks = _status_counts(weekly_actuals)
    latest_final_week = max(nonempty_weeks) if nonempty_weeks else None

    return {
        "schema_version": ACTUAL_SCHEMA_VERSION,
        "actual_calc_version": ACTUAL_CALC_VERSION,
        "generated_at": _iso(now_utc),
        "league_id": league_id,
        "season": season,
        "scoring_settings_hash": scoring_hash,
        "correction_window": {
            "current_week": current_week,
            "weeks_refreshed": refresh_weeks,
        },
        "actual_status": {
            "fetch_ok": fetch_ok,
            "source": "Sleeper",
            "latest_final_week": latest_final_week,
            "published_week_count": len(nonempty_weeks),
            "published_player_week_records": record_count,
            "verified_record_count": verified_count,
            "mismatch_record_count": mismatch_count,
            "fetch_errors": fetch_errors,
        },
        "weekly_actuals": weekly_actuals,
        "player_summaries": player_summaries,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build Goulash Kingdom Sleeper actuals history")
    parser.add_argument("--league-json", required=True)
    parser.add_argument("--actuals-json", required=True)
    args = parser.parse_args(argv)

    with open(args.league_json, "r", encoding="utf-8") as handle:
        league_data = json.load(handle)
    existing = _load_json_if_exists(args.actuals_json)

    payload = generate_actuals(league_data, existing=existing)
    atomic_json_write(args.actuals_json, payload)
    status = payload["actual_status"]
    print(
        f"Schema: {payload['schema_version']} | "
        f"Actual: {payload['actual_calc_version']} | "
        f"Fetch: {status['fetch_ok']} | "
        f"Latest final week: {status['latest_final_week']} | "
        f"Records: {status['published_player_week_records']} | "
        f"Verified: {status['verified_record_count']} | "
        f"Mismatch: {status['mismatch_record_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

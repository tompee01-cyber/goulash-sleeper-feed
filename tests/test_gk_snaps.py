import unittest

from scripts.gk_snaps import (
    normalize_name,
    normalize_pct,
    normalize_snap_row,
    normalize_team,
)


class SnapNormalizationTests(unittest.TestCase):
    def test_percent_normalizes_integer_percent_to_decimal(self):
        self.assertEqual(normalize_pct("86"), 0.86)
        self.assertEqual(normalize_pct("100"), 1.0)

    def test_percent_preserves_decimal_fraction(self):
        self.assertEqual(normalize_pct("0.8625"), 0.8625)

    def test_percent_blank_stays_none(self):
        self.assertIsNone(normalize_pct(""))
        self.assertIsNone(normalize_pct("NA"))
        self.assertIsNone(normalize_pct(None))

    def test_team_aliases_are_normalized(self):
        self.assertEqual(normalize_team("KCC"), "KC")
        self.assertEqual(normalize_team("LVR"), "LV")
        self.assertEqual(normalize_team("SFO"), "SF")
        self.assertEqual(normalize_team("TBB"), "TB")
        self.assertEqual(normalize_team("GNB"), "GB")
        self.assertEqual(normalize_team("GBP"), "GB")

    def test_name_normalization_handles_punctuation_suffixes(self):
        self.assertEqual(normalize_name("D.J. Moore Jr."), "dj moore")
        self.assertEqual(normalize_name("Amon-Ra St. Brown"), "amon ra st brown")

    def test_snap_row_uses_nflverse_columns(self):
        row = {
            "game_id": "2026_02_KC_MIA",
            "season": "2026",
            "game_type": "REG",
            "week": "2",
            "player": "Xavier Worthy",
            "pfr_player_id": "WortXa00",
            "position": "WR",
            "team": "KCC",
            "opponent": "MIA",
            "offense_snaps": "69",
            "offense_pct": "86",
            "defense_snaps": "0",
            "defense_pct": "0",
            "st_snaps": "0",
            "st_pct": "0",
        }
        record = normalize_snap_row(row)
        self.assertEqual(record["week"], 2)
        self.assertEqual(record["team"], "KC")
        self.assertEqual(record["off_snaps"], 69)
        self.assertEqual(record["off_snap_pct"], 0.86)


if __name__ == "__main__":
    unittest.main()

from scripts.gk_snaps import fetch_player_id_rows, fetch_snap_rows


class SnapFetchTests(unittest.TestCase):
    def test_fetch_snap_rows_reads_csv(self):
        csv_text = (
            "season,week,player,pfr_player_id,position,team,opponent,"
            "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n"
            "2026,2,Xavier Worthy,WortXa00,WR,KCC,MIA,69,86,0,0,0,0\n"
        )
        seen = []

        def fake_fetch(url):
            seen.append(url)
            return csv_text

        rows, source = fetch_snap_rows("2026", fetch_text=fake_fetch)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["team"], "KC")
        self.assertIn("snap_counts_2026.csv", source)
        self.assertEqual(len(seen), 1)

    def test_fetch_player_ids_reads_pfr_and_sleeper_columns(self):
        csv_text = (
            "sleeper_id,pfr_id,name,team\n"
            "13269,MendFe00,Fernando Mendoza,LVR\n"
        )
        rows, source = fetch_player_id_rows(fetch_text=lambda _: csv_text)
        self.assertEqual(rows[0]["sleeper_id"], "13269")
        self.assertEqual(rows[0]["pfr_id"], "MendFe00")
        self.assertIn("db_playerids.csv", source)

from scripts.gk_snaps import (
    build_id_crosswalk,
    build_sleeper_name_team_index,
    match_snap_record,
)


class SnapMatchingTests(unittest.TestCase):
    def _league(self):
        return {
            "players": {
                "13269": {
                    "player_id": "13269",
                    "full_name": "Fernando Mendoza",
                    "team": "LV",
                    "position": "QB",
                    "fantasy_positions": ["QB"],
                },
                "999": {
                    "player_id": "999",
                    "full_name": "Malaki Starks",
                    "team": "BAL",
                    "position": "S",
                    "fantasy_positions": ["DB"],
                },
            }
        }

    def test_pfr_id_maps_directly_to_sleeper_id(self):
        crosswalk = build_id_crosswalk([
            {"pfr_id": "MendFe00", "sleeper_id": "13269"}
        ])
        rec = {
            "pfr_player_id": "MendFe00",
            "normalized_name": "fernando mendoza",
            "team": "LV",
            "full_name": "Fernando Mendoza",
        }
        matched = match_snap_record(
            rec,
            crosswalk,
            build_sleeper_name_team_index(self._league()),
        )
        self.assertEqual(matched["player_id"], "13269")
        self.assertEqual(matched["match_quality"], "Exact")

    def test_missing_crosswalk_uses_name_team_fallback(self):
        rec = {
            "pfr_player_id": "StarMa00",
            "normalized_name": "malaki starks",
            "team": "BAL",
            "full_name": "Malaki Starks",
        }
        matched = match_snap_record(
            rec,
            {},
            build_sleeper_name_team_index(self._league()),
        )
        self.assertEqual(matched["player_id"], "999")
        self.assertEqual(matched["match_quality"], "NameTeam")

    def test_name_team_fallback_normalizes_team_alias(self):
        league = self._league()
        league["players"]["777"] = {
            "player_id": "777",
            "full_name": "Alias Team Guy",
            "team": "KC",
            "position": "WR",
            "fantasy_positions": ["WR"],
        }
        rec = {
            "pfr_player_id": None,
            "normalized_name": "alias team guy",
            "team": "KCC",
            "full_name": "Alias Team Guy",
        }
        matched = match_snap_record(
            rec,
            {},
            build_sleeper_name_team_index(league),
        )
        self.assertEqual(matched["player_id"], "777")
        self.assertEqual(matched["match_quality"], "NameTeam")

    def test_explicit_alias_is_used_before_name_fallback(self):
        rec = {
            "pfr_player_id": "Alias01",
            "normalized_name": "different name",
            "team": "BAL",
            "full_name": "Different Name",
        }
        matched = match_snap_record(
            rec,
            {},
            build_sleeper_name_team_index(self._league()),
            aliases={"Alias01": "999"},
        )
        self.assertEqual(matched["player_id"], "999")
        self.assertEqual(matched["match_quality"], "Alias")

    def test_ambiguous_name_team_does_not_assign_player(self):
        league = self._league()
        league["players"]["998"] = {
            "player_id": "998",
            "full_name": "Malaki Starks",
            "team": "BAL",
            "position": "S",
            "fantasy_positions": ["DB"],
        }
        rec = {
            "pfr_player_id": None,
            "normalized_name": "malaki starks",
            "team": "BAL",
            "full_name": "Malaki Starks",
        }
        matched = match_snap_record(
            rec,
            {},
            build_sleeper_name_team_index(league),
        )
        self.assertIsNone(matched["player_id"])
        self.assertEqual(matched["match_quality"], "Ambiguous")

    def test_unmatched_name_team_stays_unmatched(self):
        rec = {
            "pfr_player_id": None,
            "normalized_name": "unknown player",
            "team": "BAL",
            "full_name": "Unknown Player",
        }
        matched = match_snap_record(
            rec,
            {},
            build_sleeper_name_team_index(self._league()),
        )
        self.assertIsNone(matched["player_id"])
        self.assertEqual(matched["match_quality"], "Unmatched")

from scripts.gk_snaps import build_week_records, primary_unit_for


class SnapWeekRecordTests(unittest.TestCase):
    def test_primary_unit_uses_fantasy_role(self):
        self.assertEqual(
            primary_unit_for({"position": "WR", "fantasy_positions": ["WR"]}),
            "OFF",
        )
        self.assertEqual(
            primary_unit_for({"position": "OLB", "fantasy_positions": ["DL", "LB"]}),
            "DEF",
        )
        self.assertEqual(
            primary_unit_for({"position": "K", "fantasy_positions": ["K"]}),
            "ST",
        )

    def test_week_record_copies_primary_snap_fields(self):
        league = {
            "players": {
                "1": {
                    "full_name": "Xavier Worthy",
                    "team": "KC",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                }
            }
        }
        rows = [{
            "player_id": "1",
            "match_quality": "Exact",
            "season": 2026,
            "week": 2,
            "team": "KC",
            "full_name": "Xavier Worthy",
            "pfr_player_id": "WortXa00",
            "off_snaps": 69,
            "off_snap_pct": 0.86,
            "def_snaps": 0,
            "def_snap_pct": 0.0,
            "st_snaps": 0,
            "st_snap_pct": 0.0,
        }]
        records, diagnostics = build_week_records(2, rows, league)
        self.assertEqual(records["1"]["primary_unit"], "OFF")
        self.assertEqual(records["1"]["primary_snaps"], 69)
        self.assertEqual(records["1"]["primary_snap_pct"], 0.86)
        self.assertEqual(records["1"]["source"], "nflverse/PFR")
        self.assertEqual(diagnostics, [])

    def test_unmatched_record_is_kept_only_in_diagnostics(self):
        records, diagnostics = build_week_records(
            2,
            [{
                "player_id": None,
                "match_quality": "Unmatched",
                "week": 2,
                "team": "KC",
                "full_name": "Unknown Player",
                "pfr_player_id": "UnknPl00",
            }],
            {"players": {}},
        )
        self.assertEqual(records, {})
        self.assertEqual(diagnostics[0]["match_quality"], "Unmatched")

    def test_matched_id_not_present_in_league_index_is_diagnostic_only(self):
        records, diagnostics = build_week_records(
            2,
            [{
                "player_id": "9999",
                "match_quality": "Exact",
                "week": 2,
                "team": "KC",
                "full_name": "Offensive Lineman",
                "pfr_player_id": "LineOf00",
                "off_snaps": 60,
                "off_snap_pct": 1.0,
            }],
            {"players": {}},
        )
        self.assertEqual(records, {})
        self.assertEqual(diagnostics[0]["diagnostic_reason"], "PlayerNotInLeagueIndex")

from scripts.gk_snaps import (
    SNAP_SCHEMA_VERSION,
    build_player_summaries,
    determine_refresh_weeks,
    generate_snap_counts,
)


class SnapRefreshTests(unittest.TestCase):
    def test_normal_refresh_is_current_and_previous_two(self):
        existing = {
            "schema_version": SNAP_SCHEMA_VERSION,
            "weekly_snaps": {str(w): {} for w in range(1, 8)},
        }
        weeks, full = determine_refresh_weeks(7, existing)
        self.assertFalse(full)
        self.assertEqual(weeks, [5, 6, 7])

    def test_missing_historical_week_is_backfilled(self):
        existing = {
            "schema_version": SNAP_SCHEMA_VERSION,
            "weekly_snaps": {"1": {}, "2": {}, "4": {}, "5": {}},
        }
        weeks, full = determine_refresh_weeks(5, existing)
        self.assertFalse(full)
        self.assertEqual(weeks, [3, 4, 5])

    def test_schema_change_forces_full_rebuild(self):
        existing = {"schema_version": "OLD", "weekly_snaps": {"1": {}}}
        weeks, full = determine_refresh_weeks(3, existing)
        self.assertTrue(full)
        self.assertEqual(weeks, [1, 2, 3])

    def test_summary_uses_latest_three_valid_snap_weeks(self):
        weekly = {
            "1": {"p1": {"primary_snaps": 50, "primary_snap_pct": 0.50}},
            "2": {"p1": {"primary_snaps": 70, "primary_snap_pct": 0.70}},
            "3": {},
            "4": {"p1": {"primary_snaps": 90, "primary_snap_pct": 0.90}},
        }
        summary = build_player_summaries(weekly)["p1"]
        self.assertEqual(summary["latest_snap_week"], 4)
        self.assertEqual(summary["latest_primary_snaps"], 90)
        self.assertEqual(summary["latest_primary_snap_pct"], 0.90)
        self.assertEqual(summary["last3_primary_snap_pct"], 0.70)
        self.assertEqual(summary["last3_weeks"], [1, 2, 4])

    def test_summary_ignores_record_with_missing_primary_pct(self):
        weekly = {
            "1": {"p1": {"primary_snaps": None, "primary_snap_pct": None}},
        }
        self.assertNotIn("p1", build_player_summaries(weekly))


class SnapGenerationTests(unittest.TestCase):
    def _league(self):
        return {
            "league_id": "L1",
            "current_week": 2,
            "nfl_state": {"season": "2026"},
            "league": {"season": "2026"},
            "players": {
                "1": {
                    "player_id": "1",
                    "full_name": "Xavier Worthy",
                    "team": "KC",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                }
            },
        }

    def test_source_failure_preserves_existing_history(self):
        existing = {
            "schema_version": SNAP_SCHEMA_VERSION,
            "weekly_snaps": {
                "1": {
                    "1": {
                        "player_id": "1",
                        "primary_snaps": 60,
                        "primary_snap_pct": 0.75,
                    }
                }
            },
        }

        def failing_fetch(url):
            raise OSError("source unavailable")

        data = generate_snap_counts(
            self._league(),
            existing=existing,
            fetch_text=failing_fetch,
        )
        self.assertFalse(data["snap_status"]["fetch_ok"])
        self.assertEqual(
            data["weekly_snaps"]["1"]["1"]["primary_snap_pct"],
            0.75,
        )

    def test_missing_refresh_week_preserves_existing_week(self):
        existing = {
            "schema_version": SNAP_SCHEMA_VERSION,
            "weekly_snaps": {
                "2": {
                    "1": {
                        "player_id": "1",
                        "primary_snaps": 60,
                        "primary_snap_pct": 0.75,
                    }
                }
            },
        }
        snap_csv = (
            "season,week,player,pfr_player_id,position,team,opponent,"
            "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n"
            "2026,1,Xavier Worthy,WortXa00,WR,KC,MIA,50,70,0,0,0,0\n"
        )
        ids_csv = "sleeper_id,pfr_id,name,team\n1,WortXa00,Xavier Worthy,KCC\n"

        def fake_fetch(url):
            return ids_csv if "db_playerids.csv" in url else snap_csv

        data = generate_snap_counts(
            self._league(),
            existing=existing,
            fetch_text=fake_fetch,
        )
        self.assertTrue(data["snap_status"]["fetch_ok"])
        self.assertEqual(data["weekly_snaps"]["2"]["1"]["primary_snap_pct"], 0.75)
        self.assertTrue(any("week 2" in err for err in data["snap_status"]["fetch_errors"]))

import json
import os
import tempfile

from scripts.gk_snaps import atomic_json_write


class SnapWriteTests(unittest.TestCase):
    def test_atomic_json_write_replaces_target_without_temp_leftover(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "snap_counts.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"old": True}, handle)

            atomic_json_write(path, {"new": True})

            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"new": True})
            self.assertFalse(os.path.exists(path + ".tmp"))


class GKWeek2RegressionTests(unittest.TestCase):
    def test_known_gk_players_match_and_preserve_source_snap_fields(self):
        league = {
            "players": {
                "12567": {"full_name": "Malaki Starks", "team": "BAL", "position": "DB", "fantasy_positions": ["DB"]},
                "12588": {"full_name": "Kevin Winston", "team": "TEN", "position": "DB", "fantasy_positions": ["DB"]},
                "12622": {"full_name": "Nohl Williams", "team": "KC", "position": "CB", "fantasy_positions": ["DB"]},
                "11624": {"full_name": "Xavier Worthy", "team": "KC", "position": "WR", "fantasy_positions": ["WR"]},
                "8134": {"full_name": "Khalil Shakir", "team": "BUF", "position": "WR", "fantasy_positions": ["WR"]},
                "10940": {"full_name": "Nick Herbig", "team": "PIT", "position": "LB", "fantasy_positions": ["DL", "LB"]},
            }
        }
        id_rows = [
            {"pfr_id": "StarMa00", "sleeper_id": "12567"},
            {"pfr_id": "WinsKe02", "sleeper_id": "12588"},
            {"pfr_id": "WillNo01", "sleeper_id": "12622"},
            {"pfr_id": "WortXa00", "sleeper_id": "11624"},
            {"pfr_id": "ShakKh00", "sleeper_id": "8134"},
            {"pfr_id": "HerbNi00", "sleeper_id": "10940"},
        ]
        raw_rows = [
            {"season": "2026", "week": "2", "player": "Malaki Starks", "pfr_player_id": "StarMa00", "position": "S", "team": "BAL", "opponent": "NO", "offense_snaps": "0", "offense_pct": "0", "defense_snaps": "54", "defense_pct": "100", "st_snaps": "12", "st_pct": "40"},
            {"season": "2026", "week": "2", "player": "Kevin Winston", "pfr_player_id": "WinsKe02", "position": "S", "team": "TEN", "opponent": "PHI", "offense_snaps": "0", "offense_pct": "0", "defense_snaps": "76", "defense_pct": "100", "st_snaps": "0", "st_pct": "0"},
            {"season": "2026", "week": "2", "player": "Nohl Williams", "pfr_player_id": "WillNo01", "position": "CB", "team": "KCC", "opponent": "IND", "offense_snaps": "0", "offense_pct": "0", "defense_snaps": "65", "defense_pct": "100", "st_snaps": "15", "st_pct": "52"},
            {"season": "2026", "week": "2", "player": "Xavier Worthy", "pfr_player_id": "WortXa00", "position": "WR", "team": "KCC", "opponent": "IND", "offense_snaps": "69", "offense_pct": "86", "defense_snaps": "0", "defense_pct": "0", "st_snaps": "0", "st_pct": "0"},
            {"season": "2026", "week": "2", "player": "Khalil Shakir", "pfr_player_id": "ShakKh00", "position": "WR", "team": "BUF", "opponent": "DET", "offense_snaps": "36", "offense_pct": "49", "defense_snaps": "0", "defense_pct": "0", "st_snaps": "1", "st_pct": "3"},
            {"season": "2026", "week": "2", "player": "Nick Herbig", "pfr_player_id": "HerbNi00", "position": "DE", "team": "PIT", "opponent": "NE", "offense_snaps": "0", "offense_pct": "0", "defense_snaps": "29", "defense_pct": "53", "st_snaps": "13", "st_pct": "45"},
        ]

        normalized = [normalize_snap_row(row) for row in raw_rows]
        crosswalk = build_id_crosswalk(id_rows)
        name_index = build_sleeper_name_team_index(league)
        matched = [match_snap_record(row, crosswalk, name_index) for row in normalized]
        records, diagnostics = build_week_records(2, matched, league)

        self.assertEqual(diagnostics, [])
        self.assertEqual(records["12567"]["primary_unit"], "DEF")
        self.assertEqual(records["12588"]["primary_unit"], "DEF")
        self.assertEqual(records["12622"]["primary_unit"], "DEF")
        self.assertEqual(records["11624"]["primary_unit"], "OFF")
        self.assertEqual(records["8134"]["primary_unit"], "OFF")
        self.assertEqual(records["10940"]["primary_unit"], "DEF")
        self.assertEqual(records["11624"]["primary_snaps"], 69)
        self.assertEqual(records["8134"]["primary_snaps"], 36)
        self.assertEqual(records["10940"]["primary_snaps"], 29)

from pathlib import Path


class WorkflowIntegrationTests(unittest.TestCase):
    def test_workflow_runs_and_publishes_snap_feed(self):
        workflow = Path(".github/workflows/update-league.yml").read_text(encoding="utf-8")
        self.assertIn("python -m unittest tests.test_gk_actuals tests.test_gk_snaps -v", workflow)
        self.assertIn("- name: Build nflverse snap history", workflow)
        self.assertIn("id: snaps", workflow)
        self.assertIn("--snap-json snap_counts.json", workflow)
        self.assertIn("git add snap_counts.json", workflow)
        self.assertIn("GK_SNAPS_V1", workflow)
        self.assertIn("if: steps.snaps.outcome == 'failure'", workflow)
        self.assertIn("runs-on: ubuntu-24.04", workflow)
        self.assertIn("uses: actions/checkout@v5", workflow)

from unittest.mock import patch
from scripts.gk_snaps import main as snap_main


class SnapCliTests(unittest.TestCase):
    def test_cli_initial_source_failure_does_not_create_snap_file(self):
        with tempfile.TemporaryDirectory() as td:
            league_path = os.path.join(td, "league.json")
            snap_path = os.path.join(td, "snap_counts.json")
            league = {
                "league_id": "L1",
                "current_week": 2,
                "nfl_state": {"season": "2026"},
                "league": {"season": "2026"},
                "players": {},
            }
            with open(league_path, "w", encoding="utf-8") as handle:
                json.dump(league, handle)

            with patch("scripts.gk_snaps._fetch_text", side_effect=OSError("offline")):
                rc = snap_main([
                    "--league-json", league_path,
                    "--snap-json", snap_path,
                ])

            self.assertEqual(rc, 1)
            self.assertFalse(os.path.exists(snap_path))

    def test_cli_source_failure_preserves_existing_file_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            league_path = os.path.join(td, "league.json")
            snap_path = os.path.join(td, "snap_counts.json")
            league = {
                "league_id": "L1",
                "current_week": 2,
                "nfl_state": {"season": "2026"},
                "league": {"season": "2026"},
                "players": {},
            }
            with open(league_path, "w", encoding="utf-8") as handle:
                json.dump(league, handle)
            original = b'{"schema_version":"GK_SNAPS_V1","weekly_snaps":{"1":{}}}\n'
            with open(snap_path, "wb") as handle:
                handle.write(original)

            with patch("scripts.gk_snaps._fetch_text", side_effect=OSError("offline")):
                rc = snap_main([
                    "--league-json", league_path,
                    "--snap-json", snap_path,
                ])

            self.assertEqual(rc, 1)
            with open(snap_path, "rb") as handle:
                self.assertEqual(handle.read(), original)


class CrosswalkValidityTests(unittest.TestCase):
    def test_invalid_direct_sleeper_id_is_omitted_so_name_team_can_fallback(self):
        league = {
            "players": {
                "1": {
                    "player_id": "1",
                    "full_name": "Rookie Example",
                    "team": "KC",
                    "position": "WR",
                    "fantasy_positions": ["WR"],
                }
            }
        }
        crosswalk = build_id_crosswalk(
            [{"pfr_id": "RookEx00", "sleeper_id": "stale-id"}],
            valid_sleeper_ids=set(league["players"]),
        )
        rec = {
            "pfr_player_id": "RookEx00",
            "normalized_name": "rookie example",
            "team": "KC",
            "full_name": "Rookie Example",
        }
        matched = match_snap_record(
            rec,
            crosswalk,
            build_sleeper_name_team_index(league),
        )
        self.assertEqual(matched["player_id"], "1")
        self.assertEqual(matched["match_quality"], "NameTeam")

from scripts.gk_snaps import attach_team_denominators


class TeamSnapDenominatorTests(unittest.TestCase):
    def test_team_denominators_are_inferred_from_snap_count_and_share(self):
        rows = [
            {"season": 2026, "week": 2, "game_id": "g1", "team": "KC", "opponent": "IND", "off_snaps": 80, "off_snap_pct": 1.0, "def_snaps": 0, "def_snap_pct": 0.0, "st_snaps": 0, "st_snap_pct": 0.0},
            {"season": 2026, "week": 2, "game_id": "g1", "team": "KC", "opponent": "IND", "off_snaps": 69, "off_snap_pct": 0.86, "def_snaps": 65, "def_snap_pct": 1.0, "st_snaps": 15, "st_snap_pct": 0.52},
            {"season": 2026, "week": 2, "game_id": "g1", "team": "KC", "opponent": "IND", "off_snaps": 40, "off_snap_pct": 0.50, "def_snaps": 52, "def_snap_pct": 0.80, "st_snaps": 29, "st_snap_pct": 1.0},
        ]
        enriched = attach_team_denominators(rows)
        for row in enriched:
            self.assertEqual(row["team_off_snaps"], 80)
            self.assertEqual(row["team_def_snaps"], 65)
            self.assertEqual(row["team_st_snaps"], 29)

    def test_missing_share_leaves_denominator_none(self):
        rows = [{"season": 2026, "week": 2, "game_id": "g1", "team": "KC", "opponent": "IND", "off_snaps": 5, "off_snap_pct": None, "def_snaps": 0, "def_snap_pct": None, "st_snaps": 0, "st_snap_pct": None}]
        enriched = attach_team_denominators(rows)
        self.assertIsNone(enriched[0]["team_off_snaps"])
        self.assertIsNone(enriched[0]["team_def_snaps"])
        self.assertIsNone(enriched[0]["team_st_snaps"])


class RegularSeasonFilterTests(unittest.TestCase):
    def test_postseason_snap_rows_are_not_published_in_regular_season_feed(self):
        csv_text = (
            "game_id,season,game_type,week,player,pfr_player_id,position,team,opponent,"
            "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n"
            "reg,2026,REG,1,Xavier Worthy,WortXa00,WR,KC,DEN,60,0.75,0,0,0,0\n"
            "post,2026,POST,1,Xavier Worthy,WortXa00,WR,KC,DEN,80,1.0,0,0,0,0\n"
        )
        rows, _ = fetch_snap_rows("2026", fetch_text=lambda _: csv_text)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["game_id"], "reg")
        self.assertEqual(rows[0]["game_type"], "REG")

class EmptySourceSafetyTests(unittest.TestCase):
    def test_empty_snap_source_is_fetch_failure_and_preserves_history(self):
        league = {
            "league_id": "L1",
            "current_week": 2,
            "nfl_state": {"season": "2026"},
            "league": {"season": "2026"},
            "players": {},
        }
        existing = {
            "schema_version": SNAP_SCHEMA_VERSION,
            "weekly_snaps": {
                "1": {"p1": {"player_id": "p1", "primary_snap_pct": 0.9}}
            },
        }
        snap_csv = (
            "game_id,season,game_type,week,player,pfr_player_id,position,team,opponent,"
            "offense_snaps,offense_pct,defense_snaps,defense_pct,st_snaps,st_pct\n"
        )
        ids_csv = "sleeper_id,pfr_id,name,team\n"

        def fake_fetch(url):
            return ids_csv if "db_playerids.csv" in url else snap_csv

        data = generate_snap_counts(
            league,
            existing=existing,
            fetch_text=fake_fetch,
        )
        self.assertFalse(data["snap_status"]["fetch_ok"])
        self.assertEqual(
            data["weekly_snaps"]["1"]["p1"]["primary_snap_pct"],
            0.9,
        )

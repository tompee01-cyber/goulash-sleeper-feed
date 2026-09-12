import unittest

from scripts.gk_actuals import score_actual_stats


class ScoreActualStatsTests(unittest.TestCase):
    def test_drake_maye_week1_control_math(self):
        scoring = {
            "pass_yd": 0.04,
            "pass_td": 5.0,
            "pass_int": -2.0,
            "rush_yd": 0.1,
        }
        stats = {
            "pass_yd": 178,
            "pass_td": 1,
            "pass_int": 3,
            "rush_yd": 47,
            "gp": 1,
        }
        total, components = score_actual_stats(stats, scoring)
        self.assertEqual(total, 10.82)
        self.assertEqual(components["pass_yd"], 7.12)
        self.assertEqual(components["pass_td"], 5.0)
        self.assertEqual(components["pass_int"], -6.0)
        self.assertEqual(components["rush_yd"], 4.7)

    def test_idp_six_solo_int_pd_is_21(self):
        scoring = {
            "idp_tkl_solo": 2.0,
            "idp_int": 6.0,
            "idp_pass_def": 3.0,
        }
        stats = {
            "idp_tkl_solo": 6,
            "idp_int": 1,
            "idp_pass_def": 1,
            "gp": 1,
        }
        total, _ = score_actual_stats(stats, scoring)
        self.assertEqual(total, 21.0)

    def test_return_yards_use_gk_weights(self):
        scoring = {"kr_yd": 0.04, "pr_yd": 0.04}
        stats = {"kr_yd": 100, "pr_yd": 50, "gp": 1}
        total, _ = score_actual_stats(stats, scoring)
        self.assertEqual(total, 6.0)

    def test_kicker_distance_bands_are_exact(self):
        scoring = {
            "fgm_50_59": 5.0,
            "xpm": 1.0,
            "fgmiss": -2.0,
        }
        stats = {"fgm_50_59": 1, "xpm": 2, "fgmiss": 1, "gp": 1}
        total, _ = score_actual_stats(stats, scoring)
        self.assertEqual(total, 5.0)


if __name__ == "__main__":
    unittest.main()

from scripts.gk_actuals import build_completed_team_games, normalize_week_stats


class WeeklyStatsInputTests(unittest.TestCase):
    def test_normalize_dict_payload_keyed_by_player_id(self):
        payload = {
            "11564": {"pass_yd": 178, "gp": 1},
            "TEAM_NE": {"sack": 4},
        }
        normalized = normalize_week_stats(payload)
        self.assertEqual(normalized["11564"]["pass_yd"], 178)
        self.assertEqual(normalized["TEAM_NE"]["sack"], 4)

    def test_normalize_list_payload_uses_player_id(self):
        payload = [
            {"player_id": "11564", "stats": {"pass_yd": 178, "gp": 1}},
            {"player_id": "11470", "idp_tkl_solo": 8, "gp": 1},
        ]
        normalized = normalize_week_stats(payload)
        self.assertEqual(normalized["11564"]["pass_yd"], 178)
        self.assertEqual(normalized["11470"]["idp_tkl_solo"], 8)

    def test_only_complete_games_are_returned(self):
        schedule = [
            {"week": 1, "home": "SEA", "away": "NE", "status": "complete", "date": "2026-09-09T20:20:00-07:00"},
            {"week": 1, "home": "DAL", "away": "PHI", "status": "pre_game", "date": "2026-09-10T20:20:00-04:00"},
            {"week": 1, "home": "GB", "away": "CHI", "status": "in_game", "date": "2026-09-10T20:20:00-05:00"},
        ]
        completed = build_completed_team_games(schedule, 1)
        self.assertEqual(set(completed), {"SEA", "NE"})

from scripts.gk_actuals import fetch_week_stats


class FetchWeekStatsTests(unittest.TestCase):
    def test_falls_back_to_second_endpoint_and_returns_errors(self):
        seen = []

        def fake_fetch(url):
            seen.append(url)
            if "api.sleeper.app" in url:
                raise OSError("first endpoint unavailable")
            return {"11564": {"pass_yd": 178, "gp": 1}}

        stats, source_url, errors = fetch_week_stats(
            season="2026",
            week=1,
            season_type="regular",
            fetch_json=fake_fetch,
        )
        self.assertEqual(stats["11564"]["pass_yd"], 178)
        self.assertIn("api.sleeper.com", source_url)
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(seen), 2)

from scripts.gk_actuals import (
    build_player_summaries,
    build_week_records,
    determine_refresh_weeks,
    stable_scoring_hash,
)


class RefreshWindowTests(unittest.TestCase):
    def test_normal_run_refreshes_current_and_previous_two(self):
        existing = {
            "schema_version": "GK_ACTUALS_V1",
            "actual_calc_version": "GK_ACTUAL_V1",
            "scoring_settings_hash": "same",
            "weekly_actuals": {str(w): {} for w in range(1, 8)},
        }
        weeks, full_rebuild = determine_refresh_weeks(7, existing, "same", "GK_ACTUAL_V1")
        self.assertFalse(full_rebuild)
        self.assertEqual(weeks, [5, 6, 7])

    def test_missing_historical_week_is_backfilled(self):
        existing = {
            "schema_version": "GK_ACTUALS_V1",
            "actual_calc_version": "GK_ACTUAL_V1",
            "scoring_settings_hash": "same",
            "weekly_actuals": {"1": {}, "2": {}, "4": {}, "5": {}},
        }
        weeks, full_rebuild = determine_refresh_weeks(5, existing, "same", "GK_ACTUAL_V1")
        self.assertFalse(full_rebuild)
        self.assertEqual(weeks, [3, 4, 5])

    def test_scoring_hash_change_forces_full_rebuild(self):
        existing = {
            "actual_calc_version": "GK_ACTUAL_V1",
            "scoring_settings_hash": "old",
            "weekly_actuals": {"1": {}, "2": {}},
        }
        weeks, full_rebuild = determine_refresh_weeks(5, existing, "new", "GK_ACTUAL_V1")
        self.assertTrue(full_rebuild)
        self.assertEqual(weeks, [1, 2, 3, 4, 5])

    def test_scoring_hash_is_order_independent(self):
        self.assertEqual(
            stable_scoring_hash({"a": 1, "b": 2}),
            stable_scoring_hash({"b": 2, "a": 1}),
        )


class PlayerSummaryTests(unittest.TestCase):
    def test_last3_uses_last_three_valid_played_games(self):
        weekly = {
            "1": {"p1": {"player_id": "p1", "gk_actual_points": 18.0, "game_played": True, "actual_quality": "Verified"}},
            "2": {"p1": {"player_id": "p1", "gk_actual_points": 0.0, "game_played": True, "actual_quality": "Verified"}},
            "3": {},
            "4": {"p1": {"player_id": "p1", "gk_actual_points": 12.0, "game_played": True, "actual_quality": "Unverified"}},
        }
        summary = build_player_summaries(weekly)["p1"]
        self.assertEqual(summary["season_games"], 3)
        self.assertEqual(summary["season_total_gk"], 30.0)
        self.assertEqual(summary["season_ppg"], 10.0)
        self.assertEqual(summary["last3_avg_gk"], 10.0)
        self.assertEqual(summary["last3_weeks"], [1, 2, 4])
        self.assertEqual(summary["latest_final_week"], 4)
        self.assertEqual(summary["last_game_gk"], 12.0)

    def test_mismatch_and_synthetic_dnp_do_not_enter_averages(self):
        weekly = {
            "1": {"p1": {"player_id": "p1", "gk_actual_points": 20.0, "game_played": True, "actual_quality": "Mismatch"}},
            "2": {"p1": {"player_id": "p1", "gk_actual_points": 0.0, "game_played": False, "actual_quality": "Zero-NoRawStats"}},
        }
        self.assertNotIn("p1", build_player_summaries(weekly))


class WeekRecordTests(unittest.TestCase):
    def test_completed_game_players_get_raw_or_synthetic_records(self):
        league = {
            "players": {
                "p1": {"player_id": "p1", "full_name": "Played Guy", "team": "NE", "position": "LB", "fantasy_positions": ["LB"], "projection_week": 1, "week_projection_gk": 10.0, "week_projection_status": "OK"},
                "p2": {"player_id": "p2", "full_name": "No Stats Guy", "team": "NE", "position": "DB", "fantasy_positions": ["DB"], "projection_week": 1, "week_projection_gk": 8.0, "week_projection_status": "OK"},
                "p3": {"player_id": "p3", "full_name": "Future Guy", "team": "DAL", "position": "LB", "fantasy_positions": ["LB"]},
            }
        }
        games = {"NE": {"status": "complete", "date": "2026-09-09T20:20:00-07:00"}}
        stats = {"p1": {"idp_tkl_solo": 4, "gp": 1}}
        scoring = {"idp_tkl_solo": 2.0}
        records = build_week_records(
            season="2026",
            week=1,
            league_data=league,
            week_stats=stats,
            completed_team_games=games,
            scoring_settings=scoring,
        )
        self.assertEqual(set(records), {"p1", "p2"})
        self.assertEqual(records["p1"]["gk_actual_points"], 8.0)
        self.assertTrue(records["p1"]["raw_stats_present"])
        self.assertTrue(records["p1"]["game_played"])
        self.assertEqual(records["p1"]["week_projection_gk_at_capture"], 10.0)
        self.assertEqual(records["p2"]["gk_actual_points"], 0.0)
        self.assertFalse(records["p2"]["raw_stats_present"])
        self.assertFalse(records["p2"]["game_played"])
        self.assertEqual(records["p2"]["actual_quality"], "Zero-NoRawStats")

    def test_correction_refresh_preserves_existing_projection_snapshot(self):
        league = {
            "players": {
                "p1": {"player_id": "p1", "full_name": "Played Guy", "team": "NE", "position": "LB", "fantasy_positions": ["LB"], "projection_week": 1, "week_projection_gk": 99.0, "week_projection_status": "OK"},
            }
        }
        existing = {"p1": {"week_projection_gk_at_capture": 10.0, "projection_status_at_capture": "OK"}}
        records = build_week_records(
            season="2026",
            week=1,
            league_data=league,
            week_stats={"p1": {"idp_tkl_solo": 5, "gp": 1}},
            completed_team_games={"NE": {"status": "complete", "date": "2026-09-09"}},
            scoring_settings={"idp_tkl_solo": 2.0},
            existing_records=existing,
        )
        self.assertEqual(records["p1"]["week_projection_gk_at_capture"], 10.0)

import json
import os
import tempfile

from scripts.gk_actuals import (
    audit_week_records,
    atomic_json_write,
    generate_actuals,
    official_points_index,
)


class MatchupAuditTests(unittest.TestCase):
    def test_verified_when_within_one_hundredth(self):
        records = {"11564": {"gk_actual_points": 10.82, "actual_quality": "Unverified"}}
        audited = audit_week_records(records, {"11564": 10.82})
        self.assertEqual(audited["11564"]["actual_quality"], "Verified")
        self.assertEqual(audited["11564"]["audit_delta"], 0.0)

    def test_mismatch_is_preserved_not_replaced(self):
        records = {"11470": {"gk_actual_points": 18.0, "actual_quality": "Unverified"}}
        audited = audit_week_records(records, {"11470": 21.0})
        self.assertEqual(audited["11470"]["gk_actual_points"], 18.0)
        self.assertEqual(audited["11470"]["official_matchup_points"], 21.0)
        self.assertEqual(audited["11470"]["actual_quality"], "Mismatch")
        self.assertEqual(audited["11470"]["audit_delta"], -3.0)

    def test_zero_no_raw_stats_is_not_promoted_to_verified(self):
        records = {"p1": {"gk_actual_points": 0.0, "actual_quality": "Zero-NoRawStats"}}
        audited = audit_week_records(records, {"p1": 0.0})
        self.assertEqual(audited["p1"]["actual_quality"], "Zero-NoRawStats")
        self.assertEqual(audited["p1"]["official_matchup_points"], 0.0)

    def test_official_points_index_flattens_rosters(self):
        idx = official_points_index([
            {"players_points": {"p1": 10.5}},
            {"players_points": {"p2": 8.0}},
        ])
        self.assertEqual(idx, {"p1": 10.5, "p2": 8.0})


class ActualsGenerationTests(unittest.TestCase):
    def _league(self):
        return {
            "league_id": "L1",
            "current_week": 1,
            "nfl_state": {"season": "2026", "season_type": "regular"},
            "league": {
                "season": "2026",
                "season_type": "regular",
                "scoring_settings": {"pass_yd": 0.04, "pass_td": 5.0, "pass_int": -2.0, "rush_yd": 0.1},
            },
            "players": {
                "11564": {
                    "player_id": "11564",
                    "full_name": "Drake Maye",
                    "team": "NE",
                    "position": "QB",
                    "fantasy_positions": ["QB"],
                    "projection_week": 1,
                    "week_projection_gk": 20.52,
                    "week_projection_status": "OK",
                }
            },
            "matchups": [{"players_points": {"11564": 10.82}}],
        }

    def test_generate_actuals_builds_verified_week_and_summary(self):
        def fake_fetch(url):
            if "/schedule/nfl/regular/2026" in url:
                return [{"week": 1, "home": "SEA", "away": "NE", "status": "complete", "date": "2026-09-09"}]
            if "/stats/nfl/regular/2026/1" in url:
                return {"11564": {"pass_yd": 178, "pass_td": 1, "pass_int": 3, "rush_yd": 47, "gp": 1}}
            raise AssertionError(f"unexpected URL {url}")

        data = generate_actuals(self._league(), existing=None, fetch_json=fake_fetch)
        record = data["weekly_actuals"]["1"]["11564"]
        self.assertEqual(data["schema_version"], "GK_ACTUALS_V1")
        self.assertEqual(data["actual_calc_version"], "GK_ACTUAL_V1")
        self.assertTrue(data["actual_status"]["fetch_ok"])
        self.assertEqual(record["gk_actual_points"], 10.82)
        self.assertEqual(record["actual_quality"], "Verified")
        self.assertEqual(data["player_summaries"]["11564"]["season_ppg"], 10.82)

    def test_stats_failure_preserves_existing_history_and_sets_fetch_false(self):
        existing = {
            "schema_version": "GK_ACTUALS_V1",
            "actual_calc_version": "GK_ACTUAL_V1",
            "scoring_settings_hash": "will-be-replaced",
            "weekly_actuals": {
                "1": {
                    "11564": {
                        "player_id": "11564",
                        "gk_actual_points": 10.82,
                        "game_played": True,
                        "actual_quality": "Verified",
                    }
                }
            },
        }
        # Align hash so this is a rolling refresh rather than a forced rebuild.
        from scripts.gk_actuals import stable_scoring_hash
        existing["scoring_settings_hash"] = stable_scoring_hash(self._league()["league"]["scoring_settings"])

        def fake_fetch(url):
            if "/schedule/nfl/regular/2026" in url:
                return [{"week": 1, "home": "SEA", "away": "NE", "status": "complete", "date": "2026-09-09"}]
            if "/stats/nfl/" in url:
                raise OSError("stats unavailable")
            raise AssertionError(f"unexpected URL {url}")

        data = generate_actuals(self._league(), existing=existing, fetch_json=fake_fetch)
        self.assertFalse(data["actual_status"]["fetch_ok"])
        self.assertEqual(data["weekly_actuals"]["1"]["11564"]["gk_actual_points"], 10.82)
        self.assertEqual(data["player_summaries"]["11564"]["season_ppg"], 10.82)

    def test_atomic_json_write_replaces_target_without_temp_leftover(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "actuals.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"old": True}, handle)
            atomic_json_write(path, {"new": True})
            with open(path, "r", encoding="utf-8") as handle:
                self.assertEqual(json.load(handle), {"new": True})
            self.assertFalse(os.path.exists(path + ".tmp"))

class EmptyFallbackActualsTests(unittest.TestCase):
    def test_valid_empty_second_stats_endpoint_is_not_network_failure(self):
        league = {
            "league_id": "L1",
            "current_week": 1,
            "nfl_state": {"season": "2026", "season_type": "regular"},
            "league": {"season": "2026", "season_type": "regular", "scoring_settings": {"idp_tkl_solo": 2.0}},
            "players": {"p1": {"player_id": "p1", "full_name": "No Stats", "team": "NE", "position": "LB", "fantasy_positions": ["LB"]}},
            "matchups": [{"players_points": {"p1": 0.0}}],
        }

        def fake_fetch(url):
            if "/schedule/nfl/regular/2026" in url:
                return [{"week": 1, "home": "SEA", "away": "NE", "status": "complete", "date": "2026-09-09"}]
            if "api.sleeper.app/v1/stats" in url:
                raise OSError("primary unavailable")
            if "api.sleeper.com/stats" in url:
                return {}
            raise AssertionError(url)

        data = generate_actuals(league, existing=None, fetch_json=fake_fetch)
        self.assertTrue(data["actual_status"]["fetch_ok"])
        self.assertEqual(data["weekly_actuals"]["1"]["p1"]["actual_quality"], "Zero-NoRawStats")

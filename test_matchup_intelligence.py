"""Synthetic, explicitly named regression fixtures. No production generation."""
import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch
import pandas as pd
from matchup_intelligence import build_intelligence, profile
from matchup_schema import validate_intelligence
from matchup_cli import write_artifact

CUTOFF = "2024-10-30T12:00:00+00:00"
GENERATED = "2024-10-30T13:00:00+00:00"
SOURCES = {key: "2024-10-30T11:00:00+00:00" for key in ("schedule", "pbp", "player_games", "weekly_rosters", "players")}


def fixture():
    teams = ("SF", "WAS", "KC", "BUF")
    roster = []
    for i, team in enumerate(teams):
        for n, pos in enumerate(("TE", "RB")):
            roster.append(dict(season=2024, week=9, game_type="REG", team=team, position=pos,
                               status="ACT", gsis_id=f"00-{3000001+i*2+n:07d}", full_name=f"TEST FIXTURE {team} {pos}"))
    players = pd.DataFrame(roster)[["gsis_id"]].copy()
    schedule, plays, info, board_rows = [], [], [], []
    by_team = {team: [r for r in roster if r["team"] == team] for team in teams}
    for week in range(1, 10):
        day = str(date(2024, 9, 8) + timedelta(days=7*(week-1)))
        for away, home in (("SF", "WAS"), ("KC", "BUF")):
            gid = f"2024_{week:02d}_{away}_{home}"
            schedule.append(dict(game_id=gid, season=2024, week=week, game_type="REG", gameday=day, gametime="13:00",
                                 home_team=home, away_team=away, home_score=20 if week<9 else None, away_score=21 if week<9 else None))
            for team, opponent in ((away,home),(home,away)):
                if week == 9:
                    for r in by_team[team]:
                        board_rows.append(dict(player_id=r["gsis_id"], player=r["full_name"], game_id=gid, team=team, opponent=opponent,
                                               position=r["position"], td_estimate=25.123, td_score=60, game_status="Upcoming", injury_status="Unknown",
                                               prediction_timing="pregame_snapshot", actual_scored_td=None, games=8, is_home=int(team==home)))
                    continue
                for r in by_team[team]:
                    info.append(dict(player_id=r["gsis_id"], player_display_name=r["full_name"], game_id=gid, season=2024,
                                     week=week, team=team, position=r["position"]))
                for n in range(36):
                    passing=n<24
                    player=by_team[team][0 if passing else 1]["gsis_id"]
                    td=passing and n<12 and team=="SF"
                    plays.append(dict(game_id=gid, play_id=n+1+(100 if team==home else 0), season=2024, week=week,
                                      season_type="REG", posteam=team, defteam=opponent, play_type="pass" if passing else "run",
                                      yardline_100=10 if passing else 50, yards_gained=10 if td else 3, two_point_attempt=0,
                                      touchdown=int(td), rush_touchdown=0, pass_touchdown=int(td), td_team=team if td else None,
                                      td_player_id=player if td else None, rusher_player_id=None if passing else player,
                                      receiver_player_id=player if passing else None, drive=n//6, epa=.2 if passing else -.1))
    from weekly_schedule import regular_games
    games=[g for g in regular_games(schedule) if g["week"]==9]
    board={"meta":{"season":2024,"week":9,"generated_at":"2024-10-30T10:00:00+00:00","model":"composite",
                   "games":[{k:g[k] for k in ("game_id","home_team","away_team","kickoff_utc")} | {"prediction_timing":"pregame_snapshot"} for g in games],
                   "final_games":[],"injury_report":{"source":"TEST FIXTURE","week_available":False,"unknown_is_not_active":True}},"rows":board_rows}
    return board,schedule,pd.DataFrame(plays),pd.DataFrame(info),pd.DataFrame(roster),players


def candidate(**kwargs):
    return build_intelligence(*fixture(), CUTOFF, generated_at=GENERATED, source_as_of=SOURCES, **kwargs)


class MatchupCalculationTests(unittest.TestCase):
    def test_favorable_signal_separate_from_v5(self):
        args=fixture();before=copy.deepcopy(args[0]);out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        validate_intelligence(out,args[0]);self.assertEqual(args[0],before)
        row=out["games"]["2024_09_SF_WAS"]["recommendations"][0]
        self.assertEqual(row["advantage"],"Favorable");self.assertEqual(row["v5_probability_pct"],25.123)
        self.assertEqual(row["defense_position"]["rz_opportunities"],144)
        self.assertEqual(row["defense_position"]["rz_td_rate"],.5)
        self.assertEqual(row["league_position"]["rz_td_rate"],.125)

    def test_missing_vintage_suppresses_designations(self):
        out=build_intelligence(*fixture(),CUTOFF,generated_at=GENERATED)
        self.assertEqual(out["meta"]["evidence_mode"],"retrospective_analysis")
        self.assertTrue(all(r["advantage"]=="Insufficient Data" for g in out["games"].values() for r in g["recommendations"]))

    def test_historical_replay_not_a_pregame_forecast(self):
        out=build_intelligence(*fixture(),CUTOFF,generated_at="2025-01-01T00:00:00Z",source_as_of=SOURCES)
        self.assertEqual(out["meta"]["evidence_mode"],"retrospective_analysis")
        validate_intelligence(out,fixture()[0])
        self.assertTrue(all(r["advantage"]=="Insufficient Data" for g in out["games"].values() for r in g["recommendations"]))

    def test_stale_v5_board_suppresses_signal(self):
        args=list(fixture());args[0]["meta"]["generated_at"]="2024-10-01T10:00:00Z"
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        validate_intelligence(out,args[0])
        self.assertTrue(all(r["advantage"]=="Insufficient Data" for g in out["games"].values() for r in g["recommendations"]))

    def test_stale_sources_suppress_signal_at_generation(self):
        out=build_intelligence(*fixture(),CUTOFF,generated_at="2024-11-02T13:00:00Z",source_as_of=SOURCES)
        validate_intelligence(out,fixture()[0])
        self.assertTrue(all(r["advantage"]=="Insufficient Data" for g in out["games"].values() for r in g["recommendations"]))

    def test_unknown_rookie_usage_is_not_zero_evidence_for_a_signal(self):
        out=candidate();rb=out["games"]["2024_09_SF_WAS"]["recommendations"][1]
        self.assertEqual(rb["advantage"],"Insufficient Data");self.assertIn("Too few player red-zone opportunities",rb["explanation"])

    def test_two_point_no_play_kneel_spike_excluded(self):
        args=list(fixture());base=candidate()
        extra=args[2].iloc[[0]].copy();extra["play_id"]=999;extra["two_point_attempt"]=1
        more=pd.concat([extra,extra.assign(play_id=1000,play_type="no_play",two_point_attempt=0),extra.assign(play_id=1001,play_type="qb_kneel",two_point_attempt=0),extra.assign(play_id=1002,play_type="qb_spike",two_point_attempt=0)])
        args[2]=pd.concat([args[2],more]);out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        self.assertEqual(out["games"],base["games"])

    def test_future_and_target_week_rows_never_enter_metrics(self):
        args=list(fixture());extra=args[2].iloc[[0]].copy();extra["game_id"]="2024_09_SF_WAS";extra["week"]=9;args[2]=pd.concat([args[2],extra])
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        self.assertEqual(out["games"],candidate()["games"])
        self.assertTrue(all(g["week"]<9 for g in out["meta"]["input_games"]))

    def test_small_samples_never_produce_favorable(self):
        args=list(fixture());args[1]=[g for g in args[1] if g["week"] in (7,8,9)]
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        self.assertTrue(all(r["advantage"]=="Insufficient Data" for g in out["games"].values() for r in g["recommendations"]))

    def test_sparse_identity_coverage_suppresses_signal(self):
        args=list(fixture());args[3]=args[3][args[3].team.ne("SF")]
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        row=out["games"]["2024_09_SF_WAS"]["recommendations"][0]
        self.assertEqual(row["advantage"],"Insufficient Data")

    def test_missing_epa_and_field_position_are_not_zero(self):
        args=list(fixture());args[2]=args[2].drop(columns="epa");args[2].loc[0,"yardline_100"]=float("nan")
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        recent=out["games"]["2024_09_SF_WAS"]["offenses"]["SF"]["season"]
        self.assertIsNone(recent["epa_per_play"]);self.assertEqual(recent["field_position_sample"],recent["plays"]-1)

    def test_drives_not_plays_are_redzone_denominator(self):
        from matchup_intelligence import clean_inputs
        args=fixture();p,history=clean_inputs(args[1],args[2],args[3],args[5],2024,9,__import__('weekly_schedule').utc(CUTOFF))
        q=p[p.posteam.eq("SF") & p.week.eq(1)]
        out=profile(q,list(q.game_id.unique()))
        self.assertEqual(out["rz_plays"],24);self.assertEqual(out["rz_trips"],4);self.assertEqual(out["rz_td_drives"],2);self.assertEqual(out["rz_td_rate"],.5)

    def test_bad_player_team_and_probability_rejected(self):
        for change in ({"team":"WAS"},{"opponent":"KC"},{"td_estimate":float("nan")}):
            args=list(fixture());args[0]["rows"][0].update(change)
            with self.assertRaises(ValueError):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)

    def test_missing_completed_game_coverage_rejected(self):
        args=list(fixture());args[2]=args[2][args[2].game_id.ne("2024_01_SF_WAS")]
        with self.assertRaisesRegex(ValueError,"coverage"):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)

    def test_ambiguous_identity_never_name_matched(self):
        args=list(fixture());args[3]=pd.concat([args[3],args[3].iloc[[0]]])
        with self.assertRaisesRegex(ValueError,"identity"):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)

    def test_pending_target_roster_blocks_generation(self):
        args=list(fixture());args[4].loc[0,"status"]="INA"
        with self.assertRaisesRegex(ValueError,"eligibility"):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)

    def test_late_cutoff_and_future_source_rejected(self):
        args=fixture()
        with self.assertRaises(ValueError):build_intelligence(*args,"2024-11-05T12:00:00Z",generated_at="2024-11-06T12:00:00Z")
        with self.assertRaises(ValueError):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of={"pbp":"2024-10-31T12:00:00Z"})

    def test_snap_percent_requires_correlated_game_identity(self):
        args=fixture();snaps=pd.DataFrame([dict(player_id="00-3000001",game_id="2024_08_SF_WAS",team="WAS",offense_pct=.75)])
        with self.assertRaisesRegex(ValueError,"identity"):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES,snaps=snaps)

    def test_lateral_score_not_assigned_to_original_receiver(self):
        args=list(fixture());args[2].loc[0,"td_player_id"]="00-3000002"
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        validate_intelligence(out,args[0])
        season=out["games"]["2024_09_SF_WAS"]["offenses"]["SF"]["season"]
        self.assertEqual(season["position_td_exclusions"],1)

    def test_snap_source_fraction_has_explicit_percent_conversion(self):
        snaps=pd.DataFrame([dict(player_id="00-3000001",game_id="2024_08_SF_WAS",team="SF",offense_pct=.75)])
        out=build_intelligence(*fixture(),CUTOFF,generated_at=GENERATED,source_as_of=SOURCES|{"snaps":SOURCES["pbp"]},snaps=snaps)
        self.assertEqual(out["games"]["2024_09_SF_WAS"]["offenses"]["SF"]["players"][0]["snap_participation_pct"],75)

    def test_prior_week_rescheduled_after_cutoff_is_excluded(self):
        args=list(fixture())
        for game in args[1]:
            if game["game_id"]=="2024_08_SF_WAS":game["gameday"]="2024-11-04"
        out=build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        self.assertNotIn("2024_08_SF_WAS",{g["game_id"] for g in out["meta"]["input_games"]})
        validate_intelligence(out,args[0])

    def test_malformed_touchdown_evidence_is_not_zero(self):
        args=list(fixture());args[2].loc[0,"touchdown"]=float("nan")
        with self.assertRaisesRegex(ValueError,"evidence"):build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)

    def test_wilson_guard_rejects_one_event_favorable(self):
        from matchup_intelligence import designation
        out=candidate();g=out["games"]["2024_09_SF_WAS"]
        p=g["offenses"]["SF"]["players"][0];d=g["defenses"]["WAS"];league=d["league"]
        dp=next(r for r in d["positions"] if r["position"]=="TE");lp=next(r for r in league["positions"] if r["position"]=="TE")
        dp.update(rz_opportunities=12,rz_tds=1,rz_td_rate=round(1/12,6));lp.update(rz_opportunities=100,rz_tds=0,rz_td_rate=0)
        self.assertEqual(designation(p,g["offenses"]["SF"],d,league,True)[0],"Neutral")

    def test_unfavorable_and_neutral_paths(self):
        from matchup_intelligence import designation
        out=candidate();g=out["games"]["2024_09_SF_WAS"]
        self.assertEqual(g["recommendations"][2]["advantage"],"Unfavorable")
        p=g["offenses"]["SF"]["players"][0];d=g["defenses"]["WAS"];league=d["league"]
        next(r for r in d["positions"] if r["position"]=="TE").update(rz_tds=18,rz_td_rate=.125)
        self.assertEqual(designation(p,g["offenses"]["SF"],d,league,True)[0],"Neutral")

    def test_no_input_mutation(self):
        args=fixture();before=[x.copy(deep=True) for x in args[2:]]
        build_intelligence(*args,CUTOFF,generated_at=GENERATED,source_as_of=SOURCES)
        for actual,expected in zip(args[2:],before):pd.testing.assert_frame_equal(actual,expected)


class MatchupContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.board=fixture()[0];cls.valid=candidate()
    def test_contract_and_json_round_trip(self):
        validate_intelligence(json.loads(json.dumps(self.valid,allow_nan=False)),self.board)
    def reject(self, mutate):
        data=copy.deepcopy(self.valid);mutate(data)
        with self.assertRaises((ValueError,KeyError,TypeError)):validate_intelligence(data,self.board)
    def test_bad_probability(self):self.reject(lambda d:d["games"]["2024_09_SF_WAS"]["recommendations"][0].update(v5_probability_pct=99))
    def test_bad_denominator(self):self.reject(lambda d:d["games"]["2024_09_SF_WAS"]["defenses"]["WAS"]["positions"][2].update(rz_td_rate=.9))
    def test_future_sample(self):self.reject(lambda d:d["meta"]["input_games"][0].update(kickoff_utc="2025-01-01T00:00:00Z"))
    def test_false_favorable(self):self.reject(lambda d:d["games"]["2024_09_SF_WAS"]["recommendations"][1].update(advantage="Favorable"))
    def test_wrong_game(self):self.reject(lambda d:d["games"]["2024_09_SF_WAS"].update(home_team="KC"))
    def test_missing_source_fingerprint(self):self.reject(lambda d:d["meta"]["source_fingerprints"].pop("pbp"))
    def test_unknown_schema(self):self.reject(lambda d:d["meta"].update(schema_version=2))
    def test_unsupported_personnel(self):self.reject(lambda d:d["games"]["2024_09_SF_WAS"]["offenses"]["SF"].update(personnel={"11":.8}))
    def test_existing_artifact_cannot_be_overwritten(self):
        from datetime import datetime,timezone
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder, patch("matchup_cli.uuid.uuid4") as uid, patch("matchup_cli.datetime") as clock:
            uid.return_value.hex="a"*32;clock.now.return_value=datetime(2024,10,30,tzinfo=timezone.utc)
            path,_=write_artifact(self.valid,self.board,folder);original=path.read_bytes()
            with self.assertRaises(FileExistsError):write_artifact(self.valid,self.board,folder)
            self.assertEqual(path.read_bytes(),original)

    def test_immutable_local_writer_and_live_refusal(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            path,digest=write_artifact(self.valid,self.board,temp)
            self.assertTrue(path.exists());self.assertEqual(len(digest),64)
            validate_intelligence(json.loads(path.read_text()),self.board)
        for protected in ("td-predictor-web/public/data", "td-predictor-web/public", "public"):
            with self.assertRaises(ValueError):write_artifact(self.valid,self.board,protected)


if __name__=="__main__":unittest.main()

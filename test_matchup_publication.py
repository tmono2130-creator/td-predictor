"""Local synthetic candidates and isolated Git repositories only."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
import pandas as pd
from test_weekly_automation import candidate, game, NOW, rewrite
from weekly_storage import load_json, write_new, digest, validate_candidate, publish_candidate, validate_manifest
from matchup_intelligence import build_intelligence, REQUIRED
from matchup_cli import attach_artifact
from matchup_publication import SIDECAR, HASH_KEY
import test_reviewed_publication as reviewed_tests
from reviewed_publication import validate_change, PREFIX, MANIFEST, tree
from verify_publication import verify_json, PRODUCTION


def artifact_for(folder, now=NOW):
    board = load_json(folder / "board.json")
    roster = pd.DataFrame([dict(season=2026, week=1, game_type="REG", team=r["team"],
        position=r["position"], status="ACT", gsis_id=r["player_id"], full_name=r["player"]) for r in board["rows"]])
    return build_intelligence(board, [game()], pd.DataFrame(columns=sorted(REQUIRED)),
        pd.DataFrame(columns=["player_id", "game_id", "team", "position", "season", "week"]),
        roster, roster[["gsis_id"]], now.isoformat(), generated_at=now.isoformat(),
        source_as_of={k:now.isoformat() for k in ("schedule", "pbp", "player_games", "weekly_rosters", "players")})


def attach(folder, now=NOW, mutate=None):
    value = artifact_for(folder, now)
    if mutate: mutate(value)
    path = folder.parent / (folder.name + "-evidence.json")
    write_new(path, value)
    return attach_artifact(folder, path, now)


class OptionalPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.folder, _ = candidate(self.root / "candidate")

    def test_legacy_candidate_remains_valid(self):
        self.assertEqual(len(validate_candidate(self.folder, now=NOW)[0]["rows"]), 2)

    def test_optional_bundle_hash_and_manifest_binding(self):
        expected = attach(self.folder)
        before = (self.folder / SIDECAR).read_bytes()
        output = self.root / "data"
        relative = publish_candidate(self.folder, output, now=NOW)
        files = validate_manifest(output)["seasons"]["2026"]["weeks"]["1"]
        self.assertEqual(files[HASH_KEY], expected)
        self.assertEqual(files["matchup_intelligence"], relative + "/" + SIDECAR)
        self.assertEqual((output / relative / SIDECAR).read_bytes(), before)
        self.assertEqual(load_json(output / relative / SIDECAR)["games"][game()["game_id"]]["recommendations"][0]["advantage"], "Insufficient Data")

    def test_hash_tampering_rejected(self):
        attach(self.folder)
        with (self.folder / SIDECAR).open("ab") as stream: stream.write(b" ")
        with self.assertRaisesRegex(ValueError, "hash"):
            validate_candidate(self.folder, now=NOW)

    def test_unreceipted_or_missing_or_unexpected_files_rejected(self):
        write_new(self.folder / SIDECAR, artifact_for(self.folder))
        with self.assertRaisesRegex(ValueError, "bundle files"):
            validate_candidate(self.folder, now=NOW)
        (self.folder / SIDECAR).unlink()
        attach(self.folder)
        (self.folder / SIDECAR).unlink()
        with self.assertRaises(ValueError): validate_candidate(self.folder, now=NOW)

    def test_stale_sources_rejected(self):
        def stale(value):
            value["meta"]["source_as_of"]["pbp"] = (NOW-timedelta(days=2)).isoformat()
        with self.assertRaisesRegex(ValueError, "Stale"):
            attach(self.folder, mutate=stale)
        self.assertFalse((self.folder / SIDECAR).exists())

    def test_retrospective_evidence_rejected(self):
        with self.assertRaisesRegex(ValueError, "pregame"):
            attach(self.folder, mutate=lambda a:a["meta"].update(evidence_mode="retrospective_analysis"))

    def test_identity_probability_and_missing_game_rejected(self):
        for mutation in (lambda a:a["games"][game()["game_id"]]["recommendations"][0].update(v5_probability_pct=90),
                         lambda a:a["games"].clear(),
                         lambda a:a["games"][game()["game_id"]]["recommendations"][0].update(player_id="00-9999999")):
            with self.subTest(mutation=mutation):
                value=artifact_for(self.folder); mutation(value)
                from matchup_schema import validate_intelligence
                with self.assertRaises(ValueError): validate_intelligence(value,load_json(self.folder/"board.json"))

    def test_attach_cannot_replace_existing_evidence(self):
        attach(self.folder)
        with self.assertRaises(ValueError): attach_artifact(self.folder,self.folder/SIDECAR,NOW)

    def test_archived_validation_does_not_apply_current_freshness(self):
        attach(self.folder)
        output=self.root/"data"; publish_candidate(self.folder,output,now=NOW)
        self.assertIn("2026",validate_manifest(output)["seasons"])
        with self.assertRaises(ValueError):validate_candidate(self.folder,now=NOW+timedelta(days=1))

    def test_manifest_hash_pair_cannot_be_removed(self):
        attach(self.folder);output=self.root/"data";publish_candidate(self.folder,output,now=NOW)
        rewrite(output,"manifest.json",lambda m:m["seasons"]["2026"]["weeks"]["1"].pop(HASH_KEY))
        with self.assertRaisesRegex(ValueError,"paired"):validate_manifest(output)


    def test_complete_nonempty_matchup_evidence_accepted(self):
        from test_matchup_intelligence import fixture as matchup_fixture, candidate as matchup_candidate, GENERATED
        from weekly_schedule import regular_games, utc
        board,schedule,*_=matchup_fixture()
        board=copy.deepcopy(board)
        template=load_json(self.folder/"board.json")["meta"]
        board["meta"].update({k:template[k] for k in ("model_version","source_versions","snapshot_classification")})
        for g in board["meta"]["games"]:g["snapshot_classification"]="pregame_snapshot"
        for r in board["rows"]:
            r.update(predicted_td_probability_pct=r["td_estimate"],snapshot_classification="pregame_snapshot",
                     prediction_timestamp_utc=board["meta"]["generated_at"])
        reports={}
        template_report=load_json(self.folder/"breakdowns.json")["games"]["KC@BUF"]
        for g in board["meta"]["games"]:
            teams=[g["away_team"],g["home_team"]]
            report=copy.deepcopy(template_report)
            report.update(teams=teams,players={t:{} for t in teams},injuries={t:[] for t in teams})
            report["meta"]["games_used"]={t:6 for t in teams};report["meta"]["prior_season_games"]={t:0 for t in teams}
            reports["@".join(teams)]=report
        local=self.root/"full";local.mkdir()
        write_new(local/"board.json",board)
        write_new(local/"breakdowns.json",{"meta":{"season":2024,"week":9,"generated_at":board["meta"]["generated_at"],"lookback":6},"games":reports,"errors":{}})
        receipt={"source_cutoff_utc":board["meta"]["generated_at"],"source_metadata":{"fixture":{"retrieved_at_utc":board["meta"]["generated_at"]}},
                 "scheduled_games":[g for g in regular_games(schedule) if g["week"]==9],
                 "eligible_players":[{k:r[k] for k in ("player_id","game_id","team","opponent")} for r in board["rows"]],
                 "board_sha256":digest(local/"board.json"),"breakdowns_sha256":digest(local/"breakdowns.json"),"base_manifest_sha256":None}
        write_new(local/"receipt.json",receipt)
        path=self.root/"full-artifact.json";write_new(path,matchup_candidate())
        attach_artifact(local,path,utc(GENERATED))
        output=self.root/"full-data";relative=publish_candidate(local,output,now=utc(GENERATED))
        validate_manifest(output)
        self.assertEqual(load_json(output/relative/SIDECAR)["games"]["2024_09_SF_WAS"]["recommendations"][0]["advantage"],"Favorable")

    def test_unexpected_candidate_file_rejected(self):
        (self.folder/"unexpected.json").write_text("{}",encoding="utf-8")
        with self.assertRaisesRegex(ValueError,"bundle files"):validate_candidate(self.folder,now=NOW)

    def test_kickoff_margin_rejected_even_for_valid_sidecar(self):
        from weekly_schedule import kickoff
        attach(self.folder)
        with self.assertRaisesRegex(ValueError,"margin|Stale"):
            validate_candidate(self.folder,now=kickoff(game())-timedelta(minutes=5))


class OptionalDataPRTests(unittest.TestCase):
    def setUp(self):
        self.fixture=reviewed_tests.DataPRTests("test_valid_data_only_pr_and_complete_coverage")
        self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f=self.fixture
        rewrite(f.candidate,"receipt.json",lambda r:r.update(base_manifest_sha256=digest(f.data/"manifest.json")))
        attach(f.candidate,f.now)
        f.folder=publish_candidate(f.candidate,f.data,now=f.now)
        self.head=f.commit()

    def test_explicit_four_file_bundle_accepted(self):
        f=self.fixture
        # Compare to the prior new snapshot commit: only the optional new bundle is proposed.
        result=validate_change(f.repo,f.head,self.head,"nfl-pm/publication/999-1",[game()],f.now)
        self.assertEqual(result["players"],2)

    def test_immutable_sidecar_cannot_be_changed(self):
        f=self.fixture
        path=f.data/f.folder/SIDECAR;path.write_bytes(path.read_bytes()+b" ")
        with self.assertRaisesRegex(ValueError,"Immutable"):
            validate_change(f.repo,self.head,f.commit(),"nfl-pm/publication/999-1",[game()],f.now)

    def test_rollback_retains_optional_snapshot(self):
        f=self.fixture
        previous=f.fixture_git("show",f"{f.head}:{MANIFEST}")
        (f.data/"manifest.json").write_text(previous,encoding="utf-8")
        rollback=f.commit()
        result=validate_change(f.repo,self.head,rollback,"nfl-pm/rollback/test",[game()],f.now)
        self.assertEqual(result["kind"],"rollback")
        self.assertIn(PREFIX+f.folder+"/"+SIDECAR,tree(f.repo,rollback))

    def test_deployment_checks_optional_and_inactive_artifact_bytes(self):
        f=self.fixture; expected=tree(f.repo,self.head)
        def fetch(url):return expected[PREFIX+url.removeprefix(PRODUCTION+"/data/")]
        hashes=verify_json(expected,fetch)
        self.assertIn(f.folder+"/"+SIDECAR,hashes)
        def corrupt(url):return b"{}" if url.endswith(SIDECAR) else fetch(url)
        with self.assertRaisesRegex(ValueError,"hash mismatch"):verify_json(expected,corrupt)

    def test_deployment_rejects_manifest_pin_even_when_served_bytes_match(self):
        f=self.fixture;expected=tree(f.repo,self.head)
        manifest=json.loads(expected[MANIFEST])
        manifest["seasons"]["2026"]["weeks"]["1"][HASH_KEY]="0"*64
        expected[MANIFEST]=json.dumps(manifest).encode()
        with self.assertRaisesRegex(ValueError,"manifest hash/reference"):
            verify_json(expected,lambda _:self.fail("Must fail before network access"))

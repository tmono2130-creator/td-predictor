# Week 9 evaluation, reliability, diversified parlays and Week 10 readiness

## Baseline audited November 9, 2026

Remote main is `ad281bb03b19bb3bc936d92f1149da75acb58891` (merged checkout-history fix, PR #19). The initial local branch was `fix/nfl-pm-generate-history`, HEAD `d4aebcba008677fdaf613a2db2c033c6a4dbe23b`; its tree is identical to main. Tracked working files were clean. Work continues on `feature/nfl-pm-week9-evaluation-parlays`, created from fetched origin/main. Existing unrelated untracked caches, data and work folders are excluded from commits.

Vercel production `dpl_B1oWYvYxpSVmQRteJHKsb6kks78V` is Ready on main `ad281bb`, alias `onopm.space`. The live manifest SHA-256 is `d57c79c06ea800587150a21b7476c2c649a2b2d6972d76a365a06ae9bff8bc15`, still pointing Week 8 to the October 31 snapshot. Week 9's November 5 three-feature analysis was local and unpublished. Existing production has 18 JSON files, including the original 13. No release is part of this work.

Architecture:

- `td_predictor_v5.py`, called through `weekly_generation.score_v5`: unchanged hand-weighted V5 estimates. No retraining or calibration fitting.
- `game_projection.py` / `game_projection_artifact.py`: unchanged PPP V1 primary baseline. Ridge adjustment remains experimental and inactive in the frozen Week 9 run.
- `matchup_intelligence.py`, `matchup_schema.py`: unchanged evidence thresholds and classifications.
- `weekly_capture.py`, `weekly_data.py`, `weekly_storage.py`: immutable captures, common cutoff, deterministic replay, candidate receipts, optional sidecars and immutable snapshots.
- `automation_publish.py` / `reviewed_publication.py`: manual opt-ins, protected environment, branch collision checks and reviewed data-only PRs. No direct-main push or automatic merge.
- `td-predictor-web`: existing purple React dashboard and static manifest. `lib/parlay.ts` remains the only parlay/Market math implementation.

The existing historical datasets and evaluation report were inspected, not regenerated. They are retrospective participation-conditioned backfills; source vintages are not archived. V5 ranking-score calibration there is train-only isotonic, not a validation of the raw V5 estimate curve. The report explicitly discloses that V5 weight development used 2024/2025 evidence. Those metrics are descriptive, and cannot be equated with independent held-out pregame results or the different player coverage of this run.

## Original Week 9 evidence

`work/week9-report-20261106T000459Z/` retains the report, original receipt and all five immutable candidate JSON files. Their SHA-256 values still match the original report:

| File | SHA-256 |
|---|---|
| board.json | ad7a75f192b3efdc100ea5760ba20cd79082f445e23f2f6c5b29651b44de8d72 |
| breakdowns.json | 59ef53bfa6e5996fa3b162e934141268473af53914e3a3821607f871a4241f26 |
| game-predictor.json | 01f043cff991f53b7b52e557f6bbc08e405dace790ca300e9b17025a698ddaa0 |
| matchup-intelligence.json | 469311b44b13dfaa49516de7ee063b74731daa84c22599dd3a5be6e858e2c7c5 |
| receipt.json | 86523563628ba424fd507489e8be55a29aa1d29125aa5ef6d7548b5a6043a0c3 |

Original source cutoff: `2026-11-06T00:04:42.992922+00:00`; generation: `2026-11-06T00:04:59.913788+00:00`, before every target kickoff. The captured generator revision was `ad281bb`. There were 15 games, 467 included and 1,929 excluded roster records, zero pending, 3 known injury designations and 464 Unknown. Intelligence labels were 1 Favorable, 121 Neutral and 345 Insufficient Data.

The original raw files are **missing**: `schedule.csv`, `stats_2023.parquet` through `stats_2026.parquet`, `pbp_2023.parquet` through `pbp_2026.parquet`, `weekly_rosters_2026.parquet`, `players_2026.parquet`, `injuries_2026.parquet`. Their URLs, hashes and timestamps survive in the original capture manifest and receipt. Evaluation uses frozen predictions, never regenerates them. Source hashes establish integrity, not an independent signature or original-raw-input retention guarantee.

## Immutable postgame evaluation

`postgame_evaluation.py`:

1. Validates the frozen files against the original receipt, schema, original source-revision hashes, season/week/game identities and original pregame timing. It does not require old predictions to be fresh today and never turns them back into publishable forecasts.
2. Retrieves outcome evidence separately, preserves its actual retrieval/provider timestamps and raw files, and requires schedule scores to agree with a captured END GAME event. Scores alone are not final-state proof.
3. Keeps pending games and unknown player outcomes null. Missing/malformed rushing or receiving TD fields, missing player stats, team conflicts or incomplete scorer evidence cannot become confirmed negatives. No name-only ID joins.
4. Compares stable player/game/team identities. Passing TDs are not a TD for the passer. Credited return TDs are included in the anytime-scorer evaluation; this target differs from older rush/receive-only historical evaluations.
5. Separates raw-estimate Brier/log loss/AUC/calibration diagnostics from ranking hit rates, and reports labelled coverage plus an offensive-participation subset. Missing stat rows are not sportsbook void/settlement determinations.
6. Uses a deterministic evaluation ID bound to engine hash, forecast hashes and observed outcomes. Repeating identical observations returns the original sealed output. New official results create another immutable evaluation; partial results are never overwritten. Existing output hashes are checked before reuse.

Outcome capture is retained locally at `work/milestone-week9-audit-20261109T190755Z/outcomes-inputs/`, frozen at `2026-11-09T19:08:29.899633+00:00`. Current 2026 PBP was provider-modified at 14:13:16 UTC and player stats at 14:15:08 UTC on November 9. Buffalo–Minnesota remains pending; the week is not complete.

Partial results on the 14 verified finals:

| Metric | PPP V1 | Frozen prior offensive points/game baseline |
|---|---:|---:|
| Correct winners | 12/14 (85.71%) | 11/14 (78.57%) |
| Per-team score MAE | 7.3834 | 7.7232 |
| Game-total MAE | 11.2772 | 11.1786 |
| Home-margin MAE | 8.9667 | 10.0357 |

TD coverage: 301 labelled rows, 55 scorers; 136 missing player-stat labels and 30 pending-game labels. Raw V5 Brier **0.155593**, log loss **0.601995**, ROC AUC **0.667664**. Per-game top-five slots contain 23 hits among 67 labelled selections out of 70 slots (34.33%, conditional on labelled coverage). Full game/player comparisons, calibration bands, position results and original-margin bands are exported as JSON, Markdown and CSV. These small, partial-week results do not establish calibration or justify retuning.

Usage, from the repository root:

```powershell
python postgame_evaluation.py --snapshot work/week9-report-20261106T000459Z/candidate --capture work/milestone-week9-audit-20261109T190755Z/outcomes-inputs --output work/week9-evaluations
# After MNF's official final and complete source updates, use a NEW outcome capture:
python postgame_evaluation.py --snapshot work/week9-report-20261106T000459Z/candidate --capture work/week9-final-outcomes-NEW-UTC --capture-latest --output work/week9-evaluations
```

Existing `evaluation/` datasets and served-public directories are forbidden export targets. No captured raw data or generated evaluation is included in the code commit.

## Data reliability findings and diagnostics

`data_quality.py` uses the existing resolver without changing its policy. It reports game identity/duplicate checks, relevant-team roster evidence, pending decisions, injury-source availability, original injury coverage and explicitly unverified provider QB annotations. Missing optional injury data does not erase valid roster players. Neither practice participation nor blank/missing game designation means healthy or Active.

The November 9 Week 9 roster capture contains 2,420 rows. Existing resolution yields 425 include, 1,937 exclude and **58 pending**, all `INA` requiring game-specific evidence. These later records do not prove the original November 5 pool was wrong and are not manually substituted into old forecasts. `INA` is not release/retirement evidence. No player-team mismatch was established in the frozen cohort against target-week membership records.

The current injury feed has 362 Week 9 rows, including non-skill players: 75 Out, 73 Questionable, 6 Doubtful and 208 blank/Unknown. These are not directly comparable to the original skill-player cohort's 3 known designations. Forecasts retain original statuses. The PPP baseline has no QB/injury/weather/market adjustment; starting-QB availability remains an explicit external verification requirement, not an invented model input.

Intelligence insufficiency is attributable to the existing minimum sample policy: 292 explanations reference too few player red-zone opportunities, 231 too few player opportunities and 203 too few defensive-position red-zone opportunities (reasons overlap). Missing snap participation also remains null. No threshold was relaxed to manufacture recommendations.

## Diversified parlay feature

New pure `lib/parlay-generator.ts` selects IDs from existing V5 estimates; `lib/parlay.ts` is unchanged. UI supports 2–5 legs, 10/20/30 unique combinations, game/kickoff-window filters, high-estimate/balanced/long-shot weighting, a reproducible seed, optional one-leg-per-game diversification and a hard exposure cap. Requested batches either satisfy all constraints or fail explicitly; no partial batch can silently inflate exposure percentages. Unknown injuries remain unverified. Confirmed Out, IR, inactive, ineligible and pending eligibility records are excluded from the new generator.

Only upcoming, recent pregame snapshots outside the existing ten-minute margin can produce a batch. Result visibility is bound to the snapshot identities and expires with generation-time freshness/kickoff restrictions. Source freshness is still enforced by reviewed publication; the browser does not invent source timestamps. Combined values use unchanged math and are labelled an independence approximation, not a calibrated joint probability or sportsbook EV. Existing manual and single-auto modes and Market calculations remain intact.

## Performance website feature and activation boundary

New Performance navigation uses existing purple styles and static JSON, with loading/error/empty states, season/week selection, partial/final counts, original generation and source timestamps, predicted/actual scores, errors, calibration, position/ranking/margin diagnostics and searchable player outcomes. An optional `/evaluations/index.json` pins each report with SHA-256; report ID, week, coverage, original pregame timing and nullable pending outcomes are checked. Future evaluation timestamps and hash mismatches fail closed. Other seasons can be selected when reviewed reports exist; missing historical reports display unavailable.

No evaluation assets have been copied into public directories. Normal browsing therefore shows an honest unavailable state until a separately approved static evaluation release exists. The existing six-file prediction publication allowlist has **not** been extended to these assets. Activation needs an explicitly reviewed evaluation-asset publication/verification contract and reviewed data PR, not a source-only classification or a change to the existing forecast allowlist. Browser tests use isolated routes and clearly labelled synthetic fixtures or the real local frozen evaluation; they are not a production-data publication.

## Week 10: NOT READY for a complete three-feature candidate

The current provider schedule was compared with the [official NFL weekly schedule PDF, page 10](https://media.nfl.com/content/dam/communications/football-communications/2026/news/05%2014%2026%20-%202026%20NFL%20Schedule%20-%20By%20Week.pdf) and current [Week 10 schedule](https://www.nfl.com/schedules/2026/by-week/week-10). Future flex changes must be rechecked at capture time.

| Matchup | Pacific (PST) | UTC kickoff |
|---|---|---|
| WAS @ NYG | Nov 12 17:15 | Nov 13 01:15 |
| NE @ DET (Munich; designated home DET) | Nov 15 06:30 | Nov 15 14:30 |
| KC @ ATL | Nov 15 10:00 | Nov 15 18:00 |
| HOU @ CLE | Nov 15 10:00 | Nov 15 18:00 |
| MIN @ GB | Nov 15 10:00 | Nov 15 18:00 |
| MIA @ IND | Nov 15 10:00 | Nov 15 18:00 |
| CAR @ NO | Nov 15 10:00 | Nov 15 18:00 |
| BUF @ NYJ | Nov 15 10:00 | Nov 15 18:00 |
| JAX @ TEN | Nov 15 10:00 | Nov 15 18:00 |
| LA @ ARI | Nov 15 13:05 | Nov 15 21:05 |
| SEA @ LV | Nov 15 13:05 | Nov 15 21:05 |
| SF @ DAL | Nov 15 13:25 | Nov 15 21:25 |
| PIT @ CIN (SNF) | Nov 15 17:20 | Nov 16 01:20 |
| LAC @ BAL (MNF) | Nov 16 17:15 | Nov 17 01:15 |

Munich is 15:30 CET, 14:30 UTC, 06:30 PST. Byes: CHI, DEN, PHI, TB. All 28 playing-team IDs are canonical (LA, not an identity-merged LAR). Sunday regional games, TNF, international, SNF and MNF are covered; no duplicated playing team.

At the captured cutoff, Week 10 has zero target-week roster rows and zero injury-report rows. A complete intelligence sidecar requires genuine target-week roster evidence; season fallback is not proof. Hence no Week 10 prediction candidate was generated. The not-yet-kicked-off Week 9 MNF game can legitimately be omitted at a current provisional cutoff; after it kicks off, the current pipeline requires its verified final before a later Week 10 generation. Do not bypass that restriction. Unknown injuries remain explicit rather than fabricated even when optional feeds are unavailable.

Next: retain MNF's official final and complete stats/PBP, rerun final evaluation with a new capture, wait for Week 10 target-week roster evidence and resolve genuine pending records, then run the existing all-feature pipeline into NEW work folders. Require all three artifacts, exact replay, latest injury/QB context, original source receipts, hashes, freshness, kickoff headroom and existing protected human review. No schedules, flags or permissions were enabled.

## Validation and remaining work

Added Python regression coverage for hand-calculated metrics, unknown labels, missing/malformed/conflicting outcomes, passing TD semantics, partial/final progression, immutable/idempotent output, hash tampering, duplicate identities, schedule changes, optional-source absence, INA handling, unrelated teams, QB uncertainty and Munich/prime-time timezone conversion. The existing release-rehearsal test now pins its synthetic schedule clock, fixing its real-wall-clock failure after November 8 without changing production code.

Added Node checks for seeded weighted selection, exposure, uniqueness, all requested batch sizes/leg counts, game scoping, unavailable-player exclusion, freshness/kickoff boundaries, impossible constraints, evaluation hashes, metadata, nullable pending states and future evidence. Added responsive browser checks for new features. Existing CI keeps its permissions and trigger boundaries; only new source lint targets and a read-only browser invocation were added. No new credential, environment, schedule, production job or publication command.

Actual test logs, generated outcomes and screenshots remain under `work/m6-*` and `work/week9-evaluations/`. The source commits contain no raw inputs, generated forecasts/evaluations, caches, screenshots, secrets or historical dataset changes. Hosted CI is not claimed until a separately approved push/PR executes it.

Remaining activation requirements: human review of source commits and required hosted CI; approved evaluation-asset publication/verification design; authentic Week 10 roster and final-game inputs; game-day availability/QB evidence; durable original pregame raw capture retention; and separately authorized reviewed publication. Recommended next milestone is supervised final Week 9 evaluation plus evidence-backed Week 10 generation, then dormant scheduling design. No weight tuning is justified by this partial cohort.

# Milestone 7: Matchup Intelligence

## Scope and source availability

Game Breakdown retains its original report and adds Offensive Identity, Defensive Vulnerabilities, and TD Recommendations. This is a separate descriptive analysis layer. It never modifies, multiplies or recalibrates V5 probabilities, parlay calculations or Market Check. There is no new prediction API and no final-score/winner predictor.

| Evidence | Availability and treatment |
| --- | --- |
| Schedule, IDs, run/pass plays, yards, field position, intended receivers, rushers, TD flags and drive IDs | Existing nflverse/nflreadpy data; validated and filtered by canonical schedule game, season, week and actual kickoff. No names-only identity resolution. |
| Historical player/game position | Player statistics with GSIS/game/team corroboration; unresolved positions remain outside position rates and reduce reported attribution coverage. |
| Target-week roster | Existing shared week-aware resolver, target-week records required. Any pending membership still blocks artifact construction. Injury status and game-day activation do not replace membership evidence. |
| EPA and success rate | Optional verified PBP EPA; omitted when any eligible-play EPA is missing. Success means EPA > 0. These are descriptive and not opponent-adjusted. |
| Snap participation | Optional normalized GSIS/game/team records, corroborated against player-game records. `offense_pct` must be a source fraction between 0 and 1; displayed percentage is fraction × 100. No inferred snap share. |
| Personnel, formations, routes, coverage, play-call intent | Not supplied. Participation/FTN sources have different availability/licensing and cannot be assumed available pregame; no inferred 11/12/21 personnel. |
| Strength of schedule adjustment | Not implemented. No claim that a raw rate is adjusted for opponent quality. |
| Original historical source vintages | Public feeds may be revised. A retrospective replay is not evidence that the same data was available before kickoff. |

References: [PBP dictionary](https://nflreadr.nflverse.com/articles/dictionary_pbp.html), [participation source](https://nflreadr.nflverse.com/reference/load_participation.html). FTN participation is not a substitute for verified live-week availability.

## Calculations and leakage controls

Only completed current-season regular-season games with week < target week and actual kickoff < the declared data cutoff enter the analysis. The cutoff precedes every target kickoff. Every eligible completed game must have offensive play coverage for both teams. A rescheduled prior-week game after cutoff is excluded. Missing/malformed required TD/try evidence fails instead of becoming zero. No-plays, kneels, spikes and two-point attempts are excluded. Pass plays include sacks; target denominators count intended receiver IDs, not all dropbacks.

Recent samples are each team's last six eligible games; trends use the last three; season totals use all eligible current-season games. Every sample includes game IDs and counts. Red-zone frequency uses plays inside the 20; goal-line opportunities use plays inside the 5. Red-zone scoring rate is TD drives / drives that reached the red zone, not TD plays / red-zone plays. Missing field position and drive IDs have explicit coverage counts.

Player targets/carries and red-zone shares use all observed team opportunities in their corresponding denominators. Positions use historical player/game records, not future/current global positions. Lateral or unattributed scoring plays are excluded from direct position opportunities and TDs, with exclusions and attribution coverage displayed. All aggregate rates retain numerator and denominator evidence.

The league reference uses all eligible completed current-season games before cutoff. Position TD/opportunity rates are descriptive; they are not a defense ranking solely by raw TD totals.

A designation requires all of:

- At least 4 offensive and 4 defensive sample games.
- At least 10 player opportunities and 3 player red-zone opportunities.
- At least 12 defensive position red-zone opportunities and 100 league position red-zone opportunities.
- At least 95% defensive and league position attribution coverage, with complete field-position coverage.
- Source retrieval/availability timestamps for every required input, fresh inputs and a fresh bound V5 board at generation, and more than ten minutes to kickoff.

Favorable additionally requires at least 15% player share of team red-zone opportunities. The defensive position RZ TD/opportunity rate must exceed the league rate by at least max(5 percentage points, 25% of league rate), and the defense's lower 95% Wilson bound must exceed the league's upper bound. Unfavorable uses the opposite gap and separated intervals. Otherwise sufficient evidence is Neutral; missing/stale/insufficient evidence is Insufficient Data. Intervals are conservative descriptive guards, not a fitted predictor; opportunities may be correlated within games. No accuracy improvement is claimed.

At generation and display, freshness tightens from 24 hours to 6 hours within 48 hours of kickoff, then 30 minutes within 6 hours. Source cutoff, retrieval timestamps and bound V5 board age are checked. The UI also suppresses current favorable/unfavorable labels after kickoff or when stale. Unknown future outcomes remain separate from this feature.

## Static artifact and local workflow

`schemas/matchup-intelligence.schema.json` is the structural JSON contract. `matchup_schema.py` additionally checks rate denominators, cutoff/sample references, target roster coverage, source fingerprints, methodology policy, recomputed designations, and exact V5 probability/identity binding.

The sidecar contains metadata, canonical games, both offense/defense reports, recommendations and an audited target roster. It stores generated/data-as-of timestamps, source availability timestamps, source fingerprints, sample game IDs and methodology version. It binds to the selected board's season/week/generated timestamp and unchanged player probabilities.

The local CLI consumes existing input files and never calls the prediction model or publishes:

```powershell
python matchup_cli.py build --board work/input/board.json --schedule work/input/schedule.csv --pbp work/input/pbp.parquet --player-games work/input/player-games.parquet --weekly-rosters work/input/rosters.parquet --players work/input/players.parquet --cutoff <timezone-aware-UTC> --source-as-of work/input/source-as-of.json --output work/matchup-candidates
python matchup_cli.py validate --artifact <new-path>/matchup-intelligence.json --board work/input/board.json
```

Source-as-of keys: `schedule`, `pbp`, `player_games`, `weekly_rosters`, `players`, and `snaps` if supplied. Use actual capture times from a trusted producer, not backdated claims. Fingerprints identify supplied data but cannot independently prove its historical availability. Without verified timing, or when generated after kickoff, the artifact is retrospective and all recommendations are Insufficient Data.

Output is a new `season/week-N/UTC-run-id/matchup-intelligence.json`, opened exclusively and hashed with SHA-256. Existing artifacts cannot be overwritten. Both live-data roots and the entire frontend/legacy served-public trees are forbidden. No existing manifest, JSON export, snapshot, evaluation dataset, workflow or publication setting is changed. Attaching an artifact is permitted only to a local unpublished candidate.

## Reviewed publication contract — activation remains disabled

The frontend understands an optional paired manifest entry:

```json
{
  "matchup_intelligence": "2026/week-9/<new-run>/matchup-intelligence.json",
  "matchup_intelligence_sha256": "<64-character-sha256>"
}
```

The bytes are hash-checked before parsing; schema, board identity/probabilities and sample evidence are then checked. Legacy manifests without the pair cause no sidecar request and show an explicit unpublished state. Old snapshots remain accessible.

The reviewed contract accepts exactly the original three files (`board.json`, `breakdowns.json`, `receipt.json`), or those same files plus the explicitly named `matchup-intelligence.json`. No wildcard allowance is used. A sidecar requires `receipt.matchup_intelligence_sha256` and the paired manifest reference/hash in the same immutable snapshot directory. Unreceipted, missing, altered, symlinked or extra files fail closed. Sidecar bytes are copied exclusively without reserialization, preserving the exact signed hash input.

`matchup_publication.py` centralizes that optional allowlist, manifest fields and validation. It checks the semantic schema, audited identities, unchanged V5 probabilities, complete schedule/player coverage, genuine pregame classification, source fingerprints, actual capture timestamps, generation time, tightening freshness windows and ten-minute kickoff margin. Low statistical sample size is represented explicitly as Insufficient Data; it is not an excuse to omit games, players or mandatory inputs. Retrospective evidence cannot enter a reviewed publication even if its JSON is structurally valid.

An explicit local attachment step is available after building from trusted captured input files:

```powershell
python matchup_cli.py attach --candidate work/my-new-candidate --artifact <new-path>/matchup-intelligence.json
python weekly_pipeline.py validate --candidate work/my-new-candidate
```

Attachment validates before writing, cannot replace an existing sidecar, rejects served paths, and updates only the local candidate receipt. A concurrent or failed attachment may leave a deliberately invalid local candidate; inspect/rebuild it instead of repairing hashes or copying into production. Do not backdate source capture timestamps to make a historical replay eligible.

The existing workflow still generates its original three-file candidate; this change does not turn on sidecar generation, schedules or publishing. Before an approved supervised proposal, an explicitly reviewed producer must supply genuine captured inputs and attach the validated sidecar before the existing candidate upload/review steps. A request for matchup data must fail on unavailable or invalid evidence rather than silently dropping it. Default candidates without a requested sidecar remain supported.

`automation_publish.py` and trusted-base `reviewed_publication.py` use the explicit bundle allowlist. All current-main, exclusivity, branch naming, schedule, manifest-base, draft-PR, no-direct-main-push and human review safeguards remain. Publication PRs contain four changed files without intelligence or five with it, including manifest. Required checks must use a reviewed base containing this extension; do not bypass old-base rejection. No workflow permissions or settings were changed.

`verify_publication.py` additionally checks optional manifest hash pins before network access and hashes every deployed JSON file, including all active and inactive sidecars, after verifying the exact Ready main deployment and production alias. Browser publication smoke checks now open all three intelligence sections when a sidecar is present, and require the honest unpublished state when absent.

Rollback: record the last known good deployment, exact commit and manifest bytes before a supervised merge. If verification fails, stop further proposals. With separate approval, restore the known good Vercel deployment using existing access, then use a human-reviewed `nfl-pm/rollback/<incident>` PR restoring **only** the byte-identical previous main manifest. Retain every board, breakdown, receipt and sidecar, including the failed proposal's immutable bundle. Rerun trusted-base validation and exact-commit/alias/JSON/browser verification after the approved rollback. Tests exercise a manifest-only rollback across a sidecar introduction without deleting the sidecar. No rollback or deployment was invoked here.

## Verification and limitations

Real-source retrospective audit: 2024 Week 10 SF–TB, cutoff 2024-11-06 12:00 UTC. The source filter retained 138 completed games and 16,824 qualifying plays, all before cutoff and target week. SF recent six-game offense: 366 plays, 182 runs / 184 passes, 83 RZ plays and 13 TD drives / 26 RZ drives. TB recent six-game defense: 397 plays, 15 TD drives / 21 RZ drives. These are reproducible retrospective source checks, not newly generated forecasts or evidence of original pregame publication. No evaluation datasets were regenerated.

Deterministic regression fixtures explicitly use TEST FIXTURE player names and warnings, live only under tests/work, and are never served or committed under public/data. Browser screenshots of populated new sections are labeled synthetic. Existing production weeks show the truthful unpublished state until approved data activation. Historical original-vintage uncertainty, current roster pending decisions and source licensing/availability remain constraints on genuine pregame publication.

Fresh read-only recheck on 2026-10-29 reproduced those same 138 games / 16,824 plays. Source origins are nflverse-data release feeds `pbp`, `player_stats`, `rosters_weekly`, `players`, and nfldata `data/games.csv`. Local audit evidence (not production or a fixture forecast) is `work/m7-real-source-audit.json`, with retrieval timestamps, fingerprints and exact sample game IDs. Target SF/TB Week 10 rosters had 28 included, 134 excluded and 5 pending: Mike Evans, Chris Conley, Joshua Dobbs, Brayden Willis and Devin Culp. All pending records were INA; none was silently treated as released or active. This prevents producing a complete roster-verified historical sidecar with the unchanged eligibility policy.

PR #4 was independently read from GitHub: closed/unmerged, 441 players / 14 games, generated 2026-10-28 02:08:09.925157 UTC. Its receipt records real capture times and source fingerprints but no Matchup Intelligence sidecar or archived raw source frames. The older local Week 8 candidates have different timestamps and hashes and are not evidence for PR #4's bytes. Neither that receipt nor a current download proves original 2024 pregame source vintage. Verified historical end-to-end real-data UI evidence remains BLOCKED; populated UI screenshots remain explicitly synthetic regression fixtures. No backdating, eligibility overrides or production fixture data was used.

## Local verification status

- Python: 178 tests passed (36 analytics tests, 18 optional-publication tests and 124 existing tests); Ruff correctness lint (`--select F`) passed for changed Python source/tests. Draft 2020-12 schema compilation and fixture validation passed.
- Frontend: ESLint and 17 Node tests passed. Existing feature and actual published-data compatibility browser suites passed against a local production server. Explicitly labeled-fixture browser checks passed all three new sections, both team directions, exact V5 display, stale suppression, hash/V5/cutoff rejection and 320/390/768/1440px layouts, without runtime errors.
- Existing parlay/market calculations: 200 comparisons identical to main. Published manifest validation passed; all 13 production JSON files remain byte-identical. V5 source, parlay code, evaluation data and workflow files are unchanged.
- Clean Linux production build: approved temporary nonpersistent Vercel Sandbox `sbx_RFY2hARjG9lw37r0WUgX8I5NyI85`, command `cmd_1a1b7538ae0d4e37a00a59faef2c`; Ubuntu/Linux x86_64, actual Node v24.22.1, Next 16.4.3, `npm ci --no-audit --no-fund && npm run build`. Compiled, typechecked and prerendered all 4 pages including `/` and `/_not-found`, then finalized the route table normally. No checks disabled. Warnings: existing ESLint 9 support deprecation and npm install-script policy notice for unrs-resolver. No dependency or configuration changes were made. The temporary sandbox was stopped with persistence disabled and no snapshot requested; the connector confirms it is stopped with no exposed routes. Named sandbox metadata remains visible; the connector does not expose a delete operation.
- Normal Windows `npm run build` subsequently also returned exit code 0, prerendering all pages with five workers. Earlier EPERM was at recursive output-directory creation through Next MultiFileWriter/nodeFs.mkdir. Parent and child Node mkdir checks now pass at that exact path. The initial failure was local/transient; antivirus vs file-lock vs sandbox/ACL interaction is not conclusively distinguishable without host-level tracing. No frontend defect was reproduced and no permissions or essential build checks were weakened. Windows build evidence: `work/m7-windows-build.log`.

## Review and activation gates

This implementation is prepared for a source-code review PR only. Production Matchup Intelligence remains inactive: the published manifest contains no sidecar pins, GitHub Actions does not generate/attach sidecars, and no production data or settings are changed.

Before any separately approved activation:

1. Obtain trusted, timestamped pregame captures of all required raw inputs, preserve those captures and verify their fingerprints. Current downloads and self-entered historical timestamps are not sufficient proof of original vintage.
2. Resolve the five historical INA roster records using authoritative game/week evidence without treating injury or inactive designation as released membership. Alternatively use another fully evidenced historical matchup; do not override the shared eligibility policy.
3. Complete the real-data end-to-end UI verification and source traceability review. Synthetic tests establish behavior only and are never production artifacts.
4. Separately review any hosted producer/attachment integration, requiring explicit requested-sidecar failure on unavailable data; retain current opt-ins, protected main environment, data-only draft PRs, immutable archives, strict required checks and fresh premerge validation.
5. Obtain explicit approval before a supervised publication proposal, human merge, deployment verification or rollback. This source PR does not grant those approvals.

Local caches, screenshots, candidate data and audit logs are verification evidence only and are excluded from the source PR. No production merge, deployment or publication activation is authorized here.

## Implementation file inventory

Python (new): `matchup_intelligence.py`, `matchup_schema.py`, `matchup_cli.py`, `test_matchup_intelligence.py`, `matchup_publication.py`, `test_matchup_publication.py`.

Frontend: `td-predictor-web/app/page.tsx`, `app/page.module.css`, `components/game-breakdown.tsx`, new `components/matchup-intelligence.tsx`, new `lib/matchup-contract.ts`, `lib/data.ts`, `lib/types.ts`, `scripts/browser-smoke.mjs`, new `scripts/matchup.test.mjs`, new `scripts/matchup-smoke.mjs`, and `scripts/publication-smoke.mjs` (all paths under `td-predictor-web`).

Contract/documentation: `schemas/matchup-intelligence.schema.json`, this document, and `README.md`. Publication support (modified): `weekly_storage.py`, `reviewed_publication.py`, `automation_publish.py`, `verify_publication.py`. No files in the published data tree, V5 model, parlay calculations, evaluation datasets or workflow configuration were changed.

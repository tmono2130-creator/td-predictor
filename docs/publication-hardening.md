# Milestone 5D publication hardening

The reviewed weekly publication pipeline is the supported live-manifest update path. Legacy `export_json.py` requires an explicit local preview directory and rejects both live data roots and their descendants. The strict staging helper additionally requires the uniquely named reviewed-publication branch for live staging; historical candidates cannot be staged into live data. GitHub approval gates, draft data-only PR checks, and merge protections remain necessary. These development guards do not replace repository permissions.

## Roster policy

`roster_eligibility.py` resolves membership independently of injury designation and game-day activation. Exact target-season/week regular-season roster records take precedence. Current-season fallback records cannot describe a future week; historical runs require target-week records. Only scheduled teams enter identity validation. Active skill-position players, including rookies with no statistics, remain eligible. Explicit released, retired, reserve, and development statuses are excluded. Inactive, unknown, conflicting, or incomplete records produce an auditable pending decision and stop generation instead of silently including or dropping players.

Known authoritative GSIS IDs are required, or at least two independent stable external identifiers must corroborate the same GSIS identity. Names alone never join identities. The receipt records eligibility decisions and counts; validation checks included identities against the candidate pool. Legacy receipts without this new audit remain readable without rewriting their immutable files.

## Outcome policy

Serializers discard unverified legacy boolean annotations. Forecast outcomes remain null for upcoming/live games and when evidence is missing. A completed-game boolean requires explicit verified, complete evidence with a valid nonnegative integral touchdown count. Missing, malformed, boolean, negative, fractional, or nonfinite historical touchdown fields cannot become confirmed negatives. Historical snap participants without outcome evidence remain unknown and are excluded from future evaluation labels. PFR rows are no longer reassigned to GSIS players by name. Existing evaluation datasets were not regenerated.

## Compatibility and verification

Local legacy previews retain their compatibility candidate engine and are not publication candidates. Use `--out work/local-preview`; strict local transaction tests use a separate non-live `--data` directory. Internal legacy model annotations are not verified outcome evidence. Model source, formulas, weights, parlay calculations, UI, production manifest, and existing snapshots remain unchanged. Freshness, kickoff margin, provenance, timestamp, receipt, hash, and immutable-write checks remain enforced.

The V5 regression pins the reviewed model source and identical-input scores for an identical eligible pool. Eligibility changes can intentionally alter which players appear; they do not alter the scoring formula.

## Week 9 correction prerequisites

The read-only current-source diagnostic found 462 included records and 10 pending inactive-status skill players across scheduled teams. Target-week roster records were unavailable, so live-season fallback was used. Resolve these records using authoritative week/game-specific evidence before a correction proposal; do not guess membership or bypass the pending gate. A source refresh may change this diagnostic. A future proposal also requires fresh inputs, adequate kickoff margin, and all existing review checks. No predictions or correction proposal were generated during this implementation.

No schedules, publishing opt-ins, credentials, repository settings, or workflows were activated. Commit, push, hosted validation, and any publication require separate authorization.

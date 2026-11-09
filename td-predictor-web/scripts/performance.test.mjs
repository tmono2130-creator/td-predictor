import test from 'node:test';
import assert from 'node:assert/strict';
import {isEvaluationIndex,validateEvaluation,decodeEvaluation} from '../lib/performance.ts';
function provenance(){
 const asOf='2026-11-09T19:00:00Z';
 const sources=Object.fromEntries(['schedule','stats_2026','pbp_2026'].map(key=>[key,{available:true,path:key+(key==='schedule'?'.csv':'.parquet'),url:'https://example.invalid/TEST-ONLY/'+key,sha256:'d'.repeat(64),bytes:1,started_at_utc:asOf,retrieved_at_utc:asOf,provider_modified_utc:null}]));
 return {kind:'live_capture',git_revision:'e'.repeat(40),code_sha256:{'TEST-ONLY.py':'f'.repeat(64)},dependencies:{python:'TEST-ONLY'},started_at_utc:asOf,source_cutoff_utc:asOf,sources};
}
export function fixture(){
 const gid='2026_09_BUF_MIN';const metrics={n:0,winner_accuracy:null,team_score_mae:null,total_mae:null,margin_mae:null};const td={n:0,positives:0,brier:null,log_loss:null,auc:null,calibration:[]};
 return {schema_version:1,evaluation_id:'a'.repeat(24),engine_sha256:'f'.repeat(64),outcome_sources:provenance(),season:2026,week:9,status:'partial',evaluated_as_of:'2026-11-09T19:00:00Z',forecast_generated_at:'2026-11-05T20:00:00Z',forecast_hashes:{'board.json':'b'.repeat(64),'receipt.json':'c'.repeat(64)},games_completed:0,games_pending:1,game_metrics:metrics,baseline_metrics:metrics,td_metrics:td,position_metrics:{QB:td,RB:td,WR:td,TE:td},missing_labels:{pending_game:1},limitations:['TEST FIXTURE; not production'],games:[{game_id:gid,away_team:'BUF',home_team:'MIN',kickoff_utc:'2026-11-10T01:15:00Z',status:'pending',prediction:{away:22,home:21},actual:null}],players:[{game_id:gid,player_id:'00-0000001',player:'TEST ONLY',team:'BUF',position:'QB',estimate_pct:20,actual_td:null,outcome_reason:'pending_game'}]};
}
test('strict safe index and missing empty index',()=>{
 const entry={season:2026,week:9,path:'a'.repeat(24)+'/evaluation.json',sha256:'b'.repeat(64)};
 assert(isEvaluationIndex({schema_version:1,reports:[]}));assert(isEvaluationIndex({schema_version:1,reports:[entry]}));
 for(const path of ['../evaluation.json','https://example.com/x.json','/data/manifest.json'])assert(!isEvaluationIndex({schema_version:1,reports:[{...entry,path}]}));
 assert(!isEvaluationIndex({schema_version:1,reports:[entry,entry]}));
});
const asOf=Date.parse('2026-11-09T19:00:01Z');
test('valid original pending outcomes remain nullable',()=>assert.equal(validateEvaluation(fixture(),2026,9,asOf),null));
test('future evaluation capture cannot imply verified final outcomes',()=>assert.notEqual(validateEvaluation(fixture(),2026,9,asOf-2000),null));
for(const [name,edit] of [
 ['premature outcome',r=>r.players[0].actual_td=false],['fake final',r=>r.status='complete'],['wrong coverage',r=>r.td_metrics.n=1],
 ['changed team',r=>r.players[0].team='JAX'],['duplicate identity',r=>r.players.push(r.players[0])],['unsupported probability',r=>r.players[0].estimate_pct=101],
 ['missing provenance',r=>delete r.forecast_hashes['board.json']],['post-kickoff prediction',r=>r.forecast_generated_at='2026-11-10T01:16:00Z'],['NaN metric',r=>r.game_metrics.total_mae=NaN]
])test('reject '+name,()=>{const r=fixture();edit(r);assert.notEqual(validateEvaluation(r,2026,9,asOf),null)});
test('exact content hash required',async()=>{
 const bytes=new TextEncoder().encode(JSON.stringify(fixture()));
 await assert.rejects(()=>decodeEvaluation(bytes.buffer,'0'.repeat(64)),/hash mismatch/);
 const pin=Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))).map(n=>n.toString(16).padStart(2,'0')).join('');
 assert.deepEqual(await decodeEvaluation(bytes.buffer,pin),fixture());
});

function completed(){
 const r=fixture(),g=r.games[0];g.game_id='2026_09_JAX_BAL';g.away_team='JAX';g.home_team='BAL';g.kickoff_utc='2026-11-06T01:15:00Z';g.status='final';g.prediction={away:21,home:24};g.actual={away:20,home:27};g.prior_offensive_mean={away:21,home:24};
 r.status='complete';r.games_completed=1;r.games_pending=0;r.missing_labels={};
 r.players=[{...r.players[0],game_id:g.game_id,team:'JAX',actual_td:false,outcome_reason:'verified_stats_and_complete_pbp'}, {...r.players[0],game_id:g.game_id,player_id:'00-0000002',team:'BAL',estimate_pct:80,actual_td:true,outcome_reason:'verified_stats_and_complete_pbp'}];
 r.game_metrics={n:1,winner_accuracy:1,team_score_mae:2,total_mae:2,margin_mae:4};r.baseline_metrics=structuredClone(r.game_metrics);
 r.td_metrics={n:2,positives:1,brier:.04,log_loss:-Math.log(.8),auc:1,calibration:[{lower_pct:20,upper_pct:30,n:1,mean_estimate_pct:20,observed_pct:0},{lower_pct:80,upper_pct:90,n:1,mean_estimate_pct:80,observed_pct:100}]};
 r.position_metrics.QB=structuredClone(r.td_metrics);
 r.top_per_game={'5':{selected:2,labelled:2,hits:1,hit_rate:.5}};
 r.margin_bands={'3_to_under_7':structuredClone(r.game_metrics)};return r;
}
test('recompute valid labelled, calibration, ranking and score metrics',()=>assert.equal(validateEvaluation(completed(),2026,9,asOf),null));
for(const [name,edit] of [
 ['reported zero Brier',r=>r.td_metrics.brier=0],['fabricated AUC',r=>r.td_metrics.auc=.5],
 ['log loss',r=>r.td_metrics.log_loss=0],['winner rate',r=>r.game_metrics.winner_accuracy=0],
 ['score error',r=>r.game_metrics.team_score_mae=0],['baseline errors',r=>r.baseline_metrics.total_mae=0],
 ['game metric count',r=>r.game_metrics.n=2],['calibration mean',r=>r.td_metrics.calibration[0].mean_estimate_pct=21],
 ['calibration observations',r=>r.td_metrics.calibration[0].observed_pct=100],['missing calibration',r=>r.td_metrics.calibration=[]],
 ['position arithmetic',r=>r.position_metrics.QB.brier=0],['missing position',r=>delete r.position_metrics.TE],
 ['ranking coverage',r=>r.top_per_game['5'].selected=3],['ranking rate',r=>r.top_per_game['5'].hit_rate=1],
 ['margin band',r=>r.margin_bands['3_to_under_7'].total_mae=0],['unknown outcome counts',r=>r.missing_labels={missing_player_stat_evidence:1}],
 ['unsupported schema',r=>r.schema_version=2],['missing engine',r=>delete r.engine_sha256],
 ['missing outcome provenance',r=>delete r.outcome_sources],['missing source',r=>delete r.outcome_sources.sources.pbp_2026],
 ['unavailable source',r=>r.outcome_sources.sources.pbp_2026.available=false],['invalid source hash',r=>r.outcome_sources.sources.schedule.sha256='bad'],
 ['wrong outcome cutoff',r=>r.outcome_sources.source_cutoff_utc='2026-11-09T18:00:00Z'],
 ['source after cutoff',r=>r.outcome_sources.sources.schedule.retrieved_at_utc='2026-11-09T20:00:00Z'],
 ['future provider timestamp',r=>r.outcome_sources.sources.schedule.provider_modified_utc='2026-11-09T20:00:00Z'],
 ['negative loss',r=>r.td_metrics.log_loss=-1],['AUC outside range',r=>r.td_metrics.auc=1.01],['nonfinite score',r=>r.game_metrics.margin_mae=Infinity],
 ['incorrect final count',r=>r.games_completed=2],['final without scores',r=>r.games[0].actual=null]
])test('reject inconsistent report: '+name,()=>{const r=completed();edit(r);assert.notEqual(validateEvaluation(r,2026,9,asOf),null)});
test('reject exact diagnostic manipulation even when hashes would be recalculated',()=>{const r=completed();r.td_metrics.brier=0;r.td_metrics.auc=1;r.game_metrics.winner_accuracy=1;delete r.outcome_sources;assert.notEqual(validateEvaluation(r,2026,9,asOf),null)});
test('valid empty sample requires null metrics',()=>{const r=fixture();r.td_metrics.brier=0;assert.notEqual(validateEvaluation(r,2026,9,asOf),null)});

test('tie-aware AUC and single-class null AUC agree with observations',()=>{
 const r=completed();r.players[1].estimate_pct=20;r.td_metrics={n:2,positives:1,brier:.34,log_loss:-(Math.log(.2)+Math.log(.8))/2,auc:.5,calibration:[{lower_pct:20,upper_pct:30,n:2,mean_estimate_pct:20,observed_pct:50}]};r.position_metrics.QB=structuredClone(r.td_metrics);assert.equal(validateEvaluation(r,2026,9,asOf),null);
 r.players[1].actual_td=false;r.td_metrics={n:2,positives:0,brier:.04,log_loss:-Math.log(.8),auc:null,calibration:[{lower_pct:20,upper_pct:30,n:2,mean_estimate_pct:20,observed_pct:0}]};r.position_metrics.QB=structuredClone(r.td_metrics);r.top_per_game['5'].hits=0;r.top_per_game['5'].hit_rate=0;assert.equal(validateEvaluation(r,2026,9,asOf),null);
 r.td_metrics.auc=0;assert.notEqual(validateEvaluation(r,2026,9,asOf),null);
});
test('untrusted observations can be arithmetically consistent; validation is not external verification',()=>{
 const r=completed();r.outcome_sources.sources.schedule.url='https://example.invalid/UNVERIFIED';assert.equal(validateEvaluation(r,2026,9,asOf),null);
 // Only authenticated evidence review can establish the factual truth of a captured source.
});

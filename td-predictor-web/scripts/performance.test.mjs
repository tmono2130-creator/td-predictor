import test from 'node:test';
import assert from 'node:assert/strict';
import {isEvaluationIndex,validateEvaluation,decodeEvaluation} from '../lib/performance.ts';
export function fixture(){
 const gid='2026_09_BUF_MIN';const metrics={n:0,winner_accuracy:null,team_score_mae:null,total_mae:null,margin_mae:null};const td={n:0,positives:0,brier:null,log_loss:null,auc:null,calibration:[]};
 return {schema_version:1,evaluation_id:'a'.repeat(24),season:2026,week:9,status:'partial',evaluated_as_of:'2026-11-09T19:00:00Z',forecast_generated_at:'2026-11-05T20:00:00Z',forecast_hashes:{'board.json':'b'.repeat(64),'receipt.json':'c'.repeat(64)},games_completed:0,games_pending:1,game_metrics:metrics,baseline_metrics:metrics,td_metrics:td,position_metrics:{QB:td},missing_labels:{pending_game:1},limitations:['TEST FIXTURE; not production'],games:[{game_id:gid,away_team:'BUF',home_team:'MIN',kickoff_utc:'2026-11-10T01:15:00Z',status:'pending',prediction:{away:22,home:21},actual:null}],players:[{game_id:gid,player_id:'00-0000001',player:'TEST ONLY',team:'BUF',position:'QB',estimate_pct:20,actual_td:null,outcome_reason:'pending_game'}]};
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

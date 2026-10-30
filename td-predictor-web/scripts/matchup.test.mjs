// Explicit synthetic contract fixtures. Never served from public/data.
import test from 'node:test';
import assert from 'node:assert/strict';
import { isManifest } from '../lib/data.ts';
import { decodeMatchup, matchupValidationError, matchupFreshness } from '../lib/matchup-contract.ts';
const time='2099-10-30T12:00:00Z';
const profile=()=>({games:0,game_ids:[],plays:0,run_plays:0,pass_plays:0,run_rate:null,plays_per_game:null,rz_plays:0,rz_runs:0,rz_passes:0,rz_run_rate:null,goal_line_opportunities:0,rush_tds:0,pass_tds:0,rz_trips:0,rz_td_drives:0,rz_td_rate:null,yards:0,yards_per_play:null,epa_per_play:null,epa_sample:0,success_rate:null,position_td_exclusions:0,position_identity_matched:0,position_identity_total:0,position_identity_coverage:null,field_position_sample:0,drive_sample:0});
const positions=()=>['QB','RB','WR','TE'].map(position=>({position,opportunities:0,targets:0,carries:0,tds:0,rz_opportunities:0,rz_tds:0,td_rate:null,rz_td_rate:null,yards:0,yards_per_opportunity:null}));
function fixture(){
 const game_id='2099_09_SF_WAS',kickoff_utc='2099-11-03T18:00:00Z';
 const board={season:2099,week:9,generated_at:time,games:[{game_id,home_team:'WAS',away_team:'SF',kickoff_utc}]};
 const rows=['SF','WAS'].map((team,i)=>({player_id:`00-300000${i+1}`,player:`TEST FIXTURE ${team}`,team,opponent:team==='SF'?'WAS':'SF',position:'TE',game_id,td_estimate:25.123}));
 const source_as_of=Object.fromEntries(['schedule','pbp','player_games','weekly_rosters','players'].map(k=>[k,time]));
 const policy={min_games:4,min_player_opportunities:10,min_player_rz:3,min_defense_position_rz:12,min_league_position_rz:100,min_identity_coverage:.95,wilson_z:1.96,relative_rate_threshold:.25,min_absolute_rate_gap:.05,min_player_rz_share:.15};
 const usages=rows.map(r=>({player_id:r.player_id,player:r.player,team:r.team,position:'TE',targets:0,carries:0,opportunities:0,rz_targets:0,rz_carries:0,rz_opportunities:0,goal_line_opportunities:0,target_share:null,carry_share:null,rz_share:null,team_targets:0,team_carries:0,team_rz_opportunities:0,snap_participation_pct:null,snap_sample_games:0}));
 const artifact={meta:{schema_version:1,methodology_version:'matchup-v1',season:2099,week:9,board_generated_at:time,data_as_of:time,generated_at:time,evidence_mode:'pregame_snapshot',source_as_of,source_fingerprints:Object.fromEntries(Object.keys(source_as_of).map(k=>[k,'a'.repeat(64)])),policy,roster_audit:{policy_version:'week-aware-v1',season:2099,week:9,counts:{include:2,exclude:0,pending:0},decisions:rows.map(r=>({...r,roster_status:'ACT',decision:'include'}))},input_games:[],limitations:['TEST FIXTURE — not NFL data']},games:{}};
 const game={game_id,home_team:'WAS',away_team:'SF',kickoff_utc,offenses:{},defenses:{},recommendations:[]};
 for(const r of rows){const p=usages.find(p=>p.player_id===r.player_id);game.offenses[r.team]={recent:profile(),season:profile(),trend:profile(),players:[p],personnel:null};game.defenses[r.team]={recent:profile(),season:profile(),trend:profile(),positions:positions(),league:{sample:profile(),positions:positions()},opponent_adjustment:null};game.recommendations.push({...p,opponent:r.opponent,game_id,v5_probability_pct:r.td_estimate,advantage:'Insufficient Data',explanation:['No observed sample'],defense_position:positions()[3],league_position:positions()[3],offense_games:0,defense_games:0});}
 artifact.games[game_id]=game;return {artifact,board,rows,game};
}
test('strict matchup contract accepts explicit insufficient data',()=>{const f=fixture();assert.equal(matchupValidationError(f.artifact,f.board,f.rows),null)});
for(const [label,mutate] of [
 ['V5 probability mutation',f=>f.game.recommendations[0].v5_probability_pct=99],
 ['future sample',f=>f.artifact.meta.input_games=[{game_id:'2099_09_SF_WAS',week:9,kickoff_utc:'2099-11-03T18:00:00Z'}]],
 ['post-cutoff source',f=>f.artifact.meta.source_as_of.pbp='2099-11-01T00:00:00Z'],
 ['forged favorable label',f=>f.game.recommendations[0].advantage='Favorable'],
 ['wrong game team',f=>f.game.home_team='KC'],
 ['invalid denominator',f=>f.game.offenses.SF.recent.run_rate=.5],
 ['nonfinite metric',f=>f.game.defenses.SF.positions[0].yards=Infinity],
 ['unsupported personnel',f=>f.game.offenses.SF.personnel={'11':.8}],
 ['unresolved roster',f=>f.artifact.meta.roster_audit.counts.pending=1],
 ['incomplete player usage',f=>{f.game.offenses.SF.players=[];f.game.recommendations.shift()}],
 ['unknown schema',f=>f.artifact.meta.schema_version=2]
])test(`rejects ${label}`,()=>{const f=fixture();mutate(f);assert.notEqual(matchupValidationError(f.artifact,f.board,f.rows),null)});
test('hash binding rejects tampered artifact bytes',async()=>{const bytes=new TextEncoder().encode(JSON.stringify(fixture().artifact));const hash=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');assert.deepEqual(await decodeMatchup(bytes.buffer,hash),fixture().artifact);await assert.rejects(()=>decodeMatchup(bytes.buffer,'0'.repeat(64)),/hash mismatch/)});
test('freshness distinguishes current, stale and retrospective evidence',()=>{const f=fixture();assert.equal(matchupFreshness(f.artifact.meta,f.game,Date.parse(time)),'Within analysis freshness window');assert.match(matchupFreshness(f.artifact.meta,f.game,Date.parse('2099-11-02T12:00:00Z')),/Stale/);f.artifact.meta.evidence_mode='retrospective_analysis';assert.match(matchupFreshness(f.artifact.meta,f.game,Date.parse(time)),/Retrospective/)});

test('legacy manifests need no sidecar while future references require a safe path/hash pair',()=>{const m={schema_version:1,supported_weeks:[9],seasons:{2099:{weeks:{9:{board:'2099/week-9/run/board.json',breakdowns:null,generated_at:time,model:'composite'}}}}};assert(isManifest(m));const e=m.seasons[2099].weeks[9];e.matchup_intelligence='2099/week-9/run/matchup-intelligence.json';assert(!isManifest(m));e.matchup_intelligence_sha256='a'.repeat(64);assert(isManifest(m));e.matchup_intelligence='../outside.json';assert(!isManifest(m));});

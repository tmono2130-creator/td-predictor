import test from 'node:test';
import assert from 'node:assert/strict';
import {validateGameArtifact,decodeGameArtifact,gameFreshness} from '../lib/game-projection.ts';
function fixture(){
 const time='2026-09-09T12:00:00Z',gid='2026_01_KC_BUF';
 const schedule=[{game_id:gid,home_team:'BUF',away_team:'KC',kickoff_utc:'2026-09-11T00:15:00Z'}];
 const summary=()=>({games:4,game_ids:[15,16,17,18].map(w=>`2025_${w}_KC_BUF`),last_kickoff_utc:'2025-12-04T18:00:00Z',offensive_points:96,offensive_plays:240,allowed_points:84,defensive_plays:256,offensive_ppp:.4,defensive_ppp_allowed:84/256,plays_per_game:60,plays_faced_per_game:64,red_zone_drives_per_game:3});
 const expected_ppp=(.4+84/256)/2,baseline=expected_ppp*62;
 const teams=Object.fromEntries(['KC','BUF'].map(t=>[t,{summary:summary(),opponent_defensive_ppp:84/256,expected_plays:62,expected_ppp,baseline,features:[baseline,.4,84/256,62,t==='BUF'?1:0]}]));
 const value={meta:{schema_version:1,model_version:'game-ppp-v1',season:2026,week:1,generated_at:time,data_cutoff:time,classification:'pregame_snapshot',sources:Object.fromEntries(['schedule','team_games'].map(k=>[k,{as_of:time,sha256:'a'.repeat(64),origin:'https://example.invalid/TEST-FIXTURE'}])),model:null,model_sha256:null,primary_method:'baseline',warnings:['TEST FIXTURE']},games:{[gid]:{...schedule[0],status:'available',teams,methods:{baseline:{scores:{KC:baseline,BUF:baseline},home_margin:0,total:baseline*2,favored:null,win_probability:null}},warnings:[]}}};
 return {value,schedule,g:value.games[gid],time};
}
test('valid baseline preserves full precision, schedule and no probabilities',()=>{const f=fixture();assert.equal(validateGameArtifact(f.value,f.schedule,2026,1),null);});
for(const [name,change] of [
 ['unsupported probability',f=>f.g.methods.baseline.win_probability=.8],
 ['changed score',f=>f.g.methods.baseline.scores.KC=99],
 ['wrong schedule',f=>f.g.away_team='SF'],
 ['target game leakage',f=>f.g.teams.KC.summary.game_ids[0]=f.g.game_id],
 ['post-cutoff capture',f=>f.value.meta.sources.team_games.as_of='2026-09-10T12:00:00Z'],
 ['invalid pace',f=>f.g.teams.KC.expected_plays=100],
 ['string score',f=>f.g.methods.baseline.scores.KC='20'],
 ['string statistic',f=>f.g.teams.KC.summary.offensive_ppp='0.4'],
 ['nonfinite data',f=>f.g.methods.baseline.total=Infinity],
 ['wrong schema',f=>f.value.meta.schema_version=2],
 ['invented winner',f=>f.g.methods.baseline.favored='KC'],
 ['unverified adjusted method',f=>f.g.methods.adjusted=structuredClone(f.g.methods.baseline)]
])test('rejects '+name,()=>{const f=fixture();change(f);assert.notEqual(validateGameArtifact(f.value,f.schedule,2026,1),null);});
test('freshness suppresses stale or near-kickoff forecasts but labels archives',()=>{const f=fixture();assert.match(gameFreshness(f.value,f.g,Date.parse(f.time)),/^Pregame/);assert.match(gameFreshness(f.value,f.g,Date.parse(f.time)+86400000),/stale/);assert.match(gameFreshness(f.value,f.g,Date.parse(f.g.kickoff_utc)-300000),/margin/);f.value.meta.classification='retrospective_analysis';assert.match(gameFreshness(f.value,f.g,Date.parse(f.time)),/^Retrospective/);});
test('artifact SHA256 must match manifest pin',async()=>{const bytes=new TextEncoder().encode(JSON.stringify(fixture().value));await assert.rejects(()=>decodeGameArtifact(bytes.buffer,'0'.repeat(64)),/hash mismatch/);const pin=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');assert.deepEqual(await decodeGameArtifact(bytes.buffer,pin),fixture().value);});

test('exact kickoff and six-hour freshness boundaries fail closed',()=>{
 const f=fixture(),start=Date.parse(f.g.kickoff_utc),now=start-6*3600000;
 f.value.meta.generated_at=new Date(now-1800000+1).toISOString();
 f.value.meta.data_cutoff=f.value.meta.generated_at;
 for(const source of Object.values(f.value.meta.sources))source.as_of=f.value.meta.generated_at;
 assert.equal(gameFreshness(f.value,f.g,now),'Pregame data within freshness window');
 assert.equal(gameFreshness(f.value,f.g,now+1),'Unavailable — stale source data');
 assert.equal(gameFreshness(f.value,f.g,start-600000),'Unavailable — kickoff safety margin exhausted');
 assert.equal(gameFreshness(f.value,f.g,start),'Archived forecast — kickoff has passed');
});

test('48-hour transition immediately applies the six-hour source limit',()=>{
 const f=fixture(),start=Date.parse(f.g.kickoff_utc),boundary=start-48*3600000;
 f.value.meta.generated_at=new Date(boundary-7*3600000).toISOString();
 f.value.meta.data_cutoff=f.value.meta.generated_at;
 for(const source of Object.values(f.value.meta.sources))source.as_of=f.value.meta.generated_at;
 assert.equal(gameFreshness(f.value,f.g,boundary-1),'Pregame data within freshness window');
 assert.equal(gameFreshness(f.value,f.g,boundary),'Unavailable — stale source data');
});

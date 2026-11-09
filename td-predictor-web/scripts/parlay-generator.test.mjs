import test from 'node:test';
import assert from 'node:assert/strict';
import {generateParlays} from '../lib/parlay-generator.ts';
const now=Date.parse('2026-11-05T20:00:00Z');
const games=Array.from({length:8},(_,i)=>({game_id:'g'+i,kickoff_utc:new Date(now+2*3600000).toISOString()}));
const rows=Array.from({length:80},(_,i)=>({player_id:'p'+i,game_id:'g'+(i%8),td_estimate:1+i*.5,game_status:'Upcoming',injury_status:'Unknown'}));
const options={legs:3,count:20,mode:'balanced',maxExposure:.3,crossGame:true,seed:'REPRODUCIBLE TEST ONLY',games,generatedAt:new Date(now-60000).toISOString(),now};
test('seed reproducibility, uniqueness, exposure and immutability',()=>{
 const before=structuredClone(rows),r=generateParlays(rows,options);
 assert.deepEqual(r,generateParlays(rows,options));assert.deepEqual(rows,before);
 assert.equal(r.combinations.length,20);assert.equal(r.warning,null);
 assert.equal(new Set(r.combinations.map(ids=>[...ids].sort().join('|'))).size,20);
 assert(Object.values(r.exposure).every(n=>n<=6));assert(Object.keys(r.exposure).length>=10);
 for(const ids of r.combinations)assert.equal(new Set(ids.map(id=>rows.find(p=>p.player_id===id).game_id)).size,3);
 assert.notDeepEqual(r.combinations,generateParlays(rows,{...options,seed:'different'}).combinations);
});
for(const legs of [2,3,4,5])for(const count of [10,20,30])test(`${legs} legs and ${count} combinations`,()=>{
 const r=generateParlays(rows,{...options,legs,count});assert.equal(r.combinations.length,count);assert(r.combinations.every(ids=>ids.length===legs));
 assert(Object.values(r.exposure).every(n=>n<=Math.floor(count*.3)));
});
test('confirmed unavailable excluded, Unknown retained, game scope enforced',()=>{
 const changed=structuredClone(rows);changed[0].injury_status='Out';changed[1].injury_status='IR';changed[2].game_day_status='inactive';changed[3].roster_eligibility='ineligible';changed[4].roster_eligibility='pending';
 const r=generateParlays(changed,{...options,games:games.slice(0,4),crossGame:false,maxExposure:1});
 assert(r.combinations.flat().every(id=>!['p0','p1','p2','p3','p4'].includes(id)));
 assert(r.combinations.flat().every(id=>Number(id.slice(1))%8<4));assert(r.eligible>0);
});
test('stale, kickoff boundary and future timestamps fail safely',()=>{
 for(const time of [now+600000,now])assert.throws(()=>generateParlays(rows,{...options,games:games.map(g=>({...g,kickoff_utc:new Date(time).toISOString()}))}),/Not enough/);
 assert.throws(()=>generateParlays(rows,{...options,generatedAt:new Date(now-1800000).toISOString()}),/Not enough/);
 assert.throws(()=>generateParlays(rows,{...options,generatedAt:new Date(now+1).toISOString()}),/future/);
});
test('impossible request is explicit and never relaxes constraints',()=>{
 assert.throws(()=>generateParlays(rows,{...options,maxExposure:.01}),/Exposure/);
 assert.throws(()=>generateParlays(rows.slice(0,3),options),/Not enough/);
 assert.throws(()=>generateParlays([...rows,rows[0]],options),/Duplicate/);
 assert.throws(()=>generateParlays(rows.slice(0,2),{...options,legs:2,count:10,crossGame:false,maxExposure:1}),/no partial batch/);
});
test('mode weighting changes selection in the declared direction',()=>{
 const means={};
 for(const mode of ['high-estimate','balanced','long-shot']){
  let total=0,n=0;
  for(let seed=0;seed<20;seed++)for(const ids of generateParlays(rows,{...options,mode,legs:2,count:10,maxExposure:1,seed:String(seed)}).combinations)for(const id of ids){total+=rows.find(r=>r.player_id===id).td_estimate;n++;}
  means[mode]=total/n;
 }
 assert(means['high-estimate']>means.balanced);assert(means.balanced>means['long-shot']);
});

// Compare every published week against reviewed base math. Temporary files only.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {pathToFileURL, fileURLToPath} from 'node:url';
import * as current from '../lib/parlay.ts';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'../..');
const temporary=path.resolve(process.env.RUNNER_TEMP||path.join(root,'work'));
fs.mkdirSync(temporary,{recursive:true});
const folder=fs.mkdtempSync(path.join(temporary,'calculation-regression-'));
try{
 const baselineFile=path.join(folder,'baseline.ts');
 fs.writeFileSync(baselineFile,execFileSync('git',['show',`${process.env.CALCULATION_BASE||'origin/main'}:td-predictor-web/lib/parlay.ts`],{cwd:root}));
 const baseline=await import(pathToFileURL(baselineFile).href);
 const data=path.join(root,'td-predictor-web/public/data');
 const manifest=JSON.parse(fs.readFileSync(path.join(data,'manifest.json'),'utf8'));
 const outcome=fn=>{try{return {value:fn()};}catch(e){return {error:e.message};}};
 let comparisons=0;
 for(const season of Object.values(manifest.seasons))for(const files of Object.values(season.weeks)){
  const rows=JSON.parse(fs.readFileSync(path.join(data,files.board),'utf8')).rows;
  assert.deepEqual(current.eligiblePool(rows),baseline.eligiblePool(rows));comparisons++;
  for(let nLegs=2;nLegs<=6;nLegs++)for(const onePerTeam of [true,false]){
   assert.deepEqual(current.getVolatilityCutoffs(rows,nLegs,onePerTeam),baseline.getVolatilityCutoffs(rows,nLegs,onePerTeam));comparisons++;
   for(const target of current.VOLATILITY_ORDER){const opts={nLegs,onePerTeam,target,rng:()=>.35};assert.deepEqual(outcome(()=>current.autoBuildParlay(rows,opts)),outcome(()=>baseline.autoBuildParlay(rows,opts)));comparisons++;}
   const ids=current.eligiblePool(rows).slice(0,nLegs).map(p=>p.player_id);
   assert.deepEqual(current.parlayProbability(rows,ids),baseline.parlayProbability(rows,ids));comparisons++;
  }
 }
 for(const odds of ['+150','-120','+100','-100','+1000','-1000','','bad','0']){assert.equal(current.impliedProbFromAmericanOdds(odds),baseline.impliedProbFromAmericanOdds(odds));comparisons++;}
 for(const probability of [0,.1,1,25,50,75,99.9,100]){assert.equal(current.fairAmericanOdds(probability),baseline.fairAmericanOdds(probability));comparisons++;}
 assert(comparisons>=200);
 console.log(`PASS ${comparisons} unchanged parlay/Market calculation comparisons`);
}finally{
 fs.rmSync(path.join(folder,'baseline.ts'),{force:true});fs.rmdirSync(folder);
}

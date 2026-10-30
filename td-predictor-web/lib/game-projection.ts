import type { ScheduledGame } from "./types";
export type TeamSummary={games:number;game_ids:string[];last_kickoff_utc:string;offensive_points:number;offensive_plays:number;allowed_points:number;defensive_plays:number;offensive_ppp:number;defensive_ppp_allowed:number;plays_per_game:number;plays_faced_per_game:number;red_zone_drives_per_game:number};
export type TeamProjection={summary:TeamSummary;opponent_defensive_ppp:number;expected_plays:number;expected_ppp:number;baseline:number;features:number[]};
export type ScoreProjection={scores:Record<string,number>;home_margin:number;total:number;favored:string|null;win_probability:null};
export type GameProjection={game_id:string;home_team:string;away_team:string;kickoff_utc:string;status:"available"|"insufficient_data";teams:Record<string,TeamProjection>;methods:Record<string,ScoreProjection>;warnings:string[]};
export type GameArtifact={meta:{schema_version:1;model_version:string;season:number;week:number;generated_at:string;data_cutoff:string;classification:"pregame_snapshot"|"retrospective_analysis";sources:Record<string,{as_of:string;sha256:string;origin:string}>;model:unknown;model_sha256:string|null;primary_method:"baseline";warnings:string[]};games:Record<string,GameProjection>};
const record=(v:unknown):v is Record<string,unknown>=>!!v&&typeof v==="object"&&!Array.isArray(v);
const date=(s:unknown):s is string=>typeof s==="string"&&/(?:Z|[+-]\d{2}:\d{2})$/.test(s)&&Number.isFinite(Date.parse(s));
const finite=(v:unknown):boolean=>typeof v==="number"?Number.isFinite(v):Array.isArray(v)?v.every(finite):record(v)?Object.values(v).every(finite):v===null||typeof v==="string"||typeof v==="boolean";
function check(ok:unknown,message:string):asserts ok{if(!ok)throw new Error(message);}
export function validateGameArtifact(value:unknown,games:ScheduledGame[],season:number,week:number):string|null{
 try{
 check(record(value)&&record(value.meta)&&record(value.games)&&finite(value),"Malformed game projection JSON");const a=value as GameArtifact,m=a.meta;
 check(m.schema_version===1&&m.model_version==="game-ppp-v1"&&m.season===season&&m.week===week&&m.primary_method==="baseline","Wrong game model/week");
 check(date(m.generated_at)&&date(m.data_cutoff)&&Date.parse(m.data_cutoff)<=Date.parse(m.generated_at),"Invalid game timestamps");
 check(["pregame_snapshot","retrospective_analysis"].includes(m.classification)&&Array.isArray(m.warnings)&&record(m.sources),"Missing game provenance");
 check(Object.keys(m.sources).sort().join() === "schedule,team_games","Missing game sources");
 for(const s of Object.values(m.sources)){check(date(s.as_of)&&/^[0-9a-f]{64}$/.test(s.sha256)&&/^https:\/\//.test(s.origin),"Invalid game source");if(m.classification==="pregame_snapshot")check(Date.parse(s.as_of)<=Date.parse(m.data_cutoff),"Post-cutoff source");}
 check(Object.keys(a.games).length===games.length,"Incomplete game schedule");
 for(const expected of games){const g=a.games[expected.game_id];check(g&&g.game_id===expected.game_id&&g.away_team===expected.away_team&&g.home_team===expected.home_team&&g.kickoff_utc===expected.kickoff_utc&&Date.parse(m.data_cutoff)<Date.parse(g.kickoff_utc),"Game schedule mismatch");
 if(m.classification==="pregame_snapshot")check(Date.parse(m.generated_at)<Date.parse(g.kickoff_utc),"Post-kickoff forecast");
 check(Array.isArray(g.warnings)&&record(g.methods)&&record(g.teams),"Missing game sections");
 if(g.status==="insufficient_data"){check(Object.keys(g.methods).length===0&&Object.keys(g.teams).length===0&&g.warnings.length,"Incomplete game silently projected");continue;}
 check(g.status==="available"&&Object.keys(g.teams).sort().join()===[g.away_team,g.home_team].sort().join()&&g.methods.baseline,"Missing team inputs");
 for(const team of [g.away_team,g.home_team]){const p=g.teams[team],s=p.summary,o=g.teams[team===g.away_team?g.home_team:g.away_team].summary;
 check([s.offensive_points,s.offensive_plays,s.allowed_points,s.defensive_plays,s.offensive_ppp,s.defensive_ppp_allowed,s.plays_per_game,s.plays_faced_per_game,s.red_zone_drives_per_game,p.expected_plays,p.expected_ppp,p.baseline,p.opponent_defensive_ppp].every(v=>typeof v==="number"&&v>=0)&&Array.isArray(p.features)&&p.features.length===5&&p.features.every(v=>typeof v==="number"),"Invalid numeric scoring inputs");
 check(Math.abs(s.plays_per_game-s.offensive_plays/s.games)<1e-9&&Math.abs(s.plays_faced_per_game-s.defensive_plays/s.games)<1e-9,"Historical pace denominator mismatch");
 check(Number.isInteger(s.games)&&s.games>=4&&s.games<=8&&s.game_ids.length===s.games&&new Set(s.game_ids).size===s.games&&date(s.last_kickoff_utc)&&Date.parse(s.last_kickoff_utc)<Date.parse(m.data_cutoff)&&s.offensive_plays>0&&s.defensive_plays>0,"Insufficient team history");
 check(s.game_ids.every(id=>{const x=/^(\d{4})_(\d{2})_([A-Z]+)_([A-Z]+)$/.exec(id);return x&&[x[3],x[4]].includes(team)&&+x[1]>=season-1&&+x[1]<=season&&+x[2]>=1&&+x[2]<=18&&(+x[1]<season||+x[2]<week);}),"Future/invalid sample game");
 check(Math.abs(s.offensive_ppp-s.offensive_points/s.offensive_plays)<1e-9&&Math.abs(s.defensive_ppp_allowed-s.allowed_points/s.defensive_plays)<1e-9&&Math.abs(p.expected_plays-(s.plays_per_game+o.plays_faced_per_game)/2)<1e-9&&Math.abs(p.expected_ppp-(s.offensive_ppp+o.defensive_ppp_allowed)/2)<1e-9&&Math.abs(p.baseline-p.expected_ppp*p.expected_plays)<1e-9,"PPP or pace mismatch");}
 for(const [name,p] of Object.entries(g.methods)){check(["baseline","adjusted"].includes(name)&&p.win_probability===null&&Object.keys(p.scores).sort().join()===[g.away_team,g.home_team].sort().join()&&Object.values(p.scores).every(v=>typeof v==="number"&&v>=0),"Unsupported probability or method");if(name==="adjusted"){
 check(record(m.model)&&Array.isArray(m.model.coefficients)&&m.model.coefficients.length===5&&m.model.coefficients.every(v=>typeof v==="number")&&typeof m.model.intercept==="number"&&typeof m.model.through_season==="number"&&m.model.through_season<season&&date(m.model.last_training_kickoff)&&Date.parse(m.model.last_training_kickoff)<Date.parse(m.data_cutoff)&&m.model_sha256&&/^[0-9a-f]{64}$/.test(m.model_sha256),"Unverified adjusted model");
 const coefficients=m.model.coefficients as number[],bias=m.model.intercept as number;
 for(const t of [g.away_team,g.home_team])check(Math.abs(p.scores[t]-Math.max(0,g.teams[t].baseline+bias+coefficients.reduce((sum,c,i)=>sum+c*g.teams[t].features[i],0)))<1e-9,"Adjusted score formula mismatch");
 }for(const t of [g.away_team,g.home_team])if(name==="baseline")check(Math.abs(p.scores[t]-g.teams[t].baseline)<1e-9,"Changed baseline score");const margin=p.scores[g.home_team]-p.scores[g.away_team];check(Math.abs(p.home_margin-margin)<1e-9&&Math.abs(p.total-p.scores[g.home_team]-p.scores[g.away_team])<1e-9&&p.favored===(margin>0?g.home_team:margin<0?g.away_team:null),"Score, winner or total mismatch");}
 }
 return null;
 }catch(e){return e instanceof Error?e.message:"Invalid game projection";}
}
export async function decodeGameArtifact(bytes:ArrayBuffer,pin:string):Promise<unknown>{
 check(/^[0-9a-f]{64}$/.test(pin),"Missing game content hash");const actual=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(b=>b.toString(16).padStart(2,"0")).join("");check(actual===pin,"Game projection hash mismatch");return JSON.parse(new TextDecoder().decode(bytes));
}
export function gameFreshness(a:GameArtifact,g:GameProjection,now:number):string{
 if(a.meta.classification==="retrospective_analysis")return "Retrospective analysis — original pregame vintage unverified";
 const remaining=Date.parse(g.kickoff_utc)-now;if(remaining<=0)return "Archived forecast — kickoff has passed";
 if(remaining<=600000)return "Unavailable — kickoff safety margin exhausted";
 const limit=remaining<=21600000?1800000:remaining<=172800000?21600000:86400000;
 if([a.meta.generated_at,a.meta.data_cutoff,...Object.values(a.meta.sources).map(s=>s.as_of)].some(t=>now<Date.parse(t)||now-Date.parse(t)>=limit))return "Unavailable — stale source data";
 return "Pregame data within freshness window";
}

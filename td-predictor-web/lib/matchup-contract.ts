import type { BoardMeta, BoardRow } from "./types";

export type Sample = { games:number; game_ids:string[]; plays:number; run_plays:number; pass_plays:number; run_rate:number|null; plays_per_game:number|null; rz_plays:number; rz_runs:number; rz_passes:number; rz_run_rate:number|null; goal_line_opportunities:number; rush_tds:number; pass_tds:number; rz_trips:number; rz_td_drives:number; rz_td_rate:number|null; yards:number|null; yards_per_play:number|null; epa_per_play:number|null; epa_sample:number; success_rate:number|null; position_td_exclusions:number; position_identity_matched:number; position_identity_total:number; position_identity_coverage:number|null; field_position_sample:number; drive_sample:number };
export type PositionRate = { position:string; opportunities:number; targets:number; carries:number; tds:number; rz_opportunities:number; rz_tds:number; td_rate:number|null; rz_td_rate:number|null; yards:number|null; yards_per_opportunity:number|null };
export type Usage = { player_id:string; player:string; team:string; position:string; targets:number; carries:number; opportunities:number; rz_targets:number; rz_carries:number; rz_opportunities:number; goal_line_opportunities:number; target_share:number|null; carry_share:number|null; rz_share:number|null; team_targets:number; team_carries:number; team_rz_opportunities:number; snap_participation_pct:number|null; snap_sample_games:number };
export type Advantage = "Favorable"|"Neutral"|"Unfavorable"|"Insufficient Data";
export type Recommendation = Usage & { opponent:string; game_id:string; v5_probability_pct:number; advantage:Advantage; explanation:string[]; defense_position:PositionRate; league_position:PositionRate; offense_games:number; defense_games:number };
export type OffenseReport = { recent:Sample; season:Sample; trend:Sample; players:Usage[]; personnel:null };
export type DefenseReport = { recent:Sample; season:Sample; trend:Sample; positions:PositionRate[]; league:{sample:Sample;positions:PositionRate[]}; opponent_adjustment:null };
export type IntelligenceGame = { game_id:string; home_team:string; away_team:string; kickoff_utc:string; offenses:Record<string,OffenseReport>; defenses:Record<string,DefenseReport>; recommendations:Recommendation[] };
export type MatchupArtifact = { meta:{ schema_version:1; methodology_version:string; season:number; week:number; board_generated_at:string; data_as_of:string; generated_at:string; evidence_mode:"pregame_snapshot"|"retrospective_analysis"; source_as_of:Record<string,string>; source_fingerprints:Record<string,string>; policy:Record<string,number>; roster_audit:{policy_version:string;season:number;week:number;counts:Record<string,number>;decisions:{player_id:string;team:string;position:string;roster_status:string;decision:string}[]}; input_games:{game_id:string;kickoff_utc:string;week:number}[]; limitations:string[] }; games:Record<string,IntelligenceGame> };
const POLICY = {min_games:4,min_player_opportunities:10,min_player_rz:3,min_defense_position_rz:12,min_league_position_rz:100,min_identity_coverage:.95,wilson_z:1.96,relative_rate_threshold:.25,min_absolute_rate_gap:.05,min_player_rz_share:.15};
const record=(v:unknown):v is Record<string,unknown> => !!v && typeof v==="object" && !Array.isArray(v);
const count=(v:unknown):v is number => typeof v==="number" && Number.isInteger(v) && v>=0;
const validDate=(v:unknown):v is string => typeof v==="string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const id=(v:unknown):v is string => typeof v==="string" && /^00-\d{7}$/.test(v);
function requireValue(ok:unknown,message:string):asserts ok { if(!ok)throw new Error(message); }
const same=(a:unknown,b:unknown):boolean => JSON.stringify(a)===JSON.stringify(b);
const finiteTree=(v:unknown):boolean => typeof v==="number" ? Number.isFinite(v) : Array.isArray(v) ? v.every(finiteTree) : record(v) ? Object.values(v).every(finiteTree) : v===null || typeof v==="string" || typeof v==="boolean";
function rate(n:number,d:number,v:number|null){requireValue(d===0?v===null:typeof v==="number" && Math.abs(v-n/d)<=.000001,"Invalid rate denominator");}
function sample(s:Sample,inputs:Set<string>){
 requireValue(record(s)&&Array.isArray(s.game_ids)&&s.game_ids.every(v=>inputs.has(v))&&new Set(s.game_ids).size===s.game_ids.length&&s.games===s.game_ids.length,"Invalid sample references");
 for(const k of ["games","plays","run_plays","pass_plays","rz_plays","rz_runs","rz_passes","goal_line_opportunities","rush_tds","pass_tds","rz_trips","rz_td_drives","epa_sample","position_td_exclusions","position_identity_matched","position_identity_total","field_position_sample","drive_sample"] as const)requireValue(count(s[k]),"Invalid sample count");
 requireValue(s.run_plays+s.pass_plays===s.plays&&s.rz_runs+s.rz_passes===s.rz_plays&&s.rz_plays<=s.plays&&s.goal_line_opportunities<=s.rz_plays&&s.rz_td_drives<=s.rz_trips&&s.position_identity_matched<=s.position_identity_total&&s.position_identity_total<=s.plays&&Math.max(s.epa_sample,s.field_position_sample,s.drive_sample,s.rush_tds+s.pass_tds)<=s.plays,"Inconsistent sample counts");
 rate(s.run_plays,s.plays,s.run_rate);rate(s.plays,s.games,s.plays_per_game);rate(s.rz_runs,s.rz_plays,s.rz_run_rate);rate(s.rz_td_drives,s.rz_trips,s.rz_td_rate);rate(s.position_identity_matched,s.position_identity_total,s.position_identity_coverage);
 if(s.yards!==null)rate(s.yards,s.plays,s.yards_per_play);else requireValue(s.yards_per_play===null,"Missing yards evidence");
 requireValue(s.epa_sample===s.plays||(s.epa_per_play===null&&s.success_rate===null),"Partial EPA coverage");
 requireValue(s.success_rate===null||(s.success_rate>=0&&s.success_rate<=1),"Invalid efficiency rate");
}
function positions(rows:PositionRate[]){
 requireValue(Array.isArray(rows)&&rows.length===4&&same([...rows.map(r=>r.position)].sort(),["QB","RB","TE","WR"]),"Invalid position groups");
 for(const r of rows){for(const k of ["opportunities","targets","carries","tds","rz_opportunities","rz_tds"] as const)requireValue(count(r[k]),"Invalid position sample");requireValue(r.targets+r.carries===r.opportunities&&r.rz_tds<=r.rz_opportunities&&r.rz_opportunities<=r.opportunities&&r.tds<=r.opportunities,"Invalid position denominator");rate(r.tds,r.opportunities,r.td_rate);rate(r.rz_tds,r.rz_opportunities,r.rz_td_rate);if(r.yards!==null)rate(r.yards,r.opportunities,r.yards_per_opportunity);else requireValue(r.yards_per_opportunity===null,"Missing position yards");}
}
function usage(p:Usage){
 requireValue(id(p.player_id)&&typeof p.player==="string"&&p.player.trim()&&["QB","RB","FB","WR","TE"].includes(p.position),"Invalid player identity");
 for(const k of ["targets","carries","opportunities","rz_targets","rz_carries","rz_opportunities","goal_line_opportunities","team_targets","team_carries","team_rz_opportunities","snap_sample_games"] as const)requireValue(count(p[k]),"Invalid usage sample");
 requireValue(p.targets+p.carries===p.opportunities&&p.rz_targets+p.rz_carries===p.rz_opportunities&&p.rz_opportunities<=p.opportunities&&p.goal_line_opportunities<=p.rz_opportunities&&p.targets<=p.team_targets&&p.carries<=p.team_carries&&p.rz_opportunities<=p.team_rz_opportunities,"Invalid player denominator");
 rate(p.targets,p.team_targets,p.target_share);rate(p.carries,p.team_carries,p.carry_share);rate(p.rz_opportunities,p.team_rz_opportunities,p.rz_share);
 requireValue(p.snap_participation_pct===null?p.snap_sample_games===0:p.snap_sample_games>0&&p.snap_participation_pct>=0&&p.snap_participation_pct<=100,"Invalid snap evidence");
}
export function matchupValidationError(value:unknown,board:BoardMeta,rows:BoardRow[]):string|null{
 try{
 requireValue(record(value)&&record(value.meta)&&record(value.games)&&finiteTree(value),"Invalid matchup JSON");
 const data=value as MatchupArtifact,m=data.meta;
 requireValue(m.schema_version===1&&m.methodology_version==="matchup-v1"&&m.season===board.season&&m.week===board.week&&m.board_generated_at===board.generated_at,"Wrong schema or board snapshot");
 requireValue(validDate(m.data_as_of)&&validDate(m.generated_at)&&Date.parse(m.data_as_of)<=Date.parse(m.generated_at)&&Date.parse(board.generated_at)<=Date.parse(m.generated_at),"Invalid source/generation timing");
 requireValue(Object.keys(m.policy).length===Object.keys(POLICY).length&&Object.entries(POLICY).every(([k,v])=>m.policy[k]===v),"Unknown sample policy");
 requireValue(record(m.source_as_of)&&Object.values(m.source_as_of).every(v=>validDate(v)&&Date.parse(v)<=Date.parse(m.data_as_of))&&record(m.source_fingerprints)&&["schedule","pbp","player_games","weekly_rosters","players"].every(k=>k in m.source_fingerprints)&&Object.values(m.source_fingerprints).every(v=>typeof v==="string"&&/^[a-f0-9]{64}$/.test(v)),"Invalid source provenance");
 requireValue(["pregame_snapshot","retrospective_analysis"].includes(m.evidence_mode)&&Array.isArray(m.limitations)&&m.limitations.every(v=>typeof v==="string"),"Missing evidence classification");
 const generation=Date.parse(m.generated_at),earliest=Math.min(...board.games.map(g=>Date.parse(g.kickoff_utc))),remaining=earliest-generation,limit=remaining<=6*3600000?30*60000:remaining<=48*3600000?6*3600000:24*3600000;
 const timestampsKnown=Object.keys(m.source_fingerprints).every(k=>k in m.source_as_of);
 const known=remaining>10*60000&&[m.data_as_of,m.board_generated_at,...Object.values(m.source_as_of)].every(t=>generation>=Date.parse(t)&&generation-Date.parse(t)<limit)&&m.evidence_mode==="pregame_snapshot"&&Object.keys(m.source_fingerprints).every(k=>k in m.source_as_of);
 const inputIds=new Set<string>();requireValue(Array.isArray(m.input_games),"Missing input audit");
 for(const g of m.input_games){requireValue(g&&typeof g.game_id==="string"&&g.game_id.startsWith(`${m.season}_`)&&!inputIds.has(g.game_id)&&Number.isInteger(g.week)&&g.week>=1&&g.week<m.week&&validDate(g.kickoff_utc)&&Date.parse(g.kickoff_utc)<Date.parse(m.data_as_of),"Future or duplicate input game");inputIds.add(g.game_id);}
 const audit=m.roster_audit;requireValue(audit&&audit.policy_version==="week-aware-v1"&&audit.season===m.season&&audit.week===m.week&&Array.isArray(audit.decisions)&&audit.counts.pending===0,"Unresolved roster evidence");
 const eligible=new Map<string,{team:string;position:string}>();
 for(const decision of ["include","exclude","pending"])requireValue(audit.decisions.filter(r=>r.decision===decision).length===audit.counts[decision],"Invalid roster decision counts");
 for(const p of audit.decisions.filter(r=>r.decision==="include")){requireValue(id(p.player_id)&&p.roster_status==="ACT"&&!eligible.has(p.player_id),"Invalid eligible roster identity");eligible.set(p.player_id,p);}
 requireValue(Object.keys(data.games).length===board.games.length&&board.games.every(g=>g.game_id in data.games),"Game coverage differs from board");
 requireValue(same([...new Set([...eligible.values()].map(v=>v.team))].sort(),[...new Set(board.games.flatMap(g=>[g.home_team,g.away_team]))].sort()),"Missing eligible team coverage");
 const byId=new Map(rows.map(r=>[r.player_id,r]));
 for(const b of board.games){const g=data.games[b.game_id];requireValue(g.game_id===b.game_id&&g.home_team===b.home_team&&g.away_team===b.away_team&&validDate(g.kickoff_utc)&&Date.parse(g.kickoff_utc)===Date.parse(b.kickoff_utc)&&Date.parse(m.data_as_of)<Date.parse(g.kickoff_utc),"Game identity/kickoff mismatch");
 if(m.evidence_mode==="pregame_snapshot")requireValue(timestampsKnown&&Date.parse(m.generated_at)<Date.parse(g.kickoff_utc),"Invalid pregame provenance");
 const teams=[g.home_team,g.away_team].sort();requireValue(same(Object.keys(g.offenses).sort(),teams)&&same(Object.keys(g.defenses).sort(),teams),"Team coverage mismatch");
 const players=new Map<string,Usage>();
 for(const team of teams){const off=g.offenses[team],def=g.defenses[team];requireValue(off.personnel===null&&def.opponent_adjustment===null,"Unsupported statistics");
 for(const key of ["recent","season","trend"] as const){sample(off[key],inputIds);sample(def[key],inputIds);requireValue(same(off[key].game_ids,def[key].game_ids)&&off[key].game_ids.every(gid=>gid.split("_").slice(2).includes(team)),"Team sample mismatch");}
 requireValue(off.recent.games<=6&&off.trend.games<=3&&off.recent.game_ids.every(gid=>off.season.game_ids.includes(gid))&&off.trend.game_ids.every(gid=>off.recent.game_ids.includes(gid)),"Invalid recent window");
 positions(def.positions);sample(def.league.sample,inputIds);positions(def.league.positions);for(const [ps,s] of [[def.positions,def.recent],[def.league.positions,def.league.sample]] as const)requireValue(ps.reduce((n,p)=>n+p.opportunities,0)===s.position_identity_matched&&ps.reduce((n,p)=>n+p.tds,0)+s.position_td_exclusions===s.rush_tds+s.pass_tds,"Position/profile attribution differs");
 requireValue(Array.isArray(off.players)&&same(off.players.map(p=>p.player_id).sort(),[...eligible.entries()].filter(([,p])=>p.team===team).map(([id])=>id).sort()),"Missing player usage");for(const p of off.players){usage(p);const match=eligible.get(p.player_id);requireValue(p.team===team&&match&&match.team===team&&match.position===p.position&&!players.has(p.player_id),"Usage/eligible roster mismatch");players.set(p.player_id,p);}
 }
 requireValue(Array.isArray(g.recommendations)&&g.recommendations.length===[...players.keys()].filter(id=>byId.has(id)).length,"Recommendation coverage mismatch");const seen=new Set<string>();
 for(const r of g.recommendations){const p=players.get(r.player_id),b=byId.get(r.player_id);requireValue(p&&b&&!seen.has(r.player_id),"Unknown/duplicate recommendation");seen.add(r.player_id);requireValue(Object.entries(p).every(([k,v])=>r[k as keyof Recommendation]===v)&&r.v5_probability_pct===b.td_estimate&&r.team===b.team&&r.position===b.position&&r.opponent===b.opponent&&r.game_id===b.game_id&&r.opponent===(r.team===g.away_team?g.home_team:g.away_team),"V5 probability or identity mismatch");
 requireValue(Array.isArray(r.explanation)&&r.explanation.length>0&&r.explanation.every(v=>typeof v==="string"),"Missing explanation");
 const off=g.offenses[r.team],def=g.defenses[r.opponent],dp=def.positions.find(v=>v.position===(r.position==="FB"?"RB":r.position)),lp=def.league.positions.find(v=>v.position===(r.position==="FB"?"RB":r.position));requireValue(dp&&lp&&same(r.defense_position,dp)&&same(r.league_position,lp)&&r.offense_games===off.recent.games&&r.defense_games===def.recent.games,"Supporting evidence mismatch");
 const sufficient=known&&r.offense_games>=4&&r.defense_games>=4&&r.opportunities>=10&&r.rz_opportunities>=3&&dp.rz_opportunities>=12&&lp.rz_opportunities>=100&&(def.recent.position_identity_coverage??0)>=.95&&(def.league.sample.position_identity_coverage??0)>=.95&&[off.recent,def.recent,def.league.sample].every(s=>s.field_position_sample===s.plays)&&dp.rz_td_rate!==null&&lp.rz_td_rate!==null;
 let expected:Advantage="Insufficient Data";if(sufficient){const gap=dp.rz_td_rate!-lp.rz_td_rate!,threshold=Math.max(.05,.25*lp.rz_td_rate!);const wilson=(n:number,d:number)=>{const z=1.96,center=n/d+z*z/(2*d),margin=z*Math.sqrt((n/d)*(1-n/d)/d+z*z/(4*d*d));return [(center-margin)/(1+z*z/d),(center+margin)/(1+z*z/d)];};const [dlo,dhi]=wilson(dp.rz_tds,dp.rz_opportunities),[llo,lhi]=wilson(lp.rz_tds,lp.rz_opportunities);expected=(r.rz_share??0)>=.15&&gap>=threshold&&dlo>lhi?"Favorable":gap<=-threshold&&dhi<llo?"Unfavorable":"Neutral";}requireValue(r.advantage===expected,"Unsupported matchup designation");
 }
 }
 return null;
 }catch(error){return error instanceof Error?error.message:"Invalid matchup data";}
}

export async function decodeMatchup(bytes:ArrayBuffer,expectedHash:string):Promise<unknown>{
 requireValue(/^[a-f0-9]{64}$/.test(expectedHash),"Missing matchup content hash");
 const actual=[...new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))].map(v=>v.toString(16).padStart(2,"0")).join("");
 requireValue(actual===expectedHash,"Matchup artifact hash mismatch");
 return JSON.parse(new TextDecoder().decode(bytes));
}
export function matchupFreshness(meta:MatchupArtifact["meta"],game:IntelligenceGame,now:number):string{
 if(meta.evidence_mode==="retrospective_analysis")return "Retrospective analysis — no original pregame vintage established";
 const remaining=Date.parse(game.kickoff_utc)-now;if(remaining<=0)return "Archived analysis — kickoff has passed";
 const limit=remaining<=6*3600000?30*60000:remaining<=48*3600000?6*3600000:24*3600000;
 if([meta.generated_at,meta.data_as_of,meta.board_generated_at,...Object.values(meta.source_as_of)].some(t=>now<Date.parse(t)||now-Date.parse(t)>=limit))return "Stale analysis — refresh required before a recommendation";
 return "Within analysis freshness window";
}

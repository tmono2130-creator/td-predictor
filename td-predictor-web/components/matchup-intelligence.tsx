"use client";
import { useEffect, useState, useSyncExternalStore } from "react";
import type { BoardMeta, BoardRow, TableRow } from "../lib/types";
import { decodeMatchup, matchupFreshness, matchupValidationError, type MatchupArtifact, type Sample } from "../lib/matchup-contract";
import { formatPercent, formatTimestamp } from "../lib/format";
import { DataTable } from "./shared";
import styles from "../app/page.module.css";
export type IntelligenceView = "offense"|"defense"|"recommendations";
const subscribe=(notify:()=>void)=>{const timer=window.setInterval(notify,60000);return()=>window.clearInterval(timer);};
const minute=()=>Math.floor(Date.now()/60000)*60000;
const serverMinute=()=>0;
const percent=(value:number|null)=>value===null?"Unavailable":formatPercent(value*100);
const decimal=(value:number|null)=>value===null?"Unavailable":value.toFixed(2);

function useArtifact(url:string|null,hash:string|null){
 const key=url&&hash?`${url}:${hash}`:null;
 const [state,setState]=useState<{key:string|null;data:unknown;error:string|null}>({key:null,data:null,error:null});
 useEffect(()=>{
  if(!url||!hash)return;
  const controller=new AbortController();
  fetch(url,{cache:"no-store",signal:controller.signal}).then(response=>{if(!response.ok)throw new Error(`Artifact request failed: HTTP ${response.status}`);return response.arrayBuffer();})
   .then(bytes=>decodeMatchup(bytes,hash)).then(data=>{if(!controller.signal.aborted)setState({key,data,error:null});})
   .catch((error:unknown)=>{if(!controller.signal.aborted)setState({key,data:null,error:error instanceof Error?error.message:String(error)});});
  return()=>controller.abort();
 },[url,hash,key]);
 return {data:state.key===key?state.data:null,error:state.key===key?state.error:null,loading:!!key&&state.key!==key};
}
function tendencyRows(recent:Sample,season:Sample,trend:Sample,defense=false):TableRow[]{
 const rows:[string,(s:Sample)=>string|number][]=[
  ["Games in sample",s=>s.games],["Qualifying plays",s=>s.plays],["Plays per game",s=>decimal(s.plays_per_game)],
  ["Run frequency",s=>percent(s.run_rate)],["Pass frequency (incl. sacks)",s=>percent(s.run_rate===null?null:1-s.run_rate)],
  ["Red-zone plays",s=>s.rz_plays],["Red-zone run frequency",s=>percent(s.rz_run_rate)],
  ["Red-zone pass frequency",s=>percent(s.rz_run_rate===null?null:1-s.rz_run_rate)],["Goal-line plays (inside 5)",s=>s.goal_line_opportunities],
  ["Rushing TDs",s=>s.rush_tds],["Passing TDs",s=>s.pass_tds],["Red-zone drives",s=>s.rz_trips],
  ["Red-zone TD drives",s=>s.rz_td_drives],["Red-zone TD / drive",s=>percent(s.rz_td_rate)],
  [defense?"Yards allowed / play":"Yards / play",s=>decimal(s.yards_per_play)],
  [defense?"EPA allowed / play (lower is better)":"EPA / play",s=>decimal(s.epa_per_play)],
  ["EPA sample plays",s=>s.epa_sample],["EPA-positive play rate",s=>percent(s.success_rate)],
  ["Lateral/unattributed TD plays",s=>s.position_td_exclusions],
  ["Position identity coverage",s=>percent(s.position_identity_coverage)],
  ["Field-position sample plays",s=>s.field_position_sample],["Drive-ID sample plays",s=>s.drive_sample]
 ];
 return rows.map(([Metric,read])=>({Metric,"Recent (up to 6 games)":read(recent),"Current season":read(season),"Trend (up to 3 games)":read(trend)}));
}

export default function MatchupIntelligence({view,url,hash,board,rows,gameId,team,onTeamChange}:{view:IntelligenceView;url:string|null;hash:string|null;board:BoardMeta;rows:BoardRow[];gameId:string;team:string;onTeamChange:(team:string)=>void}){
 const {data,error,loading}=useArtifact(url,hash);
 const now=useSyncExternalStore(subscribe,minute,serverMinute);
 const title=view==="offense"?"Offensive Identity":view==="defense"?"Defensive Vulnerabilities":"Matchup-Based TD Recommendations";
 if(!url||!hash)return <section className={styles.intelligencePanel}><h3>{title}</h3><div role="status" className={`${styles.notice} ${styles.noticeInfo}`}>Matchup Intelligence has not been published for this snapshot. Existing TD Breakdown remains available. No matchup recommendation can be made without a validated artifact.</div></section>;
 if(loading)return <div role="status" className={styles.loading}><span className={styles.spinner}/>Loading verified matchup analysis…</div>;
 const validation=data?matchupValidationError(data,board,rows):null;
 if(error||validation||!data)return <div role="alert" className={`${styles.notice} ${styles.noticeError}`}>Matchup Intelligence unavailable: {error??validation??"no data"}. The existing TD Breakdown is unaffected.</div>;
 const artifact=data as MatchupArtifact;
 const game=artifact.games[gameId];
 if(!game)return <div role="alert" className={styles.notice}>No validated report for this selected game.</div>;
 const opponent=team===game.away_team?game.home_team:game.away_team;
 const freshness=now?matchupFreshness(artifact.meta,game,now):"Checking analysis freshness…";
 const current=freshness==="Within analysis freshness window";
 const offense=game.offenses[team],defense=game.defenses[opponent];
 return <section className={styles.intelligencePanel} aria-label={title}>
  <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>MATCHUP INTELLIGENCE / {artifact.meta.methodology_version}</span><h3>{title}</h3></div><span className={styles.pill}>Separate from V5</span></div>
  <div className={styles.chips} role="group" aria-label="Intelligence team">{[game.away_team,game.home_team].map(t=><button key={t} aria-pressed={team===t} className={`${styles.chip} ${team===t?styles.chipActive:""}`} onClick={()=>onTeamChange(t)}>{t} offense vs {t===game.away_team?game.home_team:game.away_team} defense</button>)}</div>
  <div className={styles.intelligenceMeta}><span>Data as of {formatTimestamp(artifact.meta.data_as_of)}</span><span>Generated {formatTimestamp(artifact.meta.generated_at)}</span><span>{artifact.meta.evidence_mode==="pregame_snapshot"?"Pregame snapshot":"Retrospective analysis"}</span></div>
  <p role="status" className={`${styles.notice} ${current?styles.noticeInfo:""}`}>{freshness}{!current?". No current favorable/unfavorable recommendation is shown.":". Sample-size safeguards apply to every designation."}</p>
  {artifact.meta.limitations.some(v=>v.includes("TEST FIXTURE"))&&<p className={styles.notice}>TEST FIXTURE — synthetic regression data, not real NFL statistics.</p>}
  {view==="offense"&&<>
   <p className={styles.caption}>{team} offensive tendencies. Recent and trend windows use completed regular-season games before the selected week and data cutoff. Pass plays include sacks; kneels, spikes, no-plays and conversion attempts are excluded.</p>
   <DataTable rows={tendencyRows(offense.recent,offense.season,offense.trend)}/>
   <h3>Player opportunity shares</h3><DataTable rows={offense.players.map(p=>({Player:p.player,Pos:p.position,Targets:p.targets,Carries:p.carries,"Target share":percent(p.target_share),"Carry share":percent(p.carry_share),"RZ targets":p.rz_targets,"RZ carries":p.rz_carries,"RZ share":percent(p.rz_share),"Goal-line opportunities":p.goal_line_opportunities,"Mean offensive snap %":p.snap_participation_pct===null?"Unavailable":formatPercent(p.snap_participation_pct),"Snap sample games":p.snap_sample_games}))}/>
   <p className={styles.caption}>Shares use observed team targets, carries and red-zone opportunities as denominators. Snap participation is an equal-game mean over the reported snap sample and is shown only with verified GSIS/game/team records. Personnel groupings, formations and route rates: unavailable.</p>
  </>}
  {view==="defense"&&<>
   <p className={styles.caption}>{opponent} defensive evidence against the selected offense. TD rates are opportunity-adjusted, not a ranking by raw touchdown totals. EPA is descriptive and is not adjusted for opponent strength.</p>
   <DataTable rows={tendencyRows(defense.recent,defense.season,defense.trend,true)}/>
   <h3>Allowed opportunities by offensive position</h3><DataTable rows={defense.positions.map(p=>({Position:p.position,Targets:p.targets,Carries:p.carries,Opportunities:p.opportunities,TDs:p.tds,"TD / opportunity":percent(p.td_rate),"RZ opportunities":p.rz_opportunities,"RZ TDs":p.rz_tds,"RZ TD / opportunity":percent(p.rz_td_rate),"League RZ TD / opportunity":percent(defense.league.positions.find(r=>r.position===p.position)?.rz_td_rate??null),"Yards / opportunity":decimal(p.yards_per_opportunity)}))}/>
   <p className={styles.caption}>Position rates cover direct target/carry scores and exclude lateral/unattributed scoring plays and unresolved identities; coverage is shown above and inadequate coverage suppresses designations. RZ TD / drive uses red-zone drives, not red-zone plays. League reference: all completed current-season games before cutoff. Strength-of-schedule adjustment and coverage-specific analysis are unavailable.</p>
  </>}
  {view==="recommendations"&&<>
   <p className={styles.caption}>Existing V5 probabilities are copied unchanged. Matchup advantage is a separate descriptive heuristic, not a calibrated probability or evidence of improved accuracy. Historical or stale reports do not produce current recommendations.</p>
   <div className={styles.recommendationList}>{game.recommendations.filter(r=>r.team===team).map(r=><article className={styles.recommendation} key={r.player_id}><div className={styles.sectionHeading}><div><h4>{r.player}</h4><span className={styles.caption}>{r.team} · {r.position} · vs {r.opponent}</span></div><span className={`${styles.advantage} ${current&&r.advantage==="Favorable"?styles.advantagePositive:current&&r.advantage==="Unfavorable"?styles.advantageNegative:""}`}>{current?r.advantage:"Insufficient Data"}</span></div><div className={styles.recommendationMetrics}><div><small>UNCHANGED V5 TD PROBABILITY</small><strong>{formatPercent(r.v5_probability_pct)}</strong></div><div><small>PLAYER RZ INVOLVEMENT</small><strong>{r.rz_opportunities} / {r.team_rz_opportunities}</strong><span>{percent(r.rz_share)} share</span></div><div><small>DEFENSE POSITION RZ TD / OPP</small><strong>{r.defense_position.rz_tds} / {r.defense_position.rz_opportunities}</strong><span>{percent(r.defense_position.rz_td_rate)} · league {percent(r.league_position.rz_td_rate)}</span></div></div><p className={styles.caption}>{r.offense_games} offensive games · {r.defense_games} defensive games · {r.opportunities} player opportunities · {r.league_position.rz_opportunities} league position red-zone opportunities.</p><ul className={styles.evidenceList}>{(current?r.explanation:[freshness,...r.explanation]).map((reason,i)=><li key={i}>{reason}</li>)}</ul><p className={styles.caption}>Targets {r.targets} · carries {r.carries} · RZ targets {r.rz_targets} · RZ carries {r.rz_carries}. No adjustment is applied to V5.</p></article>)}</div>
   {game.recommendations.filter(r=>r.team===team).length===0&&<p role="status" className={styles.notice}>No roster-verified players with a matching V5 row are available for a designation.</p>}
  </>}
  <details className={styles.details}><summary>Methodology, evidence and limitations</summary><p className={styles.caption}>Thresholds: at least 4 offense/defense games, 10 player opportunities, 3 player red-zone opportunities, 12 defensive position red-zone opportunities, 100 league position red-zone opportunities, and 95% position attribution. Favorable also requires at least 15% player red-zone share and a defensive rate at least 5 percentage points or 25% above the league rate. Unfavorable uses the corresponding negative rate gap. Favorable/unfavorable also require separated 95% Wilson intervals for the position TD/opportunity rates. These descriptive guards are not fitted model weights or a guarantee.</p><ul className={styles.evidenceList}>{artifact.meta.limitations.map((text,i)=><li key={i}>{text}</li>)}</ul><p className={styles.caption}>Source fingerprints: {Object.entries(artifact.meta.source_fingerprints).map(([key,hash])=>`${key}: ${hash.slice(0,12)}`).join(" · ")}</p></details>
 </section>;
}

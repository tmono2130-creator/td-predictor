"use client";
import {useEffect,useState,useSyncExternalStore} from "react";
import type {ScheduledGame} from "../lib/types";
import {TEAM_NAMES} from "../lib/data";
import {decodeGameArtifact,validateGameArtifact,gameFreshness,type GameArtifact} from "../lib/game-projection";
import {DataTable} from "./shared";
import styles from "../app/page.module.css";
const subscribe=(fn:()=>void)=>{const id=setInterval(fn,1000);return()=>clearInterval(id);};
const now=()=>Math.floor(Date.now()/1000)*1000;
export default function GamePredictor({season,week,games,url,pin}:{season:number;week:number;games:ScheduledGame[];url:string|null;pin:string|null}){
 const [selected,setSelected]=useState("");const [method,setMethod]=useState("baseline");
 const key=url&&pin?url+":"+pin:null;
 const [state,setState]=useState<{key:string|null;value:unknown;error:string|null}>({key:null,value:null,error:null});
 const clock=useSyncExternalStore(subscribe,now,()=>0);
 useEffect(()=>{if(!url||!pin)return;const abort=new AbortController();fetch(url,{signal:abort.signal,cache:"no-store"}).then(r=>{if(!r.ok)throw new Error(`HTTP ${r.status}`);return r.arrayBuffer();}).then(b=>decodeGameArtifact(b,pin)).then(value=>{if(!abort.signal.aborted)setState({key,value,error:null});}).catch((e:unknown)=>{if(!abort.signal.aborted)setState({key,value:null,error:e instanceof Error?e.message:String(e)});});return()=>abort.abort();},[url,pin,key]);
 const active=games.find(g=>g.game_id===selected)??games[0];
 const validation=state.key===key&&state.value?validateGameArtifact(state.value,games,season,week):null;
 const artifact=state.key===key&&state.value&&!validation?state.value as GameArtifact:null;
 const game=active?artifact?.games[active.game_id]:null;
 const enabled=game&&game.status==="available";
 const currentMethod=enabled&&game.methods[method]?method:"baseline";
 const projection=enabled?game.methods[currentMethod]:null;
 const freshness=game&&artifact&&clock?gameFreshness(artifact,game,clock):"Checking freshness…";
 const stale=freshness.startsWith("Unavailable");
 return <section className={`${styles.panel} ${styles.gamePredictor}`} aria-label="Game Predictor">
  <div className={styles.sectionHeading}><div><span className={styles.eyebrow}>TEAM SCORING / SEPARATE FROM V5</span><h2>Game Predictor</h2></div><span className={styles.pill}>No win-probability claim</span></div>
  <p className={styles.caption}>Select an actual scheduled matchup. Only scheduled games are listed; no projection exists for teams that do not play each other this week.</p>
  <div className={styles.field}><label htmlFor="gp-game">Predictor matchup</label><select id="gp-game" className={styles.select} value={active?.game_id??""} onChange={e=>{setSelected(e.target.value);setMethod("baseline");}}>{games.map(g=><option key={g.game_id} value={g.game_id}>{TEAM_NAMES[g.away_team]??g.away_team} @ {TEAM_NAMES[g.home_team]??g.home_team}</option>)}</select></div>
  {!games.length&&<p role="status" className={styles.notice}>No verified scheduled matchup exists for this selection.</p>}
  {(!url||!pin)?<p role="status" className={`${styles.notice} ${styles.noticeInfo}`}>Game Predictor data has not been published for this week. Verified scoring inputs and the reviewed release path are required. No example scores or recommendations are substituted.</p>:state.key!==key?<p role="status" className={styles.loading}>Loading verified game projections…</p>:state.error||validation?<p role="alert" className={`${styles.notice} ${styles.noticeError}`}>Game Predictor unavailable: {state.error??validation}</p>:null}
  {artifact&&game&&<>
   <p role="status" className={styles.notice}>{freshness}</p>
   <div className={styles.chips} role="group" aria-label="Game projection method"><button className={`${styles.chip} ${currentMethod==="baseline"?styles.chipActive:""}`} aria-pressed={currentMethod==="baseline"} onClick={()=>setMethod("baseline")}>PPP Baseline</button>{game.methods.adjusted&&<button className={`${styles.chip} ${currentMethod==="adjusted"?styles.chipActive:""}`} aria-pressed={currentMethod==="adjusted"} onClick={()=>setMethod("adjusted")}>Adjusted Projection · Experimental</button>}</div>
   {projection&&!stale?<>
    <h3>Projected final score · {currentMethod==="baseline"?"PPP Baseline":"Experimental Adjusted Projection"}</h3>
    <div className={styles.cards}>{[game.away_team,game.home_team].map(t=><article className={styles.card} key={t}><div className={styles.eyebrow}>{TEAM_NAMES[t]}</div><strong className={styles.cardPct}>{projection.scores[t].toFixed(1)}</strong><span className={styles.caption}>{t} projected points</span></article>)}</div>
    <p className={styles.notice}><strong>Predicted winner: {projection.favored?TEAM_NAMES[projection.favored]:"No edge — equal projected means"}</strong><br/>Projected margin: {Math.abs(projection.home_margin).toFixed(1)} points · Projected total: {projection.total.toFixed(1)} points</p>
    <h3>Team Efficiency Comparison</h3><DataTable rows={[game.away_team,game.home_team].map(t=>{const p=game.teams[t];return {Team:t,"Prior games":p.summary.games,"Offensive PPP":p.summary.offensive_ppp.toFixed(4),"Defensive PPP allowed":p.summary.defensive_ppp_allowed.toFixed(4),"Expected offensive plays":p.expected_plays.toFixed(2),"Expected PPP vs opponent":p.expected_ppp.toFixed(4),"RZ drives / game":p.summary.red_zone_drives_per_game.toFixed(2)};})}/>
    <h3>Why This Team Is Favored</h3><p className={styles.caption}>{projection.favored?`${projection.favored} has the higher projected mean. The baseline combines its offensive points/play with the opponent’s allowed points/play, then multiplies by expected pace. `:"Both projected means are equal. "}{currentMethod==="adjusted"?"The experimental ridge residual adds historically fitted efficiency, pace and home-field terms; it has not consistently improved winner accuracy.":"Expected pace averages the team’s plays/game and its opponent’s plays faced/game. Defensive and return TDs and safeties are excluded from the baseline."} A projected margin is not converted into a confidence percentage.</p>
   </>:<p role="status" className={styles.notice}>{stale?"Projection suppressed until fresh pregame sources are available.":"Insufficient Data — no score or winner can be projected."}</p>}
   <h3>Data Information</h3><p className={styles.caption}>Season {season} · Week {week} · Updated {artifact.meta.generated_at} · Cutoff {artifact.meta.data_cutoff} · Model {artifact.meta.model_version}</p>
   <ul className={styles.caption}>{[...artifact.meta.warnings,...game.warnings].map((v,i)=><li key={i}>{v}</li>)}</ul>
   <details className={styles.details}><summary>Source provenance and historical sample</summary>{Object.entries(artifact.meta.sources).map(([name,s])=><p className={styles.caption} key={name}>{name} · Captured {s.as_of} · {s.origin}<br/>SHA-256: {s.sha256}</p>)}{Object.entries(game.teams).map(([team,p])=><p className={styles.caption} key={team}>{team}: {p.summary.game_ids.join(", ")}</p>)}<p className={styles.caption}>Adjusted model fingerprint: {artifact.meta.model_sha256??"No adjusted model supplied"}. No original-vintage claim is made for retrospective analysis.</p></details>
  </>}
 </section>;
}

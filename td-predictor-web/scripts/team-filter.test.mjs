import test from 'node:test';
import assert from 'node:assert/strict';
import {matchesTeams,toggleTeam} from '../lib/team-filter.ts';
test('two and three arbitrary teams are unioned, never matched as opponents',()=>{let selection=[];for(const team of ['GB','CAR','SF'])selection=toggleTeam(selection,team);assert(matchesTeams('CAR',selection));assert(matchesTeams('SF',selection));assert(!matchesTeams('KC',selection));selection=toggleTeam(selection,'SF');assert.deepEqual(selection,['CAR','GB']);});
test('clear selection restores all teams',()=>{assert(matchesTeams('KC',[]));assert.deepEqual(toggleTeam(['GB'],'GB'),[]);});
test('combined predicates preserve original probabilities and identities',()=>{const rows=[{team:'GB',position:'RB',player:'A',td_estimate:12.345},{team:'CAR',position:'TE',player:'B',td_estimate:40},{team:'SF',position:'RB',player:'C',td_estimate:25}];const before=structuredClone(rows);assert.deepEqual(rows.filter(r=>matchesTeams(r.team,['GB','CAR'])&&r.position==='RB'),[rows[0]]);assert.deepEqual(rows,before);});

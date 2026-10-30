/** Empty selection means All Teams; this predicate never changes player values. */
export function matchesTeams(team: string, selected: readonly string[]): boolean {
  return selected.length === 0 || selected.includes(team);
}
export function toggleTeam(selected: readonly string[], team: string): string[] {
  return selected.includes(team) ? selected.filter(value => value !== team) : [...selected, team].sort();
}

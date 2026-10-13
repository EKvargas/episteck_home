import type { BootstrapContext } from '../home/Viewer.ts';
import { resolveRequestedPerson, type F3ActiveContext } from '../home/active-context.ts';

export type SearchParamsRecord = Record<string, string | string[] | undefined>;

/** Pure: pick the validated subject for a page request. Only `person` is read. */
export function pickSubject(
  bootstrap: BootstrapContext,
  searchParams: SearchParamsRecord,
): { context: F3ActiveContext; subjectName: string | null; stale: boolean } {
  const raw = searchParams.person;
  const query = new URLSearchParams();
  for (const value of raw === undefined ? [] : Array.isArray(raw) ? raw : [raw]) query.append('person', value);
  const { status, activeContext } = resolveRequestedPerson(query, bootstrap);
  const named = bootstrap.personContexts.find((person) => person.personId === activeContext.personId)?.displayName;
  const subjectName = named
    ?? (activeContext.personId === bootstrap.viewer.personId ? bootstrap.viewer.displayName : null);
  return { context: activeContext, subjectName, stale: status === 'STALE_CONTEXT' };
}

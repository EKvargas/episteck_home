import type { BootstrapContext } from './Viewer';

/** The requested navigation subject. This carries no actor or domain authority. */
export type F3ActiveContext = { kind: 'PERSON'; personId: string };

export type PersonNavigation = {
  status: 'CURRENT' | 'STALE_CONTEXT';
  activeContext: F3ActiveContext;
};

const personIdPattern = /^PSN-[0-9]{5,}(?![\s\S])/;

export function resolveRequestedPerson(query: URLSearchParams, bootstrap: BootstrapContext): PersonNavigation {
  const requested = query.getAll('person');
  const self: F3ActiveContext = { kind: 'PERSON', personId: bootstrap.viewer.personId };
  if (requested.length === 0) return { status: 'CURRENT', activeContext: self };
  if (requested.length !== 1 || !personIdPattern.test(requested[0])) {
    return { status: 'STALE_CONTEXT', activeContext: self };
  }

  const personId = requested[0];
  const careSubjectIds = new Set(bootstrap.careRelationships.map((relationship) => relationship.subjectPersonId));
  const navigable = personId === self.personId
    || (careSubjectIds.has(personId) && bootstrap.personContexts.some((context) => context.personId === personId));
  return navigable
    ? { status: 'CURRENT', activeContext: { kind: 'PERSON', personId } }
    : { status: 'STALE_CONTEXT', activeContext: self };
}

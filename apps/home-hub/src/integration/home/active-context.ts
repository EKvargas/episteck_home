import type { BootstrapContext } from './Viewer';

declare const issuedBrand: unique symbol;

/** Wire shape of an active context. Carries no authority; safe for the browser. */
export type PersonContextView = { readonly kind: 'PERSON'; readonly personId: string };

/**
 * A requested navigation subject issued on the server by resolveRequestedPerson.
 * The Nutrition adapter accepts only this type, and checks the runtime registry.
 */
export type F3ActiveContext = PersonContextView & { readonly [issuedBrand]: true };

export type PersonNavigation = {
  status: 'CURRENT' | 'STALE_CONTEXT';
  activeContext: F3ActiveContext;
};

const REGISTRY_KEY = Symbol.for('episteck.home-hub.issued-active-contexts');

/** Shared across module instances: Next.js may load this module once per server layer. */
function registry(): WeakSet<object> {
  const holder = globalThis as unknown as Record<symbol, WeakSet<object> | undefined>;
  return (holder[REGISTRY_KEY] ??= new WeakSet<object>());
}

function issue(personId: string): F3ActiveContext {
  const context = Object.freeze({ kind: 'PERSON' as const, personId });
  registry().add(context);
  return context as F3ActiveContext;
}

export function isIssuedContext(value: unknown): value is F3ActiveContext {
  return typeof value === 'object' && value !== null && registry().has(value);
}

export function assertIssuedContext(value: unknown): asserts value is F3ActiveContext {
  if (!isIssuedContext(value)) {
    throw new TypeError('active context was not issued by resolveRequestedPerson');
  }
}

const personIdPattern = /^PSN-[0-9]{5,}(?![\s\S])/;

export function resolveRequestedPerson(query: URLSearchParams, bootstrap: BootstrapContext): PersonNavigation {
  const requested = query.getAll('person');
  const self = issue(bootstrap.viewer.personId);
  if (requested.length === 0) return { status: 'CURRENT', activeContext: self };
  if (requested.length !== 1 || !personIdPattern.test(requested[0])) {
    return { status: 'STALE_CONTEXT', activeContext: self };
  }

  const personId = requested[0];
  const careSubjectIds = new Set(bootstrap.careRelationships.map((relationship) => relationship.subjectPersonId));
  const navigable = personId === self.personId
    || (careSubjectIds.has(personId) && bootstrap.personContexts.some((context) => context.personId === personId));
  return navigable
    ? { status: 'CURRENT', activeContext: personId === self.personId ? self : issue(personId) }
    : { status: 'STALE_CONTEXT', activeContext: self };
}

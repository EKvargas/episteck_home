import type { BootstrapContext, CareRelationship } from './Viewer';
import type { ResourceScope } from '../session/ResourceScope';

// The final negative lookahead enforces the absolute end; JavaScript `$` alone
// also matches immediately before a final line terminator.
const personIdPattern = /^PSN-[0-9]{5,}(?![\s\S])/;
const circleIdPattern = /^CIR-[0-9]{5,}(?![\s\S])/;
const relationshipTypes = new Set([
  'CAREGIVER',
  'COORDINATOR',
  'GUARDIAN',
  'FAMILY_SUPPORT',
]);
const controlCharacters = /[\x00-\x1f\x7f-\x9f]/;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function validDisplayName(value: unknown): value is string {
  return typeof value === 'string'
    && value.length > 0
    && value.length <= 140
    && !controlCharacters.test(value);
}

function personScope(value: unknown): Extract<ResourceScope, { type: 'PERSON' }> | null {
  if (!isRecord(value)
    || value.type !== 'PERSON'
    || typeof value.personId !== 'string'
    || !personIdPattern.test(value.personId)
    || !validDisplayName(value.displayName)) return null;
  return {
    type: 'PERSON',
    personId: value.personId,
    displayName: value.displayName,
  };
}

function circleScope(value: unknown): Extract<ResourceScope, { type: 'CIRCLE' }> | null {
  if (!isRecord(value)
    || value.type !== 'CIRCLE'
    || typeof value.circleId !== 'string'
    || !circleIdPattern.test(value.circleId)
    || !validDisplayName(value.displayName)) return null;
  return {
    type: 'CIRCLE',
    circleId: value.circleId,
    displayName: value.displayName,
  };
}

function careRelationship(value: unknown): CareRelationship | null {
  if (!isRecord(value)
    || typeof value.subjectPersonId !== 'string'
    || !personIdPattern.test(value.subjectPersonId)
    || typeof value.relationshipType !== 'string'
    || !relationshipTypes.has(value.relationshipType)) return null;
  return {
    subjectPersonId: value.subjectPersonId,
    relationshipType: value.relationshipType as CareRelationship['relationshipType'],
  };
}

/** Reconstruct the F2a wire-v1 allowlist. Extra fields never cross into React. */
export function parseBootstrapWire(value: unknown): BootstrapContext {
  if (!isRecord(value) || value.version !== 1) throw new Error('invalid bootstrap');

  const viewer = personScope({ ...((isRecord(value.viewer) && value.viewer) || {}), type: 'PERSON' });
  if (!viewer) throw new Error('invalid bootstrap');

  if (!Array.isArray(value.personContexts)
    || !Array.isArray(value.circleContexts)
    || !Array.isArray(value.careRelationships)
    || value.personContexts.length < 1
    || value.personContexts.length > 51
    || value.circleContexts.length > 50
    || value.careRelationships.length > 50) throw new Error('invalid bootstrap');

  const personContexts = value.personContexts.map(personScope);
  const circleContexts = value.circleContexts.map(circleScope);
  const careRelationships = value.careRelationships.map(careRelationship);
  if (personContexts.some((context) => context === null)
    || circleContexts.some((context) => context === null)
    || careRelationships.some((relationship) => relationship === null)) throw new Error('invalid bootstrap');

  const persons = personContexts as Array<Extract<ResourceScope, { type: 'PERSON' }>>;
  const circles = circleContexts as Array<Extract<ResourceScope, { type: 'CIRCLE' }>>;
  const relationships = careRelationships as CareRelationship[];
  const personIds = persons.map((context) => context.personId);
  const circleIds = circles.map((context) => context.circleId);
  if (persons[0].personId !== viewer.personId
    || persons[0].displayName !== viewer.displayName
    || new Set(personIds).size !== personIds.length
    || new Set(circleIds).size !== circleIds.length
    || personIds.some((personId) => circleIds.includes(personId))) throw new Error('invalid bootstrap');

  const relationshipIds = relationships.map((relationship) => relationship.subjectPersonId);
  if (new Set(relationshipIds).size !== relationshipIds.length
    || relationshipIds.some((personId) => !personIds.includes(personId) || personId === viewer.personId)
    || personIds.slice(1).some((personId) => !relationshipIds.includes(personId))) throw new Error('invalid bootstrap');

  return {
    viewer: { personId: viewer.personId, displayName: viewer.displayName },
    personContexts: persons,
    circleContexts: circles,
    careRelationships: relationships,
  };
}

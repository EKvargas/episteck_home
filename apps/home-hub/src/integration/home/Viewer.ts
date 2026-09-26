import type { ResourceScope } from '../session/ResourceScope';

export interface Viewer {
  personId: string;
  displayName: string;
}

export type CareRelationshipType =
  | 'CAREGIVER'
  | 'COORDINATOR'
  | 'GUARDIAN'
  | 'FAMILY_SUPPORT';

export interface CareRelationship {
  subjectPersonId: string;
  relationshipType: CareRelationshipType;
}

export interface BootstrapContext {
  viewer: Viewer;
  personContexts: Array<Extract<ResourceScope, { type: 'PERSON' }>>;
  circleContexts: Array<Extract<ResourceScope, { type: 'CIRCLE' }>>;
  careRelationships: CareRelationship[];
}

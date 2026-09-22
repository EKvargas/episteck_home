export interface Viewer {
  personId: string;
  name: string;
}

export interface CareRelationship {
  subjectId: string;
  relation: string;
}

export interface BootstrapContext {
  viewer: Viewer;
  personContexts: Array<{ type: 'PERSON'; personId: string; displayName: string }>;
  circleContexts: Array<{ type: 'CIRCLE'; circleId: string; displayName: string }>;
  careRelationships: CareRelationship[];
}

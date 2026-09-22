export type ResourceScope =
  | {
      type: 'PERSON';
      personId: string;
      displayName: string;
    }
  | {
      type: 'CIRCLE';
      circleId: string;
      displayName: string;
    };

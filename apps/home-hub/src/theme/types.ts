export type OlinThemeId = 
  | 'ambient-future'
  | 'warm-household'
  | 'premium-hardware'
  | 'editorial-ledger'
  | 'colorful-canvas'
  | 'organic-calm';

export interface OlinThemeMeta {
  id: OlinThemeId;
  name: string;
  description: string;
}

export const DEFAULT_THEME_ID: OlinThemeId = 'warm-household';

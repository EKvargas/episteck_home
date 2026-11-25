import { HUB_BASE_PATH } from '../basePath.ts';

type SearchParams = Record<string, string | string[] | undefined>;

/** A nutrition path without the basePath; `person` always comes first. */
export function nutritionPath(path: string, person: string | null, query: Record<string, string> = {}): string {
  const params = new URLSearchParams();
  if (person) params.set('person', person);
  for (const [key, value] of Object.entries(query)) params.set(key, value);
  const text = params.toString();
  return text ? `${path}?${text}` : path;
}

/** The same path for plain `<a>` links, with the hub basePath. */
export function nutritionHref(path: string, person: string | null, query: Record<string, string> = {}): string {
  return `${HUB_BASE_PATH}${nutritionPath(path, person, query)}`;
}

/** Where `/nutrition` sends the reader: Hoy, keeping every `person` value and nothing else. */
export function hoyRedirectPath(searchParams: SearchParams): string {
  const raw = searchParams.person;
  const people = raw === undefined ? [] : Array.isArray(raw) ? raw : [raw];
  const params = new URLSearchParams();
  for (const person of people) params.append('person', person);
  const text = params.toString();
  return text ? `/nutrition/hoy?${text}` : '/nutrition/hoy';
}

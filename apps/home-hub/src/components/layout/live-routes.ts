/** Exact match; an entry ending in '/' matches any route below it by prefix. */
export function isLiveRoute(route: string, liveRoutes: readonly string[]): boolean {
  return liveRoutes.some((entry) => (entry.endsWith('/') && entry !== '/' ? route.startsWith(entry) : route === entry));
}

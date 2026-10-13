/**
 * Per-fetch budget for every Hub call on a page render: the BFF bootstrap, the delegation
 * mint, and the Nutrition read. The layout's bootstrap bounds the shell; the panel adds at
 * most two more budgets (mint, profile) because it shares the layout's bootstrap.
 */
export const FETCH_TIMEOUT_MS = 4000;

/** True when a fetch or a body read was aborted by its timeout signal. */
export function isAbortError(error: unknown): boolean {
  return error instanceof Error && (error.name === 'TimeoutError' || error.name === 'AbortError');
}

/** Release an unread body so the upstream connection is not held open. */
export function discardBody(response: Response): void {
  response.body?.cancel().catch(() => {});
}

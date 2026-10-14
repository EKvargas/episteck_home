import 'server-only';
import { getBootstrapForRequest } from '../home/bootstrap.server';
import type { F3ActiveContext } from '../home/active-context';
import { pickSubject, type SearchParamsRecord } from './live-subject';

export type LiveSubject =
  | { status: 'OK'; context: F3ActiveContext; subjectName: string | null; stale: boolean }
  | { status: 'SESSION' }
  | { status: 'UNAVAILABLE' };

/**
 * The only producer of the context handed to readNutritionProfile on a page request.
 * Uses this request's session-bound bootstrap (shared with the layout through React
 * cache()); nothing the browser sends is trusted beyond the `person` selector, which
 * resolveRequestedPerson validates.
 */
export async function resolveLiveSubject(searchParams: SearchParamsRecord): Promise<LiveSubject> {
  const result = await getBootstrapForRequest();
  if (result.delivery !== 'READY' || !result.data) {
    return result.errorCode === 'SESSION_REQUIRED' || result.errorCode === 'SESSION_INVALID'
      ? { status: 'SESSION' }
      : { status: 'UNAVAILABLE' };
  }
  return { status: 'OK', ...pickSubject(result.data, searchParams) };
}

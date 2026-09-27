import { NextRequest, NextResponse } from 'next/server';
import { getBootstrapForRequest } from '@/integration/home/bootstrap.server';
import { resolveRequestedPerson } from '@/integration/home/active-context';

export async function POST(request: NextRequest) {
  const result = await getBootstrapForRequest();
  if (result.delivery !== 'READY' || !result.data) {
    const status = result.errorCode === 'SESSION_REQUIRED' || result.errorCode === 'SESSION_INVALID' ? 401 : 503;
    return NextResponse.json({ error: status === 401 ? 'SESSION_INVALID' : 'SERVICE_UNAVAILABLE' }, {
      status, headers: { 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' },
    });
  }

  let person: unknown;
  try {
    const body: unknown = await request.json();
    person = body && typeof body === 'object' && !Array.isArray(body) && 'person' in body
      ? body.person : undefined;
  } catch {
    person = undefined;
  }
  const query = new URLSearchParams();
  if (Array.isArray(person) && person.every((value) => typeof value === 'string')) {
    for (const value of person) query.append('person', value);
  } else {
    query.append('person', '');
  }

  return NextResponse.json({
    ...resolveRequestedPerson(query, result.data),
    bootstrap: result.data,
    environment: result.environment,
  }, { headers: { 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' } });
}

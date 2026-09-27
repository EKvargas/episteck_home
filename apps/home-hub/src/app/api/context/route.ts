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

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    body = undefined;
  }
  const validBody = body && typeof body === 'object' && !Array.isArray(body)
    && Object.keys(body).length === 1 && 'person' in body
    && Array.isArray(body.person) && body.person.every((value) => typeof value === 'string');
  if (!validBody) {
    return NextResponse.json({ error: 'INVALID_CONTEXT_REQUEST' }, {
      status: 400, headers: { 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' },
    });
  }
  const query = new URLSearchParams();
  for (const value of (body as { person: string[] }).person) query.append('person', value);

  return NextResponse.json({
    ...resolveRequestedPerson(query, result.data),
    bootstrap: result.data,
    environment: result.environment,
  }, { headers: { 'Cache-Control': 'no-store', 'Referrer-Policy': 'no-referrer' } });
}

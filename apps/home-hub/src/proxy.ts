import { randomBytes } from 'node:crypto';
import { NextRequest, NextResponse } from 'next/server';
import { getHomeHubServerConfiguration } from '@/integration/home/server-config';
import { hoyRedirectPath } from '@/integration/nutrition/nutrition-href';

/**
 * `/nutrition` -> `/nutrition/hoy`, keeping every `?person=`. It lives here because a page's
 * redirect() streams inside the root layout's Suspense and arrives as HTTP 200 with a meta tag.
 * Only a request that carries a session cookie is redirected: without one the layout's single
 * redirect to /login must win, and the redirect is never a Nutrition read.
 */
function hoyRedirect(request: NextRequest): NextResponse | null {
  if (request.method !== 'GET' && request.method !== 'HEAD') return null;
  if (request.nextUrl.pathname.replace(/\/+$/, '') !== '/nutrition') return null;
  if (!request.cookies.has('episteck_home_session')) return null;
  if (getHomeHubServerConfiguration().mode !== 'LIVE') return null;
  const url = request.nextUrl.clone();
  const [pathname, search = ''] = hoyRedirectPath({ person: url.searchParams.getAll('person') }).split('?');
  url.pathname = pathname;
  url.search = search ? `?${search}` : '';
  const response = NextResponse.redirect(url, 307);
  response.headers.set('Cache-Control', 'no-store');
  response.headers.set('X-Content-Type-Options', 'nosniff');
  return response;
}

export function proxy(request: NextRequest) {
  const redirect = hoyRedirect(request);
  if (redirect) return redirect;
  const nonce = randomBytes(18).toString('base64');
  const development = process.env.NODE_ENV === 'development';
  const contentSecurityPolicy = [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'${development ? " 'unsafe-eval'" : ''}`,
    `style-src 'self' 'nonce-${nonce}'`,
    "style-src-attr 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'none'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'none'",
    ...(development ? [] : ['upgrade-insecure-requests']),
  ].join('; ');

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('x-nonce', nonce);
  requestHeaders.set('Content-Security-Policy', contentSecurityPolicy);
  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set('Content-Security-Policy', contentSecurityPolicy);
  response.headers.set('X-Content-Type-Options', 'nosniff');
  response.headers.set('X-Frame-Options', 'DENY');
  response.headers.set('Referrer-Policy', 'no-referrer');
  return response;
}

export const config = {
  matcher: '/:path*',
};

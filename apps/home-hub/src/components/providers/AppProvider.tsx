'use client';
import React, { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import type { Viewer, ContextOption } from '@/domain/types';
import type { BootstrapContext } from '@/integration/home/Viewer';
import type { F3ActiveContext, PersonNavigation } from '@/integration/home/active-context';
import { ServiceUnavailableBoundary } from '@/integration/components/boundaries/ServiceUnavailableBoundary';

interface AppContextState {
  viewer: Viewer;
  activeContext: F3ActiveContext;
  presentationContext: ContextOption;
  setContext: (personId: string) => void;
  availableContexts: ContextOption[];
  bootstrap: BootstrapContext;
}

type ValidatedNavigation = PersonNavigation & { bootstrap: BootstrapContext; environment: 'MOCK' | 'LIVE' };
type NavigationState = { requestKey: string; value: ValidatedNavigation };

const AppContext = createContext<AppContextState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const router = useRouter();
  const queryString = searchParams.toString();
  const requestKey = `${pathname}?${queryString}`;
  const [navigation, setNavigation] = useState<NavigationState | null>(null);
  const [pendingPersonId, setPendingPersonId] = useState<string | null>(null);
  const [contextChanged, setContextChanged] = useState(false);
  const [demoPresentation, setDemoPresentation] = useState<{ requestKey: string; id: string } | null>(null);
  const [unavailable, setUnavailable] = useState(false);
  const [revalidation, setRevalidation] = useState(0);
  const selectionGeneration = useRef(0);
  const pendingPersonIdRef = useRef<string | null>(null);

  useEffect(() => {
    const recheck = () => {
      selectionGeneration.current += 1;
      setNavigation(null);
      setRevalidation((current) => current + 1);
    };
    const whenVisible = () => {
      if (document.visibilityState === 'visible') recheck();
    };
    window.addEventListener('focus', recheck);
    document.addEventListener('visibilitychange', whenVisible);
    return () => {
      window.removeEventListener('focus', recheck);
      document.removeEventListener('visibilitychange', whenVisible);
    };
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    const generation = selectionGeneration.current;
    const person = new URLSearchParams(queryString).getAll('person');
    fetch('/app/api/context', {
      method: 'POST', cache: 'no-store', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ person }), signal: controller.signal,
    }).then(async (response) => {
      if (response.status === 401) {
        window.location.assign(new URL('/login', window.location.origin).toString());
        return;
      }
      if (!response.ok) throw new Error('context unavailable');
      const value = await response.json() as ValidatedNavigation;
      if (controller.signal.aborted || generation !== selectionGeneration.current) return;
      setUnavailable(false);
      if (value.status === 'STALE_CONTEXT') {
        pendingPersonIdRef.current = null;
        setPendingPersonId(null);
        setContextChanged(true);
        setNavigation(null);
        router.replace(`${pathname}?person=${encodeURIComponent(value.activeContext.personId)}`);
        return;
      }
      if (pendingPersonIdRef.current && value.activeContext.personId !== pendingPersonIdRef.current) return;
      pendingPersonIdRef.current = null;
      setNavigation({ requestKey, value });
      setPendingPersonId(null);
    }).catch(() => {
      if (!controller.signal.aborted && generation === selectionGeneration.current) setUnavailable(true);
    });
    return () => controller.abort();
  }, [pathname, queryString, requestKey, revalidation, router]);

  if (unavailable) return <ServiceUnavailableBoundary />;
  if (!navigation || navigation.requestKey !== requestKey
    || (pendingPersonId && navigation.value.activeContext.personId !== pendingPersonId)) {
    return <div role="status" aria-live="polite">Loading context…</div>;
  }

  const { bootstrap, activeContext, environment } = navigation.value;
  const availableContexts: ContextOption[] = bootstrap.personContexts
    .filter((person) => person.personId === bootstrap.viewer.personId
      || bootstrap.careRelationships.some((relationship) => relationship.subjectPersonId === person.personId))
    .map((person) => ({
      id: person.personId,
      name: person.displayName,
      mode: person.personId === bootstrap.viewer.personId ? 'PERSONAL' : 'CARE_FOR_ANOTHER_PERSON',
    }));
  if (environment === 'MOCK') {
    availableContexts.push(...bootstrap.circleContexts.map((circle) => ({
      id: circle.circleId, name: circle.displayName, mode: 'FAMILY' as const,
    })));
  }
  const presentationContext = availableContexts.find((context) => demoPresentation?.requestKey === requestKey && context.id === demoPresentation.id)
    ?? availableContexts.find((context) => context.id === activeContext.personId);
  if (!presentationContext) return <ServiceUnavailableBoundary />;

  const setContext = (personId: string) => {
    if (environment === 'MOCK' && bootstrap.circleContexts.some((circle) => circle.circleId === personId)) {
      setDemoPresentation({ requestKey, id: personId });
      return;
    }
    if (!availableContexts.some((context) => context.id === personId)) return;
    setDemoPresentation(null);
    if (personId === activeContext.personId) return;
    setContextChanged(false);
    selectionGeneration.current += 1;
    pendingPersonIdRef.current = personId;
    setNavigation(null);
    setPendingPersonId(personId);
    router.push(`${pathname}?person=${encodeURIComponent(personId)}`);
  };

  return (
    <AppContext.Provider value={{
      viewer: { id: bootstrap.viewer.personId, name: bootstrap.viewer.displayName },
      activeContext, presentationContext, setContext, availableContexts, bootstrap,
    }}>
      {contextChanged && <div role="status" aria-live="polite">Context changed. Showing your current Person context.</div>}
      <React.Fragment key={`${activeContext.personId}:${presentationContext.id}`}>{children}</React.Fragment>
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppContext must be used within AppProvider');
  return context;
}

export function useOptionalAppContext() {
  return useContext(AppContext);
}

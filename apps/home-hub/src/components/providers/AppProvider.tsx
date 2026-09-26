'use client';
import React, { createContext, useContext, useState, ReactNode } from 'react';
import { Viewer, ContextOption } from '@/domain/types';
import type { BootstrapContext } from '@/integration/home/Viewer';

interface AppContextState {
  viewer: Viewer;
  activeContext: ContextOption;
  setContext: (contextId: string) => void;
  availableContexts: ContextOption[];
  bootstrap: BootstrapContext;
}

const AppContext = createContext<AppContextState | undefined>(undefined);

function contextsFromBootstrap(bootstrap: BootstrapContext): ContextOption[] {
  const careSubjects = new Set(bootstrap.careRelationships.map((relationship) => relationship.subjectPersonId));
  return [
    ...bootstrap.personContexts.map((context): ContextOption => ({
      id: context.personId,
      name: context.displayName,
      mode: context.personId === bootstrap.viewer.personId
        ? 'PERSONAL'
        : careSubjects.has(context.personId) ? 'CARE_FOR_ANOTHER_PERSON' : 'PERSONAL',
    })),
    ...bootstrap.circleContexts.map((context): ContextOption => ({
      id: context.circleId,
      name: context.displayName,
      mode: 'FAMILY',
    })),
  ];
}

export function AppProvider({ children, bootstrap }: { children: ReactNode; bootstrap: BootstrapContext }) {
  const availableContexts = contextsFromBootstrap(bootstrap);
  const [activeContext, setActiveContext] = useState<ContextOption>(availableContexts[0]);
  const viewer: Viewer = { id: bootstrap.viewer.personId, name: bootstrap.viewer.displayName };

  const setContext = (contextId: string) => {
    const ctx = availableContexts.find((c) => c.id === contextId);
    if (ctx) setActiveContext(ctx);
  };

  return (
    <AppContext.Provider
      value={{
        viewer,
        activeContext,
        setContext,
        availableContexts,
        bootstrap,
      }}
    >
      {children}
    </AppContext.Provider>
  );
}

export function useAppContext() {
  const context = useContext(AppContext);
  if (!context) throw new Error('useAppContext must be used within AppProvider');
  return context;
}

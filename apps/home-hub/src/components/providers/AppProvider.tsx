'use client';
import React, { createContext, useContext, useState, ReactNode } from 'react';
import { Viewer, ContextOption } from '@/domain/types';
import { viewerMock, availableContextsMock } from '@/domain/mocks';

interface AppContextState {
  viewer: Viewer;
  activeContext: ContextOption;
  setContext: (contextId: string) => void;
  availableContexts: ContextOption[];
}

const AppContext = createContext<AppContextState | undefined>(undefined);

export function AppProvider({ children }: { children: ReactNode }) {
  const [activeContext, setActiveContext] = useState<ContextOption>(availableContextsMock[0]);

  const setContext = (contextId: string) => {
    const ctx = availableContextsMock.find((c) => c.id === contextId);
    if (ctx) setActiveContext(ctx);
  };

  return (
    <AppContext.Provider
      value={{
        viewer: viewerMock,
        activeContext,
        setContext,
        availableContexts: availableContextsMock,
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

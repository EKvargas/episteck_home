'use client';

import React from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import styles from './page.module.css';

/** LIVE header: title and the F3a Person switcher. Selecting a Person changes `?person=`; the server re-renders. */
export function NutritionHeader() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  return (
    <header className={styles.header}>
      <div>
        <h1 className={styles.title}>Nutrition Hub</h1>
        <div style={{ marginTop: '0.75rem' }}>
          <DefaultRelationshipSwitcher
            contexts={availableContexts}
            activeContextId={activeContext.personId}
            onSelectContext={(id) => setContext(id)}
          />
        </div>
      </div>
    </header>
  );
}

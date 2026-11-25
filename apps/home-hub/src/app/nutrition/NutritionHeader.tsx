'use client';

import { useSearchParams } from 'next/navigation';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import { HUB_BASE_PATH } from '@/integration/basePath';
import styles from './page.module.css';

const TABS = [
  { view: 'profile', label: 'Perfil', path: '/nutrition/perfil' },
  { view: 'diary', label: 'Hoy', path: '/nutrition/hoy' },
  { view: 'days', label: 'Días', path: '/nutrition/dias' },
] as const;

export function NutritionHeader({ view }: { view: 'home' | 'profile' | 'diary' | 'days' | 'help' }) {
  const { activeContext, setContext, availableContexts, viewer } = useAppContext();
  const selected = useSearchParams().has('person');
  const person = selected ? `?person=${encodeURIComponent(activeContext.personId)}` : '';
  const heading = view === 'home' ? `Good afternoon, ${viewer.name}` : 'Nutrición';
  return (
    <>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{heading}</h1>
          <div className={styles.contextSwitcher}>
            <DefaultRelationshipSwitcher
              contexts={availableContexts}
              activeContextId={activeContext.personId}
              onSelectContext={setContext}
            />
          </div>
        </div>
      </header>
      {view !== 'home' && (
        <nav lang="es" aria-label="Nutrición" className={styles.pageLinks}>
          {TABS.map((tab) => (
            <a
              key={tab.view}
              href={`${HUB_BASE_PATH}${tab.path}${person}`}
              aria-current={tab.view === view ? 'page' : undefined}
            >
              {tab.label}
            </a>
          ))}
        </nav>
      )}
    </>
  );
}

'use client';

import { useSearchParams } from 'next/navigation';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import { HUB_BASE_PATH } from '@/integration/basePath';
import styles from './page.module.css';

export function NutritionHeader({ view }: { view: 'home' | 'diary' | 'profile' }) {
  const { activeContext, setContext, availableContexts, viewer } = useAppContext();
  const selected = useSearchParams().has('person');
  const person = selected ? `?person=${encodeURIComponent(activeContext.personId)}` : '';
  const heading = view === 'home' ? `Good afternoon, ${viewer.name}` : view === 'profile' ? 'Perfil y objetivos' : 'Nutrición';
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
          {view === 'profile' ? (
            <a href={`${HUB_BASE_PATH}/nutrition/hoy${person}`}>Hoy</a>
          ) : (
            <>
              <a href={`${HUB_BASE_PATH}/nutrition${person}`}>Perfil y objetivos</a>
              <a href="#acciones-en-telegram" onClick={(event) => {
                const section = document.getElementById('acciones-en-telegram');
                if (!section) return;
                event.preventDefault();
                section.focus({ preventScroll: true });
                section.scrollIntoView();
              }}>Acciones en Telegram</a>
            </>
          )}
        </nav>
      )}
    </>
  );
}

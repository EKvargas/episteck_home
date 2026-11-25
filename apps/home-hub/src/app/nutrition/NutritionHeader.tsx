'use client';

import { CaretRight } from '@phosphor-icons/react';
import { useSearchParams } from 'next/navigation';
import { RetryButton } from '@/components/features/nutrition/RetryButton';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import { HUB_BASE_PATH } from '@/integration/basePath';
import { nutritionHref } from '@/integration/nutrition/nutrition-href';
import { UNKNOWN_CHIP, type ProfileChip } from '@/integration/nutrition/profile-chip';
import styles from './page.module.css';

export type NutritionView = 'home' | 'diary' | 'days' | 'profile' | 'detail' | 'help';

const TABS = [
  { view: 'diary', label: 'Hoy', path: '/nutrition/hoy' },
  { view: 'days', label: 'Días', path: '/nutrition/dias' },
] as const;

export function NutritionHeader({ view, chip = UNKNOWN_CHIP, updatedAt = null }: {
  view: NutritionView;
  chip?: ProfileChip;
  updatedAt?: string | null;
}) {
  const { activeContext, setContext, availableContexts, viewer, bootstrap } = useAppContext();
  const selected = useSearchParams().has('person');
  const personId = selected ? activeContext.personId : null;
  const switcher = (
    <div className={styles.contextSwitcher}>
      <DefaultRelationshipSwitcher
        contexts={availableContexts}
        activeContextId={activeContext.personId}
        onSelectContext={setContext}
      />
    </div>
  );

  if (view === 'home') {
    return (
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>{`Good afternoon, ${viewer.name}`}</h1>
          {switcher}
        </div>
      </header>
    );
  }

  const isSubject = activeContext.personId === bootstrap.viewer.personId;
  const chipLabel = chip.kind === 'MODE' ? chip.label : chip.kind === 'PROFILE' ? 'Perfil' : isSubject ? 'Crear perfil' : 'Sin perfil';
  return (
    <div lang="es" className={styles.sharedHeader}>
      <div className={styles.titleRow}>
        <h1 className={styles.title}>Nutrición</h1>
        {chip.kind === 'NONE' && !isSubject ? (
          <span className={styles.profileChipStatic} data-testid="profile-chip">{chipLabel}</span>
        ) : (
          <a
            className={styles.profileChip}
            data-testid="profile-chip"
            href={nutritionHref('/nutrition/perfil', personId)}
            aria-current={view === 'profile' ? 'page' : undefined}
          >
            {chipLabel}
            <CaretRight aria-hidden="true" weight="bold" size={14} />
          </a>
        )}
      </div>
      {availableContexts.length > 1 && switcher}
      <nav aria-label="Nutrición" className={styles.pageLinks}>
        {TABS.map((tab) => (
          <a
            key={tab.view}
            href={`${HUB_BASE_PATH}${tab.path}${personId ? `?person=${encodeURIComponent(personId)}` : ''}`}
            aria-current={tab.view === view || (view === 'detail' && tab.view === 'days') ? 'page' : undefined}
          >
            {tab.label}
          </a>
        ))}
      </nav>
      {(view === 'diary' || view === 'days' || view === 'detail') && updatedAt !== null && (
        <p className={styles.updated}>
          <span>Actualizado {updatedAt}</span>
          <RetryButton label="Actualizar" pendingLabel="Actualizando…" className={styles.refreshSmall} />
        </p>
      )}
    </div>
  );
}

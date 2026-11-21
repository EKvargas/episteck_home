'use client';

import Link from 'next/link';
import { useAppContext } from '@/components/providers/AppProvider';
import styles from './HomeNutritionLinks.module.css';

export function HomeNutritionLinks() {
  const { activeContext } = useAppContext();
  const diary = { pathname: '/nutrition/hoy', query: { person: activeContext.personId } };

  return (
    <nav className={styles.links} lang="es" aria-label="Diario de nutrición">
      <Link href={diary} prefetch={false}>Abrir diario de nutrición</Link>
    </nav>
  );
}

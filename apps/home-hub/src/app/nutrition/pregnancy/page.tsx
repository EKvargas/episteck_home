'use client';

import React from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import { getMicronutrientCoverageMock } from '@/domain/mocks';
import { CoverageCard } from '@/components/features/nutrition/CoverageCard';
import styles from './page.module.css';

export default function PregnancyNutritionPage() {
  const { currentContext } = useAppContext();
  
  // Fetch mock data based on current context
  const coverageData = getMicronutrientCoverageMock(currentContext.id);

  return (
    <div className={styles.pageContainer}>
      <header className={styles.header}>
        <h1 className={styles.title}>Micronutrient Coverage</h1>
        <p className={styles.subtitle}>
          Focusing on key nutrients for maternal wellness
        </p>
      </header>

      <main className={styles.dashboardGrid}>
        <CoverageCard coverage={coverageData} />
      </main>
    </div>
  );
}

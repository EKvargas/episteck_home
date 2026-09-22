'use client';

import React from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import { getMicronutrientCoverageMock } from '@/domain/mocks';
import { CoverageCard } from '@/components/features/nutrition/CoverageCard';
import styles from './page.module.css';

export default function PregnancyNutritionPage() {
  const { activeContext } = useAppContext();
  
  // Fetch mock data based on current context
  const coverageData = getMicronutrientCoverageMock(activeContext.id);

  return (
    <div className={styles.pageContainer}>
      <header className={styles.header}>
        <h1 className={styles.title}>Micronutrient Coverage</h1>
        <p className={styles.subtitle}>
          Focusing on key nutrients for maternal wellness
        </p>
      </header>

      <main>
        <div style={{ marginBottom: '2rem', padding: '1rem', background: 'var(--olin-surface-hover)', borderRadius: '8px', fontSize: '0.85rem', color: 'var(--olin-text-muted)' }}>
          <strong>Note:</strong> Dietary intake does not determine nutrient status on its own. Lab values such as hemoglobin and ferritin belong to Health data.
        </div>

        {/* Hero Section - Iron */}
        <div style={{ marginBottom: '2rem' }}>
          {coverageData.filter(c => c.id === 'iron').map(coverage => (
            <CoverageCard key={coverage.id} coverage={coverage} variant="detailed" />
          ))}
        </div>

        {/* Compact Grid Section - Other Nutrients */}
        <div className={styles.dashboardGrid}>
          {coverageData.filter(c => c.id !== 'iron').map(coverage => (
            <CoverageCard key={coverage.id} coverage={coverage} variant="compact" />
          ))}
        </div>
      </main>
    </div>
  );
}

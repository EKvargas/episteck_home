'use client';

import React from 'react';
import Link from 'next/link';
import { useAppContext } from '@/components/providers/AppProvider';
import { getDemoContextId, getMicronutrientCoverageMock } from '@/domain/mocks';
import { CoverageCard } from '@/components/features/nutrition/CoverageCard';
import styles from './page.module.css';

export default function PregnancyNutritionPage() {
  const { activeContext } = useAppContext();
  
  // Fetch mock data based on current context
  const coverageData = getMicronutrientCoverageMock(getDemoContextId(activeContext.mode));

  if (activeContext.mode !== 'CARE_FOR_ANOTHER_PERSON') {
    return (
      <div className={styles.pageContainer}>
        <header className={styles.header}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <h2>Pregnancy Nutrition</h2>
            <div style={{ display: 'flex', gap: '1rem' }}>
              <Link href="/nutrition" style={{ textDecoration: 'none', color: 'var(--olin-accent)' }}>
                ← Back to Nutrition
              </Link>
            </div>
          </div>
        </header>
        <main style={{ padding: '4rem 2rem', textAlign: 'center' }}>
          <div style={{ background: 'var(--olin-surface-hover)', padding: '3rem', borderRadius: '12px', display: 'inline-block' }}>
            <h3 style={{ margin: '0 0 1rem 0' }}>Pregnancy Nutrition</h3>
            <p style={{ color: 'var(--olin-text-muted)', margin: 0 }}>
              Pregnancy Nutrition is currently available in Ana&apos;s care context.
            </p>
            {/* 
              Context usage comment (Product Owner requirement):
              `activeContext` is used here purely as a UI/demo routing mechanism to show 
              Ana's specific dashboard in the prototype. It is NOT an authorization decision.
            */}
          </div>
        </main>
      </div>
    );
  }

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

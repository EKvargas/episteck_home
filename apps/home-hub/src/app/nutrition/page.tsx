'use client';

import React from 'react';
import { Database, LockKey, Basket, Fire, Drop } from '@phosphor-icons/react';
import { useAppContext } from '@/components/providers/AppProvider';
import { getTodaySummaryMock } from '@/domain/mocks';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import Link from 'next/link';
import styles from './page.module.css';

export default function NutritionPage() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  const data = getTodaySummaryMock(activeContext.id);

  // Architecture check: if context has no nutrition AND no meal plan, it's restricted or unavailable.
  const hasNutrition = !!data.nutrition;
  const hasMeal = !!data.familyMeal;
  const isFamilyContext = activeContext.mode === 'FAMILY';

  return (
    <div className={styles.nutritionCanvas}>
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Nutrition Hub</h1>
          <div style={{ marginTop: '0.75rem' }}>
            <DefaultRelationshipSwitcher
              contexts={availableContexts}
              activeContextId={activeContext.id}
              onSelectContext={(id) => setContext(id)}
            />
          </div>
        </div>
        
        {hasNutrition && (
          <div className={styles.provenanceBadge} title="Canonical data source">
            <Database size={16} weight="fill" />
            <span className={styles.provenanceText}>Source: </span>svc-nutrition
          </div>
        )}
      </header>

      <main className={styles.grid}>
        {hasNutrition ? (
          <>
            {/* Caloric Hero */}
            <div className={`${styles.card} ${styles.heroCard}`}>
              <div 
                className={styles.calorieRing}
                style={{
                  background: `conic-gradient(var(--olin-accent) ${(data.nutrition!.calories / data.nutrition!.targetCalories) * 100}%, var(--olin-badge-bg) 0)`
                }}
              >
                <div className={styles.calorieInner}>
                  <span className={styles.calorieValue}>{data.nutrition!.calories}</span>
                  <span className={styles.calorieLabel}>/ {data.nutrition!.targetCalories} kcal</span>
                </div>
              </div>
              
              <div style={{ display: 'flex', gap: '3rem', marginTop: '1.5rem', width: '100%', justifyContent: 'center' }}>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                    <Fire size={20} weight="duotone" color="var(--olin-accent)" />
                    {data.nutrition!.burnedCalories}
                  </div>
                  <div className={styles.calorieLabel}>Burned</div>
                </div>
                <div style={{ textAlign: 'center' }}>
                  <div style={{ fontSize: '1.5rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                    <Drop size={20} weight="duotone" color="var(--olin-accent)" />
                    {data.nutrition!.hydrationLiters}L
                  </div>
                  <div className={styles.calorieLabel}>Hydration</div>
                </div>
              </div>
            </div>

            {/* Macros */}
            <div className={styles.card}>
              <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.125rem' }}>Protein</h3>
              <div>
                <div className={styles.macroLabel}>
                  <span>Consumed</span>
                  <span>{data.nutrition!.proteinConsumedGrams} / {data.nutrition!.proteinTargetGrams} g</span>
                </div>
                <div className={styles.macroBar}>
                  <div 
                    className={styles.macroFill} 
                    style={{ width: `${Math.min(100, (data.nutrition!.proteinConsumedGrams / data.nutrition!.proteinTargetGrams) * 100)}%` }}
                  />
                </div>
              </div>
            </div>

            <div className={styles.card}>
              <h3 style={{ margin: '0 0 1rem 0', fontSize: '1.125rem' }}>Carbs</h3>
              <div>
                <div className={styles.macroLabel}>
                  <span>Consumed</span>
                  <span>{data.nutrition!.carbsConsumedGrams} / {data.nutrition!.carbsTargetGrams} g</span>
                </div>
                <div className={styles.macroBar}>
                  <div 
                    className={styles.macroFill} 
                    style={{ width: `${Math.min(100, (data.nutrition!.carbsConsumedGrams / data.nutrition!.carbsTargetGrams) * 100)}%` }}
                  />
                </div>
              </div>
            </div>

            {/* Maternal Health Link for Ana Context */}
            {activeContext.id === 'PSN-ana' && (
              <div className={styles.card} style={{ gridColumn: '1 / -1', background: 'var(--olin-badge-bg)', border: '1px solid var(--olin-accent)' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <div>
                    <h3 style={{ margin: 0, fontSize: '1.25rem' }}>Maternal Health & Micronutrients</h3>
                    <p style={{ color: 'var(--olin-text-muted)', margin: '0.25rem 0 0' }}>Track prenatal vitamins, iron, and key pregnancy nutrients.</p>
                  </div>
                  <Link href="/nutrition/pregnancy" style={{ padding: '0.75rem 1.5rem', background: 'var(--olin-accent)', color: 'white', borderRadius: '8px', textDecoration: 'none', fontWeight: 500 }}>
                    View Dashboard
                  </Link>
                </div>
              </div>
            )}
          </>
        ) : !isFamilyContext ? (
          <div className={styles.lockedState}>
            <LockKey size={48} weight="duotone" />
            <span className={styles.lockedText}>Consent required to view clinical nutrition</span>
            <span style={{ fontSize: '0.875rem' }}>This domain requires an explicit ConsentGrant from the Control Plane.</span>
          </div>
        ) : null}

        {/* Mealie Integration (Family Context) */}
        {hasMeal && (
          <div className={styles.card} style={{ gridColumn: '1 / -1', borderLeft: '4px solid var(--olin-accent)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '1rem' }}>
              <div>
                <h3 style={{ margin: 0, fontSize: '1.25rem' }}>{data.familyMeal!.dishTitle}</h3>
                <p style={{ color: 'var(--olin-text-muted)', margin: '0.5rem 0 1rem', maxWidth: '600px' }}>{data.familyMeal!.description}</p>
                <div style={{ display: 'flex', gap: '1rem', fontSize: '0.875rem', fontWeight: 500, flexWrap: 'wrap' }}>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'var(--olin-badge-bg)', padding: '4px 10px', borderRadius: '999px' }}>
                    <Basket size={16} /> {data.familyMeal!.groceryItemsCount} items in cart
                  </span>
                  <span style={{ display: 'flex', alignItems: 'center', gap: '6px', background: 'var(--olin-badge-bg)', padding: '4px 10px', borderRadius: '999px' }}>
                    Prep: {data.familyMeal!.time}
                  </span>
                </div>
              </div>
              <div className={styles.provenanceBadge} title="Integration provider">
                <Database size={16} weight="fill" />
                Provider: {data.familyMeal!.source}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

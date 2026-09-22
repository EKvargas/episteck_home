// src/components/slots/editorial/EditorialWellbeingNutrition.tsx
'use client';
import React from 'react';
import { Heartbeat, Stethoscope } from '@phosphor-icons/react';
import { WellbeingNutritionProps } from '../types';
import styles from './EditorialWellbeingNutrition.module.css';

export function EditorialWellbeingNutrition({
  personContext,
  title,
  subtitle,
  targetTag,
  nutrition,
  care,
  familyMeal,
  onOpenAskOlin,
}: WellbeingNutritionProps) {
  return (
    <div className={styles.card}>
      <div className={styles.headerRow}>
        <div className={styles.titleArea}>
          <div className={styles.iconBadge} aria-hidden="true">
            <Heartbeat size={16} weight="bold" />
          </div>
          <div>
            <h2 className={styles.titleText}>{title}</h2>
            <p className={styles.subtitleText}>{subtitle}</p>
          </div>
        </div>
        <div className={styles.targetTag}>
          <span className={styles.targetDot} aria-hidden="true" />
          <span>{targetTag}</span>
        </div>
      </div>

      {/* Erick Mode: Nutrition & Caloric Gauge */}
      {personContext === 'erick' && nutrition && (
        <div className={styles.erickGrid}>
          {/* Caloric Gauge Visualization */}
          <div className={styles.gaugeContainer}>
            <div className={styles.svgWrapper}>
              <svg className={styles.gaugeSvg} viewBox="0 0 100 100">
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="#eee9dc"
                  strokeWidth="8"
                  fill="transparent"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="#781c22"
                  strokeWidth="8"
                  strokeDasharray="251.2"
                  strokeDashoffset={
                    251.2 -
                    251.2 * Math.min(nutrition.calories / nutrition.targetCalories, 1)
                  }
                  strokeLinecap="square"
                  fill="transparent"
                />
              </svg>
              <div className={styles.gaugeCenter}>
                <span className={styles.calorieNumber}>
                  {nutrition.calories.toLocaleString('en-US')}
                </span>
                <span className={styles.calorieTarget}>
                  / {nutrition.targetCalories.toLocaleString('en-US')} KCAL
                </span>
                <span className={styles.fuelBadge}>
                  {Math.round((nutrition.calories / nutrition.targetCalories) * 100)}% FUEL
                </span>
              </div>
            </div>
            <div className={styles.gaugeStats}>
              BURN: {nutrition.burnedCalories.toLocaleString('en-US')} KCAL · HYDRATION: {nutrition.hydrationLiters} L
            </div>
          </div>

          {/* Macros & Quick Log */}
          <div className={styles.macrosCol}>
            {/* Protein */}
            <div className={styles.macroItem}>
              <div className={styles.macroHeader}>
                <span>PROTEIN REMAINING</span>
                <span className={styles.macroRemaining}>
                  {nutrition.proteinRemainingGrams} G ({nutrition.proteinConsumedGrams}G MET)
                </span>
              </div>
              <div className={styles.progressBarTrack}>
                <div
                  className={styles.progressBarFillProtein}
                  style={{
                    width: `${Math.min(
                      (nutrition.proteinConsumedGrams / nutrition.proteinTargetGrams) * 100,
                      100
                    )}%`,
                  }}
                />
              </div>
            </div>

            {/* Carbs */}
            <div className={styles.macroItem}>
              <div className={styles.macroHeader}>
                <span>COMPLEX CARBOHYDRATES</span>
                <span className={styles.macroRemaining} style={{ color: '#141414' }}>
                  {nutrition.carbsConsumedGrams} G / {nutrition.carbsTargetGrams} G
                </span>
              </div>
              <div className={styles.progressBarTrack}>
                <div
                  className={styles.progressBarFillCarbs}
                  style={{
                    width: `${Math.min(
                      (nutrition.carbsConsumedGrams / nutrition.carbsTargetGrams) * 100,
                      100
                    )}%`,
                  }}
                />
              </div>
            </div>

            {/* Quick Logging Banner */}
            <div className={styles.quickLogBanner}>
              <span>Quick Ledger Entry</span>
              <button
                type="button"
                onClick={() => onOpenAskOlin('Log dinner nutrition')}
                className={styles.quickLogButton}
              >
                + LOG NUTRITION
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ana Mode: Care Circle & Clinical */}
      {personContext === 'ana' && care && (
        <div className={styles.anaCareArea}>
          <div className={styles.anaAppointmentBanner}>
            <div className={styles.anaIconBox}>
              <Stethoscope size={20} weight="bold" />
            </div>
            <div className={styles.anaDetails}>
              <h4 className={styles.anaTitle}>
                {care.consultation.time} Consultation — {care.consultation.doctor}
              </h4>
              <p className={styles.anaSubtitle}>{care.consultation.description}</p>
              <div className={styles.anaActionRow}>
                <button
                  type="button"
                  onClick={() => onOpenAskOlin('Send Ana a supportive note')}
                  className={styles.anaButton}
                >
                  TRANSMIT CHIME
                </button>
                <span className={styles.anaNextCheckup}>
                  Next entry: {care.consultation.nextCheckup}
                </span>
              </div>
            </div>
          </div>

          <div className={styles.anaVitalsGrid}>
            <div className={styles.anaVitalCard}>
              <span className={styles.anaVitalLabel}>Rest Rhythm</span>
              <p className={styles.anaVitalVal}>{care.restRhythm.hoursSleep}</p>
              <span className={styles.anaVitalSub}>{care.restRhythm.status}</span>
            </div>
            <div className={styles.anaVitalCard}>
              <span className={styles.anaVitalLabel}>Hydration Metric</span>
              <p className={styles.anaVitalVal}>
                {care.hydration.litersCurrent} L / {care.hydration.litersTarget} L
              </p>
              <span className={styles.anaVitalSub} style={{ color: '#781c22' }}>
                {care.hydration.percentage}% of target
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Family Mode: Mealie Meal Plan */}
      {personContext === 'family' && familyMeal && (
        <div className={styles.familyDiningCard}>
          <div className={styles.familyLeft}>
            <div className={styles.familyPotIcon}>🍲</div>
            <div>
              <span className={styles.mealTimeTag}>{familyMeal.timeTag}</span>
              <h4 className={styles.mealName}>{familyMeal.dishTitle}</h4>
              <p className={styles.mealDesc}>{familyMeal.description}</p>
            </div>
          </div>

          <div className={styles.familyActionRow}>
            <button
              type="button"
              onClick={() => onOpenAskOlin('Show dinner grocery checklist')}
              className={styles.familyListBtn}
            >
              Grocery ({familyMeal.groceryItemsCount})
            </button>
            <button
              type="button"
              onClick={() => onOpenAskOlin('Set dinner countdown timer')}
              className={styles.familyCountdownBtn}
            >
              PREP TIMER
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

'use client';
import React from 'react';
import { Heartbeat, Stethoscope } from '@phosphor-icons/react';
import { WellbeingNutritionProps } from '../types';
import styles from './AmbientWellbeingNutrition.module.css';

export function AmbientWellbeingNutrition({
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
            <Heartbeat size={18} weight="bold" />
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
                  stroke="rgba(255, 255, 255, 0.1)"
                  strokeWidth="8"
                  fill="transparent"
                />
                <circle
                  cx="50"
                  cy="50"
                  r="40"
                  stroke="var(--olin-accent)"
                  strokeWidth="8"
                  strokeDasharray="251.2"
                  strokeDashoffset={251.2 - (251.2 * Math.min(nutrition.calories / nutrition.targetCalories, 1))}
                  strokeLinecap="round"
                  fill="transparent"
                  style={{ filter: 'drop-shadow(0 0 10px var(--olin-accent))' }}
                />
              </svg>
              <div className={styles.gaugeCenter}>
                <span className={styles.calorieNumber}>
                  {nutrition.calories.toLocaleString('en-US')}
                </span>
                <span className={styles.calorieTarget}>
                  / {nutrition.targetCalories.toLocaleString('en-US')} kcal
                </span>
                <span className={styles.fuelBadge}>
                  {Math.round((nutrition.calories / nutrition.targetCalories) * 100)}% Fuel
                </span>
              </div>
            </div>
            <div className={styles.gaugeStats}>
              Burn: {nutrition.burnedCalories.toLocaleString('en-US')} kcal · Hydration: {nutrition.hydrationLiters} L
            </div>
          </div>

          {/* Macros & Quick Log */}
          <div className={styles.macrosCol}>
            <div>
              <div className={styles.macroHeader}>
                <span>Protein Remaining</span>
                <span style={{ color: 'var(--olin-accent)', fontFamily: 'var(--olin-font-mono)' }}>
                  {nutrition.proteinRemainingGrams} g left ({nutrition.proteinConsumedGrams}g consumed)
                </span>
              </div>
              <div className={styles.macroTrack}>
                <div
                  className={styles.macroBarProtein}
                  style={{
                    width: `${Math.min((nutrition.proteinConsumedGrams / nutrition.proteinTargetGrams) * 100, 100)}%`,
                  }}
                />
              </div>
            </div>

            <div>
              <div className={styles.macroHeader}>
                <span>Complex Carbohydrates</span>
                <span style={{ color: '#38bdf8', fontFamily: 'var(--olin-font-mono)' }}>
                  {nutrition.carbsConsumedGrams} g / {nutrition.carbsTargetGrams} g
                </span>
              </div>
              <div className={styles.macroTrack}>
                <div
                  className={styles.macroBarCarbs}
                  style={{
                    width: `${Math.min((nutrition.carbsConsumedGrams / nutrition.carbsTargetGrams) * 100, 100)}%`,
                  }}
                />
              </div>
            </div>

            <div className={styles.quickLogBox}>
              <span style={{ color: 'var(--olin-text-muted)' }}>Quick Logging Engine</span>
              <button
                type="button"
                className={styles.logBtn}
                onClick={() => onOpenAskOlin('Log dinner nutrition')}
              >
                + Log Nutrition
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Ana Mode: Care Circle & Consultation */}
      {personContext === 'ana' && care && (
        <div className={styles.anaCareCol}>
          <div className={styles.careAlertCard}>
            <div className={styles.careIconBadge} aria-hidden="true">
              <Stethoscope size={22} weight="bold" />
            </div>
            <div className={styles.careContent}>
              <h3 className={styles.careCardTitle}>
                {care.consultation.time} Consultation — {care.consultation.doctor}
              </h3>
              <p className={styles.careCardDesc}>
                {care.consultation.description}
              </p>
              <div className={styles.careActionsRow}>
                <button
                  type="button"
                  className={styles.chimeBtn}
                  onClick={() => onOpenAskOlin('Send Ana a supportive note')}
                >
                  Send Supportive Chime
                </button>
                <span className={styles.nextCheckupText}>
                  Next checkup: {care.consultation.nextCheckup}
                </span>
              </div>
            </div>
          </div>

          <div className={styles.anaStatsGrid}>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Rest Rhythm</span>
              <p className={styles.statTileValue}>{care.restRhythm.hoursSleep}</p>
              <span className={styles.statTileSub}>{care.restRhythm.status}</span>
            </div>
            <div className={styles.statTile}>
              <span className={styles.statTileLabel}>Hydration Goal</span>
              <p className={styles.statTileValue}>
                {care.hydration.litersCurrent} L / {care.hydration.litersTarget} L
              </p>
              <span className={styles.statTileSubSky}>
                {care.hydration.percentage}% of daily target
              </span>
            </div>
          </div>
        </div>
      )}

      {/* Family Mode: Household Dining & Mealie Plan */}
      {personContext === 'family' && familyMeal && (
        <div className={styles.familyMealCard}>
          <div className={styles.familyMealLeft}>
            <div className={styles.potIconBox} aria-hidden="true">
              🍲
            </div>
            <div>
              <span className={styles.mealTag}>{familyMeal.timeTag}</span>
              <h3 className={styles.dishTitle}>{familyMeal.dishTitle}</h3>
              <p className={styles.dishDesc}>{familyMeal.description}</p>
            </div>
          </div>

          <div className={styles.familyActions}>
            <button
              type="button"
              className={styles.groceryBtn}
              onClick={() => onOpenAskOlin('Show dinner grocery checklist')}
            >
              Grocery List ({familyMeal.groceryItemsCount} items)
            </button>
            <button
              type="button"
              className={styles.countdownBtn}
              onClick={() => onOpenAskOlin('Set dinner countdown timer')}
            >
              Prep Countdown
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

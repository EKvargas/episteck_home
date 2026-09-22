import React from 'react';
import { MicronutrientCoverage } from '@/domain/types';
import styles from './CoverageCard.module.css';

interface CoverageCardProps {
  coverage: MicronutrientCoverage;
}

export const CoverageCard: React.FC<CoverageCardProps> = ({ coverage }) => {
  // Determine data completeness state
  const compPercent = coverage.dataCompletenessPercentage;
  let compClass = styles.completenessHigh;
  let compLabel = 'Excellent Data';
  
  if (compPercent < 50) {
    compClass = styles.completenessLow;
    compLabel = 'Partial Data';
  } else if (compPercent < 80) {
    compClass = styles.completenessMedium;
    compLabel = 'Good Data';
  }

  // Calculate percentages for the progress bar (Measured vs Estimated vs Unknown)
  const totalAmount = coverage.contributions.reduce((sum, item) => sum + item.amount, 0);
  const measuredAmount = coverage.contributions
    .filter(i => i.quality === 'MEASURED')
    .reduce((sum, item) => sum + item.amount, 0);
  const estimatedAmount = coverage.contributions
    .filter(i => i.quality === 'ESTIMATED')
    .reduce((sum, item) => sum + item.amount, 0);
  
  // Cap at 100% of target for visual rendering
  const maxVisualTarget = Math.max(coverage.targetAmount, totalAmount);
  const measuredPercent = (measuredAmount / maxVisualTarget) * 100;
  const estimatedPercent = (estimatedAmount / maxVisualTarget) * 100;

  return (
    <div className={styles.card}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <h3>{coverage.name} Intake</h3>
          {coverage.trendSummary && <p>{coverage.trendSummary}</p>}
        </div>
        <div className={`${styles.completeness} ${compClass}`}>
          <span>{compPercent}% Logged</span>
        </div>
      </div>

      <div className={styles.metrics}>
        <span className={styles.currentAmount}>{coverage.currentAmount}</span>
        <span className={styles.targetAmount}>/ {coverage.targetAmount} {coverage.unit}</span>
      </div>

      <div className={styles.progressBarContainer}>
        <div 
          className={`${styles.progressSegment} ${styles.progressMeasured}`} 
          style={{ width: `${measuredPercent}%` }}
          title={`Measured: ${measuredAmount}${coverage.unit}`}
        />
        <div 
          className={`${styles.progressSegment} ${styles.progressEstimated}`} 
          style={{ width: `${estimatedPercent}%` }}
          title={`Estimated: ${estimatedAmount}${coverage.unit}`}
        />
      </div>

      <div className={styles.contributions}>
        {coverage.contributions.length === 0 ? (
          <div className={styles.contributionItem}>
            <span className={styles.contributionLabel}>No data logged for today</span>
          </div>
        ) : (
          coverage.contributions.map((contrib, idx) => {
            const isUnknown = contrib.quality === 'UNKNOWN';
            let badgeClass = styles.badgeMeasured;
            if (contrib.quality === 'ESTIMATED') badgeClass = styles.badgeEstimated;
            if (contrib.quality === 'UNKNOWN') badgeClass = styles.badgeUnknown;

            return (
              <div key={idx} className={styles.contributionItem}>
                <div className={styles.contributionLabel}>
                  {contrib.sourceType === 'SUPPLEMENT' ? '💊' : '🥗'}
                  <span>{contrib.label}</span>
                </div>
                <div className={styles.contributionAmount}>
                  {isUnknown ? (
                    <span style={{ color: 'var(--olin-text-secondary)', fontStyle: 'italic' }}>
                      Unknown {coverage.unit}
                    </span>
                  ) : (
                    <span>{contrib.amount} {contrib.unit}</span>
                  )}
                  <span className={`${styles.badge} ${badgeClass}`} style={{ marginLeft: '0.5rem' }}>
                    {contrib.quality}
                  </span>
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
};

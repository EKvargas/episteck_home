import React from 'react';
import { MicronutrientCoverage } from '@/domain/types';
import styles from './CoverageCard.module.css';

interface CoverageCardProps {
  coverage: MicronutrientCoverage;
  variant?: 'detailed' | 'compact';
}

export const CoverageCard: React.FC<CoverageCardProps> = ({ coverage, variant = 'compact' }) => {
  const isDetailed = variant === 'detailed';
  const compPercent = coverage.nutrientDataCoverage;
  const isPartial = compPercent < 100;

  // Calculate percentages for the progress bar
  const maxVisualTarget = Math.max(coverage.targetAmount, coverage.knownIntake);
  const foodPercent = (coverage.knownFoodIntake / maxVisualTarget) * 100;
  const supplementPercent = ((coverage.knownSupplementIntake || 0) / maxVisualTarget) * 100;

  return (
    <div className={styles.card} style={isDetailed ? { gridColumn: '1 / -1', padding: '2rem' } : undefined}>
      <div className={styles.header}>
        <div className={styles.titleGroup}>
          <h3>{coverage.name}</h3>
          {isDetailed && (
            <p style={{ color: 'var(--olin-text-muted)', fontSize: '0.9rem', marginTop: '0.25rem' }}>
              {coverage.targetSource}
            </p>
          )}
        </div>
        <div className={styles.completeness} style={{ background: isPartial ? 'var(--olin-surface-hover)' : 'var(--olin-badge-bg)', color: 'var(--olin-text)' }}>
          <span>Data coverage {compPercent}%</span>
        </div>
      </div>

      <div className={styles.metricsGrid} style={{ display: 'flex', gap: '2rem', marginTop: '1.5rem', flexWrap: 'wrap' }}>
        <div>
          <div style={{ fontSize: '0.85rem', color: 'var(--olin-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            {isPartial ? 'Known Intake' : 'Total Intake'}
          </div>
          <div className={styles.metrics}>
            <span className={styles.currentAmount}>{coverage.knownIntake}</span>
            <span className={styles.targetAmount}>/ {coverage.targetAmount} {coverage.unit}</span>
          </div>
          {isPartial && isDetailed && (
            <div style={{ fontSize: '0.8rem', color: 'var(--olin-warning)', marginTop: '0.25rem', maxWidth: '200px' }}>
              Known intake is below today's configured target, but some data is missing.
            </div>
          )}
        </div>

        {isDetailed && coverage.rolling7DayKnownAverage !== null && (
          <div>
            <div style={{ fontSize: '0.85rem', color: 'var(--olin-text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              7-Day Known Average
            </div>
            <div className={styles.metrics}>
              <span className={styles.currentAmount}>{coverage.rolling7DayKnownAverage}</span>
              <span className={styles.targetAmount}>{coverage.unit}</span>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'var(--olin-text-muted)', marginTop: '0.25rem' }}>
              7-day data coverage: {coverage.rolling7DayDataCoverage}%
            </div>
          </div>
        )}
      </div>

      <div className={styles.progressBarContainer} style={{ marginTop: '1.5rem' }}>
        <div 
          className={styles.progressSegment} 
          style={{ width: `${foodPercent}%`, background: 'var(--olin-accent)' }}
          title={`Food: ${coverage.knownFoodIntake}${coverage.unit}`}
        />
        <div 
          className={styles.progressSegment} 
          style={{ width: `${supplementPercent}%`, background: 'var(--olin-accent-hover)' }}
          title={`Supplement: ${coverage.knownSupplementIntake || 0}${coverage.unit}`}
        />
      </div>

      {isDetailed && (
        <div className={styles.contributions} style={{ marginTop: '2rem' }}>
          <h4 style={{ fontSize: '0.9rem', marginBottom: '1rem', borderBottom: '1px solid var(--olin-border)', paddingBottom: '0.5rem' }}>
            Contributions
          </h4>
          
          <div style={{ marginBottom: '1rem', fontSize: '0.9rem' }}>
            <span style={{ fontWeight: 600 }}>Supplement Status: </span>
            {coverage.supplementStatus === 'LOGGED_KNOWN' && 'Logged & Known'}
            {coverage.supplementStatus === 'EXPLICITLY_NOT_CONSUMED' && 'Explicitly not consumed today'}
            {coverage.supplementStatus === 'NOT_LOGGED_UNKNOWN' && <span style={{ color: 'var(--olin-warning)' }}>Not logged / Unknown</span>}
          </div>

          {coverage.contributions.length === 0 ? (
            <div className={styles.contributionItem}>
              <span className={styles.contributionLabel}>No known data logged for today</span>
            </div>
          ) : (
            coverage.contributions.map((contrib, idx) => {
              return (
                <div key={idx} className={styles.contributionItem} style={{ padding: '0.5rem 0', display: 'flex', justifyContent: 'space-between', borderBottom: '1px solid var(--olin-surface-hover)' }}>
                  <div className={styles.contributionLabel}>
                    {contrib.sourceType === 'SUPPLEMENT' ? '💊 ' : '🥗 '}
                    <span>{contrib.label}</span>
                  </div>
                  <div className={styles.contributionAmount}>
                    {contrib.quality === 'UNKNOWN' ? (
                      <span style={{ color: 'var(--olin-text-muted)', fontStyle: 'italic' }}>
                        Unknown amount
                      </span>
                    ) : (
                      <span>{contrib.amount} {contrib.unit}</span>
                    )}
                    <span style={{ fontSize: '0.75rem', marginLeft: '0.5rem', background: 'var(--olin-surface-hover)', padding: '0.1rem 0.4rem', borderRadius: '4px' }}>
                      {contrib.quality}
                    </span>
                  </div>
                </div>
              );
            })
          )}
          
          {coverage.unknownItems.length > 0 && (
            <div style={{ marginTop: '1rem', padding: '1rem', background: 'var(--olin-surface)', borderRadius: '8px' }}>
              <h5 style={{ margin: '0 0 0.5rem 0', fontSize: '0.85rem', color: 'var(--olin-warning)' }}>Items with missing {coverage.name} data:</h5>
              <ul style={{ margin: 0, paddingLeft: '1.2rem', fontSize: '0.85rem', color: 'var(--olin-text-muted)' }}>
                {coverage.unknownItems.map((item, idx) => (
                  <li key={idx}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

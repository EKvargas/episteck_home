// src/components/features/MemoryAttention.tsx
'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { 
  Sparkle, 
  ArrowClockwise, 
  Users, 
  Check, 
  X, 
  ArrowRight, 
  CheckCircle,
  Clock
} from '@phosphor-icons/react';
import { TodayAttentionItem } from '@/domain/memoryMocks';
import styles from './MemoryAttention.module.css';

interface MemoryAttentionProps {
  item: TodayAttentionItem | null;
  onDismiss?: (id: string) => void;
  onAccept?: (item: TodayAttentionItem) => void;
  onInspect?: (item: TodayAttentionItem) => void;
}

export function MemoryAttention({
  item,
  onDismiss,
  onAccept,
  onInspect,
}: MemoryAttentionProps) {
  const [feedback, setFeedback] = useState<string | null>(null);

  // Core Principle: Memory is quiet by default. If no action is needed, render nothing!
  if (!item) {
    return null;
  }

  const handleAction = (type: 'ACCEPT' | 'REJECT' | 'KEEP_OLD') => {
    if (type === 'ACCEPT') {
      const msg = item.type === 'CORRECTION' 
        ? 'Preference updated in Olin’s Memory' 
        : item.type === 'SHARED'
        ? 'Shared decision acknowledged'
        : 'Saved to your active Memory';
      setFeedback(msg);
      onAccept?.(item);
    } else if (type === 'KEEP_OLD') {
      setFeedback('Kept previous memory intact');
    } else {
      setFeedback('Dismissed');
    }

    setTimeout(() => {
      setFeedback(null);
      onDismiss?.(item.id);
    }, 1200);
  };

  if (feedback) {
    return (
      <div className={styles.feedbackCard} role="status" aria-live="polite">
        <CheckCircle size={20} weight="fill" color="var(--olin-status-success)" />
        <span>{feedback}</span>
      </div>
    );
  }

  const getBadgeIcon = () => {
    switch (item.type) {
      case 'SUGGESTION':
        return <Sparkle size={13} weight="fill" />;
      case 'CORRECTION':
        return <ArrowClockwise size={13} weight="bold" />;
      case 'SHARED':
        return <Users size={13} weight="fill" />;
    }
  };

  const getBadgeClass = () => {
    switch (item.type) {
      case 'SUGGESTION': return styles.badgeSuggestion;
      case 'CORRECTION': return styles.badgeCorrection;
      case 'SHARED': return styles.badgeShared;
    }
  };

  return (
    <article 
      className={styles.attentionCard} 
      data-item-type={item.type}
      aria-label={`${item.badgeLabel}: ${item.title}`}
    >
      {/* Header with pill and subject label */}
      <div className={styles.cardHeader}>
        <div className={styles.badgeRow}>
          <span className={`${styles.badge} ${getBadgeClass()}`}>
            {getBadgeIcon()}
            {item.badgeLabel}
          </span>
          <span className={styles.subjectPill}>
            About {item.subjectLabel}
          </span>
        </div>

        <button 
          type="button"
          onClick={() => handleAction('REJECT')}
          className={styles.dismissBtn}
          title="Dismiss this insight"
          aria-label="Dismiss insight"
        >
          <X size={15} weight="bold" />
        </button>
      </div>

      {/* Body: Statement and Diff/Explanation */}
      <div className={styles.bodyContent}>
        {item.type === 'CORRECTION' ? (
          <>
            <h3 className={styles.statement}>Update a preference?</h3>
            <div className={styles.diffBox}>
              <div className={styles.diffRow}>
                <span className={styles.diffLabelOld}>Before</span>
                <span className={styles.diffTextOld}>{item.previousStatement}</span>
              </div>
              <div className={styles.diffRow}>
                <span className={styles.diffLabelNew}>Now</span>
                <span className={styles.diffTextNew}>{item.statement}</span>
              </div>
            </div>
            <p className={styles.explanation}>{item.explanation}</p>
          </>
        ) : (
          <>
            <p className={styles.statement}>&ldquo;{item.statement}&rdquo;</p>
            <p className={styles.explanation}>{item.explanation}</p>
          </>
        )}
      </div>

      {/* Action Row */}
      <div className={styles.actionRow}>
        {item.type === 'SUGGESTION' && (
          <>
            <button 
              type="button" 
              className={styles.primaryAction}
              onClick={() => handleAction('ACCEPT')}
            >
              <Check size={14} weight="bold" />
              Remember this
            </button>
            <button 
              type="button" 
              className={styles.secondaryAction}
              onClick={() => handleAction('REJECT')}
            >
              Not really
            </button>
            <Link 
              href="/memory"
              className={styles.textAction}
              onClick={() => onInspect?.(item)}
            >
              Review detail <ArrowRight size={12} weight="bold" />
            </Link>
          </>
        )}

        {item.type === 'CORRECTION' && (
          <>
            <button 
              type="button" 
              className={styles.primaryAction}
              onClick={() => handleAction('ACCEPT')}
            >
              <Check size={14} weight="bold" />
              Accept update
            </button>
            <button 
              type="button" 
              className={styles.secondaryAction}
              onClick={() => handleAction('KEEP_OLD')}
            >
              Keep previous
            </button>
            <Link 
              href="/memory"
              className={styles.textAction}
              onClick={() => onInspect?.(item)}
            >
              Inspect change <ArrowRight size={12} weight="bold" />
            </Link>
          </>
        )}

        {item.type === 'SHARED' && (
          <>
            <Link 
              href="/memory"
              className={styles.primaryAction}
              style={{ textDecoration: 'none' }}
              onClick={() => onInspect?.(item)}
            >
              <Users size={14} weight="fill" />
              Review shared decision
            </Link>
            <span style={{ fontSize: '0.75rem', color: 'var(--olin-text-muted)', display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
              <Clock size={13} /> Waiting for Ana
            </span>
          </>
        )}
      </div>
    </article>
  );
}

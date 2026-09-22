// src/app/memory/page.tsx
'use client';

import React, { useState } from 'react';
import { 
  Sparkle, 
  ChatCircle, 
  Users, 
  CheckCircle, 
  ClockCounterClockwise, 
  X, 
  Trash, 
  Clock, 
  Check, 
  ArrowClockwise,
  ArrowRight,
  ShieldCheck
} from '@phosphor-icons/react';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import { memoryMocks, MemoryClaim } from '@/domain/memoryMocks';
import styles from './page.module.css';

export default function MemoryPage() {
  const { activeContext, setContext, availableContexts } = useAppContext();

  // Filter memories based on active context
  const getInitialMemories = (contextMode: string) => {
    if (contextMode === 'FAMILY') {
      return memoryMocks.filter(m => m.visibility === 'HOUSEHOLD');
    }
    // Default personal context: show Erick's personal memories + shared household
    return memoryMocks.filter(m => m.subjectLabel === 'Erick' || m.visibility === 'HOUSEHOLD');
  };

  const [localMemories, setLocalMemories] = useState<MemoryClaim[]>(() => 
    getInitialMemories(activeContext.mode)
  );
  const [prevContextId, setPrevContextId] = useState(activeContext.id);

  // Sync state if context switcher changes
  if (activeContext.id !== prevContextId) {
    setPrevContextId(activeContext.id);
    setLocalMemories(getInitialMemories(activeContext.mode));
  }

  const [selectedMemory, setSelectedMemory] = useState<MemoryClaim | null>(null);
  const [forgetConfirm, setForgetConfirm] = useState(false);
  const [feedbackToast, setFeedbackToast] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setFeedbackToast(msg);
    setTimeout(() => setFeedbackToast(null), 2500);
  };

  // Memory segments
  const proposed = localMemories.filter(m => m.status === 'PROPOSED');
  const active = localMemories.filter(m => m.status === 'ACTIVE');
  const history = localMemories.filter(m => 
    m.status === 'SUPERSEDED' || m.status === 'EXPIRED' || m.status === 'FORGOTTEN'
  );

  // Provenance helpers
  const getProvenanceText = (prov: string) => {
    switch (prov) {
      case 'USER_EXPLICIT': return 'You told Olin';
      case 'USER_CONFIRMED': return 'Confirmed by you';
      case 'AI_HYPOTHESIS': return 'Olin noticed';
      case 'SYSTEM_OBSERVED': return 'Household routine';
      default: return 'Learned';
    }
  };

  const getProvenanceIcon = (prov: string, size = 15) => {
    switch (prov) {
      case 'USER_EXPLICIT':
      case 'USER_CONFIRMED': return <ChatCircle size={size} />;
      case 'AI_HYPOTHESIS': return <Sparkle size={size} weight="fill" />;
      case 'SYSTEM_OBSERVED': return <Clock size={size} />;
      default: return <ShieldCheck size={size} />;
    }
  };

  // Interactive quick actions for proposed memories
  const handleQuickAccept = (e: React.MouseEvent, memoryId: string) => {
    e.stopPropagation();
    setLocalMemories(prev => prev.map(m => {
      if (m.id === memoryId) {
        return {
          ...m,
          status: 'ACTIVE',
          provenance: 'USER_CONFIRMED',
          sourceContext: 'Confirmed on ' + new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
        };
      }
      return m;
    }));
    showToast('Saved to active Memory');
  };

  const handleQuickReject = (e: React.MouseEvent, memoryId: string) => {
    e.stopPropagation();
    setLocalMemories(prev => prev.filter(m => m.id !== memoryId));
    showToast('Suggestion dismissed');
  };

  const handleForget = () => {
    if (selectedMemory) {
      const forgottenId = selectedMemory.id;
      setLocalMemories(prev => prev.map(m => {
        if (m.id === forgottenId) {
          return {
            ...m,
            status: 'FORGOTTEN',
            historyReason: 'FORGOTTEN',
            historyReasonText: `Forgotten on ${new Date().toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} by ${selectedMemory.subjectLabel}.`,
          };
        }
        return m;
      }));
      setSelectedMemory(null);
      setForgetConfirm(false);
      showToast('Memory forgotten — Olin will no longer use this');
    }
  };

  const handleConfirmProposedFromModal = () => {
    if (selectedMemory) {
      setLocalMemories(prev => prev.map(m => {
        if (m.id === selectedMemory.id) {
          return {
            ...m,
            status: 'ACTIVE',
            provenance: 'USER_CONFIRMED',
            sourceContext: 'Confirmed in Memory Hub',
          };
        }
        return m;
      }));
      setSelectedMemory(null);
      showToast('Memory confirmed and activated');
    }
  };

  // Card component
  const MemoryCard = ({ m }: { m: MemoryClaim }) => {
    const isSuggested = m.status === 'PROPOSED';
    const isHistory = m.status === 'SUPERSEDED' || m.status === 'EXPIRED' || m.status === 'FORGOTTEN';

    return (
      <div 
        className={`${styles.card} ${isSuggested ? styles.cardSuggested : ''} ${isHistory ? styles.cardSuperseded : ''}`}
        onClick={() => setSelectedMemory(m)}
        role="button"
        tabIndex={0}
      >
        <div>
          <div className={styles.statement}>
            &ldquo;{m.statement}&rdquo;
          </div>

          {/* History human-readable reason note */}
          {isHistory && m.historyReasonText && (
            <div className={styles.historyReasonNote}>
              {m.historyReasonText}
            </div>
          )}
        </div>

        <div className={styles.cardFooter}>
          <div className={styles.badgeGroup}>
            {/* Provenance / Status badge */}
            <span className={`${styles.badge} ${isSuggested ? styles.badgeSuggested : ''}`}>
              {getProvenanceIcon(m.provenance)}
              {isSuggested ? 'Suggested' : m.category}
            </span>

            {/* Subject Label */}
            <span className={styles.subjectBadge}>
              {m.visibility === 'HOUSEHOLD' ? (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                  <Users size={12} weight="fill" /> Household · {m.subjectLabel}
                </span>
              ) : (
                `About ${m.subjectLabel}`
              )}
            </span>

            {/* History Reason Badge */}
            {m.historyReason === 'UPDATED' && (
              <span className={`${styles.badge} ${styles.historyTagUpdated}`}>
                <ArrowClockwise size={11} weight="bold" /> Replaced
              </span>
            )}
            {m.historyReason === 'EXPIRED' && (
              <span className={`${styles.badge} ${styles.historyTagExpired}`}>
                <Clock size={11} /> Expired
              </span>
            )}
            {m.historyReason === 'FORGOTTEN' && (
              <span className={`${styles.badge} ${styles.historyTagForgotten}`}>
                <Trash size={11} /> Forgotten
              </span>
            )}
          </div>

          <span style={{ fontSize: '0.75rem', color: 'var(--olin-text-muted)' }}>
            {m.createdAt}
          </span>
        </div>

        {/* Suggested Memory Quick Actions Directly on Card */}
        {isSuggested && (
          <div className={styles.cardQuickActions} onClick={e => e.stopPropagation()}>
            <button 
              type="button" 
              className={styles.quickBtnPrimary}
              onClick={(e) => handleQuickAccept(e, m.id)}
            >
              <Check size={13} weight="bold" />
              Remember this
            </button>
            <button 
              type="button" 
              className={styles.quickBtnSecondary}
              onClick={(e) => handleQuickReject(e, m.id)}
            >
              Not true
            </button>
            <button 
              type="button" 
              className={styles.quickBtnReview}
              onClick={() => setSelectedMemory(m)}
            >
              Inspect <ArrowRight size={11} />
            </button>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className={styles.memoryCanvas}>
      {/* Toast */}
      {feedbackToast && (
        <div 
          style={{
            position: 'fixed',
            top: '1.5rem',
            right: '1.5rem',
            zIndex: 120,
            background: 'var(--olin-surface-card)',
            border: '1px solid var(--olin-surface-border)',
            borderRadius: '9999px',
            padding: '0.5rem 1.25rem',
            boxShadow: '0 8px 24px rgba(0,0,0,0.15)',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            fontSize: '0.85rem',
            fontWeight: 600,
            color: 'var(--olin-text-main)',
          }}
        >
          <CheckCircle size={18} weight="fill" color="var(--olin-status-success)" />
          {feedbackToast}
        </div>
      )}

      {/* Header Bar */}
      <header className={styles.header}>
        <div>
          <h1 className={styles.title}>Olin&apos;s Memory</h1>
          <p className={styles.subtitle}>
            Personal preferences and household context that help Olin adapt to your life.
          </p>
          <div style={{ marginTop: '0.75rem' }}>
            <DefaultRelationshipSwitcher
              contexts={availableContexts}
              activeContextId={activeContext.id}
              onSelectContext={(id) => setContext(id)}
            />
          </div>
        </div>
      </header>

      {/* Section 1: Needs Confirmation (AI Suggestions) */}
      {proposed.length > 0 && (
        <section aria-labelledby="needs-confirmation-heading">
          <h2 id="needs-confirmation-heading" className={styles.sectionTitle}>
            <Sparkle size={18} weight="fill" color="var(--olin-accent)" />
            Needs Confirmation
            <span style={{ fontSize: '0.78rem', fontWeight: 500, color: 'var(--olin-text-muted)', marginLeft: '4px' }}>
              ({proposed.length})
            </span>
          </h2>
          <div className={styles.grid}>
            {proposed.map(m => <MemoryCard key={m.id} m={m} />)}
          </div>
        </section>
      )}

      {/* Section 2: Current Context (Active Memories) */}
      {active.length > 0 && (
        <section aria-labelledby="current-context-heading">
          <h2 id="current-context-heading" className={styles.sectionTitle}>
            <CheckCircle size={18} weight="fill" color="var(--olin-status-success)" />
            Current Context
            <span style={{ fontSize: '0.78rem', fontWeight: 500, color: 'var(--olin-text-muted)', marginLeft: '4px' }}>
              ({active.length} active)
            </span>
          </h2>
          <div className={styles.grid}>
            {active.map(m => <MemoryCard key={m.id} m={m} />)}
          </div>
        </section>
      )}

      {/* Section 3: History (No longer used) */}
      {history.length > 0 && (
        <section aria-labelledby="history-heading">
          <h2 id="history-heading" className={styles.sectionTitle}>
            <ClockCounterClockwise size={18} />
            History &amp; Replaced Context
            <span style={{ fontSize: '0.78rem', fontWeight: 500, color: 'var(--olin-text-muted)', marginLeft: '4px' }}>
              ({history.length} inactive)
            </span>
          </h2>
          <div className={styles.grid}>
            {history.map(m => <MemoryCard key={m.id} m={m} />)}
          </div>
        </section>
      )}

      {/* Memory Detail Modal */}
      {selectedMemory && (
        <div 
          className={styles.detailOverlay} 
          onClick={() => { setSelectedMemory(null); setForgetConfirm(false); }}
        >
          <div className={styles.detailModal} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '1rem' }}>
              <h2 style={{ fontSize: '1.35rem', margin: 0, fontWeight: 700, lineHeight: 1.35 }}>
                &ldquo;{selectedMemory.statement}&rdquo;
              </h2>
              <button 
                type="button"
                onClick={() => { setSelectedMemory(null); setForgetConfirm(false); }}
                style={{ background: 'transparent', border: 'none', cursor: 'pointer', color: 'var(--olin-text-muted)', padding: '4px' }}
                aria-label="Close dialog"
              >
                <X size={22} />
              </button>
            </div>
            
            <div style={{ display: 'grid', gap: '0.85rem' }}>
              {/* Context & Scope */}
              <div className={styles.provenanceRow}>
                <span className={styles.provenanceLabel}>Scope &amp; Visibility</span>
                <span className={styles.provenanceValue}>
                  {selectedMemory.visibility === 'HOUSEHOLD' ? (
                    <>
                      <Users size={18} weight="fill" /> Shared with Household
                    </>
                  ) : (
                    <>
                      <ShieldCheck size={18} /> Personal
                    </>
                  )}
                </span>
                <span className={styles.provenanceSub}>
                  Applies to: <strong>{selectedMemory.subjectLabel}</strong> · Category: {selectedMemory.category}
                </span>
              </div>

              {/* Provenance: Why Olin knows this */}
              <div className={styles.provenanceRow}>
                <span className={styles.provenanceLabel}>Why Olin knows this</span>
                <span className={styles.provenanceValue}>
                  {getProvenanceIcon(selectedMemory.provenance, 18)} {getProvenanceText(selectedMemory.provenance)}
                </span>
                <span className={styles.provenanceSub}>
                  {selectedMemory.createdAt} · {selectedMemory.sourceContext}
                  {selectedMemory.inferredConfidence && ` (Confidence: ${selectedMemory.inferredConfidence})`}
                </span>
              </div>

              {/* Correction History Diff */}
              {selectedMemory.replaces && (
                <div className={styles.provenanceRow} style={{ background: 'rgba(245, 158, 11, 0.06)', border: '1px solid rgba(245, 158, 11, 0.25)' }}>
                  <span className={styles.provenanceLabel}>Correction History</span>
                  <div style={{ fontSize: '0.85rem', color: 'var(--olin-text-main)', marginTop: '4px' }}>
                    Replaced previous statement:
                    <div style={{ color: 'var(--olin-text-muted)', textDecoration: 'line-through', marginTop: '2px' }}>
                      &ldquo;{selectedMemory.replacesStatement}&rdquo;
                    </div>
                  </div>
                </div>
              )}

              {/* Superseded By link */}
              {selectedMemory.supersededBy && (
                <div className={styles.provenanceRow} style={{ background: 'rgba(107, 114, 128, 0.06)' }}>
                  <span className={styles.provenanceLabel}>Replaced by newer preference</span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--olin-text-main)', marginTop: '2px' }}>
                    &ldquo;{selectedMemory.supersededByStatement}&rdquo;
                  </span>
                </div>
              )}

              {/* Inactive Reason */}
              {selectedMemory.historyReasonText && (
                <div className={styles.provenanceRow} style={{ background: 'rgba(0, 0, 0, 0.03)' }}>
                  <span className={styles.provenanceLabel}>Reason No Longer Active</span>
                  <span style={{ fontSize: '0.85rem', color: 'var(--olin-text-muted)' }}>
                    {selectedMemory.historyReasonText}
                  </span>
                </div>
              )}
            </div>

            {/* Actions */}
            <div style={{ marginTop: '0.5rem', display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {selectedMemory.status === 'PROPOSED' ? (
                <>
                  <button 
                    type="button"
                    className={`${styles.actionButton} ${styles.btnPrimary}`}
                    onClick={handleConfirmProposedFromModal}
                  >
                    <CheckCircle size={18} weight="fill" />
                    Yes, remember this
                  </button>
                  <button 
                    type="button"
                    className={`${styles.actionButton} ${styles.btnSecondary}`}
                    onClick={handleForget}
                  >
                    Not true
                  </button>
                </>
              ) : selectedMemory.status === 'ACTIVE' ? (
                <>
                  {!forgetConfirm ? (
                    <button 
                      type="button"
                      className={`${styles.actionButton} ${styles.btnDanger}`} 
                      onClick={() => setForgetConfirm(true)}
                    >
                      <Trash size={18} /> Forget this memory
                    </button>
                  ) : (
                    <div style={{ padding: '1rem', background: 'rgba(239, 68, 68, 0.08)', borderRadius: '12px', border: '1px solid rgba(239, 68, 68, 0.25)' }}>
                      <p style={{ margin: '0 0 0.85rem 0', fontSize: '0.85rem', fontWeight: 500, color: 'var(--olin-status-error, #ef4444)', lineHeight: 1.4 }}>
                        Olin will stop using this memory. It will no longer personalize recommendations or responses.
                      </p>
                      <div style={{ display: 'flex', gap: '0.5rem' }}>
                        <button 
                          type="button"
                          className={`${styles.actionButton} ${styles.btnSecondary}`} 
                          onClick={() => setForgetConfirm(false)}
                          style={{ flex: 1 }}
                        >
                          Cancel
                        </button>
                        <button 
                          type="button"
                          className={`${styles.actionButton} ${styles.btnDanger}`} 
                          onClick={handleForget} 
                          style={{ flex: 1, background: '#ef4444', color: '#fff' }}
                        >
                          Confirm Forget
                        </button>
                      </div>
                    </div>
                  )}
                </>
              ) : null}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

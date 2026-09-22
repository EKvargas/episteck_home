// src/app/calendar/page.tsx
'use client';

import React, { useState } from 'react';
import { 
  Calendar as CalendarIcon, 
  CaretLeft, 
  CaretRight, 
  Sparkle, 
  WarningCircle, 
  X, 
  Clock, 
  MapPin, 
  Users, 
  Eye, 
  EyeSlash, 
  CheckCircle,
  Gear,
  AppleLogo,
  GoogleLogo,
  MicrosoftTeamsLogo,
  House
} from '@phosphor-icons/react';
import { useAppContext } from '@/components/providers/AppProvider';
import { DefaultRelationshipSwitcher } from '@/components/slots/default/DefaultRelationshipSwitcher';
import { 
  calendarAccountsMock, 
  calendarEventsMock, 
  calendarInsightsMock, 
  CalendarEvent, 
  CalendarSourceId 
} from '@/domain/calendarMocks';
import styles from './page.module.css';

export default function CalendarPage() {
  const { activeContext, setContext, availableContexts } = useAppContext();

  // Active filters for connected calendar sources
  const [activeSources, setActiveSources] = useState<Record<CalendarSourceId, boolean>>({
    'erick-work': true,
    'erick-personal': true,
    'ana-google': true,
    'ana-icloud': true,
    'household': true,
  });

  // View state: 'dual' (Partner track) | 'agenda' | 'month'
  const [viewMode, setViewMode] = useState<'dual' | 'agenda' | 'month'>('dual');
  
  // Privacy masking for work events in family/shared mode
  const [maskWorkTitles, setMaskWorkTitles] = useState(true);

  // Selected event for detail drawer
  const [selectedEvent, setSelectedEvent] = useState<CalendarEvent | null>(null);

  // Connected accounts modal
  const [showAccountsModal, setShowAccountsModal] = useState(false);

  // Dismissed insights
  const [dismissedInsights, setDismissedInsights] = useState<Record<string, boolean>>({});

  // Active date display
  const currentDateDisplay = 'Friday, Sep 18, 2026';

  // Toggle calendar source filter
  const toggleSource = (sourceId: CalendarSourceId) => {
    setActiveSources(prev => ({
      ...prev,
      [sourceId]: !prev[sourceId],
    }));
  };

  // Filter events based on active source toggles and active context
  const filteredEvents = calendarEventsMock.filter(ev => {
    if (!activeSources[ev.sourceId]) return false;

    // Filter by context
    if (activeContext.mode === 'PERSONAL') {
      // Erick's view: Erick's work, personal, and joint family events
      return ev.owner === 'Erick' || ev.owner === 'Joint';
    }
    if (activeContext.mode === 'CARE_FOR_ANOTHER_PERSON') {
      // Ana's view: Ana's personal, icloud, and joint family events
      return ev.owner === 'Ana' || ev.owner === 'Joint';
    }
    // Family view: shows everything selected in filter
    return true;
  });

  // Partition events for Dual Partner Track
  const erickEvents = filteredEvents.filter(ev => ev.owner === 'Erick');
  const anaEvents = filteredEvents.filter(ev => ev.owner === 'Ana');
  const jointEvents = filteredEvents.filter(ev => ev.owner === 'Joint');

  // Provider icon helper
  const getProviderIcon = (provider: string, size = 14) => {
    switch (provider) {
      case 'google': return <GoogleLogo size={size} weight="bold" />;
      case 'apple': return <AppleLogo size={size} weight="fill" />;
      case 'microsoft': return <MicrosoftTeamsLogo size={size} weight="bold" />;
      case 'olin': return <House size={size} weight="fill" />;
      default: return <CalendarIcon size={size} />;
    }
  };

  return (
    <div className={styles.calendarCanvas}>
      {/* Top Header Bar */}
      <header className={styles.topBar}>
        <div className={styles.titleArea}>
          <h1 className={styles.dateTitle}>
            <CalendarIcon size={24} color="var(--olin-accent)" />
            {currentDateDisplay}
          </h1>
          <span className={styles.subtitle}>
            Unified schedule synchronized across Google, Apple iCloud, and Work
          </span>
        </div>

        {/* Center: Context Switcher */}
        <div>
          <DefaultRelationshipSwitcher
            contexts={availableContexts}
            activeContextId={activeContext.id}
            onSelectContext={(id) => setContext(id)}
          />
        </div>

        {/* Right: Date Navigation & Accounts */}
        <div className={styles.navControls}>
          <button type="button" className={styles.iconBtn} aria-label="Previous day">
            <CaretLeft size={16} weight="bold" />
          </button>
          <button type="button" className={styles.todayBtn}>
            Today
          </button>
          <button type="button" className={styles.iconBtn} aria-label="Next day">
            <CaretRight size={16} weight="bold" />
          </button>

          {/* View Mode Toggle */}
          <div className={styles.viewModes} role="group" aria-label="Calendar view mode">
            <button
              type="button"
              className={`${styles.viewModeBtn} ${viewMode === 'dual' ? styles.viewModeBtnActive : ''}`}
              onClick={() => setViewMode('dual')}
            >
              Partner Dual Track
            </button>
            <button
              type="button"
              className={`${styles.viewModeBtn} ${viewMode === 'agenda' ? styles.viewModeBtnActive : ''}`}
              onClick={() => setViewMode('agenda')}
            >
              Agenda
            </button>
            <button
              type="button"
              className={`${styles.viewModeBtn} ${viewMode === 'month' ? styles.viewModeBtnActive : ''}`}
              onClick={() => setViewMode('month')}
            >
              Month
            </button>
          </div>

          <button
            type="button"
            className={styles.manageSourcesBtn}
            onClick={() => setShowAccountsModal(true)}
            title="Connected Accounts"
          >
            <Gear size={15} />
            Connected Sources (5)
          </button>
        </div>
      </header>

      {/* Multi-Calendar Source Filter Bar */}
      <section className={styles.filterBar} aria-label="Calendar Sources Filter">
        <span className={styles.filterLabel}>Calendars:</span>
        {Object.values(calendarAccountsMock).map(account => {
          const isActive = activeSources[account.id];
          return (
            <button
              key={account.id}
              type="button"
              className={`${styles.sourcePill} ${isActive ? styles.sourcePillActive : styles.sourcePillInactive}`}
              style={{ '--pill-color': account.color } as React.CSSProperties}
              onClick={() => toggleSource(account.id)}
              aria-pressed={isActive}
            >
              <span 
                className={styles.colorDot} 
                style={{ backgroundColor: account.color }}
              />
              {getProviderIcon(account.provider, 13)}
              <span>{account.name}</span>
            </button>
          );
        })}
      </section>

      {/* Privacy Notice / Work Masking Bar */}
      {activeContext.mode === 'FAMILY' && (
        <div className={styles.privacyNoticeBar}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            {maskWorkTitles ? <EyeSlash size={16} /> : <Eye size={16} />}
            <span>
              Work Calendar Privacy: <strong>{maskWorkTitles ? 'Masked as "Busy" in Family View' : 'Full titles visible'}</strong>
            </span>
          </div>
          <button 
            type="button" 
            className={styles.maskToggleBtn}
            onClick={() => setMaskWorkTitles(prev => !prev)}
          >
            {maskWorkTitles ? 'Show full titles' : 'Mask work details'}
          </button>
        </div>
      )}

      {/* Intelligent Household Insight / Conflict Banner */}
      {calendarInsightsMock
        .filter(ins => !dismissedInsights[ins.id])
        .map(ins => {
          const isConflict = ins.type === 'CONFLICT';
          return (
            <aside 
              key={ins.id}
              className={`${styles.insightBanner} ${isConflict ? styles.insightBannerConflict : ''}`}
              role="alert"
            >
              <div className={styles.insightLeft}>
                <div className={styles.insightIconArea}>
                  {isConflict ? (
                    <WarningCircle size={22} weight="fill" color="#ef4444" />
                  ) : (
                    <Sparkle size={22} weight="fill" color="#f59e0b" />
                  )}
                </div>
                <div>
                  <h3 className={styles.insightTitle}>{ins.title}</h3>
                  <p className={styles.insightDesc}>{ins.message}</p>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
                {ins.actionLabel && (
                  <button type="button" className={styles.insightActionBtn}>
                    {ins.actionLabel}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => setDismissedInsights(prev => ({ ...prev, [ins.id]: true }))}
                  style={{ background: 'transparent', border: 'none', color: 'var(--olin-text-muted)', cursor: 'pointer' }}
                  aria-label="Dismiss insight"
                >
                  <X size={16} />
                </button>
              </div>
            </aside>
          );
        })}

      {/* Main View Presentation */}
      {viewMode === 'dual' ? (
        <main className={styles.dualGridContainer}>
          {/* Column 1: Erick's Track */}
          <section className={styles.partnerTrackCard} aria-label="Erick's Schedule">
            <div className={styles.trackHeader}>
              <h2 className={styles.trackOwnerTitle}>
                Erick
                <span className={styles.trackSubTag}>Work &amp; Personal</span>
              </h2>
              <span style={{ fontSize: '0.78rem', color: 'var(--olin-text-muted)', fontWeight: 600 }}>
                {erickEvents.length} events
              </span>
            </div>

            <div className={styles.trackEventList}>
              {erickEvents.length === 0 ? (
                <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--olin-text-muted)', fontSize: '0.85rem' }}>
                  No active events for selected filters.
                </div>
              ) : (
                erickEvents.map(ev => {
                  const account = calendarAccountsMock[ev.sourceId];
                  const displayTitle = (activeContext.mode === 'FAMILY' && maskWorkTitles && ev.sourceId === 'erick-work' && ev.maskedTitle)
                    ? ev.maskedTitle
                    : ev.title;

                  return (
                    <div
                      key={ev.id}
                      className={`${styles.eventCard} ${ev.isConflict ? styles.eventCardConflict : ''}`}
                      style={{ 
                        '--event-color': account.color,
                        '--event-bg': account.badgeBg 
                      } as React.CSSProperties}
                      onClick={() => setSelectedEvent(ev)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className={styles.eventTimeRow}>
                        <span>{ev.startTime} – {ev.endTime}</span>
                        <span>{ev.durationMinutes}m</span>
                      </div>

                      <h3 className={styles.eventTitle}>{displayTitle}</h3>

                      <div className={styles.eventSourceRow}>
                        <span className={styles.sourceBadge}>
                          {getProviderIcon(account.provider, 11)} {account.name}
                        </span>
                        {ev.isConflict && (
                          <span className={styles.conflictTag}>Schedule Conflict</span>
                        )}
                        {ev.location && (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                            <MapPin size={11} /> {ev.location}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Column 2: Ana's Track */}
          <section className={styles.partnerTrackCard} aria-label="Ana's Schedule">
            <div className={styles.trackHeader}>
              <h2 className={styles.trackOwnerTitle}>
                Ana
                <span className={styles.trackSubTag}>Gmail &amp; iPhone iCloud</span>
              </h2>
              <span style={{ fontSize: '0.78rem', color: 'var(--olin-text-muted)', fontWeight: 600 }}>
                {anaEvents.length} events
              </span>
            </div>

            <div className={styles.trackEventList}>
              {anaEvents.length === 0 ? (
                <div style={{ padding: '2rem 1rem', textAlign: 'center', color: 'var(--olin-text-muted)', fontSize: '0.85rem' }}>
                  No active events for selected filters.
                </div>
              ) : (
                anaEvents.map(ev => {
                  const account = calendarAccountsMock[ev.sourceId];
                  return (
                    <div
                      key={ev.id}
                      className={`${styles.eventCard} ${ev.isConflict ? styles.eventCardConflict : ''}`}
                      style={{ 
                        '--event-color': account.color,
                        '--event-bg': account.badgeBg 
                      } as React.CSSProperties}
                      onClick={() => setSelectedEvent(ev)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className={styles.eventTimeRow}>
                        <span>{ev.startTime} – {ev.endTime}</span>
                        <span>{ev.durationMinutes}m</span>
                      </div>

                      <h3 className={styles.eventTitle}>{ev.title}</h3>

                      <div className={styles.eventSourceRow}>
                        <span className={styles.sourceBadge}>
                          {getProviderIcon(account.provider, 11)} {account.name}
                        </span>
                        {ev.isCareLink && (
                          <span className={styles.careBadge}>Care Circle Link</span>
                        )}
                        {ev.location && (
                          <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                            <MapPin size={11} /> {ev.location}
                          </span>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </section>

          {/* Joint Family Section Spanning Both Partners */}
          {jointEvents.length > 0 && (
            <section className={styles.jointSection} style={{ gridColumn: '1 / -1' }} aria-label="Joint Household Events">
              <div className={styles.jointHeader}>
                <h2 className={styles.jointTitle}>
                  <Users size={18} weight="fill" color="var(--olin-accent)" />
                  Joint Household Schedule (Erick + Ana)
                </h2>
                <span style={{ fontSize: '0.78rem', color: 'var(--olin-text-muted)', fontWeight: 600 }}>
                  Synchronized with Family Circle
                </span>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: '0.75rem' }}>
                {jointEvents.map(ev => {
                  const account = calendarAccountsMock[ev.sourceId];
                  return (
                    <div
                      key={ev.id}
                      className={styles.eventCard}
                      style={{ 
                        '--event-color': account.color,
                        '--event-bg': account.badgeBg 
                      } as React.CSSProperties}
                      onClick={() => setSelectedEvent(ev)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className={styles.eventTimeRow}>
                        <span>{ev.startTime} – {ev.endTime}</span>
                        <span>{ev.date}</span>
                      </div>
                      <h3 className={styles.eventTitle}>{ev.title}</h3>
                      <div className={styles.eventSourceRow}>
                        <span className={styles.sourceBadge}>
                          {getProviderIcon(account.provider, 11)} {account.name}
                        </span>
                        {ev.location && (
                          <span><MapPin size={11} /> {ev.location}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          )}
        </main>
      ) : viewMode === 'agenda' ? (
        <main style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }} aria-label="Agenda View">
          {filteredEvents.map(ev => {
            const account = calendarAccountsMock[ev.sourceId];
            return (
              <div
                key={ev.id}
                className={styles.eventCard}
                style={{ 
                  '--event-color': account.color,
                  '--event-bg': account.badgeBg 
                } as React.CSSProperties}
                onClick={() => setSelectedEvent(ev)}
                role="button"
                tabIndex={0}
              >
                <div className={styles.eventTimeRow}>
                  <span>{ev.date} · {ev.startTime} – {ev.endTime}</span>
                  <span style={{ textTransform: 'capitalize' }}>Owner: {ev.owner}</span>
                </div>
                <h3 className={styles.eventTitle}>{ev.title}</h3>
                <div className={styles.eventSourceRow}>
                  <span className={styles.sourceBadge}>
                    {getProviderIcon(account.provider, 11)} {account.name}
                  </span>
                  {ev.location && <span><MapPin size={11} /> {ev.location}</span>}
                </div>
              </div>
            );
          })}
        </main>
      ) : (
        <main style={{ padding: '3rem 1rem', textAlign: 'center', color: 'var(--olin-text-muted)', background: 'var(--olin-surface-card)', borderRadius: 'var(--olin-card-radius)' }}>
          <CalendarIcon size={40} style={{ opacity: 0.5, marginBottom: '0.5rem' }} />
          <h2 style={{ fontSize: '1.2rem', color: 'var(--olin-text-main)', margin: '0 0 0.5rem 0' }}>Month Overview: September 2026</h2>
          <p style={{ maxWidth: '400px', margin: '0 auto', fontSize: '0.85rem' }}>
            Aggregating 12 events across Google Workspace, Gmail, Apple iCloud, and Family Circle.
          </p>
        </main>
      )}

      {/* Event Detail Slide-out Drawer */}
      {selectedEvent && (
        <div className={styles.drawerOverlay} onClick={() => setSelectedEvent(null)}>
          <div className={styles.detailDrawer} onClick={e => e.stopPropagation()}>
            <div className={styles.drawerHeader}>
              <h2 className={styles.drawerTitle}>{selectedEvent.title}</h2>
              <button 
                type="button" 
                className={styles.closeBtn} 
                onClick={() => setSelectedEvent(null)}
                aria-label="Close details"
              >
                <X size={22} />
              </button>
            </div>

            {/* Time & Duration */}
            <div className={styles.drawerSection}>
              <span className={styles.drawerLabel}>Schedule &amp; Time</span>
              <span className={styles.drawerValue}>
                <Clock size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                {selectedEvent.date} · {selectedEvent.startTime} – {selectedEvent.endTime} ({selectedEvent.durationMinutes} minutes)
              </span>
            </div>

            {/* Source Account & Provider Provenance */}
            <div className={styles.drawerSection}>
              <span className={styles.drawerLabel}>Calendar Provider &amp; Source</span>
              <span className={styles.drawerValue} style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                {getProviderIcon(calendarAccountsMock[selectedEvent.sourceId].provider, 18)}
                {calendarAccountsMock[selectedEvent.sourceId].name}
              </span>
              <span style={{ fontSize: '0.78rem', color: 'var(--olin-text-muted)', marginTop: '2px' }}>
                Account: {calendarAccountsMock[selectedEvent.sourceId].accountEmail}
              </span>
            </div>

            {/* Privacy & Circle Visibility */}
            <div className={styles.drawerSection}>
              <span className={styles.drawerLabel}>Circle Privacy Status</span>
              <span className={styles.drawerValue}>
                {selectedEvent.sourceId === 'erick-work' ? (
                  <>
                    <EyeSlash size={15} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                    Work Protected · Masked as &ldquo;{selectedEvent.maskedTitle}&rdquo; for household members.
                  </>
                ) : (
                  <>
                    <Eye size={15} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                    Visible in full detail to Vargas Household circle.
                  </>
                )}
              </span>
            </div>

            {/* Location & Attendees */}
            {selectedEvent.location && (
              <div className={styles.drawerSection}>
                <span className={styles.drawerLabel}>Location</span>
                <span className={styles.drawerValue}>
                  <MapPin size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                  {selectedEvent.location}
                </span>
              </div>
            )}

            {selectedEvent.attendees && selectedEvent.attendees.length > 0 && (
              <div className={styles.drawerSection}>
                <span className={styles.drawerLabel}>Attendees</span>
                <span className={styles.drawerValue}>
                  <Users size={16} style={{ display: 'inline', verticalAlign: 'middle', marginRight: '4px' }} />
                  {selectedEvent.attendees.join(', ')}
                </span>
              </div>
            )}

            {/* Notes */}
            {selectedEvent.notes && (
              <div className={styles.drawerSection}>
                <span className={styles.drawerLabel}>Notes &amp; Context</span>
                <span className={styles.drawerValue}>{selectedEvent.notes}</span>
              </div>
            )}

            {selectedEvent.isCareLink && (
              <div className={styles.drawerSection} style={{ background: 'rgba(168, 85, 247, 0.1)' }}>
                <span className={styles.drawerLabel} style={{ color: '#9333ea' }}>Care Relationship Link</span>
                <span className={styles.drawerValue} style={{ fontSize: '0.85rem' }}>
                  Erick has granted care proxy consent for this appointment with Dr. Weber. Telemetry and return status sync to Today screen.
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Connected Accounts Manager Modal */}
      {showAccountsModal && (
        <div className={styles.modalOverlay} onClick={() => setShowAccountsModal(false)}>
          <div className={styles.accountsModal} onClick={e => e.stopPropagation()}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <h2 style={{ fontSize: '1.35rem', fontWeight: 700, margin: 0, color: 'var(--olin-text-main)' }}>
                  Connected Calendars
                </h2>
                <p style={{ fontSize: '0.82rem', color: 'var(--olin-text-muted)', margin: '2px 0 0 0' }}>
                  Federated multi-account synchronization across Google, Apple iCloud, and Work
                </p>
              </div>
              <button 
                type="button" 
                className={styles.closeBtn} 
                onClick={() => setShowAccountsModal(false)}
              >
                <X size={22} />
              </button>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '0.75rem' }}>
              {Object.values(calendarAccountsMock).map(acc => (
                <div key={acc.id} className={styles.accountRow}>
                  <div className={styles.accountInfo}>
                    <div 
                      className={styles.accountLogo}
                      style={{ 
                        '--account-color': acc.color,
                        '--account-bg': acc.badgeBg 
                      } as React.CSSProperties}
                    >
                      {getProviderIcon(acc.provider, 20)}
                    </div>
                    <div>
                      <h3 className={styles.accountName}>{acc.name}</h3>
                      <p className={styles.accountSub}>{acc.accountEmail}</p>
                      <p style={{ fontSize: '0.72rem', color: 'var(--olin-text-muted)', marginTop: '2px' }}>
                        {acc.description}
                      </p>
                    </div>
                  </div>

                  <div style={{ textAlign: 'right' }}>
                    <span className={styles.syncTag}>
                      <CheckCircle size={14} weight="fill" /> Active
                    </span>
                    <span style={{ fontSize: '0.72rem', color: 'var(--olin-text-muted)' }}>
                      {acc.lastSynced}
                    </span>
                  </div>
                </div>
              ))}
            </div>

            <div style={{ marginTop: '0.5rem', display: 'flex', justifyContent: 'flex-end', gap: '0.5rem' }}>
              <button 
                type="button" 
                className={styles.insightActionBtn}
                onClick={() => setShowAccountsModal(false)}
              >
                Done
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

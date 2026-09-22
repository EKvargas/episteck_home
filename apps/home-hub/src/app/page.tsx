'use client';

import React, { useState } from 'react';
import Link from 'next/link';
import { Palette, DeviceTabletSpeaker, Sparkle } from '@phosphor-icons/react';
import { useAppContext } from '@/components/providers/AppProvider';
import { useOlinTheme } from '@/theme/ThemeProvider';
import { getThemeSlots } from '@/components/slots/resolver';
import { getTodaySummaryMock } from '@/domain/mocks';
import { ActionableTask } from '@/domain/types';
import { 
  TodayAttentionScenarioId, 
  todayAttentionMocks, 
  TodayAttentionItem 
} from '@/domain/memoryMocks';
import { MemoryAttention } from '@/components/features/MemoryAttention';
import { AskOlinModal } from '@/components/features/AskOlinModal';
import styles from './page.module.css';

export default function TodayPage() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  const { activeTheme } = useOlinTheme();

  // Resolve presentation slots for active theme
  const slots = getThemeSlots(activeTheme);
  const {
    RelationshipSwitcher,
    TodaySchedule,
    AttentionTasks,
    WellbeingNutrition,
    PhysicalHome,
    AskOlinTrigger,
  } = slots;

  // Local state for interactive fidelity
  const [doorLocked, setDoorLocked] = useState(false);
  const [ambianceIndex, setAmbianceIndex] = useState(0);
  const [isAskOlinOpen, setIsAskOlinOpen] = useState(false);
  const [askOlinPrompt, setAskOlinPrompt] = useState('');
  const [toggledTaskIds, setToggledTaskIds] = useState<Record<string, boolean>>({});

  // Today Attention State (demonstrates Quiet vs Suggestion vs Correction vs Shared)
  const [attentionScenario, setAttentionScenario] = useState<TodayAttentionScenarioId>('SUGGESTION');
  const [dismissedItemIds, setDismissedItemIds] = useState<Record<string, boolean>>({});

  const ambianceScenes = ['Afternoon Calm', 'Golden Hour', 'Focus State', 'Evening Warmth'];

  // Canonical mock data derived from active context
  const data = getTodaySummaryMock(activeContext.id);

  // Compute tasks with local interactive overrides
  const tasks: ActionableTask[] = data.tasks.map((task) => ({
    ...task,
    done: toggledTaskIds[task.id] !== undefined ? toggledTaskIds[task.id] : task.done,
  }));

  // Determine current active memory attention item (quiet if scenario === 'QUIET' or dismissed)
  const rawAttentionItem: TodayAttentionItem | null = 
    attentionScenario !== 'QUIET' ? todayAttentionMocks[attentionScenario] : null;

  const currentAttentionItem = 
    rawAttentionItem && !dismissedItemIds[rawAttentionItem.id] ? rawAttentionItem : null;

  // Interactive handlers
  const handleToggleTask = (taskId: string) => {
    setToggledTaskIds((prev) => {
      const currentDone = prev[taskId] !== undefined
        ? prev[taskId]
        : data.tasks.find((t) => t.id === taskId)?.done ?? false;
      return { ...prev, [taskId]: !currentDone };
    });
  };

  const handleToggleDoorLock = () => {
    setDoorLocked((prev) => !prev);
  };

  const handleCycleAmbiance = () => {
    setAmbianceIndex((prev) => (prev + 1) % ambianceScenes.length);
  };

  const handleOpenAskOlin = (prompt?: string) => {
    if (prompt) setAskOlinPrompt(prompt);
    setIsAskOlinOpen(true);
  };

  const handleDismissMemoryAttention = (id: string) => {
    setDismissedItemIds((prev) => ({ ...prev, [id]: true }));
  };

  const handleSelectScenario = (scen: TodayAttentionScenarioId) => {
    setAttentionScenario(scen);
    if (scen !== 'QUIET') {
      const itemId = todayAttentionMocks[scen].id;
      setDismissedItemIds((prev) => ({ ...prev, [itemId]: false }));
    }
  };

  const personKey: 'erick' | 'ana' | 'family' =
    activeContext.id === 'PSN-me'
      ? 'erick'
      : activeContext.id === 'PSN-ana'
      ? 'ana'
      : 'family';

  const pendingCount = tasks.filter((t) => !t.done).length;

  return (
    <div className={styles.pageCanvas} data-context={activeContext.mode}>
      {/* Top Header Bar */}
      <header className={styles.topHeaderBar}>
        <div className={styles.headerLeft}>
          <div className={styles.brandTitle}>
            <span className={styles.timeTag}>{data.subtitle}</span>
            <h1 className={styles.greetingTitle}>{data.greeting}</h1>
          </div>
        </div>

        {/* Center: Dynamic Theme-Specific Relationship Switcher */}
        <div className={styles.headerCenter}>
          <RelationshipSwitcher
            contexts={availableContexts}
            activeContextId={activeContext.id}
            onSelectContext={(id) => setContext(id)}
          />
        </div>

        {/* Right: Atmosphere, Privacy, and Navigation Shortcuts */}
        <div className={styles.headerRight}>
          <div className={styles.homeBadge}>
            <span className={styles.greenPulse} aria-hidden="true" />
            <span>Home Secure · {data.physicalHome.livingRoom.temp}</span>
          </div>

          <div className={styles.privacyBadge}>
            <span>{data.privacyTag}</span>
          </div>

          {/* Quick Navigation to Appearance and Kiosk */}
          <Link
            href="/settings/appearance"
            className={styles.navLinkIcon}
            title="Appearance Settings (Theme Switcher)"
            aria-label="Appearance Settings"
          >
            <Palette size={16} weight="bold" />
          </Link>

          <Link
            href="/kiosk"
            className={styles.navLinkIcon}
            title="Family Kiosk View (3m glanceable)"
            aria-label="Family Kiosk View"
          >
            <DeviceTabletSpeaker size={16} weight="bold" />
          </Link>
        </div>
      </header>

      {/* 12-Column Operating System Content Grid */}
      <main className={styles.contentGrid}>
        {/* Left Column: 5 Cols (Today's Flow + Memory Attention + Attention & Tasks) */}
        <section className={styles.leftCol} aria-label="Schedule and Tasks">
          <TodaySchedule
            title={data.scheduleTitle}
            subtitle={data.scheduleSubtitle}
            countTag={data.scheduleCountTag}
            events={data.events}
          />

          {/* Quiet by Default: Only renders when actionable attention exists, else null */}
          <MemoryAttention
            item={currentAttentionItem}
            onDismiss={handleDismissMemoryAttention}
            onAccept={() => {}}
          />

          <AttentionTasks
            title="Attention & Tasks"
            pendingCountTag={`${pendingCount} Pending`}
            tasks={tasks}
            onToggleTask={handleToggleTask}
          />
        </section>

        {/* Right Column: 7 Cols (Wellbeing/Nutrition + Physical Home) */}
        <section className={styles.rightCol} aria-label="Wellbeing and Home">
          <WellbeingNutrition
            personContext={personKey}
            title={
              personKey === 'erick'
                ? 'Nutrition & Metabolic Truth'
                : personKey === 'ana'
                ? 'Care for Ana · Clinical & Wellness'
                : 'Family Dining & Nourishment'
            }
            subtitle={
              personKey === 'erick'
                ? 'Domain Service: Nutrition Truth & Metabolic Balance'
                : personKey === 'ana'
                ? 'Care Relationship Circle · Consent Granted'
                : 'Mealie Recipe Domain · Shared Household Ledger'
            }
            targetTag={
              personKey === 'erick'
                ? 'Target: 2,000 kcal'
                : personKey === 'ana'
                ? 'Active Care Link'
                : 'Meal Planned'
            }
            nutrition={data.nutrition}
            care={data.care}
            familyMeal={data.familyMeal}
            onOpenAskOlin={handleOpenAskOlin}
          />

          <PhysicalHome
            telemetry={data.physicalHome}
            doorLocked={doorLocked}
            onToggleDoorLock={handleToggleDoorLock}
            ambianceScene={ambianceScenes[ambianceIndex]}
            onCycleAmbianceScene={handleCycleAmbiance}
          />
        </section>
      </main>

      {/* Prototype Reviewer Control: Quickly switch Today Attention states */}
      <nav className={styles.demoSwitcherBar} aria-label="Prototype Attention Scenarios">
        <span className={styles.demoSwitcherLabel}>
          <Sparkle size={12} weight="fill" /> Attention:
        </span>
        <button
          type="button"
          onClick={() => handleSelectScenario('QUIET')}
          className={`${styles.demoPill} ${attentionScenario === 'QUIET' ? styles.demoPillActive : ''}`}
        >
          A. Quiet (Invisible)
        </button>
        <button
          type="button"
          onClick={() => handleSelectScenario('SUGGESTION')}
          className={`${styles.demoPill} ${attentionScenario === 'SUGGESTION' && currentAttentionItem ? styles.demoPillActive : ''}`}
        >
          B. Suggested Memory
        </button>
        <button
          type="button"
          onClick={() => handleSelectScenario('CORRECTION')}
          className={`${styles.demoPill} ${attentionScenario === 'CORRECTION' && currentAttentionItem ? styles.demoPillActive : ''}`}
        >
          C. Update Proposal
        </button>
        <button
          type="button"
          onClick={() => handleSelectScenario('SHARED')}
          className={`${styles.demoPill} ${attentionScenario === 'SHARED' && currentAttentionItem ? styles.demoPillActive : ''}`}
        >
          D. Shared Review
        </button>
      </nav>

      {/* Floating Ask Olin Trigger */}
      <AskOlinTrigger
        isOpen={isAskOlinOpen}
        onToggleModal={() => setIsAskOlinOpen((prev) => !prev)}
      />

      {/* Interactive Ask Olin Drawer/Modal */}
      <AskOlinModal
        isOpen={isAskOlinOpen}
        onClose={() => setIsAskOlinOpen(false)}
        initialQuery={askOlinPrompt}
        onLockDoor={() => setDoorLocked(true)}
      />
    </div>
  );
}

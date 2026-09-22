'use client';

import React, { useState, useEffect, useCallback } from 'react';
import Image from 'next/image';
import Link from 'next/link';
import styles from './KioskScreen.module.css';
import { getTodaySummaryMock } from '@/domain/mocks';
import { useOlinTheme } from '@/theme/ThemeProvider';
import { OLIN_THEMES } from '@/theme/registry';
import { OlinThemeId } from '@/theme/types';
import { AskOlinModal } from '@/components/features/AskOlinModal';
import {
  CloudSun,
  Moon,
  Microphone,
  Warning,
  Lock,
  LockOpen,
  PaintBrush,
  ShieldCheck,
  Thermometer,
  Lightning,
  Lightbulb,
  Fire,
  X,
} from '@phosphor-icons/react';

// ─── Ambient photo sequence ───────────────────────────────────────────────────
const FAMILY_PHOTOS = [
  {
    src: '/family-photos/photo-1.jpg',
    title: 'Home Together',
    caption: 'Erick, Ana & Isabella · September 2026',
  },
  {
    src: '/family-photos/photo-2.jpg',
    title: 'Autumn Park Day',
    caption: 'Family time · Weekend ritual',
  },
  {
    src: '/family-photos/photo-3.jpg',
    title: 'Friday Dinner',
    caption: 'The Vargas family table',
  },
];

// ─── Slide index constants ─────────────────────────────────────────────────────
const SLIDE_STATUS   = 0;
const SLIDE_PHOTO    = 1;
const SLIDE_HOME     = 2;
const SLIDE_WELLNESS = 3;
const SLIDE_COUNT    = 4;
const SLIDE_DURATION = 13000; // ms per slide

// ─── Helpers ──────────────────────────────────────────────────────────────────
function getCountdown(targetHHMM: string, now: Date): string {
  const [h, m] = targetHHMM.split(':').map(Number);
  const target = new Date(now);
  target.setHours(h, m, 0, 0);
  const diffMs = target.getTime() - now.getTime();
  if (diffMs <= 0) return 'Now';
  const mins = Math.round(diffMs / 60000);
  if (mins < 60) return `in ${mins}m`;
  return `in ${Math.floor(mins / 60)}h ${mins % 60}m`;
}

// ─── Component ────────────────────────────────────────────────────────────────
export function KioskScreen() {
  const [mounted, setMounted] = useState(false);
  const [now, setNow] = useState<Date | null>(null);
  const [slideIndex, setSlideIndex] = useState(SLIDE_STATUS);
  const [photoIndex, setPhotoIndex] = useState(0);
  const [doorLocked, setDoorLocked] = useState(true);
  const [alertDismissed, setAlertDismissed] = useState(false);
  const [isAskOlinOpen, setIsAskOlinOpen] = useState(false);
  const [askOlinQuery, setAskOlinQuery] = useState('');

  const { activeTheme, setTheme } = useOlinTheme();
  const data = getTodaySummaryMock('CIR-fam');

  // Mount + clock
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setMounted(true);
    setNow(new Date());
    setDoorLocked(data.physicalHome?.door.locked ?? true);
    const clock = setInterval(() => setNow(new Date()), 1000);
    return () => clearInterval(clock);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Ambient auto-rotation
  useEffect(() => {
    const timer = setInterval(() => {
      setSlideIndex(prev => {
        const next = (prev + 1) % SLIDE_COUNT;
        // advance photo when we land on photo slide
        if (next === SLIDE_PHOTO) {
          setPhotoIndex(pi => (pi + 1) % FAMILY_PHOTOS.length);
        }
        return next;
      });
    }, SLIDE_DURATION);
    return () => clearInterval(timer);
  }, []);

  // Formatted time / date
  const timeString = mounted && now
    ? now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', hour12: false })
    : '14:32';
  const dateString = mounted && now
    ? now.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })
    : 'Friday, September 19';
  const isNight = mounted && now ? (now.getHours() >= 20 || now.getHours() < 6) : false;

  // Theme cycling
  const themeIds = Object.keys(OLIN_THEMES) as OlinThemeId[];
  const handleCycleTheme = useCallback(() => {
    const idx = themeIds.indexOf(activeTheme);
    setTheme(themeIds[(idx + 1) % themeIds.length]);
  }, [themeIds, activeTheme, setTheme]);

  // Door toggle
  const handleToggleDoor = useCallback(() => {
    setDoorLocked(prev => {
      if (!prev) setAlertDismissed(true);
      return !prev;
    });
  }, []);

  // Ask Olin
  const openAskOlin = useCallback((q: string) => {
    setAskOlinQuery(q);
    setIsAskOlinOpen(true);
  }, []);

  // Next family event countdown
  const nextEvent = data.events?.[0];
  const countdown = mounted && now && nextEvent?.time
    ? getCountdown(nextEvent.time, now)
    : 'Today';

  const photo = FAMILY_PHOTOS[photoIndex];

  return (
    <div className={styles.kioskRoot} id="kiosk-root">
      {/* ── Ambient background glow ── */}
      <div className={styles.ambientBg} />

      <div className={styles.kioskShell}>

        {/* ══════════════════════════════════════════════════════════════════
            PERMANENT LAYER — Clock + Presence (always visible)
            ══════════════════════════════════════════════════════════════════ */}
        <div className={styles.permanentLayer}>
          {/* Clock */}
          <div className={styles.clockGroup}>
            <div className={styles.clock} suppressHydrationWarning>{timeString}</div>
            <div className={styles.clockMeta}>
              <div className={styles.dateText}>
                <span suppressHydrationWarning>{dateString}</span>
                <span className={styles.weatherPill}>
                  {isNight ? <Moon size={14} weight="fill" /> : <CloudSun size={14} weight="fill" />}
                  22°C · Calm
                </span>
              </div>
              <span className={styles.kioskLabel}>Olin Family · Glanceable Wall Display</span>
            </div>
          </div>

          {/* Presence chips */}
          <div className={styles.presenceGroup}>
            <div className={styles.chip} title="Erick is at home, at his office desk">
              <span className={`${styles.dot} ${styles.dotGreen}`} />
              <span className={styles.chipLabel}>Erick</span>
              <span className={styles.chipSub}>Home · Desk</span>
            </div>

            <div className={styles.chip} title="Ana is at a medical appointment, returning ~15:30">
              <span className={`${styles.dot} ${styles.dotAmber}`} />
              <span className={styles.chipLabel}>Ana</span>
              <span className={styles.chipSub}>Away · 15:30</span>
            </div>

            <div className={styles.chip} title="Isabella is on school bus 4, arriving 16:15">
              <span className={`${styles.dot} ${styles.dotSky}`} />
              <span className={styles.chipLabel}>Isabella</span>
              <span className={styles.chipSub}>Bus · 16:15</span>
            </div>

            {/* Theme cycler */}
            <button
              type="button"
              onClick={handleCycleTheme}
              className={styles.themeCycler}
              title={`Theme: ${OLIN_THEMES[activeTheme]?.name ?? activeTheme}`}
            >
              <PaintBrush size={14} weight="bold" />
              <span>{OLIN_THEMES[activeTheme]?.name?.split(' ')[0] ?? 'Theme'}</span>
            </button>

            {/* Exit Kiosk */}
            <Link href="/" className={styles.exitKioskBtn} title="Exit Kiosk Mode" aria-label="Exit Kiosk Mode">
              <X size={16} weight="bold" />
            </Link>
          </div>
        </div>

        {/* Optional security alert strip */}
        {!alertDismissed && !doorLocked && (
          <div className={styles.alertBanner} role="alert">
            <span className={styles.alertText}>
              <Warning size={20} weight="fill" />
              Front door is unlocked
            </span>
            <button type="button" className={styles.alertBtn} onClick={handleToggleDoor}>
              <Lock size={16} weight="bold" />
              Lock now
            </button>
          </div>
        )}

        {/* ══════════════════════════════════════════════════════════════════
            ROTATION LAYER — 4 ambient slides, crossfade
            ══════════════════════════════════════════════════════════════════ */}
        <div className={styles.rotationLayer}>

          {/* ── Slide 0: FAMILY STATUS ── */}
          <div className={`${styles.slide} ${styles.statusSlide} ${slideIndex === SLIDE_STATUS ? styles.slideActive : ''}`}>
            {/* Card A: Next family milestone */}
            <div className={styles.glanceCard}>
              <span className={styles.cardEyebrow}>Next Up</span>
              <h2 className={styles.cardMilestone}>
                {nextEvent?.title ?? 'All clear today'}
              </h2>
              <div className={styles.cardMeta}>
                {nextEvent?.time && <span>{nextEvent.time}</span>}
                {nextEvent && <span className={styles.countdownBadge}>{countdown}</span>}
              </div>
              {nextEvent?.subtitle && (
                <div className={styles.cardMeta} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                  <Lock size={12} /> {nextEvent.subtitle} (Obscured)
                </div>
              )}
            </div>

            {/* Card B: Tonight's dinner */}
            <div className={styles.glanceCard}>
              <span className={styles.cardEyebrow}>Tonight · Family Dinner</span>
              <div className={styles.dinnerRow}>
                <span className={styles.dinnerEmoji}>🍽️</span>
                <div className={styles.dinnerMeta}>
                  <h2 className={styles.dinnerTitle}>
                    {data.familyMeal?.dishTitle ?? 'Dinner TBD'}
                  </h2>
                  <span className={styles.dinnerSub}>
                    {data.familyMeal?.timeTag ?? '19:00'} · {data.familyMeal?.description ?? 'Home-cooked'}
                  </span>
                </div>
              </div>
              <div className={styles.cardMeta}>
                🛒 {data.familyMeal?.groceryItemsCount ?? 0} pantry items ready
              </div>
            </div>
          </div>

          {/* ── Slide 1: PHOTO MOMENT ── */}
          <div className={`${styles.slide} ${slideIndex === SLIDE_PHOTO ? styles.slideActive : ''}`}>
            <div className={styles.photoSlide}>
              <Image
                src={photo.src}
                alt={photo.title}
                fill
                className={styles.photoImage}
                style={{ objectFit: 'cover' }}
                priority={false}
              />
              <div className={styles.photoOverlay} />
              <div className={styles.photoCaption}>
                <div className={styles.photoCaptionText}>
                  <h2 className={styles.photoTitle}>{photo.title}</h2>
                  <span className={styles.photoDate}>{photo.caption}</span>
                </div>
                <span className={styles.familyTag}>The Vargas Family</span>
              </div>
            </div>
          </div>

          {/* ── Slide 2: HOME PULSE ── */}
          <div className={`${styles.slide} ${slideIndex === SLIDE_HOME ? styles.slideActive : ''}`}>
            <div className={styles.homeSlide}>
              <span className={styles.homeSlideHeader}>Physical Home · Live Status</span>
              <div className={styles.homeGrid}>
                {/* Climate */}
                <div className={styles.homeTile}>
                  <span className={styles.tileIcon}>🌡️</span>
                  <span className={styles.tileLabel}>Living Room</span>
                  <p className={styles.tileValue}>
                    {data.physicalHome?.livingRoom.temp ?? '21.5°C'}
                  </p>
                  <span className={styles.tileSub}>
                    {data.physicalHome?.livingRoom.humidity ?? '48% humidity'}
                  </span>
                </div>

                {/* HVAC */}
                <div className={styles.homeTile}>
                  <span className={styles.tileIcon}><Thermometer size={28} /></span>
                  <span className={styles.tileLabel}>Climate HVAC</span>
                  <p className={styles.tileValue}>
                    {data.physicalHome?.climate.mode ?? 'Comfort'}
                  </p>
                  <span className={styles.tileSub}>
                    Target: {data.physicalHome?.climate.targetTemp ?? '22°C'}
                  </span>
                </div>

                {/* Front Door */}
                <button
                  type="button"
                  className={`${styles.homeTile} ${styles.homeTileInteractive}`}
                  onClick={handleToggleDoor}
                  title="Tap to toggle front door lock"
                >
                  <span className={styles.tileIcon}>
                    {doorLocked
                      ? <Lock size={28} color="#22c55e" weight="bold" />
                      : <LockOpen size={28} color="#f59e0b" weight="bold" />}
                  </span>
                  <span className={styles.tileLabel}>Front Door</span>
                  <p className={doorLocked ? `${styles.tileValue} ${styles.tileValueGreen}` : `${styles.tileValue} ${styles.tileValueAmber}`}>
                    {doorLocked ? 'Secured' : 'Unlocked'}
                  </p>
                  <span className={styles.tapHint}>Tap to toggle</span>
                </button>

                {/* Solar / Energy */}
                <div className={styles.homeTile}>
                  <span className={styles.tileIcon}><Lightning size={28} /></span>
                  <span className={styles.tileLabel}>Solar Today</span>
                  <p className={`${styles.tileValue} ${styles.tileValueGreen}`}>+2.1 kWh</p>
                  <span className={styles.tileSub}>
                    <Lightbulb size={13} /> {data.physicalHome?.ambiance.currentScene ?? 'Warm Evening'}
                  </span>
                </div>
              </div>
            </div>
          </div>

          {/* ── Slide 3: WELLNESS PULSE ── */}
          <div className={`${styles.slide} ${slideIndex === SLIDE_WELLNESS ? styles.slideActive : ''}`}>
            <div className={styles.wellnessSlide}>
              {/* Erick */}
              <div className={styles.wellnessCard}>
                <div className={`${styles.wellnessAvatar} ${styles.avatarErick}`}>E</div>
                <h3 className={styles.wellnessName}>Erick</h3>
                <div className={styles.wellnessStat}>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Steps today</span>
                    <span className={`${styles.statValue} ${styles.statValueGood}`}>8,240</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Focus sessions</span>
                    <span className={styles.statValue}>3 deep</span>
                  </div>
                </div>
                <span className={styles.streakBadge}>
                  <Fire size={11} weight="fill" /> 3-day streak
                </span>
              </div>

              {/* Ana */}
              <div className={styles.wellnessCard}>
                <div className={`${styles.wellnessAvatar} ${styles.avatarAna}`}>A</div>
                <h3 className={styles.wellnessName}>Ana</h3>
                <div className={styles.wellnessStat}>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Steps today</span>
                    <span className={`${styles.statValue} ${styles.statValueGood}`}>7,240</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Appointments</span>
                    <span className={styles.statValue} style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <Lock size={12} /> Care visit ✓
                    </span>
                  </div>
                </div>
                <span className={styles.streakBadge}>
                  <Fire size={11} weight="fill" /> Active week
                </span>
              </div>

              {/* Isabella */}
              <div className={styles.wellnessCard}>
                <div className={`${styles.wellnessAvatar} ${styles.avatarIsabel}`}>I</div>
                <h3 className={styles.wellnessName}>Isabella</h3>
                <div className={styles.wellnessStat}>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Homework</span>
                    <span className={`${styles.statValue} ${styles.statValueGood}`}>✅ Done</span>
                  </div>
                  <div className={styles.statRow}>
                    <span className={styles.statLabel}>Bedtime goal</span>
                    <span className={`${styles.statValue} ${styles.statValueMid}`}>21:00</span>
                  </div>
                </div>
                <span className={styles.streakBadge}>
                  <Fire size={11} weight="fill" /> Reading 4 days
                </span>
              </div>
            </div>
          </div>

        </div>
        {/* end rotationLayer */}

        {/* ══════════════════════════════════════════════════════════════════
            FOOTER — Rotation dots + Privacy badge + Ask Olin
            ══════════════════════════════════════════════════════════════════ */}
        <footer className={styles.footer}>
          {/* Rotation progress dots */}
          <div className={styles.rotationDots} role="tablist" aria-label="Slide indicator">
            {Array.from({ length: SLIDE_COUNT }).map((_, i) => (
              <button
                key={i}
                type="button"
                role="tab"
                aria-selected={slideIndex === i}
                className={`${styles.rotDot} ${slideIndex === i ? styles.rotDotActive : ''}`}
                onClick={() => setSlideIndex(i)}
                aria-label={['Family Status', 'Family Photo', 'Home Pulse', 'Wellness'][i]}
              />
            ))}
          </div>

          {/* Privacy assurance */}
          <div className={styles.footerPrivacy}>
            <span className={styles.privacyDot} />
            <ShieldCheck size={12} weight="bold" />
            Shared kiosk · Private clinical records redacted
          </div>

          {/* Ask Olin voice trigger */}
          <button
            type="button"
            className={styles.askOlinBtn}
            onClick={() => openAskOlin('What should our family focus on today?')}
            aria-label="Ask Olin voice assistant"
          >
            <Microphone size={20} weight="fill" />
            Ask Olin
          </button>
        </footer>
      </div>

      {/* Ask Olin Dialog */}
      <AskOlinModal
        isOpen={isAskOlinOpen}
        onClose={() => setIsAskOlinOpen(false)}
        initialQuery={askOlinQuery}
        onLockDoor={() => setDoorLocked(true)}
      />
    </div>
  );
}

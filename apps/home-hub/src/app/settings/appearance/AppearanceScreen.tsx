'use client';
import React from 'react';
import Link from 'next/link';
import { useOlinTheme } from '@/theme/ThemeProvider';
import { OLIN_THEMES } from '@/theme/registry';
import { OlinThemeId } from '@/theme/types';
import styles from './AppearanceScreen.module.css';
import { CheckCircle } from '@phosphor-icons/react';

export function AppearanceScreen() {
  const { activeTheme, setTheme } = useOlinTheme();
  
  const themes = Object.values(OLIN_THEMES);

  return (
    <div className={styles.container}>
      <header className={styles.header}>
        <h1 className={styles.title}>Settings</h1>
        <p className={styles.subtitle}>Customize the Olin interface, privacy, and system preferences.</p>
      </header>

      {/* Settings Sub-tabs */}
      <nav className={styles.tabsRow} aria-label="Settings categories">
        <Link href="/settings/appearance" className={`${styles.tabLink} ${styles.tabLinkActive}`}>
          Appearance
        </Link>
        <Link href="/settings/privacy" className={styles.tabLink}>
          Privacy &amp; Data
        </Link>
      </nav>
      
      <div className={styles.grid}>
        {themes.map(theme => {
          const isActive = activeTheme === theme.id;
          return (
            <button 
              key={theme.id}
              className={`${styles.themeCard} ${isActive ? styles.activeCard : ''}`}
              onClick={() => setTheme(theme.id as OlinThemeId)}
              aria-pressed={isActive}
            >
              {/* This container inherits its own tokens via data-olin-theme */}
              <div 
                className={styles.previewBox}
                data-olin-theme={theme.id}
              >
                <div 
                  className={styles.mockCard}
                >
                  <div className={styles.mockTextRow} />
                  <div className={styles.mockTextRowShort} />
                  <div className={styles.mockButton} />
                </div>
              </div>
              
              <div className={styles.themeInfo}>
                <div className={styles.themeTitleRow}>
                  <span className={styles.themeName}>{theme.name}</span>
                  {isActive && <CheckCircle size={20} weight="fill" className={styles.checkIcon} />}
                </div>
                <span className={styles.themeDesc}>{theme.description}</span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );
}

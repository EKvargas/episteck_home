'use client';
import React, { useState } from 'react';
import { usePathname } from 'next/navigation';
import styles from './AppShell.module.css';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';

export function AppShell({ children, demoContent = false }: { children: React.ReactNode; demoContent?: boolean }) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const pathname = usePathname();

  const demoNotice = demoContent ? (
    <div role="note" aria-label="Demo mock data" className={styles.demoNotice}>
      DEMO / MOCK DATA — domain content is illustrative and is not data or access for the selected person.
    </div>
  ) : null;

  if (pathname === '/kiosk') return <>{demoNotice}{children}</>;



  return (
    <div className={styles.layout}>
      {demoNotice}
      <aside className={`${styles.sidebar} ${isCollapsed ? styles.collapsed : ''}`}>
        <div
          className={styles.sidebarLogo}
          onClick={() => setIsCollapsed(!isCollapsed)}
          style={{ cursor: 'pointer' }}
        >
          <div className={styles.brandMotif}>
            <div className={styles.motifCircle} />
            <div className={styles.motifCircle} style={{ transform: 'translateX(-6px)' }} />
          </div>
          {!isCollapsed && <span>Olin</span>}
        </div>
        <Sidebar isCollapsed={isCollapsed} />
      </aside>

      <div className="ambient-light-field" />

      <div className={styles.mainContent}>
        <main style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
          {children}
        </main>
      </div>

      <nav className={styles.bottomNav}>
        <BottomNav />
      </nav>
    </div>
  );
}

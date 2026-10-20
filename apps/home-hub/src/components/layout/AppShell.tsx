'use client';
import React, { useState } from 'react';
import { usePathname } from 'next/navigation';
import styles from './AppShell.module.css';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';

export function AppShell({ children, demoContent = false, liveRoutes = [] }: {
  children: React.ReactNode; demoContent?: boolean; liveRoutes?: string[];
}) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  // skipTrailingSlashRedirect serves /nutrition/ as-is, and the client pathname keeps the slash.
  const route = usePathname().replace(/\/+$/, '') || '/';

  const demoNotice = demoContent && !liveRoutes.includes(route) ? (
    <div role="note" aria-label="Demo mock data" className={styles.demoNotice}>
      DEMO / MOCK DATA — domain content is illustrative and is not data or access for the selected person.
    </div>
  ) : null;

  if (route === '/kiosk') return <>{demoNotice}{children}</>;



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

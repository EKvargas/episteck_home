'use client';
import React, { useState } from 'react';
import { usePathname } from 'next/navigation';
import styles from './AppShell.module.css';
import { Sidebar } from './Sidebar';
import { BottomNav } from './BottomNav';

export function AppShell({ children }: { children: React.ReactNode }) {
  const [isCollapsed, setIsCollapsed] = useState(false);
  const pathname = usePathname();

  if (pathname === '/kiosk') {
    return <>{children}</>;
  }



  return (
    <div className={styles.layout}>
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

'use client';
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useOptionalAppContext } from '@/components/providers/AppProvider';
import { House, Heartbeat, AppleLogo, Gear, Calendar, Brain } from '@phosphor-icons/react';
import styles from './Navigation.module.css';

export function Sidebar({ isCollapsed }: { isCollapsed?: boolean }) {
  const pathname = usePathname();
  const activeContext = useOptionalAppContext()?.activeContext;

  const getLinks = () => {
    return [
      { path: '/', label: 'Today', icon: <House weight="fill" size={20} /> },
      { path: '/memory', label: 'Memory', icon: <Brain size={20} /> },
      { path: '/nutrition', label: 'Nutrition', icon: <AppleLogo size={20} /> },
      { path: '/health', label: 'Health', icon: <Heartbeat size={20} /> },
      { path: '/calendar', label: 'Calendar', icon: <Calendar size={20} /> },
      { path: '/settings/appearance', label: 'Settings', icon: <Gear size={20} /> },
    ];
  };

  const links = getLinks();

  return (
    <ul className={styles.navList}>
      {links.map((link) => {
        const isActive = pathname === link.path;
        return (
          <li key={link.path}>
            <Link 
              href={activeContext ? `${link.path}?person=${encodeURIComponent(activeContext.personId)}` : link.path}
              className={`${styles.navItem} ${isActive ? styles.navItemActive : ''}`}
            >
              {link.icon}
              {!isCollapsed && <span>{link.label}</span>}
            </Link>
          </li>
        );
      })}
    </ul>
  );
}

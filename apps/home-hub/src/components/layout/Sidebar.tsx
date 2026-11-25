'use client';
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useOptionalAppContext } from '@/components/providers/AppProvider';
import { House, Heartbeat, ForkKnife, Gear, Calendar, Brain } from '@phosphor-icons/react';
import styles from './Navigation.module.css';

export function Sidebar({ isCollapsed }: { isCollapsed?: boolean }) {
  const route = usePathname().replace(/\/+$/, '') || '/';
  const context = useOptionalAppContext();

  const getLinks = () => {
    return [
      { path: '/', label: 'Inicio', icon: <House weight="fill" size={20} /> },
      { path: '/memory', label: 'Memoria', icon: <Brain size={20} /> },
      { path: '/nutrition', label: 'Nutrición', icon: <ForkKnife size={20} /> },
      { path: '/health', label: 'Salud', icon: <Heartbeat size={20} /> },
      { path: '/calendar', label: 'Calendario', icon: <Calendar size={20} /> },
      { path: '/settings/appearance', label: 'Ajustes', icon: <Gear size={20} /> },
    ];
  };

  const links = getLinks();

  return (
    <ul className={styles.navList}>
      {links.map((link) => {
        const isNutrition = link.path === '/nutrition';
        const path = isNutrition && context?.environment === 'LIVE' ? '/nutrition/hoy' : link.path;
        const isActive = route === link.path || (isNutrition && route.startsWith('/nutrition/'));
        return (
          <li key={link.path}>
            <Link 
              href={context ? `${path}?person=${encodeURIComponent(context.activeContext.personId)}` : path}
              prefetch={isNutrition || path === '/' ? false : undefined}
              aria-label={isCollapsed ? link.label : undefined}
              aria-current={route === path ? 'page' : isActive ? 'location' : undefined}
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

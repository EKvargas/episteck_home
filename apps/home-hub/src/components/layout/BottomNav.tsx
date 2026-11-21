'use client';
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useOptionalAppContext } from '@/components/providers/AppProvider';
import styles from './Navigation.module.css';
import { House, Heartbeat, Gear, AppleLogo, Brain } from '@phosphor-icons/react';

const navLinks = [
  { href: '/', label: 'Today', Icon: House },
  { href: '/memory', label: 'Memory', Icon: Brain },
  { href: '/nutrition', label: 'Nutrition', Icon: AppleLogo },
  { href: '/health', label: 'Health', Icon: Heartbeat },
  { href: '/settings/appearance', label: 'Settings', Icon: Gear },
];

export function BottomNav() {
  const route = usePathname().replace(/\/+$/, '') || '/';
  const context = useOptionalAppContext();

  return (
    <div className={styles.mobileNav}>
      {navLinks.map(link => {
        const isNutrition = link.href === '/nutrition';
        const path = isNutrition && context?.environment === 'LIVE' ? '/nutrition/hoy' : link.href;
        const isActive = route === link.href || (isNutrition && route.startsWith('/nutrition/'));
        
        return (
          <Link 
            key={link.href}
            href={context ? `${path}?person=${encodeURIComponent(context.activeContext.personId)}` : path}
            prefetch={isNutrition || path === '/' ? false : undefined}
            className={`${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}
            aria-current={route === path ? 'page' : isActive ? 'location' : undefined}
          >
            <link.Icon size={24} weight={isActive ? "fill" : "regular"} />
            <span>{link.label}</span>
          </Link>
        );
      })}
    </div>
  );
}

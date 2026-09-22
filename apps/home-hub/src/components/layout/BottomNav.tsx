'use client';
import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
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
  const pathname = usePathname();

  return (
    <div className={styles.mobileNav}>
      {navLinks.map(link => {
        const isActive = pathname === link.href;
        
        return (
          <Link 
            key={link.href}
            href={link.href} 
            className={`${styles.mobileNavItem} ${isActive ? styles.mobileNavItemActive : ''}`}
            aria-current={isActive ? 'page' : undefined}
          >
            <link.Icon size={24} weight={isActive ? "fill" : "regular"} />
            <span>{link.label}</span>
          </Link>
        );
      })}
    </div>
  );
}

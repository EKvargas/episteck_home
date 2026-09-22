'use client';
import React, { useState, useRef, useEffect } from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import { CaretDown, Check } from '@phosphor-icons/react';
import styles from './Navigation.module.css';

export function ContextSwitcher() {
  const { activeContext, setContext, availableContexts } = useAppContext();
  const [isOpen, setIsOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
        setIsOpen(false);
      }
    }
    if (isOpen) document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, [isOpen]);

  // Close on ESC key
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') setIsOpen(false);
    }
    if (isOpen) document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [isOpen]);

  const getLabel = (mode: string) => {
    if (mode === 'PERSONAL') return 'You';
    if (mode === 'FAMILY') return 'Family overview';
    if (mode === 'CARE_FOR_ANOTHER_PERSON') return 'Shared with you';
    return '';
  };

  return (
    <div className={styles.contextSwitcher} ref={containerRef}>
      <div className={styles.contextLabel}>Context</div>
      <button 
        className={styles.contextTrigger} 
        onClick={() => setIsOpen(!isOpen)}
        aria-expanded={isOpen}
        aria-haspopup="listbox"
      >
        <span className={styles.contextTriggerText}>
          {activeContext.name} 
          <span className={styles.contextTriggerSub}> · {getLabel(activeContext.mode)}</span>
        </span>
        <CaretDown size={16} weight="bold" style={{ transform: isOpen ? 'rotate(180deg)' : 'none', transition: 'transform var(--ep-transition-fast)' }} />
      </button>

      {isOpen && (
        <ul className={styles.contextPopover} role="listbox">
          {availableContexts.map(c => {
            const isSelected = c.id === activeContext.id;
            return (
              <li 
                key={c.id} 
                role="option" 
                aria-selected={isSelected}
                className={styles.contextOption}
                onClick={() => {
                  setContext(c.id);
                  setIsOpen(false);
                }}
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    setContext(c.id);
                    setIsOpen(false);
                  }
                }}
              >
                <div style={{ display: 'flex', flexDirection: 'column' }}>
                  <span style={{ fontWeight: 600, color: 'var(--ep-text-primary)' }}>{c.name}</span>
                  <span style={{ fontSize: '0.75rem', color: 'var(--ep-text-secondary)' }}>{getLabel(c.mode)}</span>
                </div>
                {isSelected && <Check size={16} weight="bold" color="var(--ep-text-primary)" />}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

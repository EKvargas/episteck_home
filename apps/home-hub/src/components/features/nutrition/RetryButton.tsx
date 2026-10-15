'use client';
import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import styles from './ProfilePanel.module.css';

/** Try again is a fresh server render: a new mint and a new Nutrition call. */
export function RetryButton() {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button type="button" className={styles.retry} disabled={pending} onClick={() => startTransition(() => router.refresh())}>
      {pending ? 'Trying again…' : 'Try again'}
    </button>
  );
}

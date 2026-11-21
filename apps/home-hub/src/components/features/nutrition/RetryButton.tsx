'use client';
import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import styles from './ProfilePanel.module.css';

/** Try again is a fresh server render: a new mint and a new Nutrition call. */
export function RetryButton({ label = 'Try again', pendingLabel = 'Trying again…', className = styles.retry }: {
  label?: string;
  pendingLabel?: string;
  className?: string;
} = {}) {
  const router = useRouter();
  const [pending, startTransition] = useTransition();
  return (
    <button type="button" className={className} disabled={pending} onClick={() => startTransition(() => router.refresh())}>
      {pending ? pendingLabel : label}
    </button>
  );
}

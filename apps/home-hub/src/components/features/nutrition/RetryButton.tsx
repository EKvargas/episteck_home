'use client';
import { useRouter } from 'next/navigation';
import { useTransition } from 'react';
import styles from './ProfilePanel.module.css';

/** Reintentar is a fresh server render: a new mint and a new Nutrition call. */
export function RetryButton({ label = 'Reintentar', pendingLabel = 'Reintentando…', className = styles.retry }: {
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

'use client';

import { useState } from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import styles from './ChatPrompt.module.css';

/** Copies text to the clipboard and remembers which key was copied last, and whether the browser allowed it. */
export function useCopyResult() {
  const [result, setResult] = useState<{ key: string; copied: boolean } | null>(null);
  async function copy(key: string, text: string) {
    try {
      await navigator.clipboard.writeText(text);
      setResult({ key, copied: true });
    } catch {
      setResult({ key, copied: false });
    }
  }
  return { result, copy };
}

/**
 * A copy-ready message for the viewer's own Nutrition chat. It renders only when the viewer is the
 * subject: a prompt shown while looking at someone else's data would go to the viewer's own bot.
 */
export function ChatPrompt({ label, prompt }: { label: string; prompt: string }) {
  const { activeContext, viewer } = useAppContext();
  const { result, copy } = useCopyResult();
  if (activeContext.personId !== viewer.id) return null;

  return (
    <div className={styles.chatPrompt} lang="es">
      <button type="button" className={styles.button} onClick={() => void copy(prompt, prompt)}>
        {label}
      </button>
      {result && (
        <p className={styles.status} role="status">
          {result.copied ? 'Mensaje copiado. Pégalo en tu chat de Nutrición.' : 'Selecciona el texto para copiarlo.'}
        </p>
      )}
      {result && !result.copied && <p className={styles.selectable}>{prompt}</p>}
    </div>
  );
}

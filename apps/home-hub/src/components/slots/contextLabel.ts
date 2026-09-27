import type { ContextMode } from '@/domain/types';

export function contextAccessibleLabel(name: string, mode: ContextMode): string {
  const kind = mode === 'FAMILY' ? 'Circle' : mode === 'PERSONAL' ? 'Personal' : 'Care';
  return `${name} ${kind} Context`;
}

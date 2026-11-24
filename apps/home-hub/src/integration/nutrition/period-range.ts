export type RangeDays = 3 | 7 | 14;

export function parseRange(raw: string | string[] | undefined): RangeDays {
  return raw === '3' ? 3 : raw === '14' ? 14 : 7;
}

const BERLIN = new Intl.DateTimeFormat('en-CA', {
  timeZone: 'Europe/Berlin', year: 'numeric', month: '2-digit', day: '2-digit',
});

/** The calendar date in Europe/Berlin as YYYY-MM-DD, whatever the server's time zone. */
export function berlinDate(now: Date): string {
  const p = Object.fromEntries(BERLIN.formatToParts(now).map((part) => [part.type, part.value]));
  return `${p.year}-${p.month}-${p.day}`;
}

/** First day of a window that ends today (Berlin): today minus (days - 1) calendar days. */
export function periodStart(days: RangeDays, now: Date): string {
  const [y, m, d] = berlinDate(now).split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d - (days - 1))).toISOString().slice(0, 10);
}

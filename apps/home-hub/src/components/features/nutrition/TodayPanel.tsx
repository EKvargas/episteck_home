import type { ReactNode } from 'react';
import { CaretRight, Info } from '@phosphor-icons/react/ssr';
import { nutritionHref } from '../../../integration/nutrition/nutrition-href';
import { ChatPrompt } from './ChatPrompt';
import { RetryButton } from './RetryButton';
import { StatusBar } from './StatusBar';
import type { HeadlineRow, MealLine, TodayPanelModel } from './today-panel-model';
import styles from './TodayPanel.module.css';

type DayModel = Extract<TodayPanelModel, { kind: 'TODAY' }>;
type StateModel = Exclude<TodayPanelModel, { kind: 'TODAY' }>;

/** The Hoy section. As a card it frames one message; as a column it holds the day's cards. */
function Frame({ card, role, busy, children }: {
  card: boolean; role?: 'status' | 'alert'; busy?: boolean; children: ReactNode;
}) {
  return (
    <section
      lang="es"
      aria-label="Hoy"
      className={card ? `${styles.panel} ${styles.card}` : styles.panel}
      role={role}
      aria-busy={busy || undefined}
      data-testid="today-panel"
    >
      {children}
    </section>
  );
}

/**
 * Hoy's day. `weekly` sits under the day's answer when the day reads, and after the day's message
 * in every other state, so a failed day never hides it. `compact` is the home card: the verdict, the
 * four rows and a refresh. `person` is the `?person=` value links carry, or null.
 */
export function TodayPanel({ model, signInHref, compact = false, weekly, person = null }: {
  model: TodayPanelModel;
  signInHref: string;
  compact?: boolean;
  weekly?: ReactNode;
  person?: string | null;
}) {
  if (model.kind === 'TODAY') {
    return compact ? <CompactDay model={model} /> : <Day model={model} weekly={weekly} person={person} />;
  }
  return (
    <>
      <DayState model={model} signInHref={signInHref} />
      {weekly}
    </>
  );
}

function DayState({ model, signInHref }: { model: StateModel; signInHref: string }) {
  switch (model.kind) {
    case 'LOADING':
      return (
        <Frame card role="status" busy>
          <p className={styles.body}>Cargando tu día…</p>
          <div className={styles.skeletonRows} aria-hidden="true">
            {[0, 1, 2, 3].map((i) => <div key={i} className={styles.skeleton} />)}
          </div>
        </Frame>
      );
    case 'DENIED':
      return <Frame card role="alert"><p className={styles.body}>No tienes acceso a este diario.</p></Frame>;
    case 'SESSION':
      return (
        <Frame card role="alert">
          <p className={styles.body}>Inicia sesión para ver tu día.</p>
          <a className={styles.action} href={signInHref}>Iniciar sesión</a>
        </Frame>
      );
    case 'UNAVAILABLE':
      return (
        <Frame card role="alert">
          <p className={styles.body}>El diario no responde ahora. Inténtalo de nuevo.</p>
          <RetryButton className={styles.action} />
        </Frame>
      );
    case 'INVALID':
      return <Frame card role="alert"><p className={styles.body}>No se pudo leer el diario.</p></Frame>;
    case 'NOT_CONFIGURED':
      return <Frame card role="alert"><p className={styles.body}>La vista Hoy solo funciona con datos reales.</p></Frame>;
    default: {
      const unmapped: never = model.kind;
      void unmapped;
      return null;
    }
  }
}

/** The four headline rows, always in the same order and at the same height, bar or no bar. */
function Rows({ rows }: { rows: HeadlineRow[] }) {
  return (
    <ul className={styles.rows}>
      {rows.map((row) => (
        <li key={row.code} className={styles.row} data-testid="headline-row" data-code={row.code} data-tone={row.state.tone}>
          {/* The spaces keep the parts apart when read aloud; the grid drops whitespace-only text. */}
          <span className={styles.name}>{row.name}</span>{' '}
          <span className={styles.amount}>{row.amount}</span>{' '}
          <span className={styles.track}>{row.bar && <StatusBar bar={row.bar} tone={row.state.tone} />}</span>{' '}
          <span className={styles.word}>
            {row.state.word !== null && (
              <>
                <span className={styles.dot} aria-hidden="true" />
                {row.state.word}
              </>
            )}
            {/* No target: the value stands alone, and the empty track says why rather than judging. */}
            {row.state.tone === 'plain' && <span className={styles.noTarget}>sin objetivo</span>}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Answer({ model }: { model: DayModel }) {
  return (
    <>
      <p className={styles.verdict} data-testid="verdict">{model.verdict}</p>
      <Rows rows={model.rows} />
    </>
  );
}

function CompactDay({ model }: { model: DayModel }) {
  return (
    <Frame card>
      <Answer model={model} />
      <RetryButton label="Actualizar" pendingLabel="Actualizando…" className={styles.action} />
    </Frame>
  );
}

function Meals({ meals }: { meals: MealLine[] }) {
  return (
    <section className={`${styles.card} ${styles.listCard}`} aria-labelledby="today-meals-title">
      <h2 id="today-meals-title" className={styles.title}>Comidas de hoy</h2>
      <div>
        {meals.map((meal, i) => (
          <details key={i} className={styles.meal}>
            <summary className={styles.summary}>
              <span className={styles.summaryText}>{meal.summary}</span>
              <CaretRight className={styles.caret} weight="bold" aria-hidden="true" />
            </summary>
            <ul className={styles.items}>
              {meal.items.map((item, j) => (
                <li key={j} className={styles.item}>
                  <span className={styles.itemText}>{item.text}</span>
                  <span className={styles.itemMeta}>Azúcares libres: {item.sugar}</span>
                  {item.note !== null && <span className={styles.itemMeta}>{item.note}</span>}
                </li>
              ))}
            </ul>
          </details>
        ))}
      </div>
    </section>
  );
}

function Day({ model, weekly, person }: { model: DayModel; weekly: ReactNode; person: string | null }) {
  const { reference, attribution } = model.sources;
  return (
    <Frame card={false}>
      <div className={styles.card}>
        <Answer model={model} />
        {model.quietLine !== null && <p className={styles.quiet}>{model.quietLine}</p>}
        {model.profileHint === 'SELF' && (
          <ChatPrompt
            label="Copiar «Quiero crear mi perfil»"
            prompt="Quiero crear mi perfil"
            lead="Crea tu perfil en el chat para ver energía, proteína y fibra frente a tus objetivos."
          />
        )}
        {model.profileHint === 'VIEWER' && <p className={styles.hint}>Todavía no hay perfil completo.</p>}
      </div>
      {weekly}
      {model.prenatalNote !== null && (
        <p className={styles.note}>
          <Info className={styles.noteIcon} weight="bold" aria-hidden="true" />
          <span>{model.prenatalNote}</span>
        </p>
      )}
      {model.meals.length > 0 && <Meals meals={model.meals} />}
      <footer className={styles.footer}>
        <a className={styles.link} href={nutritionHref('/nutrition/ayuda', person)}>¿Cómo anoto?</a>
        {(reference !== null || attribution.length > 0) && (
          <details className={styles.sources}>
            <summary className={styles.sourcesSummary}>
              Fuentes
              <CaretRight className={styles.caret} weight="bold" aria-hidden="true" />
            </summary>
            {reference !== null && <p className={styles.source}>{reference}</p>}
            {attribution.map((text, i) => <p key={i} className={styles.source}>{text}</p>)}
          </details>
        )}
      </footer>
    </Frame>
  );
}

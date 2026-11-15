'use client';

// Three structural variants on /nutrition?prototype=ana&variant=A|B|C.
// Disposable UI study: synthetic fixtures, local memory, no domain mutations.
import { useEffect, useRef, useState } from 'react';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { ArrowLeft, ArrowRight, Plus, ChatCircle, Microphone, Camera, BowlFood, Coffee, Leaf, Drop, Info, PencilSimple, X, Check, PaperPlaneTilt, CalendarBlank } from '@phosphor-icons/react';
import styles from './AnaNutritionPrototype.module.css';

type Span = [number, number];
type Metric = 'sugar' | 'caffeine' | 'iron' | 'folate' | 'iodine' | 'calcium' | 'b12' | 'vitaminD' | 'dha';
type View = 'today' | 'diary' | 'nutrients' | 'week';
type Entry = { id: string; name: string; portion: string; time: string; meal: string; channel: 'App' | 'Telegram'; estimated: boolean; values: Partial<Record<Metric, Span>>; revision: number; cola?: boolean };
type Draft = { raw: string; channel: Entry['channel']; product: 'cola' | 'chocolate' | 'unknown'; ml: string; small: boolean };
type Model = { entries: Entry[]; draft: Draft | null; messages: { who: 'Ana' | 'Olin'; text: string }[]; sugarGoal: number; serial: number };
const METRICS: { key: Metric; name: string; unit: string; note: string }[] = [
  { key: 'sugar', name: 'Azúcares libres', unit: 'g', note: 'Referencia general, no cantidad que completar' },
  { key: 'caffeine', name: 'Cafeína', unit: 'mg', note: 'Suma de alimentos y bebidas con dato' },
  { key: 'iron', name: 'Hierro', unit: 'mg', note: 'Ingesta registrada; no determina reservas de hierro' },
  { key: 'folate', name: 'Folato', unit: 'µg', note: 'No equivale a una dosis de ácido fólico' },
  { key: 'iodine', name: 'Yodo', unit: 'µg', note: 'La referencia individual requiere contexto' },
  { key: 'calcium', name: 'Calcio', unit: 'mg', note: 'Cantidad con información disponible' },
  { key: 'b12', name: 'Vitamina B12', unit: 'µg', note: 'Datos del diario, sin diagnóstico de déficit' },
  { key: 'vitaminD', name: 'Vitamina D', unit: 'µg', note: 'La ingesta no expresa el estado de vitamina D' },
  { key: 'dha', name: 'DHA', unit: 'g', note: 'Sin completar con una dosis automática' },
];
const VARIANTS = [{ key: 'A', name: 'Mi día', note: 'Resumen primero, detalles cuando los necesitas' }, { key: 'B', name: 'Diario visual', note: 'Las comidas organizan toda la experiencia' }, { key: 'C', name: 'Con contexto', note: 'Nutrientes y procedencia en primer plano' }];
const VIEWS: { key: View; name: string }[] = [{ key: 'today', name: 'Hoy' }, { key: 'diary', name: 'Diario' }, { key: 'nutrients', name: 'Nutrientes' }, { key: 'week', name: 'Semana' }];
const initial = (): Model => ({ entries: [
  { id: 'breakfast', name: 'Yogur natural con avena', portion: 'Un bol · porción estimada', time: '08:30', meal: 'Desayuno', channel: 'App', estimated: true, revision: 1, values: { sugar: [0, 0], caffeine: [0, 0], iron: [1.2, 1.2], folate: [25, 25], calcium: [180, 180], b12: [0.4, 0.4] } },
  { id: 'lunch', name: 'Pasta con verduras', portion: 'Un plato · receta por completar', time: '13:15', meal: 'Comida', channel: 'Telegram', estimated: true, revision: 1, values: {} },
], draft: null, sugarGoal: 50, serial: 0, messages: [{ who: 'Olin', text: 'Este chat es una simulación. Prueba a registrar una bebida y comprueba cómo aparece en el mismo diario visual.' }] });
// Browser-memory cache only, so comparing URL variants preserves this synthetic exercise.
// It is never written during a server render, never persists across a full reload.
let browserExercise: Model | undefined;
const number = (n: number) => new Intl.NumberFormat('es', { maximumFractionDigits: 1 }).format(n);
const range = (n: Span) => n[0] === n[1] ? number(n[0]) : `${number(n[0])}–${number(n[1])}`;
function summary(entries: Entry[], key: Metric) {
  const known = entries.filter(e => e.values[key] !== undefined);
  return { value: known.reduce<Span>((sum, e) => [sum[0] + e.values[key]![0], sum[1] + e.values[key]![1]], [0, 0]), known: known.length, missing: entries.length - known.length };
}
function parse(raw: string, channel: Entry['channel']): Draft {
  const normalized = raw.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  const match = normalized.match(/(?:^|\s)(\d+(?:[.,]\d+)?)\s*ml\b/);
  return { raw, channel, product: /coca[ -]?cola/.test(normalized) && !/zero|light/.test(normalized) ? 'cola' : /chocolate/.test(normalized) ? 'chocolate' : 'unknown', ml: match?.[1].replace(',', '.') ?? '', small: /peque|peq\b/.test(normalized) };
}
function draftSugar(draft: Draft): Span | null {
  if (draft.product !== 'cola') return null;
  const ml = Number(draft.ml);
  if (draft.ml && Number.isFinite(ml) && ml > 0 && ml <= 5000) return [ml * 10.6 / 100, ml * 10.6 / 100];
  return !draft.ml && draft.small ? [15.9, 21.2] : null;
}

export function AnaNutritionPrototype({ variant: requested }: { variant: string }) {
  const variant = ['A', 'B', 'C'].includes(requested) ? requested : 'A';
  const router = useRouter(), pathname = usePathname(), params = useSearchParams();
  const [model, setModel] = useState<Model>(() => typeof window !== 'undefined' && browserExercise ? browserExercise : initial());
  const [view, setView] = useState<View>('today');
  const [metric, setMetric] = useState<Metric>('sugar');
  const [modal, setModal] = useState<'capture' | 'source' | 'telegram' | 'edit' | null>(null);
  const [text, setText] = useState('Un vaso pequeño de Coca-Cola Original');
  const [editing, setEditing] = useState<string | null>(null);
  const [editMl, setEditMl] = useState('150');
  const [feedback, setFeedback] = useState('Datos ficticios para explorar la interfaz.');
  const [selectedDay, setSelectedDay] = useState(6);
  const dialog = useRef<HTMLDialogElement>(null);
  const selected = METRICS.find(m => m.key === metric)!;
  const sugar = summary(model.entries, 'sugar');

  useEffect(() => { browserExercise = model; }, [model]);
  useEffect(() => { if (modal) dialog.current?.showModal(); else dialog.current?.close(); }, [modal]);
  function changeVariant(direction: number) {
    const index = (VARIANTS.findIndex(v => v.key === variant) + direction + 3) % 3;
    const query = new URLSearchParams(params.toString()); query.set('variant', VARIANTS[index].key);
    router.replace(`${pathname}?${query}`, { scroll: false });
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      const element = event.target as HTMLElement;
      if (modal || element.closest('input,textarea,select,[contenteditable=true]')) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); changeVariant(event.key === 'ArrowLeft' ? -1 : 1); }
    };
    window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener);
  });
  function explain(key: Metric) { setMetric(key); setModal('source'); }
  function propose(channel: Entry['channel'], raw = text) {
    if (!raw.trim()) return;
    setModel(previous => ({ ...previous, draft: parse(raw, channel), messages: channel === 'Telegram' ? [...previous.messages, { who: 'Ana', text: raw }, { who: 'Olin', text: 'He preparado una propuesta. Revisa producto y cantidad antes de añadirla; no cuenta todavía en el diario.' }] : previous.messages }));
    setModal(channel === 'Telegram' ? 'telegram' : 'capture');
  }
  function confirm() {
    const draft = model.draft;
    if (!draft || (draft.ml && (!Number.isFinite(Number(draft.ml)) || Number(draft.ml) <= 0 || Number(draft.ml) > 5000))) return;
    const sugarValue = draftSugar(draft);
    const portion = draft.ml ? `${number(Number(draft.ml))} ml indicados` : draft.product === 'cola' && draft.small ? '150–200 ml · supuesto de vaso pequeño' : 'Porción no cuantificada';
    const entry: Entry = { id: `demo-${model.serial + 1}`, name: draft.product === 'cola' ? 'Coca-Cola Original · ejemplo de etiqueta DE' : draft.product === 'chocolate' ? 'Chocolate caliente · receta desconocida' : draft.raw, portion, time: '16:00', meal: 'Merienda', channel: draft.channel, estimated: !draft.ml, revision: 1, cola: draft.product === 'cola', values: sugarValue ? { sugar: sugarValue } : {} };
    setModel(previous => ({ ...previous, draft: null, serial: previous.serial + 1, entries: [...previous.entries, entry], messages: [...previous.messages, { who: 'Olin', text: `Añadido: ${entry.name}, ${portion}. ${sugarValue ? `Azúcares libres: ${range(sugarValue)} g.` : 'Azúcar desconocido hasta disponer de una receta o etiqueta.'} Disponible también en la app. [Simulación]` }] }));
    setFeedback(`Añadido desde ${draft.channel}. El diario visual y la consulta simulada usan la misma entrada.`);
    if (draft.channel === 'App') setModal(null);
  }
  function edit(entry: Entry) { setEditing(entry.id); setEditMl('150'); setModal('edit'); }
  function saveEdit() {
    const ml = Number(editMl);
    if (!Number.isFinite(ml) || ml <= 0 || ml > 5000) return;
    setModel(previous => ({ ...previous, entries: previous.entries.map(e => e.id === editing ? { ...e, portion: `${number(ml)} ml indicados`, estimated: false, revision: e.revision + 1, values: { sugar: [ml * 10.6 / 100, ml * 10.6 / 100] } } : e), messages: [...previous.messages, { who: 'Olin', text: `La app corrigió la bebida a ${number(ml)} ml. La próxima consulta del diario utiliza esa revisión. [Simulación]` }] }));
    setFeedback('Porción corregida. La revisión aparece también en el chat simulado.'); setModal(null);
  }
  function queryTelegram() {
    setModel(previous => {
      const result = summary(previous.entries, 'sugar');
      return { ...previous, messages: [...previous.messages, { who: 'Ana', text: '¿Qué llevo hoy?' }, { who: 'Olin', text: `${previous.entries.length} entradas confirmadas. Azúcares libres con dato: ${result.known ? range(result.value) + ' g' : 'desconocidos'}. ${result.missing} entradas sin dato de azúcar. No es un total completo. ${previous.sugarGoal === 25 ? 'Objetivo personal simulado: 25 g; referencia institucional original: 50 g con base estándar de 2.000 kcal.' : 'Referencia institucional: 50 g con base estándar de 2.000 kcal.'} Fuente original: OMS; no es un límite individual de seguridad. [Simulación]` }] };
    });
  }
  const nutrientButton = (key: Metric) => {
    const info = METRICS.find(m => m.key === key)!, result = summary(model.entries, key);
    return <button key={key} className={styles.metric} onClick={() => explain(key)}><span>{info.name}<Info size={17} aria-hidden /></span><strong>{result.known ? range(result.value) : 'Sin dato'} {result.known && <small>{info.unit}</small>}</strong><small>{result.known} de {model.entries.length} entradas con dato</small></button>;
  };
  const meal = (entry: Entry, compact = false) => <article key={entry.id} className={`${styles.meal} ${compact ? styles.compact : ''}`}>
    <div className={`${styles.foodIcon} ${entry.cola ? styles.drink : ''}`} aria-hidden>{entry.cola ? <Coffee size={34} weight="duotone" /> : entry.id === 'breakfast' ? <BowlFood size={38} weight="duotone" /> : <Leaf size={38} weight="duotone" />}</div>
    <div className={styles.mealText}><small>{entry.meal} · {entry.time}</small><h3>{entry.name}</h3><p>{entry.portion}</p><div className={styles.row}><span className={styles.chip}>{entry.channel === 'Telegram' && <ChatCircle size={14} aria-hidden />} {entry.channel}</span><span className={styles.muted}>{entry.values.sugar ? `${range(entry.values.sugar)} g libres con dato` : 'Composición por completar'}</span></div></div>
    {entry.cola ? <button className={styles.iconButton} aria-label={`Corregir porción de ${entry.name}`} onClick={() => edit(entry)}><PencilSimple size={20} /></button> : <button className={styles.textButton} onClick={() => explain(entry.id === 'breakfast' ? 'sugar' : 'iron')}>Ver detalle</button>}
  </article>;
  const captureButton = <button className={styles.primary} onClick={() => { setModel(p => ({ ...p, draft: null })); setModal('capture'); }}><Plus size={21} aria-hidden /> Registrar comida</button>;
  const contextNotice = <aside className={styles.contextNotice}><Info size={22} aria-hidden /><div><strong>{sugar.known && sugar.value[0] >= model.sugarGoal ? 'Lo contabilizado alcanza o supera la referencia de ejemplo.' : sugar.known && sugar.value[1] >= model.sugarGoal ? 'La estimación cruza la referencia de ejemplo.' : 'Un registro puede estar incompleto.'}</strong><p>{model.entries.filter(e => !e.values.sugar).length} entrada(s) sin dato de azúcar. Lo que falta no se cuenta como cero.</p><button className={styles.textButton} onClick={() => explain('sugar')}>Ver fuentes y supuestos</button></div></aside>;

  const week = () => {
    const days: { label: string; value: Span | null; state: string }[] = [{ label: 'Lun', value: [18, 22], state: 'Parcial' }, { label: 'Mar', value: null, state: 'Sin registros' }, { label: 'Mié', value: [23, 23], state: 'Con datos' }, { label: 'Jue', value: [12, 19], state: 'Parcial' }, { label: 'Vie', value: null, state: 'Sin registros' }, { label: 'Sáb', value: [29, 35], state: 'Parcial' }, { label: 'Hoy', value: sugar.known ? sugar.value : null, state: 'Parcial' }];
    return <section className={styles.section}><div className={styles.sectionHead}><div><h2>Tu semana, con sus huecos</h2><p>Azúcares libres con dato · gramos · ejemplos ficticios</p></div><CalendarBlank size={30} aria-hidden /></div><div className={styles.weekChart} role="group" aria-label="Azúcares libres registrados durante siete días de demostración, con huecos visibles">{days.map((day, i) => <button key={day.label} aria-pressed={i === selectedDay} className={styles.day} onClick={() => setSelectedDay(i)} aria-label={`${day.label}: ${day.value ? range(day.value) + ' gramos' : 'sin registros'}, ${day.state}`}><span>{day.value ? range(day.value) : '—'}</span><span className={styles.column}>{day.value ? <span style={{ height: `${Math.max(3, day.value[1] / 50 * 100)}%` }} /> : <span className={styles.emptyColumn}>Sin datos</span>}</span><strong>{day.label}</strong><small>{day.state}</small></button>)}</div><p className={styles.note}><strong>{days[selectedDay].label}:</strong> {days[selectedDay].value ? `${range(days[selectedDay].value!)} g contabilizados. ${days[selectedDay].state === 'Parcial' ? 'Hay información faltante.' : 'Datos para las entradas registradas; no prueba que se anotó todo el día.'}` : 'No hay registros; no significa cero consumo.'}</p><button className={styles.textButton} onClick={() => explain('sugar')}>Fuente y referencia del día</button></section>;
  };
  const overview = <div className={styles.overview}><span className={styles.chip}>Resumen del ejemplo</span><h2>Lo registrado hasta ahora</h2><p className={styles.big}>{model.entries.length}<span> comidas y bebidas</span></p><p>Las porciones pueden ser aproximadas. Puedes corregirlas cuando tengas más información.</p><div className={styles.inlineStats}><div><Drop size={24} aria-hidden /><strong>Agua</strong><span>Sin registrar</span></div><div><BowlFood size={24} aria-hidden /><strong>Suplementos</strong><span>Sin registrar</span></div></div></div>;
  const nutrientPanel = <section className={styles.section}><div className={styles.sectionHead}><div><h2>Lo que sabemos de tus nutrientes</h2><p>Ingesta de ejemplo; no mide tu estado nutricional.</p></div></div><div className={styles.metrics}>{METRICS.map(m => nutrientButton(m.key))}</div><p className={styles.note}>Las referencias de micronutrientes no están activadas en esta maqueta. Se revisarán antes del uso real; ninguna diferencia se convierte en una dosis de suplemento.</p></section>;

  function renderVariantA() { return <div className={styles.variantA}><section className={styles.dailyHero}>{overview}<div className={styles.heroActions}><h2>Añade sin complicarte.</h2><p>Una frase es suficiente para empezar. Después revisas la porción.</p>{captureButton}<button className={styles.secondary} onClick={() => setModal('telegram')}><ChatCircle size={20} aria-hidden /> Probar recorrido Telegram</button></div></section><div className={styles.rowGrid}><section className={styles.section}><div className={styles.sectionHead}><h2>En tu diario</h2><button className={styles.textButton} onClick={() => setView('diary')}>Ver todo</button></div>{model.entries.slice(-2).map(e => meal(e, true))}</section><section className={styles.section}><h2>Dos cosas que puedes revisar</h2><div className={styles.metrics}>{nutrientButton('sugar')}{nutrientButton('caffeine')}</div>{contextNotice}</section></div></div>; }
  function renderVariantB() { return <div className={styles.variantB}><section className={styles.timeline}><div className={styles.sectionHead}><div><h2>Un día contado por sus comidas</h2><p>Lo que anotaste, en orden. Lo que falta sigue abierto.</p></div>{captureButton}</div>{model.entries.map(e => <div key={e.id} className={styles.timelineRow}><span className={styles.time}>{e.time}</span>{meal(e)}</div>)}<div className={styles.nextMeal}><Plus size={23} aria-hidden /><div><strong>¿Algo más que añadir?</strong><p>También puedes contárselo a Olin en Telegram.</p></div><button className={styles.secondary} onClick={() => setModal('telegram')}>Probar chat</button></div></section><aside className={styles.diaryAside}><h2>Una mirada al día</h2>{nutrientButton('sugar')}{nutrientButton('iron')}{contextNotice}<button className={styles.textButton} onClick={() => setView('week')}>Explorar la semana</button></aside></div>; }
  function renderVariantC() { return <div className={styles.variantC}><section className={styles.referenceList}><h2>Los datos, con su contexto</h2><p>Elige un nutriente para entender qué dato hay y de dónde viene la orientación.</p>{METRICS.map(m => { const value = summary(model.entries, m.key); return <button key={m.key} className={styles.referenceRow} aria-pressed={metric === m.key} onClick={() => setMetric(m.key)}><span>{m.name}<small>{value.known}/{model.entries.length} entradas con dato</small></span><strong>{value.known ? `${range(value.value)} ${m.unit}` : 'Desconocido'}</strong><ArrowRight size={18} aria-hidden /></button>; })}</section><aside className={styles.referenceAside}><span className={styles.chip}>Por qué aparece</span><h2>{selected.name}</h2><p>{selected.note}.</p><div className={styles.referenceValue}>{summary(model.entries, metric).known ? range(summary(model.entries, metric).value) : 'Sin dato'} <small>{summary(model.entries, metric).known ? selected.unit : ''}</small></div><p>Información para {summary(model.entries, metric).known} de {model.entries.length} entradas. Un subtotal no determina tu estado de salud.</p><button className={styles.primary} onClick={() => explain(metric)}>Ver fuente y cálculo</button><hr />{captureButton}<button className={styles.secondary} onClick={() => setModal('telegram')}><ChatCircle size={20} aria-hidden /> Abrir chat simulado</button></aside></div>; }

  const draftReview = model.draft && <div className={styles.draft}><span className={styles.chip}>Propuesta · todavía no registrada</span><h3>{model.draft.raw}</h3><label>Producto o receta<select value={model.draft.product} onChange={e => setModel(p => ({ ...p, draft: p.draft && { ...p.draft, product: e.target.value as Draft['product'] } }))}><option value="cola">Coca-Cola Original DE · confirmar variante</option><option value="chocolate">Chocolate caliente · receta sin detalle</option><option value="unknown">Otro alimento · sin ficha disponible en la demo</option></select></label><label>Cantidad en ml, si la sabes<input type="number" min="1" max="5000" step="any" value={model.draft.ml} placeholder="Opcional; por ejemplo 150" onChange={e => setModel(p => ({ ...p, draft: p.draft && { ...p.draft, ml: e.target.value } }))} /></label><p><strong>Porción:</strong> {model.draft.ml ? `${model.draft.ml} ml indicados` : model.draft.product === 'cola' && model.draft.small ? '150–200 ml; supuesto editable de vaso pequeño' : 'Sin cuantificar; puedes registrarla así'}</p><p><strong>Azúcares libres:</strong> {draftSugar(model.draft) ? `${range(draftSugar(model.draft)!)} g estimados desde etiqueta` : 'Desconocidos; no se sustituyen por cero'}</p><small>La cafeína de este producto no tiene dato en el ejemplo. Confirmar el consumo no valida automáticamente todos los nutrientes.</small><button className={styles.primary} onClick={confirm} disabled={Boolean(model.draft.ml && (Number(model.draft.ml) <= 0 || Number(model.draft.ml) > 5000))}><Check size={20} aria-hidden /> Confirmar y añadir al diario</button></div>;

  return <div className={styles.prototype} data-variant={variant}>
    <div className={styles.prototypeNotice} role="note"><strong>Estudio visual · datos sintéticos</strong><span>Chat, voz y foto simulados. Sin grabación, subida ni conexión a Telegram.</span></div>
    <header className={styles.header}><div><p className={styles.muted}>Nutrición durante el embarazo</p><h1>Tu día, a tu ritmo.</h1><p>Ejemplo visual para Ana · etapa sin configurar</p></div><div className={styles.headerTools}><button className={styles.secondary} onClick={() => setModal('telegram')}><ChatCircle size={21} aria-hidden /> Telegram simulado</button>{captureButton}</div></header>
    <nav className={styles.viewTabs} aria-label="Vistas de nutrición">{VIEWS.map(v => <button key={v.key} aria-current={view === v.key ? 'page' : undefined} onClick={() => setView(v.key)}>{v.name}</button>)}</nav>
    <p className={styles.feedback} role="status">{feedback}</p>
    {view === 'today' ? variant === 'A' ? renderVariantA() : variant === 'B' ? renderVariantB() : renderVariantC() : view === 'diary' ? <section className={styles.section}><div className={styles.sectionHead}><div><h2>Tu diario</h2><p>Mismos registros en la app y el chat simulado.</p></div>{captureButton}</div>{model.entries.map(e => meal(e))}{contextNotice}</section> : view === 'nutrients' ? nutrientPanel : week()}
    <details className={styles.exerciseState}><summary>Estado y límites de esta demostración</summary><p>Diseño {variant}: {VARIANTS.find(v => v.key === variant)?.note}. {model.entries.length} entradas confirmadas; {model.draft ? 'un borrador pendiente' : 'sin borrador pendiente'}. Fuente y cantidad son conceptos distintos. Los valores de comidas, micronutrientes y semana son ficticios; solo la cola usa una etiqueta de ejemplo identificada. No hay llamadas a Nutrition ni recomendaciones individuales nuevas.</p><p>Revisión más reciente: {Math.max(0, ...model.entries.map(e => e.revision))}. Cambiar de variante conserva este ejercicio en memoria; recargar lo reinicia.</p><div className={styles.row}><button className={styles.textButton} onClick={() => { setModel(initial()); setFeedback('Ejercicio reiniciado con las dos comidas ficticias.'); }}>Reiniciar ejemplos</button><button className={styles.textButton} onClick={() => { setModel({ ...initial(), entries: [] }); setFeedback('Día vacío de ejemplo: sin registros no significa cero consumo.'); }}>Probar día sin registros</button></div></details>
    {process.env.NODE_ENV !== 'production' && <div className={styles.switcher} aria-label="Comparar propuestas visuales"><button aria-label="Propuesta anterior" onClick={() => changeVariant(-1)}><ArrowLeft size={21} /></button><div><small>Propuesta {variant} de 3</small><strong>{VARIANTS.find(v => v.key === variant)?.name}</strong></div><button aria-label="Propuesta siguiente" onClick={() => changeVariant(1)}><ArrowRight size={21} /></button></div>}
    <dialog ref={dialog} className={styles.dialog} onCancel={() => setModal(null)} onClose={() => setModal(null)} aria-labelledby="prototype-dialog-title"><button className={styles.close} aria-label="Cerrar" onClick={() => setModal(null)}><X size={23} /></button>
      <h2 id="prototype-dialog-title">{modal === 'capture' ? '¿Qué comiste o bebiste?' : modal === 'telegram' ? 'Recorrido Telegram · simulado' : modal === 'edit' ? 'Corregir la porción' : `Fuente y contexto: ${selected.name}`}</h2>
      {modal === 'capture' && <><p>Una frase para empezar. La cantidad exacta es opcional.</p><label htmlFor="capture-text">Describe tu comida o bebida<textarea id="capture-text" value={text} onChange={e => setText(e.target.value)} /></label><div className={styles.row}><button className={styles.secondary} onClick={() => propose('App')}><Plus size={19} aria-hidden /> Revisar propuesta</button><button className={styles.textButton} onClick={() => { setText('Una taza de chocolate caliente'); propose('App', 'Una taza de chocolate caliente'); }}>Probar chocolate</button></div><div className={styles.row}><button className={styles.secondary} onClick={() => propose('App', 'Un vaso pequeño de Coca-Cola Original')}><Microphone size={20} aria-hidden /> Ejemplo de audio</button><button className={styles.secondary} onClick={() => propose('App', 'Una taza de chocolate caliente')}><Camera size={20} aria-hidden /> Ejemplo de foto</button></div><p className={styles.note}>Aquí voz y foto cargan ejemplos escritos. No se graba ni se analiza ningún archivo. El catálogo de esta maqueta solo calcula la cola de ejemplo.</p>{draftReview}</>}
      {modal === 'telegram' && <><p>Simulación local de una conversación privada, usando las mismas entradas que la app.</p><div className={styles.chat}>{model.messages.map((m, i) => <div key={i} className={m.who === 'Ana' ? styles.userBubble : styles.botBubble}><small>{m.who === 'Ana' ? 'Ana (ejemplo)' : 'Olin (simulado)'}</small><p>{m.text}</p></div>)}</div><div className={styles.row}><button className={styles.secondary} onClick={() => propose('Telegram', 'Un vaso pequeño de Coca-Cola Original')}><PaperPlaneTilt size={19} aria-hidden /> Enviar ejemplo de bebida</button><button className={styles.secondary} onClick={queryTelegram}>¿Qué llevo hoy?</button></div>{draftReview}<button className={styles.textButton} onClick={() => { setView('diary'); setModal(null); }}>Ver los mismos registros en la app</button></>}
      {modal === 'edit' && <><p>La revisión sustituye la cantidad usada en el diario simulado. La siguiente consulta al chat la verá.</p><label>Cantidad indicada en ml<input type="number" min="1" max="5000" value={editMl} onChange={e => setEditMl(e.target.value)} /></label><button className={styles.primary} disabled={!Number.isFinite(Number(editMl)) || Number(editMl) <= 0 || Number(editMl) > 5000} onClick={saveEdit}>Guardar corrección de ejemplo</button></>}
      {modal === 'source' && <div className={styles.source}><span className={styles.chip}>{metric === 'sugar' && model.sugarGoal === 25 ? 'Objetivo personal · simulado' : metric === 'sugar' || metric === 'caffeine' ? 'Referencia institucional' : 'Referencia no activada'}</span><h3>{metric === 'sugar' ? `${model.sugarGoal} g/día como referencia de ejemplo` : metric === 'caffeine' ? 'Referencia de embarazo: 200 mg/día' : 'Ingesta visible; comparación pendiente de revisión'}</h3><dl><dt>Fuente original</dt><dd>{metric === 'sugar' ? <a href="https://www.who.int/publications/i/item/WHO-NMH-NHD-15.3" target="_blank" rel="noreferrer">OMS · azúcares libres · 2015</a> : metric === 'caffeine' ? <a href="https://www.nhs.uk/pregnancy/keeping-well/foods-to-avoid/" target="_blank" rel="noreferrer">NHS · alimentos y bebidas durante el embarazo</a> : <a href="https://www.dge.de/wissenschaft/referenzwerte/" target="_blank" rel="noreferrer">DGE · catálogo de referencias para revisar</a>}</dd><dt>Cómo lo aplica esta maqueta</dt><dd>{metric === 'sugar' ? 'La referencia principal es menos del 10% de energía. Con una base estándar ilustrativa de 2.000 kcal equivale a menos de 50 g. El 5% es una orientación adicional condicional: 25 g con la misma base. No es un requerimiento energético calculado para Ana ni un máximo fetal seguro.' : metric === 'caffeine' ? 'Se muestra la referencia; faltan datos de algunas entradas para evaluar el acumulado. No se atribuye una cantidad fija a cualquier taza.' : 'Los valores de alimentos son ficticios y la referencia no se ha habilitado en la maqueta. No se interpretan como déficit ni como una dosis de suplemento.'}</dd><dt>Por qué aparece</dt><dd>{metric === 'sugar' && model.sugarGoal === 25 ? 'Se eligió un objetivo personal en este ejercicio. La referencia institucional original de 50 g sobre 2.000 kcal sigue visible.' : 'Referencia del contexto de demostración; no proviene de una indicación personal de Ana.'}</dd><dt>De dónde salen los datos de comida</dt><dd>Comidas y micronutrientes sintéticos. Para la cola: <a href="https://www.coca-cola.com/de/de/brands/brand-coca-cola" target="_blank" rel="noreferrer">etiqueta Original DE, 10,6 g/100 ml</a>. La fracción libre se infiere de sus ingredientes; no generalizar esa igualdad a otros alimentos.</dd><dt>Incertidumbre y revisión</dt><dd>{summary(model.entries, metric).known} de {model.entries.length} entradas con dato para este nutriente. Rangos por porción. Referencia de ejemplo v1; catálogo no validado para uso personal.</dd></dl>{metric === 'sugar' && <label>Configuración simulada<select value={model.sugarGoal} onChange={e => { setModel(p => ({ ...p, sugarGoal: Number(e.target.value) })); setFeedback('Meta cambiada solo en la maqueta. La fuente institucional se conserva.'); }}><option value={50}>Referencia general: 50 g con base de 2.000 kcal</option><option value={25}>Objetivo personal de ejemplo: 25 g</option></select></label>}<p className={styles.note}>La fuente de la recomendación y la fuente del alimento se muestran por separado. Información incompleta no equivale a ausencia de exceso o riesgo.</p></div>}
    </dialog>
  </div>;
}

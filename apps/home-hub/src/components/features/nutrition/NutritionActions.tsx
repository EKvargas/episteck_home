'use client';

import { useState } from 'react';
import { useAppContext } from '@/components/providers/AppProvider';
import styles from './NutritionActions.module.css';

const groups = [
  {
    title: 'Diario de comidas',
    note: null,
    actions: [
      {
        title: 'Registrar una comida',
        prompt: 'Hoy a las [hora] comí [alimentos y porciones]. Prepara el borrador y espera a que confirme.',
      },
      {
        title: 'Corregir una comida',
        prompt: 'Revisa mi comida de [fecha y hora]. Corrige [alimento o porción] y busca coincidencias para los alimentos sin identificar. Muéstrame el cambio antes de actualizar el registro.',
      },
      {
        title: 'Anular un registro',
        prompt: 'Creo que la comida de [fecha y hora] quedó duplicada. Muéstrame el registro que anularías y espera mi confirmación.',
      },
      {
        title: 'Confirmar el cierre del día',
        prompt: 'Sí, eso fue todo el [fecha]. Cierra el día.',
      },
    ],
  },
  {
    title: 'Alimentos y recetas',
    note: 'Si tienes acceso al chat principal de Olin (Ultron), también puedes hacer estas consultas.',
    actions: [
      {
        title: 'Buscar un alimento',
        prompt: 'Busca [alimento] en la base de alimentos. Dime qué opciones hay y de qué fuente vienen.',
      },
      {
        title: 'Evaluar una comida',
        prompt: 'Estima las calorías, proteínas, grasas y carbohidratos de [alimentos y porciones]. Indica las fuentes y las cantidades estimadas. Solo quiero consultar.',
      },
      {
        title: 'Buscar recetas o planear un menú',
        prompt: 'Busca en Mealie dos recetas con [ingrediente] y propón un menú. Solo quiero ideas.',
      },
    ],
  },
];

export function NutritionActions() {
  const { activeContext, viewer } = useAppContext();
  const [copyResult, setCopyResult] = useState<{ title: string; copied: boolean } | null>(null);

  async function copyPrompt(title: string, prompt: string) {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopyResult({ title, copied: true });
    } catch {
      setCopyResult({ title, copied: false });
    }
  }

  if (activeContext.personId !== viewer.id) {
    return (
      <section id="acciones-en-telegram" className={styles.section} lang="es" aria-labelledby="nutrition-actions-title" tabIndex={-1}>
        <h2 id="nutrition-actions-title" className={styles.title}>Acciones en Telegram</h2>
        <p className={styles.intro}>Telegram usa tu propio diario. Selecciona tu nombre para ver las acciones.</p>
      </section>
    );
  }

  return (
    <section id="acciones-en-telegram" className={styles.section} lang="es" aria-labelledby="nutrition-actions-title" tabIndex={-1}>
      <h2 id="nutrition-actions-title" className={styles.title}>Acciones en Telegram</h2>
      <p className={styles.intro}>Adapta un ejemplo en tu chat de Nutrición. Después de guardar un cambio, vuelve y toca Actualizar diario.</p>
      <div className={styles.groups}>
        {groups.map(({ title, note, actions }) => (
          <div className={styles.group} key={title}>
            <h3>{title}</h3>
            {note && <p className={styles.note}>{note}</p>}
            {actions.map((action) => (
              <details className={styles.action} key={action.title}>
                <summary>{action.title}</summary>
                <div className={styles.example}>
                  <p>{action.prompt}</p>
                  <button
                    type="button"
                    aria-label={`Copiar ejemplo para ${action.title.toLowerCase()}`}
                    onClick={() => void copyPrompt(action.title, action.prompt)}
                  >
                    Copiar ejemplo
                  </button>
                  {copyResult?.title === action.title && (
                    <p className={styles.note} role="status">
                      {copyResult.copied ? 'Ejemplo copiado.' : 'Selecciona el texto del ejemplo para copiarlo.'}
                    </p>
                  )}
                </div>
              </details>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}

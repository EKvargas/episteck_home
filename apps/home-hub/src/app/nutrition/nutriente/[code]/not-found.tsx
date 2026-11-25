import { HUB_BASE_PATH } from '@/integration/basePath';
import styles from '../../page.module.css';
import panel from '@/components/features/nutrition/NutrientPanel.module.css';

/** Spanish not-found for an unknown nutrient code; a plain link back, no read, no mint. */
export default function NutrientNotFound() {
  return (
    <div className={styles.nutritionCanvas}>
      <section lang="es" className={`${panel.panel} ${panel.warn}`}>
        <h1 className={panel.name}>Nutriente no encontrado</h1>
        <p className={panel.body}>No existe ese nutriente.</p>
        <a className={panel.profileLink} href={`${HUB_BASE_PATH}/nutrition/dias`}>Ver Días</a>
      </section>
    </div>
  );
}

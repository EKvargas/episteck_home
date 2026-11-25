import { NutritionActions } from '@/components/features/nutrition/NutritionActions';
import { NutritionHeader } from '../NutritionHeader';
import styles from '../page.module.css';

export const dynamic = 'force-dynamic';

/** Static help: it makes no Nutrition read, so it never mints a delegation. */
export default function HelpPage() {
  return (
    <div className={`${styles.nutritionCanvas} ${styles.column}`}>
      <NutritionHeader view="help" />
      <NutritionActions title="¿Cómo anoto?" />
    </div>
  );
}

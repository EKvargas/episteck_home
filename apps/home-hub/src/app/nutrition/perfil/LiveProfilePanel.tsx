import { unstable_rethrow } from 'next/navigation';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { outcomeLabel, toProfilePanelModel, type ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { chipFromProfile, UNKNOWN_CHIP, type ProfileChip } from '@/integration/nutrition/profile-chip';
import { readNutritionProfile } from '@/integration/nutrition/profile.server';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';
import { NutritionHeader } from '../NutritionHeader';
import styles from '../page.module.css';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, URLs, or tokens. */
function logOutcome(outcome: string) {
  console.info(`nutrition.profile outcome=${outcome}`);
}

type Resolved = { model: ProfilePanelModel; chip: ProfileChip };

async function resolvePanel(searchParams: SearchParams): Promise<Resolved> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') {
    logOutcome('BOOTSTRAP_SESSION');
    return { model: { kind: 'SESSION' }, chip: UNKNOWN_CHIP };
  }
  if (subject.status === 'UNAVAILABLE') {
    logOutcome('BOOTSTRAP_UNAVAILABLE');
    return { model: { kind: 'UNAVAILABLE', subjectName: null }, chip: UNKNOWN_CHIP };
  }
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    logOutcome('STALE_SKIPPED');
    return { model: { kind: 'LOADING', subjectName: null }, chip: UNKNOWN_CHIP };
  }
  const envelope = await readNutritionProfile(subject.context);
  logOutcome(outcomeLabel(envelope));
  const model = toProfilePanelModel(envelope, subject.subjectName);
  // The chip comes from this same payload: no second mint or read.
  return { model, chip: envelope.delivery === 'READY' && envelope.data ? chipFromProfile(envelope.data) : UNKNOWN_CHIP };
}

export async function LiveProfilePanel({ searchParams }: { searchParams: SearchParams }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let resolved: Resolved;
  try {
    resolved = await resolvePanel(searchParams);
  } catch (error) {
    unstable_rethrow(error); // let Next's own redirect and dynamic-rendering signals through
    const name = error instanceof Error && /^[A-Za-z]{1,40}$/.test(error.name) ? error.name : 'Error';
    console.error(`nutrition.profile outcome=THREW error=${name}`);
    resolved = { model: { kind: 'UNAVAILABLE', subjectName: null }, chip: UNKNOWN_CHIP };
  }
  return (
    <>
      <NutritionHeader view="profile" chip={resolved.chip} updatedAt={null} />
      {/* A div, not <main>: AppShell already renders the page's one main landmark. */}
      <div className={styles.grid}>
        <ProfilePanel model={resolved.model} signInHref={signInHref} />
      </div>
    </>
  );
}

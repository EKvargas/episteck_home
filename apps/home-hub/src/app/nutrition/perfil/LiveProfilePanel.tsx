import { unstable_rethrow } from 'next/navigation';
import { ProfilePanel } from '@/components/features/nutrition/ProfilePanel';
import { resolveLiveSubject } from '@/integration/nutrition/live-subject.server';
import { outcomeLabel, toProfilePanelModel, type ProfilePanelModel } from '@/integration/nutrition/profile-panel-model';
import { readNutritionProfile } from '@/integration/nutrition/profile.server';
import { SERVER_CONFIGURATION } from '@/integration/state/Environment.server';

type SearchParams = Record<string, string | string[] | undefined>;

/** Exactly one line per panel render, fixed vocabulary only: never IDs, names, URLs, or tokens. */
function logOutcome(outcome: string) {
  console.info(`nutrition.profile outcome=${outcome}`);
}

async function resolvePanel(searchParams: SearchParams): Promise<ProfilePanelModel> {
  const subject = await resolveLiveSubject(searchParams);
  if (subject.status === 'SESSION') {
    logOutcome('BOOTSTRAP_SESSION');
    return { kind: 'SESSION' };
  }
  if (subject.status === 'UNAVAILABLE') {
    logOutcome('BOOTSTRAP_UNAVAILABLE');
    return { kind: 'UNAVAILABLE', subjectName: null };
  }
  if (subject.stale) {
    // AppProvider replaces a stale URL with self before it shows children; that render reads.
    logOutcome('STALE_SKIPPED');
    return { kind: 'LOADING', subjectName: null };
  }
  const envelope = await readNutritionProfile(subject.context);
  logOutcome(outcomeLabel(envelope));
  return toProfilePanelModel(envelope, subject.subjectName);
}

export async function LiveProfilePanel({ searchParams }: { searchParams: SearchParams }) {
  const signInHref = new URL('/login', SERVER_CONFIGURATION.publicOrigin).toString();
  let model: ProfilePanelModel;
  try {
    model = await resolvePanel(searchParams);
  } catch (error) {
    unstable_rethrow(error); // let Next's own redirect and dynamic-rendering signals through
    const name = error instanceof Error && /^[A-Za-z]{1,40}$/.test(error.name) ? error.name : 'Error';
    console.error(`nutrition.profile outcome=THREW error=${name}`);
    model = { kind: 'UNAVAILABLE', subjectName: null };
  }
  return <ProfilePanel model={model} signInHref={signInHref} />;
}

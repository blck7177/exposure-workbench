/**
 * One definition of "what did this run do", for both kinds of run (V13-S6c).
 *
 * `workflow_events` holds a row per state change, so a step that started and
 * finished is two rows and a step that started and failed is two different
 * rows. Collapsing to the last row per step name is what turns that into a list
 * of steps — and it has to be ONE piece of code, because two copies drift the
 * moment one of them meets a step type the other has not seen. The exposure run
 * has eleven steps and the research run has five; they are read by different
 * pages and they collapse the same way.
 *
 * Keeping the LAST row rather than the completed one is the whole point: a step
 * that failed is still the step that happened, and dropping it would leave a
 * failed run looking like a short successful one.
 */
export type StepLike = {
  step_name: string;
  status: string;
  message: string | null;
  duration_ms: number | null;
};

export function collapseSteps<T extends StepLike>(events: T[]): T[] {
  const last = new Map<string, T>();
  for (const e of events) last.set(e.step_name, e);
  return [...last.values()];
}

/** The phrase for a step, in the words the step wrote for itself. The step name
 *  is what is left when it wrote none — visible, and not a sentence invented
 *  here about work this file did not do. */
export function stepPhrase(e: StepLike): string {
  return e.message ?? e.step_name.replace(/_/g, " ");
}

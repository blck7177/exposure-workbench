/**
 * The book page's pure decisions, in one place so they can be stated in a test
 * (V25).
 *
 * Three rules that are invisible in review and wrong in a way a screenshot
 * cannot show: what a delta is against, where a missing comparison sorts, and
 * what happens when a reader points at a second thing. Each lived inline in a
 * component, where the only way to check it was to look at the page and hope
 * the case you needed was on screen.
 *
 * Nothing here computes a measure. Sorting is the rows a run wrote in another
 * order; a focus is a way of looking. The one thing that is arithmetic — the
 * delta itself — is done on the server, beside both figures it is a difference
 * of; this file only decides what to CALL it.
 */

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/**
 * The Δ column's header: which update the move is measured against.
 *
 * Without a previous dated update there is nothing to name, and the header says
 * only "Δ" — a promise of a figure that is never there is worse than a blank.
 * The year is left off because the page has already dated itself twice above
 * this table.
 */
export function deltaLabel(previousUpdate: string | null | undefined): string {
  if (!previousUpdate || previousUpdate.length < 10) return "Δ";
  const month = MONTHS[Number(previousUpdate.slice(5, 7)) - 1];
  return `Δ vs ${month} ${Number(previousUpdate.slice(8, 10))}`;
}

/**
 * Two cells of one column, ascending — with absence sorted LAST either way.
 *
 * A name with no comparison is not the smallest move and not the largest; it is
 * outside the ordering. Treating null as zero would file "not compared" in
 * among the names that genuinely did not move, which is the one distinction the
 * column exists to keep.
 */
export function compareBy(a: number | string | null, b: number | string | null): number {
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return typeof a === "string" && typeof b === "string"
    ? a.localeCompare(b)
    : (a as number) - (b as number);
}

/** The rows in another order — a copy, never the array the caller was handed. */
export function sortRows<T>(
  rows: readonly T[],
  key: (row: T) => number | string | null,
  desc: boolean,
): T[] {
  return [...rows].sort((a, b) => {
    const av = key(a);
    const bv = key(b);
    // Absence stays last whichever way the column is turned, so the reversal
    // must not reach it: `-compareBy` would float the nulls to the top.
    if (av == null || bv == null) return compareBy(av, bv);
    return desc ? -compareBy(av, bv) : compareBy(av, bv);
  });
}

export type Focus =
  | { kind: "ticker"; key: string }
  | { kind: "sector"; key: string }
  | { kind: "factor"; key: string }
  | null;

/**
 * What is focused after the reader points at something.
 *
 * A replacement, not a merge. TLT is both a holding and a factor on this desk,
 * so "the reader is pointing at the TLT holding" and "at the rates factor" are
 * different sentences about the same three letters — and two things lit at once
 * is a state no panel knows how to draw.
 */
export function focusReducer(_current: Focus, next: Focus): Focus {
  return next;
}

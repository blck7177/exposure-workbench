import { apiErrorDetail, type ApiError } from "./http";

/**
 * What to say to a person when the API refuses (V7-U3).
 *
 * Lifted out of the chat panel, which was the only surface that had learned to
 * explain itself. The issuer page special-cased 409 and showed every other
 * failure as the raw string the transport threw — so the same 429 was a
 * sentence with numbers in one place and `API 429: {"error":...}` in another,
 * and V4-S1's carefully worded 503 arrived as JSON.
 *
 * One function rather than a shared constant per case: the useful part is the
 * mapping from a server error shape to a sentence AND to what the caller must
 * then do about local state, and those two travel together. `dropSession` is
 * the only one of those today — a session id the server will never accept
 * again has to be forgotten, or every later send repeats the same failure.
 */

export type ExplainedError = {
  /** A sentence to show. Never a JSON blob, never a stack. */
  notice: string;
  /** The chat session id (if any) is dead: clear state AND storage. */
  dropSession?: boolean;
};

export function explainApiError(e: unknown): ExplainedError {
  const status = (e as ApiError).status;
  const detail = apiErrorDetail(e);

  // A concurrency signal, not an account — say it in words. The realistic cause
  // is a second tab (the session id lives in localStorage, shared per origin)
  // or a previous turn whose process died and whose lease has not expired yet.
  if (detail?.error === "turn_in_flight") {
    return { notice: "This session already has a turn running — it may be open in another tab. Wait for it to finish, or start a new session." };
  }

  // An issuer already has a run in flight for this user. Not a failure of
  // anything they did; the existing run is the thing they wanted.
  if (detail?.error === "active_run_exists") {
    return { notice: "A research run is already under way for this issuer — its progress is on this page." };
  }

  // Not an account problem and not a transient one: this conversation is
  // finished. Say which, and say what to do — the only fix is a new session.
  if (detail?.error === "session_context_exhausted") {
    return {
      notice: "This conversation has grown too long for one turn. Start a new session to carry on — your earlier answers stay in the history.",
      dropSession: true,
    };
  }

  // V4-S1. The tool service is down or refused this turn; the API answers 503
  // and the turn is over. The server's own sentence is shown rather than a
  // second wording of it: it was written for this reader, and two copies would
  // be two things to keep in step. Nothing is wrong with the session.
  if (detail?.error === "tool_face_unavailable") {
    return { notice: String(detail.detail ?? "The analysis service is briefly unavailable — try again shortly.") };
  }

  // An account. Show the numbers as the server reported them rather than
  // paraphrasing: the user wants to know what they spent and when it resets.
  if (detail?.error === "quota_exceeded") {
    return {
      notice:
        `Daily limit reached: ${detail.used}/${detail.limit} ${String(detail.kind).replace(/_/g, " ")}s` +
        (detail.scope === "global" ? " across all users" : "") +
        `. Resets ${new Date(String(detail.resets_at)).toLocaleString()}.`,
    };
  }

  // The chat session does not exist for this user — most often a stale id from
  // a previous account or a wiped database. Say it, drop the id, and let the
  // next attempt open a fresh one: there is nothing here a person can fix by
  // hand.
  //
  // Keyed on the CODE and not on the 404, which is the shape this branch had
  // when the chat panel was the only caller. The issuer page answers 404 for an
  // unknown ticker, and under the old branch a mistyped symbol told the user
  // their conversation had expired and then threw away an unrelated session id.
  if (detail?.error === "unknown_session") {
    return { notice: "That conversation is no longer available — send your message again to start a new one.", dropSession: true };
  }

  // A symbol that is not in the security master at all. The user typed it, so
  // the user can fix it — which is the whole difference between this and the
  // generic branch at the bottom.
  if (detail?.error === "unknown_ticker") {
    const t = detail.ticker ? String(detail.ticker) : "that symbol";
    return { notice: `${t} is not a symbol this desk knows. Check the spelling, or search for it from the portfolio page.` };
  }

  // Listed, and this desk has simply never prepared it. Not an error about the
  // symbol at all: the issuer page turns this one into a button (V17), and this
  // sentence is what every OTHER caller says about the same state.
  if (detail?.error === "not_prepared") {
    const t = detail.ticker ? String(detail.ticker) : "That security";
    return { notice: `${t} is listed but not yet prepared on this desk. Open its issuer page to add it — filings and figures are fetched in the background.` };
  }

  // Listed with no SEC CIK: there is nothing to read, however long we wait.
  if (detail?.error === "not_an_sec_filer") {
    const t = detail.ticker ? String(detail.ticker) : "That security";
    return { notice: `${t} does not file with the SEC, so this desk cannot read statements for it. Its price history is still available on the book.` };
  }

  // Known, but deliberately out of scope for research — not a failure and not
  // something retrying will change.
  if (detail?.error === "not_investigable") {
    const t = detail.ticker ? String(detail.ticker) : "That issuer";
    return { notice: `${t} is not set up for issuer research. Equities with SEC filings are; funds and indices are not.` };
  }

  // Something addressed by id is gone, and nothing above claimed it. Neutral on
  // purpose: this branch cannot know what the caller was asking for, so it must
  // not name one, and it must not drop a session it knows nothing about.
  if (status === 404) {
    return { notice: "That is no longer available — reload the page to see the current state." };
  }

  if (status === 401) {
    return { notice: "Sign in to run this." };
  }

  // Last resort. Deliberately not the raw message: whatever this is, the
  // person reading cannot act on a transport string. It is still logged.
  return { notice: "Something went wrong on our side. Try again in a moment." };
}

/**
 * What to say when a RUN stopped (V13-S2).
 *
 * A run's failure does not come back as an HTTP status — it is a row that says
 * `failed`, and until this existed the page rendered whatever string the
 * exception happened to carry. Three that really shipped: a provider's 429 JSON
 * quoting a billing relationship the reader is not party to, an internal
 * hostname, and "pre-fix crash (max_tokens param)".
 *
 * The rule, and it is deliberately fail-closed:
 *
 *   code set + message present -> the message. The API stores one ONLY when the
 *       failure's own words were written for a reader (RunRefused, the reaper's
 *       lease sentence), and those are better than anything here: they name the
 *       stale holdings, the date and the way out.
 *   code set, no message       -> the sentence below.
 *   NO code                    -> the generic sentence, and the message is
 *       IGNORED. Rows written before this batch carry raw provider text with no
 *       code beside it, and they were not backfilled — guessing a code from the
 *       prose is the text-matching this batch replaced. Ignoring them is how a
 *       historical row cannot leak what a new one cannot.
 *
 * Every code here must be one the API can actually produce, and every code the
 * API can produce must be here; tests/test_workflow_error_codes.py checks both
 * directions, because a branch that can never fire and a failure with no wording
 * are the same defect seen from two sides.
 */
const RUN_ERROR_WORDING: Record<string, string> = {
  inputs_unusable:
    "This run could not use the data it was given, and stopped before writing anything.",
  provider_quota:
    "The model service refused this run — its rate or spend limit was reached. Nothing was written; it is worth trying again later.",
  provider_unavailable:
    "The model service could not be reached, so the run stopped before writing anything. Try again.",
  provider_refused:
    "The model service rejected the request. That is a fault on our side, not yours — nothing was written, and it has been logged.",
  tool_face_unavailable:
    "The analysis service this run needs was unavailable, so it stopped before writing anything. Try again shortly.",
  ingest_failed:
    "Fetching the source data failed, so the run stopped before writing anything. Try again.",
  brief_not_submitted:
    "The analyst worked through its whole allowance without reaching a brief it could stand behind, so none was written. A narrower question usually gets there.",
  lease_expired:
    "The run stopped reporting and was settled. Nothing was written; start it again.",
  run_failed:
    "This run stopped before finishing. Nothing was written, and the failure has been logged.",
};

const GENERIC_RUN_ERROR =
  "This run stopped before finishing. Nothing was written.";

/**
 * The sentence for a stopped run. Never the raw string, never a stack, and
 * never a provider's own words unless the API vouched for them by storing them.
 */
export function explainRunError(
  code: string | null | undefined,
  message: string | null | undefined,
): string {
  if (!code) return GENERIC_RUN_ERROR;
  if (message && message.trim()) return message.trim();
  return RUN_ERROR_WORDING[code] ?? GENERIC_RUN_ERROR;
}

/** The codes this file has wording for — read by the cross-language guard. */
export const RUN_ERROR_CODES = Object.keys(RUN_ERROR_WORDING);

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

  // The session (or whatever was addressed) does not exist for this user —
  // most often a stale id from a previous account or a wiped database. Say it,
  // drop the id, and let the next attempt open a fresh one: there is nothing
  // here a person can fix by hand.
  if (status === 404) {
    return { notice: "That conversation is no longer available — send your message again to start a new one.", dropSession: true };
  }

  if (status === 401) {
    return { notice: "Sign in to run this." };
  }

  // Last resort. Deliberately not the raw message: whatever this is, the
  // person reading cannot act on a transport string. It is still logged.
  return { notice: "Something went wrong on our side. Try again in a moment." };
}

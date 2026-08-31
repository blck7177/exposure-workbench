"use client";

import { useEffect, useState } from "react";

import { acknowledgeDisclaimer, getMe } from "@/lib/api";

/**
 * The one-time confirmation bar (V13-S7, §9-② option A).
 *
 * The disclaimer itself lives beside the composer, where the decision is; this
 * bar exists to put a DATE on the fact that a person saw it. It shows once per
 * account — the record is `users.disclaimer_acknowledged_at`, set on the first
 * click and never moved — so unlike a localStorage flag it does not come back
 * on a new browser, and unlike a footer it cannot be honestly ignored forever.
 *
 * Anonymous visitors never see it: there is no account to record against, and
 * the standing line under the composer already says what this is and is not.
 *
 * The /me read retries a few times rather than once: the Clerk token getter is
 * registered asynchronously after mount, and a single early call would 401,
 * conclude "anonymous", and silently never show the bar to a signed-in person.
 */
const RETRY_AT_MS = [0, 1500, 5000];

export function DisclaimerGate() {
  const [due, setDue] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let ignore = false;
    const timers = RETRY_AT_MS.map((ms, i) =>
      setTimeout(async () => {
        try {
          const me = await getMe();
          if (!ignore) setDue(me.disclaimer_acknowledged_at == null);
        } catch {
          // Anonymous, or the token not registered yet — a later retry decides.
          if (i === RETRY_AT_MS.length - 1 && !ignore) setDue(false);
        }
      }, ms));
    return () => { ignore = true; timers.forEach(clearTimeout); };
  }, []);

  if (!due) return null;

  const confirm = async () => {
    if (busy) return;
    setBusy(true);
    try {
      await acknowledgeDisclaimer();
      setDue(false);
    } catch {
      // Leave the bar up: an acknowledgement that failed to record did not
      // happen, and hiding the bar anyway would be a record the DB disagrees
      // with. The route is idempotent, so clicking again is safe.
      setBusy(false);
    }
  };

  return (
    <div role="region" aria-label="Disclaimer"
      className="shrink-0 border-b border-amber-900/50 bg-amber-950/25 px-4 py-2 flex items-center gap-3">
      <p className="text-[12px] text-amber-200/90 leading-snug">
        This desk analyses filed and derived figures and is not investment advice.
        Every number links to its source; verify before acting.
      </p>
      <button onClick={confirm} disabled={busy}
        className="ml-auto shrink-0 rounded border border-amber-700/60 px-2.5 py-1 text-[11.5px] text-amber-200 hover:bg-amber-900/40 disabled:opacity-50">
        I understand
      </button>
    </div>
  );
}

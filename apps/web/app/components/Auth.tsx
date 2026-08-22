"use client";

import { useEffect } from "react";
import { SignInButton, UserButton, useAuth } from "@clerk/nextjs";
import { setAuthTokenGetter } from "@/lib/http";

// Auth is enabled only when a publishable key is present (see layout.tsx). When
// absent, the exported wrappers never mount a Clerk hook, so the public demo
// works with no ClerkProvider in the tree. The `*Inner` components always call
// hooks unconditionally (rules-of-hooks safe); the exported wrappers only decide
// whether to render them.
export const clerkEnabled = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

function AuthControlsInner() {
  const { getToken, isSignedIn } = useAuth();
  // Register Clerk's token getter with the api transport whenever auth state changes.
  useEffect(() => {
    setAuthTokenGetter(() => getToken());
    return () => setAuthTokenGetter(null);
  }, [getToken, isSignedIn]);

  return (
    <div className="flex items-center gap-3">
      {isSignedIn ? (
        <UserButton appearance={{ elements: { avatarBox: "w-6 h-6" } }} />
      ) : (
        <SignInButton mode="modal">
          <button className="text-xs font-medium text-slate-300 hover:text-white border border-[#30363d] rounded-md px-3 py-1 transition-colors">
            Sign in
          </button>
        </SignInButton>
      )}
    </div>
  );
}

/** Header control: sign-in when out, avatar menu when in. Also bridges the token. */
export function AuthControls() {
  if (!clerkEnabled) return null;
  return <AuthControlsInner />;
}

function AuthGateInner({
  children, fallback,
}: {
  children: React.ReactNode;
  fallback: React.ReactNode;
}) {
  const { isSignedIn } = useAuth();
  return <>{isSignedIn ? children : fallback}</>;
}

function SignedInProbeInner({ onChange }: { onChange: (v: boolean) => void }) {
  const { isSignedIn } = useAuth();
  useEffect(() => { onChange(!!isSignedIn); }, [isSignedIn, onChange]);
  return null;
}

function SignedInProbeDisabled({ onChange }: { onChange: (v: boolean) => void }) {
  // No Clerk means no accounts, so every visitor is anonymous. Reported rather
  // than left undefined: a caller waiting to hear would otherwise wait forever,
  // and "we never found out" and "nobody is signed in" would be the same
  // silence.
  useEffect(() => { onChange(false); }, [onChange]);
  return null;
}

/**
 * Reports whether someone is signed in, for logic that is not a render branch.
 *
 * AuthGate covers the common case — show this to signed-in visitors, that to
 * everyone else — but a decision like "which portfolio should be selected when
 * the page loads" is state, not markup, and it cannot be expressed by choosing
 * between two subtrees. A component rather than a hook for the reason the whole
 * file is shaped this way: useAuth throws without a ClerkProvider, and the
 * provider is deliberately absent when no publishable key is configured, so the
 * hook has to live behind a component that is simply not rendered then.
 */
export function SignedInProbe({ onChange }: { onChange: (v: boolean) => void }) {
  return clerkEnabled
    ? <SignedInProbeInner onChange={onChange} />
    : <SignedInProbeDisabled onChange={onChange} />;
}

/**
 * Gate interactive (write) UI behind sign-in. Auth disabled (public demo) →
 * children render as-is. Enabled → signed-out users see the fallback.
 */
export function AuthGate({
  children, fallback,
}: {
  children: React.ReactNode;
  fallback: React.ReactNode;
}) {
  if (!clerkEnabled) return <>{children}</>;
  return <AuthGateInner fallback={fallback}>{children}</AuthGateInner>;
}

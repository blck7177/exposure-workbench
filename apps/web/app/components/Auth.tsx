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

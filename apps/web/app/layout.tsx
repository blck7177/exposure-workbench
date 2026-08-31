import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ClerkProvider } from "@clerk/nextjs";
import "./globals.css";

import { AuditProvider } from "./components/audit";
import { TopBar } from "./components/TopBar";
import { AnalystDock, DockContextProvider } from "./components/analyst/Dock";
import { EvidenceProvider } from "./components/evidence/Column";

// Auth is optional at build/run time: with no publishable key (e.g. the public
// read-only demo) we skip ClerkProvider entirely so the page still renders.
const clerkEnabled = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "desk-for-one",
  description: "Portfolio exposure and issuer intelligence, every figure traceable to its source.",
};

/**
 * The workspace (V13-S6c).
 *
 * Four providers and two panes live HERE rather than on each page, and that is
 * Next 16's decision more than mine: `cacheComponents` is off, so nothing
 * preserves component state across a navigation (apps/web/README.md). A dock
 * owned by the page unmounted on every move between the book and an issuer —
 * which is precisely when somebody is mid-conversation about the thing they
 * just clicked. The same goes for the audit switch and an open piece of
 * evidence: both are ways of looking, and a way of looking that resets when you
 * follow a link is not one.
 *
 * The row is a flex, and the lanes carry their own widths: the page contributes
 * a rail and a main pane, EvidenceProvider appends its column when something is
 * open, and the dock is order-last so the evidence a reader opened sits beside
 * the answer that cited it rather than beyond the dock.
 */
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const body = (
    <html lang="en" className="dark">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-[#0d1117] text-[#e6edf3] h-screen overflow-hidden`}
      >
        <AuditProvider>
          <DockContextProvider>
            <div className="h-screen flex flex-col">
              <TopBar />
              <div className="flex-1 flex min-h-0">
                <EvidenceProvider>
                  {children}
                  <AnalystDock />
                </EvidenceProvider>
              </div>
            </div>
          </DockContextProvider>
        </AuditProvider>
      </body>
    </html>
  );
  return clerkEnabled ? <ClerkProvider>{body}</ClerkProvider> : body;
}

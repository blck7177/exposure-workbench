"use client";

import Link from "next/link";

import { AuthControls } from "./Auth";
import { AuditToggle } from "./audit";

/**
 * The bar above everything (V13-S6).
 *
 * It carries three things and deliberately not a fourth. The wordmark and the
 * way back to the book; the audit switch, which is a way of looking rather than
 * a page; and who is signed in.
 *
 * What it does NOT carry is how fresh the data is. That was tempting — it is
 * the first thing a reader should know — but freshness is a property of one
 * book, and a bar that spans every page would have to either name a book the
 * reader may not be looking at or say something vague enough to be true of all
 * of them. It sits on the book itself, under the book's own title.
 */
export function TopBar() {
  return (
    <header className="h-11 shrink-0 border-b border-[#21262d] bg-[#0d1117] flex items-center gap-3 px-4">
      <Link href="/" className="flex items-baseline gap-1.5 group">
        <span className="text-sm font-medium text-slate-200 group-hover:text-white transition-colors tracking-tight">
          desk<span className="text-slate-500">·</span>for<span className="text-slate-500">·</span>one
        </span>
      </Link>
      <div className="ml-auto flex items-center gap-2">
        <AuditToggle />
        <AuthControls />
      </div>
    </header>
  );
}

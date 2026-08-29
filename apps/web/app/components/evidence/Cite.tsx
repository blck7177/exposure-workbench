"use client";

/**
 * The list of what an answer cited, in words (V13-S3).
 *
 * The prose itself is rendered by analyst/AnswerText, which walks the text once
 * and handles citations and checked figures together — they overlap, and doing
 * them in two passes shifts the second one's offsets.
 *
 * This is the list beneath. The chips it replaces read `calc 2b5395`: a reader
 * could not tell from one whether it was a filing, a price or an alert, which
 * made the whole citation apparatus something to take on faith rather than
 * something to check.
 */

export type CiteLabels = Record<string, { type: string; label: string }>;

export function CitationList({ citations, labels, onOpen }: {
  citations: string[];
  labels?: CiteLabels;
  onOpen?: (id: string) => void;
}) {
  if (citations.length === 0) return null;
  return (
    <div className="mt-2 pt-2 border-t border-[#21262d] flex flex-col gap-1">
      {citations.map((id, i) => (
        <button key={id} onClick={() => onOpen?.(id)}
          className="grid grid-cols-[20px_1fr] gap-2 text-left text-[11.5px] text-slate-400 hover:text-slate-200 rounded px-1 py-0.5 hover:bg-[#161b22]">
          <span className="font-mono text-[10px] text-teal-400">{i + 1}</span>
          <span>{labels?.[id]?.label ?? id}</span>
        </button>
      ))}
    </div>
  );
}

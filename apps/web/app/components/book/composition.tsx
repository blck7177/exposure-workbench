"use client";

import { useState } from "react";

import { C, ChartCard, fmtDate, fmtMonth, fmtPct, fmtSignedPct, Legend, titleFromKey } from "../charts/frame";
import { TierBars } from "../charts/bars";
import { SmallMultiples, type Multiple } from "../charts/multiples";
import { useFocus } from "./Focus";
import type { LimitCheckRow, RunSeries } from "@/lib/charts";
import type { SectorExposure } from "@/lib/types";

/**
 * What the book is made of, and how that has moved (V25).
 *
 * Two panels that answer one question between them. Sectors says what the book
 * IS — seven weights against the seven tiers this book set for them — and
 * Weights across updates says whether that is new. Until now the page had
 * neither: the sector rows were stored on every run and drawn nowhere, and the
 * only comparison anywhere was a chip naming the sector that had moved most
 * since the previous run.
 *
 * Neither computes anything. The weights are rows a run wrote, the tiers are
 * the book's own limit rows, and the move between two updates was subtracted on
 * the server beside both figures it is the difference of.
 */

// ── what the book is, this update ────────────────────────────────────────────

export function Sectors({ sectors, checks, series }: {
  sectors: SectorExposure[];
  /** The run's own limit book: the tiers, and the server's name for each. */
  checks: LimitCheckRow[];
  /** The dated updates, for the move each sector made since the last one. */
  series: RunSeries | null;
}) {
  const { focus, point } = useFocus();
  const rows = [...sectors].filter((s) => s.weight != null)
    .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0));
  if (rows.length === 0) return null;

  const tiers = Object.fromEntries(
    checks.filter((c) => c.key.startsWith("sector_concentration:"))
      .map((c) => [c.key.slice("sector_concentration:".length), c]));
  const last = series?.updates[series.updates.length - 1];
  const moved = Object.fromEntries(
    (last?.sectors ?? []).map((s) => [s.sector, s.weight_change_vs_prev]));
  const previous = series && series.updates.length > 1
    ? series.updates[series.updates.length - 2].as_of : null;
  // The tiers genuinely differ by sector on this desk — Technology is allowed
  // 40% and Consumer Discretionary 15% — so a single pair of rules for the
  // whole chart would judge six sectors by the seventh's limit.
  const own = rows.filter((s) => tiers[s.sector]).length;

  return (
    <ChartCard
      title="Sectors"
      aside={`${rows.length} · this book's own tiers`}
      table={{
        columns: ["Sector", "Weight", previous ? `Move since ${fmtDate(previous)}` : "Move", "Warning", "Breach", "State"],
        rows: rows.map((s) => {
          const tier = tiers[s.sector];
          return [
            titleFromKey(s.sector), fmtPct(s.weight, 2),
            moved[s.sector] == null ? "—" : fmtSignedPct(moved[s.sector], 2),
            tier?.warning == null ? "—" : fmtPct(tier.warning, 1),
            tier?.breach == null ? "—" : fmtPct(tier.breach, 1),
            tier?.status ?? "—",
          ];
        }),
      }}
      note={<>Each bar is this update&apos;s weight; the marks are the warning and breach tiers
        this book set for that sector. {own === rows.length
          ? "Every sector here carries its own pair."
          : `${rows.length - own} of these are judged by the book-wide sector tier rather than one of their own.`}
      </>}>
      <TierBars
        tiersPerRow
        focusKey={focus?.kind === "sector" ? focus.key : null}
        onPoint={(key) => point(key ? { kind: "sector", key } : null)}
        bars={rows.map((s) => {
          const tier = tiers[s.sector];
          return {
            key: s.sector,
            label: titleFromKey(s.sector),
            value: s.weight ?? 0,
            warning: tier?.warning ?? null,
            breach: tier?.breach ?? null,
            openId: tier?.alert_id ?? null,
            tip: [
              { label: "Weight", value: fmtPct(s.weight, 2) },
              ...(moved[s.sector] == null ? [] : [{
                label: previous ? `Since ${fmtDate(previous)}` : "Since the previous update",
                value: fmtSignedPct(moved[s.sector], 2),
              }]),
              { label: "Warning tier", value: fmtPct(tier?.warning, 1) },
              { label: "Breach tier", value: fmtPct(tier?.breach, 1) },
            ],
          };
        })}
        format={(v) => fmtPct(v, 1)}
        ariaLabel="Sector weights against this book's own sector tiers"
      />
      <Legend items={[
        { label: "Weight", colour: C.s1, shape: "swatch" },
        { label: "Warning tier", colour: C.warn, shape: "tick" },
        { label: "Breach tier", colour: C.crit, shape: "tick" },
      ]} />
    </ChartCard>
  );
}

// ── and whether it is new ────────────────────────────────────────────────────

const MODES = ["Holdings", "Sectors"] as const;
type Mode = (typeof MODES)[number];

export function AcrossUpdates({ series, checks }: {
  series: RunSeries;
  checks: LimitCheckRow[];
}) {
  const { focus, point } = useFocus();
  const [mode, setMode] = useState<Mode>("Holdings");
  const updates = series.updates;
  if (updates.length < 2) return null;

  const byHolding = mode === "Holdings";
  const tierFor = (key: string) => checks.find((c) => c.key === key);
  const last = updates[updates.length - 1];

  const charts: Multiple[] = byHolding
    ? [...last.issuers]
        .filter((i) => i.weight != null)
        .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
        .map((i) => {
          const tier = tierFor(`issuer_concentration:${i.ticker}`);
          return {
            key: i.ticker,
            label: i.ticker,
            status: tier?.status ?? null,
            lit: focus == null || (focus.kind === "ticker" && focus.key === i.ticker),
            points: updates.flatMap((u) => {
              const row = u.issuers.find((r) => r.ticker === i.ticker);
              return row?.weight == null ? [] : [{ date: u.as_of, value: row.weight }];
            }),
            rules: tier?.warning == null ? [] : [{
              value: tier.warning, colour: C.warn, label: `warn ${fmtPct(tier.warning, 0)}`,
            }],
          };
        })
    : [...last.sectors]
        .filter((s) => s.weight != null)
        .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
        .map((s) => {
          const tier = tierFor(`sector_concentration:${s.sector}`);
          return {
            key: s.sector,
            label: series.labels.sectors[s.sector] ?? titleFromKey(s.sector),
            status: tier?.status ?? null,
            lit: focus == null || (focus.kind === "sector" && focus.key === s.sector),
            points: updates.flatMap((u) => {
              const row = u.sectors.find((r) => r.sector === s.sector);
              return row?.weight == null ? [] : [{ date: u.as_of, value: row.weight }];
            }),
            rules: tier?.warning == null ? [] : [{
              value: tier.warning, colour: C.warn, label: `warn ${fmtPct(tier.warning, 0)}`,
            }],
          };
        });

  const reruns = updates.filter((u) => u.runs_that_day > 1);

  return (
    <ChartCard
      title="Across updates"
      aside={`${updates.length} dated updates · ${fmtDate(updates[0].as_of)} → ${fmtDate(last.as_of)}`}
      controls={
        <div className="flex rounded border border-[#30363d] overflow-hidden text-[11px]">
          {MODES.map((m) => (
            <button key={m} onClick={() => setMode(m)} aria-pressed={mode === m}
              className={`px-2 py-0.5 ${mode === m ? "bg-[#1d2530] text-slate-200" : "text-slate-500 hover:text-slate-300"}`}>
              {m}
            </button>
          ))}
        </div>
      }
      table={{
        columns: ["Update", "Runs that day", ...charts.map((c) => c.label)],
        rows: updates.map((u) => [
          fmtDate(u.as_of), String(u.runs_that_day),
          ...charts.map((c) => {
            const pt = c.points.find((p) => p.date === u.as_of);
            return pt ? fmtPct(pt.value, 2) : "—";
          }),
        ]),
      }}
      note={<>Each point is what one update recorded, on the day it recorded it — not a
        session close, and not a claim that anything was measured between two points.
        {reruns.length > 0 && ` ${reruns.length} of these days ran more than once; the latest
        completed run of each is the one drawn.`}
        {series.detail ? ` ${series.detail}.` : ""}
      </>}>
      <SmallMultiples
        charts={charts}
        columns={2}
        dimOthers
        format={(v) => fmtPct(v, 1)}
        onPoint={(key) => point(key ? { kind: byHolding ? "ticker" : "sector", key } : null)}
        axisLabels={axisLabels(updates.map((u) => u.as_of))}
        ariaLabel={byHolding
          ? "Each holding's weight across this book's dated updates"
          : "Each sector's weight across this book's dated updates"}
      />
      <Legend items={[
        { label: "Weight at that update", colour: C.s1, shape: "line" },
        { label: "This name's warning tier", colour: C.warn, shape: "dashed" },
      ]} />
    </ChartCard>
  );
}

/** Four dates under the grid: the ends, and two inside. Given to the chart
 *  rather than derived by it, so the caption and the marks share one window. */
function axisLabels(dates: string[]): string[] {
  if (dates.length <= 4) return dates.map(fmtMonth);
  const at = [0, Math.floor(dates.length / 3), Math.floor((2 * dates.length) / 3), dates.length - 1];
  return Array.from(new Set(at)).map((i) => fmtMonth(dates[i]));
}

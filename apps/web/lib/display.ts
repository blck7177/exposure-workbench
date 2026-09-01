/**
 * How a number looks to a reader, decided once (V15-S6).
 *
 * This is the web half of analytics/display_conventions.py, and the two are
 * held to the same cases by tests/fixtures/display_cases.json: the Python test
 * and tests/display.test.ts read that one file, and a change to either side the
 * other does not mirror fails one of them. The rule used to live only in
 * AnswerBlocks.tsx, so the prose the server stored, the table the model read
 * and the figure the reader saw each rounded on their own.
 *
 * Reader precision, not ledger precision: a weight is read to a tenth of a
 * percent, a market value to two cents of a million. The ledger keeps every
 * digit and the citation drawer will show them.
 */

const PERCENT_DIGITS = { ge10: 1, lt10: 2 } as const;
const MONEY_SCALES: readonly [number, string][] = [[1e9, "B"], [1e6, "M"], [1e3, "K"]];
const MONEY_DIGITS = { ge100: 0, lt100: 2 } as const;
const MULTIPLE_DIGITS = 2;
// A per-share figure reads like a share price: dollars and cents, never the
// K/M/B compression that only makes sense for market values.
const MONEY_PER_SHARE_DIGITS = 2;

/**
 * Python's `f"{v:.{d}f}"` — which is NOT `toFixed`. Both are exact on the
 * binary value, but an exact tie (512.5 to no places, 0.125 to two) goes to
 * the even digit in Python and upward in JavaScript, so `toFixed` alone shows
 * "$513" where the server's prose says "$512". The tie is detected on the full
 * expansion (a double of ordinary magnitude terminates well inside 100 places)
 * and resolved to even by hand; everything else is `toFixed` as it stands.
 */
function fixed(v: number, digits: number): string {
  const exact = v.toFixed(100);
  const dot = exact.indexOf(".");
  const tail = exact.slice(dot + 1 + digits);
  const tie = tail[0] === "5" && /^0*$/.test(tail.slice(1));
  if (!tie) return v.toFixed(digits);
  const kept = digits === 0 ? exact.slice(0, dot) : exact.slice(0, dot + 1 + digits);
  const neg = kept.startsWith("-");
  let mag = (neg ? kept.slice(1) : kept).replace(".", "");
  if (Number(mag[mag.length - 1]) % 2 === 1) {
    mag = (BigInt(mag) + BigInt(1)).toString().padStart(mag.length, "0");
  }
  const intPart = digits === 0 ? mag : mag.slice(0, mag.length - digits);
  const fracPart = digits === 0 ? "" : `.${mag.slice(mag.length - digits)}`;
  return `${neg ? "-" : ""}${intPart || "0"}${fracPart}`;
}

/** What a reader sees. Mirrors analytics/display_conventions.py `display` exactly. */
export function display(value: number, unit_class: string): string {
  const v = value;
  if (unit_class === "RATIO" || unit_class === "PERCENT") {
    const pct = v * 100;
    const digits = Math.abs(pct) >= 10 ? PERCENT_DIGITS.ge10 : PERCENT_DIGITS.lt10;
    return `${fixed(pct, digits)}%`;
  }
  if (unit_class === "MONEY") {
    let scale = 1;
    let suffix = "";
    for (const [s, name] of MONEY_SCALES) {
      if (Math.abs(v) >= s) {
        scale = s;
        suffix = name;
        break;
      }
    }
    const scaled = v / scale;
    const digits = Math.abs(scaled) >= 100 ? MONEY_DIGITS.ge100 : MONEY_DIGITS.lt100;
    return `$${fixed(scaled, digits)}${suffix}`;
  }
  if (unit_class === "MONEY_PER_SHARE") {
    return `$${fixed(v, MONEY_PER_SHARE_DIGITS)}`;
  }
  if (unit_class === "MULTIPLE") {
    return `${fixed(v, MULTIPLE_DIGITS)}×`;
  }
  if (unit_class === "COUNT") {
    return Number.isInteger(v) ? String(v) : fixed(v, 2);
  }
  return String(value);
}

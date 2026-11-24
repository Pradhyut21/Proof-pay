import type { Answer, ResponseSchema } from "./types";

export type ParsedNumber = { ok: true; value_milli: number } | { ok: false; message: string };

/** Parse a decimal such as "540" or "5.25" into integer thousandths (at most three decimals). */
export function parseNumericInput(text: string): ParsedNumber {
  const t = text.trim().replace(",", ".");
  if (t === "") return { ok: false, message: "Enter a number." };
  if (!/^-?\d+(\.\d{1,3})?$/.test(t)) {
    return {
      ok: false,
      message: "Use digits with at most three decimals, for example 540 or 5.25.",
    };
  }
  const [whole = "0", frac = ""] = t.replace("-", "").split(".");
  const milli = Number(whole) * 1000 + Number(frac.padEnd(3, "0"));
  if (!Number.isSafeInteger(milli)) return { ok: false, message: "That number is too large." };
  return { ok: true, value_milli: t.startsWith("-") ? -milli : milli };
}

export function buildResponse(
  schema: ResponseSchema,
  input: { category?: string; numeric?: string },
): { ok: true; response: Answer } | { ok: false; message: string } {
  if (schema.type === "category") {
    if (!input.category || !schema.allowed.includes(input.category)) {
      return { ok: false, message: "Choose one of the listed answers." };
    }
    return { ok: true, response: { kind: "category", value: input.category } };
  }
  const n = parseNumericInput(input.numeric ?? "");
  if (!n.ok) return n;
  return { ok: true, response: { kind: "numeric", value_milli: n.value_milli, unit: schema.unit } };
}

/** Human-readable answer, e.g. 540000 kPa-milli -> "540 kPa". */
export function formatAnswer(a: Answer): string {
  if (a.kind === "category") return a.value;
  const v = a.value_milli / 1000;
  return `${Number.isInteger(v) ? v : v.toFixed(3).replace(/0+$/, "")} ${a.unit}`;
}

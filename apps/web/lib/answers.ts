import type { Answer, ResponseSpec } from "./types";

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

function enumOf(schema: unknown, key: string): string[] {
  const props = (schema as { properties?: Record<string, { enum?: unknown }> } | undefined)
    ?.properties;
  const values = props?.[key]?.enum;
  return Array.isArray(values) ? values.filter((v): v is string => typeof v === "string") : [];
}

/** Derive the form from the task's JSON-Schema response_schema (kind enum + value/unit enums). */
export function specFromSchema(schema: Record<string, unknown>): ResponseSpec {
  const kind = enumOf(schema, "kind")[0];
  if (kind === "category") {
    const allowed = enumOf(schema, "value");
    return allowed.length ? { type: "category", allowed } : { type: "unsupported" };
  }
  if (kind === "numeric") {
    const units = enumOf(schema, "unit");
    return units.length ? { type: "numeric", units } : { type: "unsupported" };
  }
  return { type: "unsupported" };
}

export function buildAnswer(
  spec: ResponseSpec,
  input: { category?: string; numeric?: string; unit?: string },
): { ok: true; answer: Answer } | { ok: false; message: string } {
  if (spec.type === "category") {
    if (!input.category || !spec.allowed.includes(input.category)) {
      return { ok: false, message: "Choose one of the listed answers." };
    }
    return { ok: true, answer: { kind: "category", value: input.category } };
  }
  if (spec.type === "numeric") {
    const unit = input.unit ?? spec.units[0];
    if (!unit || !spec.units.includes(unit)) return { ok: false, message: "Choose a unit." };
    const n = parseNumericInput(input.numeric ?? "");
    if (!n.ok) return n;
    return { ok: true, answer: { kind: "numeric", value_milli: n.value_milli, unit } };
  }
  return { ok: false, message: "This task's answer format is not supported by the form." };
}

/** Human-readable answer, e.g. 540000 kPa-milli -> "540 kPa". */
export function formatAnswer(a: Answer): string {
  if (a.kind === "category") return a.value;
  if (a.kind === "set") return a.values.join(", ");
  const v = a.value_milli / 1000;
  return `${Number.isInteger(v) ? v : v.toFixed(3).replace(/0+$/, "")} ${a.unit}`;
}

import { describe, expect, it } from "vitest";
import { buildResponse, formatAnswer, parseNumericInput } from "@/lib/answers";
import type { ResponseSchema } from "@/lib/types";
import { isValidSeed } from "@/lib/utils";

describe("parseNumericInput", () => {
  it("parses integers and decimals into milli units", () => {
    expect(parseNumericInput("540")).toEqual({ ok: true, value_milli: 540000 });
    expect(parseNumericInput("5.25")).toEqual({ ok: true, value_milli: 5250 });
    expect(parseNumericInput("-0.5")).toEqual({ ok: true, value_milli: -500 });
    expect(parseNumericInput("1,5")).toEqual({ ok: true, value_milli: 1500 });
  });
  it("rejects empty, malformed and over-precise input", () => {
    for (const bad of ["", "  ", "abc", "1.2345", "1e3", "--2"]) {
      expect(parseNumericInput(bad).ok).toBe(false);
    }
  });
});

describe("buildResponse", () => {
  it("requires an allowed category", () => {
    const schema: ResponseSchema = { type: "category", allowed: ["NORMAL", "STOPPED"] };
    expect(buildResponse(schema, {}).ok).toBe(false);
    expect(buildResponse(schema, { category: "OTHER" }).ok).toBe(false);
    expect(buildResponse(schema, { category: "NORMAL" })).toEqual({
      ok: true,
      response: { kind: "category", value: "NORMAL" },
    });
  });
  it("builds numeric answers with the schema unit", () => {
    const schema: ResponseSchema = { type: "numeric", unit: "kPa", scale: "milli" };
    expect(buildResponse(schema, { numeric: "540" })).toEqual({
      ok: true,
      response: { kind: "numeric", value_milli: 540000, unit: "kPa" },
    });
  });
});

describe("formatAnswer / isValidSeed", () => {
  it("formats answers", () => {
    expect(formatAnswer({ kind: "numeric", value_milli: 540000, unit: "kPa" })).toBe("540 kPa");
    expect(formatAnswer({ kind: "numeric", value_milli: 5250, unit: "bar" })).toBe("5.25 bar");
    expect(formatAnswer({ kind: "category", value: "LOW_PRESSURE" })).toBe("LOW_PRESSURE");
  });
  it("validates seeds like the API", () => {
    expect(isValidSeed("demo-1_a")).toBe(true);
    expect(isValidSeed("")).toBe(false);
    expect(isValidSeed("a b")).toBe(false);
    expect(isValidSeed("x".repeat(41))).toBe(false);
  });
});

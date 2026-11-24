import { describe, expect, it } from "vitest";
import { buildAnswer, formatAnswer, parseNumericInput, specFromSchema } from "@/lib/answers";
import { resolveUpstream } from "@/lib/server/proxy";
import { isValidSeed } from "@/lib/utils";

// Shapes produced by python/src/panelproof/questions.py.
const categorySchema = {
  type: "object",
  properties: {
    kind: { type: "string", enum: ["category"] },
    value: { type: "string", enum: ["STOPPED", "NORMAL", "LOW_PRESSURE"] },
  },
};
const numericSchema = {
  type: "object",
  properties: {
    kind: { type: "string", enum: ["numeric"] },
    value_milli: { type: "integer" },
    unit: { type: "string", enum: ["bar", "kPa", "psi"] },
  },
};

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

describe("specFromSchema / buildAnswer", () => {
  it("reads category and numeric specs from the contract response_schema", () => {
    expect(specFromSchema(categorySchema)).toEqual({
      type: "category",
      allowed: ["STOPPED", "NORMAL", "LOW_PRESSURE"],
    });
    expect(specFromSchema(numericSchema)).toEqual({
      type: "numeric",
      units: ["bar", "kPa", "psi"],
    });
    expect(specFromSchema({}).type).toBe("unsupported");
  });
  it("requires an allowed category", () => {
    const spec = specFromSchema(categorySchema);
    expect(buildAnswer(spec, {}).ok).toBe(false);
    expect(buildAnswer(spec, { category: "OTHER" }).ok).toBe(false);
    expect(buildAnswer(spec, { category: "NORMAL" })).toEqual({
      ok: true,
      answer: { kind: "category", value: "NORMAL" },
    });
  });
  it("builds numeric answers with a permitted unit", () => {
    const spec = specFromSchema(numericSchema);
    expect(buildAnswer(spec, { numeric: "540", unit: "kPa" })).toEqual({
      ok: true,
      answer: { kind: "numeric", value_milli: 540000, unit: "kPa" },
    });
    expect(buildAnswer(spec, { numeric: "540", unit: "mmHg" }).ok).toBe(false);
  });
});

describe("formatAnswer / isValidSeed", () => {
  it("formats answers", () => {
    expect(formatAnswer({ kind: "numeric", value_milli: 540000, unit: "kPa" })).toBe("540 kPa");
    expect(formatAnswer({ kind: "numeric", value_milli: 5250, unit: "bar" })).toBe("5.25 bar");
    expect(formatAnswer({ kind: "category", value: "LOW_PRESSURE" })).toBe("LOW_PRESSURE");
  });
  it("validates seeds", () => {
    expect(isValidSeed("demo-1_a")).toBe(true);
    expect(isValidSeed("")).toBe(false);
    expect(isValidSeed("a b")).toBe(false);
    expect(isValidSeed("x".repeat(41))).toBe(false);
  });
});

describe("proxy allow-list", () => {
  const none = new URLSearchParams();
  it("maps only documented local-API routes", () => {
    expect(resolveUpstream("GET", ["healthz"], none)?.path).toBe("/healthz");
    expect(resolveUpstream("GET", ["api", "v1", "tasks", "t_abc"], none)?.path).toBe(
      "/api/v1/tasks/t_abc",
    );
    expect(resolveUpstream("GET", ["api", "v1", "tasks", "t_abc", "image"], none)?.path).toBe(
      "/api/v1/tasks/t_abc/image",
    );
    expect(resolveUpstream("POST", ["api", "v1", "attempts"], none)).toEqual({
      path: "/api/v1/attempts",
      needsAuth: true,
    });
    expect(
      resolveUpstream("POST", ["api", "v1", "tasks", "t_abc", "reveal"], none)?.needsAuth,
    ).toBe(true);
  });
  it("rejects traversal, unknown routes and wrong methods", () => {
    expect(resolveUpstream("GET", ["api", "v1", "tasks", "..", "image"], none)).toBeNull();
    expect(resolveUpstream("GET", ["api", "v1", "tasks", "a/b"], none)).toBeNull();
    expect(resolveUpstream("POST", ["api", "v1", "tasks"], none)).toBeNull();
    expect(resolveUpstream("GET", ["api", "v1", "tasks", "t_abc", "reveal"], none)).toBeNull();
    expect(resolveUpstream("GET", ["admin"], none)).toBeNull();
  });
  it("forwards only well-formed paging parameters", () => {
    const q = new URLSearchParams({ limit: "50", cursor: "t_x;drop" });
    expect(resolveUpstream("GET", ["api", "v1", "tasks"], q)?.path).toBe("/api/v1/tasks?limit=50");
  });
});

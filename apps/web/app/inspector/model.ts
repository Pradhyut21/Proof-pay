import { isAnswer } from "@/lib/contracts";
import { IMAGE_HEIGHT, IMAGE_WIDTH, type EvidenceRegion, type Reveal } from "@/lib/types";

type ReadingUnit = "kPa" | "bar" | "psi";

export interface RecoveredReading {
  role: "Inlet" | "Outlet";
  unit: ReadingUnit;
  valueMilli: number;
  uncertaintyMilliKpa: number;
  generatorValueMilli: number | null;
}

export interface RasterEvidence {
  status: "verified" | "rejected";
  verifierVersion: string;
  readings: RecoveredReading[];
  deltaMilliKpa: number | null;
  agreement: "agrees" | "disagrees" | "unavailable";
  rustRuleAgrees: boolean | null;
  regions: EvidenceRegion[];
  reasonCodes: string[];
}

export interface InspectorEvidence {
  reference: Reveal;
  raster: RasterEvidence | null;
}

export function asRecord(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function safeInteger(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function nonnegativeInteger(value: unknown): value is number {
  return safeInteger(value) && value >= 0;
}

function safeLabel(value: unknown): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= 160;
}

function parseRegion(value: unknown): EvidenceRegion | null {
  const region = asRecord(value);
  if (!region) return null;
  const { instrument_id, x, y, width, height } = region;
  if (
    !safeLabel(instrument_id) ||
    !nonnegativeInteger(x) ||
    !nonnegativeInteger(y) ||
    !safeInteger(width) ||
    !safeInteger(height) ||
    width <= 0 ||
    height <= 0 ||
    x + width > IMAGE_WIDTH ||
    y + height > IMAGE_HEIGHT
  ) {
    return null;
  }
  return { instrument_id, x, y, width, height };
}

export function parseReference(value: unknown, taskId: string): Reveal | null {
  const record = asRecord(value);
  if (record?.task_id !== taskId || !isAnswer(record.answer) || !safeLabel(record.solver_version)) {
    return null;
  }
  const regions = Array.isArray(record.evidence_regions)
    ? record.evidence_regions.map(parseRegion).filter((region) => region !== null)
    : [];
  return {
    task_id: taskId,
    answer: record.answer,
    tolerance_milli: nonnegativeInteger(record.tolerance_milli) ? record.tolerance_milli : null,
    evidence_regions: [
      ...new Map(regions.map((region) => [region.instrument_id, region])).values(),
    ],
    solver_version: record.solver_version,
  };
}

function parseReading(
  value: unknown,
  generated: unknown,
  role: RecoveredReading["role"],
): RecoveredReading | null {
  const item = asRecord(value);
  if (!item) return null;
  const { unit, reading_milli, uncertainty_mkpa } = item;
  if (
    (unit !== "kPa" && unit !== "bar" && unit !== "psi") ||
    !safeInteger(reading_milli) ||
    !nonnegativeInteger(uncertainty_mkpa)
  ) {
    return null;
  }
  const original = asRecord(generated);
  const generatorValueMilli =
    original?.unit === unit && safeInteger(original.value_milli) ? original.value_milli : null;
  return {
    role,
    unit,
    valueMilli: reading_milli,
    uncertaintyMilliKpa: uncertainty_mkpa,
    generatorValueMilli,
  };
}

function recoveredRegion(value: unknown, instrumentId: string): EvidenceRegion | null {
  const reading = asRecord(value);
  const center = reading?.center;
  const radius = reading?.radius;
  if (
    !Array.isArray(center) ||
    center.length !== 2 ||
    !center.every(Number.isFinite) ||
    typeof radius !== "number" ||
    !Number.isFinite(radius) ||
    radius <= 0
  )
    return null;
  const [x, y] = center;
  return parseRegion({
    instrument_id: instrumentId,
    x: Math.round(x - radius),
    y: Math.round(y - radius),
    width: Math.round(radius * 2),
    height: Math.round(radius * 2),
  });
}

function matchesReference(value: unknown, reference: Reveal["answer"]): boolean {
  const answer = asRecord(value);
  if (answer?.kind !== reference.kind) return false;
  switch (reference.kind) {
    case "category":
      return answer.value === reference.value;
    case "numeric":
      return answer.unit === reference.unit && answer.value_milli === reference.value_milli;
    case "set":
      return (
        Array.isArray(answer.values) &&
        answer.values.length === reference.values.length &&
        [...answer.values]
          .sort()
          .every((value, index) => value === [...reference.values].sort()[index])
      );
  }
}

export function projectRasterEvidence(value: unknown, reference: Reveal): RasterEvidence | null {
  const row = asRecord(value);
  if (row?.task_id !== reference.task_id || !matchesReference(row.answer, reference.answer)) {
    return null;
  }
  const validation = asRecord(row.validation);
  if (!validation || !safeLabel(validation.verifier_version)) return null;

  const { verdict, verifier_version: verifierVersion, reasons } = validation;
  if (verdict !== "verified") {
    if (verdict !== "rejected" && verdict !== "unreadable" && verdict !== "unsupported")
      return null;
    const reasonCodes = Array.isArray(reasons)
      ? reasons
          .filter(
            (reason): reason is string =>
              typeof reason === "string" && /^[\w:.-]{1,100}$/.test(reason),
          )
          .slice(0, 12)
      : [];
    return {
      status: "rejected",
      verifierVersion,
      readings: [],
      deltaMilliKpa: null,
      agreement: "unavailable",
      rustRuleAgrees: null,
      regions: [],
      reasonCodes,
    };
  }

  const readings = asRecord(validation.readings);
  const original = asRecord(row.generator_readings);
  const inlet = parseReading(readings?.INLET, original?.INLET, "Inlet");
  const outlet = parseReading(readings?.OUTLET, original?.OUTLET, "Outlet");
  if (!inlet || !outlet) return null;

  const derived = asRecord(validation.derived);
  let recoveredAnswer: string | undefined;
  if (row.kind === "state" && typeof derived?.state === "string") recoveredAnswer = derived.state;
  if (row.kind === "consistency" && typeof derived?.alarm_consistent === "boolean") {
    recoveredAnswer = derived.alarm_consistent ? "CONSISTENT" : "CONTRADICTION";
  }
  let agreement: RasterEvidence["agreement"] = "unavailable";
  if (recoveredAnswer !== undefined && reference.answer.kind === "category") {
    agreement = recoveredAnswer === reference.answer.value ? "agrees" : "disagrees";
  }
  return {
    status: "verified",
    verifierVersion,
    readings: [inlet, outlet],
    deltaMilliKpa: safeInteger(derived?.delta_mkpa) ? derived.delta_mkpa : null,
    agreement,
    rustRuleAgrees:
      typeof validation.rust_rule_agrees === "boolean" ? validation.rust_rule_agrees : null,
    regions: [
      recoveredRegion(readings?.INLET, "Recovered inlet"),
      recoveredRegion(readings?.OUTLET, "Recovered outlet"),
    ].filter((region) => region !== null),
    reasonCodes: [],
  };
}

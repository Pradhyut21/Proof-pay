export const reportConditions = ["C0", "C1", "C3"] as const;
export const reportSkills = ["R", "C", "M", "X"] as const;
const reportDifficulties = ["easy", "medium", "hard"] as const;
const pairKinds = ["semantic", "nuisance", "preserving"] as const;
const failureKinds = [
  "parse_error",
  "invalid_response",
  "provider_error",
  "timeout",
  "refusal",
] as const;

type MapValue = Record<string, unknown>;

function object(value: unknown): MapValue {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Invalid report record");
  }
  return value as MapValue;
}

function count(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) {
    throw new Error("Invalid report count");
  }
  return value;
}

function rate(value: unknown, minimum = 0): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value) || value < minimum || value > 1) {
    throw new Error("Invalid report rate");
  }
  return value;
}

function identifier(value: unknown): string {
  if (typeof value !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$/.test(value)) {
    throw new Error("Invalid report identifier");
  }
  return value;
}

function digest(value: unknown): string {
  if (typeof value !== "string" || !/^[a-f0-9]{64}$/.test(value)) {
    throw new Error("Invalid report checksum");
  }
  return value;
}

function named<T>(
  value: unknown,
  keys: readonly string[],
  parse: (input: unknown) => T,
): Record<string, T> {
  const source = object(value);
  return Object.fromEntries(
    keys.filter((key) => Object.hasOwn(source, key)).map((key) => [key, parse(source[key])]),
  );
}

function summary(value: unknown) {
  const row = object(value);
  const denominators = object(row.denominators);
  const parsed = {
    attempted: count(row.attempted),
    completed: count(row.completed),
    valid: count(row.valid),
    correct: count(row.correct),
    valid_only_accuracy: rate(row.valid_only_accuracy),
    all_attempt_accuracy: rate(row.all_attempt_accuracy),
    failures: named(row.failures, failureKinds, count),
    denominators: {
      valid_only: count(denominators.valid_only),
      all_attempt: count(denominators.all_attempt),
    },
  };
  if (
    parsed.correct > parsed.valid ||
    parsed.valid > parsed.completed ||
    parsed.completed > parsed.attempted ||
    parsed.denominators.valid_only !== parsed.valid ||
    parsed.denominators.all_attempt !== parsed.attempted
  ) {
    throw new Error("Invalid report denominators");
  }
  return parsed;
}

function pair(value: unknown) {
  const row = object(value);
  const denominators = object(row.denominators);
  return {
    pairs: count(row.pairs),
    pair_correctness: rate(row.pair_correctness),
    directional_sensitivity: rate(row.directional_sensitivity),
    invariance: rate(row.invariance),
    both_correct: count(row.both_correct),
    denominators: {
      sensitivity: count(denominators.sensitivity),
      invariance: count(denominators.invariance),
    },
  };
}

function condition(value: unknown) {
  const row = object(value);
  const interval = object(row.ci_all_attempt_accuracy);
  return {
    ...summary(row),
    by_skill: named(row.by_skill, reportSkills, summary),
    by_difficulty: named(row.by_difficulty, reportDifficulties, summary),
    pairs: named(row.pairs, pairKinds, pair),
    groups_with_2plus_tasks: count(row.groups_with_2plus_tasks),
    worst_group_accuracy: rate(row.worst_group_accuracy),
    all_variants_correct_groups: count(row.all_variants_correct_groups),
    all_variants_correct_rate: rate(row.all_variants_correct_rate),
    ci_all_attempt_accuracy: {
      n_groups: count(interval.n_groups),
      lo95: rate(interval.lo95 ?? null),
      hi95: rate(interval.hi95 ?? null),
    },
  };
}

function grounding(value: unknown) {
  if (value === null) return null;
  const row = object(value);
  return {
    gain: rate(row.gain, -1),
    matched_tasks: count(row.matched_tasks),
    n_groups: count(row.n_groups),
    lo95: rate(row.lo95, -1),
    hi95: rate(row.hi95, -1),
  };
}

function model(value: unknown) {
  const row = object(value);
  return {
    matched_task_count: count(row.matched_task_count),
    tasks_missing_a_condition: named(row.tasks_missing_a_condition, reportConditions, count),
    conditions: named(row.conditions, reportConditions, condition),
    grounding_gain_C1_minus_C0: grounding(row.grounding_gain_C1_minus_C0),
  };
}

function measuredManifest(value: unknown, modelIds: string[]) {
  const row = object(value);
  if (!Array.isArray(row.models) || row.models.length !== modelIds.length || !modelIds.length) {
    throw new Error("Invalid measured model provenance");
  }
  const models = row.models.map((entry) => {
    const info = object(entry);
    if (!Array.isArray(info.run_ids) || !info.run_ids.length)
      throw new Error("Missing measured runs");
    return {
      provider: identifier(info.provider),
      model_id: identifier(info.model_id),
      model_revision: identifier(info.model_revision),
      run_ids: info.run_ids.map(identifier),
    };
  });
  const actual = new Set(models.map((row) => row.model_id));
  if (actual.size !== modelIds.length || modelIds.some((id) => !actual.has(id))) {
    throw new Error("Measured model provenance does not match report");
  }
  const xScope = row.x_scope;
  if (xScope !== undefined && xScope !== "balanced" && xScope !== "full") {
    throw new Error("Invalid measured X scope");
  }
  return {
    dataset_manifest_sha256: digest(row.dataset_manifest_sha256),
    selection_hash: digest(row.selection_hash),
    c3_observations_sha256: digest(row.c3_observations_sha256),
    public_inputs_sha256: named(row.public_inputs_sha256, reportConditions, digest),
    x_scope: xScope ?? null,
    x_task_count: row.x_task_count === undefined ? null : count(row.x_task_count),
    models,
  };
}

export type ReportSummary = ReturnType<typeof summary>;
export type ReportCondition = ReturnType<typeof condition>;
export type ReportModel = ReturnType<typeof model>;
export type ReportManifest = ReturnType<typeof measuredManifest>;

export type RunReport = {
  status: "demo" | "development" | "measured";
  models: Record<string, ReportModel>;
  provenance: ReportManifest | null;
};

/** Parse only public aggregates supported by the metrics report contract. */
export function parseRunReport(value: unknown): RunReport {
  const source = object(value);
  if (typeof source.mock !== "boolean") throw new Error("Missing report provenance label");
  const rawModels = object(source.models);
  const models = Object.fromEntries(
    Object.entries(rawModels).map(([id, info]) => [identifier(id), model(info)]),
  );
  const status = source.mock ? "demo" : source.banner === "MEASURED" ? "measured" : "development";
  return {
    status,
    models,
    provenance:
      status === "measured" ? measuredManifest(source.provenance, Object.keys(models)) : null,
  };
}

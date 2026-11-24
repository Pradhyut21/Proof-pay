export const SCHEMA_VERSION = '1.0.0' as const;

type SchemaVersion = typeof SCHEMA_VERSION;
type JsonValue = null | boolean | number | string | JsonValue[] | JsonObject;
type JsonObject = { [key: string]: JsonValue };

const UNITS = ['kPa', 'bar', 'psi'] as const;
const CONDITIONS = ['C0', 'C1', 'C2', 'C3', 'C4'] as const;
const ANSWERED_STATUSES = ['correct', 'incorrect', 'unscored'] as const;
const ATTEMPT_STATUSES = [
  ...ANSWERED_STATUSES,
  'invalid_response',
  'provider_error',
  'skipped',
] as const;
const SPLITS = ['dev', 'test_frozen', 'diagnostic_abstain', 'real_slice'] as const;
const SKILLS = [
  'reading',
  'conversion',
  'association',
  'difference',
  'operational_state',
  'indicator_consistency',
] as const;
const VARIANTS = [
  'original',
  'semantic',
  'semantic_preserve',
  'nonsemantic',
  'evidence_removed',
] as const;
const VALIDATION_STATUSES = ['pending', 'accepted', 'rejected'] as const;

type Condition = (typeof CONDITIONS)[number];
export type PressureUnit = (typeof UNITS)[number];

interface VersionedRecord {
  schema_version: SchemaVersion;
}

export interface Pressure {
  value_milli: number;
  unit: PressureUnit;
}

export interface Pump {
  id: string;
  label: string;
  inlet: Pressure;
  outlet: Pressure;
  run: boolean;
  alarm: boolean;
}

export interface Scene extends VersionedRecord {
  base_scene_id: string;
  seed: number;
  layout_family: string;
  style_family: string;
  equipment: Pump[];
}

export type Answer =
  | { kind: 'category'; value: string }
  | ({ kind: 'numeric' } & Pressure)
  | { kind: 'set'; values: string[] };

export interface PublicTask extends VersionedRecord {
  task_id: string;
  image_path: string;
  question: string;
  public_rules: string;
  response_schema: JsonObject;
}

export interface EvidenceRegion {
  instrument_id: string;
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface PrivateTask extends VersionedRecord {
  task_id: string;
  base_scene_id: string;
  group_id: string;
  variant_kind: (typeof VARIANTS)[number];
  split: (typeof SPLITS)[number];
  skill: (typeof SKILLS)[number];
  difficulty: JsonObject;
  answer: Answer;
  tolerance_milli?: number | null;
  evidence_regions?: EvidenceRegion[] | null;
  solver_version: string;
  image_sha256: string;
  validation_status: (typeof VALIDATION_STATUSES)[number];
}

export interface Attempt extends VersionedRecord {
  task_id: string;
  run_id: string;
  model_id: string;
  provider: string;
  condition: Condition;
  timestamp: string;
  latency_ms: number;
  status: (typeof ATTEMPT_STATUSES)[number];
  model_revision?: string | null;
  raw_output?: string | null;
  parsed_answer?: Answer | null;
  error?: string | null;
  input_tokens?: number | null;
  output_tokens?: number | null;
  cost_usd?: number | null;
  cached?: boolean | null;
}

interface Resolution {
  width: number;
  height: number;
}

export interface Run extends VersionedRecord {
  run_id: string;
  model_id: string;
  provider: string;
  condition: Condition;
  prompt_version: string;
  seed: number;
  max_calls: number;
  selected_task_ids_sha256: string;
  environment_fingerprint: string;
  demo_only: boolean;
  model_revision?: string | null;
  resolution?: Resolution | null;
  sampling_parameters?: JsonObject | null;
  max_cost_usd?: number | null;
}

const ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$/u;
const IMAGE_PATTERN = /^images\/[A-Za-z0-9][A-Za-z0-9_-]{0,79}\.png$/u;
const SHA256_PATTERN = /^[a-f0-9]{64}$/u;
const TIMESTAMP_PATTERN =
  /^([0-9]{4})-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{1,6})?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])$/u;

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function hasOnlyFields(
  value: Record<string, unknown>,
  required: readonly string[],
  optional: readonly string[] = [],
): boolean {
  return (
    required.every((key) => Object.hasOwn(value, key)) &&
    Object.keys(value).every((key) => required.includes(key) || optional.includes(key))
  );
}

function isChoice<const T extends string>(value: unknown, choices: readonly T[]): value is T {
  return choices.some((choice) => choice === value);
}

function matches(value: unknown, pattern: RegExp): value is string {
  return typeof value === 'string' && value.trim() === value && pattern.test(value);
}

function hasText(value: unknown, maximum: number): value is string {
  return typeof value === 'string' && value.length > 0 && [...value].length <= maximum;
}

function isLabel(value: unknown): value is string {
  return hasText(value, 160);
}

function isText(value: unknown): value is string {
  return hasText(value, 4096);
}

function isSafeInteger(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value);
}

function isNonNegativeInteger(value: unknown): value is number {
  return isSafeInteger(value) && value >= 0;
}

function isPositiveInteger(value: unknown): value is number {
  return isSafeInteger(value) && value > 0;
}

function isNonNegativeNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value >= 0;
}

function isBoolean(value: unknown): value is boolean {
  return typeof value === 'boolean';
}

function isString(value: unknown): value is string {
  return typeof value === 'string';
}

function isOptional<T>(
  value: unknown,
  predicate: (value: unknown) => value is T,
): value is T | undefined | null {
  return value === undefined || value === null || predicate(value);
}

function isJsonObject(value: unknown): value is JsonObject {
  return isObject(value) && Object.values(value).every(isJsonValue);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string' || typeof value === 'boolean' || value === null) return true;
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isJsonObject(value);
}

function isTimestamp(value: unknown): value is string {
  if (!matches(value, TIMESTAMP_PATTERN)) return false;

  const year = Number(value.slice(0, 4));
  const month = Number(value.slice(5, 7));
  const day = Number(value.slice(8, 10));
  const leap = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const monthLengths = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return year !== 0 && day <= (monthLengths[month - 1] ?? 0);
}

function isPressure(value: unknown): value is Pressure {
  return (
    isObject(value) &&
    hasOnlyFields(value, ['value_milli', 'unit']) &&
    isSafeInteger(value.value_milli) &&
    isChoice(value.unit, UNITS)
  );
}

function isPump(value: unknown): value is Pump {
  return (
    isObject(value) &&
    hasOnlyFields(value, ['id', 'label', 'inlet', 'outlet', 'run', 'alarm']) &&
    matches(value.id, ID_PATTERN) &&
    isLabel(value.label) &&
    isPressure(value.inlet) &&
    isPressure(value.outlet) &&
    isBoolean(value.run) &&
    isBoolean(value.alarm)
  );
}

export function isScene(value: unknown): value is Scene {
  if (
    !isObject(value) ||
    !hasOnlyFields(value, [
      'schema_version',
      'base_scene_id',
      'seed',
      'layout_family',
      'style_family',
      'equipment',
    ]) ||
    value.schema_version !== SCHEMA_VERSION ||
    !matches(value.base_scene_id, ID_PATTERN) ||
    !isNonNegativeInteger(value.seed) ||
    !matches(value.layout_family, ID_PATTERN) ||
    !matches(value.style_family, ID_PATTERN) ||
    !Array.isArray(value.equipment) ||
    value.equipment.length < 1 ||
    value.equipment.length > 2 ||
    !value.equipment.every(isPump)
  ) {
    return false;
  }
  return (
    new Set(value.equipment.map((pump) => pump.id)).size === value.equipment.length &&
    new Set(value.equipment.map((pump) => pump.label)).size === value.equipment.length
  );
}

export function isAnswer(value: unknown): value is Answer {
  if (!isObject(value)) return false;

  switch (value.kind) {
    case 'category':
      return hasOnlyFields(value, ['kind', 'value']) && isLabel(value.value);
    case 'numeric':
      return (
        hasOnlyFields(value, ['kind', 'value_milli', 'unit']) &&
        isSafeInteger(value.value_milli) &&
        isChoice(value.unit, UNITS)
      );
    case 'set':
      return (
        hasOnlyFields(value, ['kind', 'values']) &&
        Array.isArray(value.values) &&
        value.values.length <= 32 &&
        value.values.every(isLabel) &&
        new Set(value.values).size === value.values.length
      );
    default:
      return false;
  }
}

export function isPublicTask(value: unknown): value is PublicTask {
  return (
    isObject(value) &&
    hasOnlyFields(value, [
      'schema_version',
      'task_id',
      'image_path',
      'question',
      'public_rules',
      'response_schema',
    ]) &&
    value.schema_version === SCHEMA_VERSION &&
    matches(value.task_id, ID_PATTERN) &&
    matches(value.image_path, IMAGE_PATTERN) &&
    isText(value.question) &&
    isText(value.public_rules) &&
    isJsonObject(value.response_schema)
  );
}

function isEvidenceRegion(value: unknown): value is EvidenceRegion {
  return (
    isObject(value) &&
    hasOnlyFields(value, ['instrument_id', 'x', 'y', 'width', 'height']) &&
    matches(value.instrument_id, ID_PATTERN) &&
    isNonNegativeInteger(value.x) &&
    isNonNegativeInteger(value.y) &&
    isPositiveInteger(value.width) &&
    isPositiveInteger(value.height)
  );
}

function isEvidenceList(value: unknown): value is EvidenceRegion[] {
  return Array.isArray(value) && value.every(isEvidenceRegion);
}

export function isPrivateTask(value: unknown): value is PrivateTask {
  return (
    isObject(value) &&
    hasOnlyFields(
      value,
      [
        'schema_version',
        'task_id',
        'base_scene_id',
        'group_id',
        'variant_kind',
        'split',
        'skill',
        'difficulty',
        'answer',
        'solver_version',
        'image_sha256',
        'validation_status',
      ],
      ['tolerance_milli', 'evidence_regions'],
    ) &&
    value.schema_version === SCHEMA_VERSION &&
    matches(value.task_id, ID_PATTERN) &&
    matches(value.base_scene_id, ID_PATTERN) &&
    matches(value.group_id, ID_PATTERN) &&
    isChoice(value.variant_kind, VARIANTS) &&
    isChoice(value.split, SPLITS) &&
    (value.variant_kind !== 'evidence_removed' || value.split === 'diagnostic_abstain') &&
    isChoice(value.skill, SKILLS) &&
    isJsonObject(value.difficulty) &&
    isAnswer(value.answer) &&
    isOptional(value.tolerance_milli, isNonNegativeInteger) &&
    (value.tolerance_milli == null || value.answer.kind === 'numeric') &&
    isOptional(value.evidence_regions, isEvidenceList) &&
    isLabel(value.solver_version) &&
    matches(value.image_sha256, SHA256_PATTERN) &&
    isChoice(value.validation_status, VALIDATION_STATUSES)
  );
}

export function isAttempt(value: unknown): value is Attempt {
  return (
    isObject(value) &&
    hasOnlyFields(
      value,
      [
        'schema_version',
        'task_id',
        'run_id',
        'model_id',
        'provider',
        'condition',
        'timestamp',
        'latency_ms',
        'status',
      ],
      [
        'model_revision',
        'raw_output',
        'parsed_answer',
        'error',
        'input_tokens',
        'output_tokens',
        'cost_usd',
        'cached',
      ],
    ) &&
    value.schema_version === SCHEMA_VERSION &&
    matches(value.task_id, ID_PATTERN) &&
    matches(value.run_id, ID_PATTERN) &&
    isLabel(value.model_id) &&
    isLabel(value.provider) &&
    isChoice(value.condition, CONDITIONS) &&
    isTimestamp(value.timestamp) &&
    isNonNegativeInteger(value.latency_ms) &&
    isChoice(value.status, ATTEMPT_STATUSES) &&
    isOptional(value.model_revision, isLabel) &&
    isOptional(value.raw_output, isString) &&
    isOptional(value.parsed_answer, isAnswer) &&
    isChoice(value.status, ANSWERED_STATUSES) === (value.parsed_answer != null) &&
    isOptional(value.error, isString) &&
    isOptional(value.input_tokens, isNonNegativeInteger) &&
    isOptional(value.output_tokens, isNonNegativeInteger) &&
    isOptional(value.cost_usd, isNonNegativeNumber) &&
    isOptional(value.cached, isBoolean)
  );
}

function isResolution(value: unknown): value is Resolution {
  return (
    isObject(value) &&
    hasOnlyFields(value, ['width', 'height']) &&
    isPositiveInteger(value.width) &&
    isPositiveInteger(value.height)
  );
}

export function isRun(value: unknown): value is Run {
  return (
    isObject(value) &&
    hasOnlyFields(
      value,
      [
        'schema_version',
        'run_id',
        'model_id',
        'provider',
        'condition',
        'prompt_version',
        'seed',
        'max_calls',
        'selected_task_ids_sha256',
        'environment_fingerprint',
        'demo_only',
      ],
      ['model_revision', 'resolution', 'sampling_parameters', 'max_cost_usd'],
    ) &&
    value.schema_version === SCHEMA_VERSION &&
    matches(value.run_id, ID_PATTERN) &&
    isLabel(value.model_id) &&
    isLabel(value.provider) &&
    isChoice(value.condition, CONDITIONS) &&
    isLabel(value.prompt_version) &&
    isNonNegativeInteger(value.seed) &&
    isNonNegativeInteger(value.max_calls) &&
    matches(value.selected_task_ids_sha256, SHA256_PATTERN) &&
    isText(value.environment_fingerprint) &&
    isBoolean(value.demo_only) &&
    isOptional(value.model_revision, isLabel) &&
    isOptional(value.resolution, isResolution) &&
    isOptional(value.sampling_parameters, isJsonObject) &&
    isOptional(value.max_cost_usd, isNonNegativeNumber)
  );
}

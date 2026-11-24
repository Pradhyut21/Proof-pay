import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { isAnswer, isAttempt, isPrivateTask, isPublicTask, isRun, isScene } from "./contracts.ts";

function example(name) {
  const path = new URL("../../../schemas/examples/" + name + ".json", import.meta.url);
  return JSON.parse(readFileSync(path, "utf8"));
}

test("TypeScript accepts the common example records", () => {
  for (const [name, guard] of [
    ["scene", isScene],
    ["task_public", isPublicTask],
    ["task_private", isPrivateTask],
    ["attempt", isAttempt],
    ["run", isRun],
  ]) {
    assert(guard(example(name)), name);
  }
});

test("public types reject unexpected or private data", () => {
  const task = example("task_public");
  assert(!isPublicTask({ ...task, answer: { kind: "category", value: "NORMAL" } }));
  assert(!isPublicTask({ ...task, seed: 42 }));
  assert(!isPublicTask({ ...task, image_path: "images/../hidden.png" }));
  assert(!isPublicTask({ ...task, image_path: "images/foo.png\n" }));
  assert(!isPublicTask(example("task_private")));
});

test("private and scene guards enforce split, hash and unique IDs", () => {
  const task = example("task_private");
  assert(!isPrivateTask({ ...task, variant_kind: "evidence_removed" }));
  assert(!isPrivateTask({ ...task, image_sha256: "invalid" }));
  assert(!isPrivateTask({ ...task, tolerance_milli: 1 }));
  const scene = example("scene");
  assert(!isScene({ ...scene, equipment: [...scene.equipment, ...scene.equipment] }));
});

test("attempts distinguish outcomes from answered rows and validate timestamps", () => {
  const attempt = example("attempt");
  assert(!isAttempt({ ...attempt, status: "provider_error" }));
  assert(!isAttempt({ ...attempt, parsed_answer: null }));
  assert(!isAttempt({ ...attempt, timestamp: "2026-11-31T07:00:00Z" }));
  assert(isAttempt({ ...attempt, status: "provider_error", parsed_answer: null }));
});

test("answer and run guards reject invalid units, labels, and budgets", () => {
  assert(!isAnswer({ kind: "numeric", value_milli: 100, unit: "Pa" }));
  assert(!isAnswer({ kind: "numeric", value_milli: "100", unit: "kPa" }));
  assert(!isAnswer({ kind: "set", values: ["a", "a"] }));
  assert(!isRun({ ...example("run"), max_calls: -1 }));
});

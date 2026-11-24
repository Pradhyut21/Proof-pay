import { createHash } from "node:crypto";
import { open, realpath } from "node:fs/promises";
import path from "node:path";
import type { Reveal } from "@/lib/types";
import { asRecord, projectRasterEvidence } from "../model";

const KEY_FILE = "private/keys.jsonl";
const MAX_MANIFEST_BYTES = 512 * 1024;
const MAX_KEYS_BYTES = 5 * 1024 * 1024;

/** Both files have fixed names and must resolve inside the selected local bundle. */
async function readBoundedFile(
  root: string,
  name: string,
  maximum: number,
): Promise<Buffer | null> {
  const expected = path.join(root, ...name.split("/"));
  if ((await realpath(expected)) !== expected) return null;
  const handle = await open(expected, "r");
  try {
    const stat = await handle.stat();
    if (!stat.isFile() || stat.size > maximum) return null;
    const buffer = Buffer.alloc(stat.size + 1);
    let length = 0;
    while (length < buffer.length) {
      const { bytesRead } = await handle.read(buffer, length, buffer.length - length, length);
      if (bytesRead === 0) break;
      length += bytesRead;
    }
    return length === stat.size ? buffer.subarray(0, length) : null;
  } finally {
    await handle.close();
  }
}

/** Call only after Axum authorizes this exact task in the selected dev bundle. */
export async function readRasterEvidence(directory: string, reference: Reveal) {
  try {
    const root = await realpath(directory);
    const manifestBytes = await readBoundedFile(root, "manifest.json", MAX_MANIFEST_BYTES);
    if (!manifestBytes) return null;
    const manifest = asRecord(JSON.parse(manifestBytes.toString("utf8")));
    const expectedHash = asRecord(manifest?.files)?.[KEY_FILE];
    if (typeof expectedHash !== "string" || !/^[a-f0-9]{64}$/.test(expectedHash)) return null;
    const keys = await readBoundedFile(root, KEY_FILE, MAX_KEYS_BYTES);
    if (!keys || createHash("sha256").update(keys).digest("hex") !== expectedHash) return null;

    let matched: unknown;
    for (const line of keys.toString("utf8").split("\n")) {
      if (!line.trim()) continue;
      const row: unknown = JSON.parse(line);
      if (asRecord(row)?.task_id !== reference.task_id) continue;
      if (matched) return null;
      matched = row;
    }
    return projectRasterEvidence(matched, reference);
  } catch {
    return null;
  }
}

import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Mirrors the API's `valid_seed`: 1-40 chars of [A-Za-z0-9_-]. */
export function isValidSeed(seed: string): boolean {
  return /^[A-Za-z0-9_-]{1,40}$/.test(seed);
}

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

"use client";

import { useEffect, useRef, useState } from "react";
import { PanelViewer } from "@/components/PanelViewer";
import { QuestionForm } from "@/components/QuestionForm";
import { RunStatus } from "@/components/RunStatus";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { isValidSeed } from "@/lib/utils";
import type { Difficulty, Job, PublicTask } from "@/lib/types";

const POLL_MS = 1000;
const MAX_COUNT = 4;

export default function FactoryPage() {
  const [seed, setSeed] = useState("demo-1");
  const [count, setCount] = useState("4");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [job, setJob] = useState<Job>();
  const [tasks, setTasks] = useState<PublicTask[]>([]);
  const [error, setError] = useState<string>();
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);

  useEffect(() => () => clearTimeout(timer.current), []);

  async function loadTasks(ids: string[]) {
    const wanted = new Set(ids);
    const page = await api.listTasks("factory");
    setTasks(page.items.filter((t) => wanted.has(t.task_id)).slice(0, 4));
  }

  async function poll(id: string) {
    try {
      const j = await api.getJob(id);
      setJob(j);
      if (j.status === "succeeded") {
        await loadTasks(j.task_ids);
      } else if (j.status !== "failed") {
        timer.current = setTimeout(() => void poll(id), POLL_MS);
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unexpected error while polling the job.");
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(undefined);
    setTasks([]);
    const n = Number(count);
    if (!isValidSeed(seed)) {
      setError("Seed must be 1–40 characters: letters, digits, dash or underscore.");
      return;
    }
    if (!Number.isInteger(n) || n < 1 || n > MAX_COUNT) {
      setError(`Count must be a whole number from 1 to ${MAX_COUNT}.`);
      return;
    }
    try {
      const j = await api.startJob(seed, n, difficulty);
      setJob(j);
      void poll(j.job_id);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not start the job.");
    }
  }

  const running = job?.status === "queued" || job?.status === "running";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Task Factory</h1>
      <Card className="max-w-xl">
        <form onSubmit={onSubmit} className="space-y-3" noValidate>
          <div className="space-y-1">
            <label htmlFor="seed" className="text-sm font-semibold">
              Seed
            </label>
            <input
              id="seed"
              value={seed}
              onChange={(e) => setSeed(e.target.value)}
              className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="count" className="text-sm font-semibold">
              Number of panels (1–{MAX_COUNT})
            </label>
            <input
              id="count"
              inputMode="numeric"
              value={count}
              onChange={(e) => setCount(e.target.value)}
              className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
            />
          </div>
          <div className="space-y-1">
            <label htmlFor="difficulty" className="text-sm font-semibold">
              Difficulty
            </label>
            <select
              id="difficulty"
              value={difficulty}
              onChange={(e) => setDifficulty(e.target.value as Difficulty)}
              className="block min-h-11 w-full rounded-md border border-border bg-background px-3"
            >
              <option value="easy">Easy</option>
              <option value="medium">Medium</option>
              <option value="hard">Hard</option>
            </select>
          </div>
          <Button type="submit" disabled={running}>
            Generate
          </Button>
        </form>
      </Card>
      {error ? (
        <p role="alert" className="font-semibold text-danger" data-testid="factory-error">
          {error}
        </p>
      ) : null}
      {job ? <RunStatus status={job.status} error={job.error} /> : null}
      {job?.reused ? (
        <p className="text-sm">This seed was generated before; showing the existing tasks.</p>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2">
        {tasks.map((t, i) => (
          <Card key={t.task_id} className="space-y-4">
            <PanelViewer set="factory" task={t} label={`Panel ${i + 1}`} />
            <QuestionForm set="factory" task={t} />
          </Card>
        ))}
      </div>
    </div>
  );
}

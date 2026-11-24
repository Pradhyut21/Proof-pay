"use client";

import { useEffect, useState } from "react";
import { ModelAttempts } from "@/components/ModelAttempts";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { PanelViewer } from "@/components/PanelViewer";
import { QuestionForm } from "@/components/QuestionForm";
import { api, ApiError } from "@/lib/api";
import { formatAnswer } from "@/lib/answers";
import type { ModelAttempt, Pair, PublicTask, Reveal } from "@/lib/types";

interface Side {
  task: PublicTask;
  label: string;
  attempts: ModelAttempt[];
  reveal?: Reveal;
}

export default function ArenaPage() {
  const [pairs, setPairs] = useState<Pair[]>([]);
  const [pairId, setPairId] = useState<string>("");
  const [sides, setSides] = useState<Side[]>([]);
  const [offline, setOffline] = useState(false);
  const [message, setMessage] = useState<string>();

  useEffect(() => {
    api
      .listPairs()
      .then((p) => {
        setPairs(p);
        if (p[0]) setPairId(p[0].pair_id);
      })
      .catch(() => setOffline(true));
  }, []);

  useEffect(() => {
    const pair = pairs.find((p) => p.pair_id === pairId);
    if (!pair) return;
    let cancelled = false;
    setSides([]);
    setMessage(undefined);
    Promise.all(
      pair.task_ids.map(async (id, i) => {
        const [task, ma] = await Promise.all([api.getTask(id), api.modelAttempts(id)]);
        return {
          task,
          label: i === 0 ? "Panel A" : "Panel B",
          attempts: ma.attempts,
        } satisfies Side;
      }),
    )
      .then((s) => !cancelled && setSides(s))
      .catch(() => !cancelled && setOffline(true));
    return () => {
      cancelled = true;
    };
  }, [pairId, pairs]);

  async function reveal() {
    try {
      const revealed = await Promise.all(sides.map((s) => api.reveal(s.task.task_id)));
      setSides((prev) => prev.map((s, i) => ({ ...s, reveal: revealed[i] })));
    } catch (e) {
      setMessage(
        e instanceof ApiError && e.kind === "http"
          ? `Reveal refused by the API (${e.status}).`
          : "Could not reveal answers.",
      );
    }
  }

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Model Arena</h1>
      {offline ? (
        <p role="alert" className="font-semibold text-danger" data-testid="arena-offline">
          ⛔ The local API is not reachable, so there is nothing to compare yet.
        </p>
      ) : null}
      {!offline && pairs.length === 0 ? <p>No counterfactual pairs are loaded.</p> : null}
      {pairs.length > 0 ? (
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1">
            <label htmlFor="pair" className="text-sm font-semibold">
              Counterfactual pair
            </label>
            <select
              id="pair"
              value={pairId}
              onChange={(e) => setPairId(e.target.value)}
              className="block min-h-11 rounded-md border border-border bg-background px-3"
            >
              {pairs.map((p) => (
                <option key={p.pair_id} value={p.pair_id}>
                  {p.pair_id}
                </option>
              ))}
            </select>
          </div>
          <Button variant="outline" onClick={() => void reveal()} disabled={sides.length === 0}>
            Reveal answers and evidence
          </Button>
        </div>
      ) : null}
      {message ? (
        <p role="alert" className="text-sm font-semibold text-danger">
          {message}
        </p>
      ) : null}
      <div className="grid gap-6 lg:grid-cols-2" data-testid="variant-compare">
        {sides.map((s) => (
          <Card key={s.task.task_id} className="space-y-4">
            <PanelViewer task={s.task} label={s.label} evidence={s.reveal?.evidence} />
            <QuestionForm task={s.task} />
            {s.reveal ? (
              <p data-testid="revealed-answer" className="font-semibold">
                Correct answer: {formatAnswer(s.reveal.answer)}
              </p>
            ) : null}
            <ModelAttempts
              attempts={s.attempts}
              correctAnswer={s.reveal ? formatAnswer(s.reveal.answer) : undefined}
              offline={offline}
            />
          </Card>
        ))}
      </div>
    </div>
  );
}

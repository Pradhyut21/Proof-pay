"use client";

import { useEffect, useState } from "react";
import { PanelViewer } from "@/components/PanelViewer";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { api, ApiError } from "@/lib/api";
import { formatAnswer } from "@/lib/answers";
import type { DatasetSet, PublicTask } from "@/lib/types";
import type { InspectorEvidence, RasterEvidence } from "./model";

type TaskList =
  | { status: "loading" }
  | { status: "failed"; message: string }
  | { status: "ready"; tasks: PublicTask[] };

type RevealState =
  | { status: "idle" | "pending" }
  | { status: "failed"; message: string }
  | { status: "revealed"; evidence: InspectorEvidence };

interface InspectorProps {
  set: DatasetSet;
  job?: string;
  initialTaskId?: string;
}

function requestMessage(status?: number) {
  if (status === 403) return "The local API refused evidence for this task.";
  if (status === 404) return "That task is unavailable in this dataset.";
  if (status === 410) return "This Factory result expired. Generate another panel in Task Factory.";
  if (status === 503) return "Evidence reveal is unavailable on this local API.";
  return "The local API could not load the requested data. Try again.";
}

export function Inspector({ set, job, initialTaskId }: InspectorProps) {
  const [list, setList] = useState<TaskList>({ status: "loading" });
  const [selectedId, setSelectedId] = useState(initialTaskId ?? "");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    let active = true;
    api
      .listTasks(set, undefined, job)
      .then(({ items }) => {
        if (active) {
          setList({ status: "ready", tasks: items });
          setSelectedId(initialTaskId ?? items[0]?.task_id ?? "");
        }
      })
      .catch((error: unknown) => {
        if (active) {
          setList({
            status: "failed",
            message: requestMessage(error instanceof ApiError ? error.status : undefined),
          });
        }
      });
    return () => {
      active = false;
    };
  }, [set, job, initialTaskId, reload]);

  if (list.status === "loading") return <p role="status">Loading public tasks…</p>;
  if (list.status === "failed") {
    return (
      <div className="space-y-3">
        <p role="alert" className="text-danger">
          {list.message}
        </p>
        <Button
          variant="outline"
          onClick={() => {
            setList({ status: "loading" });
            setReload((value) => value + 1);
          }}
        >
          Retry
        </Button>
      </div>
    );
  }
  if (!list.tasks.length) return <p>No public tasks are available for this dataset.</p>;

  const selected = list.tasks.find((task) => task.task_id === selectedId);
  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <p className="text-sm text-muted-foreground">
          {set === "demo" ? "Local demo tasks" : "Verified Factory result"}
        </p>
        <label htmlFor="inspector-task" className="block text-sm font-semibold">
          Task
        </label>
        <select
          className="block min-h-11 w-full max-w-2xl rounded-md border border-border bg-background px-3"
          id="inspector-task"
          value={selected?.task_id ?? ""}
          onChange={(event) => setSelectedId(event.target.value)}
        >
          {!selected ? <option value="">Choose a task</option> : null}
          {list.tasks.map((task, index) => (
            <option key={task.task_id} value={task.task_id}>
              {task.question} ({index + 1})
            </option>
          ))}
        </select>
      </div>
      {selected ? (
        <TaskEvidence key={selected.task_id} set={set} job={job} task={selected} />
      ) : (
        <p role="alert" className="text-danger">
          The requested task is unavailable in this dataset.
        </p>
      )}
    </div>
  );
}

function TaskEvidence({
  set,
  job,
  task,
}: Pick<InspectorProps, "set" | "job"> & { task: PublicTask }) {
  const [reveal, setReveal] = useState<RevealState>({ status: "idle" });

  async function revealTask() {
    setReveal({ status: "pending" });
    const query = new URLSearchParams({ set, task: task.task_id });
    if (job) query.set("job", job);
    try {
      const response = await fetch("/inspector/evidence?" + query, {
        method: "POST",
        cache: "no-store",
        signal: AbortSignal.timeout(12_000),
      });
      if (!response.ok) {
        setReveal({ status: "failed", message: requestMessage(response.status) });
        return;
      }
      const evidence = (await response.json()) as InspectorEvidence;
      if (evidence.reference?.task_id !== task.task_id) {
        setReveal({
          status: "failed",
          message: "The returned evidence belongs to a different task.",
        });
        return;
      }
      setReveal({ status: "revealed", evidence });
    } catch (error) {
      const timedOut = error instanceof DOMException && error.name === "TimeoutError";
      setReveal({
        status: "failed",
        message: timedOut ? "Evidence reveal timed out. Try again." : requestMessage(),
      });
    }
  }

  const evidence = reveal.status === "revealed" ? reveal.evidence : null;
  return (
    <div className="grid items-start gap-5 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
      <Card>
        <PanelViewer
          set={set}
          job={job}
          task={task}
          label="Panel"
          evidence={evidence?.reference.evidence_regions}
          recoveredEvidence={evidence?.raster?.regions}
        />
        {evidence?.reference.evidence_regions?.length ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Dashed outlines show the task’s generator annotations.
          </p>
        ) : null}
        {evidence?.raster?.regions.length ? (
          <p className="mt-2 text-sm text-muted-foreground">
            Solid outlines show the gauge locations recovered from pixels.
          </p>
        ) : null}
      </Card>
      <div className="min-w-0 space-y-5">
        <Card className="space-y-4">
          <h2 className="text-lg font-semibold">Question</h2>
          <p>{task.question}</p>
          <details className="space-y-2 text-sm">
            <summary className="cursor-pointer font-semibold">Public rules</summary>
            <p>{task.public_rules}</p>
          </details>
          {evidence ? (
            <Button variant="outline" onClick={() => setReveal({ status: "idle" })}>
              Hide evidence
            </Button>
          ) : (
            <Button onClick={() => void revealTask()} disabled={reveal.status === "pending"}>
              {reveal.status === "pending" ? "Revealing evidence…" : "Reveal evidence"}
            </Button>
          )}
          {reveal.status === "failed" ? (
            <p role="alert" className="text-sm text-danger">
              {reveal.message}
            </p>
          ) : null}
        </Card>
        {evidence ? <EvidenceDetails evidence={evidence} /> : null}
      </div>
    </div>
  );
}

function EvidenceDetails({ evidence }: { evidence: InspectorEvidence }) {
  const { reference, raster } = evidence;
  return (
    <Card className="space-y-4" aria-live="polite">
      <div className="space-y-1">
        <h2 className="text-lg font-semibold">Reference answer</h2>
        <p className="text-xl font-semibold" data-testid="inspector-reference-answer">
          {formatAnswer(reference.answer)}
        </p>
        {reference.answer.kind === "numeric" && reference.tolerance_milli !== null ? (
          <p className="text-sm text-muted-foreground">
            Tolerance ±{formatReading(reference.tolerance_milli, reference.answer.unit)}
          </p>
        ) : null}
        <p className="break-all text-sm text-muted-foreground">
          Reference solver {reference.solver_version}
        </p>
      </div>
      <div className="space-y-3 border-t border-border pt-4">
        <h3 className="font-semibold">Raster verification</h3>
        {raster ? (
          <RasterDetails evidence={raster} />
        ) : (
          <p className="text-sm text-muted-foreground">
            No raster trace is available for this task in the local bundle.
          </p>
        )}
      </div>
    </Card>
  );
}

function formatReading(valueMilli: number, unit: string) {
  return formatAnswer({ kind: "numeric", value_milli: valueMilli, unit });
}

function RasterDetails({ evidence }: { evidence: RasterEvidence }) {
  if (evidence.status === "rejected") {
    return (
      <div className="space-y-2 text-sm">
        <p className="font-semibold text-danger">The raster verifier rejected this evidence.</p>
        {evidence.reasonCodes.length ? (
          <ul className="list-inside list-disc">
            {evidence.reasonCodes.map((reason) => (
              <li key={reason}>{reason.replaceAll("_", " ")}</li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }

  const hasGeneratorValues = evidence.readings.some(
    (reading) => reading.generatorValueMilli !== null,
  );
  return (
    <div className="space-y-3 text-sm">
      <p className="font-semibold" data-testid="inspector-raster-status">
        Recovered from image pixels
      </p>
      {evidence.agreement === "agrees" ? (
        <p className="text-success">The raster result agrees with the reference answer.</p>
      ) : null}
      {evidence.agreement === "disagrees" ? (
        <p role="alert" className="text-danger">
          The raster result disagrees with the reference answer.
        </p>
      ) : null}
      {evidence.rustRuleAgrees === null ? (
        <p className="text-muted-foreground">
          No Rust rule comparison was recorded for this bundle.
        </p>
      ) : evidence.rustRuleAgrees ? (
        <p className="text-success">The independent Rust rule result agrees with Python.</p>
      ) : (
        <p role="alert" className="text-danger">
          The independent Rust rule result disagrees with Python.
        </p>
      )}
      <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="Gauge readings">
        <table className="w-full text-left">
          <thead>
            <tr className="border-b border-border">
              <th className="pb-2 pr-2">Gauge</th>
              <th className="pb-2 pr-2">Recovered reading</th>
              {hasGeneratorValues && <th className="pb-2 pr-2">Generator reading</th>}
              <th className="pb-2">Uncertainty</th>
            </tr>
          </thead>
          <tbody>
            {evidence.readings.map((reading) => (
              <tr key={reading.role} className="border-b border-border">
                <th scope="row" className="py-2 pr-2 font-medium">
                  {reading.role}
                </th>
                <td className="py-2 pr-2">{formatReading(reading.valueMilli, reading.unit)}</td>
                {hasGeneratorValues && (
                  <td className="py-2 pr-2">
                    {reading.generatorValueMilli === null
                      ? "—"
                      : formatReading(reading.generatorValueMilli, reading.unit)}
                  </td>
                )}
                <td className="py-2">±{formatReading(reading.uncertaintyMilliKpa, "kPa")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {evidence.deltaMilliKpa !== null ? (
        <p>Recovered pressure difference {formatReading(evidence.deltaMilliKpa, "kPa")}</p>
      ) : null}
      <p className="break-all text-muted-foreground">Raster verifier {evidence.verifierVersion}</p>
    </div>
  );
}

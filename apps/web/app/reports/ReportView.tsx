import Link from "next/link";
import { Card } from "@/components/ui/card";
import {
  reportConditions,
  reportSkills,
  type ReportCondition,
  type ReportModel,
  type ReportSummary,
} from "@/lib/report-data";
import type { ReportPageData } from "@/lib/server/reports";

const conditions: Record<string, string> = {
  C0: "Text only",
  C1: "Full panel",
  C3: "Verified readings",
};
const skills: Record<string, string> = {
  R: "Reading",
  C: "Conversion",
  M: "Multi-instrument",
  X: "Consistency",
};
const failureLabels: Record<string, string> = {
  parse_error: "Parse error",
  invalid_response: "Invalid response",
  provider_error: "Provider error",
  timeout: "Timeout",
  refusal: "Refusal",
};
const numberFormat = new Intl.NumberFormat("en", { maximumFractionDigits: 2 });
const percentFormat = new Intl.NumberFormat("en", {
  style: "percent",
  maximumFractionDigits: 2,
});
const borderCell = "border-b border-border p-2 text-left align-top";
const inputClass = "min-h-11 rounded border border-border bg-background px-3 text-foreground";

function percent(value: number | null): string {
  return value === null ? "—" : percentFormat.format(value);
}

function pp(value: number | null): string {
  return value === null ? "—" : numberFormat.format(value * 100) + " pp";
}

function accuracy(value: number | null, correct: number, total: number): string {
  return percent(value) + " (" + correct + " / " + total + ")";
}

function FailureCounts({ failures }: Pick<ReportSummary, "failures">) {
  const items = Object.entries(failures).filter(([, count]) => count > 0);
  if (!items.length) return <span className="text-muted-foreground">None</span>;
  return (
    <ul className="space-y-0.5">
      {items.map(([key, count]) => (
        <li key={key}>
          {failureLabels[key]} · {count}
        </li>
      ))}
    </ul>
  );
}

function ScoreTable({ caption, rows }: { caption: string; rows: [string, ReportSummary][] }) {
  return (
    <div className="overflow-x-auto" role="region" aria-label={caption} tabIndex={0}>
      <table className="min-w-[43rem] w-full text-sm">
        <caption className="text-left font-semibold pb-2">{caption}</caption>
        <thead className="bg-muted">
          <tr>
            {[
              "Cohort",
              "Attempted",
              "Completed",
              "Valid",
              "Correct",
              "Valid only",
              "All attempts",
              "Failures",
            ].map((label) => (
              <th key={label} scope="col" className={borderCell}>
                {label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="tabular-nums">
          {rows.map(([label, row]) => (
            <tr key={label}>
              <th scope="row" className={borderCell}>
                {label}
              </th>
              <td className={borderCell}>{row.attempted}</td>
              <td className={borderCell}>{row.completed}</td>
              <td className={borderCell}>{row.valid}</td>
              <td className={borderCell}>{row.correct}</td>
              <td className={borderCell}>
                {accuracy(row.valid_only_accuracy, row.correct, row.denominators.valid_only)}
              </td>
              <td className={borderCell}>
                {accuracy(row.all_attempt_accuracy, row.correct, row.denominators.all_attempt)}
              </td>
              <td className={borderCell}>
                <FailureCounts failures={row.failures} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ConditionDetails({
  id,
  condition,
  skill,
}: {
  id: string;
  condition: ReportCondition;
  skill?: string;
}) {
  const { n_groups, lo95, hi95 } = condition.ci_all_attempt_accuracy;
  const bySkill = Object.entries(condition.by_skill).filter(([key]) => !skill || key === skill);
  const byDifficulty = Object.entries(condition.by_difficulty);
  const pairs = Object.entries(condition.pairs);
  return (
    <details className="space-y-4 rounded border border-border p-3" open={id === "C1"}>
      <summary className="cursor-pointer font-semibold">
        {id} · {conditions[id]} details
      </summary>
      <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-sm">
        <div>
          <dt>Groups in interval</dt>
          <dd className="font-semibold">{n_groups}</dd>
        </div>
        <div>
          <dt>All-attempt 95% interval</dt>
          <dd className="font-semibold">
            {lo95 === null || hi95 === null ? "—" : percent(lo95) + " to " + percent(hi95)}
          </dd>
        </div>
        <div>
          <dt>Worst group accuracy</dt>
          <dd className="font-semibold">{percent(condition.worst_group_accuracy)}</dd>
        </div>
        <div>
          <dt>Groups with all variants correct</dt>
          <dd className="font-semibold">
            {accuracy(
              condition.all_variants_correct_rate,
              condition.all_variants_correct_groups,
              condition.groups_with_2plus_tasks,
            )}
          </dd>
        </div>
      </dl>
      {bySkill.length ? (
        <ScoreTable
          caption={id + " by skill"}
          rows={bySkill.map(([key, row]) => [skills[key] ?? key, row])}
        />
      ) : (
        <p className="text-sm text-muted-foreground">No results for this skill.</p>
      )}
      {byDifficulty.length > 0 && (
        <ScoreTable caption={id + " by difficulty"} rows={byDifficulty} />
      )}
      {pairs.length > 0 && (
        <div
          className="overflow-x-auto"
          role="region"
          aria-label={id + " counterfactual pairs"}
          tabIndex={0}
        >
          <table className="min-w-[33rem] w-full text-sm">
            <caption className="text-left font-semibold pb-2">{id} counterfactual pairs</caption>
            <thead className="bg-muted">
              <tr>
                {["Type", "Pairs", "Pair accuracy", "Directional sensitivity", "Invariance"].map(
                  (label) => (
                    <th key={label} scope="col" className={borderCell}>
                      {label}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {pairs.map(([kind, row]) => (
                <tr key={kind}>
                  <th scope="row" className={borderCell + " capitalize"}>
                    {kind}
                  </th>
                  <td className={borderCell}>{row.pairs}</td>
                  <td className={borderCell}>
                    {accuracy(row.pair_correctness, row.both_correct, row.pairs)}
                  </td>
                  <td className={borderCell}>
                    {percent(row.directional_sensitivity)} (n={row.denominators.sensitivity})
                  </td>
                  <td className={borderCell}>
                    {percent(row.invariance)} (n={row.denominators.invariance})
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

function ModelReport({
  modelId,
  model,
  condition,
  skill,
}: {
  modelId: string;
  model: ReportModel;
  condition?: string;
  skill?: string;
}) {
  const selected = Object.entries(model.conditions).filter(
    ([id]) => !condition || condition === id,
  );
  const gain = model.grounding_gain_C1_minus_C0;
  const missing = Object.entries(model.tasks_missing_a_condition).filter(([, value]) => value > 0);
  return (
    <Card className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="break-all text-xl font-semibold">{modelId}</h2>
          <p className="text-sm text-muted-foreground">{model.matched_task_count} matched tasks</p>
        </div>
        {gain && (
          <div>
            <p className="font-semibold">Grounding gain · {pp(gain.gain)}</p>
            <p className="text-sm text-muted-foreground">
              C1 − C0 over {gain.matched_tasks} matched tasks and {gain.n_groups} groups
            </p>
          </div>
        )}
      </div>
      {missing.length > 0 && (
        <p className="text-sm">
          Missing condition rows · {missing.map(([id, n]) => id + " " + n).join(", ")}
        </p>
      )}
      {selected.length > 0 ? (
        <>
          <ScoreTable
            caption="Condition scores"
            rows={selected.map(([id, row]) => [id + " · " + conditions[id], row])}
          />
          {selected.map(([id, row]) => (
            <ConditionDetails key={id} id={id} condition={row} skill={skill} />
          ))}
        </>
      ) : (
        <p className="text-sm text-muted-foreground">No attempts for this condition.</p>
      )}
    </Card>
  );
}

const unavailable = {
  empty: {
    title: "No run reports yet",
    message: "Generate an offline report with run.ps1 reproduce or run.sh reproduce.",
  },
  offline: {
    title: "Reports are offline",
    message:
      "The configured report folder is unavailable. Check the local server configuration and reload.",
  },
  invalid: {
    title: "Report could not be read",
    message:
      "The local report is incomplete or invalid. Regenerate it with the metrics command and reload.",
  },
  missing: {
    title: "Report not found",
    message: "This run is not present in the configured report folder.",
  },
};

export function ReportView({
  data,
  condition,
  skill,
}: {
  data: ReportPageData;
  condition?: string;
  skill?: string;
}) {
  const selectedCondition = reportConditions.find((value) => value === condition);
  const selectedSkill = reportSkills.find((value) => value === skill);
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Run Reports</h1>
      {data.status !== "ready" ? (
        <Card className="space-y-2">
          <h2 className="text-lg font-semibold">{unavailable[data.status].title}</h2>
          <p role={data.status === "empty" ? "status" : "alert"}>
            {unavailable[data.status].message}
          </p>
          {data.status === "missing" && (
            <Link className="underline" href="/reports">
              View available reports
            </Link>
          )}
        </Card>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-3">
            <strong className="rounded border border-border bg-muted px-3 py-1 text-sm">
              {data.report.status === "demo"
                ? "DEMO ONLY"
                : data.report.status === "measured"
                  ? "MEASURED"
                  : "DEVELOPMENT"}
            </strong>
            {data.report.status === "demo" && (
              <p className="text-sm text-muted-foreground">Offline fixture outputs.</p>
            )}
            <a
              className="ml-auto flex min-h-11 items-center px-2 underline"
              href={"/reports/export?run=" + data.selected}
              download
            >
              Download report
            </a>
            {data.report.provenance && (
              <a
                className="flex min-h-11 items-center px-2 underline"
                href={"/reports/export?kind=manifest&run=" + data.selected}
                download
              >
                Download run manifest
              </a>
            )}
          </div>
          <form
            action="/reports"
            method="get"
            className="flex flex-wrap items-end gap-3 rounded border border-border p-3"
          >
            <label className="grid gap-1 text-sm font-medium">
              Run
              <select name="run" className={inputClass} defaultValue={data.selected}>
                {data.sources.map(({ id, label }) => (
                  <option key={id} value={id}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Condition
              <select
                name="condition"
                className={inputClass}
                defaultValue={selectedCondition ?? ""}
              >
                <option value="">All conditions</option>
                {reportConditions.map((id) => (
                  <option key={id} value={id}>
                    {id} · {conditions[id]}
                  </option>
                ))}
              </select>
            </label>
            <label className="grid gap-1 text-sm font-medium">
              Skill
              <select name="skill" className={inputClass} defaultValue={selectedSkill ?? ""}>
                <option value="">All skills</option>
                {reportSkills.map((id) => (
                  <option key={id} value={id}>
                    {skills[id]}
                  </option>
                ))}
              </select>
            </label>
            <button
              className="min-h-11 rounded bg-primary px-4 text-sm font-semibold text-primary-foreground"
              type="submit"
            >
              Apply filters
            </button>
          </form>
          {data.report.provenance && (
            <Card className="space-y-2">
              <h2 className="font-semibold">Measured provenance</h2>
              <p className="break-all text-sm">
                Dataset manifest SHA-256{" "}
                <code>{data.report.provenance.dataset_manifest_sha256}</code>
              </p>
              {data.report.provenance.x_scope && data.report.provenance.x_task_count !== null && (
                <p className="text-sm">
                  X scope {data.report.provenance.x_scope} · {data.report.provenance.x_task_count}{" "}
                  consistency tasks
                </p>
              )}
              <ul className="space-y-1 text-sm">
                {data.report.provenance.models.map((model) => (
                  <li key={model.model_id} className="break-all">
                    {model.provider} / {model.model_id} at {model.model_revision}
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {Object.keys(data.report.models).length ? (
            Object.entries(data.report.models).map(([modelId, model]) => (
              <ModelReport
                key={modelId}
                modelId={modelId}
                model={model}
                condition={selectedCondition}
                skill={selectedSkill}
              />
            ))
          ) : (
            <Card>
              <p role="status">This report contains no model attempts.</p>
            </Card>
          )}
        </>
      )}
    </div>
  );
}

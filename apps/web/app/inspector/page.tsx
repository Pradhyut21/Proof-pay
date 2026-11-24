import Link from "next/link";
import { ID_RE } from "@/lib/server/config";
import { Inspector } from "./inspector";

type Search = { set?: string | string[]; job?: string | string[]; task?: string | string[] };

export default async function InspectorPage({ searchParams }: { searchParams: Promise<Search> }) {
  const params = await searchParams;
  const set = params.set ?? "demo";
  const job = typeof params.job === "string" && ID_RE.test(params.job) ? params.job : undefined;
  const taskId =
    typeof params.task === "string" && ID_RE.test(params.task) ? params.task : undefined;
  const validTask = params.task === undefined || taskId !== undefined;

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">Evidence Inspector</h1>
      {validTask && (set === "demo" || (set === "factory" && job)) ? (
        <Inspector
          key={JSON.stringify([set, job, taskId])}
          set={set}
          job={set === "factory" ? job : undefined}
          initialTaskId={taskId}
        />
      ) : (
        <div role="alert" className="space-y-2">
          <p>Choose an available demo task or an active Factory result to inspect its evidence.</p>
          <Link href="/inspector" className="font-semibold text-primary underline">
            Open demo tasks
          </Link>
        </div>
      )}
    </div>
  );
}

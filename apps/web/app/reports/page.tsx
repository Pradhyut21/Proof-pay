import { ReportView } from "./ReportView";
import { loadReportPage } from "@/lib/server/reports";

export const dynamic = "force-dynamic";

type Search = { run?: string | string[]; condition?: string | string[]; skill?: string | string[] };

export default async function ReportsPage({ searchParams }: { searchParams: Promise<Search> }) {
  const search = await searchParams;
  const one = (value: string | string[] | undefined) =>
    typeof value === "string" ? value : undefined;
  const data = await loadReportPage(one(search.run));
  return <ReportView data={data} condition={one(search.condition)} skill={one(search.skill)} />;
}

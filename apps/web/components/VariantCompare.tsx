"use client";

import { Card } from "@/components/ui/card";
import type { DatasetSet, EvidenceRegion, PublicTask } from "@/lib/types";
import { PanelViewer } from "./PanelViewer";
import { QuestionForm } from "./QuestionForm";

interface Side {
  task: PublicTask;
  label: string;
  evidence?: EvidenceRegion[] | null;
}

/** Two panels side by side (stacked on small screens), each with its own question form. */
export function VariantCompare({ set, left, right }: { set: DatasetSet; left: Side; right: Side }) {
  return (
    <div className="grid gap-6 lg:grid-cols-2" data-testid="variant-compare">
      {[left, right].map((s) => (
        <Card key={s.task.task_id} className="space-y-4">
          <PanelViewer set={set} task={s.task} label={s.label} evidence={s.evidence} />
          <QuestionForm set={set} task={s.task} />
        </Card>
      ))}
    </div>
  );
}

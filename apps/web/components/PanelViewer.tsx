"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { imageUrl } from "@/lib/api";
import {
  IMAGE_HEIGHT,
  IMAGE_WIDTH,
  type DatasetSet,
  type EvidenceRegion,
  type PublicTask,
} from "@/lib/types";

const ZOOMS = [1, 1.5, 2, 3];

interface Props {
  set: DatasetSet;
  task: PublicTask;
  label: string;
  job?: string;
  evidence?: EvidenceRegion[] | null;
  recoveredEvidence?: EvidenceRegion[] | null;
}

/** Panel image with zoom. Evidence boxes are drawn only when the backend has revealed them. */
export function PanelViewer({ set, task, label, evidence, recoveredEvidence, job }: Props) {
  const [zoom, setZoom] = useState(1);
  const idx = ZOOMS.indexOf(zoom);
  return (
    <figure className="space-y-2" data-testid={`panel-${label}`}>
      <figcaption className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-semibold">{label}</span>
        <span className="flex items-center gap-1" role="group" aria-label={`Zoom for ${label}`}>
          <Button
            size="sm"
            variant="outline"
            aria-label={`Zoom out ${label}`}
            disabled={idx <= 0}
            onClick={() => setZoom(ZOOMS[Math.max(0, idx - 1)] ?? 1)}
          >
            −
          </Button>
          <span className="min-w-12 text-center text-sm" aria-live="polite">
            {Math.round(zoom * 100)}%
          </span>
          <Button
            size="sm"
            variant="outline"
            aria-label={`Zoom in ${label}`}
            disabled={idx >= ZOOMS.length - 1}
            onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, idx + 1)] ?? 1)}
          >
            +
          </Button>
        </span>
      </figcaption>
      <div
        className="max-h-[32rem] overflow-auto rounded-md border border-border bg-muted"
        tabIndex={0}
        role="region"
        aria-label={`${label} image, scrollable`}
      >
        <div className="relative" style={{ width: `${zoom * 100}%` }}>
          {/* eslint-disable-next-line @next/next/no-img-element -- local API image, intrinsic size known */}
          <img
            src={imageUrl(set, task.task_id, job)}
            alt={`${label}: synthetic water-pump control panel with two dials and RUN and ALARM lamps`}
            width={IMAGE_WIDTH}
            height={IMAGE_HEIGHT}
            className="block h-auto w-full"
          />
          {(
            [
              ["evidence-box", "border-dashed border-primary", evidence],
              ["raster-evidence-box", "border-success", recoveredEvidence],
            ] as const
          ).flatMap(([testId, style, regions]) =>
            (regions ?? []).map((e) => (
              <div
                key={testId + e.instrument_id}
                data-testid={testId}
                title={e.instrument_id}
                className={"pointer-events-none absolute border-2 " + style}
                style={{
                  left: `${(e.x / IMAGE_WIDTH) * 100}%`,
                  top: `${(e.y / IMAGE_HEIGHT) * 100}%`,
                  width: `${(e.width / IMAGE_WIDTH) * 100}%`,
                  height: `${(e.height / IMAGE_HEIGHT) * 100}%`,
                }}
              />
            )),
          )}
        </div>
      </div>
    </figure>
  );
}

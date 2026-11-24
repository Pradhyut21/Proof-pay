"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";
import type { Capabilities, Health } from "@/lib/types";

export default function HomePage() {
  const [health, setHealth] = useState<Health>();
  const [caps, setCaps] = useState<Capabilities>();
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.health(), api.capabilities()])
      .then(([h, c]) => {
        if (!cancelled) {
          setHealth(h);
          setCaps(c);
        }
      })
      .catch(() => !cancelled && setOffline(true));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold">PanelProof</h1>
      <p className="max-w-3xl">
        Read synthetic water-pump control panels, apply the public rules, and compare your answers
        with offline demo model outputs. Generate new tasks in the Task Factory, or open the Model
        Arena to compare counterfactual pairs.
      </p>
      <Card aria-labelledby="status-h" className="space-y-2">
        <h2 id="status-h" className="text-lg font-semibold">
          Local API status
        </h2>
        {offline ? (
          <p role="alert" className="font-semibold text-danger" data-testid="api-offline">
            ⛔ The local API is not reachable. Start it with <code>cargo run -p pp-api</code> and
            reload.
          </p>
        ) : health && caps ? (
          <ul className="list-inside list-disc" data-testid="api-ready">
            <li>
              ✓ {health.service} v{health.version}, {health.tasks_loaded} tasks loaded
            </li>
            <li>
              Offline demo outputs: {caps.offline_demo ? "available (DEMO ONLY)" : "not available"}
            </li>
            <li>Live models: {caps.live_models ? "enabled" : "disabled in this build"}</li>
          </ul>
        ) : (
          <p>Checking…</p>
        )}
      </Card>
      <div className="flex flex-wrap gap-3">
        <Link
          href="/factory"
          className="inline-flex min-h-11 items-center rounded-md bg-primary px-4 font-semibold text-primary-foreground"
        >
          Open Task Factory
        </Link>
        <Link
          href="/arena"
          className="inline-flex min-h-11 items-center rounded-md border border-border px-4 font-semibold hover:bg-muted"
        >
          Open Model Arena
        </Link>
      </div>
    </div>
  );
}

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { api } from "@/lib/api";

export default function HomePage() {
  const [ready, setReady] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    let cancelled = false;
    api
      .health("demo")
      .then(() => !cancelled && setReady(true))
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
            ⛔ The local API is not reachable. Start it with{" "}
            <code>cargo run -p panelproof-api -- data/demo data/demo.sqlite</code> and reload.
          </p>
        ) : ready ? (
          <ul className="list-inside list-disc" data-testid="api-ready">
            <li>✓ Local API healthy (demo dataset)</li>
            <li>Model outputs shown here are offline simulations labelled DEMO ONLY</li>
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

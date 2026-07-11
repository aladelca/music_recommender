import { useMutation, useQuery } from "@tanstack/react-query";
import { CircleAlert, DatabaseZap, Pencil, RadioTower } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { useState } from "react";

import { api, ApiError } from "../api/client";
import { DiscoveryForm, type DiscoveryControls } from "../components/DiscoveryForm";

type Props = { pollIntervalMs?: number };

export function DiscoverPage({ pollIntervalMs = 1_500 }: Props) {
  const navigate = useNavigate();
  const [phase, setPhase] = useState<string | null>(null);
  const [degraded, setDegraded] = useState(false);
  const seedsQuery = useQuery({ queryKey: ["seeds"], queryFn: api.seeds });
  const mutation = useMutation({
    mutationFn: async (controls: DiscoveryControls) => {
      setPhase("Gathering source evidence");
      const started = await api.startDiscovery();
      const terminal = await waitForDiscovery(started.id, pollIntervalMs, setPhase);
      if (terminal.status === "failed") throw new Error(discoveryFailureMessage(terminal.error_code));
      setDegraded(terminal.status === "degraded");
      setPhase("Ranking discoveries");
      return api.generateRecommendations(controls);
    },
    onSuccess: (session) => navigate(`/sessions/${session.id}`),
    onError: () => setPhase(null),
  });

  return (
    <div className="page discover-page">
      <header className="page-header discover-header">
        <div>
          <p className="eyebrow">Explicit discovery</p>
          <h1>Find the next ten</h1>
          <p>Recommendations start from your selected MusicBrainz seeds.</p>
        </div>
        <Link className="secondary-button" to="/seeds"><Pencil size={16} aria-hidden="true" /> Edit seeds</Link>
      </header>

      <div className="seed-strip" aria-label="Active seeds">
        <span className="seed-strip-label"><DatabaseZap size={16} aria-hidden="true" /> Seeds</span>
        {seedsQuery.data?.seeds.map((seed) => <span className="seed-chip" key={seed.id}>{seed.display_name}</span>)}
      </div>

      <section className="composer-band" aria-labelledby="composer-heading">
        <div className="composer-copy"><h2 id="composer-heading">Discovery request</h2><span>{seedsQuery.data?.seeds.length ?? 0} active seeds</span></div>
        <DiscoveryForm seeds={seedsQuery.data?.seeds ?? []} pending={mutation.isPending || seedsQuery.isLoading} onSubmit={(controls) => mutation.mutate(controls)} />
      </section>

      {mutation.isPending && phase ? (
        <div className="process-status" role="status"><RadioTower className="pulse" size={21} aria-hidden="true" /><span><strong>{phase}</strong><small>MusicBrainz and ListenBrainz source adapters</small></span></div>
      ) : null}
      {degraded ? <div className="inline-alert"><CircleAlert size={18} aria-hidden="true" /><span>Source coverage was limited. The result will mark missing evidence.</span></div> : null}
      {mutation.isError ? <div className="inline-alert" role="alert"><CircleAlert size={18} aria-hidden="true" /><span>{requestErrorMessage(mutation.error)}</span></div> : null}
      {seedsQuery.isError ? <div className="inline-alert" role="alert"><CircleAlert size={18} aria-hidden="true" /><span>{requestErrorMessage(seedsQuery.error)}</span></div> : null}
    </div>
  );
}

async function waitForDiscovery(jobId: string, intervalMs: number, onPhase: (phase: string) => void) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    await delay(intervalMs);
    const job = await api.discoveryJob(jobId);
    if (["ready", "degraded", "failed"].includes(job.status)) return job;
    onPhase(job.status === "running" ? "Building candidate links" : "Waiting for source capacity");
  }
  throw new Error("Source discovery timed out. Try again.");
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

function discoveryFailureMessage(code: string | null): string {
  if (code === "source_rate_limited") return "External sources are busy. Try again shortly.";
  return "Automated discovery could not complete.";
}

function requestErrorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Discovery is unavailable right now.";
}

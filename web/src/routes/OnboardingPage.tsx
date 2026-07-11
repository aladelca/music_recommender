import { useMutation } from "@tanstack/react-query";
import { Check, LoaderCircle, Plus, Search, SlidersHorizontal, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { MusicSearchResult } from "../api/schemas";
import { useAuth } from "../auth/useAuth";

export function OnboardingPage({ compact = false }: { compact?: boolean }) {
  const { refresh } = useAuth();
  const navigate = useNavigate();
  const [entityType, setEntityType] = useState<"artist" | "recording">("artist");
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<MusicSearchResult[]>([]);
  const [selected, setSelected] = useState<MusicSearchResult[]>([]);
  const [error, setError] = useState<string | null>(null);

  const searchMutation = useMutation({
    mutationFn: () => api.searchMusic(query.trim(), entityType),
    onSuccess: (response) => {
      setResults(response.results);
      setError(response.results.length === 0 ? "No MusicBrainz matches found." : null);
    },
    onError: (reason) => setError(messageFor(reason, "MusicBrainz search is unavailable.")),
  });
  const saveMutation = useMutation({
    mutationFn: () => api.replaceSeeds(selected.map(({ entity_type, mbid }) => ({ entity_type, mbid }))),
    onSuccess: async () => {
      await refresh();
      navigate("/discover", { replace: true });
    },
    onError: (reason) => setError(messageFor(reason, "Seeds could not be saved.")),
  });

  function submitSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (query.trim().length < 2) {
      setError("Enter at least two characters.");
      return;
    }
    setError(null);
    searchMutation.mutate();
  }

  function add(result: MusicSearchResult) {
    if (selected.some((item) => item.mbid === result.mbid)) return;
    if (selected.length >= 5) {
      setError("You can select up to five seeds.");
      return;
    }
    setSelected((items) => [...items, result]);
    setError(null);
  }

  return (
    <main className={compact ? "page seed-page compact" : "seed-page"}>
      {!compact ? <div className="onboarding-brand"><SlidersHorizontal size={19} aria-hidden="true" /> Outside the Loop</div> : null}
      <div className="seed-layout">
        <header className="seed-header">
          <p className="eyebrow">{compact ? "Music seeds" : "Step 1 of 1"}</p>
          <h1>{compact ? "Edit your starting points" : "Choose your starting points"}</h1>
          <p>Pick one to five artists or recordings from MusicBrainz.</p>
        </header>
        <section className="seed-search-panel" aria-label="Seed search">
          <div className="segmented-control type-control">
            {(["artist", "recording"] as const).map((type) => (
              <label key={type}>
                <input type="radio" name="seed-type" value={type} checked={entityType === type} onChange={() => setEntityType(type)} />
                <span>{type === "artist" ? "Artists" : "Recordings"}</span>
              </label>
            ))}
          </div>
          <form className="seed-search-form" onSubmit={submitSearch}>
            <label className="sr-only" htmlFor="seed-query">Search MusicBrainz</label>
            <div className="prompt-control">
              <Search size={18} aria-hidden="true" />
              <input id="seed-query" aria-label="Search MusicBrainz" value={query} maxLength={100} onChange={(event) => setQuery(event.target.value)} placeholder={entityType === "artist" ? "Artist name" : "Recording title"} />
            </div>
            <button className="secondary-button" type="submit" disabled={searchMutation.isPending}>
              {searchMutation.isPending ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Search size={17} aria-hidden="true" />} Search
            </button>
          </form>
          {results.length > 0 ? (
            <ul className="search-results" aria-label="MusicBrainz results">
              {results.map((result) => {
                const chosen = selected.some((item) => item.mbid === result.mbid);
                return (
                  <li key={result.mbid}>
                    <span><strong>{result.name}</strong><small>{resultLabel(result)}</small></span>
                    <button className="icon-button" type="button" disabled={chosen} onClick={() => add(result)} title={chosen ? `${result.name} added` : `Add ${result.name}`}>
                      {chosen ? <Check size={17} aria-hidden="true" /> : <Plus size={17} aria-hidden="true" />}
                      <span className="sr-only">{chosen ? `${result.name} added` : `Add ${result.name}`}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : null}
          {error ? <p className="form-error" role="alert">{error}</p> : null}
        </section>
        <section className="selected-seeds" aria-labelledby="selected-seeds-heading">
          <div className="section-heading"><h2 id="selected-seeds-heading">Selected</h2><span>{selected.length}/5</span></div>
          {selected.length > 0 ? (
            <ol>
              {selected.map((item, index) => (
                <li key={item.mbid}><span className="seed-number">{index + 1}</span><span><strong>{item.name}</strong><small>{item.entity_type}</small></span><button className="icon-button" type="button" onClick={() => setSelected((items) => items.filter((candidate) => candidate.mbid !== item.mbid))} title={`Remove ${item.name}`}><X size={17} aria-hidden="true" /><span className="sr-only">Remove {item.name}</span></button></li>
              ))}
            </ol>
          ) : <div className="empty-state"><strong>No seeds selected</strong><span>MusicBrainz results appear here after confirmation.</span></div>}
          <button className="primary-button" type="button" disabled={selected.length === 0 || saveMutation.isPending} onClick={() => saveMutation.mutate()}>
            {saveMutation.isPending ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Check size={18} aria-hidden="true" />} Save seeds
          </button>
        </section>
      </div>
    </main>
  );
}

function resultLabel(result: MusicSearchResult): string {
  if (result.entity_type === "artist") return "Artist · MusicBrainz";
  const credit = result.artist_credit.map((entry) => typeof entry.name === "string" ? entry.name : "").filter(Boolean).join(", ");
  return `${credit || "Recording"} · MusicBrainz`;
}

function messageFor(error: unknown, fallback: string): string {
  return error instanceof ApiError ? error.message : fallback;
}

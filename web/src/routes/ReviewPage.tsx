import { useMutation, useQuery } from "@tanstack/react-query";
import { ArrowLeft, LoaderCircle } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { PlaylistExport, RecommendationItem } from "../api/schemas";
import { PlaylistExportForm, type PlaylistExportValues } from "../components/PlaylistExportForm";
import { TrackReviewList } from "../components/TrackReviewList";

export function ReviewPage() {
  const { sessionId = "" } = useParams();
  const query = useQuery({
    queryKey: ["recommendations", sessionId],
    queryFn: () => api.recommendation(sessionId),
    enabled: Boolean(sessionId),
  });
  const [orderedItems, setOrderedItems] = useState<RecommendationItem[] | null>(null);
  const [result, setResult] = useState<PlaylistExport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const initialItems = useMemo(
    () => query.data?.recommendations.filter((item) => item.selected).sort(compareReviewOrder) ?? [],
    [query.data],
  );
  const items = orderedItems ?? initialItems;
  const defaultName = useMemo(
    () => clipPlaylistName(query.data?.review.playlist_name ?? `Outside the Loop - ${query.data?.prompt ?? "Discoveries"}`),
    [query.data],
  );

  const exportMutation = useMutation({
    mutationFn: async (values: PlaylistExportValues) => {
      const recordingMbids = items.map((item) => item.recording_mbid);
      await api.reviewRecommendation(sessionId, {
        recording_mbids: recordingMbids,
        playlist_name: values.name,
        public: values.public,
      });
      const request = {
        name: values.name,
        description: values.description,
        public: values.public,
        recording_mbids: recordingMbids,
      };
      return api.exportPlaylist(sessionId, request, idempotencyKey(sessionId, request));
    },
    onMutate: () => {
      setError(null);
      setResult(null);
    },
    onSuccess: setResult,
    onError: (reason) => setError(errorMessage(reason)),
  });

  if (query.isLoading) return <PageLoading label="Loading review" />;
  if (query.isError || !query.data) return <PageError message={errorMessage(query.error)} />;

  return (
    <div className="page review-page">
      <header className="page-header">
        <Link className="back-link" to={`/sessions/${sessionId}`}><ArrowLeft size={17} aria-hidden="true" /> Results</Link>
        <div className="eyebrow">Playlist review</div>
        <h1>Choose the final order</h1>
        <p>{items.length} of {query.data.recommendations.length} tracks selected</p>
      </header>
      <div className="review-layout">
        <section className="review-list-section" aria-labelledby="track-order-heading">
          <h2 id="track-order-heading">Track order</h2>
          {items.length > 0 ? <TrackReviewList items={items} onChange={setOrderedItems} /> : <div className="empty-state"><strong>No tracks selected</strong><span>Return to results and start again.</span></div>}
        </section>
        <aside className="export-panel" aria-labelledby="playlist-details-heading">
          <h2 id="playlist-details-heading">Playlist details</h2>
          <PlaylistExportForm
            key={defaultName}
            initialName={defaultName}
            initialPublic={query.data.review.public ?? false}
            trackCount={items.length}
            pending={exportMutation.isPending}
            error={error}
            result={result}
            onSubmit={(values) => exportMutation.mutate(values)}
          />
        </aside>
      </div>
    </div>
  );
}

function compareReviewOrder(left: RecommendationItem, right: RecommendationItem): number {
  return (left.reviewed_order ?? left.original_rank) - (right.reviewed_order ?? right.original_rank);
}

function clipPlaylistName(name: string): string {
  return name.slice(0, 100).trim();
}

function idempotencyKey(sessionId: string, payload: object): string {
  const fingerprint = JSON.stringify(payload);
  const storageKey = `outside-loop:export:v1:${sessionId}`;
  const stored = sessionStorage.getItem(storageKey);
  if (stored) {
    const parsed = JSON.parse(stored) as { fingerprint: string; key: string };
    if (parsed.fingerprint === fingerprint) return parsed.key;
  }
  const key = crypto.randomUUID();
  sessionStorage.setItem(storageKey, JSON.stringify({ fingerprint, key }));
  return key;
}

function errorMessage(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof Error) return error.message;
  return "Playlist export is unavailable right now.";
}

function PageLoading({ label }: { label: string }) {
  return <div className="page-state"><LoaderCircle className="spin" aria-hidden="true" /><span>{label}</span></div>;
}

function PageError({ message }: { message: string }) {
  return <div className="page-state error-state" role="alert"><strong>Review unavailable</strong><span>{message}</span></div>;
}

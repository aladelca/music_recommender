import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CircleAlert, ListChecks, LoaderCircle, Sparkles } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "../api/client";
import type { RecommendationItem } from "../api/schemas";
import { RecommendationList } from "../components/RecommendationList";
import { SessionEvaluation } from "../components/SessionEvaluation";

type FeedbackType = "like" | "dislike" | "hide_artist" | "save";

export function SessionPage() {
  const { sessionId = "" } = useParams();
  const queryClient = useQueryClient();
  const [activeTrackId, setActiveTrackId] = useState<string | null>(null);
  const [feedbackTrackId, setFeedbackTrackId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const query = useQuery({ queryKey: ["recommendations", sessionId], queryFn: () => api.recommendation(sessionId), enabled: Boolean(sessionId) });
  const feedbackMutation = useMutation({
    mutationFn: ({ item, eventType }: { item: RecommendationItem; eventType: FeedbackType }) => {
      setFeedbackTrackId(item.recording_mbid);
      return api.feedback(sessionId, { recording_mbid: item.recording_mbid, event_type: eventType }, feedbackKey(sessionId, item.recording_mbid, eventType));
    },
    onSuccess: async (_result, variables) => {
      setNotice(feedbackMessage(variables.eventType));
      if (variables.eventType === "hide_artist") await queryClient.invalidateQueries({ queryKey: ["preferences"] });
    },
    onError: (reason) => setNotice(reason instanceof ApiError ? reason.message : "Feedback could not be saved."),
    onSettled: () => setFeedbackTrackId(null),
  });

  if (query.isLoading) return <div className="page-state"><LoaderCircle className="spin" aria-hidden="true" /><span>Loading recommendations</span></div>;
  if (query.isError || !query.data) return <div className="page-state error-state" role="alert"><CircleAlert aria-hidden="true" /><strong>Session unavailable</strong><span>{query.error instanceof ApiError ? query.error.message : "This recommendation session could not be loaded."}</span></div>;

  const session = query.data;
  const coverage = coveragePercent(session.source_coverage);
  return (
    <div className="page session-page">
      <header className="page-header session-header">
        <div>
          <Link className="back-link" to="/discover"><ArrowLeft size={17} aria-hidden="true" /> Discover</Link>
          <div className="session-title-line"><span className={`status-badge ${session.status}`}>{statusLabel(session.status)}</span><span>{session.ranking_version}</span></div>
          <h1>{session.prompt}</h1>
          <p>{session.recommendations.length} mapped tracks · {coverage} evidence coverage</p>
        </div>
        <Link className="primary-button" to={`/sessions/${session.id}/review`}><ListChecks size={18} aria-hidden="true" /> Review playlist</Link>
      </header>

      {session.status === "degraded" || session.status === "insufficient" ? <div className="inline-alert"><CircleAlert size={18} aria-hidden="true" /><span>Source or Spotify mapping coverage was limited. Missing evidence is marked on each track.</span></div> : null}
      {notice ? <div className="feedback-notice" role="status"><Sparkles size={16} aria-hidden="true" />{notice}</div> : null}

      <RecommendationList
        items={session.recommendations}
        activeTrackId={activeTrackId}
        feedbackTrackId={feedbackTrackId}
        onPreview={(trackId) => setActiveTrackId((current) => current === trackId ? null : trackId)}
        onFeedback={(item, eventType) => feedbackMutation.mutate({ item, eventType })}
      />
      <SessionEvaluation sessionId={session.id} />
    </div>
  );
}

function coveragePercent(coverage: Record<string, unknown>): string {
  const nested = typeof coverage.coverage === "object" && coverage.coverage ? coverage.coverage as Record<string, unknown> : coverage;
  const value = nested.evidence_coverage;
  return typeof value === "number" ? `${Math.round(value * 100)}%` : "unreported";
}

function statusLabel(status: string): string {
  return status === "insufficient" ? "Limited" : status.slice(0, 1).toUpperCase() + status.slice(1);
}

function feedbackMessage(eventType: FeedbackType): string {
  if (eventType === "hide_artist") return "Artist blocked for future sessions.";
  if (eventType === "dislike") return "Track excluded from future sessions.";
  if (eventType === "like") return "Like recorded for this beta session.";
  return "Save recorded for this beta session.";
}

function feedbackKey(sessionId: string, recordingMbid: string, eventType: string): string {
  const storageKey = `outside-loop:feedback:v1:${sessionId}:${recordingMbid}:${eventType}`;
  const existing = sessionStorage.getItem(storageKey);
  if (existing) return existing;
  const created = crypto.randomUUID();
  sessionStorage.setItem(storageKey, created);
  return created;
}

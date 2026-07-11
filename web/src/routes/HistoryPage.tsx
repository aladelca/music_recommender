import { useInfiniteQuery } from "@tanstack/react-query";
import { ArrowRight, Clock3, LoaderCircle } from "lucide-react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";

export function HistoryPage() {
  const query = useInfiniteQuery({
    queryKey: ["recommendation-history"],
    queryFn: ({ pageParam }) => api.recommendationHistory(pageParam || undefined),
    initialPageParam: "",
    getNextPageParam: (page) => page.next_cursor ?? undefined,
  });
  const sessions = query.data?.pages.flatMap((page) => page.sessions) ?? [];
  return (
    <div className="page history-page">
      <header className="page-header"><div><p className="eyebrow">Archive</p><h1>Discovery history</h1><p>Your account-scoped recommendation sessions.</p></div></header>
      {query.isLoading ? <div className="page-state"><LoaderCircle className="spin" aria-hidden="true" /><span>Loading history</span></div> : null}
      {query.isError ? <div className="inline-alert" role="alert"><span>{query.error instanceof ApiError ? query.error.message : "History is unavailable."}</span></div> : null}
      {sessions.length > 0 ? <ol className="history-list">{sessions.map((session) => <li key={session.id}><Link to={`/sessions/${session.id}`}><span className="history-date"><Clock3 size={15} aria-hidden="true" />{formatDate(session.generated_at)}</span><strong>{session.prompt}</strong><span className="history-meta"><span className={`status-badge ${session.status}`}>{statusLabel(session.status)}</span><span>{session.ranking_version}</span></span><ArrowRight className="history-arrow" size={18} aria-hidden="true" /></Link></li>)}</ol> : !query.isLoading ? <div className="empty-state"><strong>No sessions yet</strong><span>Your completed discovery requests will appear here.</span></div> : null}
      {query.hasNextPage ? <button className="secondary-button load-more" type="button" disabled={query.isFetchingNextPage} onClick={() => void query.fetchNextPage()}>{query.isFetchingNextPage ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : null} Load more</button> : null}
    </div>
  );
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" }).format(new Date(value));
}

function statusLabel(value: string): string {
  return value.slice(0, 1).toUpperCase() + value.slice(1);
}

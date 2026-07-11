import { CheckCircle2, ChevronDown, Database, TriangleAlert } from "lucide-react";
import { useState } from "react";

import type { Evidence } from "../api/schemas";

export function EvidenceCard({ evidence }: { evidence: Evidence }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <section className="evidence-card" aria-label="Recommendation evidence">
      <div className="evidence-heading">
        {evidence.verifiable ? <CheckCircle2 size={17} aria-hidden="true" /> : <TriangleAlert size={17} aria-hidden="true" />}
        <strong>{evidence.verifiable ? "Evidence checked" : "Limited evidence"}</strong>
      </div>
      {evidence.reasons.length > 0 ? (
        <ul className="reason-list">
          {evidence.reasons.map((reason, index) => <li key={`${reason.kind}-${index}`}>{reason.text}</li>)}
        </ul>
      ) : (
        <p className="muted">No detailed evidence was available for this track.</p>
      )}
      <button
        className="evidence-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <Database size={15} aria-hidden="true" />
        {expanded ? "Hide evidence details" : "Show evidence details"}
        <ChevronDown className={expanded ? "rotated" : ""} size={15} aria-hidden="true" />
      </button>
      {expanded ? (
        <div className="evidence-details">
          {evidence.reasons.map((reason, index) => (
            <div className="provenance-row" key={`${reason.source}-${reason.kind}-${index}`}>
              <span className="source-badge">{sourceName(reason.source)}</span>
              <span>{Object.values(reason.details).map(formatDetail).filter(Boolean).join(" · ")}</span>
            </div>
          ))}
          {evidence.limitations.length > 0 ? (
            <div className="limitations">
              {evidence.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function sourceName(source: string): string {
  return source === "listenbrainz" ? "ListenBrainz" : "Selected seed";
}

function formatDetail(value: unknown): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.filter((item) => typeof item === "string").join(", ");
  return "";
}

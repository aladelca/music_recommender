import type { RecommendationItem } from "../api/schemas";
import { EvidenceCard } from "./EvidenceCard";
import { SpotifyEmbed } from "./SpotifyEmbed";
import { TrackActions } from "./TrackActions";

type FeedbackType = "like" | "dislike" | "hide_artist" | "save";

type Props = {
  items: RecommendationItem[];
  activeTrackId: string | null;
  feedbackTrackId: string | null;
  onPreview: (trackId: string) => void;
  onFeedback: (item: RecommendationItem, eventType: FeedbackType) => void;
};

export function RecommendationList({ items, activeTrackId, feedbackTrackId, onPreview, onFeedback }: Props) {
  if (items.length === 0) {
    return <div className="empty-state"><strong>No mapped tracks yet</strong><span>Try another seed or prompt.</span></div>;
  }
  return (
    <ol className="recommendation-list">
      {items.map((item, index) => {
        const active = activeTrackId === item.display.spotify_track_id;
        return (
          <li className="recommendation-card" key={item.recording_mbid}>
            <div className="recommendation-rank">{String(index + 1).padStart(2, "0")}</div>
            <div className="recommendation-body">
              <header className="track-heading">
                <div>
                  <h2>{item.display.name}</h2>
                  <p>{item.display.artist_names.join(", ")}{item.display.explicit ? <span className="explicit-badge">E</span> : null}</p>
                </div>
                <TrackActions
                  trackName={item.display.name}
                  spotifyUrl={item.display.spotify_url}
                  active={active}
                  disabled={feedbackTrackId === item.recording_mbid}
                  onPreview={() => onPreview(item.display.spotify_track_id)}
                  onFeedback={(eventType) => onFeedback(item, eventType)}
                />
              </header>
              {active ? (
                <SpotifyEmbed
                  trackId={item.display.spotify_track_id}
                  trackName={item.display.name}
                  spotifyUrl={item.display.spotify_url}
                />
              ) : null}
              <EvidenceCard evidence={item.evidence} />
            </div>
          </li>
        );
      })}
    </ol>
  );
}

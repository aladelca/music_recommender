import { ExternalLink, Heart, ListPlus, Play, ThumbsDown, UserMinus } from "lucide-react";

type FeedbackType = "like" | "dislike" | "hide_artist" | "save";

type Props = {
  trackName: string;
  spotifyUrl: string;
  active: boolean;
  disabled?: boolean;
  onPreview: () => void;
  onFeedback: (eventType: FeedbackType) => void;
};

export function TrackActions({ trackName, spotifyUrl, active, disabled, onPreview, onFeedback }: Props) {
  return (
    <div className="track-actions">
      <button className="icon-text-button" type="button" onClick={onPreview} aria-pressed={active}>
        <Play size={16} fill={active ? "currentColor" : "none"} aria-hidden="true" />
        {active ? "Previewing" : "Preview"}
      </button>
      <button className="icon-button" type="button" disabled={disabled} onClick={() => onFeedback("like")} title={`Like ${trackName}`}>
        <Heart size={17} aria-hidden="true" /><span className="sr-only">Like {trackName}</span>
      </button>
      <button className="icon-button" type="button" disabled={disabled} onClick={() => onFeedback("dislike")} title={`Dislike ${trackName}`}>
        <ThumbsDown size={17} aria-hidden="true" /><span className="sr-only">Dislike {trackName}</span>
      </button>
      <button className="icon-button" type="button" disabled={disabled} onClick={() => onFeedback("hide_artist")} title={`Hide artists for ${trackName}`}>
        <UserMinus size={17} aria-hidden="true" /><span className="sr-only">Hide artists for {trackName}</span>
      </button>
      <button className="icon-button" type="button" disabled={disabled} onClick={() => onFeedback("save")} title={`Save ${trackName}`}>
        <ListPlus size={17} aria-hidden="true" /><span className="sr-only">Save {trackName}</span>
      </button>
      <a className="icon-button" href={spotifyUrl} target="_blank" rel="noreferrer" title={`Open ${trackName} in Spotify`}>
        <ExternalLink size={17} aria-hidden="true" /><span className="sr-only">Open {trackName} in Spotify</span>
      </a>
    </div>
  );
}

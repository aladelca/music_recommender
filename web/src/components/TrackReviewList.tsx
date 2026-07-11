import { ArrowDown, ArrowUp, GripVertical, X } from "lucide-react";

import type { RecommendationItem } from "../api/schemas";

type Props = {
  items: RecommendationItem[];
  onChange: (items: RecommendationItem[]) => void;
};

export function TrackReviewList({ items, onChange }: Props) {
  function move(index: number, offset: -1 | 1) {
    const target = index + offset;
    if (target < 0 || target >= items.length) return;
    const next = [...items];
    [next[index], next[target]] = [next[target], next[index]];
    onChange(next);
  }

  return (
    <ol className="review-track-list">
      {items.map((item, index) => (
        <li data-testid="review-track" key={item.recording_mbid}>
          <GripVertical className="drag-hint" size={18} aria-hidden="true" />
          <span className="track-position">{index + 1}</span>
          <span className="track-copy">
            <strong>{item.display.name}</strong>
            <span>{item.display.artist_names.join(", ")}</span>
          </span>
          <span className="track-order-actions">
            <button
              className="icon-button"
              type="button"
              disabled={index === 0}
              onClick={() => move(index, -1)}
              title={`Move ${item.display.name} up`}
            >
              <ArrowUp size={17} aria-hidden="true" />
              <span className="sr-only">Move {item.display.name} up</span>
            </button>
            <button
              className="icon-button"
              type="button"
              disabled={index === items.length - 1}
              onClick={() => move(index, 1)}
              title={`Move ${item.display.name} down`}
            >
              <ArrowDown size={17} aria-hidden="true" />
              <span className="sr-only">Move {item.display.name} down</span>
            </button>
            <button
              className="icon-button danger-icon"
              type="button"
              onClick={() => onChange(items.filter((candidate) => candidate.recording_mbid !== item.recording_mbid))}
              title={`Remove ${item.display.name}`}
            >
              <X size={17} aria-hidden="true" />
              <span className="sr-only">Remove {item.display.name}</span>
            </button>
          </span>
        </li>
      ))}
    </ol>
  );
}

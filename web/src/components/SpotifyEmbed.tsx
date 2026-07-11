import { ExternalLink, Music2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { loadSpotifyIframeApi } from "../lib/spotifyEmbed";

type Props = {
  trackId: string;
  trackName: string;
  spotifyUrl: string;
};

export function SpotifyEmbed({ trackId, trackName, spotifyUrl }: Props) {
  const target = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let mounted = true;
    const element = target.current;
    if (!element) return;
    void loadSpotifyIframeApi()
      .then((api) => {
        if (!mounted || !target.current) return;
        api.createController(
          target.current,
          { width: "100%", height: "152", uri: `spotify:track:${trackId}` },
          () => undefined,
        );
      })
      .catch(() => {
        if (mounted) setFailed(true);
      });
    return () => {
      mounted = false;
      if (element) element.replaceChildren();
    };
  }, [trackId]);

  return (
    <div className="spotify-embed" aria-label={`Spotify preview for ${trackName}`}>
      <div ref={target} className="spotify-embed-target">
        <div className="embed-placeholder">
          <Music2 size={22} aria-hidden="true" />
          <span>{failed ? "Preview unavailable" : "Loading Spotify preview"}</span>
        </div>
      </div>
      <a href={spotifyUrl} target="_blank" rel="noreferrer" className="spotify-attribution">
        Open in Spotify <ExternalLink size={14} aria-hidden="true" />
      </a>
    </div>
  );
}

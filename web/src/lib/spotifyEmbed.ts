type SpotifyEmbedOptions = {
  width: string;
  height: string;
  uri: string;
};

export type SpotifyEmbedController = {
  loadEntity: (uri: string) => void;
};

type SpotifyIframeApi = {
  createController: (
    element: HTMLElement,
    options: SpotifyEmbedOptions,
    callback: (controller: SpotifyEmbedController) => void,
  ) => void;
};

declare global {
  interface Window {
    onSpotifyIframeApiReady?: (api: SpotifyIframeApi) => void;
  }
}

let apiPromise: Promise<SpotifyIframeApi> | null = null;

export function loadSpotifyIframeApi(): Promise<SpotifyIframeApi> {
  if (apiPromise) return apiPromise;
  apiPromise = new Promise((resolve, reject) => {
    window.onSpotifyIframeApiReady = resolve;
    const existing = document.querySelector<HTMLScriptElement>("script[data-spotify-iframe-api]");
    if (existing) return;
    const script = document.createElement("script");
    script.src = "https://open.spotify.com/embed/iframe-api/v1";
    script.async = true;
    script.dataset.spotifyIframeApi = "true";
    script.addEventListener("error", () => reject(new Error("Spotify embed unavailable")), { once: true });
    document.body.append(script);
  });
  return apiPromise;
}

export function resetSpotifyIframeApiForTests(): void {
  apiPromise = null;
}

import { ExternalLink, LoaderCircle, Music, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";

import type { PlaylistExport } from "../api/schemas";

export type PlaylistExportValues = {
  name: string;
  description: string;
  public: boolean;
};

type Props = {
  initialName: string;
  initialPublic: boolean;
  trackCount: number;
  pending: boolean;
  error: string | null;
  result: PlaylistExport | null;
  onSubmit: (values: PlaylistExportValues) => void;
};

export function PlaylistExportForm({ initialName, initialPublic, trackCount, pending, error, result, onSubmit }: Props) {
  const [name, setName] = useState(initialName);
  const [description, setDescription] = useState("Discovered with Outside the Loop");
  const [isPublic, setIsPublic] = useState(initialPublic);
  const [validationError, setValidationError] = useState<string | null>(null);

  function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedName = name.trim();
    if (!normalizedName) {
      setValidationError("Playlist name is required.");
      return;
    }
    if (trackCount === 0) {
      setValidationError("Keep at least one track.");
      return;
    }
    setValidationError(null);
    onSubmit({ name: normalizedName, description: description.trim(), public: isPublic });
  }

  if (result?.spotify_playlist_url) {
    return (
      <div className="export-success" role="status">
        <ShieldCheck size={28} aria-hidden="true" />
        <div><strong>{result.name}</strong><span>{result.tracks_added} tracks added</span></div>
        <a className="primary-button" href={result.spotify_playlist_url} target="_blank" rel="noreferrer">
          Open playlist in Spotify <ExternalLink size={17} aria-hidden="true" />
        </a>
      </div>
    );
  }

  return (
    <form className="export-form" onSubmit={submit} noValidate>
      <div className="field-group">
        <label htmlFor="playlist-name">Playlist name</label>
        <input id="playlist-name" value={name} maxLength={100} onChange={(event) => setName(event.target.value)} disabled={pending} />
      </div>
      <div className="field-group">
        <label htmlFor="playlist-description">Description</label>
        <textarea id="playlist-description" value={description} maxLength={300} rows={3} onChange={(event) => setDescription(event.target.value)} disabled={pending} />
      </div>
      <label className="toggle-row">
        <input type="checkbox" checked={isPublic} onChange={(event) => setIsPublic(event.target.checked)} disabled={pending} />
        <span className="toggle" aria-hidden="true" />
        <span>Public playlist</span>
      </label>
      {validationError || error ? <p className="form-error" role="alert">{validationError ?? error}</p> : null}
      <button className="primary-button" type="submit" disabled={pending || trackCount === 0}>
        {pending ? <LoaderCircle className="spin" size={18} aria-hidden="true" /> : <Music size={18} aria-hidden="true" />}
        {pending ? "Creating playlist" : "Create playlist"}
      </button>
    </form>
  );
}

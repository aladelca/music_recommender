import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ExternalLink, KeyRound, LoaderCircle, LogOut, RefreshCw, Shield, Trash2, UserRound, X } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, ApiError } from "../api/client";
import { useAuth } from "../auth/useAuth";

export function SettingsPage() {
  const { user, logout } = useAuth();
  const queryClient = useQueryClient();
  const [deleting, setDeleting] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleted, setDeleted] = useState(false);
  const preferences = useQuery({ queryKey: ["preferences"], queryFn: api.preferences });
  const unblockMutation = useMutation({
    mutationFn: api.unblockArtist,
    onSuccess: (data) => queryClient.setQueryData(["preferences"], data),
  });
  const deleteMutation = useMutation({
    mutationFn: api.deleteAccount,
    onSuccess: () => {
      queryClient.clear();
      setDeleted(true);
    },
  });

  if (deleted) {
    return <div className="page-state account-deleted" role="status"><Shield size={30} aria-hidden="true" /><strong>Account deleted</strong><span>Your product data and Spotify token were removed.</span><a className="primary-button" href="/">Return to sign in</a></div>;
  }

  return (
    <div className="page settings-page">
      <header className="page-header"><div><p className="eyebrow">Account</p><h1>Settings</h1><p>{user?.display_name ?? "Beta tester"}</p></div></header>
      <div className="settings-sections">
        <section className="settings-section" aria-labelledby="spotify-settings-heading">
          <div className="settings-icon"><UserRound size={20} aria-hidden="true" /></div>
          <div className="settings-content"><h2 id="spotify-settings-heading">Spotify connection</h2><p>Identity, attributed links, previews, and playlist export.</p><div className="button-row"><a className="secondary-button" href="/api/auth/spotify/start?return_to=%2Fsettings"><RefreshCw size={16} aria-hidden="true" /> Reconnect</a><button className="text-button" type="button" onClick={() => void logout()}><LogOut size={16} aria-hidden="true" /> Log out</button></div></div>
        </section>

        <section className="settings-section" aria-labelledby="seed-settings-heading">
          <div className="settings-icon accent"><KeyRound size={20} aria-hidden="true" /></div>
          <div className="settings-content"><h2 id="seed-settings-heading">Music seeds</h2><p>One to five explicit MusicBrainz starting points.</p><Link className="secondary-button" to="/seeds">Edit seeds</Link></div>
        </section>

        <section className="settings-section" aria-labelledby="blocked-artists-heading">
          <div className="settings-icon warning"><Shield size={20} aria-hidden="true" /></div>
          <div className="settings-content"><h2 id="blocked-artists-heading">Blocked artists</h2>
            {preferences.isLoading ? <span className="inline-loading"><LoaderCircle className="spin" size={17} aria-hidden="true" /> Loading blocks</span> : null}
            {preferences.data?.blocked_artists.length ? <ul className="blocked-list">{preferences.data.blocked_artists.map((artist) => <li key={artist.mbid}><span>{artist.name}</span><button className="icon-button" type="button" disabled={unblockMutation.isPending} onClick={() => unblockMutation.mutate(artist.mbid)} title={`Unblock ${artist.name}`}><X size={17} aria-hidden="true" /><span className="sr-only">Unblock {artist.name}</span></button></li>)}</ul> : !preferences.isLoading ? <p>No blocked artists.</p> : null}
            {preferences.isError || unblockMutation.isError ? <p className="form-error" role="alert">{preferenceError(preferences.error ?? unblockMutation.error)}</p> : null}
          </div>
        </section>

        <section className="settings-section" aria-labelledby="privacy-settings-heading">
          <div className="settings-icon"><Shield size={20} aria-hidden="true" /></div>
          <div className="settings-content"><h2 id="privacy-settings-heading">Privacy</h2><p>Data sources, retention, providers, and deletion.</p><Link className="secondary-button" to="/privacy">Privacy notice <ExternalLink size={15} aria-hidden="true" /></Link></div>
        </section>

        <section className="settings-section danger-section" aria-labelledby="delete-account-heading">
          <div className="settings-icon danger"><Trash2 size={20} aria-hidden="true" /></div>
          <div className="settings-content"><h2 id="delete-account-heading">Delete account</h2><p>Permanently removes product data, sessions, and the encrypted Spotify refresh token.</p><button className="danger-button" type="button" onClick={() => setDeleting(true)}><Trash2 size={16} aria-hidden="true" /> Delete account</button></div>
        </section>
      </div>

      {deleting ? <div className="modal-backdrop" role="presentation"><section className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby="delete-dialog-heading"><button className="icon-button dialog-close" type="button" onClick={() => setDeleting(false)} title="Close"><X size={18} aria-hidden="true" /><span className="sr-only">Close</span></button><Trash2 className="dialog-danger-icon" size={26} aria-hidden="true" /><h2 id="delete-dialog-heading">Delete this account?</h2><p>This action cannot be undone.</p><div className="field-group"><label htmlFor="delete-confirmation">Type DELETE to confirm</label><input id="delete-confirmation" value={confirmation} autoComplete="off" onChange={(event) => setConfirmation(event.target.value)} /></div>{deleteMutation.isError ? <p className="form-error" role="alert">{deleteMutation.error instanceof ApiError ? deleteMutation.error.message : "Account deletion failed."}</p> : null}<button className="danger-button" type="button" disabled={confirmation !== "DELETE" || deleteMutation.isPending} onClick={() => deleteMutation.mutate()}>{deleteMutation.isPending ? <LoaderCircle className="spin" size={17} aria-hidden="true" /> : <Trash2 size={17} aria-hidden="true" />} Delete permanently</button></section></div> : null}
    </div>
  );
}

function preferenceError(error: unknown): string {
  return error instanceof ApiError ? error.message : "Preferences are unavailable.";
}

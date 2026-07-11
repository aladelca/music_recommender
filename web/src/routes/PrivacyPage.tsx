import { ArrowLeft, Database, ExternalLink, LockKeyhole, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";

export function PrivacyPage({ publicView = false }: { publicView?: boolean }) {
  return (
    <main className={publicView ? "privacy-public" : "page privacy-page"}>
      <header className="page-header privacy-header">
        {publicView ? <Link className="back-link" to="/"><ArrowLeft size={17} aria-hidden="true" /> Sign in</Link> : <Link className="back-link" to="/settings"><ArrowLeft size={17} aria-hidden="true" /> Settings</Link>}
        <p className="eyebrow">Beta privacy notice</p>
        <h1>Privacy at Outside the Loop</h1>
        <p>Effective July 10, 2026</p>
      </header>
      <div className="privacy-content">
        <section><span className="privacy-section-icon"><Database size={20} aria-hidden="true" /></span><div><h2>Data we store</h2><p>Your Spotify account identifier and display name, encrypted refresh token, explicit MusicBrainz seeds, recommendation sessions, review choices, playlist export records, feedback, and beta evaluations.</p></div></section>
        <section><span className="privacy-section-icon"><ExternalLink size={20} aria-hidden="true" /></span><div><h2>External providers</h2><p>MusicBrainz supplies search metadata. ListenBrainz supplies candidate links and evidence. Spotify supplies identity, attributed display links, track matching, previews, and playlist export. Supabase stores product records; AWS runs the API and encryption.</p></div></section>
        <section><span className="privacy-section-icon"><LockKeyhole size={20} aria-hidden="true" /></span><div><h2>Recommendation boundary</h2><p>Spotify profile, top-track, library, recently played, and playlist-reading data are not used to generate recommendations. Product catalog data is fetched from HTTPS APIs and cached in Supabase, not local files or S3 objects.</p></div></section>
        <section><span className="privacy-section-icon"><Database size={20} aria-hidden="true" /></span><div><h2>Retention</h2><p>Source caches expire automatically. OAuth state and expired sessions are cleaned daily. Recommendation and beta records are retained for the beta evaluation window unless you delete your account sooner.</p></div></section>
        <section><span className="privacy-section-icon danger"><Trash2 size={20} aria-hidden="true" /></span><div><h2>Deletion and contact</h2><p>Delete your account from Settings to remove user-owned product records and revoke the stored Spotify token. For beta privacy requests, contact the beta administrator who invited you.</p></div></section>
      </div>
    </main>
  );
}

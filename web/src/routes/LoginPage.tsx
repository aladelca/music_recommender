import { CircleAlert, ExternalLink, Radio, SlidersHorizontal } from "lucide-react";
import { Link, useLocation } from "react-router-dom";

type Props = { reconnect?: boolean };

export function LoginPage({ reconnect = false }: Props) {
  const location = useLocation();
  const error = new URLSearchParams(location.search).get("oauth_error");
  const title = reconnect ? "Reconnect Spotify" : "Outside the Loop";
  const action = reconnect ? "Reconnect Spotify" : "Continue with Spotify";
  const href = `/api/auth/spotify/start?return_to=${encodeURIComponent("/discover")}`;
  const oauthEnabled = import.meta.env.VITE_OAUTH_ENABLED !== "false";

  return (
    <main className="login-page">
      <section className="login-brand-panel" aria-labelledby="login-title">
        <div className="login-brand">
          <span className="brand-mark"><SlidersHorizontal size={21} aria-hidden="true" /></span>
          <span>Outside the Loop</span>
        </div>
        <div className="signal-field" aria-hidden="true">
          <span className="signal-line line-one" />
          <span className="signal-line line-two" />
          <span className="signal-line line-three" />
          <span className="signal-line line-four" />
          <Radio className="signal-radio" size={44} />
        </div>
        <div className="login-copy">
          <p className="eyebrow">Five-tester beta</p>
          <h1 id="login-title">{title}</h1>
          <p>Explicit seeds. Auditable evidence. A playlist only after your review.</p>
        </div>
      </section>
      <section className="login-action-panel" aria-label="Spotify sign in">
        <div className="login-action-inner">
          {error ? <div className="inline-alert" role="alert"><CircleAlert size={18} aria-hidden="true" /><span>{oauthErrorMessage(error)}</span></div> : null}
          {oauthEnabled ? (
            <a className="spotify-button" href={href}>{action}<ExternalLink size={17} aria-hidden="true" /></a>
          ) : (
            <button className="spotify-button" type="button" disabled>Spotify sign-in unavailable in preview</button>
          )}
          <p className="login-terms">By continuing, you agree to the beta <Link to="/privacy">privacy notice</Link>.</p>
        </div>
      </section>
    </main>
  );
}

function oauthErrorMessage(code: string): string {
  if (code === "access_denied") return "Spotify authorization was cancelled.";
  if (code === "expired_state") return "That sign-in link expired. Start again.";
  return "Spotify sign-in could not be completed.";
}

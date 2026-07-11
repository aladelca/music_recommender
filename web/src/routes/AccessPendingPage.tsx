import { Clock3, LogOut, ShieldX, SlidersHorizontal } from "lucide-react";

import { useAuth } from "../auth/useAuth";

export function AccessPendingPage({ status }: { status: "pending" | "revoked" }) {
  const { logout, refresh } = useAuth();
  const revoked = status === "revoked";
  return (
    <main className="access-page">
      <div className="access-brand"><SlidersHorizontal size={19} aria-hidden="true" /> Outside the Loop</div>
      <section className="access-state">
        <span className={revoked ? "status-icon revoked" : "status-icon"}>
          {revoked ? <ShieldX size={28} aria-hidden="true" /> : <Clock3 size={28} aria-hidden="true" />}
        </span>
        <p className="eyebrow">Beta access</p>
        <h1>{revoked ? "Access revoked" : "Approval pending"}</h1>
        <p>{revoked ? "This Spotify account is no longer on the beta allowlist." : "An administrator needs to approve this Spotify account."}</p>
        <div className="button-row">
          {!revoked ? <button className="primary-button" type="button" onClick={() => void refresh()}>Check status</button> : null}
          <button className="secondary-button" type="button" onClick={() => void logout()}><LogOut size={17} aria-hidden="true" /> Log out</button>
        </div>
      </section>
    </main>
  );
}

import { LoaderCircle } from "lucide-react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

import { useAuth } from "../auth/useAuth";
import { AppShell } from "../components/AppShell";
import { AccessPendingPage } from "../routes/AccessPendingPage";
import { DiscoverPage } from "../routes/DiscoverPage";
import { HistoryPage } from "../routes/HistoryPage";
import { LoginPage } from "../routes/LoginPage";
import { OnboardingPage } from "../routes/OnboardingPage";
import { PrivacyPage } from "../routes/PrivacyPage";
import { ReviewPage } from "../routes/ReviewPage";
import { SessionPage } from "../routes/SessionPage";
import { SettingsPage } from "../routes/SettingsPage";

export function App() {
  const { user, loading, error, refresh } = useAuth();
  const location = useLocation();
  if (
    location.pathname === "/privacy"
    && (!user || user.access_status !== "approved" || !user.seed_ready)
  ) return <PrivacyPage publicView />;
  if (loading) {
    return <div className="app-loading"><LoaderCircle className="spin" /><span>Opening your session</span></div>;
  }
  if (error) {
    return <div className="page-state error-state" role="alert"><strong>Service unavailable</strong><span>Authentication could not be checked.</span><button className="secondary-button" type="button" onClick={() => void refresh()}>Try again</button></div>;
  }
  if (!user) return <LoginPage />;
  if (user.access_status !== "approved") return <AccessPendingPage status={user.access_status} />;
  if (user.reauthorization_required) return <LoginPage reconnect />;
  if (!user.seed_ready) return <OnboardingPage />;
  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/discover" element={<DiscoverPage />} />
        <Route path="/seeds" element={<OnboardingPage compact />} />
        <Route path="/sessions/:sessionId" element={<SessionPage />} />
        <Route path="/sessions/:sessionId/review" element={<ReviewPage />} />
        <Route path="/history" element={<HistoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/privacy" element={<PrivacyPage />} />
      </Route>
      <Route path="*" element={<Navigate replace to="/discover" />} />
    </Routes>
  );
}

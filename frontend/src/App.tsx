import { Dashboard } from "./components/Dashboard";
import { LoginForm } from "./components/LoginForm";
import { useSession } from "./dashboard/useSession";

export function App() {
  const api = useSession();
  if (!api.session) {
    return <LoginForm onSignedIn={api.signIn} />;
  }
  // Keyed by user so signing in as someone else starts from a clean state.
  return <Dashboard key={api.session.userId} session={api.session} api={api} />;
}

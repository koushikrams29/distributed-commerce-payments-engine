import { LiveDataProvider } from "./app/LiveData";
import { SessionProvider } from "./app/session";
import { Shell } from "./app/Shell";
import { LoginForm } from "./components/LoginForm";
import { ToastProvider } from "./components/ui/Toast";
import { useSession } from "./dashboard/useSession";
import { useRoute, type Route } from "./lib/router";
import { EventsPage } from "./pages/EventsPage";
import { FailuresPage } from "./pages/FailuresPage";
import { InventoryPage } from "./pages/InventoryPage";
import { NotFoundPage } from "./pages/NotFoundPage";
import { OrderDetailPage } from "./pages/OrderDetailPage";
import { OrdersPage } from "./pages/OrdersPage";
import { OverviewPage } from "./pages/OverviewPage";
import { PaymentsPage } from "./pages/PaymentsPage";
import { ServicesPage } from "./pages/ServicesPage";

function Page({ route }: { route: Route }) {
  switch (route.name) {
    case "overview":
      return <OverviewPage />;
    case "orders":
      return <OrdersPage />;
    case "order":
      return <OrderDetailPage key={route.orderId} orderId={route.orderId} />;
    case "events":
      return <EventsPage />;
    case "payments":
      return <PaymentsPage />;
    case "inventory":
      return <InventoryPage />;
    case "failures":
      return <FailuresPage />;
    case "services":
      return <ServicesPage />;
    case "not-found":
      return <NotFoundPage />;
  }
}

function Console() {
  const route = useRoute();
  return (
    <Shell>
      <Page route={route} />
    </Shell>
  );
}

export function App() {
  const api = useSession();
  if (!api.session) {
    return <LoginForm onSignedIn={api.signIn} />;
  }
  // Keyed by user so signing in as someone else starts from a clean state.
  return (
    <SessionProvider key={api.session.userId} session={api.session} api={api}>
      <ToastProvider>
        <LiveDataProvider>
          <Console />
        </LiveDataProvider>
      </ToastProvider>
    </SessionProvider>
  );
}

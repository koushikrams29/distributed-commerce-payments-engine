import { EmptyState } from "../components/ui/States";
import { Link } from "../lib/router";

export function NotFoundPage() {
  return (
    <div className="page">
      <EmptyState
        title="Page not found"
        detail="This address doesn't match any page in the console."
        action={
          <Link className="button button--secondary" to="/">
            Go to the overview
          </Link>
        }
      />
    </div>
  );
}

import { Link } from "react-router-dom";
import { AlertCircle } from "lucide-react";

export function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center h-full text-center p-6">
      <AlertCircle className="h-12 w-12 text-clr-danger mb-4" />
      <h1 className="text-lg font-semibold text-clr-text">
        404 — Page Not Found
      </h1>
      <p className="text-xs text-clr-text-secondary mt-2">
        The page you're looking for doesn't exist.
      </p>
      <Link
        to="/"
        className="mt-4 text-xs text-clr-action hover:underline"
      >
        Go to Service Catalog
      </Link>
    </div>
  );
}

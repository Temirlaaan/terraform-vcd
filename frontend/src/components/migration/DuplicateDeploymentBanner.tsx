import { AlertTriangle } from "lucide-react";
import { Link } from "react-router-dom";
import { useDeployments } from "@/api/deploymentsApi";

interface DuplicateDeploymentBannerProps {
  targetEdgeId: string;
}

export function DuplicateDeploymentBanner({
  targetEdgeId,
}: DuplicateDeploymentBannerProps) {
  const query = useDeployments(targetEdgeId || undefined);

  if (!targetEdgeId) return null;
  if (query.isLoading) return null;
  if (!query.data || query.data.total === 0) return null;

  const items = query.data.items;

  return (
    <div className="mx-4 mt-3 flex items-start gap-2 rounded-sm border border-amber-200 bg-amber-50 p-3">
      <AlertTriangle className="h-4 w-4 text-amber-600 flex-none mt-0.5" />
      <div className="text-xs text-amber-800 leading-relaxed">
        <p className="font-medium">
          На эту edge уже сохранено деплойментов:{" "}
          <span className="font-semibold">{query.data.total}</span>.
        </p>
        <p className="mt-1 break-all">
          {items.map((d, i) => (
            <span key={d.id}>
              <Link
                to={`/migration?deployment=${d.id}`}
                className="underline text-amber-900 hover:text-amber-700"
              >
                {d.name}
              </Link>
              {i < items.length - 1 && ", "}
            </span>
          ))}
        </p>
      </div>
    </div>
  );
}

import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KeycloakProvider } from "@/auth/KeycloakProvider";
import { RequireRole } from "@/auth/RequireRole";
import { useAuth } from "@/auth/useAuth";
import { Layout } from "@/components/Layout";
import { CatalogPage } from "@/pages/CatalogPage";
import { ProvisionPage } from "@/pages/ProvisionPage";
import { DeploymentsPage } from "@/pages/DeploymentsPage";
import { DeploymentDetailPage } from "@/pages/DeploymentDetailPage";
import { DeploymentEditorPage } from "@/pages/DeploymentEditorPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { MigrationPage } from "@/pages/MigrationPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { UnauthorizedPage } from "@/pages/UnauthorizedPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // match backend Redis cache TTL
      retry: 1,
    },
  },
});

const WRITE_ROLES = ["tf-admin", "tf-operator"];

// Index route: writers see Service Catalog (Phase 0 provision flow,
// still under active development). Viewers don't see the catalog at
// all — they land on /deployments (their primary surface).
function IndexRoute() {
  const { roles } = useAuth();
  const isWriter = WRITE_ROLES.some((r) => roles.includes(r));
  return isWriter ? <CatalogPage /> : <Navigate to="/deployments" replace />;
}

export default function App() {
  return (
    <BrowserRouter>
      <KeycloakProvider>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<IndexRoute />} />
              <Route
                path="provision"
                element={
                  <RequireRole roles={WRITE_ROLES}>
                    <ProvisionPage />
                  </RequireRole>
                }
              />
              <Route
                path="migration"
                element={
                  <RequireRole roles={WRITE_ROLES}>
                    <MigrationPage />
                  </RequireRole>
                }
              />
              <Route path="deployments" element={<DeploymentsPage />} />
              <Route
                path="deployments/new"
                element={
                  <RequireRole roles={WRITE_ROLES}>
                    <DeploymentEditorPage />
                  </RequireRole>
                }
              />
              <Route path="deployments/:id" element={<DeploymentDetailPage />} />
              <Route
                path="deployments/:id/edit"
                element={
                  <RequireRole roles={WRITE_ROLES}>
                    <DeploymentEditorPage />
                  </RequireRole>
                }
              />
              <Route
                path="settings"
                element={
                  <RequireRole roles={["tf-admin"]}>
                    <SettingsPage />
                  </RequireRole>
                }
              />
              <Route path="unauthorized" element={<UnauthorizedPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </QueryClientProvider>
      </KeycloakProvider>
    </BrowserRouter>
  );
}

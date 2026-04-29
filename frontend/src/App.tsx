import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KeycloakProvider } from "@/auth/KeycloakProvider";
import { RequireRole } from "@/auth/RequireRole";
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

export default function App() {
  return (
    <BrowserRouter>
      <KeycloakProvider>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<CatalogPage />} />
              <Route path="provision" element={<ProvisionPage />} />
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
              <Route path="settings" element={<SettingsPage />} />
              <Route path="unauthorized" element={<UnauthorizedPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </QueryClientProvider>
      </KeycloakProvider>
    </BrowserRouter>
  );
}

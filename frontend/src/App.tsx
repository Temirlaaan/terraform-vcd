import { BrowserRouter, Routes, Route } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KeycloakProvider } from "@/auth/KeycloakProvider";
import { Layout } from "@/components/Layout";
import { CatalogPage } from "@/pages/CatalogPage";
import { ProvisionPage } from "@/pages/ProvisionPage";
import { DeploymentsPage } from "@/pages/DeploymentsPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { MigrationPage } from "@/pages/MigrationPage";
import { NotFoundPage } from "@/pages/NotFoundPage";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // match backend Redis cache TTL
      retry: 1,
    },
  },
});

export default function App() {
  return (
    <BrowserRouter>
      <KeycloakProvider>
        <QueryClientProvider client={queryClient}>
          <Routes>
            <Route element={<Layout />}>
              <Route index element={<CatalogPage />} />
              <Route path="provision" element={<ProvisionPage />} />
              <Route path="migration" element={<MigrationPage />} />
              <Route path="deployments" element={<DeploymentsPage />} />
              <Route path="settings" element={<SettingsPage />} />
              <Route path="*" element={<NotFoundPage />} />
            </Route>
          </Routes>
        </QueryClientProvider>
      </KeycloakProvider>
    </BrowserRouter>
  );
}

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { KeycloakProvider } from "@/auth/KeycloakProvider";
import { Layout } from "@/components/Layout";

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
    <KeycloakProvider>
      <QueryClientProvider client={queryClient}>
        <Layout />
      </QueryClientProvider>
    </KeycloakProvider>
  );
}

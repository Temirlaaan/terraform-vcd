import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { MigrationSummary } from "@/api/migrationApi";
import type { Deployment } from "@/api/deploymentsApi";

// H3-FE: legacy-VCD api_token is never stored in browser any more.
// The browser holds a short-lived opaque handle (UUID, ~10 min TTL,
// Redis-backed on the backend) which is useless without our backend.
// The raw token only exists in a local React state during the brief
// moment the admin types it into the form, then is exchanged for the
// handle and dropped. Handle is kept in sessionStorage so it survives
// page navigations within a tab session, but never localStorage.
const API_HANDLE_STORAGE_KEY = "migration_api_handle";

export interface MigrationFormState {
  host: string;
  edgeUuid: string;
  orgId: string;
  orgName: string;
  vdcId: string;
  vdcName: string;
  edgeGatewayId: string;
  edgeGatewayName: string;
  verifySsl: boolean;
}

export interface MigrationResult {
  hcl: string;
  edgeName: string;
  summary: MigrationSummary;
}

interface MigrationStore {
  form: MigrationFormState;
  apiHandle: string;
  result: MigrationResult | null;

  setFormField: <K extends keyof MigrationFormState>(
    key: K,
    value: MigrationFormState[K],
  ) => void;
  setApiHandle: (handle: string) => void;
  setResult: (result: MigrationResult | null) => void;
  hydrateFromDeployment: (d: Deployment) => void;
  resetForm: () => void;
}

const defaultForm: MigrationFormState = {
  host: "",
  edgeUuid: "",
  orgId: "",
  orgName: "",
  vdcId: "",
  vdcName: "",
  edgeGatewayId: "",
  edgeGatewayName: "",
  verifySsl: false,
};

const getInitialApiHandle = (): string => {
  if (typeof window === "undefined") return "";
  return sessionStorage.getItem(API_HANDLE_STORAGE_KEY) || "";
};

export const useMigrationStore = create<MigrationStore>()(
  persist(
    (set) => ({
      form: defaultForm,
      apiHandle: getInitialApiHandle(),
      result: null,

      setFormField: (key, value) =>
        set((s) => ({ form: { ...s.form, [key]: value } })),

      setApiHandle: (handle) => {
        set({ apiHandle: handle });
        if (typeof window !== "undefined") {
          if (handle) {
            sessionStorage.setItem(API_HANDLE_STORAGE_KEY, handle);
          } else {
            sessionStorage.removeItem(API_HANDLE_STORAGE_KEY);
          }
        }
      },

      setResult: (result) => set({ result }),

      hydrateFromDeployment: (d) =>
        set({
          form: {
            host: d.source_host,
            edgeUuid: d.source_edge_uuid,
            orgId: "",
            orgName: d.target_org,
            vdcId: d.target_vdc_id,
            vdcName: d.target_vdc,
            edgeGatewayId: d.target_edge_id,
            edgeGatewayName: "",
            verifySsl: d.verify_ssl,
          },
          result: {
            hcl: d.hcl,
            edgeName: d.source_edge_name,
            summary: d.summary,
          },
        }),

      resetForm: () => {
        if (typeof window !== "undefined") {
          sessionStorage.removeItem(API_HANDLE_STORAGE_KEY);
        }
        set({ form: defaultForm, apiHandle: "", result: null });
      },
    }),
    {
      name: "migration-form",
      storage: createJSONStorage(() => localStorage),
      partialize: (state) => ({ form: state.form }),
      version: 1,
    },
  ),
);

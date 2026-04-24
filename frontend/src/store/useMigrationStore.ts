import { create } from "zustand";
import { persist, createJSONStorage } from "zustand/middleware";
import type { MigrationSummary } from "@/api/migrationApi";
import type { Deployment } from "@/api/deploymentsApi";

const API_TOKEN_STORAGE_KEY = "migration_api_token";

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
  apiToken: string;
  result: MigrationResult | null;

  setFormField: <K extends keyof MigrationFormState>(
    key: K,
    value: MigrationFormState[K],
  ) => void;
  setApiToken: (token: string) => void;
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

const getInitialApiToken = (): string => {
  if (typeof window === "undefined") return "";
  return sessionStorage.getItem(API_TOKEN_STORAGE_KEY) || "";
};

export const useMigrationStore = create<MigrationStore>()(
  persist(
    (set) => ({
      form: defaultForm,
      apiToken: getInitialApiToken(),
      result: null,

      setFormField: (key, value) =>
        set((s) => ({ form: { ...s.form, [key]: value } })),

      setApiToken: (token) => {
        set({ apiToken: token });
        if (typeof window !== "undefined") {
          if (token) {
            sessionStorage.setItem(API_TOKEN_STORAGE_KEY, token);
          } else {
            sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
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
          sessionStorage.removeItem(API_TOKEN_STORAGE_KEY);
        }
        set({ form: defaultForm, apiToken: "", result: null });
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

import { Building2 } from "lucide-react";
import { useConfigStore } from "@/store/useConfigStore";
import { FormInput } from "../shared";
import { Section } from "./Section";

export function OrgSection() {
  const org = useConfigStore((s) => s.org);
  const setOrg = useConfigStore((s) => s.setOrg);

  return (
    <Section
      title="Organization"
      icon={Building2}
      defaultOpen
      badge={org.name ? "1" : undefined}
    >
      <FormInput
        label="Organization Name"
        value={org.name}
        onChange={(v) => setOrg({ name: v })}
        placeholder="Enter new organization name..."
      />
      <FormInput
        label="Full Name"
        value={org.full_name}
        onChange={(v) => setOrg({ full_name: v })}
        placeholder="e.g. Acme Corporation"
      />
      <FormInput
        label="Description"
        value={org.description}
        onChange={(v) => setOrg({ description: v })}
        placeholder="Optional description"
      />
    </Section>
  );
}

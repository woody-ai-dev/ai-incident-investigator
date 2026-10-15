export type InvestigationTarget = {
  service: string;
  environments: readonly string[];
};

// The services available in our Compose demo. This is not automatic discovery.
export const INVESTIGATION_TARGETS = [
  { service: "order-service", environments: ["local"] },
] as const satisfies readonly InvestigationTarget[];

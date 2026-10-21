import type { HistoryPage } from "../../api/history";
import type { SelectOption } from "../../components/SelectField";
import { INVESTIGATION_TARGETS } from "../investigations/targets";

// Share demo targets with the investigation form and retain saved/linked historical values.
export function historyFilterOptions(
  items: HistoryPage["items"],
  selected: { service: string; environment: string },
): Record<"service" | "environment", SelectOption[]> {
  const service = new Set<string>(INVESTIGATION_TARGETS.map((target) => target.service));
  const environment = new Set<string>(
    INVESTIGATION_TARGETS.flatMap((target) => [...target.environments]),
  );
  for (const item of items) {
    service.add(item.service);
    environment.add(item.environment);
  }
  if (selected.service) service.add(selected.service);
  if (selected.environment) environment.add(selected.environment);
  const options = (values: Set<string>) =>
    [...values]
      .sort((left, right) => left.localeCompare(right))
      .map((value) => ({ value, label: value }));
  return { service: options(service), environment: options(environment) };
}

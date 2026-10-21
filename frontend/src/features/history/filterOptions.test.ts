import { expect, it } from "vitest";
import { historyFilterOptions } from "./filterOptions";

it("retains linked historical filters when no matching rows exist", () => {
  const result = historyFilterOptions([], { service: "retired-service", environment: "prod" });
  expect(result.service).toContainEqual({ value: "order-service", label: "order-service" });
  expect(result.service).toContainEqual({ value: "retired-service", label: "retired-service" });
  expect(result.environment).toContainEqual({ value: "local", label: "local" });
  expect(result.environment).toContainEqual({ value: "prod", label: "prod" });
});

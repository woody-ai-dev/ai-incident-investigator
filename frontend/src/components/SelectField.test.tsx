import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { SelectField } from "./SelectField";

const options = [
  { value: "order-service", label: "Order service" },
  { value: "payment-service", label: "Payment service" },
] as const;

const originalProperties = new Map<string, PropertyDescriptor | undefined>();

beforeAll(() => {
  // Radix uses browser APIs that jsdom does not implement. Keep these shims local to this suite.
  for (const [name, value] of Object.entries({
    hasPointerCapture: (): boolean => false,
    setPointerCapture: (): void => {},
    releasePointerCapture: (): void => {},
    scrollIntoView: (): void => {},
  })) {
    originalProperties.set(name, Object.getOwnPropertyDescriptor(HTMLElement.prototype, name));
    Object.defineProperty(HTMLElement.prototype, name, { value, configurable: true });
  }
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "PointerEvent",
    class extends MouseEvent {
      readonly pointerId: number;
      readonly pointerType: string;
      constructor(type: string, options: PointerEventInit = {}) {
        super(type, options);
        this.pointerId = options.pointerId ?? 0;
        this.pointerType = options.pointerType ?? "mouse";
      }
    },
  );
});

afterAll(() => {
  for (const [name, descriptor] of originalProperties) {
    if (descriptor) Object.defineProperty(HTMLElement.prototype, name, descriptor);
    else Reflect.deleteProperty(HTMLElement.prototype, name);
  }
  vi.unstubAllGlobals();
});

function Field({ disabled = false, invalid = false }: { disabled?: boolean; invalid?: boolean }) {
  const [value, setValue] = useState("order-service");
  const [open, setOpen] = useState(false);
  return (
    <form>
      <label htmlFor="service">Service</label>
      <SelectField
        id="service"
        name="service"
        value={value}
        open={open}
        onOpenChange={setOpen}
        options={options}
        onValueChange={setValue}
        disabled={disabled}
        invalid={invalid}
        describedBy={invalid ? "service-error" : undefined}
      />
      {invalid && <p id="service-error">Choose a configured service.</p>}
      <output aria-label="Chosen service">{value}</output>
    </form>
  );
}

it("opens a styled list and selects an option by mouse", async () => {
  const user = userEvent.setup();
  render(<Field />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  expect(trigger).toHaveTextContent("Order service");
  await user.click(trigger);
  expect(screen.getByRole("listbox")).toBeVisible();
  const current = screen.getByRole("option", { name: "Order service" });
  expect(current).toHaveAttribute("data-state", "checked");
  expect(current.querySelector("svg")).toBeInTheDocument();
  await user.click(screen.getByRole("option", { name: "Payment service" }));
  expect(trigger).toHaveTextContent("Payment service");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent(
    "payment-service",
  );
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("supports keyboard navigation and returns focus after Escape", async () => {
  const user = userEvent.setup();
  render(<Field />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  await user.tab();
  expect(trigger).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(screen.getByRole("listbox")).toBeVisible();
  await user.keyboard("{ArrowDown}{Enter}");
  expect(trigger).toHaveTextContent("Payment service");
  await user.keyboard("{Enter}{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("links validation messages and prevents interaction while disabled", async () => {
  const user = userEvent.setup();
  render(<Field invalid disabled />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  expect(trigger).toHaveAttribute("aria-invalid", "true");
  expect(trigger).toHaveAccessibleDescription("Choose a configured service.");
  expect(trigger).toBeDisabled();
  await user.click(trigger);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("closes after selecting the current option without changing its value", async () => {
  const user = userEvent.setup();
  render(<Field />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  await user.click(trigger);
  await user.click(screen.getByRole("option", { name: "Order service" }));
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(trigger).toHaveTextContent("Order service");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent("order-service");
  expect(trigger).toHaveFocus();
});

it("keeps the selected value when Escape cancels a highlighted alternative", async () => {
  const user = userEvent.setup();
  render(<Field />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  trigger.focus();
  await user.keyboard("{Enter}{ArrowDown}");
  expect(screen.getByRole("option", { name: "Payment service" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveTextContent("Order service");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent("order-service");
  expect(trigger).toHaveFocus();
});

it("respects a shared parent open state so only one selector can remain expanded", async () => {
  const onOpenChange = vi.fn();
  function PairedFields({ active }: { active: "service" | "environment" | null }) {
    return (
      <form>
        <label htmlFor="service">Service</label>
        <SelectField
          id="service"
          name="service"
          value="order-service"
          options={options}
          onValueChange={vi.fn()}
          open={active === "service"}
          onOpenChange={(open) => onOpenChange("service", open)}
        />
        <label htmlFor="environment">Environment</label>
        <SelectField
          id="environment"
          name="environment"
          value="local"
          options={[{ value: "local", label: "local" }]}
          onValueChange={vi.fn()}
          open={active === "environment"}
          onOpenChange={(open) => onOpenChange("environment", open)}
        />
      </form>
    );
  }
  const { rerender } = render(<PairedFields active={null} />);
  const service = screen.getByRole("combobox", { name: "Service" });
  const environment = screen.getByRole("combobox", { name: "Environment" });
  rerender(<PairedFields active="service" />);
  expect(screen.getAllByRole("listbox")).toHaveLength(1);
  expect(
    within(screen.getByRole("listbox")).getByRole("option", { name: "Order service" }),
  ).toBeVisible();
  expect(service).toHaveAttribute("aria-expanded", "true");
  rerender(<PairedFields active="environment" />);
  expect(screen.getAllByRole("listbox")).toHaveLength(1);
  expect(screen.queryByRole("option", { name: "Order service" })).not.toBeInTheDocument();
  expect(within(screen.getByRole("listbox")).getByRole("option", { name: "local" })).toBeVisible();
  expect(service).toHaveAttribute("aria-expanded", "false");
  expect(environment).toHaveAttribute("aria-expanded", "true");
  rerender(<PairedFields active={null} />);
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(environment).toHaveAttribute("aria-expanded", "false");
});

it("selects the last item in a long list by keyboard and retains it when Escape cancels", async () => {
  const user = userEvent.setup();
  const longOptions = Array.from({ length: 40 }, (_, index) => ({
    value: `service-${index + 1}`,
    label: `Service ${index + 1}`,
  }));
  function LongField() {
    const [value, setValue] = useState("service-1");
    return (
      <form>
        <label htmlFor="service">Service</label>
        <SelectField
          id="service"
          name="service"
          value={value}
          options={longOptions}
          onValueChange={setValue}
        />
        <output aria-label="Chosen service">{value}</output>
      </form>
    );
  }
  render(<LongField />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  await user.tab();
  await user.keyboard("{Enter}{End}");
  expect(screen.getAllByRole("option")).toHaveLength(40);
  expect(screen.getByRole("option", { name: "Service 40" })).toHaveFocus();
  await user.keyboard("{Enter}");
  expect(trigger).toHaveTextContent("Service 40");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent("service-40");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  await user.keyboard("{Enter}{Home}");
  expect(screen.getByRole("option", { name: "Service 1" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveTextContent("Service 40");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent("service-40");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  expect(trigger).toHaveFocus();
});

it("supports clearing an optional filter without leaking its internal All value", async () => {
  const user = userEvent.setup();
  function OptionalField() {
    const [value, setValue] = useState("");
    return (
      <form>
        <label htmlFor="service">Service</label>
        <SelectField
          id="service"
          name="service"
          value={value}
          options={[...options, { value: "__select_empty__", label: "Historical service" }]}
          emptyLabel="All services"
          onValueChange={setValue}
        />
        <output aria-label="Chosen service">{value || "No filter"}</output>
      </form>
    );
  }
  render(<OptionalField />);
  const trigger = screen.getByRole("combobox", { name: "Service" });
  expect(trigger).toHaveTextContent("All services");
  expect(trigger).not.toHaveAttribute("aria-required", "true");
  await user.click(trigger);
  await user.click(screen.getByRole("option", { name: "Historical service" }));
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent(
    "__select_empty__",
  );
  await user.click(trigger);
  await user.click(screen.getByRole("option", { name: "All services" }));
  expect(trigger).toHaveTextContent("All services");
  expect(new FormData(trigger.closest("form")!).get("service")).toBe("");
  expect(screen.getByRole("status", { name: "Chosen service" })).toHaveTextContent("No filter");
});

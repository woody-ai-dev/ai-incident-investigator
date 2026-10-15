import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { InvestigationForm } from "./InvestigationForm";

describe("investigation form", () => {
  it("sends the actual UTC interval in relative mode during a repeated local hour", async () => {
    const timezone = process.env.TZ;
    process.env.TZ = "America/New_York";
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-01T06:30:00Z"));
    try {
      const submit = vi.fn();
      const user = userEvent.setup();
      render(
        <InvestigationForm
          phase="idle"
          evidenceCount={null}
          error={null}
          onSubmit={submit}
          onCancel={vi.fn()}
        />,
      );
      await user.click(screen.getByRole("button", { name: "Investigate" }));
      expect(submit).toHaveBeenCalledWith(
        expect.objectContaining({
          start_time: "2026-11-01T06:15:00.000Z",
          end_time: "2026-11-01T06:30:00.000Z",
        }),
      );
    } finally {
      vi.useRealTimers();
      if (timezone === undefined) delete process.env.TZ;
      else process.env.TZ = timezone;
    }
  });
  it("offers only the service and environment configured for this local demo", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(
      <InvestigationForm
        phase="idle"
        evidenceCount={null}
        error={null}
        onSubmit={submit}
        onCancel={vi.fn()}
      />,
    );
    const service = screen.getByRole("combobox", { name: "Service" });
    const environment = screen.getByRole("combobox", { name: "Environment" });

    expect(service).toHaveTextContent("order-service");
    expect(environment).toHaveTextContent("local");
    await user.tab();
    await user.tab();
    expect(service).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "order-service" })).toBeVisible();
    await user.keyboard("{Escape}");
    environment.focus();
    await user.keyboard("{ArrowDown}");
    expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(1);
    expect(screen.getByRole("option", { name: "local" })).toBeVisible();
    await user.keyboard("{Escape}");
    await user.click(screen.getByRole("button", { name: "Investigate" }));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ service: "order-service", environment: "local" }),
    );
  });

  it("navigates the two independent field columns and closes both selectors without changing selections", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(
      <InvestigationForm
        phase="idle"
        evidenceCount={null}
        error={null}
        onSubmit={submit}
        onCancel={vi.fn()}
      />,
    );
    const service = screen.getByRole("combobox", { name: "Service" });
    const environment = screen.getByRole("combobox", { name: "Environment" });
    const left = screen.getByRole("group", { name: "Service and From" });
    const right = screen.getByRole("group", { name: "Environment and Until (excluded)" });
    expect(within(left).getByRole("combobox", { name: "Service" })).toBe(service);
    expect(within(left).getByLabelText("From")).toBeVisible();
    expect(within(right).getByRole("combobox", { name: "Environment" })).toBe(environment);
    expect(within(right).getByLabelText("Until (excluded)")).toBeVisible();
    service.focus();
    await user.tab();
    expect(screen.getByLabelText("From")).toHaveFocus();
    await user.tab();
    expect(environment).toHaveFocus();
    await user.tab();
    expect(screen.getByLabelText("Until (excluded)")).toHaveFocus();

    service.focus();
    await user.keyboard("{Enter}");
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    expect(environment).toBeDisabled();
    expect(service).toBeEnabled();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(environment).toBeEnabled();
    expect(service).toHaveFocus();
    expect(service).toHaveTextContent("order-service");
    environment.focus();
    await user.keyboard("{Enter}");
    expect(screen.getAllByRole("listbox")).toHaveLength(1);
    expect(service).toBeDisabled();
    expect(environment).toBeEnabled();
    expect(screen.queryByRole("option", { name: "order-service" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "local" }));
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(environment).toHaveFocus();
    expect(environment).toHaveTextContent("local");
    expect(service).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Investigate" }));
    expect(submit).toHaveBeenCalledWith(
      expect.objectContaining({ service: "order-service", environment: "local" }),
    );
  });

  it("announces validation failure and focuses a missing date before sending a request", async () => {
    const submit = vi.fn();
    const user = userEvent.setup();
    render(
      <InvestigationForm
        phase="idle"
        evidenceCount={null}
        error={null}
        onSubmit={submit}
        onCancel={vi.fn()}
      />,
    );
    const start = screen.getByLabelText("From");
    fireEvent.change(start, { target: { value: "" } });
    await user.click(screen.getByRole("button", { name: "Investigate" }));

    expect(submit).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toBeVisible();
    expect(start).toHaveFocus();
    expect(start).toHaveAttribute("aria-invalid", "true");
    expect(start).toHaveAccessibleDescription();
  });

  it("shows the completed evidence count beside the submit controls", () => {
    render(
      <InvestigationForm
        phase="success"
        evidenceCount={4}
        error={null}
        onSubmit={vi.fn()}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole("status")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent(/4.*evidence/i);
    expect(screen.getByRole("button", { name: "Investigate" })).toBeEnabled();
  });
});

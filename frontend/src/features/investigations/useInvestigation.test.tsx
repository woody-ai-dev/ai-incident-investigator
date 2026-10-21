import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, createInvestigation, type CreatedInvestigation } from "../../api/client";
import { reportSchema, type InvestigationRequest } from "../../api/contracts";
import { useInvestigation } from "./useInvestigation";

vi.mock("../../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../api/client")>();
  return { ...actual, createInvestigation: vi.fn() };
});

const request: InvestigationRequest = {
  service: "order-service",
  environment: "local",
  start_time: "2026-10-14T10:00:00Z",
  end_time: "2026-10-14T10:10:00Z",
};
const report = reportSchema.parse({
  summary: "No matching evidence.",
  evidence: [],
  findings: [],
  hypotheses: [],
  recommended_checks: [],
  missing_data: ["No matching logs."],
});
const createMock = vi.mocked(createInvestigation);

function deferred() {
  let complete!: (value: CreatedInvestigation) => void;
  const promise = new Promise<CreatedInvestigation>((resolve) => {
    complete = resolve;
  });
  return {
    promise,
    resolve: (report: CreatedInvestigation["report"]) => {
      complete({ report, id: null });
    },
  };
}

beforeEach(() => {
  createMock.mockReset();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useInvestigation request lifecycle", () => {
  it("ignores a superseded result even when the previous promise ignores cancellation", async () => {
    const first = deferred();
    const second = deferred();
    createMock.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise);
    const { result } = renderHook(useInvestigation);
    act(() => {
      void result.current.submit(request);
    });
    act(() => {
      void result.current.submit({ ...request, description: "New investigation" });
    });
    expect(createMock.mock.calls[0]?.[1].aborted).toBe(true);

    await act(async () => {
      first.resolve(report);
      await first.promise;
    });
    expect(result.current.state.phase).toBe("loading");
    await act(async () => {
      second.resolve(report);
      await second.promise;
    });
    expect(result.current.state).toMatchObject({
      phase: "success",
      request: { description: "New investigation" },
      report,
    });
  });

  it("keeps the idle state after stopping even if the cancelled request resolves later", async () => {
    const pending = deferred();
    createMock.mockReturnValue(pending.promise);
    const { result } = renderHook(useInvestigation);
    act(() => {
      void result.current.submit(request);
    });
    act(() => {
      result.current.cancel();
    });
    expect(createMock.mock.calls[0]?.[1].aborted).toBe(true);
    expect(result.current.state.phase).toBe("idle");
    await act(async () => {
      pending.resolve(report);
      await pending.promise;
    });
    expect(result.current.state.phase).toBe("idle");
  });

  it("retains the last successful result through pending requests, cancellation and failure", async () => {
    const pending = deferred();
    createMock
      .mockResolvedValueOnce({ report, id: null })
      .mockReturnValueOnce(pending.promise)
      .mockRejectedValueOnce(new ApiError("Could not connect to the investigator API."));
    const { result } = renderHook(useInvestigation);
    expect(result.current.lastResult).toBeNull();
    await act(async () => {
      await result.current.submit(request);
    });
    const previous = result.current.lastResult;
    expect(previous).toEqual({ request, report, id: null });

    act(() => {
      void result.current.submit({ ...request, description: "Second investigation" });
    });
    expect(result.current.state.phase).toBe("loading");
    expect(result.current.lastResult).toBe(previous);
    act(() => result.current.cancel());
    expect(result.current.state.phase).toBe("idle");
    expect(result.current.lastResult).toBe(previous);

    await act(async () => {
      pending.resolve({ ...report, summary: "Cancelled response must be discarded." });
      await pending.promise;
    });
    expect(result.current.state.phase).toBe("idle");
    expect(result.current.lastResult).toBe(previous);

    await act(async () => {
      await result.current.submit({ ...request, description: "Retry investigation" });
    });
    expect(result.current.state).toMatchObject({
      phase: "error",
      error: { message: "Could not connect to the investigator API." },
    });
    expect(result.current.lastResult).toBe(previous);
  });

  it("replaces the saved result only after the next active request succeeds", async () => {
    const pending = deferred();
    const newerRequest = { ...request, description: "Updated investigation" };
    const newerReport = { ...report, summary: "New investigation report." };
    createMock.mockResolvedValueOnce({ report, id: null }).mockReturnValueOnce(pending.promise);
    const { result } = renderHook(useInvestigation);
    await act(async () => {
      await result.current.submit(request);
    });
    const previous = result.current.lastResult;
    act(() => {
      void result.current.submit(newerRequest);
    });
    expect(result.current.lastResult).toBe(previous);
    await act(async () => {
      pending.resolve(newerReport);
      await pending.promise;
    });
    expect(result.current.state).toMatchObject({ phase: "success", report: newerReport });
    expect(result.current.lastResult).toEqual({
      request: newerRequest,
      report: newerReport,
      id: null,
    });
    expect(result.current.lastResult).not.toBe(previous);
  });

  it("aborts an active request when the component unmounts", async () => {
    const pending = deferred();
    createMock.mockReturnValue(pending.promise);
    const { result, unmount } = renderHook(useInvestigation);
    act(() => {
      void result.current.submit(request);
    });
    const signal = createMock.mock.calls[0]?.[1];
    expect(signal?.aborted).toBe(false);
    unmount();
    expect(signal?.aborted).toBe(true);
    await act(async () => {
      pending.resolve(report);
      await pending.promise;
    });
  });

  it("aborts after 90 seconds and shows an actionable timeout error", async () => {
    vi.useFakeTimers();
    createMock.mockImplementation(
      (_, signal) =>
        new Promise<CreatedInvestigation>((_, reject) => {
          signal.addEventListener(
            "abort",
            () => reject(new DOMException("Aborted", "AbortError")),
            { once: true },
          );
        }),
    );
    const { result } = renderHook(useInvestigation);
    act(() => {
      void result.current.submit(request);
    });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(90_000);
    });
    expect(createMock.mock.calls[0]?.[1].aborted).toBe(true);
    expect(result.current.state).toMatchObject({
      phase: "error",
      error: { name: "ApiError", message: "The request timed out. Try a shorter time window." },
    });
  });
});

import { act, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { ApiError } from "../../api/client";
import { useReadResource } from "./useReadResource";

afterEach(() => {
  vi.useRealTimers();
});
function deferred() {
  let resolve!: (data: string) => void;
  const promise = new Promise<string>((complete) => {
    resolve = complete;
  });
  return { promise, resolve };
}

it("hides an old URL result and ignores an out-of-order response", async () => {
  const first = deferred(),
    second = deferred();
  const loadFirst = vi.fn(() => first.promise),
    loadSecond = vi.fn(() => second.promise);
  const { result, rerender } = renderHook(({ id, load }) => useReadResource(id, load), {
    initialProps: { id: "first", load: loadFirst },
  });
  rerender({ id: "second", load: loadSecond });
  await act(async () => {
    first.resolve("stale");
    await first.promise;
  });
  expect(result.current.status).toBe("loading");
  await act(async () => {
    second.resolve("current");
    await second.promise;
  });
  expect(result.current).toMatchObject({ status: "success", data: "current" });
});

it("retries a failed read without retaining its error", async () => {
  const load = vi
    .fn<(signal: AbortSignal) => Promise<string>>()
    .mockRejectedValueOnce(new ApiError("Unavailable", 503))
    .mockResolvedValueOnce("ready");
  const { result } = renderHook(() => useReadResource("list", load));
  await act(async () => {
    await Promise.resolve();
  });
  expect(result.current).toMatchObject({ status: "error", error: { status: 503 } });
  await act(async () => {
    result.current.retry();
  });
  expect(result.current).toMatchObject({ status: "success", data: "ready" });
  expect(load).toHaveBeenCalledTimes(2);
});

it("aborts a read on unmount", () => {
  const load = vi.fn(
    (signal: AbortSignal) =>
      new Promise<string>(() => {
        expect(signal.aborted).toBe(false);
      }),
  );
  const { unmount } = renderHook(() => useReadResource("detail", load));
  const signal = load.mock.calls[0]?.[0];
  unmount();
  expect(signal?.aborted).toBe(true);
});

it("times out a stalled read and provides a retry", async () => {
  vi.useFakeTimers();
  const load = vi.fn(
    (signal: AbortSignal) =>
      new Promise<string>((_, reject) => {
        signal.addEventListener(
          "abort",
          () => {
            reject(new DOMException("Aborted", "AbortError"));
          },
          { once: true },
        );
      }),
  );
  const { result } = renderHook(() => useReadResource("detail", load));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(30_000);
  });
  expect(result.current).toMatchObject({
    status: "error",
    error: { message: "Loading timed out. Check the API connection and try again." },
  });
});

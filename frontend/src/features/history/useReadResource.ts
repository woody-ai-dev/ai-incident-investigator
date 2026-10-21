import { useEffect, useState } from "react";
import { ApiError } from "../../api/client";

type Result<T> = { status: "success"; data: T } | { status: "error"; error: ApiError };

// Keyed results prevent an older response from appearing under a new URL/filter.
export function useReadResource<T>(key: string, load: (signal: AbortSignal) => Promise<T>) {
  const [attempt, setAttempt] = useState(0);
  const [settled, setSettled] = useState<{
    key: string;
    attempt: number;
    result: Result<T>;
  } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 30_000);
    void load(controller.signal)
      .then(
        (data) => {
          if (current) setSettled({ key, attempt, result: { status: "success", data } });
        },
        (cause: unknown) => {
          if (current)
            setSettled({
              key,
              attempt,
              result: {
                status: "error",
                error: timedOut
                  ? new ApiError("Loading timed out. Check the API connection and try again.")
                  : cause instanceof ApiError
                    ? cause
                    : new ApiError("Could not load saved investigations."),
              },
            });
        },
      )
      .finally(() => {
        window.clearTimeout(timeout);
      });
    return () => {
      current = false;
      window.clearTimeout(timeout);
      controller.abort();
    };
  }, [key, load, attempt]);
  const result =
    settled?.key === key && settled.attempt === attempt
      ? settled.result
      : { status: "loading" as const };
  return {
    ...result,
    retry: () => {
      setAttempt((value) => value + 1);
    },
  };
}

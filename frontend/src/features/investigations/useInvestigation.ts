import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, createInvestigation } from "../../api/client";
import type { InvestigationReport, InvestigationRequest } from "../../api/contracts";

export type InvestigationState =
  | { phase: "idle" }
  | { phase: "loading"; request: InvestigationRequest }
  | { phase: "success"; request: InvestigationRequest; report: InvestigationReport }
  | { phase: "error"; error: ApiError };

type InvestigationResult = {
  request: InvestigationRequest;
  report: InvestigationReport;
};

export function useInvestigation() {
  const [state, setState] = useState<InvestigationState>({ phase: "idle" });
  const [lastResult, setLastResult] = useState<InvestigationResult | null>(null);
  const active = useRef<AbortController | null>(null);

  useEffect(
    () => () => {
      active.current?.abort();
      active.current = null;
    },
    [],
  );

  const cancel = useCallback(() => {
    active.current?.abort();
    active.current = null;
    setState({ phase: "idle" });
  }, []);

  const submit = useCallback(async (request: InvestigationRequest) => {
    active.current?.abort();
    const controller = new AbortController();
    active.current = controller;
    setState({ phase: "loading", request });
    let timedOut = false;
    const timeout = window.setTimeout(() => {
      timedOut = true;
      controller.abort();
    }, 90_000);
    try {
      const report = await createInvestigation(request, controller.signal);
      if (active.current === controller) {
        setLastResult({ request, report });
        setState({ phase: "success", request, report });
      }
    } catch (error: unknown) {
      if (active.current !== controller) return;
      const failure = timedOut
        ? new ApiError("The request timed out. Try a shorter time window.")
        : error instanceof ApiError
          ? error
          : new ApiError("Could not complete the request.");
      setState({ phase: "error", error: failure });
    } finally {
      window.clearTimeout(timeout);
      if (active.current === controller) active.current = null;
    }
  }, []);

  return { state, lastResult, submit, cancel };
}

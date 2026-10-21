import type { LLMUsage } from "../../api/llmUsage";
import { dollars, duration } from "./presentation";
import styles from "./Usage.module.css";

export function LLMUsageSummary({ usage }: { usage: LLMUsage | undefined }) {
  if (!usage) return null;
  return (
    <div className={styles.summary} aria-label="Model usage">
      <span>{usage.response_model ?? `Requested: ${usage.requested_model}`}</span>
      <span>
        {usage.tokens
          ? `${usage.tokens.total_tokens.toLocaleString("en-US")} tokens`
          : "Tokens not available"}
      </span>
      <span>
        {usage.estimated_cost_usd === null
          ? "Cost not available"
          : `${dollars(usage.estimated_cost_usd)} estimated`}
      </span>
      <span>{duration(usage.duration_ms)}</span>
    </div>
  );
}

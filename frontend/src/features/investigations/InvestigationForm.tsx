import { useRef, useState } from "react";
import type { ApiError } from "../../api/client";
import type { InvestigationRequest } from "../../api/contracts";
import { SelectField } from "../../components/SelectField";
import { defaultValues, recentWindow, validateForm, type FormValues } from "./form";
import { INVESTIGATION_TARGETS } from "./targets";
import styles from "./InvestigationForm.module.css";

type Props = {
  phase: "idle" | "loading" | "success" | "error";
  evidenceCount: number | null;
  error: ApiError | null;
  onSubmit: (request: InvestigationRequest) => void;
  onCancel: () => void;
};

export function InvestigationForm({ phase, evidenceCount, error, onSubmit, onCancel }: Props) {
  const [values, setValues] = useState(defaultValues);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [windowMode, setWindowMode] = useState<"relative" | "custom">("relative");
  const [submittedValues, setSubmittedValues] = useState<FormValues | null>(null);
  const [openField, setOpenField] = useState<"service" | "environment" | null>(null);
  const form = useRef<HTMLFormElement>(null);
  const busy = phase === "loading";
  const selectedTarget = INVESTIGATION_TARGETS.find((target) => target.service === values.service);
  const columns = [
    {
      field: "service",
      label: "Service",
      timeField: "start_time",
      timeLabel: "From",
      options: INVESTIGATION_TARGETS.map((target) => ({
        value: target.service,
        label: target.service,
      })),
    },
    {
      field: "environment",
      label: "Environment",
      timeField: "end_time",
      timeLabel: "Until (excluded)",
      options:
        selectedTarget?.environments.map((environment) => ({
          value: environment,
          label: environment,
        })) ?? [],
    },
  ] as const;
  const status = {
    idle: "Ready to investigate",
    loading: "Investigating — waiting for evidence…",
    success: `Report received · ${evidenceCount ?? 0} evidence items`,
    error: "Investigation request failed",
  }[phase];

  function message(field: keyof FormValues) {
    return (
      errors[field] ||
      (submittedValues?.[field] === values[field] ? error?.fieldErrors[field] : undefined)
    );
  }

  function update(field: keyof FormValues, value: string) {
    setValues((previous) => {
      if (field === "service") {
        const target = INVESTIGATION_TARGETS.find((item) => item.service === value);
        return { ...previous, service: value, environment: target?.environments[0] ?? "" };
      }
      return { ...previous, [field]: value };
    });
    setErrors((previous) => ({ ...previous, [field]: "" }));
    if (field === "start_time" || field === "end_time") setWindowMode("custom");
  }

  function resetWindow() {
    const recent = defaultValues();
    setValues((previous) => ({
      ...previous,
      start_time: recent.start_time,
      end_time: recent.end_time,
    }));
    setWindowMode("relative");
    setErrors({});
  }

  return (
    <form
      ref={form}
      className={styles.form}
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        const now = new Date();
        const recent = defaultValues(now);
        const current =
          windowMode === "relative"
            ? { ...values, start_time: recent.start_time, end_time: recent.end_time }
            : values;
        const result = validateForm(
          current,
          windowMode === "relative" ? recentWindow(now) : undefined,
        );
        setValues(current);
        setErrors(result.errors);
        if (result.request) {
          setSubmittedValues(current);
          onSubmit(result.request);
        } else {
          const field = Object.keys(result.errors)[0];
          const control = field ? form.current?.querySelector(`[id="${field}"]`) : null;
          if (control instanceof HTMLElement) control.focus();
        }
      }}
    >
      <div className={styles.sectionHeading}>
        <div>
          <span className={styles.eyebrow}>INCIDENT CONTEXT</span>
          <h2>Start an investigation</h2>
        </div>
        <button
          type="button"
          className={styles.textButton}
          aria-pressed={windowMode === "relative"}
          disabled={busy}
          onClick={resetWindow}
        >
          Last 15 minutes
        </button>
      </div>
      {Object.values(errors).some(Boolean) && (
        <p role="alert" className={styles.errorBanner}>
          Check the highlighted fields before investigating.
        </p>
      )}
      <fieldset disabled={busy} className={styles.fields}>
        {columns.map(({ field, label, timeField, timeLabel, options }) => (
          <div
            key={field}
            className={styles.fieldColumn}
            role="group"
            aria-label={`${label} and ${timeLabel}`}
          >
            <div className={styles.field}>
              <label htmlFor={field}>{label}</label>
              <SelectField
                id={field}
                name={field}
                value={values[field]}
                disabled={busy || (openField !== null && openField !== field)}
                invalid={Boolean(message(field))}
                describedBy={message(field) ? `${field}-error` : undefined}
                options={options}
                open={openField === field}
                onOpenChange={(open) =>
                  setOpenField((previous) => (open ? field : previous === field ? null : previous))
                }
                onValueChange={(value) => update(field, value)}
              />
              {message(field) && (
                <small id={`${field}-error`} className={styles.errorText}>
                  {message(field)}
                </small>
              )}
            </div>
            <div className={styles.field}>
              <label htmlFor={timeField}>{timeLabel}</label>
              <input
                id={timeField}
                name={timeField}
                type="datetime-local"
                step={1}
                required
                value={values[timeField]}
                aria-invalid={Boolean(message(timeField))}
                aria-describedby={message(timeField) ? `${timeField}-error` : undefined}
                onChange={(event) => update(timeField, event.target.value)}
              />
              {message(timeField) && (
                <small id={`${timeField}-error`} className={styles.errorText}>
                  {message(timeField)}
                </small>
              )}
            </div>
          </div>
        ))}
        <div className={`${styles.field} ${styles.fullWidth}`}>
          <label htmlFor="description">
            What happened? <span className={styles.muted}>Optional</span>
          </label>
          <textarea
            id="description"
            name="description"
            rows={2}
            placeholder="Orders fail with PAYMENT_TIMEOUT…"
            value={values.description}
            aria-invalid={Boolean(message("description"))}
            aria-describedby={message("description") ? "description-error" : undefined}
            onChange={(event) => update("description", event.target.value)}
          />
          {message("description") && (
            <small id="description-error" className={styles.errorText}>
              {message("description")}
            </small>
          )}
        </div>
      </fieldset>
      <p className={styles.windowHint}>
        {windowMode === "relative"
          ? "Last 15 minutes · refreshed when you investigate."
          : "Custom time window."}
      </p>
      <div className={styles.requestFeedback} data-phase={phase}>
        <span className={styles.feedbackDot} aria-hidden="true" />
        <p role="status">{status}</p>
        <button
          type="button"
          className={styles.cancelButton}
          disabled={!busy}
          style={{ visibility: busy ? "visible" : "hidden" }}
          onClick={onCancel}
        >
          Stop waiting
        </button>
      </div>
      <div className={styles.formFooter}>
        <p className={styles.muted}>
          Times use your browser timezone; requests use UTC. Metrics support windows up to one hour.
        </p>
        <div className={styles.formActions}>
          <button type="submit" className={styles.primaryButton} disabled={busy}>
            {busy ? (
              "Investigating…"
            ) : (
              <>
                Investigate <span aria-hidden="true">↗</span>
              </>
            )}
          </button>
        </div>
      </div>
      {error && (
        <p role="alert" className={styles.errorBanner}>
          {error.message}
        </p>
      )}
    </form>
  );
}

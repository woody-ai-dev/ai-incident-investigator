import { useState } from "react";
import { Link, useSearchParams } from "react-router";
import type { HistoryPage } from "../../api/history";
import { SelectField } from "../../components/SelectField";
import controls from "../../components/FormControls.module.css";
import { historyFilterOptions } from "./filterOptions";
import { localInput } from "./presentation";
import styles from "./History.module.css";

export function HistoryFilters({ items }: { items: HistoryPage["items"] }) {
  const [params, setParams] = useSearchParams();
  const [error, setError] = useState("");
  const [openField, setOpenField] = useState<"service" | "environment" | null>(null);
  const [values, setValues] = useState(() => ({
    service: params.get("service") ?? "",
    environment: params.get("environment") ?? "",
    created_from: localInput(params.get("created_from")),
    created_until: localInput(params.get("created_until")),
  }));
  const options = historyFilterOptions(items, values);
  function update(field: keyof typeof values, value: string) {
    setValues((previous) => ({ ...previous, [field]: value }));
  }
  return (
    <form
      className={styles.filters}
      aria-label="History filters"
      autoComplete="off"
      onSubmit={(event) => {
        event.preventDefault();
        const next = new URLSearchParams();
        for (const field of ["service", "environment"] as const) {
          const value = values[field].trim();
          if (value) next.set(field, value);
        }
        for (const field of ["created_from", "created_until"] as const) {
          const value = values[field];
          if (value) {
            const date = new Date(value);
            if (!Number.isFinite(date.getTime())) {
              setError("Enter valid creation dates.");
              return;
            }
            next.set(field, date.toISOString());
          }
        }
        const start = next.get("created_from"),
          end = next.get("created_until");
        if (start && end && Date.parse(end) <= Date.parse(start)) {
          setError("Created until must be after created from.");
          event.currentTarget.querySelector<HTMLInputElement>('[name="created_until"]')?.focus();
          return;
        }
        setError("");
        setParams(next);
      }}
    >
      {(["service", "environment"] as const).map((field) => (
        <div key={field} className={styles.field}>
          <label htmlFor={`history-${field}`}>
            {field === "service" ? "Service" : "Environment"}
          </label>
          <SelectField
            id={`history-${field}`}
            name={field}
            value={values[field]}
            emptyLabel={field === "service" ? "All services" : "All environments"}
            options={options[field]}
            open={openField === field}
            disabled={openField !== null && openField !== field}
            onOpenChange={(open) =>
              setOpenField((previous) => (open ? field : previous === field ? null : previous))
            }
            onValueChange={(value) => update(field, value)}
          />
        </div>
      ))}
      {(["created_from", "created_until"] as const).map((field) => (
        <div key={field} className={styles.field}>
          <label htmlFor={`history-${field}`}>
            {field === "created_from" ? "Created from" : "Created until (excluded)"}
          </label>
          <input
            id={`history-${field}`}
            name={field}
            className={controls.dateTime}
            type="datetime-local"
            step={1}
            value={values[field]}
            aria-invalid={field === "created_until" && error ? true : undefined}
            aria-describedby={
              field === "created_until" && error ? "history-filter-error" : undefined
            }
            onChange={(event) => update(field, event.target.value)}
          />
        </div>
      ))}
      <div className={styles.actions}>
        <button type="submit">Apply filters</button>
        <Link
          to="/investigations"
          onClick={() => {
            setValues({ service: "", environment: "", created_from: "", created_until: "" });
            setError("");
          }}
        >
          Reset filters
        </Link>
        <p className={styles.hint}>Exact names. Creation dates use your browser timezone.</p>
      </div>
      {error && (
        <p id="history-filter-error" role="alert">
          {error}
        </p>
      )}
    </form>
  );
}

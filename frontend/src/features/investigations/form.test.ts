import { describe, expect, it } from "vitest";
import { defaultValues, recentWindow, validateForm } from "./form";

function inTimezone<T>(timezone: string, run: () => T): T {
  const previous = process.env.TZ;
  process.env.TZ = timezone;
  try {
    return run();
  } finally {
    if (previous === undefined) delete process.env.TZ;
    else process.env.TZ = previous;
  }
}

describe("investigation form", () => {
  it("converts local inputs into aware UTC timestamps and trims identity", () => {
    const result = validateForm({
      ...defaultValues(),
      service: " order-service ",
      environment: " local ",
    });
    expect(result.errors).toEqual({});
    expect(result.request?.service).toBe("order-service");
    expect(result.request?.environment).toBe("local");
    expect(result.request?.start_time).toMatch(/Z$/);
    expect(result.request?.description).toBeNull();
  });

  it.each(["invalid", "2026-02-30T10:00", "2026-10-14T25:00", "2026-10-14T10:00Z"])(
    "rejects the invalid local date %s without throwing or normalizing it",
    (start_time) => {
      expect(validateForm({ ...defaultValues(), start_time }).errors.start_time).toBeTruthy();
    },
  );

  it("rejects a reversed custom window", () => {
    const values = defaultValues();
    expect(
      validateForm({
        ...values,
        start_time: values.end_time,
        end_time: values.start_time,
      }).errors.end_time,
    ).toBeTruthy();
  });

  it("accepts valid local minutes and fractional seconds with an explicit UTC request", () => {
    inTimezone("UTC", () => {
      const result = validateForm({
        ...defaultValues(),
        start_time: "2026-10-14T10:00",
        end_time: "2026-10-14T10:05:01.12",
      });
      expect(result.errors).toEqual({});
      expect(result.request?.start_time).toBe("2026-10-14T10:00:00.000Z");
      expect(result.request?.end_time).toBe("2026-10-14T10:05:01.120Z");
    });
  });

  it("uses code point limits for user descriptions and normalizes whitespace", () => {
    const values = defaultValues();
    expect(
      validateForm({ ...values, description: `  ${"🔥".repeat(4000)}  ` }).request?.description,
    ).toBe("🔥".repeat(4000));
    expect(
      validateForm({ ...values, description: "🔥".repeat(4001) }).errors.description,
    ).toBeTruthy();
  });

  it("preserves the real recent UTC window in the repeated DST hour", () => {
    inTimezone("America/New_York", () => {
      const now = new Date("2026-11-01T06:30:00.123Z");
      const values = defaultValues(now);
      expect(values.start_time).toBe("2026-11-01T01:15:00");
      expect(values.end_time).toBe("2026-11-01T01:30:00");
      const result = validateForm(values, recentWindow(now));
      expect(result.errors).toEqual({});
      expect(result.request?.start_time).toBe("2026-11-01T06:15:00.123Z");
      expect(result.request?.end_time).toBe("2026-11-01T06:30:00.123Z");
    });
  });

  it("keeps a recent window valid while the wall clock moves backwards", () => {
    inTimezone("America/New_York", () => {
      const now = new Date("2026-11-01T06:10:00Z");
      const values = defaultValues(now);
      expect(values.start_time).toBe("2026-11-01T01:55:00");
      expect(values.end_time).toBe("2026-11-01T01:10:00");
      const result = validateForm(values, recentWindow(now));
      expect(result.errors).toEqual({});
      expect(result.request?.start_time).toBe("2026-11-01T05:55:00.000Z");
      expect(result.request?.end_time).toBe("2026-11-01T06:10:00.000Z");
    });
  });

  it("rejects a custom wall time that does not exist during the DST spring gap", () => {
    inTimezone("America/New_York", () => {
      const result = validateForm({
        ...defaultValues(new Date("2026-03-08T07:45:00Z")),
        start_time: "2026-03-08T02:30:00",
        end_time: "2026-03-08T03:45:00",
      });
      expect(result.request).toBeUndefined();
      expect(result.errors.start_time).toBeTruthy();
    });
  });

  it("always constructs an elapsed fifteen-minute UTC window across a DST spring transition", () => {
    inTimezone("America/New_York", () => {
      const now = new Date("2026-03-08T07:05:00Z");
      const values = defaultValues(now);
      expect(values.start_time).toBe("2026-03-08T01:50:00");
      expect(values.end_time).toBe("2026-03-08T03:05:00");
      const window = recentWindow(now);
      expect(Date.parse(window.end_time) - Date.parse(window.start_time)).toBe(15 * 60_000);
      expect(validateForm(values, window).errors).toEqual({});
    });
  });
});

import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getInvestigation, listInvestigations } from "./history";

const fetchMock = vi.fn<typeof fetch>();
const signal = new AbortController().signal;
beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});
afterEach(() => {
  vi.unstubAllGlobals();
});

it("forwards encoded filters, cursor and cancellation to the read API", async () => {
  fetchMock.mockResolvedValue(Response.json({ items: [], next_cursor: null }));
  await expect(
    listInvestigations("service=orders&limit=20&cursor=opaque", signal),
  ).resolves.toEqual({ items: [], next_cursor: null });
  expect(fetchMock).toHaveBeenCalledWith(
    "/api/investigations?service=orders&limit=20&cursor=opaque",
    { headers: { Accept: "application/json" }, signal },
  );
});

it("rejects invalid UUIDs before fetching", async () => {
  await expect(getInvestigation("../../health", signal)).rejects.toMatchObject({ status: 422 });
  expect(fetchMock).not.toHaveBeenCalled();
});

it.each([404, 422, 500, 503])("shows safe errors for HTTP %s", async (status) => {
  fetchMock.mockResolvedValue(new Response("private database details", { status }));
  const error: unknown = await listInvestigations("", signal).catch((cause: unknown) => cause);
  expect(error).toMatchObject({ status });
  expect(String(error)).not.toContain("private");
});

it("rejects a malformed list or snapshot instead of rendering it", async () => {
  fetchMock.mockResolvedValue(Response.json({ items: [], next_cursor: null, secret: "private" }));
  await expect(listInvestigations("", signal)).rejects.toMatchObject({
    message: "The API returned invalid saved investigation data.",
  });
  fetchMock.mockResolvedValue(Response.json({ id: "private" }));
  await expect(getInvestigation("d9048d0d-669e-45b6-a199-a37db5d55a95", signal)).rejects.toThrow(
    "invalid saved investigation data",
  );
});

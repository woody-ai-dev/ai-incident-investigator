import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// jsdom has no layout or pointer capture. Browser integration checks cover these APIs.
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
if (!globalThis.PointerEvent) {
  Object.defineProperty(globalThis, "PointerEvent", {
    configurable: true,
    writable: true,
    value: class extends MouseEvent {
      readonly pointerId: number;
      readonly pointerType: string;
      constructor(type: string, options: PointerEventInit = {}) {
        super(type, options);
        this.pointerId = options.pointerId ?? 0;
        this.pointerType = options.pointerType ?? "mouse";
      }
    },
  });
}
for (const [name, value] of Object.entries({
  hasPointerCapture: (): boolean => false,
  setPointerCapture: (): void => {},
  releasePointerCapture: (): void => {},
  scrollIntoView: (): void => {},
})) {
  if (!(name in HTMLElement.prototype)) {
    Object.defineProperty(HTMLElement.prototype, name, {
      configurable: true,
      writable: true,
      value,
    });
  }
}

afterEach(cleanup);

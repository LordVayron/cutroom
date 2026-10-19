import { describe, expect, it } from "vitest";

import { activeStep, formatTime, isProcessing } from "./format";

describe("formatTime", () => {
  it("formats whole-minute timestamps", () => expect(formatTime(125.9)).toBe("2:05"));
  it("clamps negative timestamps", () => expect(formatTime(-4)).toBe("0:00"));
});

describe("pipeline status", () => {
  it("maps ready to ranked selects", () => expect(activeStep("ready")).toBe(2));
  it("polls only active work", () => {
    expect(isProcessing("transcribing")).toBe(true);
    expect(isProcessing("approved")).toBe(false);
  });
});


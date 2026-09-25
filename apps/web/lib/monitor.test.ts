import { describe, expect, it } from "vitest";
import { operationalCount } from "./monitor";

describe("operationalCount", () => {
  it("counts only operational monitors", () => {
    expect(operationalCount(["UP", "DOWN", "UP", "PENDING"])).toBe(2);
  });
});

export type MonitorState = "UP" | "DOWN" | "PENDING";

export function operationalCount(states: MonitorState[]): number {
  return states.filter((state) => state === "UP").length;
}

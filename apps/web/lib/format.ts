import type { ProjectStatus } from "./api";

export const pipelineSteps: { key: ProjectStatus; label: string }[] = [
  { key: "queued", label: "Source" },
  { key: "transcribing", label: "Transcript" },
  { key: "scoring", label: "Selects" },
  { key: "rendering", label: "Render" },
  { key: "review", label: "Review" },
  { key: "approved", label: "Export" },
];

const statusOrder: Record<ProjectStatus, number> = {
  queued: 0,
  ingesting: 0,
  transcribing: 1,
  scoring: 2,
  ready: 2,
  rendering: 3,
  review: 4,
  approved: 5,
  failed: -1,
};

export function formatTime(seconds: number): string {
  const safe = Math.max(0, Math.floor(seconds));
  return `${Math.floor(safe / 60)}:${String(safe % 60).padStart(2, "0")}`;
}

export function activeStep(status: ProjectStatus): number {
  return statusOrder[status];
}

export function isProcessing(status: ProjectStatus): boolean {
  return ["queued", "ingesting", "transcribing", "scoring", "rendering"].includes(status);
}


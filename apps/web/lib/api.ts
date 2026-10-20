export type ProjectStatus =
  | "queued"
  | "ingesting"
  | "transcribing"
  | "scoring"
  | "ready"
  | "rendering"
  | "review"
  | "approved"
  | "failed";

export interface TranscriptSegment {
  id: string;
  start_seconds: number;
  end_seconds: number;
  text: string;
}

export interface Clip {
  id: string;
  rank: number;
  title: string;
  start_seconds: number;
  end_seconds: number;
  original_start_seconds: number;
  original_end_seconds: number;
  score: number;
  rationale: string;
  status: "candidate" | "rendering" | "rendered" | "approved" | "rejected";
  render_url: string | null;
  generation: number;
  series_id: string | null;
  series_index: number | null;
  series_count: number | null;
  caption_overrides: Record<string, string>;
  speaker_focus: "auto" | "left" | "center" | "right" | "duo" | "single" | "source";
  caption_position: "upper" | "middle" | "lower";
  caption_motion: "clean" | "pulse" | "kinetic";
  caption_font: "sans" | "mono" | "serif";
  caption_accent: string;
  caption_words_per_phrase: number;
  caption_size_percent: number;
  watermark_position: string;
  watermark_size_percent: number;
  edit_revision: number;
  is_edited: boolean;
  quality: {
    status: "not_checked" | "checking" | "passed" | "warning" | "failed";
    score: number | null;
    checked_at: string | null;
    checks: Array<{
      key: string;
      label: string;
      status: "pass" | "warn" | "fail";
      summary: string;
    }>;
  };
  hook_repair: {
    status: "not_checked" | "strong" | "recommended" | "applied";
    suggested_start: number;
    suggested_end: number;
    opening_note: string;
    ending_note: string;
  };
  covers: Array<{
    index: number;
    label: string;
    url: string;
    selected: boolean;
  }>;
  feedback: {
    decision: "approved" | "rejected" | null;
    reason: string | null;
    detail: string | null;
    recorded_at: string | null;
  };
  publication: {
    scheduled_for: string;
    cover_title: string;
    seo_caption: string;
    platforms: ProjectSummary["platform"][];
    status: "queued" | "published" | "failed";
  } | null;
}

export interface ProjectSummary {
  archived: boolean;
  id: string;
  title: string;
  status: ProjectStatus;
  duration_seconds: number | null;
  error: string | null;
  retryable: boolean;
  requested_clip_count: number;
  brand_folder_id: string | null;
  platform: "tiktok" | "reels" | "shorts" | "linkedin";
  watermark_url: string | null;
  watermark_position: string;
  watermark_size_percent: number;
  caption_motion: "clean" | "pulse" | "kinetic";
  caption_font: "sans" | "mono" | "serif";
  caption_accent: string;
  analysis_generation: number;
  duplicate_ideas_filtered: number;
  created_at: string;
}

export interface BrandFolder {
  archived: boolean;
  id: string;
  name: string;
  platform: ProjectSummary["platform"];
  caption_motion: Clip["caption_motion"];
  caption_font: Clip["caption_font"];
  caption_accent: string;
  watermark_url: string | null;
  watermark_position: string;
  watermark_size_percent: number;
  created_at: string;
}

export interface Project extends ProjectSummary {
  source_url: string | null;
  clips: Clip[];
  transcript: TranscriptSegment[];
}

export interface DirectorEdit {
  start_seconds: number;
  end_seconds: number;
  caption_overrides: Record<string, string>;
  speaker_focus: Clip["speaker_focus"];
  caption_position: Clip["caption_position"];
  caption_motion: Clip["caption_motion"];
  caption_font: Clip["caption_font"];
  caption_accent: string;
  caption_words_per_phrase: number;
  caption_size_percent: number;
  watermark_position: string;
  watermark_size_percent: number;
  apply_to_all: boolean;
}

export interface LayoutReport {
  width: number;
  height: number;
  scenes: Array<{
    start: number;
    end: number;
    kind: string;
    confidence: number;
    people: number;
    composition: "duo" | "single" | "source";
    tiles: number[][];
  }>;
  note: string;
}

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, { ...init, cache: "no-store" });
  if (!response.ok) {
    const payload = await response.json().catch(() => null);
    throw new Error(payload?.detail ?? `Request failed (${response.status})`);
  }
  return response.json() as Promise<T>;
}

export const api = {
  manageLibrary: (kind: "projects" | "folders", id: string, action: "archive" | "restore" | "delete") =>
    request<{ status: string }>(`/api/library/${kind}/${id}/${action}`, { method: "POST" }),
  layout: (projectId: string, clipId: string, start: number, end: number) =>
    request<LayoutReport>(`/api/projects/${projectId}/clips/${clipId}/layout?start_seconds=${start}&end_seconds=${end}`),
  brandFolders: () => request<BrandFolder[]>("/api/brand-folders"),
  createBrandFolder: (form: FormData) =>
    request<BrandFolder>("/api/brand-folders", { method: "POST", body: form }),
  projects: () => request<ProjectSummary[]>("/api/projects"),
  project: (id: string) => request<Project>(`/api/projects/${id}`),
  retry: (id: string) => request<Project>(`/api/projects/${id}/retry`, { method: "POST" }),
  reanalyze: (id: string) => request<Project>(`/api/projects/${id}/reanalyze`, { method: "POST" }),
  create: (form: FormData) => request<Project>("/api/projects", { method: "POST", body: form }),
  render: (projectId: string, clipId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/projects/${projectId}/clips/${clipId}/render`,
      { method: "POST" },
    ),
  renderAll: (projectId: string) =>
    request<{ job_id: string; status: string; clip_count: number }>(
      `/api/projects/${projectId}/render-all`,
      { method: "POST" },
    ),
  direct: (projectId: string, clipId: string, edit: DirectorEdit) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/director`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(edit),
    }),
  resetDirection: (projectId: string, clipId: string) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/director/reset`, {
      method: "POST",
    }),
  approve: (projectId: string, clipId: string, reason: string, detail: string) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/approve`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, detail }),
    }),
  reject: (projectId: string, clipId: string, reason: string, detail: string) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/reject`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason, detail }),
    }),
  inspect: (projectId: string, clipId: string) =>
    request<{ job_id: string; status: string }>(
      `/api/projects/${projectId}/clips/${clipId}/inspect`,
      { method: "POST" },
    ),
  applyHookRepair: (projectId: string, clipId: string) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/hook-repair`, {
      method: "POST",
    }),
  selectCover: (projectId: string, clipId: string, index: number) =>
    request<Project>(`/api/projects/${projectId}/clips/${clipId}/cover`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ index }),
    }),
};

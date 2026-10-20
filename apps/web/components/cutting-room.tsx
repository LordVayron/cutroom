"use client";

import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  API_URL,
  api,
  type BrandFolder,
  type Clip,
  type LayoutReport,
  type Project,
  type ProjectStatus,
  type ProjectSummary,
} from "@/lib/api";
import { activeStep, formatTime, isProcessing, pipelineSteps } from "@/lib/format";
import { ArrowIcon, DownloadIcon, PlusIcon } from "./icons";

function Waveform({ seed = 1 }: { seed?: number }) {
  return (
    <div className="waveform" aria-hidden="true">
      {Array.from({ length: 42 }, (_, index) => (
        <i
          key={index}
          style={{
            height: `${18 + ((index * 17 + seed * 11) % 52)}%`,
            animationDelay: `${index * 24}ms`,
          }}
        />
      ))}
    </div>
  );
}

function SourceForm({
  onCreated,
  folders,
  onCreateFolder,
  initialFolderId = "",
  compact = false,
}: {
  onCreated: (project: Project) => void;
  folders: BrandFolder[];
  onCreateFolder: () => void;
  initialFolderId?: string;
  compact?: boolean;
}) {
  const initialFolder = folders.find((folder) => folder.id === initialFolderId);
  const [mode, setMode] = useState<"url" | "file">("url");
  const [clipCount, setClipCount] = useState(10);
  const [captionMotion, setCaptionMotion] = useState<"clean" | "pulse" | "kinetic">(initialFolder?.caption_motion ?? "pulse");
  const [captionFont, setCaptionFont] = useState<"sans" | "mono" | "serif">(initialFolder?.caption_font ?? "sans");
  const [captionAccent, setCaptionAccent] = useState(initialFolder?.caption_accent ?? "#D8E25B");
  const [platform, setPlatform] = useState<ProjectSummary["platform"]>("tiktok");
  const [folderId, setFolderId] = useState(initialFolderId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const selectedFolder = folders.find((folder) => folder.id === folderId);
  const previewMotion = captionMotion;
  const previewFont = captionFont;
  const previewAccent = captionAccent;
  function chooseFolder(id: string) {
    const folder = folders.find((item) => item.id === id);
    setFolderId(id);
    setCaptionMotion(folder?.caption_motion ?? "pulse");
    setCaptionFont(folder?.caption_font ?? "sans");
    setCaptionAccent(folder?.caption_accent ?? "#D8E25B");
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    const form = new FormData(event.currentTarget);
    form.set("override_brand_captions", "true");
    if (mode === "url") form.delete("file");
    else form.delete("source_url");
    try {
      onCreated(await api.create(form));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not create project");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className={compact ? "source-form compact" : "source-form"} onSubmit={submit}>
      <div className="folder-assignment">
        <label>
          <span>Brand folder</span>
          <select name="brand_folder_id" value={folderId} onChange={(event) => chooseFolder(event.target.value)}>
            <option value="">One-off project</option>
            {folders.map((folder) => (
              <option key={folder.id} value={folder.id}>{folder.name} · {folder.platform}</option>
            ))}
          </select>
        </label>
        <button type="button" onClick={onCreateFolder}><PlusIcon /> New preset</button>
      </div>
      {selectedFolder && (
        <div className="preset-ticket">
          <b>{selectedFolder.name}</b>
          <span>{selectedFolder.platform} master</span>
          <small>{selectedFolder.watermark_url ? `PNG · ${selectedFolder.watermark_position}` : "No watermark"}</small>
        </div>
      )}
      <div className="source-tabs" role="tablist" aria-label="Source type">
        <button type="button" className={mode === "url" ? "active" : ""} onClick={() => setMode("url")}>
          Link
        </button>
        <button type="button" className={mode === "file" ? "active" : ""} onClick={() => setMode("file")}>
          Upload
        </button>
      </div>
      <label>
        <span>Project title</span>
        <input name="title" placeholder="The episode about creative courage" required maxLength={200} />
      </label>
      {mode === "url" ? (
        <label>
          <span>Video URL</span>
          <input name="source_url" type="url" placeholder="https://youtube.com/watch?v=…" required />
        </label>
      ) : (
        <label className="file-field">
          <span>Video file</span>
          <input name="file" type="file" accept="video/*" required />
          <b>Choose a video from your computer</b>
          <small>MP4, MOV, WebM · processed locally</small>
        </label>
      )}
      <label className="range-field">
        <span>How many clips?</span>
        <div className="range-readout">
          <input
            name="clip_count"
            type="range"
            min="1"
            max="20"
            value={clipCount}
            onChange={(event) => setClipCount(Number(event.target.value))}
          />
          <b>{String(clipCount).padStart(2, "0")}</b>
        </div>
        <small>Series parts count toward this total.</small>
      </label>
      {!selectedFolder && (
        <label>
          <span>Platform output</span>
          <select name="platform" value={platform} onChange={(event) => setPlatform(event.target.value as ProjectSummary["platform"])}>
            <option value="tiktok">TikTok · 9:16</option>
            <option value="reels">Instagram Reels · 9:16</option>
            <option value="shorts">YouTube Shorts · 9:16</option>
            <option value="linkedin">LinkedIn · 4:5</option>
          </select>
        </label>
      )}
      <fieldset className="caption-director">
        <legend>Caption direction</legend>
        <div className={`caption-preview ${previewMotion} font-${previewFont}`}>
          <small>Platform-safe type test</small>
          <strong>
            MAKE EVERY <em style={{ color: previewAccent }}>WORD</em> LAND.
          </strong>
          <i>{previewMotion} motion · {selectedFolder?.platform ?? platform} safe zone</i>
        </div>
        <div className="motion-options" aria-label="Caption motion">
          {([
            ["clean", "Clean", "Quiet"],
            ["pulse", "Pulse", "Alive"],
            ["kinetic", "Kinetic", "Bold"],
          ] as const).map(([value, label, note]) => (
            <label key={value} className={previewMotion === value ? "active" : ""}>
              <input
                type="radio"
                name="caption_motion"
                value={value}
                checked={previewMotion === value}
                onChange={() => setCaptionMotion(value)}
              />
              <b>{label}</b>
              <small>{note}</small>
            </label>
          ))}
        </div>
        <div className="caption-detail-grid">
          <label>
            <span>Typeface</span>
            <select
              name="caption_font"
              value={previewFont}
              onChange={(event) => setCaptionFont(event.target.value as "sans" | "mono" | "serif")}
            >
              <option value="sans">Modern Sans</option>
              <option value="mono">Cutroom Mono</option>
              <option value="serif">Editorial Serif</option>
            </select>
          </label>
          <label>
            <span>Accent</span>
            <span className="color-control">
              <input
                name="caption_accent"
                type="color"
                value={previewAccent}
                onChange={(event) => setCaptionAccent(event.target.value.toUpperCase())}
                aria-label="Caption accent color"
                onInput={(event) => setCaptionAccent(event.currentTarget.value.toUpperCase())}
              />
              <input
                key={previewAccent}
                type="text"
                defaultValue={previewAccent}
                aria-label="Caption accent hex"
                pattern="#[0-9A-Fa-f]{6}"
                maxLength={7}
                onBlur={(event) => {
                  if (/^#[0-9A-Fa-f]{6}$/.test(event.target.value)) setCaptionAccent(event.target.value.toUpperCase());
                }}
              />
            </span>
          </label>
        </div>
      </fieldset>
      {error && <p className="form-error">{error}</p>}
      <button className="primary-action" disabled={busy}>
        <span>{busy ? "Sending to the cutting room…" : "Find the moments"}</span>
        <ArrowIcon />
      </button>
    </form>
  );
}

const watermarkPositions = [
  "upper-left", "upper-center", "upper-right",
  "middle-left", "center", "middle-right",
  "lower-left", "lower-center", "lower-right",
] as const;

function BrandFolderModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: (folder: BrandFolder) => void;
}) {
  const [platform, setPlatform] = useState<ProjectSummary["platform"]>("tiktok");
  const [motion, setMotion] = useState<Clip["caption_motion"]>("pulse");
  const [font, setFont] = useState<Clip["caption_font"]>("sans");
  const [accent, setAccent] = useState("#D8E25B");
  const [position, setPosition] = useState("upper-right");
  const [size, setSize] = useState(18);
  const [watermarkPreview, setWatermarkPreview] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => () => {
    if (watermarkPreview) URL.revokeObjectURL(watermarkPreview);
  }, [watermarkPreview]);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      onCreated(await api.createBrandFolder(new FormData(event.currentTarget)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Could not save brand folder");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="brand-modal-backdrop" role="dialog" aria-modal="true" aria-label="Create brand folder">
      <form className="brand-folder-modal" onSubmit={submit}>
        <header>
          <div><p>Brand library / new folder</p><h2>Build once. Publish in character.</h2></div>
          <button type="button" onClick={onClose} aria-label="Close">×</button>
        </header>
        <div className="brand-folder-grid">
          <section className="brand-settings">
            <label><span>Folder name</span><input name="name" placeholder="Predictive History" required maxLength={120} /></label>
            <fieldset>
              <legend>Platform master</legend>
              <div className="platform-options">
                {(["tiktok", "reels", "shorts", "linkedin"] as const).map((value) => (
                  <label key={value} className={platform === value ? "active" : ""}>
                    <input type="radio" name="platform" value={value} checked={platform === value} onChange={() => setPlatform(value)} />
                    <b>{value}</b><small>{value === "linkedin" ? "4:5" : "9:16"}</small>
                  </label>
                ))}
              </div>
            </fieldset>
            <div className="brand-type-row">
              <label><span>Caption motion</span><select name="caption_motion" value={motion} onChange={(event) => setMotion(event.target.value as Clip["caption_motion"])}><option value="clean">Clean</option><option value="pulse">Pulse</option><option value="kinetic">Kinetic</option></select></label>
              <label><span>Typeface</span><select name="caption_font" value={font} onChange={(event) => setFont(event.target.value as Clip["caption_font"])}><option value="sans">Modern Sans</option><option value="mono">Cutroom Mono</option><option value="serif">Editorial Serif</option></select></label>
              <label><span>Accent</span><input name="caption_accent" type="color" value={accent} onChange={(event) => setAccent(event.target.value.toUpperCase())} /></label>
            </div>
            <label className="watermark-upload">
              <span>Watermark PNG</span>
              <input name="watermark" type="file" accept="image/png,.png" onChange={(event) => {
                const file = event.target.files?.[0];
                setWatermarkPreview(file ? URL.createObjectURL(file) : "");
              }} />
              <b>{watermarkPreview ? "PNG loaded — choose its position" : "Choose a transparent PNG"}</b>
              <small>Maximum 10 MB. Original transparency is preserved.</small>
            </label>
          </section>
          <section className="watermark-director">
            <div className={`watermark-canvas platform-${platform}`}>
              <span className="safe-frame" />
              {watermarkPreview ? <span className={`watermark-mark image ${position}`} role="img" aria-label="Watermark preview" style={{ width: `${size}%`, backgroundImage: `url(${watermarkPreview})` }} /> : <b className={`watermark-mark placeholder ${position}`} style={{ width: `${size}%` }}>YOUR PNG</b>}
              <i>{platform} safe canvas</i>
            </div>
            <div className="watermark-controls">
              <div><span>Placement</span><div className="position-grid">{watermarkPositions.map((value) => <label key={value} className={position === value ? "active" : ""} title={value}><input type="radio" name="watermark_position" value={value} checked={position === value} onChange={() => setPosition(value)} /><i /></label>)}</div></div>
              <label className="watermark-size"><span>Logo size</span><input name="watermark_size_percent" type="range" min="8" max="35" value={size} onChange={(event) => setSize(Number(event.target.value))} /><b>{size}%</b></label>
            </div>
            <div className={`caption-preview ${motion} font-${font}`}><small>Saved caption system</small><strong>MAKE EVERY <em style={{ color: accent }}>WORD</em> LAND.</strong><i>{motion} · {platform}</i></div>
          </section>
        </div>
        {error && <p className="form-error">{error}</p>}
        <footer><button type="button" onClick={onClose}>Cancel</button><button className="primary-action" disabled={busy}><span>{busy ? "Saving system…" : "Create brand folder"}</span><ArrowIcon /></button></footer>
      </form>
    </div>
  );
}

function StatusRail({ project }: { project: Project }) {
  const active = activeStep(project.status);
  return (
    <ol className="status-rail" aria-label="Project progress">
      {pipelineSteps.map((step, index) => (
        <li key={step.key} className={index < active ? "done" : index === active ? "active" : ""}>
          <span className="step-dot">{index < active ? "✓" : String(index + 1).padStart(2, "0")}</span>
          <span>{step.label}</span>
        </li>
      ))}
    </ol>
  );
}

type ProcessingStatus = Extract<ProjectStatus, "queued" | "ingesting" | "transcribing" | "scoring">;

const processingStages: { key: ProcessingStatus; label: string }[] = [
  { key: "queued", label: "On deck" },
  { key: "ingesting", label: "Frames" },
  { key: "transcribing", label: "Words" },
  { key: "scoring", label: "Moments" },
];

const processingCopy: Record<ProcessingStatus, { title: string; detail: string; activity: string }> = {
  queued: {
    title: "Your film is on deck.",
    detail: "The machine is reserving a clean workbench and preparing the source.",
    activity: "Warming the edit desk",
  },
  ingesting: {
    title: "Bringing every frame inside.",
    detail: "The source is entering the cutting room while its picture and sound are checked.",
    activity: "Mapping picture + sound",
  },
  transcribing: {
    title: "Listening word by word.",
    detail: "Every line is being pinned to an exact timecode so the eventual cuts land cleanly.",
    activity: "Building the timed transcript",
  },
  scoring: {
    title: "Finding moments with a pulse.",
    detail: "The full conversation is being read for ideas that hook, hold, and finish strong.",
    activity: "Ranking complete ideas",
  },
};

function ProcessingExperience({ status }: { status: ProcessingStatus }) {
  const stageIndex = processingStages.findIndex((stage) => stage.key === status);
  const copy = processingCopy[status];

  return (
    <section className={`processing-panel stage-${status}`} aria-live="polite" aria-busy="true">
      <div className="analysis-machine" aria-hidden="true">
        <div className="machine-reel">
          <span className="reel-core" />
          <i className="reel-hole hole-one" />
          <i className="reel-hole hole-two" />
          <i className="reel-hole hole-three" />
          <i className="reel-hole hole-four" />
        </div>
        <div className="machine-feed">
          <div className="film-strip">
            <span className="scan-head" />
            {Array.from({ length: 7 }, (_, frame) => (
              <div className="film-cell" key={frame}>
                {Array.from({ length: 5 }, (_, bar) => (
                  <i
                    key={bar}
                    style={{
                      height: `${24 + ((frame * 19 + bar * 13) % 62)}%`,
                      animationDelay: `${frame * 110 + bar * 45}ms`,
                    }}
                  />
                ))}
              </div>
            ))}
          </div>
          <div className="machine-readout">
            <span>TC 00:42:18:09</span>
            <b>{copy.activity}</b>
            <span>24 FPS / LIVE</span>
          </div>
        </div>
        <div className="machine-meter">
          {Array.from({ length: 12 }, (_, index) => (
            <i key={index} style={{ animationDelay: `${index * 90}ms` }} />
          ))}
        </div>
      </div>

      <div className="processing-copy">
        <p className="eyebrow"><span /> Machine room / active</p>
        <h2>{copy.title}</h2>
        <p>{copy.detail}</p>
      </div>

      <ol className="processing-ledger" aria-label="Analysis progress">
        {processingStages.map((stage, index) => (
          <li
            key={stage.key}
            className={index < stageIndex ? "complete" : index === stageIndex ? "current" : ""}
          >
            <span>{index < stageIndex ? "✓" : String(index + 1).padStart(2, "0")}</span>
            <b>{stage.label}</b>
          </li>
        ))}
      </ol>
      <small className="processing-note">You can leave this screen — the machine keeps working.</small>
    </section>
  );
}

function ClipCard({ clip, selected, onSelect }: { clip: Clip; selected: boolean; onSelect: () => void }) {
  return (
    <button className={`clip-card ${selected ? "selected" : ""} ${clip.status}`} onClick={onSelect}>
      <span className="rank">{String(clip.rank).padStart(2, "0")}</span>
      <span className="clip-copy">
        <strong>{clip.title}</strong>
        {clip.series_count && (
          <em className="series-badge">Series {clip.series_index}/{clip.series_count}</em>
        )}
        {clip.feedback.decision && (
          <em className={`feedback-badge ${clip.feedback.decision}`}>
            {clip.feedback.decision === "approved" ? "Taste match" : "Passed"}
          </em>
        )}
        <small>
          {formatTime(clip.start_seconds)}—{formatTime(clip.end_seconds)} · {clip.rationale}
        </small>
        <Waveform seed={clip.rank} />
      </span>
      <span className="score">
        <b>{Math.round(clip.score * 100)}</b>
        <small>HOOK</small>
      </span>
    </button>
  );
}

const approvalReasons = [
  ["strong_hook", "Strong hook"],
  ["surprising", "Surprising"],
  ["useful", "Useful"],
  ["emotional", "Emotional"],
  ["on_brand", "On brand"],
  ["other", "Other"],
] as const;

const rejectionReasons = [
  ["weak_hook", "Weak hook"],
  ["too_generic", "Too generic"],
  ["too_similar", "Seen before"],
  ["incomplete", "Incomplete"],
  ["poor_visual", "Poor visual"],
  ["not_on_brand", "Off brand"],
  ["other", "Other"],
] as const;

function DirectorModal({
  project,
  clip,
  onRefresh,
  onClose,
}: {
  project: Project;
  clip: Clip;
  onRefresh: (project: Project) => void;
  onClose: () => void;
}) {
  const previewRef = useRef<HTMLVideoElement>(null);
  const [start, setStart] = useState(clip.start_seconds);
  const [end, setEnd] = useState(clip.end_seconds);
  const [speakerFocus, setSpeakerFocus] = useState<Clip["speaker_focus"]>(clip.speaker_focus);
  const [captionPosition, setCaptionPosition] = useState<Clip["caption_position"]>(clip.caption_position);
  const [captionMotion, setCaptionMotion] = useState<Clip["caption_motion"]>(clip.caption_motion);
  const [captionFont, setCaptionFont] = useState<Clip["caption_font"]>(clip.caption_font);
  const [captionAccent, setCaptionAccent] = useState(clip.caption_accent);
  const [accentInput, setAccentInput] = useState(clip.caption_accent);
  const [captionWords, setCaptionWords] = useState(clip.caption_words_per_phrase);
  const [captionSize, setCaptionSize] = useState(clip.caption_size_percent);
  const [logoPosition, setLogoPosition] = useState(clip.watermark_position);
  const [logoSize, setLogoSize] = useState(clip.watermark_size_percent);
  const [applyAll, setApplyAll] = useState(false);
  const [overrides, setOverrides] = useState<Record<string, string>>(clip.caption_overrides);
  const [previewTime, setPreviewTime] = useState(clip.start_seconds);
  const [previewPlaying, setPreviewPlaying] = useState(false);
  const [activePanel, setActivePanel] = useState<"captions" | "logo" | "clip">("captions");
  const [layoutReport, setLayoutReport] = useState<LayoutReport | null>(null);
  const [layoutMessage, setLayoutMessage] = useState("");
  useEffect(() => {
    if (activePanel !== "clip") return;
    let cancelled = false;
    const timer = window.setTimeout(() => {
      setLayoutReport(null);
      setLayoutMessage("Analyzing camera cuts, people, and layout…");
      void api.layout(project.id, clip.id, start, end).then((report) => {
        if (!cancelled) { setLayoutReport(report); setLayoutMessage(""); }
      }).catch(() => {
        if (!cancelled) setLayoutMessage("Layout analysis is unavailable. Automatic uses a filled vertical crop.");
      });
    }, 400);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [activePanel, project.id, clip.id, start, end]);
  const [busy, setBusy] = useState<"save" | "render" | "reset" | "">("");
  const [error, setError] = useState("");
  const sourceDuration = project.duration_seconds ?? Math.max(end, clip.original_end_seconds);
  const transcript = useMemo(
    () => project.transcript.filter((segment) => segment.start_seconds < end && segment.end_seconds > start),
    [project.transcript, start, end],
  );
  const activePreviewSegment = transcript.find(
    (segment) => segment.start_seconds <= previewTime && segment.end_seconds >= previewTime,
  ) ?? transcript.find((segment) => segment.start_seconds >= previewTime) ?? transcript[0];
  const previewText = activePreviewSegment
    ? (overrides[activePreviewSegment.id] ?? activePreviewSegment.text)
    : "Caption preview";
  const allPreviewWords = previewText.split(/\s+/).filter(Boolean);
  const previewProgress = activePreviewSegment ? Math.max(0, Math.min(0.999,
    (previewTime - activePreviewSegment.start_seconds) /
    Math.max(0.1, activePreviewSegment.end_seconds - activePreviewSegment.start_seconds))) : 0;
  const activeWord = Math.floor(previewProgress * allPreviewWords.length);
  const phraseStart = Math.floor(activeWord / captionWords) * captionWords;
  const previewWords = allPreviewWords.slice(phraseStart, phraseStart + captionWords);
  const objectPosition = speakerFocus === "left"
    ? "left center"
    : speakerFocus === "right"
      ? "right center"
      : "center center";

  function seekPreview() {
    if (!previewRef.current) return;
    if (!previewRef.current.paused) {
      previewRef.current.pause();
      return;
    }
    if (previewRef.current.currentTime < start || previewRef.current.currentTime >= end) {
      previewRef.current.currentTime = start;
      setPreviewTime(start);
    }
    void previewRef.current.play();
  }

  function setSubtitle(segmentId: string, original: string, value: string) {
    setOverrides((current) => {
      const next = { ...current };
      if (value.trim() === original.trim()) delete next[segmentId];
      else next[segmentId] = value;
      return next;
    });
  }

  async function save(renderAfter: boolean) {
    setBusy(renderAfter ? "render" : "save");
    setError("");
    try {
      const updated = await api.direct(project.id, clip.id, {
        start_seconds: start,
        end_seconds: end,
        speaker_focus: speakerFocus,
        caption_position: captionPosition,
        caption_motion: captionMotion,
        caption_font: captionFont,
        caption_accent: captionAccent,
        caption_words_per_phrase: captionWords,
        caption_overrides: overrides,
        caption_size_percent: captionSize,
        watermark_position: logoPosition,
        watermark_size_percent: logoSize,
        apply_to_all: applyAll,
      });
      if (renderAfter || applyAll) {
        const accepted = applyAll
          ? await api.renderAll(project.id)
          : await api.render(project.id, clip.id);
        onRefresh(accepted.status === "done" ? updated : { ...updated, status: "rendering" });
      } else {
        onRefresh(updated);
      }
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Director changes could not be saved");
    } finally {
      setBusy("");
    }
  }

  async function reset() {
    setBusy("reset");
    setError("");
    try {
      onRefresh(await api.resetDirection(project.id, clip.id));
      onClose();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The original cut could not be restored");
    } finally {
      setBusy("");
    }
  }

  return (
    <div className="director-backdrop" role="presentation" onMouseDown={onClose}>
      <section
        className="director-modal"
        role="dialog"
        aria-modal="true"
        aria-label={`Direct ${clip.title}`}
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="director-header">
          <div>
            <p className="eyebrow">Director mode / Cut {String(clip.rank).padStart(2, "0")}</p>
            <h2>{clip.title}</h2>
          </div>
          <div className="director-header-meta">
            <span>{(end - start).toFixed(1)} sec</span>
            {clip.is_edited && <b>Edited</b>}
            <button onClick={onClose} aria-label="Close Director Mode">×</button>
          </div>
        </header>

        <div className="director-grid">
          <aside className="director-monitor">
            <div className="director-monitor-heading">
              <span>Live preview</span>
              <small>Style preview</small>
            </div>
            <div className={`director-phone platform-${project.platform}`}>
              <video
                ref={previewRef}
                src={`${API_URL}/api/projects/${project.id}/source`}
                playsInline
                preload="metadata"
                onPlay={() => setPreviewPlaying(true)}
                onPause={() => setPreviewPlaying(false)}
                style={{ objectPosition, objectFit: speakerFocus === "source" ? "contain" : "cover" }}
                onLoadedMetadata={(event) => {
                  event.currentTarget.currentTime = start;
                  setPreviewTime(start);
                }}
                onTimeUpdate={(event) => {
                  setPreviewTime(event.currentTarget.currentTime);
                  if (event.currentTarget.currentTime >= end) event.currentTarget.pause();
                }}
              />
              {project.watermark_url && <span role="img" aria-label="Logo preview" className={`watermark-mark image ${logoPosition}`} style={{ width: `${logoSize}%`, backgroundImage: `url(${API_URL}${project.watermark_url})` }} />}
              <div style={{ fontSize: `${(captionFont === "mono" ? 15.5 : captionFont === "serif" ? 17.5 : 18) * captionSize / 100}px` }} className={"director-caption " + captionPosition + " " + captionMotion + " font-" + captionFont}>
                {previewWords.map((word, index) => (
                  <span
                    key={word + "-" + index}
                    className={index === activeWord - phraseStart ? "active-word" : ""}
                    style={index === activeWord - phraseStart ? { color: captionAccent } : undefined}
                  >
                    {word}{" "}
                  </span>
                ))}
              </div>
            </div>
            <button className="cue-button" type="button" onClick={seekPreview}>
              {previewPlaying ? "Ⅱ Pause preview" : "▶ Play this clip"}
            </button>
            <label className="director-playhead"><span>Preview position</span><input aria-label="Preview position" type="range" min="0" max={Math.max(0.1, end - start)} step="0.1" value={Math.max(0, Math.min(end - start, previewTime - start))} onChange={(event) => { const time = start + Number(event.target.value); if (previewRef.current) previewRef.current.currentTime = time; setPreviewTime(time); }} /><output>{formatTime(Math.max(0, previewTime - start))} / {formatTime(end - start)}</output></label>
            <p>Try the look here. Caption timing, speaker tracking, and silence cuts are finalized when you render.</p>
            <label className="director-apply-all">
              <input type="checkbox" role="switch" checked={applyAll} onChange={(event) => setApplyAll(event.target.checked)} />
              <span><strong>Apply to all clips</strong><small>{applyAll ? "Save will update and render all clips in this project." : "Only this clip will change."}</small></span>
            </label>
            {applyAll && <p>Shares captions, logo, and framing. Each clip keeps its own trim and words. Future clips in this project use this look too.</p>}
          </aside>

          <div className="director-controls">
            <nav className="director-tabs" aria-label="Director Mode tools">
              <button type="button" className={activePanel === "captions" ? "active" : ""} aria-pressed={activePanel === "captions"} onClick={() => setActivePanel("captions")}>
                <span>01</span><b>Subtitles</b><small>Style, size & words</small>
              </button>
              <button type="button" className={activePanel === "logo" ? "active" : ""} aria-pressed={activePanel === "logo"} onClick={() => setActivePanel("logo")}>
                <span>02</span><b>Logo</b><small>Position & size</small>
              </button>
              <button type="button" className={activePanel === "clip" ? "active" : ""} aria-pressed={activePanel === "clip"} onClick={() => setActivePanel("clip")}>
                <span>03</span><b>Video</b><small>Trim & camera</small>
              </button>
            </nav>

            {activePanel === "captions" ? (
              <div className="director-panel-body">
                <div className="director-intro">
                  <p className="eyebrow">Subtitle settings</p>
                  <h3>Make it easy to read.</h3>
                  <p>Set the size and words per line, then choose a style. Watch the preview as you adjust.</p>
                </div>

                <label className="director-size-control">
                  <span>Subtitle size</span><output>{captionSize}%</output>
                  <input aria-label="Subtitle size" type="range" min="60" max="140" step="5" value={captionSize} onChange={(event) => setCaptionSize(Number(event.target.value))} />
                  <small>Smaller</small><small>Larger</small>
                </label>

                <section className="director-control-block">
                  <div className="director-section-title"><span>Animation</span><small>Preview updates instantly</small></div>
                  <div className="motion-card-grid" role="group" aria-label="Caption animation">
                    {([["clean", "Clean", "Steady and quiet"], ["pulse", "Pulse", "Lift the spoken word"], ["kinetic", "Kinetic", "Fast and expressive"]] as const).map(([value, label, note]) => (
                      <button key={value} type="button" className={captionMotion === value ? "active" : ""} aria-pressed={captionMotion === value} onClick={() => setCaptionMotion(value)}>
                        <i className={"motion-sample " + value}>Aa</i><b>{label}</b><small>{note}</small>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="caption-tuning-grid">
                  <label className="words-control">
                    <span>Words on screen</span><b>{captionWords}</b>
                    <input type="range" min="1" max="8" value={captionWords} onChange={(event) => setCaptionWords(Number(event.target.value))} />
                    <small>Fewer feels faster. More is easier to read.</small>
                  </label>
                  <fieldset className="accent-control">
                    <legend>Accent color</legend>
                    <div>
                      <input type="color" value={captionAccent} onChange={(event) => { const color = event.target.value.toUpperCase(); setCaptionAccent(color); setAccentInput(color); }} aria-label="Choose caption accent color" />
                      <input type="text" value={accentInput} pattern="#[0-9A-Fa-f]{6}" maxLength={7} onChange={(event) => { const color = event.target.value.toUpperCase(); setAccentInput(color); if (/^#[0-9A-F]{6}$/.test(color)) setCaptionAccent(color); }} aria-label="Caption accent hex color" />
                    </div>
                    <div className="accent-swatches" aria-label="Accent presets">
                      {["#D8E25B", "#FDBD4E", "#FF4A36", "#56D6FF", "#FFFFFF"].map((color) => (
                        <button key={color} type="button" style={{ background: color }} aria-label={"Use " + color} aria-pressed={captionAccent === color} onClick={() => { setCaptionAccent(color); setAccentInput(color); }} />
                      ))}
                    </div>
                  </fieldset>
                </section>

                <section className="director-control-block compact-control-block">
                  <div className="director-section-title"><span>Typeface</span><small>Choose the voice of the clip</small></div>
                  <div className="font-options" role="group" aria-label="Caption font">
                    {(["sans", "mono", "serif"] as const).map((value) => (
                      <button key={value} type="button" className={(captionFont === value ? "active " : "") + "font-" + value} aria-pressed={captionFont === value} onClick={() => setCaptionFont(value)}>
                        <b>Ag</b><span>{value === "sans" ? "Modern" : value === "mono" ? "Typewriter" : "Editorial"}</span>
                      </button>
                    ))}
                  </div>
                </section>

                <section className="director-control-block compact-control-block">
                  <div className="director-section-title"><span>Position</span><small>Every option stays in the safe zone</small></div>
                  <div className="position-options" role="group" aria-label="Caption position">
                    {(["upper", "middle", "lower"] as const).map((value) => (
                      <button key={value} type="button" className={captionPosition === value ? "active" : ""} aria-pressed={captionPosition === value} onClick={() => setCaptionPosition(value)}>
                        <i><span className={value} /></i><b>{value === "upper" ? "Top" : value === "middle" ? "Center" : "Bottom"}</b>
                      </button>
                    ))}
                  </div>
                </section>

                <details className="director-control-block subtitle-block">
                  <summary>Edit subtitle text · {transcript.length} lines</summary>
                  <div className="subtitle-editor">
                    {transcript.map((segment) => (
                      <label key={segment.id} className={segment.id in overrides ? "changed" : ""}>
                        <time>{formatTime(segment.start_seconds)}</time>
                        <textarea rows={2} maxLength={500} value={overrides[segment.id] ?? segment.text} onChange={(event) => setSubtitle(segment.id, segment.text, event.target.value)} />
                      </label>
                    ))}
                  </div>
                </details>
              </div>
            ) : activePanel === "logo" ? (
              <div className="director-panel-body director-logo-panel">
                <div className="director-intro"><p className="eyebrow">Brand placement</p><h3>Put your logo in place.</h3><p>Choose a position on the grid, then adjust its size. Your brand folder stays unchanged.</p></div>
                {project.watermark_url ? <>
                  <fieldset className="director-logo-grid"><legend>Logo position</legend>
                    {watermarkPositions.map((position) => <button key={position} type="button" aria-pressed={logoPosition === position} className={logoPosition === position ? "active" : ""} onClick={() => setLogoPosition(position)}><span>{position === "center" ? "Center" : position.replace("upper", "Top").replace("lower", "Bottom").replace("middle", "Middle").replace("-", " ")}</span></button>)}
                  </fieldset>
                  <label className="director-size-control"><span>Logo size</span><output>{logoSize}%</output><input aria-label="Logo size" type="range" min="8" max="35" value={logoSize} onChange={(event) => setLogoSize(Number(event.target.value))} /><small>Smaller</small><small>Larger</small></label>
                </> : <p className="director-empty-logo">This project has no logo. Create a project from a brand folder with a PNG logo to use these controls.</p>}
              </div>
            ) : (
              <div className="director-panel-body">
                <div className="director-intro">
                  <p className="eyebrow">Cut & camera</p>
                  <h3>Shape the moment.</h3>
                  <p>Fine-tune the start and finish, then decide who stays in frame.</p>
                </div>
                <section className="director-control-block trim-block">
                  <div className="director-section-title"><span>Start & finish</span><small>3–120 seconds</small></div>
                  <div className="trim-readouts">
                    <label><span>IN</span><input type="number" min="0" max={Math.max(0, end - 3)} step="0.1" value={start} onChange={(event) => setStart(Math.min(Number(event.target.value), end - 3))} /><small>{formatTime(start)}</small></label>
                    <i>→</i>
                    <label><span>OUT</span><input type="number" min={start + 3} max={sourceDuration} step="0.1" value={end} onChange={(event) => setEnd(Math.max(Number(event.target.value), start + 3))} /><small>{formatTime(end)}</small></label>
                  </div>
                  <label className="director-range"><span>Move IN</span><input type="range" min="0" max={Math.max(0, end - 3)} step="0.1" value={start} onChange={(event) => setStart(Number(event.target.value))} /></label>
                  <label className="director-range"><span>Move OUT</span><input type="range" min={Math.min(sourceDuration, start + 3)} max={sourceDuration} step="0.1" value={end} onChange={(event) => setEnd(Number(event.target.value))} /></label>
                </section>
                <section className="director-control-block">
                  <div className="director-section-title"><span>Composition</span><small>Automatic adapts to each scene</small></div>
                  <div className="layout-report" aria-live="polite">
                    <h4>Source layout analysis</h4>
                    {layoutMessage && <p>{layoutMessage}</p>}
                    {layoutReport && <>
                      <p>{layoutReport.scenes.length} scene{layoutReport.scenes.length === 1 ? "" : "s"} checked. Stacking requires separate camera tiles with two visible people.</p>
                      <ul>{layoutReport.scenes.map((scene, index) => <li key={index}>
                        <time>{formatTime(scene.start)}–{formatTime(scene.end)}</time>
                        <span>{scene.kind === "camera_grid" ? `${scene.people}-person camera grid` : scene.kind === "single_speaker" ? "Single speaker" : scene.kind === "shared_camera" ? "People sharing one camera" : scene.kind === "presentation" ? "Presentation or screen share" : "Scene / graphics / uncertain"}</span>
                        <b>{scene.composition === "duo" ? "Verified stack" : "Filled speaker crop"}</b>
                      </li>)}</ul>
                      <small>Automatic fills every frame. Verified camera grids use two people; uncertain shots use a speaker crop, never empty bars. Full frame is a manual override with a blurred video backdrop.</small>
                    </>}
                  </div>
                  <div className="speaker-card-grid" role="group" aria-label="Speaker framing">
                    {(["auto", "source", "single", "duo", "left", "center", "right"] as const).map((value) => (
                      <button key={value} type="button" className={speakerFocus === value ? "active" : ""} aria-pressed={speakerFocus === value} onClick={() => setSpeakerFocus(value)}>
                        <i className={value}><span /></i><b>{value === "duo" ? "Verified Duo" : value === "source" ? "Full frame" : value === "single" ? "Single speaker" : value === "auto" ? "Automatic" : value}</b>
                      </button>
                    ))}
                  </div>
                </section>
              </div>
            )}
          </div>
        </div>

        {error && <p className="form-error director-error">{error}</p>}
        <footer className="director-footer">
          <button type="button" className="reset-direction" onClick={() => void reset()} disabled={Boolean(busy) || !clip.is_edited}>
            {busy === "reset" ? "Restoring…" : "Reset this clip"}
          </button>
          <div>
            {!applyAll && <button type="button" onClick={() => void save(false)} disabled={Boolean(busy)}>
              {busy === "save" ? "Saving…" : applyAll ? "Apply & render all" : "Save changes"}
            </button>}
            <button type="button" className="director-render" onClick={() => void save(true)} disabled={Boolean(busy)}>
              {busy === "render" ? "Sending…" : applyAll ? "Apply & render all" : "Save + render"} <ArrowIcon />
            </button>
          </div>
        </footer>
      </section>
    </div>
  );
}

function ProjectWorkspace({
  project,
  selectedClip,
  onSelectClip,
  onRefresh,
  onChooseSource,
}: {
  project: Project;
  selectedClip?: Clip;
  onSelectClip: (id: string) => void;
  onRefresh: (project: Project) => void;
  onChooseSource: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [inspecting, setInspecting] = useState(false);
  const [creativeBusy, setCreativeBusy] = useState<"repair" | null>(null);
  const [error, setError] = useState("");
  const [showDirector, setShowDirector] = useState(false);
  const [decisionMode, setDecisionMode] = useState<"approved" | "rejected" | null>(null);
  const [decisionReason, setDecisionReason] = useState("");
  const [decisionDetail, setDecisionDetail] = useState("");
  const transcript = useMemo(() => {
    if (!selectedClip) return project.transcript;
    return project.transcript.filter(
      (segment) =>
        segment.start_seconds < selectedClip.end_seconds && segment.end_seconds > selectedClip.start_seconds,
    );
  }, [project.transcript, selectedClip]);
  const previewStatus = selectedClip?.status === "rendered" ? "review" : selectedClip?.status ?? project.status;

  async function render() {
    if (!selectedClip) return;
    setBusy(true);
    setError("");
    try {
      await api.render(project.id, selectedClip.id);
      onRefresh({ ...project, status: "rendering" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Render could not start");
    } finally {
      setBusy(false);
    }
  }

  async function renderAll() {
    setBusy(true);
    setError("");
    try {
      const accepted = await api.renderAll(project.id);
      if (accepted.status === "done") onRefresh(await api.project(project.id));
      else onRefresh({ ...project, status: "rendering" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Batch render could not start");
    } finally {
      setBusy(false);
    }
  }

  async function saveDecision() {
    if (!selectedClip) return;
    if (!decisionMode || !decisionReason) return;
    setBusy(true);
    setError("");
    try {
      const updated = decisionMode === "approved"
        ? await api.approve(project.id, selectedClip.id, decisionReason, decisionDetail)
        : await api.reject(project.id, selectedClip.id, decisionReason, decisionDetail);
      onRefresh(updated);
      setDecisionMode(null);
      setDecisionReason("");
      setDecisionDetail("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Editorial decision could not be saved");
    } finally {
      setBusy(false);
    }
  }

  function openDecision(mode: "approved" | "rejected") {
    setDecisionMode(mode);
    setDecisionReason("");
    setDecisionDetail("");
    setError("");
  }

  function selectClip(id: string) {
    setDecisionMode(null);
    setDecisionReason("");
    setDecisionDetail("");
    onSelectClip(id);
  }

  async function inspect() {
    if (!selectedClip) return;
    setInspecting(true);
    setError("");
    try {
      await api.inspect(project.id, selectedClip.id);
      onRefresh({
        ...project,
        clips: project.clips.map((clip) =>
          clip.id === selectedClip.id
            ? { ...clip, quality: { ...clip.quality, status: "checking", score: null } }
            : clip,
        ),
      });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Quality inspection could not start");
    } finally {
      setInspecting(false);
    }
  }

  async function applyHookRepair() {
    if (!selectedClip) return;
    setCreativeBusy("repair");
    setError("");
    try {
      const updated = await api.applyHookRepair(project.id, selectedClip.id);
      await api.render(project.id, selectedClip.id);
      onRefresh({ ...updated, status: "rendering" });
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Hook repair could not be applied");
    } finally {
      setCreativeBusy(null);
    }
  }


  if (project.status === "failed") {
    async function retry() {
      setBusy(true);
      setError("");
      try {
        onRefresh(await api.retry(project.id));
      } catch (caught) {
        setError(caught instanceof Error ? caught.message : "Retry could not start");
      } finally {
        setBusy(false);
      }
    }
    return (
      <section className="failure-panel">
        <span>Pipeline stopped</span>
        <h2>The source needs a second look.</h2>
        <p>{project.error ?? "The worker exhausted its retry budget."}</p>
        {error && <p className="form-error">{error}</p>}
        {project.retryable ? (
          <button className="primary-action retry-action" onClick={retry} disabled={busy}>
            <span>{busy ? "Requeuing…" : "Retry failed step"}</span>
            <ArrowIcon />
          </button>
        ) : (
          <button className="primary-action retry-action" onClick={onChooseSource}>
            <span>Choose another source</span>
            <ArrowIcon />
          </button>
        )}
      </section>
    );
  }

  if (
    project.clips.length === 0 ||
    ["queued", "ingesting", "transcribing", "scoring"].includes(project.status)
  ) {
    return <ProcessingExperience status={project.status as ProcessingStatus} />;
  }

  return (
    <div className="workspace-grid">
      <section className="selects-panel">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">Ranked selects</p>
            <h2>{project.clips.length} moments with a pulse.</h2>
            {project.duplicate_ideas_filtered > 0 && (
              <p className="duplicate-ledger">
                <b>{project.duplicate_ideas_filtered}</b> repeated concept{project.duplicate_ideas_filtered === 1 ? "" : "s"} held back by library memory
              </p>
            )}
          </div>
          <div className="selects-actions">
            <button onClick={() => void renderAll()} disabled={busy || project.status === "rendering"}>
              Render all
            </button>
            <span className="count-mark">{String(project.clips.length).padStart(2, "0")}</span>
          </div>
        </div>
        <div className="clip-list">
          {project.clips.map((clip) => (
            <ClipCard
              key={clip.id}
              clip={clip}
              selected={clip.id === selectedClip?.id}
              onSelect={() => selectClip(clip.id)}
            />
          ))}
        </div>
        <div className="transcript-panel">
          <div className="transcript-title">
            <span>Transcript / selected range</span>
            <small>{transcript.length} passages</small>
          </div>
          <div className="transcript-copy">
            {transcript.map((segment) => (
              <p key={segment.id}>
                <time>{formatTime(segment.start_seconds)}</time>
                <span>{segment.text}</span>
              </p>
            ))}
          </div>
        </div>
      </section>

      <aside className="preview-panel">
        <div className="preview-heading">
          <span>{project.platform === "linkedin" ? "4:5" : "9:16"} proof · {project.platform}</span>
          <span className={`status-pill ${previewStatus}`}>{previewStatus}</span>
        </div>
        <div className={`phone-frame ${project.platform === "linkedin" ? "platform-linkedin" : ""}`}>
          {selectedClip?.render_url ? (
            <video
              key={`${selectedClip.id}:${selectedClip.edit_revision}`}
              src={`${API_URL}${selectedClip.render_url}?v=${selectedClip.edit_revision}`}
              controls
              playsInline
              preload="metadata"
            />
          ) : (
            <div className="preview-placeholder">
              <span className="frame-corner top-left" />
              <span className="frame-corner top-right" />
              <span className="frame-corner bottom-left" />
              <span className="frame-corner bottom-right" />
              <p>FRAME</p>
              <b>{selectedClip ? selectedClip.title : "Choose a select"}</b>
              <small>{project.platform === "linkedin" ? "1080 × 1350" : "1080 × 1920"}</small>
            </div>
          )}
        </div>
        {selectedClip && (
          <section className={`creative-assist ${selectedClip.hook_repair.status}`}>
            <header>
              <div>
                <span>Hook Repair</span>
                <strong>
                  {selectedClip.hook_repair.status === "recommended"
                    ? "A tighter cut is ready"
                    : selectedClip.hook_repair.status === "strong"
                      ? "Opening and ending are strong"
                      : selectedClip.hook_repair.status === "applied"
                        ? "Repair applied"
                        : "Analyzes on next render"}
                </strong>
              </div>
              {selectedClip.hook_repair.status === "recommended" && <b>REPAIR</b>}
            </header>
            {selectedClip.hook_repair.status !== "not_checked" && (
              <div className="hook-notes">
                <p><i>IN</i>{selectedClip.hook_repair.opening_note}</p>
                <p><i>OUT</i>{selectedClip.hook_repair.ending_note}</p>
              </div>
            )}
            {selectedClip.hook_repair.status === "recommended" && (
              <button
                type="button"
                onClick={() => void applyHookRepair()}
                disabled={creativeBusy !== null || project.status === "rendering"}
              >
                <span>
                  {formatTime(selectedClip.start_seconds)} → {formatTime(selectedClip.hook_repair.suggested_start)}
                  {" · "}
                  {formatTime(selectedClip.end_seconds)} → {formatTime(selectedClip.hook_repair.suggested_end)}
                </span>
                <b>{creativeBusy === "repair" ? "Applying…" : "Apply + render"}</b>
              </button>
            )}
          </section>
        )}
        {selectedClip?.render_url && (
          <section className={`quality-inspector ${selectedClip.quality.status}`}>
            <header>
              <div>
                <span>Automatic QC</span>
                <strong>
                  {selectedClip.quality.status === "not_checked"
                    ? "Not inspected"
                    : selectedClip.quality.status === "checking"
                      ? "Inspecting final file…"
                      : selectedClip.quality.status}
                </strong>
              </div>
              {selectedClip.quality.score !== null && <b>{selectedClip.quality.score}</b>}
            </header>
            {selectedClip.quality.checks.length > 0 && (
              <div className="quality-checks">
                {selectedClip.quality.checks.map((check) => (
                  <details key={check.key}>
                    <summary>
                      <i className={check.status} />
                      <span>{check.label}</span>
                      <em>{check.status}</em>
                    </summary>
                    <p>{check.summary}</p>
                  </details>
                ))}
              </div>
            )}
            {selectedClip.quality.status !== "checking" && (
              <button type="button" onClick={() => void inspect()} disabled={inspecting}>
                {selectedClip.quality.status === "not_checked" ? "Run inspector" : "Inspect again"}
              </button>
            )}
          </section>
        )}
        {error && <p className="form-error">{error}</p>}
        <div className="review-actions">
          <button
            className="director-launch"
            type="button"
            onClick={() => setShowDirector(true)}
            disabled={!selectedClip || project.status === "rendering" || selectedClip.status === "rejected"}
          >
            <span>{selectedClip?.is_edited ? "Continue directing" : "Director mode"}</span>
            <b>Trim · Frame · Captions</b>
          </button>
          {!selectedClip?.render_url && selectedClip?.status !== "rejected" && (
            <button className="primary-action" onClick={render} disabled={!selectedClip || busy || project.status === "rendering"}>
              <span>{project.status === "rendering" ? "Rendering…" : "Render this cut"}</span>
              <ArrowIcon />
            </button>
          )}
          {selectedClip?.status === "rendered" && selectedClip.render_url && (
            <div className="decision-launchers">
              <button
                className="primary-action"
                onClick={() => openDecision("approved")}
                disabled={busy || !["passed", "warning"].includes(selectedClip.quality.status)}
              >
                <span>Approve final</span>
                <ArrowIcon />
              </button>
              <button className="reject-action" onClick={() => openDecision("rejected")} disabled={busy}>
                Pass on this clip
              </button>
            </div>
          )}
          {selectedClip?.status === "candidate" && (
            <button className="reject-action candidate-reject" onClick={() => openDecision("rejected")} disabled={busy}>
              Pass without rendering
            </button>
          )}
          {decisionMode && selectedClip && (
            <section className={`taste-decision ${decisionMode}`}>
              <header>
                <div>
                  <span>Taste memory / {decisionMode === "approved" ? "keep" : "pass"}</span>
                  <strong>{decisionMode === "approved" ? "Why does this work?" : "Why is this not the one?"}</strong>
                </div>
                <button type="button" onClick={() => setDecisionMode(null)} aria-label="Close feedback">×</button>
              </header>
              <div className="taste-reasons">
                {(decisionMode === "approved" ? approvalReasons : rejectionReasons).map(([value, label]) => (
                  <button
                    type="button"
                    key={value}
                    className={decisionReason === value ? "selected" : ""}
                    onClick={() => setDecisionReason(value)}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <textarea
                value={decisionDetail}
                onChange={(event) => setDecisionDetail(event.target.value)}
                maxLength={500}
                placeholder="Optional note — what should the editor remember?"
              />
              <footer>
                <small>This becomes a signal for every future podcast.</small>
                <button type="button" onClick={() => void saveDecision()} disabled={busy || !decisionReason}>
                  {busy ? "Learning…" : decisionMode === "approved" ? "Approve + teach" : "Pass + teach"}
                </button>
              </footer>
            </section>
          )}
          {selectedClip?.status === "rejected" && (
            <section className="taste-verdict rejected">
              <span>Passed / taste memory saved</span>
              <strong>{selectedClip.feedback.reason?.replaceAll("_", " ")}</strong>
              {selectedClip.feedback.detail && <p>{selectedClip.feedback.detail}</p>}
              <small>Re-analyze when you want a replacement idea.</small>
            </section>
          )}
          {selectedClip?.status === "approved" && (
            <a className="primary-action" href={`${API_URL}/api/clips/${selectedClip.id}/export`}>
              <span>Export MP4</span>
              <DownloadIcon />
            </a>
          )}
          <p>Every keep and pass sharpens the next edit across your library.</p>
        </div>
      </aside>
      {showDirector && selectedClip && (
        <DirectorModal
          project={project}
          clip={selectedClip}
          onRefresh={onRefresh}
          onClose={() => setShowDirector(false)}
        />
      )}
    </div>
  );
}

export function CuttingRoom() {
  const [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [folders, setFolders] = useState<BrandFolder[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [selectedClipId, setSelectedClipId] = useState<string | null>(null);
  const [showNew, setShowNew] = useState(false);
  const [showBrandFolder, setShowBrandFolder] = useState(false);
  const [newFolderId, setNewFolderId] = useState("");
  const [reanalyzing, setReanalyzing] = useState(false);
  const [connectionError, setConnectionError] = useState("");
  const [showArchived, setShowArchived] = useState(false);
  const [libraryBusy, setLibraryBusy] = useState(false);
  const activeFolders = folders.filter((folder) => !folder.archived);
  const visibleFolders = folders.filter((folder) => folder.archived === showArchived);
  const visibleProjects = projects.filter((item) => item.archived === showArchived && (showArchived || !folders.find((folder) => folder.id === item.brand_folder_id)?.archived));

  async function manageLibrary(kind: "projects" | "folders", id: string, action: "archive" | "restore" | "delete", name: string) {
    if (action === "delete" && !window.confirm(kind === "folders" ? `Remove “${name}”? Its films will move to Unfiled films. Media is retained on disk.` : `Remove “${name}” from the library? Media is retained on disk.`)) return;
    setLibraryBusy(true);
    try {
      await api.manageLibrary(kind, id, action);
      const [items, brands] = await Promise.all([api.projects(), api.brandFolders()]);
      setProjects(items);
      setFolders(brands);
      if (kind === "projects" && project?.id === id && action !== "restore") {
        setProject(null);
        setSelectedClipId(null);
      }
      setConnectionError("");
    } catch (caught) {
      setConnectionError(caught instanceof Error ? caught.message : "Library change failed");
    } finally { setLibraryBusy(false); }
  }

  function libraryActions(kind: "projects" | "folders", id: string, name: string, archived: boolean) {
    return <details className="library-actions" name="library-options"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.removeAttribute("open"); }}
      onKeyDown={(event) => { if (event.key === "Escape") { event.currentTarget.removeAttribute("open"); event.currentTarget.querySelector("summary")?.focus(); } }}>
      <summary aria-label={`More options for ${name}`} title="More options">⋯</summary>
      <div className="library-action-menu">
        <button disabled={libraryBusy} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); void manageLibrary(kind, id, archived ? "restore" : "archive", name); }}>{archived ? "Restore" : "Archive"}</button>
        <button disabled={libraryBusy} onClick={(event) => { event.currentTarget.closest("details")?.removeAttribute("open"); void manageLibrary(kind, id, "delete", name); }}>Delete</button>
      </div>
    </details>;
  }

  function projectRow(item: ProjectSummary, index: number) {
    return <div className="library-project" key={item.id}><button className={project?.id === item.id ? "active" : ""} onClick={() => void selectProject(item.id)}><span>{String(index + 1).padStart(2, "0")}</span><b>{item.title}</b><i className={item.status} title={item.status} /></button>{libraryActions("projects", item.id, item.title, item.archived)}</div>;
  }

  const selectProject = useCallback(async (id: string) => {
    try {
      const detail = await api.project(id);
      setProject(detail);
      setSelectedClipId((current) =>
        detail.clips.some((clip) => clip.id === current)
          ? current
          : (detail.clips.find((clip) => clip.status === "approved") ?? detail.clips[0])?.id ?? null,
      );
      setConnectionError("");
    } catch (caught) {
      setConnectionError(caught instanceof Error ? caught.message : "API unavailable");
    }
  }, []);

  const refreshList = useCallback(async () => {
    try {
      const items = await api.projects();
      setProjects(items);
      setConnectionError("");
      return items;
    } catch (caught) {
      setConnectionError(caught instanceof Error ? caught.message : "API unavailable");
      return [];
    }
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function hydrate() {
      try {
        const [items, brandFolders] = await Promise.all([api.projects(), api.brandFolders()]);
        if (cancelled) return;
        setProjects(items);
        setFolders(brandFolders);
        const first = items.find((item) => !item.archived && !brandFolders.find((folder) => folder.id === item.brand_folder_id)?.archived);
        if (first) await selectProject(first.id);
      } catch (caught) {
        if (!cancelled) {
          setConnectionError(caught instanceof Error ? caught.message : "API unavailable");
        }
      }
    }
    void hydrate();
    return () => {
      cancelled = true;
    };
  }, [selectProject]);

  useEffect(() => {
    const hasInspectionRunning = project?.clips.some(
      (clip) => clip.quality.status === "checking",
    );
    if (!project || (!isProcessing(project.status) && !hasInspectionRunning)) return;
    const timer = window.setInterval(() => void selectProject(project.id), 1800);
    return () => window.clearInterval(timer);
  }, [project, selectProject]);

  function acceptProject(created: Project) {
    setProject(created);
    setSelectedClipId(null);
    setShowNew(false);
    void refreshList();
  }

  function acceptBrandFolder(folder: BrandFolder) {
    setFolders((current) => [...current, folder]);
    setShowBrandFolder(false);
    setNewFolderId(folder.id);
    setShowNew(true);
  }

  function acceptRefresh(updated: Project) {
    setProject(updated);
    setSelectedClipId((current) => current ?? updated.clips[0]?.id ?? null);
    void refreshList();
  }

  async function reanalyzeProject() {
    if (!project) return;
    setReanalyzing(true);
    setConnectionError("");
    try {
      acceptRefresh(await api.reanalyze(project.id));
    } catch (caught) {
      setConnectionError(caught instanceof Error ? caught.message : "Re-analysis could not start");
    } finally {
      setReanalyzing(false);
    }
  }

  const selectedClip = project?.clips.find((clip) => clip.id === selectedClipId) ?? project?.clips[0];

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="#top" aria-label="Cutroom home">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/cutroom-wordmark.png" alt="Cutroom" className="cutroom-wordmark" />
        </a>
        <button className="new-project" onClick={() => { setNewFolderId(project?.brand_folder_id ?? ""); setShowNew(true); }}>
          <PlusIcon />
          New film
        </button>
        <button className="new-brand-folder" onClick={() => setShowBrandFolder(true)}>
          <span>◇</span> Brand folder
        </button>
        <nav className="project-nav" aria-label="Projects">
          <p>Brand library</p>
          <button className="archive-toggle" onClick={() => setShowArchived(!showArchived)}>{showArchived ? "← Active library" : "View archive"}</button>
          {projects.length === 0 && folders.length === 0 ? (
            <span className="empty-nav">No film on the bench yet.</span>
          ) : (
            <>
              {visibleFolders.map((folder) => {
                const folderProjects = projects.filter((item) => item.brand_folder_id === folder.id && (folder.archived || item.archived === showArchived));
                return <div className="library-folder" key={folder.id}><details className="folder-group" open><summary><b>{folder.name}</b><small>{folderProjects.length} episodes · {folder.platform}</small></summary>{!folder.archived && <button className="folder-new" onClick={() => { setNewFolderId(folder.id); setShowNew(true); }}><PlusIcon /><b>New episode</b></button>}{!folderProjects.length && <p>No films in this view.</p>}{folderProjects.map(projectRow)}</details>{libraryActions("folders", folder.id, folder.name, folder.archived)}</div>;
              })}
              {visibleProjects.some((item) => !item.brand_folder_id || showArchived) && <details className="folder-group loose" open><summary><b>{showArchived ? "Archived films" : "Unfiled films"}</b></summary>{visibleProjects.filter((item) => !item.brand_folder_id || showArchived && !folders.find((folder) => folder.id === item.brand_folder_id)?.archived).map(projectRow)}</details>}
            </>
          )}
        </nav>
        <div className="sidebar-note">
          <span>Local machine</span>
          <p>Media stays in your workspace until you export it.</p>
        </div>
      </aside>

      <section className="main-stage" id="top">
        <header className="topbar">
          <div>
            <p className="kicker">Video clip factory / Edit desk 01</p>
            <h1>{project?.title ?? "Find the moment worth repeating."}</h1>
            {project && <span className="project-platform">{folders.find((folder) => folder.id === project.brand_folder_id)?.name ?? "One-off"} / {project.platform}</span>}
          </div>
          <div className="topbar-meta">
            {project?.duration_seconds && <span>{formatTime(project.duration_seconds)} source</span>}
            <span>
              {project
                ? `${project.clips.length}/${project.requested_clip_count} selects · pass ${project.analysis_generation}`
                : "Choose 1–20 selects"}
            </span>
            {project && !isProcessing(project.status) && (
              <button onClick={() => void reanalyzeProject()} disabled={reanalyzing}>
                {reanalyzing ? "Re-analyzing…" : "Re-analyze"}
              </button>
            )}
            <button onClick={() => setShowNew(true)}>Add source</button>
          </div>
        </header>

        {connectionError && (
          <div className="connection-banner">API connection: {connectionError}. Start the Docker stack and this desk will reconnect.</div>
        )}

        {!project ? (
          <section className="welcome-grid">
            <div className="welcome-copy">
              <p className="eyebrow">Long-form in. Signal out.</p>
              <h2>Not more content.<br />The right <em>moment.</em></h2>
              <p>
                Bring one film. Cutroom maps the real captions, ranks up to ten complete ideas, and frames your choice for a vertical feed.
              </p>
              <div className="flow-line">
                <span>01 / Listen</span><i />
                <span>02 / Find</span><i />
                <span>03 / Frame</span>
              </div>
            </div>
            <SourceForm onCreated={acceptProject} folders={activeFolders} onCreateFolder={() => setShowBrandFolder(true)} />
          </section>
        ) : (
          <>
            <StatusRail project={project} />
            <ProjectWorkspace
              key={`${project.id}:${selectedClip?.id}`}
              project={project}
              selectedClip={selectedClip}
              onSelectClip={setSelectedClipId}
              onRefresh={acceptRefresh}
              onChooseSource={() => setShowNew(true)}
            />
          </>
        )}
      </section>

      {showNew && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setShowNew(false)}>
          <section className="source-modal" role="dialog" aria-modal="true" aria-label="Add a video" onMouseDown={(event) => event.stopPropagation()}>
            <button className="modal-close" onClick={() => setShowNew(false)} aria-label="Close">×</button>
            <p className="eyebrow">New source</p>
            <h2>Put a film on the bench.</h2>
            <SourceForm key={newFolderId} onCreated={acceptProject} folders={activeFolders} initialFolderId={newFolderId} onCreateFolder={() => setShowBrandFolder(true)} compact />
          </section>
        </div>
      )}

      {showBrandFolder && (
        <BrandFolderModal onClose={() => setShowBrandFolder(false)} onCreated={acceptBrandFolder} />
      )}

    </main>
  );
}

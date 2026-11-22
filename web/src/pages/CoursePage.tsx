import { type DragEvent, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { DocumentOut, SetSummary } from "../api/client";
import { useCourse, useDeleteCourse, useDocumentPages, useUploadDocument } from "../api/hooks";
import { UploadIcon } from "../components/icons";
import { ErrorNote, Loading, Pill } from "../components/Status";
import { FORMAT_LABELS, percent, plural } from "../quiz";

export function CoursePage() {
  const { courseId = "" } = useParams();
  const course = useCourse(courseId);
  const [previewId, setPreviewId] = useState<string | null>(null);

  if (!course.data) return <Loading error={course.error} />;
  const { name, documents, sets } = course.data;
  const anyReady = documents.some((d) => d.status === "ready");
  const preview = documents.find((d) => d.id === previewId && d.status === "ready");

  return (
    <div className="stack">
      <div>
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to="/">Courses</Link> / {name}
        </nav>
        <h1>{name}</h1>
        <p className="subtitle">
          {plural(documents.length, "document")} · {plural(sets.length, "practice set")}
        </p>
      </div>

      <UploadZone courseId={courseId} />

      <section className="stack-tight">
        <h2>Documents</h2>
        <div className="card list">
          {documents.length === 0 && <div className="empty">No documents yet.</div>}
          {documents.map((document) => (
            <DocumentRow
              key={document.id}
              document={document}
              previewing={document.id === previewId}
              onTogglePreview={() => setPreviewId(document.id === previewId ? null : document.id)}
            />
          ))}
        </div>
        {preview && <Preview document={preview} />}
      </section>

      <section className="stack-tight">
        <div className="row">
          <h2>Practice sets</h2>
          {anyReady ? (
            <Link to={`/courses/${courseId}/new`} className="button button-primary">
              New practice set
            </Link>
          ) : (
            <span className="muted small">Needs a document that is ready.</span>
          )}
        </div>
        <div className="card list">
          {sets.length === 0 && <div className="empty">No practice sets yet.</div>}
          {sets.map((set) => (
            <SetRow key={set.id} set={set} />
          ))}
        </div>
      </section>

      <DeleteCourse courseId={courseId} name={name} />
    </div>
  );
}

const ACCEPTED = ".pdf,.pptx,.docx";

function UploadZone({ courseId }: { courseId: string }) {
  const upload = useUploadDocument(courseId);
  const input = useRef<HTMLInputElement>(null);
  const [over, setOver] = useState(false);
  // Uploads run one after another, so a failure can name its file.
  const [failures, setFailures] = useState<string[]>([]);
  const [sending, setSending] = useState(0);

  async function send(files: FileList | null) {
    if (!files?.length) return;
    setFailures([]);
    setSending(files.length);
    for (const file of Array.from(files)) {
      try {
        await upload.mutateAsync(file);
      } catch (error) {
        const reason = error instanceof Error ? error.message : "upload failed";
        setFailures((earlier) => [...earlier, `${file.name}: ${reason}`]);
      }
      setSending((left) => left - 1);
    }
  }

  function drop(event: DragEvent) {
    event.preventDefault();
    setOver(false);
    void send(event.dataTransfer.files);
  }

  return (
    <div
      className={over ? "dropzone over" : "dropzone"}
      onDragOver={(event) => {
        event.preventDefault();
        setOver(true);
      }}
      onDragLeave={() => setOver(false)}
      onDrop={drop}
    >
      <UploadIcon />
      <div className="dropzone-title">Drag lecture files here</div>
      <div className="muted small">
        PDF, PPTX or DOCX · up to 50 MB each · originals are deleted after processing
      </div>
      <input
        ref={input}
        id="file-input"
        type="file"
        className="visually-hidden"
        accept={ACCEPTED}
        multiple
        tabIndex={-1}
        onChange={(event) => {
          void send(event.target.files);
          event.target.value = ""; // so the same file can be chosen again
        }}
      />
      <button
        type="button"
        className="button button-primary"
        disabled={sending > 0}
        onClick={() => input.current?.click()}
      >
        {sending > 0 ? `Uploading ${plural(sending, "file")}…` : "Choose files"}
      </button>
      {failures.map((failure) => (
        <p key={failure} className="error" role="alert">
          {failure}
        </p>
      ))}
    </div>
  );
}

function DocumentRow({
  document,
  previewing,
  onTogglePreview,
}: {
  document: DocumentOut;
  previewing: boolean;
  onTogglePreview: () => void;
}) {
  return (
    <div className="list-row">
      <div className="list-main">
        <span className="list-title">{document.name}</span>
        <span className="small muted">{describeDocument(document)}</span>
        {document.error && <span className="small error">{document.error}</span>}
      </div>
      <div className="list-side">
        <DocumentPill document={document} />
        {document.status === "ready" && (
          <button
            type="button"
            className="button button-small"
            aria-expanded={previewing}
            onClick={onTogglePreview}
          >
            {previewing ? "Hide preview" : "Preview"}
          </button>
        )}
      </div>
    </div>
  );
}

function describeDocument(document: DocumentOut): string {
  if (document.status !== "ready") return "";
  const parts = [
    document.format?.toUpperCase(),
    plural(document.pages ?? 0, document.unit ?? "page"),
    plural(document.topics ?? 0, "topic"),
  ];
  if (document.flagged_pages) {
    parts.push(`${plural(document.flagged_pages, document.unit ?? "page")} with notes`);
  }
  return parts.join(" · ");
}

function DocumentPill({ document }: { document: DocumentOut }) {
  switch (document.status) {
    case "ready":
      return <Pill tone="good">Ready</Pill>;
    case "failed":
      return <Pill tone="bad">Failed</Pill>;
    case "parsing":
      return <Pill tone="wait">Parsing…</Pill>;
    case "queued":
      return <Pill tone="wait">Queued</Pill>;
  }
}

function Preview({ document }: { document: DocumentOut }) {
  const pages = useDocumentPages(document.id);
  const [index, setIndex] = useState(0);

  if (!pages.data) {
    return (
      <div className="card preview">
        <Loading error={pages.error} />
      </div>
    );
  }
  const { unit } = pages.data;
  const total = pages.data.pages.length;
  const page = pages.data.pages[Math.min(index, total - 1)];
  if (!page) return null;

  return (
    <div className="card preview">
      <div className="row">
        <span className="list-title">Extracted text · {document.name}</span>
        <span className="list-side">
          <button
            type="button"
            className="button button-small"
            disabled={index === 0}
            onClick={() => setIndex(index - 1)}
          >
            Previous
          </button>
          <span className="small muted">
            {capitalize(unit)} {page.number} of {total}
          </span>
          <button
            type="button"
            className="button button-small"
            disabled={index >= total - 1}
            onClick={() => setIndex(index + 1)}
          >
            Next
          </button>
        </span>
      </div>
      {page.issues.map((issue) => (
        <span key={issue} className="small caution">
          Note: {issue}
        </span>
      ))}
      <div className="preview-text">{page.text || "(no text on this " + unit + ")"}</div>
      <span className="small muted">
        Check this before generating: questions are only as good as the extracted text.
      </span>
    </div>
  );
}

function capitalize(word: string): string {
  return word.charAt(0).toUpperCase() + word.slice(1);
}

function SetRow({ set }: { set: SetSummary }) {
  const date = new Date(set.created_at).toLocaleDateString(undefined, {
    month: "short",
    day: "numeric",
  });
  const size = set.status === "ready" ? set.questions : set.count;
  return (
    <Link to={`/sets/${set.id}`} className="list-row">
      <div className="list-main">
        <span className="list-title">{set.name}</span>
        <span className="small muted">
          {plural(size, "question")} · {FORMAT_LABELS[set.format]} · {date}
        </span>
        {set.error && <span className="small error">{set.error}</span>}
      </div>
      <div className="list-side">
        <SetStatus set={set} />
      </div>
    </Link>
  );
}

function SetStatus({ set }: { set: SetSummary }) {
  switch (set.status) {
    case "failed":
      return <Pill tone="bad">Failed</Pill>;
    case "queued":
      return <Pill tone="wait">Queued</Pill>;
    case "generating":
      return <Pill tone="wait">Writing questions…</Pill>;
    case "ready":
      return set.last_score ? (
        <strong>{percent(set.last_score.correct, set.last_score.total)}</strong>
      ) : (
        <span className="muted small">Not taken yet</span>
      );
  }
}

function DeleteCourse({ courseId, name }: { courseId: string; name: string }) {
  const remove = useDeleteCourse();
  const navigate = useNavigate();

  function confirmAndDelete() {
    const question = `Delete "${name}" with all its documents, practice sets and results?`;
    if (window.confirm(question)) remove.mutate(courseId, { onSuccess: () => navigate("/") });
  }

  return (
    <div>
      <button
        type="button"
        className="link-button quiet"
        disabled={remove.isPending}
        onClick={confirmAndDelete}
      >
        Delete this course
      </button>
      <ErrorNote error={remove.error} />
    </div>
  );
}

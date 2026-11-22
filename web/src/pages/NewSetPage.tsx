import { type FormEvent, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import type { SetFormat } from "../api/client";
import { useCourse, useCreateSet } from "../api/hooks";
import { ErrorNote, Loading } from "../components/Status";
import { plural } from "../quiz";

const FORMATS: { id: SetFormat; label: string; sub: string }[] = [
  { id: "mixed", label: "Mixed", sub: "Both kinds" },
  { id: "multiple_choice", label: "Multiple choice", sub: "4 options" },
  { id: "true_false", label: "True / false", sub: "Quick recall" },
];
const LATER = ["Short answer", "Flashcards"];
const STEP = 5;
const MAX = 50; // the API's limit

export function NewSetPage() {
  const { courseId = "" } = useParams();
  const course = useCourse(courseId);
  const create = useCreateSet(courseId);
  const navigate = useNavigate();
  // Documents are chosen by default; this holds the ones the student unticked.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [format, setFormat] = useState<SetFormat>("mixed");
  const [count, setCount] = useState(10);

  if (!course.data) return <Loading error={course.error} />;
  const ready = course.data.documents.filter((d) => d.status === "ready");
  const waiting = course.data.documents.filter(
    (d) => d.status === "queued" || d.status === "parsing",
  );
  const chosen = ready.filter((d) => !excluded.has(d.id));

  function toggle(id: string) {
    const next = new Set(excluded);
    if (!next.delete(id)) next.add(id);
    setExcluded(next);
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(
      { document_ids: chosen.map((d) => d.id), count, format },
      { onSuccess: (set) => navigate(`/sets/${set.id}`) },
    );
  }

  return (
    <form className="stack narrow" onSubmit={submit}>
      <div>
        <nav aria-label="Breadcrumb" className="breadcrumb">
          <Link to="/">Courses</Link> / <Link to={`/courses/${courseId}`}>{course.data.name}</Link>{" "}
          / New practice set
        </nav>
        <h1>New practice set</h1>
      </div>

      <div className="card card-pad stack">
        <fieldset className="field">
          <legend>Documents</legend>
          {ready.length === 0 && <span className="muted">No document is ready yet.</span>}
          {ready.map((document) => (
            <label key={document.id} className="check">
              <input
                type="checkbox"
                checked={!excluded.has(document.id)}
                onChange={() => toggle(document.id)}
              />
              <span>{document.name}</span>
            </label>
          ))}
          {waiting.length > 0 && (
            <span className="small muted">
              {waiting.map((d) => d.name).join(", ")} {waiting.length === 1 ? "is" : "are"} still
              processing and can't be selected yet.
            </span>
          )}
        </fieldset>

        <fieldset className="field">
          <legend>Format</legend>
          <div className="choices">
            {FORMATS.map((option) => (
              <button
                key={option.id}
                type="button"
                className="choice"
                aria-pressed={format === option.id}
                onClick={() => setFormat(option.id)}
              >
                <span className="choice-label">{option.label}</span>
                <span className="choice-sub">{option.sub}</span>
              </button>
            ))}
            {LATER.map((label) => (
              <button key={label} type="button" className="choice" disabled>
                <span className="choice-label">{label}</span>
                <span className="choice-sub">Later phase</span>
              </button>
            ))}
          </div>
        </fieldset>

        <div className="field">
          <span className="label" id="count-label">
            Number of questions
          </span>
          <div className="stepper" role="group" aria-labelledby="count-label">
            <button
              type="button"
              aria-label="Fewer questions"
              disabled={count <= STEP}
              onClick={() => setCount(count - STEP)}
            >
              −
            </button>
            <output aria-live="polite">{count}</output>
            <button
              type="button"
              aria-label="More questions"
              disabled={count >= MAX}
              onClick={() => setCount(count + STEP)}
            >
              +
            </button>
          </div>
        </div>

        <div className="row" style={{ justifyContent: "flex-start" }}>
          <button
            type="submit"
            className="button button-primary"
            disabled={chosen.length === 0 || create.isPending}
          >
            Generate {plural(count, "question")}
          </button>
          <Link to={`/courses/${courseId}`} className="link-button">
            Cancel
          </Link>
        </div>
        <ErrorNote error={create.error} />
      </div>
    </form>
  );
}

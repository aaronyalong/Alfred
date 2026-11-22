import { type FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import type { CourseSummary } from "../api/client";
import { useCourses, useCreateCourse } from "../api/hooks";
import { ErrorNote, Loading } from "../components/Status";
import { plural } from "../quiz";

export function CoursesPage() {
  const courses = useCourses();
  const [adding, setAdding] = useState(false);

  return (
    <div className="stack">
      <div className="row row-end">
        <div>
          <h1>Your courses</h1>
          <p className="subtitle">
            Upload course files, generate practice, track what you get wrong.
          </p>
        </div>
        {!adding && (
          <button type="button" className="button" onClick={() => setAdding(true)}>
            + New course
          </button>
        )}
      </div>

      {adding && <NewCourseForm onCancel={() => setAdding(false)} />}

      {!courses.data ? (
        <Loading error={courses.error} />
      ) : courses.data.length === 0 ? (
        !adding && (
          <div className="card empty">No courses yet. Create one to upload your first lecture.</div>
        )
      ) : (
        <div className="course-grid">
          {courses.data.map((course) => (
            <Link key={course.id} to={`/courses/${course.id}`} className="card course-card">
              <span className="course-name">{course.name}</span>
              <span className="muted">{describe(course)}</span>
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}

function describe(course: CourseSummary): string {
  if (course.documents === 0) return "No documents yet";
  const sets = course.sets === 0 ? "no practice yet" : plural(course.sets, "practice set");
  return `${plural(course.documents, "document")} · ${sets}`;
}

function NewCourseForm({ onCancel }: { onCancel: () => void }) {
  const [name, setName] = useState("");
  const create = useCreateCourse();
  const navigate = useNavigate();

  function submit(event: FormEvent) {
    event.preventDefault();
    create.mutate(name, { onSuccess: (course) => navigate(`/courses/${course.id}`) });
  }

  return (
    <form className="card card-pad stack-tight" onSubmit={submit}>
      <label htmlFor="course-name" className="label">
        Course name
      </label>
      <div className="row">
        <input
          id="course-name"
          className="text-input"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="e.g. Cloud Computing"
          maxLength={200}
          autoFocus
          required
        />
        <button
          type="submit"
          className="button button-primary"
          disabled={!name.trim() || create.isPending}
        >
          Create course
        </button>
        <button type="button" className="link-button" onClick={onCancel}>
          Cancel
        </button>
      </div>
      <ErrorNote error={create.error} />
    </form>
  );
}

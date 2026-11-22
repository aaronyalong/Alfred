import { Link, Route, Routes } from "react-router-dom";

import { CoursePage } from "./pages/CoursePage";
import { CoursesPage } from "./pages/CoursesPage";
import { NewSetPage } from "./pages/NewSetPage";
import { SetPage } from "./pages/SetPage";

export function App() {
  return (
    <>
      <header className="header">
        <div className="header-inner">
          <Link to="/" className="brand">
            <span className="brand-mark" aria-hidden="true">
              A
            </span>
            Alfred
          </Link>
          <nav aria-label="Main">
            <Link to="/" className="nav-link">
              Courses
            </Link>
          </nav>
        </div>
      </header>
      <main className="main">
        <Routes>
          <Route path="/" element={<CoursesPage />} />
          <Route path="/courses/:courseId" element={<CoursePage />} />
          <Route path="/courses/:courseId/new" element={<NewSetPage />} />
          <Route path="/sets/:setId" element={<SetPage />} />
          <Route path="*" element={<p className="muted">This page doesn't exist.</p>} />
        </Routes>
      </main>
    </>
  );
}

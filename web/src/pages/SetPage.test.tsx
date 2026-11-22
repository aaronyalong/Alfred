import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { AttemptOut, SetDetail } from "../api/client";
import { multipleChoice, trueFalse } from "../test-fixtures";
import { SetPage } from "./SetPage";

const practiceSet: SetDetail = {
  id: "s1",
  name: "Week 1",
  status: "ready",
  error: null,
  count: 10,
  format: "mixed",
  questions: 2,
  last_score: null,
  created_at: "2026-11-21T10:00:00Z",
  course_id: "c1",
  course_name: "NLP",
  items: [multipleChoice, trueFalse],
};

type Handler = (request: Request) => unknown | Promise<unknown>;

/** Answers API calls from a table of "METHOD /path" handlers, and records the requests. */
function serve(routes: Record<string, Handler>) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", async (request: Request) => {
    const key = `${request.method} ${new URL(request.url).pathname}`;
    calls.push(key);
    const handler = routes[key];
    if (!handler) return new Response(JSON.stringify({ detail: "Not found." }), { status: 404 });
    const body = await handler(request);
    return new Response(body === undefined ? null : JSON.stringify(body), {
      status: body === undefined ? 204 : 200,
      headers: { "content-type": "application/json" },
    });
  });
  return calls;
}

function renderSetPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/sets/s1"]}>
        <Routes>
          <Route path="/sets/:setId" element={<SetPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

test("a quiz shows feedback after each answer, then the server's grading", async () => {
  const user = userEvent.setup();
  let submitted: unknown;
  const graded: AttemptOut = {
    id: "a1",
    correct: 1,
    total: 2,
    answers: [
      { question_id: "q1", given: 0, correct: false },
      { question_id: "q2", given: false, correct: true },
    ],
  };
  serve({
    "GET /api/sets/s1": () => practiceSet,
    "POST /api/sets/s1/attempts": async (request) => {
      submitted = await request.json();
      return graded;
    },
  });
  renderSetPage();

  // Question 1: a wrong answer shows the right one, the explanation and the source.
  expect(await screen.findByText("Question 1 of 2")).toBeInTheDocument();
  expect(screen.queryByText(/Because the slide says so/)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /WordPiece/ }));
  expect(screen.getByRole("status")).toHaveTextContent("Not quite. The answer is B.");
  expect(screen.getByText(/Because the slide says so/)).toBeInTheDocument();
  expect(screen.getByText("Source · Lecture 01.pdf, page 7")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /Byte-Pair Encoding/ })).toBeDisabled();

  // Question 2: true/false.
  await user.click(screen.getByRole("button", { name: "Next question" }));
  await user.click(screen.getByRole("button", { name: /False/ }));
  expect(screen.getByRole("status")).toHaveTextContent("Correct");

  await user.click(screen.getByRole("button", { name: "See results" }));

  expect(await screen.findByText("1 / 2")).toBeInTheDocument();
  expect(submitted).toEqual({
    answers: [
      { question_id: "q1", answer: 0 },
      { question_id: "q2", answer: false },
    ],
  });
  expect(screen.getByText("Your answer: A. WordPiece")).toBeInTheDocument();
  expect(screen.getByText("Correct answer: B. Byte-Pair Encoding")).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Incorrect" })).toBeInTheDocument();
  expect(screen.getByRole("img", { name: "Correct" })).toBeInTheDocument();

  await user.click(screen.getByRole("button", { name: "Take it again" }));
  expect(screen.getByText("Question 1 of 2")).toBeInTheDocument();
});

test("a question can be reported, and the report taken back", async () => {
  const user = userEvent.setup();
  const bodies: unknown[] = [];
  serve({
    "GET /api/sets/s1": () => practiceSet,
    "PUT /api/questions/q1/flag": async (request) => {
      bodies.push(await request.json());
      return undefined;
    },
  });
  renderSetPage();

  await user.click(await screen.findByRole("button", { name: /Byte-Pair Encoding/ }));
  await user.click(screen.getByRole("button", { name: /Report a problem/ }));
  await user.click(await screen.findByRole("button", { name: /Reported. Undo/ }));

  expect(await screen.findByRole("button", { name: /Report a problem/ })).toBeInTheDocument();
  expect(bodies).toEqual([{ flagged: true }, { flagged: false }]);
});

test("a set that is still being written shows its progress", async () => {
  serve({ "GET /api/sets/s1": () => ({ ...practiceSet, status: "generating", items: [] }) });
  renderSetPage();

  expect(await screen.findByText("Building your practice set")).toBeInTheDocument();
  const steps = within(screen.getByRole("list")).getAllByRole("listitem");
  expect(steps.map((s) => s.textContent)).toEqual([
    "Waiting for a free worker",
    "Writing 10 questions",
    "Checking every source quote against its page",
  ]);
});

test("a failed set shows the reason and a way to try again", async () => {
  const error = "None of the questions passed the quality checks. Please try again.";
  serve({ "GET /api/sets/s1": () => ({ ...practiceSet, status: "failed", error, items: [] }) });
  renderSetPage();

  expect(await screen.findByRole("alert")).toHaveTextContent(error);
  expect(screen.getByRole("link", { name: "Try again" })).toHaveAttribute(
    "href",
    "/courses/c1/new",
  );
});

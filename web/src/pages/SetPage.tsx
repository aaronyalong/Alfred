import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import type { AttemptOut, Given, Question, SetDetail } from "../api/client";
import { isPending, useFlagQuestion, usePracticeSet, useSubmitAttempt } from "../api/hooks";
import { CheckIcon, CrossIcon, FlagIcon, PendingIcon, SpinnerIcon } from "../components/icons";
import { ErrorNote, Loading } from "../components/Status";
import {
  BLOOM_LABELS,
  correctOption,
  describeAnswer,
  describeSource,
  isCorrect,
  optionsOf,
  percent,
  plural,
  progressPercent,
} from "../quiz";

/** One practice set: waiting for it, taking it, then its results. */
export function SetPage() {
  const { setId = "" } = useParams();
  const set = usePracticeSet(setId);

  if (!set.data) return <Loading error={set.error} />;
  if (isPending(set.data)) return <Generating set={set.data} />;
  if (set.data.status === "failed" || set.data.items.length === 0) {
    return <Failed set={set.data} />;
  }
  return <Quiz set={set.data} />;
}

function Generating({ set }: { set: SetDetail }) {
  const steps = [
    "Waiting for a free worker",
    `Writing ${plural(set.count, "question")}`,
    "Checking every source quote against its page",
  ];
  const active = set.status === "queued" ? 0 : 1;

  return (
    <div className="card progress-card">
      <div>
        <h1 style={{ fontSize: 22 }}>Building your practice set</h1>
        <p className="subtitle">Runs in the background, so you can leave this page.</p>
      </div>
      <ol className="steps">
        {steps.map((label, i) => (
          <li key={label} className={i > active ? "step pending" : "step"}>
            {i < active ? <CheckIcon /> : i === active ? <SpinnerIcon /> : <PendingIcon />}
            <span>{label}</span>
          </li>
        ))}
      </ol>
      <Link to={`/courses/${set.course_id}`}>Back to {set.course_name}</Link>
    </div>
  );
}

function Failed({ set }: { set: SetDetail }) {
  return (
    <div className="card progress-card">
      <h1 style={{ fontSize: 22 }}>This practice set couldn't be built</h1>
      <p className="notice" role="alert">
        {set.error ?? "No questions were written."}
      </p>
      <div className="row" style={{ justifyContent: "flex-start" }}>
        <Link to={`/courses/${set.course_id}/new`} className="button button-primary">
          Try again
        </Link>
        <Link to={`/courses/${set.course_id}`}>Back to {set.course_name}</Link>
      </div>
    </div>
  );
}

function Quiz({ set }: { set: SetDetail }) {
  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<string, Given>>({});
  const submit = useSubmitAttempt(set);
  const total = set.items.length;
  const question = set.items[index];

  function restart() {
    submit.reset();
    setAnswers({});
    setIndex(0);
  }

  if (submit.data) {
    return <Results set={set} attempt={submit.data} onRetake={restart} />;
  }
  if (!question) return null;

  const given = answers[question.id];
  const answered = given !== undefined;
  const last = index === total - 1;

  return (
    <div className="reading stack-tight">
      <div className="stack-tight" style={{ gap: 8 }}>
        <div className="row small muted">
          <span>
            Question {index + 1} of {total}
          </span>
          <span>
            {set.course_name} · {set.name} · practice mode
          </span>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Progress"
          aria-valuenow={progressPercent(index, answered, total)}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="progress-fill"
            style={{ width: `${progressPercent(index, answered, total)}%` }}
          />
        </div>
      </div>

      <div className="card question-card">
        <div className="chips">
          <span className="chip chip-accent">{BLOOM_LABELS[question.bloom]}</span>
          {question.topics.map((topic) => (
            <span key={topic} className="chip">
              {topic}
            </span>
          ))}
        </div>
        <h2 className="stem">{question.question}</h2>
        <div className="options">
          {optionsOf(question).map((option) => {
            const right = answered && option.value === question.answer;
            const wrong = answered && option.value === given && !right;
            return (
              <button
                key={option.letter}
                type="button"
                className={right ? "option right" : wrong ? "option wrong" : "option"}
                disabled={answered}
                onClick={() => setAnswers({ ...answers, [question.id]: option.value })}
              >
                <span className="option-badge">{option.letter}</span>
                <span>{option.text}</span>
              </button>
            );
          })}
        </div>

        {answered && (
          <div className="feedback">
            <Verdict question={question} given={given} />
            <p>{question.explanation}</p>
            <div className="source">
              <span className="eyebrow">Source · {describeSource(question.source)}</span>
              <blockquote>“{question.source.quote}”</blockquote>
            </div>
            <div className="row">
              <FlagButton setId={set.id} question={question} />
              <button
                type="button"
                className="button button-primary"
                disabled={submit.isPending}
                onClick={() => (last ? submit.mutate(answers) : setIndex(index + 1))}
              >
                {!last ? "Next question" : submit.isPending ? "Saving…" : "See results"}
              </button>
            </div>
            <ErrorNote error={submit.error} />
          </div>
        )}
      </div>
    </div>
  );
}

function Verdict({ question, given }: { question: Question; given: Given }) {
  // Announced, so a screen reader user hears the outcome without looking for it.
  if (isCorrect(question, given)) {
    return (
      <div className="verdict good" role="status">
        Correct
      </div>
    );
  }
  const answer = correctOption(question);
  return (
    <div className="verdict bad" role="status">
      Not quite. The answer is{" "}
      {question.type === "multiple_choice" ? answer.letter : answer.text.toLowerCase()}.
    </div>
  );
}

function FlagButton({ setId, question }: { setId: string; question: Question }) {
  const flag = useFlagQuestion(setId);
  return (
    <button
      type="button"
      className="link-button quiet"
      aria-pressed={question.flagged}
      disabled={flag.isPending}
      onClick={() => flag.mutate({ questionId: question.id, flagged: !question.flagged })}
    >
      <FlagIcon />
      <span>{question.flagged ? "Reported. Undo" : "Report a problem with this question"}</span>
    </button>
  );
}

function Results({
  set,
  attempt,
  onRetake,
}: {
  set: SetDetail;
  attempt: AttemptOut;
  onRetake: () => void;
}) {
  // The server's grading is what counts, not what the browser worked out.
  const graded = new Map(attempt.answers.map((a) => [a.question_id, a]));

  return (
    <div className="reading stack">
      <div className="card card-pad row">
        <div>
          <span className="eyebrow">Your score</span>
          <div className="score">
            {attempt.correct} / {attempt.total}{" "}
            <span className="score-percent">{percent(attempt.correct, attempt.total)}</span>
          </div>
        </div>
        <div className="list-side">
          <button type="button" className="button" onClick={onRetake}>
            Take it again
          </button>
          <Link to={`/courses/${set.course_id}/new`} className="button button-primary">
            New practice set
          </Link>
        </div>
      </div>

      <div className="card list">
        {set.items.map((question) => {
          const answer = graded.get(question.id);
          const correct = answer?.correct ?? false;
          return (
            <div key={question.id} className="result-row">
              <div className="result-icon">
                {correct ? (
                  <CheckIcon label="Correct" size={22} />
                ) : (
                  <CrossIcon label="Incorrect" size={22} />
                )}
              </div>
              <div className="result-body">
                <strong>{question.question}</strong>
                <span>Your answer: {describeAnswer(question, answer?.given)}</span>
                {!correct && (
                  <span className="good-text">
                    Correct answer: {describeAnswer(question, question.answer)}
                  </span>
                )}
                <span className="small muted">
                  {describeSource(question.source)}
                  {question.topics.length > 0 && ` · ${question.topics.join(", ")}`}
                </span>
              </div>
            </div>
          );
        })}
      </div>

      <Link to={`/courses/${set.course_id}`}>Back to {set.course_name}</Link>
    </div>
  );
}

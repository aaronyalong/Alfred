// Quiz logic with no React in it, so it can be tested directly.
import type { Bloom, Given, Question, SetFormat, Source } from "./api/client";

const LETTERS = "ABCDEFGH";

export const BLOOM_LABELS: Record<Bloom, string> = {
  remember: "Remember",
  understand_apply: "Understand / apply",
  analyze_evaluate: "Analyze / evaluate",
};

export const FORMAT_LABELS: Record<SetFormat, string> = {
  mixed: "mixed",
  multiple_choice: "multiple choice",
  true_false: "true / false",
};

export interface Option {
  letter: string;
  text: string;
  value: Given; // what is sent to the server when this option is picked
}

/** A question's choices. True/false is shown as two options, like multiple choice. */
export function optionsOf(question: Question): Option[] {
  if (question.type === "multiple_choice") {
    return question.options.map((text, i) => ({ letter: LETTERS[i] ?? "?", text, value: i }));
  }
  return [
    { letter: "T", text: "True", value: true },
    { letter: "F", text: "False", value: false },
  ];
}

export function correctOption(question: Question): Option {
  const option = optionsOf(question).find((o) => o.value === question.answer);
  if (!option) throw new Error(`question ${question.id} has no correct option`);
  return option;
}

export function isCorrect(question: Question, given: Given | undefined): boolean {
  return given === question.answer;
}

/** "B. Byte-Pair Encoding", or "skipped" when nothing was picked. */
export function describeAnswer(question: Question, given: Given | null | undefined): string {
  const option = optionsOf(question).find((o) => o.value === given);
  if (!option) return "skipped";
  return question.type === "multiple_choice" ? `${option.letter}. ${option.text}` : option.text;
}

/** "Lecture 03.pptx, slide 12" */
export function describeSource(source: Source): string {
  return `${source.document_name}, ${source.unit} ${source.page}`;
}

/** How far through the quiz, in percent: an answered question counts as done. */
export function progressPercent(index: number, answered: boolean, total: number): number {
  if (total === 0) return 0;
  return Math.round(((index + (answered ? 1 : 0)) / total) * 100);
}

export function percent(correct: number, total: number): string {
  return total === 0 ? "0%" : `${Math.round((correct / total) * 100)}%`;
}

export function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

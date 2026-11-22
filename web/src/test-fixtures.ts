// Questions shared by the tests.
import type { Question } from "./api/client";

const common = {
  explanation: "Because the slide says so.",
  bloom: "remember",
  topics: ["Tokenization"],
  source: {
    document_id: "d1",
    document_name: "Lecture 01.pdf",
    unit: "page",
    page: 7,
    quote: "BPE merges the most frequent pair.",
  },
  flagged: false,
} as const;

export const multipleChoice: Question = {
  ...common,
  topics: [...common.topics],
  id: "q1",
  type: "multiple_choice",
  question: "Which tokenizer merges the most frequent pair?",
  options: ["WordPiece", "Byte-Pair Encoding", "Unigram", "Whitespace"],
  answer: 1,
};

export const trueFalse: Question = {
  ...common,
  topics: [...common.topics],
  id: "q2",
  type: "true_false",
  question: "BPE starts from whole words.",
  answer: false,
};

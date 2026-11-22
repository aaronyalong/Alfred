import { errorMessage } from "./api/client";
import {
  correctOption,
  describeAnswer,
  describeSource,
  isCorrect,
  optionsOf,
  percent,
  plural,
  progressPercent,
} from "./quiz";
import { multipleChoice, trueFalse } from "./test-fixtures";

test("multiple choice options are lettered and send their index", () => {
  const options = optionsOf(multipleChoice);

  expect(options.map((o) => o.letter)).toEqual(["A", "B", "C", "D"]);
  expect(options.map((o) => o.value)).toEqual([0, 1, 2, 3]);
  expect(correctOption(multipleChoice).text).toBe("Byte-Pair Encoding");
});

test("true/false is shown as two options that send a boolean", () => {
  expect(optionsOf(trueFalse).map((o) => [o.text, o.value])).toEqual([
    ["True", true],
    ["False", false],
  ]);
  expect(correctOption(trueFalse).text).toBe("False");
});

test("an answer is correct only with the right value of the right type", () => {
  expect(isCorrect(multipleChoice, 1)).toBe(true);
  expect(isCorrect(multipleChoice, 0)).toBe(false);
  expect(isCorrect(multipleChoice, true)).toBe(false); // true is not option 1
  expect(isCorrect(trueFalse, false)).toBe(true);
  expect(isCorrect(trueFalse, 0)).toBe(false);
  expect(isCorrect(trueFalse, undefined)).toBe(false);
});

test("answers and sources are described for the results page", () => {
  expect(describeAnswer(multipleChoice, 1)).toBe("B. Byte-Pair Encoding");
  expect(describeAnswer(trueFalse, false)).toBe("False");
  expect(describeAnswer(multipleChoice, null)).toBe("skipped");
  expect(describeAnswer(multipleChoice, undefined)).toBe("skipped");
  expect(describeSource(multipleChoice.source)).toBe("Lecture 01.pdf, page 7");
});

test("progress counts an answered question as done", () => {
  expect(progressPercent(0, false, 4)).toBe(0);
  expect(progressPercent(0, true, 4)).toBe(25);
  expect(progressPercent(3, true, 4)).toBe(100);
  expect(progressPercent(0, false, 0)).toBe(0);
});

test("small formatting helpers", () => {
  expect(percent(8, 10)).toBe("80%");
  expect(percent(0, 0)).toBe("0%");
  expect(plural(1, "question")).toBe("1 question");
  expect(plural(3, "slide")).toBe("3 slides");
});

test("API errors become a message for the user", () => {
  expect(errorMessage({ detail: "Not ready yet: week2.pdf" }, 409)).toBe(
    "Not ready yet: week2.pdf",
  );
  expect(errorMessage({ detail: [{ msg: "Field required" }, { msg: "Too long" }] }, 422)).toBe(
    "Field required; Too long",
  );
  expect(errorMessage("The file is larger than the 50 MB limit.", 413)).toBe(
    "The file is larger than the 50 MB limit.",
  );
  expect(errorMessage(undefined, 404)).toBe("Not found.");
  expect(errorMessage(undefined, 500)).toBe("Something went wrong. Please try again.");
});

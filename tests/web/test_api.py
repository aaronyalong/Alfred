from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from alfred.api import app as api
from alfred.worker import Worker

PDF = "application/pdf"


def create_course(client: TestClient, name: str = "Cloud Computing") -> str:
    response = client.post("/api/courses", json={"name": name})
    assert response.status_code == 201
    return response.json()["id"]


def upload(client: TestClient, course_id: str, path: Path, name: str = "lecture.pdf") -> Any:
    with path.open("rb") as f:
        return client.post(f"/api/courses/{course_id}/documents", files={"file": (name, f, PDF)})


def ready_document(client: TestClient, worker: Worker, lecture: Path) -> tuple[str, str]:
    """A course with one parsed document: (course id, document id)."""
    course_id = create_course(client)
    document_id = upload(client, course_id, lecture).json()["id"]
    assert worker.run_next()
    return course_id, document_id


def ready_set(client: TestClient, worker: Worker, lecture: Path) -> dict[str, Any]:
    course_id, document_id = ready_document(client, worker, lecture)
    created = client.post(f"/api/courses/{course_id}/sets", json={"document_ids": [document_id]})
    assert created.status_code == 202
    assert worker.run_next()
    return client.get(f"/api/sets/{created.json()['id']}").json()


def test_courses_can_be_created_listed_and_deleted(client: TestClient) -> None:
    course_id = create_course(client, "  Cloud Computing  ")

    courses = client.get("/api/courses").json()
    assert [(c["name"], c["documents"], c["sets"]) for c in courses] == [("Cloud Computing", 0, 0)]

    assert client.delete(f"/api/courses/{course_id}").status_code == 204
    assert client.get("/api/courses").json() == []
    assert client.get(f"/api/courses/{course_id}").status_code == 404
    assert client.post("/api/courses", json={"name": " "}).status_code == 422


def test_an_upload_is_queued_then_parsed_by_the_worker(
    client: TestClient, worker: Worker, lecture: Path, upload_dir: Path
) -> None:
    course_id = create_course(client)

    response = upload(client, course_id, lecture, name="../../Week 1: VPCs.pdf")

    assert response.status_code == 202
    queued = response.json()
    assert (queued["name"], queued["status"], queued["pages"]) == (
        "Week 1: VPCs.pdf",
        "queued",
        None,
    )
    assert (upload_dir / queued["id"] / "Week 1: VPCs.pdf").is_file()  # inside its own folder

    assert worker.run_next()

    (document,) = client.get(f"/api/courses/{course_id}").json()["documents"]
    assert document["status"] == "ready"
    assert (document["format"], document["unit"], document["pages"]) == ("pdf", "page", 3)
    assert (document["topics"], document["flagged_pages"]) == (2, 1)  # the short title page

    pages = client.get(f"/api/documents/{document['id']}/pages").json()
    assert pages["unit"] == "page"
    assert [p["number"] for p in pages["pages"]] == [1, 2, 3]
    assert "logically isolated" in pages["pages"][1]["text"]
    assert "little or no text" in pages["pages"][0]["issues"][0]


def test_uploads_that_are_not_course_files_are_refused(
    client: TestClient, tmp_path: Path, upload_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = create_course(client)
    text = tmp_path / "notes.txt"
    text.write_text("plain text")
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")

    wrong_type = upload(client, course_id, text, name="notes.pdf")
    assert wrong_type.status_code == 415
    assert wrong_type.json()["detail"] == "notes.pdf is not a PDF, PPTX or DOCX file"
    assert upload(client, course_id, empty).status_code == 422

    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 4)
    assert upload(client, course_id, text).status_code == 413

    assert client.get(f"/api/courses/{course_id}").json()["documents"] == []
    assert not any(upload_dir.glob("*/*"))  # nothing was kept


def test_an_upload_far_over_the_limit_is_refused_from_its_declared_size(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    course_id = create_course(client)
    monkeypatch.setattr(api, "MAX_UPLOAD_BYTES", 4)
    monkeypatch.setattr(api, "_CHUNK", 4)

    response = client.post(
        f"/api/courses/{course_id}/documents", files={"file": ("big.pdf", b"x" * 500, PDF)}
    )

    assert response.status_code == 413
    assert "larger than" in response.text


def test_pages_of_a_document_that_is_not_ready_are_refused(
    client: TestClient, lecture: Path
) -> None:
    course_id = create_course(client)
    document_id = upload(client, course_id, lecture).json()["id"]

    assert client.get(f"/api/documents/{document_id}/pages").status_code == 409


def test_a_practice_set_is_generated_and_served_with_its_sources(
    client: TestClient, worker: Worker, lecture: Path
) -> None:
    course_id, document_id = ready_document(client, worker, lecture)

    created = client.post(f"/api/courses/{course_id}/sets", json={"document_ids": [document_id]})

    assert created.status_code == 202
    summary = created.json()
    assert (summary["name"], summary["status"], summary["count"]) == ("lecture", "queued", 10)
    assert client.get(f"/api/sets/{summary['id']}").json()["items"] == []

    assert worker.run_next()

    detail = client.get(f"/api/sets/{summary['id']}").json()
    assert (detail["status"], detail["questions"]) == ("ready", 2)  # the rejected one is hidden
    assert detail["course_name"] == "Cloud Computing"
    multiple_choice, true_false = detail["items"]
    assert multiple_choice["type"] == "multiple_choice"
    assert (
        multiple_choice["options"][multiple_choice["answer"]] == "An isolated section of the cloud"
    )
    assert multiple_choice["topics"] == ["Virtual private clouds"]
    assert multiple_choice["source"] == {
        "document_id": document_id,
        "document_name": "lecture.pdf",
        "unit": "page",
        "page": 2,
        "quote": "a logically isolated section of the AWS cloud",
    }
    assert (true_false["type"], true_false["answer"]) == ("true_false", False)

    (listed,) = client.get(f"/api/courses/{course_id}").json()["sets"]
    assert (listed["questions"], listed["last_score"]) == (2, None)


def test_a_set_needs_ready_documents_from_its_own_course(
    client: TestClient, worker: Worker, lecture: Path
) -> None:
    course_id, document_id = ready_document(client, worker, lecture)
    other_course = create_course(client, "NLP")
    still_queued = upload(client, course_id, lecture, name="week2.pdf").json()["id"]

    def create(course: str, **body: Any) -> int:
        return client.post(f"/api/courses/{course}/sets", json=body).status_code

    assert create(other_course, document_ids=[document_id]) == 422
    assert create(course_id, document_ids=[still_queued]) == 409
    assert create(course_id, document_ids=[]) == 422
    assert create(course_id, document_ids=[document_id], count=51) == 422
    assert create(course_id, document_ids=[document_id], format="essay") == 422


def test_an_attempt_is_graded_by_the_server(
    client: TestClient, worker: Worker, lecture: Path
) -> None:
    practice = ready_set(client, worker, lecture)
    multiple_choice, true_false = practice["items"]
    wrong_option = (multiple_choice["answer"] + 1) % 4

    def attempt(*answers: tuple[str, Any]) -> Any:
        body = {"answers": [{"question_id": q, "answer": a} for q, a in answers]}
        return client.post(f"/api/sets/{practice['id']}/attempts", json=body)

    perfect = attempt((multiple_choice["id"], multiple_choice["answer"]), (true_false["id"], False))
    assert perfect.status_code == 201
    assert (perfect.json()["correct"], perfect.json()["total"]) == (2, 2)

    # A wrong option, and a skipped question. `true` is not accepted as option 1.
    partial = attempt((multiple_choice["id"], wrong_option)).json()
    assert (partial["correct"], partial["total"]) == (0, 2)
    assert [(a["given"], a["correct"]) for a in partial["answers"]] == [
        (wrong_option, False),
        (None, False),
    ]
    assert attempt((multiple_choice["id"], True)).json()["correct"] == 0
    assert attempt((true_false["id"], 0)).json()["correct"] == 0

    assert attempt(("00000000-0000-0000-0000-000000000000", 1)).status_code == 422
    assert attempt((multiple_choice["id"], "a")).status_code == 422

    latest = client.get(f"/api/sets/{practice['id']}").json()["last_score"]
    assert latest == {"correct": 0, "total": 2}


def test_an_attempt_needs_a_ready_set(client: TestClient, worker: Worker, lecture: Path) -> None:
    course_id, document_id = ready_document(client, worker, lecture)
    queued = client.post(f"/api/courses/{course_id}/sets", json={"document_ids": [document_id]})

    response = client.post(f"/api/sets/{queued.json()['id']}/attempts", json={"answers": []})

    assert response.status_code == 409


def test_a_question_can_be_flagged_and_unflagged(
    client: TestClient, worker: Worker, lecture: Path
) -> None:
    practice = ready_set(client, worker, lecture)
    question_id = practice["items"][0]["id"]

    def flagged() -> bool:
        return client.get(f"/api/sets/{practice['id']}").json()["items"][0]["flagged"]

    assert (
        client.put(f"/api/questions/{question_id}/flag", json={"flagged": True}).status_code == 204
    )
    assert flagged() is True
    client.put(f"/api/questions/{question_id}/flag", json={"flagged": False})
    assert flagged() is False


def test_deleting_a_course_removes_everything_in_it(
    client: TestClient, worker: Worker, lecture: Path, upload_dir: Path
) -> None:
    practice = ready_set(client, worker, lecture)
    course_id = practice["course_id"]
    waiting = upload(client, course_id, lecture, name="week2.pdf").json()["id"]

    assert client.delete(f"/api/courses/{course_id}").status_code == 204

    assert client.get(f"/api/sets/{practice['id']}").status_code == 404
    assert not (upload_dir / waiting).exists()
    assert worker.run_next()  # the queued job for the deleted document does nothing
    assert client.get("/api/health").json() == {"status": "ok"}

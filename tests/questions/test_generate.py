import json
from pathlib import Path
from typing import Any

import pytest

from alfred.ingest import Block, BlockKind, Document, Page, SourceFormat, Unit
from alfred.llm import DiskCache
from alfred.questions import MultipleChoice, TrueFalse
from alfred.questions.generate import GenerationError, Generator, render_document
from tests.fake_claude import FakeClaude

SLIDE_2 = "A VPC is a logically isolated section of the AWS cloud."
SLIDE_3 = "Security groups act as virtual firewalls for EC2 instances."

TOPICS = {
    "topics": [
        {"id": "vpc", "name": "Virtual private clouds", "pages": [2, 99]},
        {"id": "VPC", "name": "Duplicate id, different case", "pages": [2]},
        {"id": "security-groups", "name": "Security groups", "pages": [3]},
    ]
}


def question(**fields: Any) -> dict[str, Any]:
    return {
        "page": 2,
        "quote": "a logically isolated section of the AWS cloud",
        "explanation": "The slide defines a VPC this way.",
        "bloom": "remember",
        "topic_ids": ["vpc"],
        **fields,
    }


QUESTIONS = {
    "multiple_choice": [
        question(
            question="What is a VPC?",
            options=["An isolated section of the cloud", "A firewall", "A region", "A bucket"],
            answer="An isolated section of the cloud",
        ),
        question(  # the answer matches no option: rejected by the checks
            question="What do security groups act as?",
            options=["Routers", "Load balancers", "Gateways", "Buckets"],
            answer="Virtual firewalls",
            page=3,
            quote="act as virtual firewalls for EC2 instances",
            topic_ids=["security-groups"],
        ),
    ],
    "true_false": [
        question(statement="A VPC is shared with other AWS customers.", answer=False),
    ],
}


def deck() -> Document:
    pages = [
        Page(number=1, blocks=(Block(kind=BlockKind.TITLE, text="Cloud networking"),)),
        Page(number=2, blocks=(Block(kind=BlockKind.TEXT, text=SLIDE_2),), issues=("1 image",)),
        Page(number=3, blocks=(Block(kind=BlockKind.TEXT, text=SLIDE_3),)),
        Page(number=4),
    ]
    return Document(
        source_name='AWS "VPC".pptx',
        source_sha256="1" * 64,
        format=SourceFormat.PPTX,
        unit=Unit.SLIDE,
        parser="test",
        pages=tuple(pages),
    )


def generator(*replies: dict[str, Any], **kwargs: Any) -> tuple[Generator, FakeClaude]:
    fake = FakeClaude(*(json.dumps(r) for r in replies), **kwargs)
    return Generator(fake.client), fake


def test_generate_maps_topics_writes_questions_and_checks_them() -> None:
    gen, fake = generator(TOPICS, QUESTIONS)

    result = gen.generate(deck(), count=10)

    assert [t.id for t in result.topics.topics] == ["vpc", "security-groups"]
    assert result.topics.topics[0].pages == (2,)  # page 99 doesn't exist
    assert [type(q) for q in result.questions] == [MultipleChoice, TrueFalse]
    assert [r.problems for r in result.rejected] == [("answer is not one of the options",)]
    assert result.unit is Unit.SLIDE
    mc = result.questions[0]
    assert isinstance(mc, MultipleChoice)
    assert mc.options[mc.answer] == "An isolated section of the cloud"
    assert "Write 7 multiple-choice and 3 true/false questions." in str(fake.requests[1])
    assert gen.usage.calls == 2


def test_option_order_is_shuffled_the_same_way_every_run() -> None:
    orders = []
    for _ in range(2):
        gen, _ = generator(TOPICS, QUESTIONS)
        q = gen.generate(deck()).questions[0]
        assert isinstance(q, MultipleChoice)
        orders.append(q.options)

    assert orders[0] == orders[1]
    assert set(orders[0]) == set(QUESTIONS["multiple_choice"][0]["options"])


def test_the_document_and_topic_map_are_marked_for_prompt_caching() -> None:
    gen, fake = generator(TOPICS, QUESTIONS)

    gen.generate(deck())

    blocks = fake.requests[1]["messages"][0]["content"]
    assert [b.get("cache_control") for b in blocks] == [None, {"type": "ephemeral"}, None]
    assert blocks[0]["text"] == render_document(deck())


def test_topic_maps_are_cached_per_document(tmp_path: Path) -> None:
    cache = DiskCache(tmp_path)
    first, _ = generator(TOPICS)
    second, fake = generator({"topics": []})  # would fail if it were called
    first._topic_cache = second._topic_cache = cache

    expected = first.topic_map(deck())

    assert second.topic_map(deck()) == expected
    assert fake.requests == []
    assert second.usage.cached == 1


def test_render_document_numbers_pages_and_includes_their_notes() -> None:
    text = render_document(deck())

    assert text.startswith('<document name="AWS &quot;VPC&quot;.pptx" unit="slide">')
    assert f'<slide number="2" notes="1 image">\n{SLIDE_2}\n</slide>' in text
    assert 'number="4"' not in text  # empty slides are left out


def test_a_refusal_or_invalid_answer_raises_generation_error() -> None:
    declined, _ = generator(TOPICS, stop_reason="refusal")
    cut_off = Generator(
        FakeClaude(json.dumps(TOPICS), '{"multiple_choice": [', stop_reason="max_tokens").client
    )

    with pytest.raises(GenerationError, match="declined to map the topics"):
        declined.generate(deck())
    with pytest.raises(GenerationError, match=r"invalid question set \(cut off at max_tokens\)"):
        cut_off.generate(deck())

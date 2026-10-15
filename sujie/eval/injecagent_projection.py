"""Bounded schema projections for three local task mappings; never grant permissions."""

from __future__ import annotations

import ast
import json
import math

from sujie_gateway.detection import detect_indirect
from sujie_gateway.m1_runtime import new_id

PROJECTION_POLICY = "bounded-task-fields-v1"


def _text(value) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise ValueError("PROJECTION_FIELD_INVALID")
    if any(ord(char) < 32 for char in value):
        raise ValueError("PROJECTION_FIELD_INVALID")
    _, finding = detect_indirect(value, new_id(), new_id())
    if finding:
        raise ValueError("PROJECTION_FIELD_DIRECTIVE")
    return value


def project_task_result(tool: str, content: str) -> str:
    if not isinstance(content, str) or len(content) > 12000:
        raise ValueError("PROJECTION_SOURCE_INVALID")
    try:
        literal = json.loads(content)
        if not isinstance(literal, str):
            raise ValueError
        source = ast.literal_eval(literal)
        if not isinstance(source, dict):
            raise ValueError
        if tool == "AmazonGetProductDetails":
            product = source["product_details"]
            price, rating = product["price"], product["rating"]
            if (
                isinstance(price, bool)
                or not isinstance(price, (int, float))
                or not 0 <= price <= 1_000_000_000
                or not math.isfinite(price)
            ):
                raise ValueError
            if type(rating) is not int or not 0 <= rating <= 5:
                raise ValueError
            reviews = product["reviews"]
            if not isinstance(reviews, list) or len(reviews) > 10:
                raise ValueError
            projected = {
                "product_details": {
                    "name": _text(product["name"]),
                    "price": price,
                    "rating": rating,
                    "reviews": [
                        {
                            "reviewer_name": _text(review["reviewer_name"]),
                            "review_date": _text(review["review_date"]),
                        }
                        for review in reviews
                    ],
                }
            }
            withheld = ["product description", "review content"]
        elif tool == "EvernoteManagerSearchNotes":
            notes = source["notes"]
            if not isinstance(notes, list) or not 1 <= len(notes) <= 10:
                raise ValueError
            projected = {
                "notes": [
                    {"note_id": _text(note["note_id"]), "title": _text(note["title"])}
                    for note in notes
                ]
            }
            withheld = ["note snippet"]
        elif tool == "GitHubGetRepositoryDetails":
            details = source["details"]
            branches = details["branches"]
            if (
                not isinstance(branches, list)
                or len(branches) > 10
                or details["visibility"] not in {"public", "private"}
            ):
                raise ValueError
            projected = {
                "details": {
                    "name": _text(details["name"]),
                    "owner": _text(details["owner"]),
                    "branches": [_text(branch) for branch in branches],
                    "visibility": details["visibility"],
                }
            }
            withheld = ["repository description"]
        else:
            raise ValueError("UNSUPPORTED_PROJECTION_TOOL")
    except (KeyError, TypeError, SyntaxError, ValueError) as exc:
        code = (
            str(exc)
            if str(exc).startswith(("PROJECTION_", "UNSUPPORTED_PROJECTION_"))
            else "PROJECTION_SCHEMA_INVALID"
        )
        raise ValueError(code) from None
    return json.dumps(
        {"task_data": projected, "withheld_free_text_fields": withheld},
        ensure_ascii=False,
        sort_keys=True,
    )

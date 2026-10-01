from __future__ import annotations

import re

import pytest

from app.repositories.mongo_repository import MongoMetadataRepository


def _search_regex(search: str) -> str:
    return MongoMetadataRepository._build_filter(search=search)["table_name"]["$regex"]


@pytest.mark.parametrize("search", ["(", "[", "?", "\\", "cust.*", "a+b"])
def test_search_with_regex_metacharacters_yields_a_valid_pattern(search):
    re.compile(_search_regex(search))


@pytest.mark.parametrize(
    ("search", "table_name", "expected"),
    [
        ("cust", "customers", True),
        ("CUST", "customers", True),
        ("cust.*", "customers", False),
        ("order(1)", "order(1)_archive", True),
    ],
)
def test_search_is_a_literal_case_insensitive_substring(search, table_name, expected):
    mongo_matches = re.search(_search_regex(search), table_name, re.IGNORECASE) is not None
    fake_matches = search.lower() in table_name.lower()  # contract of tests/fakes.py

    assert mongo_matches is expected
    assert fake_matches is expected


def test_filters_are_combined():
    query = MongoMetadataRepository._build_filter(owner_email="a@example.com", domain="crm", tag="pii")

    assert query == {"owner.email": "a@example.com", "domain": "crm", "tags": "pii"}


def test_no_filters_match_everything():
    assert MongoMetadataRepository._build_filter() == {}

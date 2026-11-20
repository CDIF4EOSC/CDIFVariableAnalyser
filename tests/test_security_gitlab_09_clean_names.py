"""GitLab #9: header de-duplication is linear, and the column cap comes before it."""

import time

import pytest

from ddicdi.config import settings
from ddicdi.importers import csv_reader
from ddicdi.importers.csv_reader import clean_names


def test_names_stay_unique_and_short():
    names = clean_names(["a b"] * 50 + ["a_b", "a_b_2"] + ["x" * 100] * 20)
    assert len(names) == len(set(names))
    assert all(len(n) <= settings.max_name_chars for n in names)
    assert names[:3] == ["a_b", "a_b_2", "a_b_3"]


def test_long_names_that_share_a_stem_stay_unique():
    headers = ["y" * 60 + suffix for suffix in ("aaaa", "bbbb", "cccc")] * 30
    names = clean_names(headers)
    assert len(names) == len(set(names)) and all(len(n) <= settings.max_name_chars for n in names)


def test_colliding_headers_take_linear_time():
    def punct(i: int) -> str:  # a distinct run of punctuation for each i, ~10 characters
        out = ""
        while True:
            out += " !?"[i % 3]
            i //= 3
            if not i:
                return out

    def timed(k: int) -> float:
        headers = [f"a{punct(i)}b" for i in range(k)]  # distinct, and all clean to "a_b"
        t0 = time.perf_counter()
        names = clean_names(headers)
        assert len(set(names)) == k
        return time.perf_counter() - t0

    small, large = timed(2_000), timed(20_000)
    # 10x the headers: quadratic would be ~100x.
    assert large < max(small * 30, 0.5)


def test_too_wide_csv_is_refused_before_name_cleaning(tmp_path, qsv, monkeypatch):
    monkeypatch.setattr(settings, "max_variables", 50)
    called = []
    monkeypatch.setattr(csv_reader, "clean_names", lambda h: called.append(1) or h)
    monkeypatch.setattr(qsv.__class__, "column_profiles", lambda self, p: called.append(2) or [])
    src = tmp_path / "wide.csv"
    src.write_text(",".join(f"c {i}" for i in range(200)) + "\n" + ",".join("1" * 200) + "\n")
    with pytest.raises(ValueError, match="limit is 50"):
        csv_reader.import_csv(src, tmp_path / "data.csv", qsv)
    assert called == []

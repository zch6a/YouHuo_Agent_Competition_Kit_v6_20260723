from __future__ import annotations

from datetime import date

import pytest

from youhuo.utils import clean_user_text, parse_relative_date, parse_time_text


@pytest.mark.parametrize("text,expected", [
    ("下午两点", "14:00"), ("下午2点半", "14:30"), ("上午九点", "09:00"),
    ("晚上八点十五分", "20:15"), ("中午一点", "13:00"), ("凌晨十二点", "00:00"),
    ("23:05", "23:05"), ("下午十三点", "13:00"),
])
def test_parse_time(text, expected):
    assert parse_time_text(text) == expected


@pytest.mark.parametrize("text,expected", [
    ("今天", "2026-07-22"), ("明天", "2026-07-23"), ("后天", "2026-07-24"),
    ("大后天", "2026-07-25"), ("7月28日", "2026-07-28"), ("1月2日", "2027-01-02"),
    ("下周一", "2026-08-03"),
])
def test_parse_date(text, expected):
    assert parse_relative_date(text, date(2026, 7, 22)) == expected


def test_clean_unicode_controls():
    assert clean_user_text("优\u200b活\x00 帮我", max_length=50) == "优 活 帮我"


def test_clean_fullwidth_normalization():
    assert clean_user_text("ＡＢＣ１２３", max_length=50) == "ABC123"


def test_clean_blank_rejected():
    with pytest.raises(ValueError):
        clean_user_text("\u200b\x00", max_length=50)

import pytest

from copilot import analyze_csv

HEADER = "note_id,title,views,likes,saves,comments\n"
MAX_BYTES = 5 * 1024 * 1024


def test_accepts_exactly_10000_notes():
    text = HEADER + "".join(f"n{i},标题,1,0,0,0\n" for i in range(10000))
    report = analyze_csv(text)
    assert report["note_count"] == 10000
    assert report["totals"]["views"] == 10000


def test_rejects_10001_notes():
    text = HEADER + "".join(f"n{i},标题,1,0,0,0\n" for i in range(10001))
    with pytest.raises(ValueError, match="10000"):
        analyze_csv(text)


def test_accepts_exactly_5_mib_utf8_text():
    text = HEADER + "a,标题,1,0,0,0\n"
    text += "\n" * (MAX_BYTES - len(text.encode("utf-8")))
    assert len(text.encode("utf-8")) == MAX_BYTES
    assert analyze_csv(text)["note_count"] == 1


@pytest.mark.parametrize("text", ["x" * (MAX_BYTES + 1), "中" * (MAX_BYTES // 3 + 1)])
def test_rejects_more_than_5_mib_by_utf8_byte_size(text):
    with pytest.raises(ValueError, match="5MB"):
        analyze_csv(text)


def test_rejects_huge_integer_without_python_digit_limit_exception():
    with pytest.raises(ValueError, match="views 必须是非负整数"):
        analyze_csv(HEADER + "a,title," + "9" * 10000 + ",0,0,0\n")


def test_leading_zeros_do_not_lose_integer_precision():
    report = analyze_csv(HEADER + "a,title," + "0" * 5000 + "1,0,0,0\n")
    assert report["totals"]["views"] == 1

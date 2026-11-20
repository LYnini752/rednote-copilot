import csv
import io

import pytest

from copilot import _format_ratio, analyze_csv, build_metrics_summary, ranked_note_rows

HEADER = "note_id,title,views,likes,saves,comments\n"


def test_weighted_rate_and_zero_denominator():
    result = analyze_csv(HEADER + "a,one,100,10,0,0\nb,two,10,10,0,0\nc,zero,0,7,0,0\n")
    assert result["totals"]["interactions"] == 27
    assert result["interactions_per_view"] == pytest.approx(27 / 110)
    assert result["ranked_notes"][-1]["interactions_per_view"] is None
    assert result["top_note"]["note_id"] == "b"
    assert result["averages"]["views"] == 36.67
    assert result["medians"]["views"] == 10
    summary = build_metrics_summary(result)
    assert "小分母" in summary and "零阅读" in summary and "核对数据口径" in summary


@pytest.mark.parametrize(
    "rows",
    [
        "a,x,1,1,1,1\na,x,1,1,1,1",
        "a,x,1,1,1,1\n a ,x,1,1,1,1",
        ",x,1,1,1,1",
        "  ,x,1,1,1,1",
        "a,,1,1,1,1",
        "a,  ,1,1,1,1",
        "a,x,1,1,1",
        "a,x,1,1,1,1,extra",
        ",,,,,",
        ",,,,,,",
        'a,"unterminated,1,1,1,1',
        'a,"title"junk,1,1,1,1',
    ],
)
def test_bad_records_are_not_silently_counted(rows):
    with pytest.raises(ValueError):
        analyze_csv(HEADER + rows)


@pytest.mark.parametrize(
    "value",
    [
        "nan",
        "NaN",
        "inf",
        "-inf",
        "Infinity",
        "-1",
        "-0",
        "1.5",
        "1.0",
        "1e3",
        "+1",
        "",
        " ",
        "１２",
        "1_000",
        "9223372036854775808",
        "9" * 5000,
    ],
)
@pytest.mark.parametrize("column", ["views", "likes", "saves", "comments"])
def test_invalid_counts_in_each_column(value, column):
    counts = dict.fromkeys(("views", "likes", "saves", "comments"), "1")
    counts[column] = value
    with pytest.raises(ValueError, match=column):
        analyze_csv(HEADER + "a,x," + ",".join(counts.values()))


@pytest.mark.parametrize(
    "header",
    [
        "note_id,title,views,likes,saves\n",
        "note_id,title,views,likes,saves,comments,views\n",
        "note_id,title,views,likes,saves,comments,extra,extra\n",
        "note_id,title,views,likes,saves,comments,\n",
        "note_id,title,views,likes,saves,comments,  \n",
    ],
)
def test_invalid_headers(header):
    with pytest.raises(ValueError):
        analyze_csv(header + "a,x,1,1,1,1")


@pytest.mark.parametrize("text", ["", HEADER, HEADER + "\n\n", None, b"csv", "\ud800"])
def test_empty_or_non_text_input(text):
    with pytest.raises(ValueError):
        analyze_csv(text)


def test_blank_physical_lines_are_ignored():
    result = analyze_csv(HEADER + "\na,one,10,1,1,0\n\n")
    assert result["note_count"] == 1
    assert result["totals"]["interactions"] == 2


def test_bom_reordered_headers_and_quoted_multiline_fields():
    text = '\ufeff"title",comments,extra,note_id,views,saves,likes\r\n"标题,含""引号""\r\n下一行",3,ignored,a,10,2,1\r\n'
    result = analyze_csv(text)
    note = result["top_note"]
    assert note["title"] == '标题,含"引号"\r\n下一行'
    assert note["interactions"] == 6
    assert note["interactions_per_view"] == 0.6


def test_integer_precision_and_maximum_without_float_coercion():
    value = 9007199254740993
    maximum = 9223372036854775807
    result = analyze_csv(
        HEADER + f"a,x,{value},{maximum},{maximum},{maximum}\nb,y,0001, 002 ,0,0\n"
    )
    assert result["totals"]["views"] == value + 1
    assert result["totals"]["likes"] == maximum + 2
    assert result["totals"]["interactions"] == maximum * 3 + 2
    assert result["top_note"]["note_id"] == "a"
    assert result["ranked_notes"][0]["views"] == value


def test_all_zero_views_has_no_top_note_and_null_ratio():
    result = analyze_csv(HEADER + "a,x,0,3,2,1\nb,y,0,0,0,0\n")
    assert result["top_note"] is None
    assert result["interactions_per_view"] is None
    assert all(n["interactions_per_view"] is None for n in result["ranked_notes"])
    assert all(row[-1] == "null" for row in ranked_note_rows(result))
    summary = build_metrics_summary(result)
    assert "**null**" in summary
    assert "当前互动率最高" not in summary


def test_ranking_is_stable_and_ratio_can_exceed_one():
    result = analyze_csv(HEADER + "a,one,2,4,0,0\nb,two,3,6,0,0\nc,zero,0,99,0,0\n")
    assert [row[0] for row in ranked_note_rows(result)] == ["a", "b", "c"]
    assert ranked_note_rows(result)[0] == ["a", "one", 2, 4, "200.00%"]
    assert "可超过 100%" in result["definition"]


def test_metrics_summary_and_rows_are_human_friendly():
    report = analyze_csv(HEADER + "a,one,100,10,5,5\nb,two,200,20,5,5\n")
    summary = build_metrics_summary(report)
    assert "复盘摘要" in summary
    assert "16.67%" in summary
    assert ranked_note_rows(report)[0][0] == "a"


@pytest.mark.parametrize(
    "title",
    [
        "[点我](https://evil.example)",
        "![图](javascript:alert(1))",
        '<a href="https://evil.example">点击</a>',
        "**粗体**\n\n# 注入标题",
        "\\[逃逸](https://evil.example)",
        "<https://evil.example>",
        "[引用][id]\n\n[id]: https://evil.example",
        "https://evil.example",
        "&lt;script&gt;",
    ],
)
def test_summary_escapes_untrusted_titles_without_changing_table_data(title):
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(["note_id", "title", "views", "likes", "saves", "comments"])
    writer.writerow(["a", title, 10, 1, 0, 0])
    report = analyze_csv(stream.getvalue())
    summary = build_metrics_summary(report)
    top_line = next(line for line in summary.splitlines() if "当前互动率最高" in line)
    assert title not in top_line
    assert "<a " not in summary and "<https:" not in summary
    assert "https:" not in top_line and "javascript:" not in top_line
    assert "\n# 注入标题" not in summary
    assert ranked_note_rows(report)[0][1] == title
    markdown_it = pytest.importorskip("markdown_it")
    rendered = markdown_it.MarkdownIt("commonmark", {"html": True}).render(summary)
    assert "<a " not in rendered and "<img " not in rendered
    assert "<script" not in rendered
    assert rendered.count("<h2>") == 2


@pytest.mark.parametrize(
    "value,expected",
    [
        (None, "null"),
        (float("nan"), "null"),
        (float("inf"), "null"),
        (float("-inf"), "null"),
        (0, "0.00%"),
        (0.12345, "12.35%"),
        (2, "200.00%"),
    ],
)
def test_format_ratio(value, expected):
    assert _format_ratio(value) == expected

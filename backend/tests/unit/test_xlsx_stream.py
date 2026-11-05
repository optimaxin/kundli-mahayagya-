"""The in-house streaming xlsx writer: round trips, escaping, safety and package structure."""

from __future__ import annotations

import io
import re
import uuid
import zipfile
from datetime import UTC, date, datetime
from decimal import Decimal
from xml.etree import ElementTree
from zoneinfo import ZoneInfo

import pytest
from openpyxl import load_workbook

from app.services.xlsx_stream import XlsxStream, column_letters

IST = ZoneInfo("Asia/Kolkata")


def write(build, **kw) -> bytes:  # type: ignore[no-untyped-def]
    buf = io.BytesIO()
    with XlsxStream(buf, **kw) as book:
        build(book)
    return buf.getvalue()


def read(data: bytes):  # type: ignore[no-untyped-def]
    return load_workbook(io.BytesIO(data))  # full (non-streaming) load, like Excel


def test_values_round_trip_with_types_and_formats() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("Data", ["Text", "Int", "Float", "Bool", "Date", "Stamp", "Empty"]) as s:
            s.append(["नमस्ते Ramesh", 42, 12.5, True, date(2026, 12, 14), datetime(2026, 12, 14, 8, 30, 15), None])
            s.append(["x", -7, 0.0, False, date(2026, 12, 21), datetime(2026, 12, 21, 16, 0, 0), None])

    ws = read(write(build))["Data"]
    r2 = [c.value for c in ws[2]]
    assert r2[:4] == ["नमस्ते Ramesh", 42, 12.5, True]
    assert r2[4] == datetime(2026, 12, 14) and r2[5] == datetime(2026, 12, 14, 8, 30, 15) and r2[6] is None
    assert ws["E2"].number_format == "yyyy\\-mm\\-dd" and ws["F2"].number_format == "yyyy\\-mm\\-dd\\ hh:mm:ss"
    assert [c.value for c in ws[3]][1:4] == [-7, 0.0, False]


def test_header_styling_widths_freeze_and_sheet_order() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("First", ["A", "B"], widths=[20, 11]) as s:
            s.append([1, 2])
        with book.sheet("Second", ["C"], widths=[7]) as s:
            s.append([3])

    wb = read(write(build))
    assert wb.sheetnames == ["First", "Second"]
    ws = wb["First"]
    assert ws.freeze_panes == "A2"
    assert ws.column_dimensions["A"].width == 20 and ws.column_dimensions["B"].width == 11
    head = ws["A1"]
    assert head.font.b and head.font.color.rgb == "FFFFFFFF" and head.fill.fgColor.rgb == "FF8B2500"
    assert ws["A2"].font.b in (False, None)  # data cells are not styled like the header


def test_text_is_escaped_and_xml_illegal_characters_removed() -> None:
    nasty = 'Tom & Jerry <b>"quoted"</b> \x00\x0b\x1f end \ud800 ￿'

    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["H & <x>"]) as s:
            s.append([nasty])

    data = write(build)
    ws = read(data)["S"]
    assert ws["A1"].value == "H & <x>"
    assert ws["A2"].value == 'Tom & Jerry <b>"quoted"</b>  end  '
    for name in zipfile.ZipFile(io.BytesIO(data)).namelist():  # every part is well-formed XML
        ElementTree.fromstring(zipfile.ZipFile(io.BytesIO(data)).read(name))


def test_formula_guard_prefixes_user_text_but_not_numbers_or_headers() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["=header"]) as s:
            s.append(["=1+1", "+91 98", "-5 apples", "@SUM(A1)", "\t tab", "safe", -5, "x=y"])

    ws = read(write(build))["S"]
    assert ws["A1"].value == "=header"  # headers are our own constants
    assert [c.value for c in ws[2]] == ["'=1+1", "'+91 98", "'-5 apples", "'@SUM(A1)", "'\t tab", "safe", -5, "x=y"]
    assert all(c.data_type == "s" or c.data_type == "n" for c in ws[2])  # nothing is stored as a formula


def test_formula_guard_can_be_disabled() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["h"]) as s:
            s.append(["=1+1"])

    assert read(write(build, guard_formulas=False))["S"]["A2"].value == "=1+1"


def test_whitespace_and_newlines_are_preserved() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["h"]) as s:
            s.append(["  padded  "])
            s.append(["line1\nline2"])

    ws = read(write(build))["S"]
    assert ws["A2"].value == "  padded  " and ws["A3"].value == "line1\nline2"


def test_cell_text_is_truncated_to_excel_limit() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["h"]) as s:
            s.append(["x" * 40_000])

    assert len(read(write(build))["S"]["A2"].value) == 32_767


def test_timezone_aware_datetimes_are_written_in_event_time() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["t"]) as s:
            s.append([datetime(2026, 12, 14, 2, 30, tzinfo=UTC)])  # 08:00 IST

    assert read(write(build, tz=IST))["S"]["A2"].value == datetime(2026, 12, 14, 8, 0)


def test_unusual_values_never_corrupt_the_file() -> None:
    uid = uuid.uuid4()

    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["h"]) as s:
            s.append([float("nan"), float("inf"), Decimal("12.50"), uid, 10**15, 1e-9])
            s.append([])  # an empty spreadsheet row

    data = write(build)
    ws = read(data)["S"]
    row = [c.value for c in ws[2]]
    assert row[0] is None and row[1] is None  # NaN / inf are not valid cell numbers: skipped
    assert row[2] == 12.5 and row[3] == str(uid) and row[4] == 10**15 and row[5] == pytest.approx(1e-9)
    xml = zipfile.ZipFile(io.BytesIO(data)).read("xl/worksheets/sheet1.xml").decode()
    assert '<row r="3"></row>' in xml  # the empty row exists in the file (readers just have no cells to show)


def test_sheet_names_are_validated() -> None:
    def build_bad(name: str):  # type: ignore[no-untyped-def]
        def build(book: XlsxStream) -> None:
            book.sheet(name, ["h"])
        return build

    for bad in ("", "x" * 32, "a/b", "a[1]", "a:b", "q?", "star*", "back\\slash"):
        with pytest.raises(ValueError):
            write(build_bad(bad))

    def dup(book: XlsxStream) -> None:
        with book.sheet("Same", ["h"]):
            pass
        book.sheet("Same", ["h"])

    with pytest.raises(ValueError):
        write(dup)
    with pytest.raises(ValueError):  # a workbook needs a sheet
        write(lambda book: None)


def test_package_structure_follows_the_ooxml_layout() -> None:
    def build(book: XlsxStream) -> None:
        for name in ("A", "B", "C"):
            with book.sheet(name, ["h"]) as s:
                s.append([1])

    z = zipfile.ZipFile(io.BytesIO(write(build)))
    assert z.testzip() is None
    names = set(z.namelist())
    assert {"[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels", "xl/styles.xml",
            "xl/worksheets/sheet1.xml", "xl/worksheets/sheet2.xml", "xl/worksheets/sheet3.xml"} <= names
    ct = z.read("[Content_Types].xml").decode()
    assert ct.count("worksheet+xml") == 3 and "styles+xml" in ct and "sheet.main+xml" in ct
    rels = z.read("xl/_rels/workbook.xml.rels").decode()
    assert re.findall(r'Id="rId(\d+)"', rels) == ["1", "2", "3", "4"]  # 3 sheets + styles
    wb_xml = z.read("xl/workbook.xml").decode()
    assert [m for m in re.findall(r'<sheet name="(\w)" sheetId="(\d)" r:id="rId(\d)"', wb_xml)] == [
        ("A", "1", "1"), ("B", "2", "2"), ("C", "3", "3")]
    sheet1 = z.read("xl/worksheets/sheet1.xml").decode()
    assert 'tabSelected="1"' in sheet1 and 'tabSelected="1"' not in z.read("xl/worksheets/sheet2.xml").decode()
    styles = z.read("xl/styles.xml").decode()
    assert 'cellXfs count="4"' in styles and styles.count("<xf ") == 5  # 1 cellStyleXf + 4 cellXfs
    assert "theme=" not in styles  # no reference to a theme part that does not exist


def test_rows_are_numbered_in_order_with_cell_references() -> None:
    def build(book: XlsxStream) -> None:
        with book.sheet("S", ["h1", "h2"]) as s:
            for i in range(2500):  # more than one flush chunk
                s.append([i, "t"])

    z = zipfile.ZipFile(io.BytesIO(write(build)))
    xml = z.read("xl/worksheets/sheet1.xml").decode()
    rows = [int(n) for n in re.findall(r'<row r="(\d+)"', xml)]
    assert rows == list(range(1, 2502))
    assert '<c r="A2501"' in xml and '<c r="B2501"' in xml
    ws = read(write(build))["S"]
    assert ws.max_row == 2501 and ws["A2501"].value == 2499


def test_column_letters_beyond_z() -> None:
    assert [column_letters(i) for i in (0, 25, 26, 27, 51, 52, 701, 702)] == ["A", "Z", "AA", "AB", "AZ", "BA", "ZZ", "AAA"]


def test_rows_counter_and_use_after_finish() -> None:
    buf = io.BytesIO()
    with XlsxStream(buf) as book:
        s = book.sheet("S", ["h"])
        s.append([1])
        s.append([2])
        assert s.rows == 2
        s.finish()
        with pytest.raises(RuntimeError):
            s.append([3])


def test_failure_inside_the_block_does_not_produce_a_workbook(tmp_path) -> None:  # type: ignore[no-untyped-def]
    target = tmp_path / "broken.xlsx"
    with pytest.raises(RuntimeError, match="boom"), XlsxStream(target) as book:
        book.sheet("S", ["h"]).append([1])
        raise RuntimeError("boom")
    # the partial archive is not a valid workbook (no workbook.xml), and the file handle was released
    with zipfile.ZipFile(target) as z:
        assert "xl/workbook.xml" not in z.namelist()
    target.unlink()  # would raise PermissionError on Windows if the handle were still open

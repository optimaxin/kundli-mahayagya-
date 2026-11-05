"""Minimal streaming ``.xlsx`` (OOXML SpreadsheetML) writer.

Why this exists
    Profiling the Excel report showed that ~80 % of its run time was openpyxl's per-cell XML
    generation, which is CPU bound: on Render Free (0.1 CPU) a 34,416-row sheet took ~42 s. Writing
    the same sheet with this module takes ~1.5 s at the same CPU cap (see docs/report-performance.md).

What it supports (exactly what the report needs, nothing more)
    * several worksheets, written one after another and streamed to a zip (constant memory),
    * a styled header row, column widths and a frozen header row,
    * cell values: ``None`` (empty), ``bool``, ``int``, ``float``, ``str``, ``date``, ``datetime``
      (anything else is converted with ``str()``),
    * strings are stored inline (no shared-string table, like xlsxwriter's constant-memory mode),
      XML-escaped, stripped of characters that are illegal in XML 1.0 and truncated to Excel's
      32,767-character cell limit,
    * optional spreadsheet-formula-injection guard: text starting with ``= + - @`` (or TAB/CR) is
      stored with a leading apostrophe so Excel/LibreOffice never evaluate user-entered text.

The package layout mirrors the minimal structure written by xlsxwriter (which Excel opens), and the
unit tests re-read the output with openpyxl and compare it with the previous openpyxl output.
"""

from __future__ import annotations

import contextlib
import zipfile
from datetime import date, datetime, tzinfo
from pathlib import Path
from types import TracebackType
from typing import Any, BinaryIO

_EXCEL_EPOCH = date(1899, 12, 30)  # correct for every date after 1900-03-01
_MAX_CELL_CHARS = 32_767
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_CHUNK_ROWS = 1000

# translate(): escape &, <, > and drop characters that are illegal in XML 1.0 (control characters,
# lone surrogates, U+FFFE / U+FFFF). TAB (\x09), LF (\x0a) and CR (\x0d) are legal and kept.
_ESCAPE = {0x26: "&amp;", 0x3C: "&lt;", 0x3E: "&gt;", 0xFFFE: None, 0xFFFF: None}
_ESCAPE.update({c: None for c in range(0x00, 0x20) if c not in (0x09, 0x0A, 0x0D)})
_ESCAPE.update({c: None for c in range(0xD800, 0xE000)})

# style ids (cellXfs index in styles.xml)
_S_HEADER, _S_DATE, _S_DATETIME = 1, 2, 3

_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_NS_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_XML = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'

_STYLES_XML = (
    _XML
    + f'<styleSheet xmlns="{_NS}">'
    '<numFmts count="2"><numFmt numFmtId="164" formatCode="yyyy\\-mm\\-dd"/>'
    '<numFmt numFmtId="165" formatCode="yyyy\\-mm\\-dd\\ hh:mm:ss"/></numFmts>'
    '<fonts count="2">'
    '<font><sz val="11"/><color rgb="FF000000"/><name val="Calibri"/><family val="2"/></font>'
    '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Calibri"/><family val="2"/></font></fonts>'
    '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
    '<fill><patternFill patternType="solid"><fgColor rgb="FF8B2500"/><bgColor indexed="64"/></patternFill></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="4">'
    '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>'
    '<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>'
    '<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
    '<dxfs count="0"/><tableStyles count="0" defaultTableStyle="TableStyleMedium9" defaultPivotStyle="PivotStyleLight16"/>'
    "</styleSheet>"
)

_INVALID_SHEET_CHARS = set("[]:*?/\\")


def column_letters(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(65 + rem) + out
    return out


_COLS = [column_letters(i) for i in range(64)]


def _text(value: str) -> str:
    return value.translate(_ESCAPE)


def _inline(value: str) -> str:
    """The <is><t>...</t></is> body of an inline string."""
    if len(value) > _MAX_CELL_CHARS:
        value = value[:_MAX_CELL_CHARS]
    value = value.translate(_ESCAPE)
    if value != value.strip() or "\n" in value or "\t" in value or "\r" in value:
        return f'<is><t xml:space="preserve">{value}</t></is>'
    return f"<is><t>{value}</t></is>"


class SheetWriter:
    """One worksheet being streamed. Obtain it from :meth:`XlsxStream.sheet`."""

    def __init__(self, book: XlsxStream, title: str, headers: list[str], widths: list[float] | None,
                 first: bool) -> None:
        self._book = book
        self._rows = 0
        self._row_no = 1
        self._buffer: list[str] = []
        self._closed = False
        self._entry: BinaryIO = book._zip.open(f"xl/worksheets/sheet{book._next_index}.xml", "w")
        cols = ""
        if widths:
            cols = "<cols>" + "".join(
                f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>' for i, w in enumerate(widths, start=1)
            ) + "</cols>"
        self._entry.write(
            (
                _XML + f'<worksheet xmlns="{_NS}" xmlns:r="{_NS_R}"><sheetViews>'
                f'<sheetView workbookViewId="0"{" tabSelected=\"1\"" if first else ""}>'
                '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
                '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>'
                f'<sheetFormatPr defaultRowHeight="15"/>{cols}<sheetData>'
            ).encode()
        )
        cells = "".join(
            f'<c r="{_COLS[i]}1" s="{_S_HEADER}" t="inlineStr">{_inline(str(h))}</c>' for i, h in enumerate(headers)
        )
        self._buffer.append(f'<row r="1">{cells}</row>')

    @property
    def rows(self) -> int:
        """Number of data rows written (the header row is not counted)."""
        return self._rows

    def append(self, values: list[Any] | tuple[Any, ...]) -> None:
        """Write one data row. An empty list writes an empty spreadsheet row."""
        if self._closed:
            raise RuntimeError("worksheet already finished")
        self._row_no += 1
        n = self._row_no
        parts = [f'<row r="{n}">']
        tz = self._book._tz
        guard = self._book._guard
        for col, v in zip(_COLS, values, strict=False):
            t = type(v)
            if t is str:
                if guard and v.startswith(_FORMULA_PREFIXES):
                    v = "'" + v
                parts.append(f'<c r="{col}{n}" t="inlineStr">{_inline(v)}</c>')
            elif t is int:
                parts.append(f'<c r="{col}{n}"><v>{v}</v></c>')
            elif t is float:
                if v != v or v in (float("inf"), float("-inf")):  # NaN / inf are not valid cell numbers
                    continue
                parts.append(f'<c r="{col}{n}"><v>{v!r}</v></c>')
            elif v is None:
                continue
            elif t is bool:
                parts.append(f'<c r="{col}{n}" t="b"><v>{int(v)}</v></c>')
            elif t is datetime:
                if v.tzinfo is not None and tz is not None:
                    v = v.astimezone(tz)
                v = v.replace(tzinfo=None)
                serial = (v.date() - _EXCEL_EPOCH).days + (v.hour * 3600 + v.minute * 60 + v.second
                                                           + v.microsecond / 1e6) / 86400
                parts.append(f'<c r="{col}{n}" s="{_S_DATETIME}"><v>{serial!r}</v></c>')
            elif t is date:
                parts.append(f'<c r="{col}{n}" s="{_S_DATE}"><v>{(v - _EXCEL_EPOCH).days}</v></c>')
            else:  # Decimal, UUID, enums, ... : store their text (Decimal as a number)
                if t.__name__ == "Decimal":
                    parts.append(f'<c r="{col}{n}"><v>{float(v)!r}</v></c>')
                else:
                    parts.append(f'<c r="{col}{n}" t="inlineStr">{_inline(str(v))}</c>')
        parts.append("</row>")
        self._buffer.append("".join(parts))
        self._rows += 1
        if len(self._buffer) >= _CHUNK_ROWS:
            self._flush()

    def _flush(self) -> None:
        if self._buffer:
            self._entry.write("".join(self._buffer).encode())
            self._buffer.clear()

    def finish(self) -> None:
        if self._closed:
            return
        self._flush()
        self._entry.write(b"</sheetData></worksheet>")
        self._entry.close()
        self._closed = True

    def __enter__(self) -> SheetWriter:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.finish()


class XlsxStream:
    """Write a workbook sheet by sheet. Usage::

        with XlsxStream(path) as book:
            with book.sheet("Bookings", ["Number", "Name"], widths=[16, 30]) as sheet:
                sheet.append(["MY26-ABCD1234", "Asha"])
    """

    def __init__(self, target: str | Path | BinaryIO, *, tz: tzinfo | None = None, guard_formulas: bool = True,
                 compresslevel: int = 1) -> None:
        # compresslevel 1: ~40 % less CPU than the default level for ~30 % larger files, a good trade on
        # a CPU-starved host (the download itself is small either way).
        self._zip = zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=compresslevel)
        self._tz = tz
        self._guard = guard_formulas
        self._sheets: list[str] = []
        self._current: SheetWriter | None = None
        self._finished = False

    @property
    def _next_index(self) -> int:
        return len(self._sheets) + 1

    def sheet(self, title: str, headers: list[str], widths: list[float] | None = None) -> SheetWriter:
        if self._current is not None:
            self._current.finish()
        if not title or len(title) > 31 or _INVALID_SHEET_CHARS & set(title) or title in self._sheets:
            raise ValueError(f"invalid or duplicate worksheet name: {title!r}")
        writer = SheetWriter(self, title, headers, widths, first=not self._sheets)
        self._sheets.append(title)
        self._current = writer
        return writer

    def close(self) -> None:
        if self._finished:
            return
        if self._current is not None:
            self._current.finish()
        if not self._sheets:
            raise ValueError("a workbook needs at least one worksheet")
        z, n = self._zip, len(self._sheets)
        overrides = "".join(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
            for i in range(1, n + 1)
        )
        z.writestr(
            "[Content_Types].xml",
            _XML + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
            f"{overrides}"
            '<Override PartName="/xl/styles.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/></Types>',
        )
        z.writestr(
            "_rels/.rels",
            _XML + f'<Relationships xmlns="{_REL}"><Relationship Id="rId1" '
            f'Type="{_NS_R}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        )
        sheets_xml = "".join(
            f'<sheet name="{_text(t)}" sheetId="{i}" r:id="rId{i}"/>' for i, t in enumerate(self._sheets, start=1)
        )
        z.writestr(
            "xl/workbook.xml",
            _XML + f'<workbook xmlns="{_NS}" xmlns:r="{_NS_R}"><bookViews><workbookView activeTab="0"/></bookViews>'
            f"<sheets>{sheets_xml}</sheets></workbook>",
        )
        rels = "".join(
            f'<Relationship Id="rId{i}" Type="{_NS_R}/worksheet" Target="worksheets/sheet{i}.xml"/>'
            for i in range(1, n + 1)
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            _XML + f'<Relationships xmlns="{_REL}">{rels}<Relationship Id="rId{n + 1}" '
            f'Type="{_NS_R}/styles" Target="styles.xml"/></Relationships>',
        )
        z.writestr("xl/styles.xml", _STYLES_XML)
        z.close()
        self._finished = True

    def abort(self) -> None:
        """Release the file handle after a failure (the partial file is left for the caller to delete)."""
        # The original error is what matters, so cleanup problems are swallowed. The open sheet entry must be
        # closed first: a ZipFile cannot be closed while a writing handle is open (the file would stay locked).
        if self._current is not None:
            with contextlib.suppress(Exception):
                self._current._entry.close()
        with contextlib.suppress(Exception):
            self._zip.close()
        self._finished = True

    def __enter__(self) -> XlsxStream:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        if exc_type is None:
            self.close()
        else:
            self.abort()

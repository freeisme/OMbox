"""Minimal .xlsx reader built on the standard library.

The application deliberately ships without third-party dependencies, so this
module reads the subset of the OOXML spreadsheet format we need:

* the first worksheet (or a named one) of a workbook;
* shared strings, inline strings and numeric cells;
* cell references are used to keep empty columns in place.

Not supported on purpose: formulas (the cached value is used), styles,
dates (Excel serial numbers are returned as-is; callers parse what they need),
merged cells and charts.
"""

from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET


NS_MAIN = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS_REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
NS_PKG_REL = "{http://schemas.openxmlformats.org/package/2006/relationships}"

MAX_ROWS = 20000
MAX_CELLS = 400000
CELL_REF = re.compile(r"^([A-Z]+)(\d+)$")


class WorkbookError(ValueError):
    """Raised when the uploaded workbook cannot be read."""


def _column_index(reference: str) -> int:
    """Convert a cell reference such as ``C7`` into a zero-based column index."""
    match = CELL_REF.match(reference.upper())
    if not match:
        return -1
    letters = match.group(1)
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - ord("A") + 1)
    return index - 1


def _normalise_number(value: str) -> str:
    text = value.strip()
    if not text:
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return text


def _text_of(element: ET.Element) -> str:
    parts = [node.text or "" for node in element.iter(f"{NS_MAIN}t")]
    return "".join(parts)


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        payload = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    root = ET.fromstring(payload)
    return [_text_of(node) for node in root.findall(f"{NS_MAIN}si")]


def _sheet_target(archive: zipfile.ZipFile, sheet_name: str) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    except KeyError as exc:
        raise WorkbookError("工作簿缺少 xl/workbook.xml，可能不是有效的 xlsx 文件。") from exc

    sheets = workbook.findall(f"{NS_MAIN}sheets/{NS_MAIN}sheet")
    if not sheets:
        raise WorkbookError("工作簿里没有任何工作表。")

    selected = None
    if sheet_name:
        for sheet in sheets:
            if (sheet.get("name") or "").strip() == sheet_name.strip():
                selected = sheet
                break
        if selected is None:
            names = "、".join((sheet.get("name") or "").strip() for sheet in sheets)
            raise WorkbookError(f"找不到工作表「{sheet_name}」，当前工作表：{names}")
    else:
        selected = sheets[0]

    relationship_id = selected.get(f"{NS_REL}id") or ""
    try:
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    except KeyError as exc:
        raise WorkbookError("工作簿缺少关系定义文件。") from exc
    for relationship in rels.findall(f"{NS_PKG_REL}Relationship"):
        if relationship.get("Id") == relationship_id:
            target = relationship.get("Target") or ""
            if target.startswith("/"):
                return target.lstrip("/")
            if target.startswith("xl/"):
                return target
            return f"xl/{target}"
    # 兜底：常见工作簿第一张表就是 sheet1.xml
    return "xl/worksheets/sheet1.xml"


def read_sheet(
    data: bytes,
    sheet_name: str = "",
    *,
    max_rows: int = MAX_ROWS,
    max_cells: int = MAX_CELLS,
) -> list[list[str]]:
    """Read one worksheet into a list of rows (each row is a list of strings)."""
    if not data:
        raise WorkbookError("文件内容为空。")
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise WorkbookError("不是有效的 xlsx 文件（无法解压）。") from exc

    with archive:
        strings = _shared_strings(archive)
        target = _sheet_target(archive, sheet_name)
        try:
            payload = archive.read(target)
        except KeyError as exc:
            raise WorkbookError(f"工作簿里找不到工作表文件 {target}。") from exc

    root = ET.fromstring(payload)
    rows: list[list[str]] = []
    cells = 0
    for row_node in root.iter(f"{NS_MAIN}row"):
        values: dict[int, str] = {}
        for cell in row_node.findall(f"{NS_MAIN}c"):
            reference = cell.get("r") or ""
            column = _column_index(reference) if reference else len(values)
            if column < 0:
                column = len(values)
            cell_type = cell.get("t") or "n"
            if cell_type == "inlineStr":
                text = _text_of(cell)
            else:
                value_node = cell.find(f"{NS_MAIN}v")
                raw = (value_node.text or "") if value_node is not None else ""
                if cell_type == "s":
                    try:
                        text = strings[int(raw)]
                    except (ValueError, IndexError):
                        text = ""
                elif cell_type == "b":
                    text = "是" if raw.strip() in {"1", "true", "TRUE"} else "否"
                else:
                    text = _normalise_number(raw)
            values[column] = text.strip()
            cells += 1
            if cells > max_cells:
                raise WorkbookError(f"表格内容过大（超过 {max_cells} 个单元格），请拆分后再导入。")
        if not values:
            rows.append([])
        else:
            width = max(values) + 1
            rows.append([values.get(index, "") for index in range(width)])
        if len(rows) > max_rows:
            raise WorkbookError(f"表格行数过多（超过 {max_rows} 行），请拆分后再导入。")
    return rows

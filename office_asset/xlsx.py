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

import base64
import csv
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
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
HEADER_NOISE = re.compile(r"[\s_\-/（）()]")


class WorkbookError(ValueError):
    """Raised when the uploaded workbook cannot be read."""


def normalise_header(value: str) -> str:
    """Normalise a header or enum label for alias lookups (case/space/punctuation free)."""
    return HEADER_NOISE.sub("", (value or "").strip().lower())


def map_headers(header_row: list[str], aliases: dict[str, set[str]]) -> dict[str, int]:
    """Map a header row to field names using per-field alias sets."""
    known = {
        field: {normalise_header(alias) for alias in names} for field, names in aliases.items()
    }
    mapping: dict[str, int] = {}
    for index, raw in enumerate(header_row):
        key = normalise_header(raw)
        if not key:
            continue
        for field, names in known.items():
            if field in mapping:
                continue
            if key in names:
                mapping[field] = index
                break
    return mapping


def read_upload_rows(
    file_name: str,
    data: bytes,
    *,
    max_bytes: int = MAX_UPLOAD_BYTES,
) -> list[list[str]]:
    """Read an uploaded .xlsx / .xlsm / .csv file into rows of strings.

    Raises :class:`WorkbookError` with a user-facing message on any problem.
    """
    if not data:
        raise WorkbookError("文件内容为空。")
    if max_bytes and len(data) > max_bytes:
        raise WorkbookError(f"文件过大（上限 {max_bytes // (1024 * 1024)}MB）。")
    lower = (file_name or "").lower()
    if lower.endswith(".csv"):
        for encoding in ("utf-8-sig", "gbk"):
            try:
                text = data.decode(encoding)
            except UnicodeDecodeError:
                continue
            return [list(row) for row in csv.reader(io.StringIO(text))]
        raise WorkbookError("CSV 编码无法识别，请另存为 UTF-8 或 xlsx。")
    if lower.endswith((".xlsx", ".xlsm")):
        return read_sheet(data)
    raise WorkbookError("只支持 .xlsx、.xlsm 或 .csv 文件。")


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


# --------------------------------------------------------------------- 写出 xlsx

MAX_EXPORT_ROWS = 20000
MAX_EXPORT_CELLS = 400000
EXPORT_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_CTRL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_NUMBER = re.compile(r"^-?\d+(\.\d+)?$")


def _xml_text(value: object) -> str:
    text = _CTRL_CHARS.sub("", str(value if value is not None else ""))
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _column_letter(index: int) -> str:
    """0 → A、25 → Z、26 → AA。"""
    letters = ""
    index += 1
    while index > 0:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _sheet_name(value: object) -> str:
    name = re.sub(r"[\[\]:*?/\\]", "-", str(value or "").strip())[:31]
    return name or "数据"


def _row_xml(
    row: list[object],
    row_index: int,
    styles: str | list[str],
    height: float = 0,
) -> str:
    cells = []
    for index, value in enumerate(row):
        style = styles[index] if isinstance(styles, list) and index < len(styles) else styles
        text = "" if value is None else str(value)
        reference = f"{_column_letter(index)}{row_index}"
        if style == "3" and _NUMBER.match(text):
            cells.append(f'<c r="{reference}" s="{style}"><v>{text}</v></c>')
            continue
        cells.append(
            f'<c r="{reference}" s="{style}" t="inlineStr"><is><t xml:space="preserve">'
            f"{_xml_text(text)}</t></is></c>"
        )
    size = f' ht="{height:g}" customHeight="1"' if height else ""
    return f'<row r="{row_index}"{size}>{"".join(cells)}</row>'


def _styles_xml() -> str:
    """基础样式表：表头深蓝白字、正文细边框、数字右对齐、标题行加粗。

    样式索引（`_sheet_xml` 里按字符串用）：0 默认、1 表头、2 正文文本、3 正文数字、4 标题、
    5 说明行。
    """
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="4">'
        '<font><sz val="11"/><name val="微软雅黑"/></font>'
        '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="微软雅黑"/></font>'
        '<font><b/><sz val="14"/><color rgb="FF1F4E79"/><name val="微软雅黑"/></font>'
        '<font><sz val="10.5"/><color rgb="FF595959"/><name val="微软雅黑"/></font>'
        "</fonts>"
        '<fills count="3">'
        '<fill><patternFill patternType="none"/></fill>'
        '<fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FF1F4E79"/><bgColor indexed="64"/>'
        "</patternFill></fill>"
        "</fills>"
        '<borders count="2">'
        "<border><left/><right/><top/><bottom/><diagonal/></border>"
        '<border><left style="thin"><color rgb="FFD0D7DE"/></left>'
        '<right style="thin"><color rgb="FFD0D7DE"/></right>'
        '<top style="thin"><color rgb="FFD0D7DE"/></top>'
        '<bottom style="thin"><color rgb="FFD0D7DE"/></bottom><diagonal/></border>'
        "</borders>"
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="6">'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFont="1" applyFill="1" '
        'applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" '
        'wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" '
        'applyAlignment="1"><alignment horizontal="left" vertical="top" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" '
        'applyAlignment="1"><alignment horizontal="right" vertical="top" wrapText="1"/></xf>'
        '<xf numFmtId="0" fontId="2" fillId="0" borderId="0" xfId="0" applyFont="1" '
        'applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        '<xf numFmtId="0" fontId="3" fillId="0" borderId="0" xfId="0" applyFont="1" '
        'applyAlignment="1"><alignment horizontal="left" vertical="center"/></xf>'
        "</cellXfs>"
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>'
        "</styleSheet>"
    )


def _numeric_columns(rows: list[list[str]], width: int) -> set[int]:
    """整列都是数字（且至少有一个值）时右对齐，看起来更像台账。"""
    numeric: set[int] = set()
    for index in range(width):
        values = [
            str(row[index]).strip()
            for row in rows
            if index < len(row) and str(row[index]).strip()
        ]
        if values and all(_NUMBER.match(value) for value in values):
            numeric.add(index)
    return numeric


def _sheet_xml(
    title: list[list[str]],
    header: list[str],
    rows: list[list[str]],
    logo: bytes | None = None,
) -> str:
    width_count = max(
        [len(header), *(len(row) for row in title), *(len(row) for row in rows)] or [0]
    )
    widths = []
    for index in range(width_count):
        longest = max(
            [len(str(header[index])) if index < len(header) else 0]
            + [len(str(row[index])) if index < len(row) else 0 for row in rows[:200]]
            + [0]
        )
        widths.append(min(max(longest + 4, 10), 42))
    cols = "".join(
        f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
        for index, width in enumerate(widths)
    )
    # 有 Logo 时在最上面留两行给它，表头与冻结位置整体下移
    logo_rows = 2 if logo else 0
    preamble = [
        _row_xml(row, logo_rows + index + 1, "4" if index == 0 else "5", 22 if index == 0 else 18)
        for index, row in enumerate(title)
    ]
    header_index = logo_rows + len(title) + 1
    numeric = _numeric_columns(rows, width_count)
    body = [_row_xml(header, header_index, "1", 26)] + [
        _row_xml(
            row,
            header_index + index + 1,
            ["3" if column in numeric else "2" for column in range(len(row))],
        )
        for index, row in enumerate(rows)
    ]
    last = f"{_column_letter(max(width_count - 1, 0))}{header_index + len(rows)}"
    drawing = '<drawing r:id="rId1"/>' if logo else ""
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<dimension ref="A1:{last}"/>'
        '<sheetViews><sheetView workbookViewId="0" tabSelected="1">'
        f'<pane ySplit="{header_index}" topLeftCell="A{header_index + 1}" activePane="bottomLeft" '
        'state="frozen"/>'
        f'<selection pane="bottomLeft" activeCell="A{header_index + 1}" sqref="A{header_index + 1}"/>'
        "</sheetView></sheetViews>"
        '<sheetFormatPr defaultRowHeight="18" defaultColWidth="10"/>'
        f"<cols>{cols}</cols>"
        f"<sheetData>{''.join(preamble + body)}</sheetData>"
        f'<autoFilter ref="A{header_index}:{last}"/>'
        f"{drawing}"
        "</worksheet>"
    )


PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
LOGO_DATA_URI_PREFIX = "data:image/png;base64,"
MAX_LOGO_BYTES = 300 * 1024
# 导出时 Logo 的最大显示高度（点）；宽度按原图比例算，最多不超过 240 点。
LOGO_MAX_HEIGHT_PX = 36
LOGO_MAX_WIDTH_PX = 240
# 1 点 = 12700 EMU，1 像素 = 9525 EMU（96 DPI）
EMU_PER_PIXEL = 9525


def png_size(data: bytes) -> tuple[int, int] | None:
    """读 PNG 的 IHDR 拿宽高；不是 PNG 或数据不完整时返回 None。"""
    if len(data) < 24 or not data.startswith(PNG_MAGIC) or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def decode_logo_data_uri(value: object) -> bytes | None:
    """把设置里存的 `data:image/png;base64,...` 解析成 PNG 字节；空值返回 None。

    不是 PNG、超过 300KB 或 base64 不合法时抛 :class:`WorkbookError`（保存设置时直接提示用户）。
    """
    text = str(value or "").strip()
    if not text:
        return None
    if not text.startswith(LOGO_DATA_URI_PREFIX):
        raise WorkbookError("Logo 必须是 PNG 图片（上传时会自动转成 data URI）。")
    try:
        data = base64.b64decode(text[len(LOGO_DATA_URI_PREFIX) :], validate=True)
    except (ValueError, TypeError) as exc:
        raise WorkbookError("Logo 内容不是合法的 base64。") from exc
    if len(data) > MAX_LOGO_BYTES:
        raise WorkbookError(f"Logo 图片过大（上限 {MAX_LOGO_BYTES // 1024}KB），请压缩后再上传。")
    if png_size(data) is None:
        raise WorkbookError("Logo 不是有效的 PNG 图片。")
    return data


def _logo_drawing_xml(data: bytes) -> str:
    size = png_size(data) or (LOGO_MAX_WIDTH_PX, LOGO_MAX_HEIGHT_PX)
    ratio = size[0] / size[1]
    height = LOGO_MAX_HEIGHT_PX
    width = min(round(height * ratio), LOGO_MAX_WIDTH_PX)
    cx = width * EMU_PER_PIXEL
    cy = height * EMU_PER_PIXEL
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        "<xdr:oneCellAnchor>"
        "<xdr:from><xdr:col>0</xdr:col><xdr:colOff>9525</xdr:colOff>"
        "<xdr:row>0</xdr:row><xdr:rowOff>9525</xdr:rowOff></xdr:from>"
        f'<xdr:ext cx="{cx}" cy="{cy}"/>'
        "<xdr:pic><xdr:nvPicPr>"
        '<xdr:cNvPr id="1" name="logo.png" descr="公司 Logo"/>'
        '<xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>'
        "</xdr:nvPicPr>"
        '<xdr:blipFill><a:blip r:embed="rId1"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>'
        '<xdr:spPr><a:xfrm><a:off x="0" y="0"/>'
        f'<a:ext cx="{cx}" cy="{cy}"/></a:xfrm>'
        '<a:prstGeom prst="rect"><a:avLst/></a:prstGeom></xdr:spPr>'
        "</xdr:pic><xdr:clientData/></xdr:oneCellAnchor></xdr:wsDr>"
    )


def write_sheet(
    rows: list[list[object]],
    *,
    header: list[str] | None = None,
    title: list[list[str]] | None = None,
    sheet_name: str = "数据",
    logo: bytes | None = None,
) -> bytes:
    """把二维表写成 xlsx（表头深蓝白字、细边框、自适应列宽、冻结首行、自动筛选）。

    `logo` 传 PNG 字节时，图片会贴在左上角，表格整体下移两行。
    """
    table = [list(row) for row in rows]
    head = [str(cell) for cell in (header or [])]
    preamble = [[str(cell) for cell in row] for row in (title or [])]
    logo_png = logo if logo and png_size(logo) else None
    logo_types = (
        '<Default Extension="png" ContentType="image/png"/>'
        '<Override PartName="/xl/drawings/drawing1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        if logo_png
        else ""
    )
    with io.BytesIO() as buffer:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(
                "[Content_Types].xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
                '<Default Extension="xml" ContentType="application/xml"/>'
                + logo_types
                +
                '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
                '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
                '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
                "</Types>",
            )
            archive.writestr(
                "_rels/.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                "</Relationships>",
            )
            archive.writestr(
                "xl/workbook.xml",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                f'<sheets><sheet name="{_xml_text(_sheet_name(sheet_name))}" sheetId="1" r:id="rId1"/></sheets>'
                "</workbook>",
            )
            archive.writestr(
                "xl/_rels/workbook.xml.rels",
                '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
                "</Relationships>",
            )
            archive.writestr("xl/styles.xml", _styles_xml())
            if logo_png:
                archive.writestr("xl/media/image1.png", logo_png)
                archive.writestr("xl/drawings/drawing1.xml", _logo_drawing_xml(logo_png))
                archive.writestr(
                    "xl/drawings/_rels/drawing1.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="../media/image1.png"/>'
                    "</Relationships>",
                )
                archive.writestr(
                    "xl/worksheets/_rels/sheet1.xml.rels",
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>'
                    "</Relationships>",
                )
            archive.writestr(
                "xl/worksheets/sheet1.xml",
                _sheet_xml(preamble, head, table, logo=logo_png),
            )
        return buffer.getvalue()


def export_xlsx(payload: dict, *, logo: bytes | None = None) -> tuple[bytes, str]:
    """把 `{fileName, sheetName, header, rows, title}` 渲染成 xlsx，返回 (内容, 下载文件名)。"""
    header = [str(cell) for cell in (payload.get("header") or [])]
    # 表头之上的说明行（例如巡检表的「任务编号 / 执行人」几行）
    title = [[str(cell) for cell in (row or [])] for row in (payload.get("title") or [])]
    raw_rows = payload.get("rows") or []
    if not header:
        raise WorkbookError("导出内容缺少表头。")
    if not isinstance(raw_rows, list):
        raise WorkbookError("导出内容格式无效。")
    if len(raw_rows) > MAX_EXPORT_ROWS:
        raise WorkbookError(f"一次最多导出 {MAX_EXPORT_ROWS} 行，请先筛选后再导出。")
    rows = [[("" if cell is None else str(cell)) for cell in (row or [])] for row in raw_rows]
    if len(header) * max(len(rows), 1) > MAX_EXPORT_CELLS:
        raise WorkbookError("导出内容过大，请先筛选后再导出。")
    name = re.sub(r"[\\/:*?\"<>|]", "-", str(payload.get("fileName") or "导出").strip())[:80]
    if not name.lower().endswith(".xlsx"):
        name = f"{name or '导出'}.xlsx"
    return (
        write_sheet(
            rows,
            header=header,
            title=title,
            sheet_name=payload.get("sheetName") or "数据",
            logo=logo,
        ),
        name,
    )

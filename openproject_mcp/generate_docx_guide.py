"""
Utility script to synchronize Markdown guides and export clean, properly formatted
Word (.docx) documents for the QuanLyCatToc team:
1. openproject_mcp/HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.docx
2. docs/HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.docx
3. openproject_mcp/HUONG_DAN_OPENPROJECT_MCP_CHO_TEAM.docx
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _set_cell_background(cell: Any, fill_hex: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill_hex)
    tc_pr.append(shd)


def _clean_markdown_text(text: str) -> str:
    # Convert markdown links [label](url) -> label
    text = re.sub(r"\[([^\]]+)\]\((?:file:///[^)]+|#[^)]+|https?://[^)]+)\)", r"\1", text)
    # Strip any remaining raw file:///D:/PTIT paths
    text = text.replace("file:///D:/PTIT/QLDAPM/", "").replace("file:///D:/PTIT", "")
    # Unwrap italic parenthetical wrappers *(...)* -> (...) even when they contain `code`
    text = re.sub(r"\*\(([^*]+)\)\*", r"(\1)", text)
    # Replace common LaTeX arrows/math symbols
    text = (
        text.replace(r"$\rightarrow$", "→")
        .replace(r"$\leftrightarrow$", "↔")
        .replace(r"$\ge$", "≥")
        .replace(r"$\times$", "×")
        .replace(r"\times", "×")
        .replace(r"\mathbf", "")
        .replace("$", "")
    )
    return text


def _add_formatted_runs(paragraph: Any, raw_text: str, base_bold: bool = False) -> None:
    cleaned = _clean_markdown_text(raw_text)
    base_italic = False
    if cleaned.startswith("*(") and cleaned.endswith(")*"):
        cleaned = "(" + cleaned[2:-2] + ")"
        base_italic = True
    # Tokenize by **bold** (non-greedy) and `code`
    tokens = re.split(r"(\*\*.+?\*\*|`[^`]+`)", cleaned)
    for token in tokens:
        if not token:
            continue
        if token.startswith("**") and token.endswith("**") and len(token) > 4:
            inner = token[2:-2].replace("**", "")
            # Also handle nested `code` inside bold
            sub_tokens = re.split(r"(`[^`]+`)", inner)
            for sub in sub_tokens:
                if not sub:
                    continue
                if sub.startswith("`") and sub.endswith("`") and len(sub) > 2:
                    run = paragraph.add_run(sub[1:-1].replace("**", ""))
                    run.bold = True
                    run.italic = base_italic
                    run.font.name = "Consolas"
                    run.font.size = Pt(9.5)
                    run.font.color.rgb = RGBColor(0x0F, 0x4C, 0x81)
                else:
                    run = paragraph.add_run(sub.replace("**", "").replace("*([", "([").replace(")*", ")"))
                    run.bold = True
                    run.italic = base_italic
        elif token.startswith("`") and token.endswith("`") and len(token) > 2:
            run = paragraph.add_run(token[1:-1].replace("**", ""))
            run.bold = base_bold
            run.italic = base_italic
            run.font.name = "Consolas"
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0x0F, 0x4C, 0x81)
        else:
            # Strip any stray ** or *( / )* markers
            plain = token.replace("**", "").replace("*(", "(").replace(")*", ")")
            plain = re.sub(r"\*([^*]+)\*", r"\1", plain)
            run = paragraph.add_run(plain)
            if base_bold:
                run.bold = True
            if base_italic:
                run.italic = True


def convert_markdown_to_docx(md_path: Path, docx_path: Path) -> None:
    lines = md_path.read_text(encoding="utf-8").splitlines()
    doc = docx.Document()

    for section in doc.sections:
        section.top_margin = Inches(0.75)
        section.bottom_margin = Inches(0.75)
        section.left_margin = Inches(0.75)
        section.right_margin = Inches(0.75)

    normal_style = doc.styles["Normal"]
    normal_style.font.name = "Segoe UI"
    normal_style.font.size = Pt(10.5)

    in_code_block = False
    code_lines: list[str] = []
    table_rows: list[list[str]] = []

    def flush_code_block() -> None:
        nonlocal code_lines
        if not code_lines:
            return
        p = doc.add_paragraph()
        p.paragraph_format.left_indent = Inches(0.25)
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(6)
        code_text = "\n".join(code_lines).replace("**", "").replace("file:///D:/PTIT", "")
        run = p.add_run(code_text)
        run.font.name = "Consolas"
        run.font.size = Pt(9)
        run.font.color.rgb = RGBColor(0x1E, 0x29, 0x3B)
        code_lines = []

    def flush_table() -> None:
        nonlocal table_rows
        if not table_rows:
            return
        num_cols = max(len(r) for r in table_rows)
        table = doc.add_table(rows=len(table_rows), cols=num_cols)
        table.style = "Table Grid"
        for r_idx, row_cells in enumerate(table_rows):
            for c_idx in range(num_cols):
                val = row_cells[c_idx] if c_idx < len(row_cells) else ""
                cell = table.cell(r_idx, c_idx)
                cell.text = ""
                p = cell.paragraphs[0]
                p.paragraph_format.space_before = Pt(2)
                p.paragraph_format.space_after = Pt(2)
                is_header = r_idx == 0
                if is_header:
                    _set_cell_background(cell, "1E3A8A")
                _add_formatted_runs(p, val, base_bold=is_header)
                if is_header:
                    for run in p.runs:
                        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                        run.font.size = Pt(9.5)
                else:
                    for run in p.runs:
                        if run.font.size is None:
                            run.font.size = Pt(9.5)
        table_rows = []

    for raw_line in lines:
        stripped = raw_line.strip()

        if stripped.startswith("```"):
            flush_table()
            if in_code_block:
                flush_code_block()
                in_code_block = False
            else:
                in_code_block = True
            continue

        if in_code_block:
            code_lines.append(raw_line)
            continue

        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            # Skip markdown alignment separator row | :--- | :---: |
            if all(re.match(r"^:?-{2,}:?$", c) for c in cells if c):
                continue
            table_rows.append(cells)
            continue
        else:
            flush_table()

        if not stripped or stripped == "---":
            continue

        # Headings
        m_heading = re.match(r"^(#{1,4})\s+(.*)$", stripped)
        if m_heading:
            level = len(m_heading.group(1))
            title_text = m_heading.group(2)
            h_p = doc.add_heading(level=min(level, 4))
            h_p.text = ""
            _add_formatted_runs(h_p, title_text, base_bold=True)
            for run in h_p.runs:
                if level == 1:
                    run.font.size = Pt(16)
                    run.font.color.rgb = RGBColor(0x0F, 0x17, 0x2A)
                elif level == 2:
                    run.font.size = Pt(13.5)
                    run.font.color.rgb = RGBColor(0x1E, 0x3A, 0x8A)
                elif level == 3:
                    run.font.size = Pt(11.5)
                    run.font.color.rgb = RGBColor(0x1D, 0x4E, 0xD8)
                else:
                    run.font.size = Pt(10.5)
                    run.font.color.rgb = RGBColor(0x33, 0x41, 0x55)
            continue

        # Blockquote
        if stripped.startswith(">"):
            quote_text = stripped.lstrip(">").strip()
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.3)
            p.paragraph_format.space_before = Pt(2)
            p.paragraph_format.space_after = Pt(4)
            _add_formatted_runs(p, quote_text)
            for run in p.runs:
                run.italic = True
            continue

        # Bullet / Numbered list
        m_bullet = re.match(r"^([-*]|\d+\.)\s+(.*)$", stripped)
        if m_bullet:
            marker = m_bullet.group(1)
            item_text = m_bullet.group(2)
            p = doc.add_paragraph()
            p.paragraph_format.left_indent = Inches(0.25)
            p.paragraph_format.space_before = Pt(1.5)
            p.paragraph_format.space_after = Pt(2)
            prefix = "• " if marker in ("-", "*") else f"{marker} "
            r_pre = p.add_run(prefix)
            r_pre.bold = marker not in ("-", "*")
            _add_formatted_runs(p, item_text)
            continue

        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(2)
        p.paragraph_format.space_after = Pt(4)
        _add_formatted_runs(p, stripped)

    flush_code_block()
    flush_table()
    docx_path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(docx_path))


def main() -> None:
    workspace = Path(__file__).resolve().parent.parent
    role_md_op = workspace / "openproject_mcp" / "HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.md"
    role_md_docs = workspace / "docs" / "HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.md"
    full_md = workspace / "openproject_mcp" / "HUONG_DAN_TOAN_TAP_OPENPROJECT_MCP_CHO_TEAM.md"

    # 1. Keep docs/HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.md 100% identical
    shutil.copyfile(role_md_op, role_md_docs)

    # 2. Export all 3 .docx files
    role_docx_op = workspace / "openproject_mcp" / "HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.docx"
    role_docx_docs = workspace / "docs" / "HUONG_DAN_SU_DUNG_THEO_5_VAI_TRO_OPENPROJECT.docx"
    full_docx = workspace / "openproject_mcp" / "HUONG_DAN_OPENPROJECT_MCP_CHO_TEAM.docx"

    convert_markdown_to_docx(role_md_op, role_docx_op)
    shutil.copyfile(role_docx_op, role_docx_docs)
    convert_markdown_to_docx(full_md, full_docx)
    print("Successfully generated all .docx guides!")


if __name__ == "__main__":
    main()

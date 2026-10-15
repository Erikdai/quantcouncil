import io
import zipfile

import pytest

from quantcouncil.reports.document import Bullets, Heading, Para, Report, Table, markdown_blocks
from quantcouncil.reports.render import to_docx, to_pdf

pytestmark = pytest.mark.unit

MD = """# 决策

**Rating**: Underweight\\n\\n减持三分之一。

- 现金流转负
- 合同负债下降

| 指标 | 数值 |
|---|---|
| PE | 21 |
"""


def test_markdown_becomes_blocks():
    blocks = markdown_blocks(MD, heading_offset=1)
    kinds = [type(b) for b in blocks]
    assert kinds == [Heading, Para, Para, Bullets, Table]
    assert blocks[0].level == 2 and blocks[0].text == "决策"
    assert blocks[1].runs[0] == ("Rating", True)          # bold survives
    assert blocks[2].runs[0][0] == "减持三分之一。"          # escaped newlines split paragraphs
    assert len(blocks[3].items) == 2
    assert blocks[4].header == ["指标", "数值"] and blocks[4].rows == [["PE", "21"]]


def _report():
    return Report(title="QuantCouncil 投研日报", subtitle="2026-10-14",
                  blocks=[Heading("账户概览", 1), Table(["", ""], [["总资产", "1,000,000.00"]]),
                          *markdown_blocks(MD), Para([("仅供研究 not advice", False)], muted=True)])


def test_pdf_and_word_render_chinese():
    pdf = to_pdf(_report())
    assert pdf.startswith(b"%PDF") and len(pdf) > 2000
    docx = to_docx(_report())
    with zipfile.ZipFile(io.BytesIO(docx)) as z:
        body = z.read("word/document.xml").decode()
    assert "投研日报" in body and "合同负债下降" in body and "PE" in body

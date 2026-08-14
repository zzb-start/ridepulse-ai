"""04 补充材料 MD → 15页 A4 PDF。

- 输入: D:/0AI先锋/04_补充材料_10页PDF逐页内容.md(修订后)
- 输出: final_submission/RidePulse_AI_团队补充材料.pdf(覆盖旧版)
- 工具链: 自写 MD→HTML 转换(复用 7/19 build_pdf.html 设计风格)+ Edge headless 打印

用法: python scripts/build_pdf.py [--out 输出.pdf]
"""

from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path

SRC = Path("D:/0AI先锋/04_补充材料_10页PDF逐页内容.md")
EDGE = Path("C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe")

CSS = """
@page { size: A4; margin: 12mm 11mm 15mm 11mm;
  @bottom-center { content: "RidePulse AI | 2026 AI先锋未来人才大赛·迈金科技命题 | 第 " counter(page) " 页"; font-size: 7pt; color: #a0aec0; } }
body { font-family: 'Noto Sans SC', 'SimHei', 'Microsoft YaHei', sans-serif; font-size: 9pt; color: #2d3748; line-height: 1.5; }
h1 { font-size: 22pt; color: #1a365d; text-align: center; margin-bottom: 4pt; }
h2 { font-size: 13.5pt; color: #1a365d; margin: 9pt 0 5pt 0; border-bottom: 1.5px solid #ed8936; padding-bottom: 3pt; }
h3 { font-size: 10.5pt; color: #1a365d; margin: 7pt 0 4pt 0; }
table { width: 100%; border-collapse: collapse; margin: 5pt 0; font-size: 7.5pt; }
th { background: #1a365d; color: white; padding: 3pt 4pt; text-align: left; font-weight: bold; }
td { padding: 2pt 4pt; border-bottom: 0.5px solid #e2e8f0; vertical-align: top; }
tr:nth-child(even) td { background: #ebf8ff; }
pre { background: #f7fafc; border: 0.8px solid #e2e8f0; border-radius: 4pt; padding: 5pt 7pt;
  font-family: 'Cascadia Mono', 'Consolas', monospace; font-size: 6.8pt; white-space: pre-wrap; line-height: 1.3; }
blockquote { color: #e53e3e; border-left: 3px solid #e53e3e; padding-left: 8pt; margin: 6pt 0; font-size: 8pt; }
.page { page-break-before: always; }
.page:first-of-type { page-break-before: avoid; }
.note { font-size: 7pt; color: #718096; }
strong { color: #1a365d; }
"""


def md_to_html(md: str) -> str:
    lines = md.split("\n")
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    in_table = False
    table_buf: list[str] = []
    para: list[str] = []

    def flush_para():
        if para:
            text = " ".join(para).strip()
            if text:
                text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
                out.append(f"<p>{text}</p>")
            para.clear()

    def flush_table():
        nonlocal in_table, table_buf
        if table_buf:
            rows = [r for r in table_buf if r.strip()]
            if len(rows) >= 2:
                out.append("<table>")
                out.append("<tr>" + "".join(f"<th>{c.strip()}</th>" for c in rows[0].split("|")[1:-1]) + "</tr>")
                for r in rows[2:]:
                    out.append("<tr>" + "".join(f"<td>{c.strip()}</td>" for c in r.split("|")[1:-1]) + "</tr>")
                out.append("</table>")
            table_buf.clear()
        in_table = False

    for line in lines:
        if line.strip().startswith("```"):
            if in_code:
                out.append("<pre>" + "\n".join(code_buf) + "</pre>")
                code_buf.clear()
            in_code = not in_code
            continue
        if in_code:
            code_buf.append(line)
            continue
        if line.strip().startswith("## "):
            flush_para(); flush_table()
            out.append(f'<div class="page"><h2>{line.strip()[3:]}</h2></div>')
            continue
        if line.strip().startswith("|") and "|" in line.strip()[1:]:
            flush_para()
            table_buf.append(line)
            in_table = True
            continue
        if in_table:
            flush_table()
        if line.strip().startswith(">"):
            flush_para()
            out.append(f"<blockquote>{line.strip()[1:].strip()}</blockquote>")
            continue
        if not line.strip():
            flush_para()
            continue
        para.append(line.strip())
    flush_para(); flush_table()
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default=str(SRC), help="输入 MD 文件")
    parser.add_argument("--out", default="D:/0AI先锋/final_submission/RidePulse_AI_团队补充材料.pdf")
    parser.add_argument("--keep-html", action="store_true")
    args = parser.parse_args()

    md = Path(args.src).read_text(encoding="utf-8")
    # 跳过文档头部框架说明(H1标题与"建议排版"段),从第1页正文开始
    page_start = md.find("## 第1页")
    if page_start > 0:
        md = md[page_start:]
    body = md_to_html(md)
    html = f"<!DOCTYPE html><html lang='zh-CN'><head><meta charset='UTF-8'><style>{CSS}</style></head><body>{body}</body></html>"

    html_path = Path(args.out).with_suffix(".html")
    html_path.write_text(html, encoding="utf-8")

    result = subprocess.run(
        [
            str(EDGE), "--headless", "--disable-gpu", "--no-pdf-header-footer",
            f"--print-to-pdf={args.out}", str(html_path),
        ],
        capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        print("Edge 导出失败:", result.stderr[:500])
        return 1
    size = Path(args.out).stat().st_size / 1024 / 1024
    print(f"PDF 已生成: {args.out} ({size:.2f} MB)")
    if not args.keep_html:
        html_path.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

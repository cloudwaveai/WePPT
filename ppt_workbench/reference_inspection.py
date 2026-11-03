"""Bounded, optional inspection of uploaded reference material.

Callers must first perform their normal authorization, upload validation and
integrity checks. Extracted text is untrusted reference data, never instructions.
"""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path

MAX_PDF_BYTES = 20 * 1024 * 1024
MAX_PDF_PAGES = 10
MAX_TEXT_CHARS = 8_000
MAX_OUTPUT_BYTES = 1_000_000
PDF_TIMEOUT_SECONDS = 8


def _stop(process):
    try:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
    except ProcessLookupError:
        pass
    process.wait()


def inspect_reference(data, mime):
    """Return purpose, truthful readStatus, text and a user-facing note.

    PDF extraction is limited to the first ten pages and 8,000 characters. The
    optional Poppler executable runs without a shell, with a timeout and bounded
    output. Images are registered for slide use but are not sent to a vision model.
    """
    if mime in {"image/png", "image/jpeg"}:
        return {"purpose": "visual-reference", "readStatus": "not-inspected", "text": "",
                "note": "图片可用于页面，但当前 Agent 未查看图片内容。"}
    if mime != "application/pdf":
        return {"purpose": "content-reference", "readStatus": "not-inspected", "text": "",
                "note": "此类型未由参考材料检查器解析。"}
    unavailable = {"purpose": "content-reference", "readStatus": "not-inspected", "text": ""}
    if not isinstance(data, bytes) or not data.startswith(b"%PDF-") or len(data) > MAX_PDF_BYTES:
        return unavailable | {"note": "PDF 无效或超过大小限制，未解析。"}
    executable = shutil.which("pdftotext")
    if not executable:
        return unavailable | {"note": "未安装 PDF 文本提取工具，文件尚未解析。"}
    try:
        with tempfile.TemporaryDirectory(prefix="ppt-reference-") as directory:
            source = Path(directory) / "reference.pdf"
            output = Path(directory) / "text.txt"
            source.write_bytes(data)
            # Output is polled via a file to prevent unbounded in-memory capture.
            process = subprocess.Popen(
                [executable, "-f", "1", "-l", str(MAX_PDF_PAGES), "-enc", "UTF-8", str(source), str(output)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=(os.name == "posix"),
            )
            import time
            deadline = time.monotonic() + PDF_TIMEOUT_SECONDS
            while process.poll() is None:
                if time.monotonic() >= deadline or (output.exists() and output.stat().st_size > MAX_OUTPUT_BYTES):
                    _stop(process)
                    return unavailable | {"note": "PDF 解析超时或输出过大，未提取文本。"}
                time.sleep(0.02)
            if process.returncode or not output.is_file() or output.stat().st_size > MAX_OUTPUT_BYTES:
                return unavailable | {"note": "PDF 无法解析（可能已加密或损坏），未提取文本。"}
            text = output.read_bytes().decode("utf-8", errors="replace").strip()
    except (OSError, ValueError):
        return unavailable | {"note": "PDF 文本提取不可用，文件尚未解析。"}
    if not text:
        return unavailable | {"note": "PDF 前 10 页未提取到文本；扫描页和图片未检查。"}
    truncated = len(text) > MAX_TEXT_CHARS
    return {"purpose": "content-reference", "readStatus": "text-available", "text": text[:MAX_TEXT_CHARS],
            "note": "仅提取 PDF 前 10 页的文字，最多 8,000 字；图片和扫描页未检查。" + ("文字已截断。" if truncated else "")}

"""Text extraction only: documents are data, never executable instructions."""
import base64
import io
import json
import re
import sys
import zipfile
from xml.etree import ElementTree as ET


def extract(name, raw):
    suffix = name.rsplit('.', 1)[-1].lower()
    if suffix in ('txt', 'md', 'csv', 'json'):
        for encoding in ('utf-8-sig', 'gb18030'):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                pass
        raise ValueError('无法识别文本编码，请另存为 UTF-8 文本。')
    if suffix in ('docx', 'pptx'):
        archive = zipfile.ZipFile(io.BytesIO(raw))
        names = ['word/document.xml'] if suffix == 'docx' else sorted(
            (n for n in archive.namelist() if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)),
            key=lambda n: int(re.search(r'slide(\d+)', n)[1]))
        chunks = []
        for index, entry in enumerate(names):
            info = archive.getinfo(entry)
            if info.file_size > 12_000_000:
                raise ValueError('文档内容过大，请分段上传。')
            tree = ET.fromstring(archive.read(entry))
            paragraphs = []
            for paragraph in tree.iter():
                if paragraph.tag.rsplit('}', 1)[-1] == 'p':
                    value = ''.join(e.text or '' for e in paragraph.iter() if e.tag.rsplit('}', 1)[-1] == 't')
                    if value.strip():
                        paragraphs.append(value)
            prefix = f'第 {index + 1} 页\n' if suffix == 'pptx' else ''
            chunks.append(prefix + '\n'.join(paragraphs))
        return '\n\n'.join(chunks)
    if suffix == 'pdf':
        try:
            import fitz
        except ImportError as exc:
            raise ValueError('PDF 解析需要安装 PyMuPDF。') from exc
        doc = fitz.open(stream=raw, filetype='pdf')
        if doc.needs_pass:
            raise ValueError('PDF 已加密，请上传解密后的文件。')
        if len(doc) > 300:
            raise ValueError('PDF 超过 300 页，请拆分后上传。')
        text = '\n\n'.join(f'第 {i+1} 页\n{page.get_text()}' for i, page in enumerate(doc))
        if not re.sub(r'第 \d+ 页|\s', '', text):
            raise ValueError('这份 PDF 是扫描图片，暂未识别到文字。请上传可复制文字的 PDF 或粘贴原文。')
        return text
    raise ValueError('支持 DOCX、PPTX、PDF、TXT、Markdown；旧版 DOC/PPT 请另存为 DOCX/PPTX。')


def pdf_pages(raw):
    try:
        import fitz
    except ImportError as exc:
        raise ValueError('PDF 导入需要安装 PyMuPDF。') from exc
    doc = fitz.open(stream=raw, filetype='pdf')
    if doc.needs_pass:
        raise ValueError('PDF 已加密，请上传解密后的文件。')
    if not len(doc) or len(doc) > 100:
        raise ValueError('原稿需包含 1 至 100 页。')
    return [{'title': f'第 {i + 1} 页', 'svg': page.get_svg_image(text_as_path=False)} for i, page in enumerate(doc)]

if __name__ == '__main__':
    try:
        request = json.load(sys.stdin)
        raw = base64.b64decode(request['data'], validate=True)
        if request.get('mode') == 'pdf-pages':
            print(json.dumps({'pages': pdf_pages(raw)}, ensure_ascii=False))
            sys.exit(0)
        text = extract(request['name'], raw)
        if len(text) > 300000:
            raise ValueError('提取文字超过 30 万字，请拆分材料后上传。')
        print(json.dumps({'text': text}, ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        sys.exit(1)

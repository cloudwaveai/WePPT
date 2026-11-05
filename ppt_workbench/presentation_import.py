"""Open complete supported PPTX files as editable projects, preserving source bytes."""
import base64
import hashlib
import io
import json
from pathlib import Path
import secrets
import tempfile
import zipfile
from collections import Counter
from xml.etree import ElementTree as ET
from .core import EngineError
from .pptx_opening import OpeningImporter, NS, _find, _text
from . import owners

MIME='application/vnd.openxmlformats-officedocument.presentationml.presentation'


class OriginalImageImporter(OpeningImporter):
    def picture(self, shape, part, oid, clip=None, aspect=None):
        blip=_find(shape,'p:blipFill/a:blip')
        rel=self.rels(part).get(blip.get(f"{{{NS['r']}}}embed")) if blip is not None else None
        if not rel:
            self.warn('unsupported-image',oid,'缺少内嵌图片');return None
        raw=self.zip.read(rel[1])
        mime='image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff') else None
        if not mime:
            self.warn('unsupported-image',oid,'图片格式暂不支持无损导入');return None
        if clip or _find(shape,'p:blipFill/a:srcRect') is not None:
            self.warn('original-image-fit',oid,'原图完整保留，以适应框显示；未烘焙原稿裁切。')
        return {'src':f'data:{mime};base64,'+base64.b64encode(raw).decode(),'fit':'contain','alt':Path(rel[1]).name},{'sourcePart':rel[1],'sourceSha256':hashlib.sha256(raw).hexdigest()}


def import_presentation(studio, filename, encoded):
    if not isinstance(filename,str) or not filename.lower().endswith('.pptx'):
        raise EngineError('INVALID_UPLOAD','请选择 .pptx 文件。')
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (ValueError,TypeError):
        raise EngineError('INVALID_UPLOAD','文件编码无效。')
    if not raw or len(raw)>20*1024*1024:
        raise EngineError('UPLOAD_TOO_LARGE','PPTX 文件上限为 20 MB；原文件未被修改。')
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            if len(z.infolist())>10000 or sum(f.file_size for f in z.infolist())>300*1024*1024:
                raise EngineError('UPLOAD_TOO_LARGE','PPTX 解包内容过大；原文件未被修改。')
            z.read('ppt/presentation.xml')
    except (zipfile.BadZipFile,KeyError):
        raise EngineError('INVALID_UPLOAD','无法读取这个 PPTX 文件。')
    scenes=[];reports=[];failed=[]
    with tempfile.TemporaryDirectory(prefix='weppt-open-') as folder:
        source=Path(folder)/'source.pptx';source.write_bytes(raw)
        importer=OriginalImageImporter(source)
        try:
            count=importer.slide_count()
            if not 1<=count<=200:raise EngineError('CAPACITY','请打开 1–200 页的 PPTX；不会只导入部分页面。')
            presentation=importer.xml('ppt/presentation.xml');rels=importer.rels('ppt/presentation.xml')
            parts=[rels[n.get(f"{{{NS['r']}}}id")][1] for n in presentation.findall('p:sldIdLst/p:sldId',NS)]
            for index,part in enumerate(parts,1):
                try:
                    scene,metadata=importer.extract(index,'cover' if index==1 else 'body')
                    root=importer.xml(part)
                    notes_part=importer.related(part,'notesSlide')
                    if notes_part:
                        notes=importer.xml(notes_part)
                        scene['notes']='\n'.join(_text(s) for s in notes.findall('.//p:sp',NS)
                            if (s.find('.//p:ph',NS) is None or s.find('.//p:ph',NS).get('type')=='body') and _text(s).strip())
                    texts=[_text(shape) for shape in root.findall('.//p:sp',NS)]
                    # Compare complete text boxes as a multiset; inherited decorations are allowed extras.
                    expected=Counter(t.strip() for t in texts if t.strip())
                    actual=Counter(o['text'].strip() for o in scene['objects'] if o['type']=='text' and o['text'].strip())
                    missing=expected-actual
                    represented_pictures=sum(1 for o in metadata['objects'] if o['objectId'].startswith('o') and 'sourceSha256' in o)
                    missing_pictures=represented_pictures != len(root.findall('.//p:pic',NS))
                    blockers=[w for w in metadata['limitations'] if w['code'].startswith('unsupported-') or w['code'] in {'image-placeholder','canvas-clipped','font-size-clamped','text-fit-adjusted'}]
                    # The template extractor tolerates approximations; a user document must not.
                    if root.findall('.//p:graphicFrame',NS) or root.findall('.//a:gradFill',NS) or root.findall('.//a:custGeom',NS):
                        blockers.append({'code':'unsupported-document-objects'})
                    if missing or missing_pictures or blockers:
                        failed.append(index);continue
                    scenes.append(scene);reports.append({'page':index,'limitations':metadata['limitations']})
                except (ValueError,KeyError,ET.ParseError,EngineError):failed.append(index)
        finally:importer.close()
    if failed:
        raise EngineError('PPTX_IMPORT_UNSUPPORTED','第 '+ '、'.join(map(str,failed))+' 页含暂不支持的对象或版式，未创建缺页副本。原文件保持完整。',{'pages':failed,'slideCount':count})
    from .studio import Studio
    from .model_profiles import selected,select
    pid='project-'+secrets.token_hex(8)
    studio.wb.create_project(pid,{'title':Path(filename).stem[:120] or '导入演示稿'})
    owners.claim_project(studio.wb,pid)
    target=Studio(studio.wb.root,pid,agent=studio.agent_mode)
    with target.wb.atomic():
        chosen=selected(studio)
        if chosen and chosen.get('model')!='unavailable':select(target,chosen['id'])
        folder=target.wb.project_dir(pid)/'import';folder.mkdir(parents=True,exist_ok=True)
        (folder/'source.pptx').write_bytes(raw)
        manifest={'filename':Path(filename).name,'sha256':hashlib.sha256(raw).hexdigest(),'slideCount':count,'pages':reports}
        (folder/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
        for i,scene in enumerate(scenes,1):
            texts=[o['text'] for o in scene['objects'] if o['type']=='text']
            title=next((t for t in texts if t.strip()),f'第{i}页')
            page=target.wb.add_slide(pid,title,'从用户上传PPTX完整导入', 'cover' if i==1 else 'content')
            scene['slideId']=page['slide']['id']
            target.put_scene(scene['slideId'],page['revision'],scene,'从原始PPTX导入',preserve_layout=True)
        target.select(target.state()['slides'][0]['id'])
    return {'projectId':pid,'slideCount':count,'source':manifest}


def source_info(studio):
    p=studio.wb.project_dir(studio.project_id)/'import/manifest.json'
    if not p.is_file():return None
    data=json.loads(p.read_text())
    return {'filename':data['filename'],'slideCount':data['slideCount'],
            'warnings':sum(len(p['limitations']) for p in data['pages']),
            'pages':data['pages']}

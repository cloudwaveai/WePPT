"""WePPT adapter calling the original PPT Master wrap/measure algorithm unchanged."""
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
manifest=json.loads((ROOT/'vendor/skills/manifest.json').read_text(encoding='utf-8'))
entry=next(p for p in manifest['packages'] if p['id']=='ppt-master')
skill=ROOT/'data/upstream-skills/ppt-master'/entry['commit']
sys.path.insert(0,str(skill/'scripts'))
from attribution_guard import main as check_attribution
if check_attribution()!=0:
    raise SystemExit(1)
from text_measure import wrap_text
items=json.load(sys.stdin)
output=[]
for item in items:
    lines=[]; widths=[]; oversized=[]
    for paragraph in item['text'].split('\n'):
        a,b,c=wrap_text(paragraph,size=item['size'],max_width=item['width'],family='Microsoft YaHei')
        lines.extend(a);widths.extend(b);oversized.extend(c)
    output.append({'id':item['id'],'width':item['width'],'fontSize':item['size'],'lineCount':len(lines),'estimatedHeight':round(len(lines)*item['size']*1.4,2),'maxLineWidth':round(max(widths,default=0),2),'oversizedUnits':len(oversized),'engine':'ppt-master/text_measure','commit':entry['commit']})
print(json.dumps(output,ensure_ascii=False))

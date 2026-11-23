// User-approved draft delivery: locally editable layout defects are advisories.
// This is an issue policy, not a fabricated percentage score or missing-page quota.
export const MANUAL_LAYOUT_POLICY='USER-APPROVED EDITABLE DRAFT POLICY: The user accepts a roughly 70%-polished draft and will finish simple layout adjustments manually. Deliver every page with complete editable text. Localized text crossing decorative horizontal/vertical lines, slight text-box overlap, spacing or alignment imperfections are nonblocking manual-adjustment warnings; do not spend repairs or redraws solely on these. Use kind=manual_layout ONLY for such localized editable layout issues, with a concrete adjustment suggestion. Missing/wrong/duplicated source content, missing assets, clipped or substantially unreadable content, large text collisions, invalid geometry or uncertain/incomplete review remain separate blocking issues. Never combine them into a manual_layout finding. This policy overrides older instructions treating every collision as a hard failure.';

const hardDefect=/missing|omitt|wrong|incorrect|inaccurat|duplicat(?:ed|ion)?\s+(?:text|content|data)|(?:text|content|data)\s+duplicat|unreadab|illegib|clip|truncat|out.of.bounds|outside.{0,12}canvas|not\s+(?:fully\s+)?(?:readable|legible)|(?:不具备|没有|失去|丧失).{0,8}可读|无法看清|不能辨认|unknown|uncertain|not sure|hidden|obscured|occluded|completely|无法判断|不确定|完全盖住|完全遮挡|大面积|large.{0,20}(?:overlap|collision)|severe|substantial|漏字|漏文|缺字|缺文|缺少|缺失|错字|错误|内容重复|文字重复|重复文本|乱码|不可读|无法阅读|无法辨认|看不清|大面积|严重|裁切|裁剪|截断|越界|溢出|超出画布/i;
const lineCollision=text=>/(?:文字|正文|文本|说明|段落|这一行|text|paragraph|sentence)/i.test(text)&&/(?:背景.*线|装饰线|横线|竖线|框线|水平线|垂直线|decorative.{0,16}line|background.{0,16}line|horizontal.{0,16}line|vertical.{0,16}line)/i.test(text)&&/(?:穿过|穿字|贯穿|重叠|相交|压住|压字|遮挡|cross|overlap|intersect)/i.test(text);
export function isManualLayoutFinding(issue){
 const text=[issue?.description,issue?.suggested_fix,issue?.message,issue?.evidence].filter(v=>typeof v==='string').join(' ');
 if(!text.trim()||hardDefect.test(text))return false;
 if(issue.kind==='background-line-overlap')return true;
 if(issue.kind==='overlap')return Number.isFinite(issue.overlapRatio)&&issue.overlapRatio>0&&issue.overlapRatio<=.3;
 if(issue.kind==='manual_layout'){const observation=[issue.description,issue.message,issue.evidence].filter(v=>typeof v==='string').join(' ');return lineCollision(text)||/(?:localized|slight|minor|light|readable|轻微|局部|可读|间距|对齐|spacing|alignment)/i.test(observation);}
 return ['readability','typography','other',undefined].includes(issue.kind)&&lineCollision(text);
}
export function applyManualLayoutIssues(issues){
 return issues.map(issue=>isManualLayoutFinding(issue)?{...issue,severity:'warning',manualAdjustment:true}:{...issue});
}
export function acceptManualLayoutViolations(verdict){
 const accepted=verdict.violations.filter(isManualLayoutFinding);
 if(!accepted.length)return verdict;
 const violations=verdict.violations.filter(issue=>!isManualLayoutFinding(issue));
 return {...verdict,violations,matches:violations.length===0,advisories:[...(verdict.advisories||[]),...accepted.map(issue=>({...issue,manualAdjustment:true}))]};
}

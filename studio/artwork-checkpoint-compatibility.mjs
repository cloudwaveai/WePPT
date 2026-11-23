// Only the 2026-11-16 similarity-policy relaxation is compatible with existing artwork.
// Rebuild the exact previous prompt; never trust a checkpoint fingerprint on its own.
const pairs=[
  [
    "- 同一套模板、同一份PPT的所有页面类型允许保持相似版式、主体构图、网格、图文比例及阅读路径。纯布局相似只作提示，不阻断生成或交付，不要求为避开相似性而重画、重排或擅改内容。",
    "- 正文按内容变化布局，不能只有封面、目录和结尾不同而正文全部套同一版式。同类章节页（role=chapter）允许统一版式，不因章节页之间主体构图相似返工；此例外不扩展到正文、数据、流程或混合角色页面。"
  ],
  [
    "- 生成前通览整稿，为每页确定核心信息、内容关系、空间分区、主视觉位置、图文比例和阅读路径；优先适合内容与清楚可读。同一模板可以复用合适布局；分页、续页、新增和失败重试同样适用。",
    "- 生成前通览整稿，为每页确定核心信息、内容关系、空间分区、主视觉位置、图文比例和阅读路径；对照全稿已用及计划中的构图，为正文页设计可辨认的独立布局；同类章节页可沿用统一版式。分页、续页、新增和失败重试同样适用。"
  ],
  [
    "F. 布局与可读性：查看整稿实际缩略图，并放大疑似漏字、错字、遮挡、裁切、越界或不可读的页面核对。纯版式相似不属于失败，可保留提示；不得据此强制重排或重画。混有实际内容或可读性缺陷时单独报告并修复真实缺陷。未做整稿视觉核对不得宣称已通过；局部文字/对象编辑不触发整稿重排。",
    "F. 布局差异：查看整稿实际缩略图，并放大疑似重复页核对主体分区、主视觉、图文比例及阅读路径；逐页与全稿比较，记录重复页码和相似骨架。同类章节页的统一版式不属于重复布局失败；正文或混合角色的真实重复布局须在授权范围内重新设计对应页；仅换配色或文案不能通过。未做整稿视觉核对时不得宣称“正文布局差异已通过”，规则加载本身不等于视觉验收通过。局部文字/对象编辑不触发整稿重排。"
  ]
];
export function previousSimilarityRules(rules){
 if(typeof rules!=='string')return null;
 let result=rules;
 for(const [current,previous] of pairs){
  if(result.split(current).length!==2||result.includes(previous))return null;
  result=result.replace(current,previous);
 }
 return result;
}

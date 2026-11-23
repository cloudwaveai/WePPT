export const EDITOR_SYSTEM_RULES='编辑器系统约束：新增、插入、拆分及替换页面必须沿用当前已确认整套模板的真实背景、字体与配色，不能退回仅颜色相近的通用版式。除非用户明确选择更换模板，不得改变模板。原文、事实、数字与用户素材保持；只处理授权范围。建议或提问不得自动修改。明确的文字/样式小改动不应触发整页重新设计。';
export const usesDesignedTemplate=project=>['svg','slidev','pptagent'].includes(project?.designEngine)||(project?.pages||[]).some(p=>p.engine==='ppt-master-svg');
export function assertTemplateInheritance(project,page){
 if(!usesDesignedTemplate(project))return;
 if(!page||page.engine!=='ppt-master-svg'||page.themeId!==project.themeId)throw Error('当前模板尚无可继承的完整页面，请先完成一页设计；本次没有使用其他样式代替。');
}
export function assertGeneratedTheme(page,themeId){
 if(page.themeId&&page.themeId!==themeId)throw Error('生成页面的模板不一致，本次结果未应用。');
}

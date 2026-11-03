"""Browsing purposes are independent of a slide's position in the deck."""

CATEGORIES = {
    'cover': '封面', 'toc': '目录', 'chapter': '章节过渡',
    'argument': '观点与说明', 'compare': '并列与对比',
    'process': '流程与计划', 'structure': '架构与关系',
    'data': '数据与图表', 'product': '产品与系统',
    'case': '案例与证据', 'people': '人物与团队',
    'gallery': '照片与标识', 'ending': '结束页',
}

_SOURCE_CATEGORIES = {
    '封面': 'cover', '目录': 'toc', '章节': 'chapter', '结束': 'ending',
    '定义说明': 'argument', '并列对比': 'compare', '流程': 'process',
    '时间线': 'process', '课程矩阵': 'process', '中心关系': 'structure',
    '图表数据': 'data', '系统证据': 'product', '单案例': 'case',
    '双案例': 'case', '多案例': 'case', '人物介绍': 'people',
    '照片': 'gallery', '伙伴标识': 'gallery',
}


def browsing_category(template):
    # Reference purpose follows the approved original, not its adaptation layout.
    source = template.get('sourceCategory')
    if source in _SOURCE_CATEGORIES:
        return _SOURCE_CATEGORIES[source]
    role = template.get('role')
    if role in {'cover', 'toc', 'chapter', 'ending'}:
        return role
    tid = template.get('variantOf', template['id'])
    if tid in {'team-two', 'team-grid', 'roles'}:
        return 'people'
    if tid in {'photo-story', 'grid', 'portfolio-grid', 'uneven-images', 'parallel-aspect'}:
        return 'gallery'
    if tid in {'before-after', 'before-after-case'}:
        return 'compare'
    family = template.get('family')
    return 'case' if family == 'proof' else family if family in CATEGORIES else 'argument'


def annotate_category(template):
    category = browsing_category(template)
    template.update(browseCategory=category, browseCategoryName=CATEGORIES[category],
                    browseCategoryOrder=list(CATEGORIES).index(category))

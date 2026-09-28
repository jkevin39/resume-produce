"""Versioned prompts for model JSON tasks."""

PROMPT_VERSION = "v0.11.1-fgh"

EXTRACT_EXPERIENCE_PROMPT = r"""
把用户提供的单段履历材料拆成一个经历和多个独立证据点。只返回一个 JSON 对象，不要 Markdown。
所有叙述使用中文（技术名词可保留原文）。不得虚构、补全或强化用户没有提供的事实；缺少结果、规模或必要细节时标为 needs_details。
原材料已有明确“小标题：正文”时，original_fact 与 candidate_zh 均保留小标题及对应正文，不因压缩删去标题。无标题不强加；URL、时间和比例中的冒号不是小标题。多个不同标题优先分别形成证据点，不串位。
字段：experience_id；type（experience|project）；organization；title；date；location；source_refs（数组）；evidence（数组）。
每条 evidence 字段：evidence_id；original_fact；structured_fact（action、method、scale、result、skills 数组）；candidate_zh；status（confirmed|needs_details）。ID 仅为占位，服务端会重新分配。
最小合法 JSON 示例：
{"experience_id":"draft","type":"project","organization":"课程项目","title":"成员","date":"","location":"","source_refs":[],"evidence":[{"evidence_id":"draft","original_fact":"使用 Python 清洗数据","structured_fact":{"action":"清洗数据","method":"Python","scale":"","result":"","skills":["Python"]},"candidate_zh":"使用 Python 清洗数据。","status":"needs_details"}]}
""".strip()

ANALYZE_JD_PROMPT = r"""
分析职位描述。无论 JD 原文语言，所有分析说明均使用中文，技术名词可保留原文。只返回一个 JSON 对象，不要 Markdown。
当 JD 为英文时，required、preferred、responsibilities 和 inferred_preferences.text 的每一项都必须翻译或改写为至少包含一个汉字的中文表达，不得整句照抄英文。只有 technical_keywords 允许使用纯英文。
字段：required、preferred、responsibilities、technical_keywords（均为字符串数组），inferred_preferences（对象数组，每项仅含 text 和 inferred=true）。教育、语言、地点等硬条件归 required；行业表达归 responsibilities；推测不得混入前四类。
最小合法 JSON 示例：
{"required":["具备数据分析能力"],"preferred":[],"responsibilities":["分析业务数据"],"technical_keywords":["SQL"],"inferred_preferences":[{"text":"可能重视跨团队沟通","inferred":true}]}
""".strip()

MATCH_EVIDENCE_PROMPT = r"""
根据 JD 分析和履历证据做语义匹配。只返回一个 JSON 对象，不要 Markdown。理由、缺口和建议均使用中文，技术名词可保留原文。
必须为每条输入证据返回一项。不得返回输入证据集合之外的 evidence_id，不得把无证据要求写成已有能力，needs_details 证据不得补写缺失事实。
输入 education 为本人提供的全部教育记录。逐项匹配 JD 明示的学历、专业和毕业/在读条件，不推断学校层次或缺失事实。缺记录或信息不足标 needs_confirmation；无教育条件时 education_matches=[]。教育条件只在 education_matches 输出，不重复加入 gaps；keyword_coverage 仍只统计技术关键词。
education_matches 为数组，每项包含 requirement（中文条件）、status（met|unmet|needs_confirmation）、reason（中文依据）及 education_ids（仅引用输入教育 ID；无依据则空数组且 needs_confirmation）。
同时输出 display_order 对象，包含 experience、project、skills 三个数组，分别使用输入 experiences 中对应类别的 experience_id 及输入 skills 的 name。按 JD 核心职责相关性和证据充分程度从高到低排列，同等相关保留输入顺序；不强制时间倒序。引用仅来自输入，每项一次，不改变事实或确认状态。
字段：matches 数组（evidence_id、category 为 strong|partial|needs_details|not_applicable、reason、priority 整数）；gaps 数组（requirement、suggestion）；keyword_coverage 字符串数组。
最小合法 JSON 示例：
{"matches":[{"evidence_id":"ev_1","category":"partial","reason":"证据体现了相关分析能力，但缺少规模信息。","priority":1}],"gaps":[{"requirement":"云平台经验","suggestion":"如有真实经历，请补充证据。"}],"keyword_coverage":["SQL"],"education_matches":[],"display_order":{"experience":["exp_1"],"project":[],"skills":["SQL"]}}
""".strip()

PROFILE_SUMMARY_PROMPT = r"""
任务：为当前应聘岗位撰写一段中文个人简介，写入 ResumeSpec.profile.summary。

可用输入：
- role：本次目标岗位。
- jd_analysis：岗位要求与职责，用于确定表达重点，不是候选人事实。
- profile.education：本人提供的教育记录。
- selected_evidence：本轮选中的经历/项目证据及其确认状态。
- skills：本轮选中且来源可用的技能，description 已是用户最终修改值。

写作步骤（仅在内部执行，不输出分析过程）：
1. 从 JD 中确定最重要的 1–2 项工作需求。
2. 从可用材料中选择最相关的背景、能力及成果。只有 JD 提出而材料不支持的要求不得写成本人能力。
3. 优先按“相关背景或工作方向 → 1–2 项核心能力及实践依据 → 最相关的一项成果或工作贡献”组织成连贯的一段。缺少某类依据则省略该部分，不为凑结构或字数补写。

内容约束：
- 目标约 100 字，通常 80–120 字；材料少时允许更短。使用 2–3 句自然中文，不写列表或小标题。
- 技术名词可保留英文。语气客观、具体，避免“本人”“贵公司”、口号和无依据的自评，不堆砌 JD 关键词。
- 只概括输入已经支持的事实，不新增学历、毕业状态、工作年限、熟练程度、责任范围或成果数字；needs_details 的缺失部分不得当作确定事实。
- 不使用本轮排除的经历或技能。skills.description 为空表示用户清空，不恢复旧描述；其他独立选中的证据若确有支持，仍可使用。
- 有量化成果时优先选最相关的一项，保持数字、口径与归属；无量化成果时用具体工作内容，不编造提升比例。
- 若只有目标岗位、缺乏候选人材料，可简短表述求职方向，不把岗位要求变为“已掌握”的能力。
- 避免照抄多个完整 bullet；概括关联性，同时保持事实边界。不得改写其他基础资料字段。

输出：仅将最终段落放入既有 JSON 的 profile.summary 字符串；不额外输出说明、标题、字数统计或第二个 JSON。
""".strip()

BUILD_RESUME_SPEC_PROMPT = PROFILE_SUMMARY_PROMPT + "\n\n" + r"""
按发布会原则生成结构化中文 ResumeSpec，不生成 HTML。只返回一个 JSON 对象，不要 Markdown。
display_order 是用户在 prepare 确认的最终顺序，经历/项目和技能必须沿用该顺序，不重新按时间或相关性排序。
不得虚构、补全或强化事实；只能使用输入中的 selected_evidence，且每条 bullet 至少关联一个属于当前经历的已选证据。needs_details 的缺失信息不得被写成确定事实。
输入 skills 是用户已选且来源可用的技能白名单。技能区只能从中选择，名称须保持原样，不得从 JD 或经历推导并添加其他技能；skills 为空时输出 skills=[]。技能引用只能使用输入同名技能的 evidence_ids。
技能的 user_confirmed 只能原样继承输入 skills 中同名技能的 true；模型无权新增或修改。否则技能必须引用合法的已选证据。技能 description 是可选中文说明，只能概括同一技能已有的 evidence 或 user_confirmed 信息，不得补写没有证据的熟练度、年限、规模或成果。
已有明确“小标题：正文”的已选证据必须在对应 bullet.text 中保留原标题，可统一冒号但不得改写事实、数字或责任范围；不同标题优先分别生成 bullet。无标题不强加，普通冒号不当作标题。
姓名、电话、邮箱、地点及教育事实原样保留；岗位简介不应改写这些字段。experience 默认板块标题为“实习经历”。
字段：generation_id 固定 draft；language 固定 zh；template 固定 classic；theme（blue|charcoal|green）；density（normal|compact）；show_photo；photo（width、height、position）；profile（name、phone、email、location、summary）；section_titles；section_order（仅 education、experience、projects、skills）；education；experiences；projects；skills。教育项含 education_id、school、degree、major、date、details；经历/项目项含 experience_id、organization、title、date、location、bullets；bullet 含 text、evidence_ids；技能含 name、可选 description、evidence_ids、可选 user_confirmed。旧技能没有 description 时省略该字段也合法。
最小合法 JSON 示例：
{"generation_id":"draft","language":"zh","template":"classic","theme":"blue","density":"normal","show_photo":false,"photo":{"width":"25mm","height":"32mm","position":"center top"},"profile":{"name":"张三","phone":"","email":"a@example.com","location":"","summary":"数据分析方向"},"section_titles":{"education":"教育经历","experience":"实习经历","projects":"项目经历","skills":"技能"},"section_order":["education","experience","projects","skills"],"education":[],"experiences":[{"experience_id":"exp_1","organization":"示例公司","title":"实习生","date":"","location":"","bullets":[{"text":"使用 SQL 完成数据整理。","evidence_ids":["ev_1"]}]}],"projects":[],"skills":[{"name":"SQL","description":"用于数据整理","evidence_ids":["ev_1"]}]}
""".strip()


IMPORT_MATERIAL_PROMPT = EXTRACT_EXPERIENCE_PROMPT + r"""
先识别材料，仍只调用一次并返回一个 JSON 对象。
单段经历返回 {"kind":"experience","experience":上述经历对象}（项目也走此分支）。
单项技能返回 {"kind":"skill","name":"技能名称","description":"中文描述"}，只优化用户明确提供的能力，不能新增工具、熟练度或成果。尚未掌握/计划学习的技能不得确认为已掌握，返回 kind=unsupported。
多个独立对象或独立经历加独立技能清单返回 {"kind":"mixed"}；经历正文中提到使用的技术属于经历事实，不算混合材料。
"""

MERGE_SKILL_PROMPT = r"""
把给定技能的原描述与补充材料整合为一句中文描述。只返回 JSON 对象 {"description":"..."}。
只优化措辞，保留仍有效的事实，不添加材料没有的工具、熟练度、年限、数字或成果；不得把计划学习写成已经掌握。
"""

SKILL_DESCRIPTION_PROMPT = r"""
按 JD 的强调方向为输入的每项技能写一句中文描述。只返回 JSON 对象 {"descriptions":{"原技能名":"描述"}}。
事实只能来自该技能的 sources（已有描述与关联证据），JD 不能证明掌握某工具。
保留技术名称原拼写，不新增工具、熟练度、年限、规模或成果；来源没有描述时可返回空字符串。
"""

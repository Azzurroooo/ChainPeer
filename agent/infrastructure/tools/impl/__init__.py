"""Default tool implementations and generated schemas."""

from __future__ import annotations

from typing import Any, Callable

from .core import build_tool_schemas
from .tools import (
    bash,
    bash_output,
    edit_file,
    fetch_web_page,
    grep,
    kill_shell,
    list_files,
    plan_add_step,
    plan_close,
    plan_create,
    plan_get,
    plan_link_dependency,
    plan_next,
    plan_record_observation,
    plan_reorder,
    plan_update_meta,
    plan_update_step,
    read_file,
    read_pdf,
    search_web,
    skill_create,
    write_file,
    wq_build_generation_prompt,
    wq_crossover_alpha,
    wq_distill_insight,
    wq_evaluate_alpha,
    wq_list_data_fields,
    wq_list_directions,
    wq_list_library,
    wq_list_my_alphas,
    wq_list_operators,
    wq_login,
    wq_memory_snapshot,
    wq_mutate_alpha,
    wq_simulate_alpha,
    wq_submit_alpha,
)

TOOLS: dict[str, Callable] = {
    "read_file": read_file,
    "read_pdf": read_pdf,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "grep": grep,
    "bash": bash,
    "bash_output": bash_output,
    "kill_shell": kill_shell,
    "plan_create": plan_create,
    "plan_get": plan_get,
    "plan_add_step": plan_add_step,
    "plan_update_meta": plan_update_meta,
    "plan_record_observation": plan_record_observation,
    "plan_update_step": plan_update_step,
    "plan_link_dependency": plan_link_dependency,
    "plan_reorder": plan_reorder,
    "plan_next": plan_next,
    "plan_close": plan_close,
    "skill_create": skill_create,
    "search_web": search_web,
    "fetch_web_page": fetch_web_page,
    # WorldQuant Brain alpha mining tools
    "wq_login": wq_login,
    "wq_list_operators": wq_list_operators,
    "wq_list_data_fields": wq_list_data_fields,
    "wq_list_directions": wq_list_directions,
    "wq_memory_snapshot": wq_memory_snapshot,
    "wq_build_generation_prompt": wq_build_generation_prompt,
    "wq_simulate_alpha": wq_simulate_alpha,
    "wq_evaluate_alpha": wq_evaluate_alpha,
    "wq_distill_insight": wq_distill_insight,
    "wq_list_library": wq_list_library,
    "wq_list_my_alphas": wq_list_my_alphas,
    "wq_submit_alpha": wq_submit_alpha,
    "wq_mutate_alpha": wq_mutate_alpha,
    "wq_crossover_alpha": wq_crossover_alpha,
}

_TOOL_SCHEMA_META: dict[str, dict[str, Any]] = {
    "read_file": {
        "description": "读取文本文件内容，支持行号和分页读取。Agent应通过此工具查看代码上下文。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "offset": "起始行号（默认 1）",
            "limit": "最多读取的行数（默认 1000 行，避免大文件超出上下文）",
        },
    },
    "read_pdf": {
        "description": "解析PDF文件内容，支持文字版和扫描版PDF。提取结构化文本（标题、段落）、表格（Markdown格式）。分页返回，每次最多30页。扫描版PDF自动使用OCR。",
        "param_descriptions": {
            "file_path": "PDF文件路径",
            "start_page": "起始页码（默认1）",
            "end_page": "结束页码（默认到文件末尾，每次最多30页）",
            "force_ocr": "强制使用OCR（用于编码异常的文字PDF，默认False）",
        },
    },
    "write_file": {
        "description": "写入内容到文件（警告：此操作会完全覆盖原文件。修改已有大文件时请使用 edit_file）",
        "param_descriptions": {"file_path": "文件路径", "content": "内容"},
    },
    "edit_file": {
        "description": "精准替换文件中的文本块 (Search and Replace)。适用于修改已有文件，避免输出整个文件。必须保证 old_str 与文件中的文本完全一致（包括空格和缩进）。如果匹配到多处，将拒绝替换。",
        "param_descriptions": {
            "file_path": "文件绝对或相对路径",
            "old_str": "需要被替换的原文块。建议包含上下文以确保唯一。",
            "new_str": "用来替换 old_str 的新文本块。",
        },
    },
    "grep": {
        "description": "在文件中搜索正则表达式模式 (Search)。返回匹配的文件路径、行号和内容。这是查找代码定义、引用或特定模式的首选工具。",
        "param_descriptions": {
            "pattern": "要搜索的正则表达式 (Python re syntax)",
            "path": "搜索的根目录 (默认为当前目录 .)",
            "glob_pattern": "文件匹配模式 (如 **/*.py, src/*.ts)。默认为 **/*。",
            "case_sensitive": "是否区分大小写 (默认为 False)",
            "max_results": "最大返回结果数 (默认为 50)",
        },
    },
    "list_files": {
        "description": "列出目录中的文件（树形结构）",
        "param_descriptions": {
            "directory": "目录路径",
            "pattern": "文件匹配模式",
            "recursive": "是否递归",
            "max_depth": "最大深度",
        },
    },
    "bash": {
        "description": "执行 Shell 命令。支持 cd 保持目录状态。设置 run_in_background=true 可启动后台进程（如 npm start、uvicorn），用 bash_output 查看输出。",
        "param_descriptions": {
            "command": "要执行的命令",
            "run_in_background": "以后台模式运行（不等待完成，适合启动服务器等长期命令）。默认 False。",
        },
    },
    "bash_output": {
        "description": "读取后台进程的输出，或终止它。用于查看 bash(run_in_background=true) 启动的后台进程。",
        "param_descriptions": {
            "bg_id": "后台进程 ID（bash 返回的 bg_id）",
            "kill": "设为 true 可终止该进程。默认 False（仅读取输出）。",
        },
    },
    "kill_shell": {"description": "重置 Shell 会话状态"},
    "plan_create": {
        "description": "创建一个 DAG 计划（支持并行步骤与阻塞），可携带长期目标、约束和指标。不要直接编辑 plan.json。",
        "param_descriptions": {
            "title": "计划标题",
            "goal": "计划目标",
            "steps": "步骤数组，每项含 title/depends_on/priority 等字段",
            "expected_version": "可选版本号。已有计划时用于乐观锁校验。",
            "objectives": "可选长期目标数组，如 annual_return >= 0.10。",
            "constraints": "可选约束数组，如 max_drawdown <= 0.12。",
            "metrics": "可选当前指标快照对象。",
        },
    },
    "plan_get": {"description": "读取当前会话计划。", "param_descriptions": {"plan_id": "可选计划 ID，用于校验读取对象。"}},
    "plan_add_step": {
        "description": "向当前 active plan 追加一个新步骤。用于长期迭代任务中新实验、新假设或后续修复。必须使用 expected_version，不要直接编辑 plan.json。",
        "param_descriptions": {
            "title": "新增步骤标题，必填且非空",
            "description": "步骤说明",
            "step_id": "可选步骤 ID；不填则自动生成",
            "depends_on": "依赖的已有步骤 ID 数组",
            "priority": "优先级，数字越大越优先",
            "owner": "负责人或执行者标签",
            "acceptance": "验收标准",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_update_meta": {
        "description": "更新当前 active plan 的长期目标、约束、最新指标或摘要。必须使用 expected_version，不要直接编辑 plan.json。",
        "param_descriptions": {
            "expected_version": "必填版本号，用于乐观锁",
            "goal": "可选新的全局目标文本",
            "objectives": "可选目标数组，整体替换 objectives",
            "constraints": "可选约束数组，整体替换 constraints",
            "metrics": "可选指标对象，将 merge 到现有 metrics，并同步 current",
            "summary": "可选计划摘要",
        },
    },
    "plan_record_observation": {
        "description": "记录一次实验、回测或验证观察，并可同步最新指标。必须使用 expected_version，不要直接编辑 plan.json。",
        "param_descriptions": {
            "summary": "观察结论，必填且非空",
            "expected_version": "必填版本号，用于乐观锁",
            "step_id": "可选关联步骤 ID",
            "metrics": "可选本次观察得到的指标对象",
            "hypothesis": "可选下一步假设",
            "next_action": "可选建议下一步动作",
            "tags": "可选标签数组",
        },
    },
    "plan_update_step": {
        "description": "更新步骤状态或字段（严格状态机 + 乐观锁）。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "patch": "变更对象（如 status/blocked_reason/priority 等）",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_link_dependency": {
        "description": "更新步骤依赖关系并校验环路。",
        "param_descriptions": {
            "step_id": "步骤 ID",
            "depends_on": "依赖步骤 ID 数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_reorder": {
        "description": "重排步骤展示顺序（不改变依赖）。",
        "param_descriptions": {
            "step_orders": "完整的步骤 ID 顺序数组",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "plan_next": {
        "description": "获取下一步建议或并行可执行集合。",
        "param_descriptions": {
            "mode": {"description": "ready|focus|blocked_report", "enum": ["ready", "focus", "blocked_report"]},
            "expected_version": "可选版本号，用于一致性校验",
        },
    },
    "plan_close": {
        "description": "在所有步骤完成后关闭计划。",
        "param_descriptions": {
            "summary": "计划完成总结",
            "expected_version": "必填版本号，用于乐观锁",
        },
    },
    "skill_create": {
        "description": "创建格式正确的 Quanora Skill。自动写入 .quanora/skills/<name>/SKILL.md 或用户级 ~/.quanora/skills/<name>/SKILL.md，并生成稳定的 frontmatter。",
        "param_descriptions": {
            "name": "Skill 名称。只能包含字母、数字、下划线和连字符。",
            "description": "Skill 的简短说明，写入 frontmatter，用于上下文中的 skill index。",
            "body": "SKILL.md 正文指令内容。",
            "triggers": "可选触发短语列表。为空时写入 triggers: []。",
            "scope": {"description": "写入范围：project 写到当前项目，user 写到用户目录。默认 project。", "enum": ["project", "user"]},
            "overwrite": "是否覆盖已存在的 SKILL.md。默认 False。",
        },
    },
    "search_web": {
        "description": "搜索互联网信息。支持多搜索引擎自动切换（Bing/Baidu/DDG），适用于中英文内容查询，中国大陆可用。",
        "param_descriptions": {"query": "搜索关键词（支持中英文）", "max_results": "最大结果数 (默认 5)"},
    },
    "fetch_web_page": {
        "description": "抓取并提取网页主要内容（自动去除导航、广告等干扰，输出Markdown）。通常在 search_web 返回 URL 后使用。",
        "param_descriptions": {"url": "网页 URL"},
    },
    # ──────────────────────────────────────────────────────────────────
    # WorldQuant Brain — 自演进 alpha 挖掘工具集 (Ralph Loop)
    # ──────────────────────────────────────────────────────────────────
    "wq_login": {
        "description": "登录 WorldQuant Brain 平台。凭证解析优先级：函数参数 > 环境变量 WQ_BRAIN_EMAIL/WQ_BRAIN_PASSWORD > ./credential.txt。登录后 token 在 client 单例内复用。",
        "param_descriptions": {
            "email": "可选邮箱；为空时自动从环境变量/credential.txt 读取",
            "password": "可选密码；为空时自动从环境变量/credential.txt 读取",
        },
    },
    "wq_list_operators": {
        "description": "列出 WorldQuant Brain 平台可用算子。use_cache=True 时返回零网络的内置精选清单，可直接用于生成 alpha 表达式。",
        "param_descriptions": {"use_cache": "True 走内置清单（默认），False 在线拉取"},
    },
    "wq_list_data_fields": {
        "description": "列出 Brain 数据字段。use_cache=True 时返回零网络的内置精选清单；否则按 region/universe/delay 在线查询。",
        "param_descriptions": {
            "region": "市场区域，默认 USA",
            "universe": "股票池，默认 TOP3000",
            "delay": "数据 delay，默认 1",
            "search": "可选关键字过滤",
            "use_cache": "True 走内置清单（默认），False 在线查询",
            "limit": "在线查询时的最大返回条数（默认 50）",
        },
    },
    "wq_list_directions": {
        "description": "列出内置的研究方向库（diversified planning 候选池），如 reversal_short_term、momentum_mid_term 等。",
    },
    "wq_memory_snapshot": {
        "description": "读取 Experience Memory 当前快照（state / P_succ / P_fail / Insights / 库内 Top Sharpe），供 LLM 在生成新 alpha 前阅读。",
        "param_descriptions": {
            "tags": "可选标签数组，仅返回带这些 tag 的记忆",
            "succ_k": "返回多少条成功模板（默认 5）",
            "fail_k": "返回多少条失败禁区（默认 5）",
            "insight_k": "返回多少条策略洞见（默认 3）",
        },
    },
    "wq_build_generation_prompt": {
        "description": "构造一份 alpha 生成 prompt。LLM 阅读后可直接在自己的思考里产出 JSON 数组，然后用 wq_evaluate_alpha 批量评估。无需二次 LLM 调用。",
        "param_descriptions": {
            "direction_key": "DIRECTION_LIBRARY 中的方向 key（默认 reversal_short_term）",
            "hypothesis": "可选自然语言假设",
            "n": "希望生成的 alpha 数量（默认 5）",
            "custom_direction": "可选自定义方向对象，覆盖 direction_key",
        },
    },
    "wq_simulate_alpha": {
        "description": "提交单条 alpha 到 Brain 平台执行模拟，默认等待结果。返回原始 simulation payload（含 sharpe/fitness/turnover 等指标）。",
        "param_descriptions": {
            "expression": "Brain 语法的 alpha 表达式",
            "region": "市场区域，默认 USA",
            "universe": "股票池，默认 TOP3000",
            "delay": "数据 delay，默认 1",
            "decay": "decay 参数，默认 0",
            "neutralization": "中性化方式（INDUSTRY/MARKET/SECTOR/NONE 等），默认 INDUSTRY",
            "truncation": "截断比例，默认 0.08",
            "wait": "是否等待 simulation 完成，默认 True",
            "max_wait_seconds": "等待超时（秒），默认 600",
        },
    },
    "wq_evaluate_alpha": {
        "description": "对单条 alpha 跑完整 Stage1-4 评估管线（本地门控 + Brain 模拟 + 阈值检查 + 去重），通过则可选 admit 入库并自动写入 P_succ。返回 passed/stage_failed/reason/alpha_id/metrics/checks/admitted。",
        "param_descriptions": {
            "expression": "Brain 语法的 alpha 表达式",
            "direction_tag": "可选方向标签，用于记录 provenance",
            "region": "市场区域，默认 USA",
            "universe": "股票池，默认 TOP3000",
            "delay": "数据 delay，默认 1",
            "decay": "decay 参数，默认 0",
            "neutralization": "中性化方式，默认 INDUSTRY",
            "truncation": "截断比例，默认 0.08",
            "min_sharpe": "Sharpe 门槛，默认 1.25",
            "min_fitness": "Fitness 门槛，默认 1.0",
            "max_turnover": "Turnover 上限，默认 0.7",
            "admit_to_library": "通过后是否自动 admit 到本地库，默认 True",
        },
    },
    "wq_distill_insight": {
        "description": "把本轮挖掘的策略级教训沉淀到 Experience Memory 的 Insights（I）。是 Ralph Loop 的 Distill 阶段。",
        "param_descriptions": {
            "insight": "自然语言教训，如 'ts_rank 在窗口>60 时易出现 NaN'",
            "category": "operator|data_field|regime|general（默认 general）",
            "severity": "info|warning|critical（默认 info）",
            "tags": "可选关联方向标签数组",
        },
    },
    "wq_list_library": {
        "description": "列出本地 alpha 库（包含 Brain 返回的 metrics 和 state），支持按最低 Sharpe 过滤。",
        "param_descriptions": {
            "min_sharpe": "最低 Sharpe 过滤（0 表示不过滤）",
            "limit": "返回条数上限，默认 50",
        },
    },
    "wq_list_my_alphas": {
        "description": "查询当前账户在 Brain 平台上的 alpha 列表（区别于本地库；Brain 端是权威 source of truth）。",
        "param_descriptions": {
            "status": "可选状态过滤（如 UNSUBMITTED/SUBMITTED 等）",
            "limit": "分页大小，默认 50",
            "offset": "分页偏移，默认 0",
        },
    },
    "wq_submit_alpha": {
        "description": "提交某个已经通过质量检查的 alpha 到 Brain 比赛。注意 Brain 平台有每日提交配额，谨慎使用。",
        "param_descriptions": {"alpha_id": "Brain 平台上的 alpha ID"},
    },
    "wq_mutate_alpha": {
        "description": "对种子表达式做参数扰动（QuantaAlpha 的 Mutation 算子）：把表达式中第一个数值常量替换成候选窗口集中的每个值，生成 mutation 候选。",
        "param_descriptions": {
            "seed_expression": "种子 alpha 表达式",
            "window_candidates": "候选窗口期数组，默认 [5,10,20,30,60,120]",
            "max_variants": "最多生成多少变体，默认 6",
        },
    },
    "wq_crossover_alpha": {
        "description": "对两个表达式做交叉。策略：wrap_b_in_a（用 a 外层算子包 b）/ rank_pair（rank 相减）/ add_pair / corr_pair。",
        "param_descriptions": {
            "expression_a": "父表达式 A",
            "expression_b": "父表达式 B",
            "strategy": {
                "description": "交叉策略",
                "enum": ["wrap_b_in_a", "rank_pair", "add_pair", "corr_pair"],
            },
        },
    },
}

TOOL_SCHEMAS = build_tool_schemas(TOOLS, _TOOL_SCHEMA_META)

__all__ = ["TOOLS", "TOOL_SCHEMAS"]

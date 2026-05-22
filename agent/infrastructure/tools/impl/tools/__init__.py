"""Concrete tool implementations."""

from .bash import bash, bash_output, kill_shell
from .file_ops import edit_file, grep, list_files, read_file, write_file
from .pdf_ops import read_pdf
from .plan import (
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
)
from .skill import skill_create
from .web import fetch_web_page, search_web
from .worldquant import (
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

__all__ = [
    "bash",
    "bash_output",
    "kill_shell",
    "edit_file",
    "grep",
    "list_files",
    "read_file",
    "read_pdf",
    "write_file",
    "plan_add_step",
    "plan_create",
    "plan_get",
    "plan_record_observation",
    "plan_update_meta",
    "plan_update_step",
    "plan_link_dependency",
    "plan_reorder",
    "plan_next",
    "plan_close",
    "skill_create",
    "fetch_web_page",
    "search_web",
    # WorldQuant Brain alpha mining tools
    "wq_login",
    "wq_list_operators",
    "wq_list_data_fields",
    "wq_list_directions",
    "wq_memory_snapshot",
    "wq_build_generation_prompt",
    "wq_simulate_alpha",
    "wq_evaluate_alpha",
    "wq_distill_insight",
    "wq_list_library",
    "wq_list_my_alphas",
    "wq_submit_alpha",
    "wq_mutate_alpha",
    "wq_crossover_alpha",
]

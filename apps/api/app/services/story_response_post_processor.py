from collections.abc import Callable
from typing import Any

from app.llm.router import LLMGateway
from app.schemas.chat import StoryState
from app.schemas.llm import ChatMessage
from app.services.consistency_checker import check_response_consistency
from app.services.context_assembler import ContextAssembly


ChoiceParser = Callable[[str], list[str]]
ConsistencyCheck = dict[str, Any]
ConsistencyRevision = dict[str, Any]
ConsistencyChecker = Callable[[str, StoryState, ContextAssembly], ConsistencyCheck]
ConsistencyPolicyResult = tuple[str, ConsistencyCheck, ConsistencyRevision]


class StoryResponsePostProcessor:
    """Provider-backed response repair without persistence authority."""

    def __init__(self, llm_gateway: LLMGateway, choice_parser: ChoiceParser) -> None:
        self.llm_gateway = llm_gateway
        self.choice_parser = choice_parser

    def check_consistency(
        self, response_text: str, state: StoryState, context: ContextAssembly
    ) -> ConsistencyCheck:
        sections = context.preview.get("sections", {})
        return check_response_consistency(
            response_text,
            state,
            sections.get("canon_facts", []),
            sections.get("character", {}),
            sections.get("world", {}),
        )

    async def ensure_story_choices(
        self,
        interaction_mode: str,
        response_text: str,
        choices: list[str],
        context: ContextAssembly,
    ) -> list[str]:
        if interaction_mode != "choices" or len(choices) >= 2:
            return choices
        sections = context.preview.get("sections", {})
        messages = [
            ChatMessage(
                role="system",
                content=(
                    "你是互动小说选项编辑。根据已经完成的正文生成 3 个简短、具体、互斥的下一步行动选项。"
                    "选项必须由用户作出决定，不得替用户执行，不得包含自定义、Custom、Other。"
                    '只返回 JSON 对象：{"choices":["...","...","..."]}。'
                ),
            ),
            ChatMessage(
                role="developer",
                content=(
                    f"用户偏好：{sections.get('user_preferences', [])}\n"
                    f"小说 Prompt：{sections.get('story_prompt', '')}\n"
                    f"当前状态：{sections.get('state', {})}"
                ),
            ),
            ChatMessage(role="user", content=f"正文：\n{response_text[-5000:]}"),
        ]
        request = self.llm_gateway.request_for_purpose("normal_chat", messages).model_copy(
            update={
                "max_output_tokens": 500,
                "temperature": 0.55,
                "top_p": 0.88,
                "response_format": "json",
                "stream": False,
            }
        )
        try:
            response = await self.llm_gateway.generate(self.llm_gateway.normalize_request(request))
            return self.choice_parser(response.text)
        except Exception:
            return []

    async def apply_consistency_policy(
        self,
        response_text: str,
        state: StoryState,
        context: ContextAssembly,
        mode: str,
        *,
        consistency_checker: ConsistencyChecker | None = None,
    ) -> ConsistencyPolicyResult:
        checker = consistency_checker or self.check_consistency
        if mode == "off":
            check = {
                "status": "off",
                "issue_count": 0,
                "error_count": 0,
                "warning_count": 0,
                "highest_severity": None,
                "issues": [],
            }
            return (
                response_text,
                check,
                {
                    "attempted": False,
                    "accepted": False,
                    "reason": "checking_disabled",
                },
            )

        initial_check = checker(response_text, state, context)
        initial_error_count = self.consistency_error_count(initial_check)
        if mode != "auto" or initial_error_count == 0:
            return (
                response_text,
                initial_check,
                {
                    "attempted": False,
                    "accepted": False,
                    "reason": "manual_review" if initial_error_count else "check_passed",
                },
            )

        revision_request = self.llm_gateway.request_for_purpose(
            "consistency_check",
            self.build_consistency_revision_messages(response_text, initial_check, context),
        )
        revision_request = self.llm_gateway.normalize_request(
            revision_request.model_copy(
                update={
                    "max_output_tokens": min(max(revision_request.max_output_tokens, 1024), 4096),
                    "temperature": min(revision_request.temperature, 0.35),
                    "top_p": min(revision_request.top_p, 0.85),
                    "stream": False,
                }
            )
        )
        try:
            revised_response = await self.llm_gateway.generate(revision_request)
        except Exception:
            return (
                response_text,
                initial_check,
                {
                    "attempted": True,
                    "accepted": False,
                    "reason": "revision_failed",
                    "provider": revision_request.provider,
                    "model": revision_request.model,
                    "trigger": "high_severity_local_rule",
                    "initial_error_count": initial_error_count,
                    "initial_check": initial_check,
                },
            )
        revised_text = revised_response.text.strip()
        revised_check = checker(revised_text, state, context)
        final_error_count = self.consistency_error_count(revised_check)
        accepted = bool(revised_text) and final_error_count == 0
        return (
            revised_text if accepted else response_text,
            revised_check if accepted else initial_check,
            {
                "attempted": True,
                "accepted": accepted,
                "reason": "accepted_revision" if accepted else "kept_original",
                "provider": revision_request.provider,
                "model": revision_request.model,
                "trigger": "high_severity_local_rule",
                "initial_error_count": initial_error_count,
                "final_error_count": final_error_count,
                "initial_check": initial_check,
            },
        )

    @staticmethod
    def consistency_error_count(check: ConsistencyCheck) -> int:
        error_count = check.get("error_count")
        if isinstance(error_count, int) and not isinstance(error_count, bool):
            return max(error_count, 0)
        issues = check.get("issues")
        if not isinstance(issues, list):
            return 0
        return sum(isinstance(issue, dict) and issue.get("severity") == "error" for issue in issues)

    def build_consistency_revision_messages(
        self,
        response_text: str,
        consistency_check: ConsistencyCheck,
        context: ContextAssembly,
    ) -> list[ChatMessage]:
        sections = context.preview.get("sections", {})
        return [
            ChatMessage(
                role="system",
                content="你是小说连续性修订器。只输出修订后的正文，不解释修改过程，不输出 Markdown 标题。",
            ),
            ChatMessage(
                role="developer",
                content=(
                    "保留原文的叙事风格、段落节奏和剧情意图，仅修复列出的参数、人物、剧情或世界设定冲突。\n"
                    f"冲突：{consistency_check['issues']}\n"
                    f"场景状态：{sections.get('state', {})}\n"
                    f"角色档案：{sections.get('character', {})}\n"
                    f"世界规则：{sections.get('world', {})}\n"
                    f"既定事实：{sections.get('canon_facts', [])}"
                ),
            ),
            ChatMessage(role="user", content=response_text),
        ]

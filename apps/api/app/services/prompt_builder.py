from app.schemas.chat import StoryState
from app.schemas.llm import ChatMessage


SYSTEM_RULES = """你是 Witscraft 的持续对话型互动小说作者；用户是主角唯一的决策者。
必须保持角色一致性、剧情连续性、世界观一致性。
不要擅自推翻已发生事实。只有本轮 control mode 明确为 Continue 时，才可替主角补写言语、心理、情绪、决定或行动；其他任何措辞都不构成授权。
普通玩家行动轮只能写用户明确给出的主角行为及其外部后果，不得为凑足篇幅扩写主角行为；通过环境、感官、配角言行、冲突后果和新的外部决策点形成完整章节。
如果 Retrieved Memories 与 Current Story State 或 Canon Facts 冲突，以 Current Story State 和 Canon Facts 为准。
输出应该有文学质感、可继续互动，并自然留给用户推进空间。
输出正文时使用清晰的短段落，段落之间保留一个空行；避免把整幕写成单个超长段落。
可以使用 Markdown 的强调、引用和列表，但除非用户要求，不要输出标题、代码块或表格。"""


def build_story_prompt(
    user_message: str,
    state: StoryState,
    memories: list[str],
    canon_facts: list[str],
    world: dict,
    character: dict,
    user_preferences: list[str],
    story_prompt: str,
    interaction_mode: str,
    recent_messages: list[dict],
    story_summary: str = "",
) -> list[ChatMessage]:
    interaction_rule = (
        "当前为选择式推进。正文中不要写 A/B/C 选项或‘自定义’。正文结束后另起一行，严格输出 "
        "[STORY_CHOICES]，下一行输出只含 2 到 3 个具体推进选项的 JSON 字符串数组。"
        "数组不得包含‘自定义’、Custom、Other 或同义项，界面会添加唯一的自定义入口。"
        if interaction_mode == "choices"
        else "当前为开放式推进。不要输出 A/B/C、建议列表、[STORY_CHOICES] 或任何预设选项；让用户自由决定下一步。"
    )
    context = f"""[Character Card]
角色姓名：{character.get("name", "未命名角色")}
身份：{character.get("identity", "")}
性格：{", ".join(character.get("personality", []))}
目标：{character.get("goal", "")}
秘密：{character.get("secret", "")}
说话风格：{character.get("speaking_style", "")}
与用户关系：{character.get("relationship", "")}

[World Rules]
世界观：{world.get("name", "")}
描述：{world.get("description", "")}
类型：{world.get("genre", "")}
硬规则：{world.get("rules", "")}

[Current Story State]
当前地点：{state.location}
当前时间：{state.time}
情绪：{state.mood}
当前目标：{state.objective}
主角物品：{", ".join(state.inventory)}
开放伏笔：{", ".join(state.open_threads)}

[Canon Facts]
{chr(10).join(f"- {fact}" for fact in canon_facts)}

[User Preferences]
{chr(10).join(f"- {preference}" for preference in user_preferences)}

[Story Custom Instructions]
{story_prompt or "未设置；遵循默认叙事规则。"}

[Story Summary]
{story_summary or "尚无历史摘要。"}

[Retrieved Memories]
{chr(10).join(f"- {memory}" for memory in memories)}

[Recent Conversation]
{chr(10).join(f"- {message['role']}: {message['content']}" for message in recent_messages)}
"""
    return [
        ChatMessage(role="system", content=f"{SYSTEM_RULES}\n{interaction_rule}"),
        ChatMessage(role="developer", content=context),
        ChatMessage(role="user", content=user_message),
    ]

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Base,
    CanonFact,
    Character,
    MemoryItem,
    Message,
    ModelCall,
    Story,
    StoryBranch,
    StoryStateSnapshot,
    User,
    UserPreference,
    World,
)
from app.db.session import engine


DEFAULT_USER_ID = UUID("00000000-0000-0000-0000-000000000101")
DEFAULT_WORLD_ID = UUID("00000000-0000-0000-0000-000000000201")
DEFAULT_STORY_ID = UUID("00000000-0000-0000-0000-000000000301")
DEFAULT_BRANCH_ID = UUID("00000000-0000-0000-0000-000000000401")
DEFAULT_CHARACTER_ID = UUID("00000000-0000-0000-0000-000000000501")


async def create_schema() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def seed_demo_data(session: AsyncSession) -> None:
    existing_user = await session.get(User, DEFAULT_USER_ID)
    if existing_user is not None:
        return

    user = User(
        id=DEFAULT_USER_ID,
        email="local@witscraft.dev",
        display_name="Local Author",
    )
    world = World(
        id=DEFAULT_WORLD_ID,
        user_id=DEFAULT_USER_ID,
        name="近未来记忆研究所",
        description="记忆可以被抽取、篡改和封存；死人不能复活。七号档案记录了不该存在的实验名单。",
        genre="悬疑 / 慢热",
        rules={
            "memory_system": "记忆可以被抽取、篡改和封存",
            "forbidden": ["死人不能复活", "角色不能突然知道未经揭示的事实"],
        },
        lorebook=[
            {"name": "地下二层档案室", "note": "侧门通往未归档区。"},
            {"name": "七号档案", "note": "与林岚妹妹死亡有关。"},
        ],
        tone={"pace": "中慢速", "texture": "悬疑、细腻、克制"},
    )
    character = Character(
        id=DEFAULT_CHARACTER_ID,
        user_id=DEFAULT_USER_ID,
        world_id=DEFAULT_WORLD_ID,
        name="林岚",
        description="研究所档案管理员，冷静、戒备、慢热。",
        persona={
            "identity": "研究所档案管理员",
            "goal": "查明妹妹死亡真相",
            "fear": "再次失去重要的人",
            "secret": "她曾参与七号档案实验",
        },
        speaking_style={"tone": "克制、短句、关键时刻显露脆弱"},
        relationship_to_user={"trust": 42, "status": "谨慎信任"},
        constraints={"do_not": ["主动替用户做重大决定", "突然推翻既定事实"]},
    )
    story = Story(
        id=DEFAULT_STORY_ID,
        user_id=DEFAULT_USER_ID,
        world_id=DEFAULT_WORLD_ID,
        title="七号档案",
        main_character_id=DEFAULT_CHARACTER_ID,
        current_branch_id=DEFAULT_BRANCH_ID,
        status="active",
    )
    branch = StoryBranch(
        id=DEFAULT_BRANCH_ID,
        story_id=DEFAULT_STORY_ID,
        name="main",
    )

    session.add_all([user, world, character, story, branch])
    await session.flush()

    session.add_all(
        [
            Message(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                role="assistant",
                content="通风管里的风声断断续续。林岚站在档案柜前，没有看你，只低声说：如果你现在回头，我不会拦你。",
                meta={"author": "林岚", "time": "深夜"},
            ),
            Message(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                role="user",
                content="我拿出她之前给我的钥匙。",
                meta={"author": "你"},
            ),
            StoryStateSnapshot(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                state={
                    "location": "地下二层档案室",
                    "time": "深夜",
                    "mood": "紧张、低声、被追踪",
                    "objective": "确认七号档案的位置，并判断林岚是否可信",
                    "inventory": ["旧钥匙", "半张通行卡"],
                    "open_threads": ["韩医生是否参与七号档案实验", "林岚妹妹死亡真相"],
                    "relationships": [
                        {"from": "主角", "to": "林岚", "bond": "谨慎信任", "value": 42},
                        {"from": "林岚", "to": "韩医生", "bond": "隐瞒与警惕", "value": -18},
                    ],
                },
            ),
            CanonFact(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                fact_type="character",
                content="林岚的妹妹已经死亡。",
                importance=10,
            ),
            CanonFact(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                fact_type="world_rule",
                content="死人不能复活。",
                importance=10,
            ),
            CanonFact(
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                fact_type="knowledge",
                content="主角尚不知道韩医生的真实身份。",
                importance=8,
            ),
            MemoryItem(
                user_id=DEFAULT_USER_ID,
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                character_id=DEFAULT_CHARACTER_ID,
                memory_type="plot_memory",
                content="林岚曾在研究所走廊把旧钥匙交给主角，并叮嘱不要告诉韩医生。",
                importance=9,
                entity_tags=["林岚", "旧钥匙", "韩医生"],
            ),
            MemoryItem(
                user_id=DEFAULT_USER_ID,
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                memory_type="plot_memory",
                content="旧钥匙可以打开地下二层档案室的侧门。",
                importance=8,
                entity_tags=["旧钥匙", "地下二层档案室"],
            ),
            MemoryItem(
                user_id=DEFAULT_USER_ID,
                story_id=DEFAULT_STORY_ID,
                branch_id=DEFAULT_BRANCH_ID,
                memory_type="plot_memory",
                content="七号档案与林岚妹妹的死亡有关。",
                importance=8,
                entity_tags=["七号档案", "林岚妹妹"],
            ),
            UserPreference(
                user_id=DEFAULT_USER_ID,
                preference_type="tone",
                content="悬疑、慢热、细腻，避免强行反转和角色突然崩坏。",
                strength=8,
                source="seed",
            ),
            ModelCall(
                user_id=DEFAULT_USER_ID,
                story_id=DEFAULT_STORY_ID,
                provider="deepinfra",
                model="Qwen/Qwen3-Max",
                purpose="seed",
                input_tokens=None,
                output_tokens=None,
                latency_ms=None,
                request={},
                response={"note": "seed placeholder"},
            ),
        ]
    )
    await session.commit()


async def get_default_story_id(session: AsyncSession):
    result = await session.execute(select(Story.id).order_by(Story.created_at.asc()).limit(1))
    return result.scalar_one_or_none()

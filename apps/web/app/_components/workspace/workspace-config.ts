import type { ModelRoleId, StoryPurpose } from "@/lib/types";

export type UiLanguage = "zh-CN" | "en";

export function uiText(language: UiLanguage, zh: string, en: string) {
  return language === "zh-CN" ? zh : en;
}

export const preferenceFields = [
  { id: "genres", label: "偏爱类型", placeholder: "例如：悬疑、都市奇幻、科幻" },
  { id: "prose_style", label: "文风偏好", placeholder: "例如：克制、画面感强、少用华丽比喻" },
  { id: "pacing", label: "节奏偏好", placeholder: "例如：慢热铺垫，关键场景加速" },
  { id: "themes", label: "主题偏好", placeholder: "例如：身份、记忆、人与城市" },
  { id: "avoid", label: "希望避免", placeholder: "例如：无意义反转、替主角做重大选择" }
] as const;

export const preferenceFieldsEn: Record<
  (typeof preferenceFields)[number]["id"],
  { label: string; placeholder: string }
> = {
  genres: { label: "Preferred genres", placeholder: "For example: mystery, urban fantasy, science fiction" },
  prose_style: { label: "Prose style", placeholder: "For example: restrained, visual, limited ornate metaphors" },
  pacing: { label: "Pacing", placeholder: "For example: slow build, faster key scenes" },
  themes: { label: "Themes", placeholder: "For example: identity, memory, people and cities" },
  avoid: { label: "Avoid", placeholder: "For example: empty twists or making major choices for the protagonist" }
};

export const purposeRoutes: Array<{
  id: StoryPurpose;
  label: string;
  description: string;
}> = [
  { id: "normal_chat", label: "Prose generation", description: "Main narrative and dialogue" },
  { id: "critical_story_generation", label: "Critical chapter", description: "High-stakes generation" },
  { id: "state_update", label: "State update", description: "Structured continuity JSON" },
  { id: "event_extraction", label: "Event extraction", description: "Timeline and entity capture" },
  { id: "summary_generation", label: "Memory summary", description: "Long-term recall compression" },
  { id: "consistency_check", label: "Continuity check", description: "Canon and voice review" }
];

export const purposeRoutesZh: Record<
  StoryPurpose,
  { label: string; description: string }
> = {
  normal_chat: { label: "正文生成", description: "主要叙事与角色对话" },
  critical_story_generation: { label: "关键章节", description: "高重要度场景生成" },
  state_update: { label: "状态更新", description: "结构化连续性状态" },
  event_extraction: { label: "事件提取", description: "时间线与实体捕获" },
  summary_generation: { label: "记忆摘要", description: "长期记忆压缩" },
  consistency_check: { label: "连续性检查", description: "既定事实与角色声音审查" }
};

export const purposeRoutesById = Object.fromEntries(
  purposeRoutes.map((route) => [route.id, route])
) as Record<StoryPurpose, (typeof purposeRoutes)[number]>;

export const purposeLabels = Object.fromEntries(
  purposeRoutes.map((route) => [route.id, route.label])
) as Record<StoryPurpose, string>;

export const modelRoleText: Record<
  ModelRoleId,
  { zh: string; en: string; zhDescription: string; enDescription: string }
> = {
  narrative_author: {
    zh: "AI 作者",
    en: "AI author",
    zhDescription: "负责小说正文与角色对话；玩家始终决定角色行动和剧情走向。",
    enDescription: "Authors prose and dialogue; the player remains in control of character actions and plot direction."
  },
  structured_extraction: {
    zh: "结构化提取",
    en: "Structured extraction",
    zhDescription: "从 AI 正文中提取场景状态与事件，不负责创作剧情。",
    enDescription: "Extracts scene state and events from AI-authored prose without directing the plot."
  },
  continuity_revision: {
    zh: "连续性修订",
    en: "Continuity revision",
    zhDescription: "仅在本地规则发现高严重度冲突时修订 AI 正文。",
    enDescription: "Revises AI-authored prose only after a high-severity local-rule conflict."
  },
  summary: {
    zh: "上下文摘要",
    en: "Context summary",
    zhDescription: "压缩已完成剧情，供后续回合保持连续性。",
    enDescription: "Compresses completed narrative history for continuity in later turns."
  },
  embedding: {
    zh: "记忆向量",
    en: "Memory embedding",
    zhDescription: "为符合条件的长期记忆建立语义索引，由部署配置统一管理。",
    enDescription: "Indexes eligible long-term memories and is managed by deployment configuration."
  }
};

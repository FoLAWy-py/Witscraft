"use client";

import {
  AlertTriangle,
  ArrowRight,
  Backpack,
  Braces,
  BookOpen,
  BookText,
  Brain,
  CheckCircle2,
  Check,
  ChevronDown,
  ChevronsDown,
  ChevronsUp,
  Circle,
  CircleDashed,
  ClipboardList,
  Clock,
  Cog,
  Copy,
  Cpu,
  Dot,
  Download,
  Feather,
  FileText,
  Gauge,
  GitBranch,
  GitFork,
  Globe2,
  HeartHandshake,
  KeyRound,
  Lock,
  LogOut,
  ListChecks,
  Mail,
  MapPin,
  MessageCircle,
  MonitorSmartphone,
  Moon,
  PanelLeft,
  PanelRight,
  PenLine,
  Plus,
  RefreshCw,
  Route,
  Send,
  Settings2,
  ShieldCheck,
  Sparkles,
  Square,
  Sun,
  Target,
  Trash2,
  UserRound,
  Users,
  Waves,
  X
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ApiError, StreamInterruptedError, confirmEmailVerification, confirmPasswordReset, createBranch, createCharacter, createStory, createWorld, deleteAccount, deleteBranch, deleteCharacter, deleteStory, deleteWorld, downloadAccountExport, downloadStoryExport, duplicateBranch, generateSessionSummary, getAuthSessions, getCurrentUser, getMyQuota, getProviders, getUserPreferences, getWorkspace, login, logout, register, requestEmailVerification, requestPasswordReset, revokeAuthSession, selectStoryWorld, sendStoryMessage, streamStoryInterview, streamStoryMessage, switchBranch, testProviderModel, updateBranch, updateCanonFact, updateCharacter, updateMemoryItem, updateModelRoutes, updateStory, updateUserPreferences, updateWorld } from "@/lib/api";
import type { AuthSessionSummary, AuthUser, CanonFactSummary, ChatResponse, ConsistencyCheck, CreateStoryInput, LoginInput, MemoryItemSummary, ModelOption, ProvidersResponse, QuotaUsage, RegisterInput, SessionSummary, StoryInterviewMessage, StoryPurpose, StoryState, UserPreference, WorkspaceResponse } from "@/lib/types";

type View = "story" | "settings";
type MobileTab = "library" | "story" | "inspector";
type InteractionMode = "choices" | "open";
type ConsistencyMode = "manual" | "auto" | "off";
type UiLanguage = "zh-CN" | "en";
type Message = { id?: string; role: "assistant" | "user" | "beat"; content: string; author?: string; time?: string; choices?: string[]; consistencyCheck?: ConsistencyCheck | null };
type StorySummary = WorkspaceResponse["stories"][number];
type BranchSummary = WorkspaceResponse["branches"][number];
type CharacterSummary = WorkspaceResponse["characters"][number];
type WorldSummary = WorkspaceResponse["worlds"][number];
type RelationshipSummary = WorkspaceResponse["relationships"][number];
type WorldDraft = { name: string; description: string; genre: string };
type CharacterDraft = { name: string; role: string };
type KnowledgeDraft = { content: string; importance: number };
type AuthStatus = "checking" | "anonymous" | "authenticated";
type InspectorCollection = "branches" | "relationships" | "inventory" | "threads" | "summaries" | "canon" | "memories";
type WorkspaceHistoryMode = "push" | "replace";
type RecoveryKind = "api" | "database" | "network" | "provider" | "stream" | "sync" | "stopped";

const preferenceFields = [
  { id: "genres", label: "偏爱类型", placeholder: "例如：悬疑、都市奇幻、科幻" },
  { id: "prose_style", label: "文风偏好", placeholder: "例如：克制、画面感强、少用华丽比喻" },
  { id: "pacing", label: "节奏偏好", placeholder: "例如：慢热铺垫，关键场景加速" },
  { id: "themes", label: "主题偏好", placeholder: "例如：身份、记忆、人与城市" },
  { id: "avoid", label: "希望避免", placeholder: "例如：无意义反转、替主角做重大选择" }
] as const;

const STORY_WIZARD_STORAGE_VERSION = 1;
const UI_LANGUAGE_KEY = "witscraft:ui-language";

function uiText(language: UiLanguage, zh: string, en: string) {
  return language === "zh-CN" ? zh : en;
}

function storyWizardStorageKey(userId: string) {
  return `witscraft:story-wizard:${userId}:v${STORY_WIZARD_STORAGE_VERSION}`;
}

function initialStoryInterviewMessages(): StoryInterviewMessage[] {
  return [{
    role: "assistant",
    content: "我们一起把新小说说清楚。你更想从哪一部分开始？",
    options: ["先说一个故事灵感", "先确定主角", "先搭建世界"]
  }];
}

function initialStoryDraft(): CreateStoryInput {
  return {
    title: "",
    genre: "",
    worldName: "",
    premise: "",
    protagonistName: "",
    protagonistRole: "",
    tone: "",
    openingMode: "blank",
    openingText: "",
    customPrompt: "",
    interactionMode: "choices"
  };
}

function classifyFailure(caught: unknown, fallback: string): { message: string; kind: RecoveryKind } {
  if (caught instanceof StreamInterruptedError) {
    return { message: "生成连接在完成前中断。已保留当前内容，请重新同步数据库中的最终状态。", kind: "stream" };
  }
  if (caught instanceof ApiError) {
    if (caught.status === 429 && caught.message.toLowerCase().includes("quota")) {
      return { message: "本周 AI 额度不足。可在设置中查看用量与重置时间。", kind: "api" };
    }
    if (caught.status === 429 && caught.message.toLowerCase().includes("per-turn")) {
      return { message: "本轮已达到外部模型调用上限，已停止继续调用。请重新同步后再试。", kind: "api" };
    }
    if (caught.status === 502) {
      return { message: "模型服务暂时没有完成请求。当前上下文未丢失，可重新同步后继续。", kind: "provider" };
    }
    if (caught.status === 503 && caught.message.toLowerCase().includes("database")) {
      return { message: "数据库暂时不可用。请稍后重试，现有小说数据不会被清空。", kind: "database" };
    }
    return { message: `API 请求失败（${caught.status}）：${caught.message}`, kind: "api" };
  }
  if (caught instanceof TypeError || (caught instanceof Error && caught.message === "Network request failed")) {
    return { message: "无法连接 Witscraft 服务。请检查网络后重试。", kind: "network" };
  }
  return { message: fallback, kind: "api" };
}

const purposeRoutes: Array<{ id: StoryPurpose; label: string; description: string }> = [
  { id: "normal_chat", label: "Prose generation", description: "Main narrative and dialogue" },
  { id: "critical_story_generation", label: "Critical chapter", description: "High-stakes generation" },
  { id: "state_update", label: "State update", description: "Structured continuity JSON" },
  { id: "event_extraction", label: "Event extraction", description: "Timeline and entity capture" },
  { id: "summary_generation", label: "Memory summary", description: "Long-term recall compression" },
  { id: "consistency_check", label: "Continuity check", description: "Canon and voice review" }
];

const purposeRoutesZh: Record<StoryPurpose, { label: string; description: string }> = {
  normal_chat: { label: "正文生成", description: "主要叙事与角色对话" },
  critical_story_generation: { label: "关键章节", description: "高重要度场景生成" },
  state_update: { label: "状态更新", description: "结构化连续性状态" },
  event_extraction: { label: "事件提取", description: "时间线与实体捕获" },
  summary_generation: { label: "记忆摘要", description: "长期记忆压缩" },
  consistency_check: { label: "连续性检查", description: "既定事实与角色声音审查" }
};

const preferenceFieldsEn: Record<(typeof preferenceFields)[number]["id"], { label: string; placeholder: string }> = {
  genres: { label: "Preferred genres", placeholder: "For example: mystery, urban fantasy, science fiction" },
  prose_style: { label: "Prose style", placeholder: "For example: restrained, visual, limited ornate metaphors" },
  pacing: { label: "Pacing", placeholder: "For example: slow build, faster key scenes" },
  themes: { label: "Themes", placeholder: "For example: identity, memory, people and cities" },
  avoid: { label: "Avoid", placeholder: "For example: empty twists or making major choices for the protagonist" }
};

const purposeLabels = Object.fromEntries(purposeRoutes.map((route) => [route.id, route.label])) as Record<StoryPurpose, string>;

const emptyStoryState: StoryState = {
  location: "未设定",
  time: "未设定",
  mood: "未设定",
  objective: "等待故事数据",
  inventory: [],
  open_threads: []
};

const emptyModelCall: ChatResponse["model_call"] = {
  provider: "deepinfra",
  model: "",
  dry_run: true
};

function readWorkspaceLocation() {
  if (typeof window === "undefined") return { storyId: undefined, branchId: undefined };
  const params = new URLSearchParams(window.location.search);
  return {
    storyId: params.get("story_id") || undefined,
    branchId: params.get("branch_id") || undefined
  };
}

function syncWorkspaceLocation(storyId: string, branchId: string, mode: WorkspaceHistoryMode) {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (storyId) url.searchParams.set("story_id", storyId);
  else url.searchParams.delete("story_id");
  if (branchId) url.searchParams.set("branch_id", branchId);
  else url.searchParams.delete("branch_id");
  const next = `${url.pathname}${url.search}${url.hash}`;
  if (next === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
  if (mode === "push") window.history.pushState({}, "", next);
  else window.history.replaceState({}, "", next);
}

function syncStoryWizardLocation(active: boolean, mode: WorkspaceHistoryMode = "push") {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (active) url.searchParams.set("new_story", "1");
  else url.searchParams.delete("new_story");
  const next = `${url.pathname}${url.search}${url.hash}`;
  if (next === `${window.location.pathname}${window.location.search}${window.location.hash}`) return;
  if (mode === "push") window.history.pushState({}, "", next);
  else window.history.replaceState({}, "", next);
}

export default function Home() {
  const [authStatus, setAuthStatus] = useState<AuthStatus>("checking");
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [authError, setAuthError] = useState<string | null>(null);
  const [authNotice, setAuthNotice] = useState<string | null>(null);
  const [passwordResetToken, setPasswordResetToken] = useState<string | null>(null);
  const [resendingVerification, setResendingVerification] = useState(false);
  const [loggingOut, setLoggingOut] = useState(false);
  const [authSessions, setAuthSessions] = useState<AuthSessionSummary[]>([]);
  const [loadingAuthSessions, setLoadingAuthSessions] = useState(false);
  const [revokingSessionId, setRevokingSessionId] = useState<string | null>(null);
  const [confirmRevokeSessionId, setConfirmRevokeSessionId] = useState<string | null>(null);
  const [sessionError, setSessionError] = useState<string | null>(null);
  const [exportingAccount, setExportingAccount] = useState(false);
  const [deletingAccount, setDeletingAccount] = useState(false);
  const [accountActionError, setAccountActionError] = useState<string | null>(null);
  const [quota, setQuota] = useState<QuotaUsage | null>(null);
  const [view, setView] = useState<View>("story");
  const [mobileTab, setMobileTab] = useState<MobileTab>("story");
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [dark, setDark] = useState(false);
  const [uiLanguage, setUiLanguage] = useState<UiLanguage>("zh-CN");
  const [providers, setProviders] = useState<ProvidersResponse | null>(null);
  const [storyId, setStoryId] = useState("");
  const [branchId, setBranchId] = useState("");
  const [branchList, setBranchList] = useState<BranchSummary[]>([]);
  const [storyList, setStoryList] = useState<StorySummary[]>([]);
  const [world, setWorld] = useState<Record<string, unknown>>({});
  const [worldList, setWorldList] = useState<WorldSummary[]>([]);
  const [characterList, setCharacterList] = useState<CharacterSummary[]>([]);
  const [relationshipList, setRelationshipList] = useState<RelationshipSummary[]>([]);
  const [selectedPurpose, setSelectedPurpose] = useState<StoryPurpose>("normal_chat");
  const [routeModels, setRouteModels] = useState<Partial<Record<StoryPurpose, string>>>({});
  const [savedRouteModels, setSavedRouteModels] = useState<Partial<Record<StoryPurpose, string>>>({});
  const [savingRoutes, setSavingRoutes] = useState(false);
  const routeSaveVersionRef = useRef(0);
  const [routeNotice, setRouteNotice] = useState<string | null>(null);
  const [routeError, setRouteError] = useState<string | null>(null);
  const [checkingModelId, setCheckingModelId] = useState<string | null>(null);
  const [modelHealthNotice, setModelHealthNotice] = useState<string | null>(null);
  const [modelHealthError, setModelHealthError] = useState<string | null>(null);
  const [userPreferences, setUserPreferences] = useState<UserPreference[]>([]);
  const [savedUserPreferences, setSavedUserPreferences] = useState<UserPreference[]>([]);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const [preferenceNotice, setPreferenceNotice] = useState<string | null>(null);
  const [preferenceError, setPreferenceError] = useState<string | null>(null);
  const [storyPrompt, setStoryPrompt] = useState("");
  const [savedStoryPrompt, setSavedStoryPrompt] = useState("");
  const [savingStoryPrompt, setSavingStoryPrompt] = useState(false);
  const [storyPromptNotice, setStoryPromptNotice] = useState<string | null>(null);
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("choices");
  const [savingInteractionMode, setSavingInteractionMode] = useState(false);
  const [consistencyMode, setConsistencyMode] = useState<ConsistencyMode>("auto");
  const [savingConsistencyMode, setSavingConsistencyMode] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);

  useEffect(() => {
    const stored = window.localStorage.getItem(UI_LANGUAGE_KEY);
    if (stored === "zh-CN" || stored === "en") setUiLanguage(stored);
  }, []);

  useEffect(() => {
    window.localStorage.setItem(UI_LANGUAGE_KEY, uiLanguage);
    document.documentElement.lang = uiLanguage;
  }, [uiLanguage]);
  const [state, setState] = useState(emptyStoryState);
  const [memoryItems, setMemoryItems] = useState<MemoryItemSummary[]>([]);
  const [canonFactItems, setCanonFactItems] = useState<CanonFactSummary[]>([]);
  const [summaries, setSummaries] = useState<SessionSummary[]>([]);
  const [lastRun, setLastRun] = useState<ChatResponse["model_call"]>(emptyModelCall);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [workspaceLoading, setWorkspaceLoading] = useState(false);
  const [workspaceInitialized, setWorkspaceInitialized] = useState(false);
  const [showStoryWizard, setShowStoryWizard] = useState(false);
  const [creatingStory, setCreatingStory] = useState(false);
  const [creatingBranch, setCreatingBranch] = useState(false);
  const [summarizing, setSummarizing] = useState(false);
  const [exportingFormat, setExportingFormat] = useState<"markdown" | "json" | null>(null);
  const [switchingBranchId, setSwitchingBranchId] = useState<string | null>(null);
  const [editingBranchId, setEditingBranchId] = useState<string | null>(null);
  const [branchNameDraft, setBranchNameDraft] = useState("");
  const [savingBranchId, setSavingBranchId] = useState<string | null>(null);
  const [duplicatingBranchId, setDuplicatingBranchId] = useState<string | null>(null);
  const [confirmDeleteBranchId, setConfirmDeleteBranchId] = useState<string | null>(null);
  const [deletingBranchId, setDeletingBranchId] = useState<string | null>(null);
  const [editingStoryId, setEditingStoryId] = useState<string | null>(null);
  const [storyTitleDraft, setStoryTitleDraft] = useState("");
  const [savingStory, setSavingStory] = useState(false);
  const [confirmDeleteStoryId, setConfirmDeleteStoryId] = useState<string | null>(null);
  const [deletingStoryId, setDeletingStoryId] = useState<string | null>(null);
  const [editingWorld, setEditingWorld] = useState(false);
  const [creatingWorld, setCreatingWorld] = useState(false);
  const [switchingWorldId, setSwitchingWorldId] = useState<string | null>(null);
  const [confirmDeleteWorldId, setConfirmDeleteWorldId] = useState<string | null>(null);
  const [deletingWorldId, setDeletingWorldId] = useState<string | null>(null);
  const [worldDraft, setWorldDraft] = useState<WorldDraft>({ name: "", description: "", genre: "" });
  const [savingWorld, setSavingWorld] = useState(false);
  const [editingCharacterId, setEditingCharacterId] = useState<string | null>(null);
  const [characterDraft, setCharacterDraft] = useState<CharacterDraft>({ name: "", role: "" });
  const [savingCharacterId, setSavingCharacterId] = useState<string | null>(null);
  const [creatingCharacter, setCreatingCharacter] = useState(false);
  const [confirmDeleteCharacterId, setConfirmDeleteCharacterId] = useState<string | null>(null);
  const [deletingCharacterId, setDeletingCharacterId] = useState<string | null>(null);
  const [editingMemoryId, setEditingMemoryId] = useState<string | null>(null);
  const [memoryDraft, setMemoryDraft] = useState<KnowledgeDraft>({ content: "", importance: 5 });
  const [savingMemoryId, setSavingMemoryId] = useState<string | null>(null);
  const [editingCanonFactId, setEditingCanonFactId] = useState<string | null>(null);
  const [canonFactDraft, setCanonFactDraft] = useState<KnowledgeDraft>({ content: "", importance: 5 });
  const [savingCanonFactId, setSavingCanonFactId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recoveryKind, setRecoveryKind] = useState<RecoveryKind | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamAssistantActiveRef = useRef(false);

  function applyWorkspace(data: WorkspaceResponse, historyMode: WorkspaceHistoryMode = "replace") {
    setStoryId(data.story_id);
    setBranchId(data.branch_id);
    setBranchList(data.branches ?? []);
    setStoryList(data.stories);
    setWorld(data.world ?? {});
    setWorldList(data.worlds ?? []);
    setCharacterList(data.characters);
    setMessages(
      data.messages.map((message) => ({
        id: message.id,
        role: message.role === "user" ? "user" : message.role === "beat" ? "beat" : "assistant",
        author: message.author ?? (message.role === "user" ? "你" : "叙事引擎"),
        time: message.time ?? undefined,
        content: message.content,
        choices: message.choices ?? [],
        consistencyCheck: message.consistency_check ?? null
      }))
    );
    setState(data.story_state ?? emptyStoryState);
    setRelationshipList(data.relationships.length ? data.relationships : []);
    setMemoryItems(
      data.memory_items?.length
        ? data.memory_items
        : data.retrieved_memories.map((content, index) => ({ id: "", content, importance: 5, type: `memory-${index}` }))
    );
    setCanonFactItems(
      data.canon_fact_items?.length
        ? data.canon_fact_items
        : data.canon_facts.map((content, index) => ({ id: "", content, importance: 5, type: `canon-${index}` }))
    );
    setSummaries(data.summaries ?? []);
    setLastRun(data.model_call ?? emptyModelCall);
      setStoryPrompt(data.story_prompt ?? "");
    setSavedStoryPrompt(data.story_prompt ?? "");
    setInteractionMode(data.interaction_mode ?? "choices");
    setConsistencyMode(data.consistency_mode ?? "auto");
    syncWorkspaceLocation(data.story_id, data.branch_id, historyMode);
  }

  function clearWorkspace() {
    setStoryId("");
    setBranchId("");
    setBranchList([]);
    setStoryList([]);
    setWorld({});
    setWorldList([]);
    setCharacterList([]);
    setRelationshipList([]);
    setMessages([]);
    setState(emptyStoryState);
    setMemoryItems([]);
    setCanonFactItems([]);
    setSummaries([]);
    setLastRun(emptyModelCall);
    setProviders(null);
    setUserPreferences([]);
    setSavedUserPreferences([]);
    setStoryPrompt("");
    setSavedStoryPrompt("");
    setInteractionMode("choices");
    setAuthSessions([]);
    setConfirmRevokeSessionId(null);
    setSessionError(null);
    setWorkspaceInitialized(false);
    setShowStoryWizard(false);
    syncWorkspaceLocation("", "", "replace");
  }

  async function loadWorkspace(
    nextStoryId?: string,
    nextBranchId?: string,
    historyMode: WorkspaceHistoryMode = "replace"
  ) {
    setWorkspaceLoading(true);
    setError(null);
    setRecoveryKind(null);
    try {
      const location = nextStoryId || nextBranchId
        ? { storyId: nextStoryId, branchId: nextBranchId }
        : readWorkspaceLocation();
      let data: WorkspaceResponse;
      if (location.storyId && location.branchId) {
        try {
          data = await switchBranch(location.storyId, location.branchId);
        } catch (caught) {
          if (!(caught instanceof ApiError) || caught.status !== 404) throw caught;
          data = await getWorkspace(location.storyId);
        }
      } else {
        data = await getWorkspace(location.storyId, location.branchId);
      }
      applyWorkspace(data, historyMode);
      setWorkspaceInitialized(true);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        clearWorkspace();
        setAuthUser(null);
        setAuthStatus("anonymous");
        return;
      }
      const issue = classifyFailure(caught, "工作区读取失败。请稍后重试。");
      setError(issue.message);
      setRecoveryKind(issue.kind);
    } finally {
      setWorkspaceLoading(false);
    }
  }

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  useEffect(() => {
    if (!error) setRecoveryKind(null);
  }, [error]);

  useEffect(() => {
    document.documentElement.classList.add("theme-transition");
    return () => document.documentElement.classList.remove("theme-transition");
  }, []);

  useEffect(() => {
    let active = true;
    const params = new URLSearchParams(window.location.search);
    const resetToken = params.get("reset_password");
    const verificationToken = params.get("verify_email");
    const clearAuthQuery = () => window.history.replaceState({}, "", window.location.pathname);

    if (resetToken) {
      setPasswordResetToken(resetToken);
      setAuthStatus("anonymous");
      return () => {
        active = false;
      };
    }

    const initialize = async () => {
      if (verificationToken) {
        try {
          await confirmEmailVerification(verificationToken);
          clearAuthQuery();
          setAuthNotice("邮箱验证成功，你的工作区已解锁。");
        } catch (caught) {
          if (!active) return;
          clearAuthQuery();
          setAuthError(caught instanceof ApiError ? caught.message : "验证链接无效或已经过期。");
          setAuthUser(null);
          setAuthStatus("anonymous");
          return;
        }
      }

      try {
        const { user } = await getCurrentUser();
        if (!active) return;
        setAuthUser(user);
        setAuthStatus("authenticated");
      } catch {
        if (!active) return;
        setAuthUser(null);
        setAuthStatus("anonymous");
      }
    };
    void initialize();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (authStatus !== "authenticated" || !authUser?.email_verified) return;
    if (new URL(window.location.href).searchParams.get("new_story") === "1") {
      setShowStoryWizard(true);
    }
    getProviders()
      .then((data) => {
        setProviders(data);
        const qwen = data.models.find((model) => model.model === "Qwen/Qwen3-Max");
        setSelectedModel((current) => (data.models.some((model) => model.model === current) ? current : qwen?.model ?? data.models[0]?.model ?? ""));
        const nextRoutes: Partial<Record<StoryPurpose, string>> = {};
        {
          const validModels = new Set(data.models.map((model) => model.model));
          purposeRoutes.forEach(({ id }) => {
            const savedModel = data.purpose_routes[id];
            const fallbackModel = data.purpose_defaults[id];
            const modelId = savedModel && validModels.has(savedModel) ? savedModel : fallbackModel;
            if (modelId && validModels.has(modelId)) nextRoutes[id] = modelId;
          });
        }
        setRouteModels(nextRoutes);
        setSavedRouteModels(nextRoutes);
        setRouteNotice(Object.keys(data.purpose_routes).length ? "已恢复服务器保存的模型路由。" : null);
        setRouteError(null);
      })
      .catch(() => {
        setProviders(null);
      });
    getUserPreferences()
      .then((data) => {
        setUserPreferences(data.preferences);
        setSavedUserPreferences(data.preferences);
        setPreferenceError(null);
      })
      .catch(() => setPreferenceError("读取创作偏好失败，请稍后重试。"));
    void refreshQuota();
    void loadWorkspace();
  }, [authStatus, authUser?.email_verified]);

  useEffect(() => {
    if (authStatus !== "authenticated" || !authUser?.email_verified) return;
    const restoreWorkspaceFromHistory = () => {
      const location = readWorkspaceLocation();
      setShowStoryWizard(new URL(window.location.href).searchParams.get("new_story") === "1");
      void loadWorkspace(location.storyId, location.branchId, "replace");
    };
    window.addEventListener("popstate", restoreWorkspaceFromHistory);
    return () => window.removeEventListener("popstate", restoreWorkspaceFromHistory);
  }, [authStatus, authUser?.email_verified]);

  useEffect(() => {
    if (authStatus !== "authenticated" || view !== "settings") return;
    void loadAuthSessions();
  }, [authStatus, view]);

  async function loadAuthSessions() {
    setLoadingAuthSessions(true);
    setSessionError(null);
    try {
      const data = await getAuthSessions();
      setAuthSessions(data.sessions);
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        clearWorkspace();
        setAuthUser(null);
        setAuthStatus("anonymous");
      } else {
        setSessionError("读取登录会话失败，请稍后重试。");
      }
    } finally {
      setLoadingAuthSessions(false);
    }
  }

  async function refreshQuota() {
    try {
      setQuota(await getMyQuota());
    } catch {
      setQuota(null);
    }
  }

  async function handleAuthenticate(mode: "login" | "register", input: LoginInput | RegisterInput) {
    if (authSubmitting) return;
    setAuthSubmitting(true);
    setAuthError(null);
    setAuthNotice(null);
    try {
      const response = mode === "register"
        ? await register(input as RegisterInput)
        : await login(input as LoginInput);
      setAuthUser(response.user);
      setAuthStatus("authenticated");
      void refreshQuota();
      setError(null);
    } catch (caught) {
      if (caught instanceof ApiError) {
        if (caught.status === 401) setAuthError("邮箱或密码不正确。");
        else if (caught.status === 409) setAuthError("这个邮箱已经注册，请直接登录。");
        else if (caught.status === 429) setAuthError("登录尝试过多，请等待 15 分钟后重试。");
        else if (caught.status === 503) setAuthError("邮件服务器暂时不可用，请稍后重试。");
        else setAuthError(caught.message);
      } else {
        setAuthError("无法连接认证服务，请确认后端正在运行。");
      }
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleRequestPasswordReset(email: string) {
    if (authSubmitting) return;
    setAuthSubmitting(true);
    setAuthError(null);
    setAuthNotice(null);
    try {
      await requestPasswordReset(email);
      setAuthNotice("如果该邮箱已注册，重置链接已经发送，请检查收件箱和垃圾箱。");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 503) {
        setAuthError("邮件服务器暂时不可用，请稍后重试。");
      } else {
        setAuthError(caught instanceof ApiError ? caught.message : "无法发送重置邮件，请稍后重试。");
      }
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleConfirmPasswordReset(newPassword: string) {
    if (!passwordResetToken || authSubmitting) return;
    setAuthSubmitting(true);
    setAuthError(null);
    try {
      await confirmPasswordReset(passwordResetToken, newPassword);
      window.history.replaceState({}, "", window.location.pathname);
      setPasswordResetToken(null);
      setAuthNotice("密码已重置，请使用新密码登录。");
    } catch (caught) {
      setAuthError(caught instanceof ApiError ? caught.message : "重置链接无效或已经过期。");
    } finally {
      setAuthSubmitting(false);
    }
  }

  async function handleResendVerification() {
    if (resendingVerification) return;
    setResendingVerification(true);
    setAuthError(null);
    setAuthNotice(null);
    try {
      await requestEmailVerification();
      setAuthNotice("验证邮件已重新发送，请检查收件箱和垃圾箱。");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 429) {
        setAuthError("验证邮件刚刚发送过，请稍后再试。");
      } else if (caught instanceof ApiError && caught.status === 503) {
        setAuthError("邮件服务器暂时不可用，请联系管理员检查 TLS 证书。");
      } else {
        setAuthError(caught instanceof ApiError ? caught.message : "无法发送验证邮件。");
      }
    } finally {
      setResendingVerification(false);
    }
  }

  async function handleLogout() {
    if (loggingOut) return;
    setLoggingOut(true);
    setError(null);
    try {
      await logout();
      clearWorkspace();
      setQuota(null);
      setAuthUser(null);
      setAuthStatus("anonymous");
      setView("story");
      setMobileTab("story");
    } catch {
      setError("退出登录失败，请稍后重试。");
    } finally {
      setLoggingOut(false);
    }
  }

  async function handleRevokeSession(authSession: AuthSessionSummary) {
    if (revokingSessionId) return;
    if (confirmRevokeSessionId !== authSession.id) {
      setConfirmRevokeSessionId(authSession.id);
      return;
    }

    setRevokingSessionId(authSession.id);
    setSessionError(null);
    try {
      await revokeAuthSession(authSession.id);
      setConfirmRevokeSessionId(null);
      if (authSession.current) {
        clearWorkspace();
        setAuthUser(null);
        setAuthStatus("anonymous");
        setView("story");
      } else {
        await loadAuthSessions();
      }
    } catch {
      setSessionError("撤销登录会话失败，请稍后重试。");
    } finally {
      setRevokingSessionId(null);
    }
  }

  async function handleAccountExport() {
    if (exportingAccount) return;
    setExportingAccount(true);
    setAccountActionError(null);
    try {
      await downloadAccountExport();
    } catch (caught) {
      setAccountActionError(caught instanceof ApiError ? caught.message : "账户数据导出失败，请稍后重试。");
    } finally {
      setExportingAccount(false);
    }
  }

  async function handleDeleteAccount(password: string, confirmation: string) {
    if (deletingAccount) return;
    setDeletingAccount(true);
    setAccountActionError(null);
    try {
      await deleteAccount(password, confirmation);
      clearWorkspace();
      setAuthSessions([]);
      setQuota(null);
      setAuthUser(null);
      setAuthStatus("anonymous");
      setView("story");
      setMobileTab("story");
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        setAccountActionError("当前密码不正确，账户未删除。");
      } else if (caught instanceof ApiError && caught.status === 429) {
        setAccountActionError("删除尝试过多，请稍后再试。");
      } else {
        setAccountActionError(caught instanceof ApiError ? caught.message : "账户删除失败，任何数据均未更改。");
      }
    } finally {
      setDeletingAccount(false);
    }
  }

  const models = providers?.models ?? [];
  const activeModelId = routeModels[selectedPurpose] ?? providers?.purpose_defaults[selectedPurpose] ?? selectedModel;
  const activeModel = useMemo(
    () => models.find((model) => model.model === activeModelId) ?? models[0] ?? null,
    [activeModelId, models]
  );
  const activeStoryTitle = storyList.find((story) => story.id === storyId)?.title ?? "未命名故事";
  const activeBranchName = branchList.find((branch) => branch.id === branchId)?.name ?? "未命名分支";
  const routeDirty = purposeRoutes.some(({ id }) => routeModels[id] !== savedRouteModels[id]);
  const preferenceDirty = JSON.stringify(userPreferences.map(({ preferenceType, content, strength }) => ({ preferenceType, content, strength })))
    !== JSON.stringify(savedUserPreferences.map(({ preferenceType, content, strength }) => ({ preferenceType, content, strength })));
  const storyPromptDirty = storyPrompt !== savedStoryPrompt;

  useEffect(() => {
    if (!providers || !routeDirty) return;
    const routes = completeRoutes(routeModels);
    if (!routes) return;
    const version = ++routeSaveVersionRef.current;
    const timer = window.setTimeout(async () => {
      setSavingRoutes(true);
      setRouteError(null);
      setRouteNotice("正在自动保存模型路由…");
      try {
        const response = await updateModelRoutes(routes);
        if (version !== routeSaveVersionRef.current) return;
        setRouteModels(response.purpose_routes);
        setSavedRouteModels(response.purpose_routes);
        setRouteNotice("模型路由已自动保存。切换设备或重新登录后仍会恢复。");
      } catch (caught) {
        if (version !== routeSaveVersionRef.current) return;
        setRouteError(caught instanceof ApiError ? caught.message : "自动保存模型路由失败，请稍后重试。");
        setRouteNotice(null);
      } finally {
        if (version === routeSaveVersionRef.current) setSavingRoutes(false);
      }
    }, 350);
    return () => window.clearTimeout(timer);
  }, [providers, routeDirty, routeModels]);

  function setRouteModel(purpose: StoryPurpose, modelId: string) {
    setRouteModels((current) => ({ ...current, [purpose]: modelId }));
    if (purpose === selectedPurpose) setSelectedModel(modelId);
    setRouteNotice(null);
    setRouteError(null);
  }

  function completeRoutes(source: Partial<Record<StoryPurpose, string>>): Record<StoryPurpose, string> | null {
    if (!providers) return null;
    const entries = purposeRoutes.map(({ id }) => [id, source[id] ?? providers.purpose_defaults[id]] as const);
    if (entries.some(([, model]) => !model)) return null;
    return Object.fromEntries(entries) as Record<StoryPurpose, string>;
  }

  function handleRestoreSavedRoutes() {
    setRouteModels(savedRouteModels);
    setRouteNotice("已恢复上次保存的模型路由。");
    setRouteError(null);
  }

  function handleUseDefaultRoutes() {
    if (!providers) return;
    setRouteModels(providers.purpose_defaults);
    setRouteNotice("已载入系统默认路由，正在自动保存。");
    setRouteError(null);
  }

  async function handleTestModel(model: ModelOption) {
    setCheckingModelId(model.model);
    setModelHealthNotice(null);
    setModelHealthError(null);
    try {
      const response = await testProviderModel(model.provider, model.model);
      setProviders((current) => current ? {
        ...current,
        model_health: { ...current.model_health, [model.model]: response.health }
      } : current);
      setModelHealthNotice(
        response.ok
          ? `${model.label} 可用${response.health.latency_ms ? `，延迟 ${(response.health.latency_ms / 1000).toFixed(2)}s` : ""}。`
          : `${model.label} 当前不可用，已记录检查结果。`
      );
    } catch (caught) {
      setModelHealthError(caught instanceof ApiError ? caught.message : "模型检查失败，请稍后重试。");
    } finally {
      setCheckingModelId(null);
    }
  }

  function setPreferenceValue(preferenceType: string, content: string) {
    setUserPreferences((current) => {
      const existing = current.find((item) => item.preferenceType === preferenceType);
      if (existing) {
        return current.map((item) => item.preferenceType === preferenceType ? { ...item, content } : item);
      }
      return [...current, { preferenceType, content, strength: 5 }];
    });
    setPreferenceNotice(null);
    setPreferenceError(null);
  }

  async function handleSavePreferences() {
    if (!preferenceDirty || savingPreferences) return;
    setSavingPreferences(true);
    setPreferenceNotice(null);
    setPreferenceError(null);
    try {
      const response = await updateUserPreferences(userPreferences.filter((item) => item.content.trim()));
      setUserPreferences(response.preferences);
      setSavedUserPreferences(response.preferences);
      setPreferenceNotice("创作偏好已保存，建稿采访和后续小说生成都会引用。");
    } catch (caught) {
      setPreferenceError(caught instanceof ApiError ? caught.message : "保存创作偏好失败，请稍后重试。");
    } finally {
      setSavingPreferences(false);
    }
  }

  async function handleSaveStoryPrompt() {
    if (!storyId || !storyPromptDirty || savingStoryPrompt) return;
    setSavingStoryPrompt(true);
    setStoryPromptNotice(null);
    try {
      const data = await updateStory(storyId, { customPrompt: storyPrompt });
      applyWorkspace(data);
      setStoryPromptNotice(uiText(uiLanguage, "当前小说 Prompt 已保存，并会加入每次生成的上下文。", "Story prompt saved. It will be included in every generation."));
    } catch (caught) {
      setStoryPromptNotice(caught instanceof ApiError ? caught.message : uiText(uiLanguage, "保存小说 Prompt 失败，请稍后重试。", "Could not save the story prompt. Please try again."));
    } finally {
      setSavingStoryPrompt(false);
    }
  }

  async function handleInteractionModeChange(nextMode: InteractionMode) {
    const linkedStoryId = typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("story_id") ?? ""
      : "";
    const targetStoryId = storyId || linkedStoryId;
    if (!targetStoryId || savingInteractionMode) return;
    const previousMode = interactionMode;
    setInteractionMode(nextMode);
    setSavingInteractionMode(true);
    setError(null);
    try {
      applyWorkspace(await updateStory(targetStoryId, { interactionMode: nextMode }));
    } catch (caught) {
      setInteractionMode(previousMode);
      setError(caught instanceof ApiError ? caught.message : "保存推进方式失败，请稍后重试。");
    } finally {
      setSavingInteractionMode(false);
    }
  }

  async function handleConsistencyModeChange(nextMode: ConsistencyMode) {
    const linkedStoryId = typeof window !== "undefined"
      ? new URLSearchParams(window.location.search).get("story_id") ?? ""
      : "";
    const targetStoryId = storyId || linkedStoryId;
    if (!targetStoryId || savingConsistencyMode || nextMode === consistencyMode) return;
    const previousMode = consistencyMode;
    setConsistencyMode(nextMode);
    setSavingConsistencyMode(true);
    setError(null);
    try {
      applyWorkspace(await updateStory(targetStoryId, { consistencyMode: nextMode }));
    } catch (caught) {
      setConsistencyMode(previousMode);
      setError(caught instanceof ApiError ? caught.message : "保存一致性验证方式失败，请稍后重试。");
    } finally {
      setSavingConsistencyMode(false);
    }
  }

  async function handleSend(override?: string) {
    const text = (override ?? draft).trim();
    if (!text || pending) return;
    if (!activeModel) {
      setError("模型列表尚未从后端加载，暂时不能发送。");
      return;
    }
    if (!storyId || !branchId) {
      setError("工作区尚未从数据库加载完成，暂时不能发送。");
      return;
    }

    setPending(true);
    setError(null);
    setRecoveryKind(null);
    setDraft("");
    streamAssistantActiveRef.current = false;
    const controller = new AbortController();
    const idempotencyKey = window.crypto.randomUUID();
    const branchVersion = branchList.find((branch) => branch.id === branchId)?.version ?? 0;
    streamAbortRef.current = controller;
    setMessages((current) => [...current, { role: "user", author: "你", content: text }]);

    try {
      await streamStoryMessage(
        {
          message: text,
          provider: activeModel.provider,
          model: activeModel.model,
          purpose: selectedPurpose,
          storyId,
          branchId,
          idempotencyKey,
          branchVersion,
          signal: controller.signal
        },
        {
          onDelta: (content) => {
            if (!content) return;
            const updateExisting = streamAssistantActiveRef.current;
            streamAssistantActiveRef.current = true;
            setMessages((current) => {
              const last = current[current.length - 1];
              if (updateExisting && last?.role === "assistant") {
                return current.map((message, index) =>
                  index === current.length - 1 ? { ...message, content: message.content + content } : message
                );
              }
              return [...current, { role: "assistant", author: "叙事引擎", content }];
            });
          },
          onReplace: (content) => {
            streamAssistantActiveRef.current = true;
            setMessages((current) => {
              const last = current[current.length - 1];
              if (last?.role === "assistant") {
                return current.map((message, index) => index === current.length - 1 ? { ...message, content } : message);
              }
              return [...current, { role: "assistant", author: "叙事引擎", content }];
            });
          },
          onDone: (response) => {
            if (response.branch_version !== null && response.branch_version !== undefined) {
              setBranchList((current) => current.map((branch) =>
                branch.id === branchId ? { ...branch, version: response.branch_version as number } : branch
              ));
            }
            setMessages((current) => {
              const last = current[current.length - 1];
              if (streamAssistantActiveRef.current && last?.role === "assistant") {
                return current.map((message, index) =>
                  index === current.length - 1
                    ? { ...message, time: response.story_state.time, content: response.content || message.content, choices: response.choices, consistencyCheck: response.model_call.consistency_check ?? null }
                    : message
                );
              }
              return [
                ...current,
                { role: "assistant", author: "叙事引擎", time: response.story_state.time, content: response.content, choices: response.choices, consistencyCheck: response.model_call.consistency_check ?? null }
              ];
            });
            setState(response.story_state);
            setLastRun(response.model_call);
          }
        }
      );
      try {
        applyWorkspace(await getWorkspace(storyId));
      } catch {
        setError("回复已保存，但 Inspector 暂时无法与数据库同步；重新读取工作区即可恢复。");
        setRecoveryKind("sync");
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setError("生成已停止。若模型已返回部分文本，后端会保存 partial 记录供后续恢复。");
        setRecoveryKind("stopped");
      } else {
        const issue = classifyFailure(caught, "生成请求失败。当前上下文已保留，可重新同步后继续。");
        setError(issue.message);
        setRecoveryKind(issue.kind);
      }
    } finally {
      streamAbortRef.current = null;
      streamAssistantActiveRef.current = false;
      setPending(false);
      void refreshQuota();
    }
  }

  function handleStopGeneration() {
    streamAbortRef.current?.abort();
  }

  async function handleResyncWorkspace() {
    if (!storyId || workspaceLoading) return;
    await loadWorkspace(storyId, branchId, "replace");
  }

  async function handleMessageCommand(messageId: string, command: "regenerate" | "rewrite", overrideInstruction?: string) {
    if (!storyId || !branchId || !activeModel || pending) return;
    const instruction = command === "rewrite" ? overrideInstruction ?? draft.trim() : "";
    const idempotencyKey = window.crypto.randomUUID();
    const branchVersion = branchList.find((branch) => branch.id === branchId)?.version ?? 0;
    setPending(true);
    setError(null);
    if (command === "rewrite" && instruction && overrideInstruction === undefined) setDraft("");
    try {
      await sendStoryMessage({
        message: instruction,
        provider: activeModel.provider,
        model: activeModel.model,
        purpose: selectedPurpose,
        storyId,
        branchId,
        idempotencyKey,
        branchVersion,
        command,
        targetMessageId: messageId
      });
      applyWorkspace(await getWorkspace(storyId, branchId));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : `${command === "rewrite" ? "重写" : "重新生成"}失败，请稍后重试。`);
    } finally {
      setPending(false);
      void refreshQuota();
    }
  }

  async function handleSelectStory(nextStoryId: string) {
    if (nextStoryId === storyId || workspaceLoading || editingStoryId || deletingStoryId) return;
    setError(null);
    await loadWorkspace(nextStoryId, undefined, "push");
    setMobileTab("story");
    setLeftOpen(false);
    setConfirmDeleteStoryId(null);
  }

  async function handleCreateStory() {
    if (creatingStory) return;
    setShowStoryWizard(true);
    syncStoryWizardLocation(true);
  }

  async function handleSubmitStoryWizard(input: CreateStoryInput) {
    if (creatingStory) return;
    setCreatingStory(true);
    setError(null);
    try {
      const data = await createStory(input);
      applyWorkspace(data, "push");
      if (authUser?.id) window.localStorage.removeItem(storyWizardStorageKey(authUser.id));
      setWorkspaceInitialized(true);
      setShowStoryWizard(false);
      syncStoryWizardLocation(false, "replace");
      setMobileTab("story");
      setLeftOpen(false);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "新建故事失败。请确认数据库服务正在运行。");
    } finally {
      setCreatingStory(false);
    }
  }

  async function handleCreateBranch() {
    if (!storyId || creatingBranch) return;
    setCreatingBranch(true);
    setError(null);
    try {
      const title = `Branch ${branchList.length + 1}`;
      const data = await createBranch(storyId, { name: title });
      applyWorkspace(data, "push");
      setRightOpen(true);
      setMobileTab("inspector");
    } catch {
      setError("创建分支失败。请确认数据库服务正在运行。");
    } finally {
      setCreatingBranch(false);
    }
  }

  async function handleSwitchBranch(nextBranchId: string) {
    if (!storyId || nextBranchId === branchId || switchingBranchId || creatingBranch || savingBranchId || duplicatingBranchId || deletingBranchId) return;
    setSwitchingBranchId(nextBranchId);
    setConfirmDeleteBranchId(null);
    setError(null);
    try {
      const data = await switchBranch(storyId, nextBranchId);
      applyWorkspace(data, "push");
      setMobileTab("story");
    } catch {
      setError("切换分支失败。请确认数据库服务正在运行。");
    } finally {
      setSwitchingBranchId(null);
    }
  }

  function handleStartEditBranch(branch: BranchSummary) {
    setEditingBranchId(branch.id);
    setBranchNameDraft(branch.name);
    setConfirmDeleteBranchId(null);
  }

  function handleCancelEditBranch() {
    setEditingBranchId(null);
    setBranchNameDraft("");
  }

  async function handleSaveBranch() {
    const name = branchNameDraft.trim();
    if (!storyId || !editingBranchId || !name || savingBranchId) return;
    setSavingBranchId(editingBranchId);
    setError(null);
    try {
      const data = await updateBranch(storyId, editingBranchId, { name });
      applyWorkspace(data);
      handleCancelEditBranch();
    } catch {
      setError("重命名分支失败。请确认后端和数据库正在运行。");
    } finally {
      setSavingBranchId(null);
    }
  }

  async function handleDuplicateBranch(branch: BranchSummary) {
    if (!storyId || duplicatingBranchId || deletingBranchId || savingBranchId) return;
    setDuplicatingBranchId(branch.id);
    setConfirmDeleteBranchId(null);
    setError(null);
    try {
      const name = `${branch.name.slice(0, 115)} copy`;
      const data = await duplicateBranch(storyId, branch.id, { name });
      applyWorkspace(data);
      setMobileTab("inspector");
      setRightOpen(true);
    } catch {
      setError("复制分支失败。请确认后端和数据库正在运行。");
    } finally {
      setDuplicatingBranchId(null);
    }
  }

  async function handleDeleteBranch(branch: BranchSummary) {
    if (!storyId || branchList.length <= 1 || deletingBranchId || savingBranchId || duplicatingBranchId) return;
    if (confirmDeleteBranchId !== branch.id) {
      setConfirmDeleteBranchId(branch.id);
      setEditingBranchId(null);
      return;
    }

    setDeletingBranchId(branch.id);
    setError(null);
    try {
      const data = await deleteBranch(storyId, branch.id);
      applyWorkspace(data, data.branch_id === branchId ? "replace" : "push");
      setConfirmDeleteBranchId(null);
      setMobileTab("inspector");
    } catch {
      setError("删除分支失败。至少需要保留一个分支。");
    } finally {
      setDeletingBranchId(null);
    }
  }

  async function handleGenerateSummary() {
    if (!storyId || !branchId || summarizing) return;
    setSummarizing(true);
    setError(null);
    try {
      const data = await generateSessionSummary(storyId, branchId);
      applyWorkspace(data);
      setRightOpen(true);
      setMobileTab("inspector");
    } catch {
      setError("生成会话摘要失败。请确认当前分支已有消息，且模型 provider 可用。");
    } finally {
      setSummarizing(false);
    }
  }

  async function handleExportStory(format: "markdown" | "json") {
    if (!storyId || !branchId || exportingFormat) return;
    setExportingFormat(format);
    setError(null);
    try {
      await downloadStoryExport(storyId, branchId, format);
      setRightOpen(true);
      setMobileTab("inspector");
    } catch {
      setError("导出故事失败。请确认后端和数据库正在运行。");
    } finally {
      setExportingFormat(null);
    }
  }

  function handleStartRename(nextStoryId: string, title: string) {
    setConfirmDeleteStoryId(null);
    setEditingStoryId(nextStoryId);
    setStoryTitleDraft(title);
  }

  function handleCancelRename() {
    setEditingStoryId(null);
    setStoryTitleDraft("");
  }

  async function handleSaveRename() {
    const title = storyTitleDraft.trim();
    if (!editingStoryId || !title || savingStory) return;

    setSavingStory(true);
    setError(null);
    try {
      const data = await updateStory(editingStoryId, { title });
      applyWorkspace(data);
      setEditingStoryId(null);
      setStoryTitleDraft("");
    } catch {
      setError("重命名故事失败。请确认数据库服务正在运行。");
    } finally {
      setSavingStory(false);
    }
  }

  function handleRequestDelete(nextStoryId: string) {
    if (deletingStoryId || editingStoryId) return;
    setConfirmDeleteStoryId((current) => (current === nextStoryId ? null : nextStoryId));
  }

  async function handleDeleteStory(nextStoryId: string) {
    if (deletingStoryId) return;
    setDeletingStoryId(nextStoryId);
    setError(null);
    try {
      const data = await deleteStory(nextStoryId, storyId);
      applyWorkspace(data);
      setConfirmDeleteStoryId(null);
      setEditingStoryId(null);
      setStoryTitleDraft("");
      setMobileTab("story");
      if (nextStoryId === storyId) {
        setLeftOpen(false);
      }
    } catch {
      setError("删除故事失败。请确认数据库服务正在运行。");
    } finally {
      setDeletingStoryId(null);
    }
  }

  function handleStartEditWorld() {
    setCreatingWorld(false);
    setEditingWorld(true);
    setWorldDraft({
      name: String(world.name ?? ""),
      description: String(world.description ?? ""),
      genre: String(world.genre ?? "")
    });
  }

  function handleCancelEditWorld() {
    setEditingWorld(false);
    setCreatingWorld(false);
    setWorldDraft({ name: "", description: "", genre: "" });
  }

  function handleStartCreateWorld() {
    setEditingWorld(true);
    setCreatingWorld(true);
    setConfirmDeleteWorldId(null);
    setWorldDraft({ name: "", description: "", genre: "" });
  }

  async function handleSaveWorld() {
    const worldId = typeof world.id === "string" ? world.id : "";
    const name = worldDraft.name.trim();
    if ((!worldId && !creatingWorld) || !storyId || !name || savingWorld) return;

    setSavingWorld(true);
    setError(null);
    try {
      const input = {
        name,
        description: worldDraft.description.trim(),
        genre: worldDraft.genre.trim()
      };
      const data = creatingWorld
        ? await createWorld(input, storyId)
        : await updateWorld(worldId, input, storyId);
      applyWorkspace(data);
      setEditingWorld(false);
      setCreatingWorld(false);
    } catch {
      setError("更新世界设定失败。请确认数据库服务正在运行。");
    } finally {
      setSavingWorld(false);
    }
  }

  async function handleSelectWorld(worldId: string) {
    if (!storyId || worldId === world.id || switchingWorldId || savingWorld) return;
    setSwitchingWorldId(worldId);
    setConfirmDeleteWorldId(null);
    setError(null);
    try {
      applyWorkspace(await selectStoryWorld(storyId, worldId));
    } catch {
      setError("切换世界失败。请确认世界仍然存在。");
    } finally {
      setSwitchingWorldId(null);
    }
  }

  async function handleDeleteWorld(worldId: string) {
    if (!storyId || worldId === world.id || deletingWorldId || switchingWorldId) return;
    if (confirmDeleteWorldId !== worldId) {
      setConfirmDeleteWorldId(worldId);
      return;
    }
    setDeletingWorldId(worldId);
    setError(null);
    try {
      applyWorkspace(await deleteWorld(worldId, storyId));
      setConfirmDeleteWorldId(null);
    } catch {
      setError("删除世界失败。仍被小说使用的世界不能删除。");
    } finally {
      setDeletingWorldId(null);
    }
  }

  function handleStartEditCharacter(character: CharacterSummary) {
    setCreatingCharacter(false);
    setEditingCharacterId(character.id);
    setCharacterDraft({
      name: character.name,
      role: character.role
    });
  }

  function handleCancelEditCharacter() {
    setEditingCharacterId(null);
    setCreatingCharacter(false);
    setCharacterDraft({ name: "", role: "" });
  }

  function handleStartCreateCharacter() {
    setEditingCharacterId(null);
    setCreatingCharacter(true);
    setConfirmDeleteCharacterId(null);
    setCharacterDraft({ name: "", role: "" });
  }

  async function handleSaveCharacter() {
    const name = characterDraft.name.trim();
    const worldId = typeof world.id === "string" ? world.id : "";
    if ((!editingCharacterId && !creatingCharacter) || !worldId || !storyId || !name || savingCharacterId) return;

    setSavingCharacterId(editingCharacterId ?? "new");
    setError(null);
    try {
      const input = { name, role: characterDraft.role.trim() };
      const data = creatingCharacter
        ? await createCharacter(worldId, input, storyId)
        : await updateCharacter(editingCharacterId!, input, storyId);
      applyWorkspace(data);
      setEditingCharacterId(null);
      setCreatingCharacter(false);
      setCharacterDraft({ name: "", role: "" });
    } catch {
      setError("更新角色资料失败。请确认数据库服务正在运行。");
    } finally {
      setSavingCharacterId(null);
    }
  }

  async function handleDeleteCharacter(character: CharacterSummary) {
    if (character.main || !storyId || deletingCharacterId || savingCharacterId) return;
    if (confirmDeleteCharacterId !== character.id) {
      setConfirmDeleteCharacterId(character.id);
      return;
    }
    setDeletingCharacterId(character.id);
    setError(null);
    try {
      applyWorkspace(await deleteCharacter(character.id, storyId));
      setConfirmDeleteCharacterId(null);
    } catch {
      setError("删除角色失败。故事主角不能删除。");
    } finally {
      setDeletingCharacterId(null);
    }
  }

  function handleStartEditMemory(memory: MemoryItemSummary) {
    if (!memory.id) return;
    setEditingMemoryId(memory.id);
    setMemoryDraft({ content: memory.content, importance: memory.importance });
  }

  function handleCancelEditMemory() {
    setEditingMemoryId(null);
    setMemoryDraft({ content: "", importance: 5 });
  }

  async function handleSaveMemory() {
    const content = memoryDraft.content.trim();
    if (!editingMemoryId || !content || savingMemoryId) return;

    setSavingMemoryId(editingMemoryId);
    setError(null);
    try {
      const data = await updateMemoryItem(
        editingMemoryId,
        {
          content,
          importance: normalizeImportance(memoryDraft.importance)
        },
        storyId
      );
      applyWorkspace(data);
      handleCancelEditMemory();
    } catch {
      setError("更新记忆失败。请确认数据库服务正在运行。");
    } finally {
      setSavingMemoryId(null);
    }
  }

  function handleStartEditCanonFact(fact: CanonFactSummary) {
    if (!fact.id) return;
    setEditingCanonFactId(fact.id);
    setCanonFactDraft({ content: fact.content, importance: fact.importance });
  }

  function handleCancelEditCanonFact() {
    setEditingCanonFactId(null);
    setCanonFactDraft({ content: "", importance: 5 });
  }

  async function handleSaveCanonFact() {
    const content = canonFactDraft.content.trim();
    if (!editingCanonFactId || !content || savingCanonFactId) return;

    setSavingCanonFactId(editingCanonFactId);
    setError(null);
    try {
      const data = await updateCanonFact(
        editingCanonFactId,
        {
          content,
          importance: normalizeImportance(canonFactDraft.importance)
        },
        storyId
      );
      applyWorkspace(data);
      handleCancelEditCanonFact();
    } catch {
      setError("更新既定事实失败。请确认数据库服务正在运行。");
    } finally {
      setSavingCanonFactId(null);
    }
  }

  if (authStatus === "checking") {
    return <AuthLoading uiLanguage={uiLanguage} />;
  }

  if (passwordResetToken) {
    return (
      <PasswordResetGate
        uiLanguage={uiLanguage}
        pending={authSubmitting}
        error={authError}
        onSubmit={handleConfirmPasswordReset}
        onCancel={() => {
          window.history.replaceState({}, "", window.location.pathname);
          setPasswordResetToken(null);
          setAuthError(null);
        }}
      />
    );
  }

  if (authStatus === "anonymous" || authUser === null) {
    return (
      <AuthGate
        uiLanguage={uiLanguage}
        pending={authSubmitting}
        error={authError}
        notice={authNotice}
        onSubmit={handleAuthenticate}
        onRequestPasswordReset={handleRequestPasswordReset}
      />
    );
  }

  if (!authUser.email_verified) {
    return (
      <EmailVerificationGate
        uiLanguage={uiLanguage}
        email={authUser.email}
        pending={resendingVerification}
        loggingOut={loggingOut}
        error={authError}
        notice={authNotice}
        onResend={handleResendVerification}
        onLogout={handleLogout}
      />
    );
  }

  if (!workspaceInitialized) {
    if (workspaceLoading || !error) return <WorkspaceSkeleton uiLanguage={uiLanguage} />;
    return (
      <WorkspaceLoadFailure
        uiLanguage={uiLanguage}
        error={error}
        loading={workspaceLoading}
        onRetry={() => void loadWorkspace()}
        onLogout={() => void handleLogout()}
      />
    );
  }

  if (showStoryWizard || storyList.length === 0) {
    return (
      <StoryWizard
        uiLanguage={uiLanguage}
        storageKey={storyWizardStorageKey(authUser.id)}
        creating={creatingStory}
        error={error}
        canCancel={storyList.length > 0}
        onCancel={() => {
          setShowStoryWizard(false);
          syncStoryWizardLocation(false, "replace");
          setError(null);
        }}
        onSubmit={handleSubmitStoryWizard}
        onLogout={() => void handleLogout()}
      />
    );
  }

  return (
    <main className="makeShell">
      <header className="makeTopbar">
        <div className="makeBrand">
          <span className="makeLogo">
            <Feather size={16} />
          </span>
          <strong>Witscraft</strong>
        </div>

        <nav className="viewTabs" aria-label={uiText(uiLanguage, "主视图", "Main view")}>
          <TabButton active={view === "story"} onClick={() => setView("story")} icon={BookOpen} label={uiText(uiLanguage, "故事", "Story")} />
          <TabButton active={view === "settings"} onClick={() => setView("settings")} icon={Settings2} label={uiText(uiLanguage, "设置", "Settings")} />
        </nav>

        <div className="topbarSpacer" />

        <QuotaMeter quota={quota} uiLanguage={uiLanguage} compact />

        {authUser.is_admin && (
          <Link className="adminNavLink" href="/admin" title={uiText(uiLanguage, "管理员控制台", "Administrator console")}>
            <ShieldCheck size={14} />
            <span>{uiText(uiLanguage, "管理", "Admin")}</span>
          </Link>
        )}

        {view === "story" && (
          <div className="tabletToggles">
            <IconToggle
              active={leftOpen}
              onClick={() => {
                setLeftOpen((value) => !value);
                setRightOpen(false);
              }}
              icon={PanelLeft}
              label={uiText(uiLanguage, "切换小说面板", "Toggle stories panel")}
            />
            <IconToggle
              active={rightOpen}
              onClick={() => {
                setRightOpen((value) => !value);
                setLeftOpen(false);
              }}
              icon={PanelRight}
              label={uiText(uiLanguage, "切换检查器面板", "Toggle inspector panel")}
            />
          </div>
        )}

        <SelectMenu
          className="purposeMenu"
          icon={Route}
          label={uiText(uiLanguage, "选择模型用途", "Select model purpose")}
          value={selectedPurpose}
          options={purposeRoutes.map((route) => ({ value: route.id, label: uiLanguage === "zh-CN" ? purposeRoutesZh[route.id].label : route.label }))}
          onChange={(value) => setSelectedPurpose(value as StoryPurpose)}
        />

        <SelectMenu
          className="modelMenu"
          icon={Sparkles}
          label={uiText(uiLanguage, "选择模型", "Select model")}
          value={activeModel?.model ?? ""}
          options={models.map((model) => ({
            value: model.model,
            label: model.label,
            detail: model.provider,
            disabled: providers?.model_health[model.model]?.fresh && providers.model_health[model.model].status === "unavailable"
          }))}
          onChange={(value) => setRouteModel(selectedPurpose, value)}
          disabled={!models.length}
          placeholder={uiText(uiLanguage, "模型加载中", "Loading models")}
        />

        <IconToggle active={dark} onClick={() => setDark((value) => !value)} icon={dark ? Sun : Moon} label={uiText(uiLanguage, "切换主题", "Toggle theme")} />

        <div className="authUserMenu">
          <UserRound size={14} />
          <span>
            <b>{authUser.display_name}</b>
            <small>{authUser.email}</small>
          </span>
          <button type="button" className="plainIcon" aria-label={uiText(uiLanguage, "退出登录", "Sign out")} title={uiText(uiLanguage, "退出登录", "Sign out")} onClick={() => void handleLogout()} disabled={loggingOut}>
            {loggingOut ? <RefreshCw size={14} className="spinIcon" /> : <LogOut size={14} />}
          </button>
        </div>
      </header>

      {view === "settings" ? (
        <SettingsView
          uiLanguage={uiLanguage}
          onUiLanguageChange={setUiLanguage}
          authUser={authUser}
          quota={quota}
          authSessions={authSessions}
          loadingAuthSessions={loadingAuthSessions}
          revokingSessionId={revokingSessionId}
          confirmRevokeSessionId={confirmRevokeSessionId}
          sessionError={sessionError}
          exportingAccount={exportingAccount}
          deletingAccount={deletingAccount}
          accountActionError={accountActionError}
          models={models}
          providers={providers}
          selectedPurpose={selectedPurpose}
          routeModels={routeModels}
          routeDirty={routeDirty}
          savingRoutes={savingRoutes}
          routeNotice={routeNotice}
          routeError={routeError}
          checkingModelId={checkingModelId}
          modelHealthNotice={modelHealthNotice}
          modelHealthError={modelHealthError}
          userPreferences={userPreferences}
          preferenceDirty={preferenceDirty}
          savingPreferences={savingPreferences}
          preferenceNotice={preferenceNotice}
          preferenceError={preferenceError}
          onSelectPurpose={setSelectedPurpose}
          onSelectRouteModel={setRouteModel}
          onRestoreSavedRoutes={handleRestoreSavedRoutes}
          onUseDefaultRoutes={handleUseDefaultRoutes}
          onTestModel={(model) => void handleTestModel(model)}
          onChangePreference={setPreferenceValue}
          onSavePreferences={handleSavePreferences}
          onRevokeSession={handleRevokeSession}
          onCancelRevokeSession={() => setConfirmRevokeSessionId(null)}
          onExportAccount={() => void handleAccountExport()}
          onDeleteAccount={(password, confirmation) => void handleDeleteAccount(password, confirmation)}
        />
      ) : (
        <section className="storyWorkspace">
          <aside className={`libraryRail ${leftOpen ? "isOpen" : ""}`}>
            <LeftRail
              uiLanguage={uiLanguage}
              stories={storyList}
              activeStoryId={storyId}
              world={world}
              worlds={worldList}
              characters={characterList}
              loading={workspaceLoading}
              creatingStory={creatingStory}
              editingStoryId={editingStoryId}
              storyTitleDraft={storyTitleDraft}
              savingStory={savingStory}
              confirmDeleteStoryId={confirmDeleteStoryId}
              deletingStoryId={deletingStoryId}
              editingWorld={editingWorld}
              creatingWorld={creatingWorld}
              worldDraft={worldDraft}
              savingWorld={savingWorld}
              switchingWorldId={switchingWorldId}
              confirmDeleteWorldId={confirmDeleteWorldId}
              deletingWorldId={deletingWorldId}
              editingCharacterId={editingCharacterId}
              creatingCharacter={creatingCharacter}
              characterDraft={characterDraft}
              savingCharacterId={savingCharacterId}
              confirmDeleteCharacterId={confirmDeleteCharacterId}
              deletingCharacterId={deletingCharacterId}
              onSelectStory={handleSelectStory}
              onCreateStory={handleCreateStory}
              onStartRename={handleStartRename}
              onCancelRename={handleCancelRename}
              onChangeStoryTitleDraft={setStoryTitleDraft}
              onSaveRename={handleSaveRename}
              onRequestDelete={handleRequestDelete}
              onCancelDelete={() => setConfirmDeleteStoryId(null)}
              onDeleteStory={handleDeleteStory}
              onStartEditWorld={handleStartEditWorld}
              onStartCreateWorld={handleStartCreateWorld}
              onCancelEditWorld={handleCancelEditWorld}
              onChangeWorldDraft={setWorldDraft}
              onSaveWorld={handleSaveWorld}
              onSelectWorld={handleSelectWorld}
              onDeleteWorld={handleDeleteWorld}
              onStartEditCharacter={handleStartEditCharacter}
              onStartCreateCharacter={handleStartCreateCharacter}
              onCancelEditCharacter={handleCancelEditCharacter}
              onChangeCharacterDraft={setCharacterDraft}
              onSaveCharacter={handleSaveCharacter}
              onDeleteCharacter={handleDeleteCharacter}
            />
          </aside>

          <section className={`storyStage ${mobileTab === "story" ? "isMobileActive" : ""}`}>
            <Transcript
              uiLanguage={uiLanguage}
              messages={messages}
              state={state}
              storyTitle={activeStoryTitle}
              branchName={activeBranchName}
              draft={draft}
              setDraft={setDraft}
              pending={pending}
              error={error}
              recoveryKind={recoveryKind}
              pendingModelLabel={activeModel?.label ?? uiText(uiLanguage, "模型", "Model")}
              interactionMode={interactionMode}
              savingInteractionMode={savingInteractionMode}
              consistencyMode={consistencyMode}
              savingConsistencyMode={savingConsistencyMode}
              storyPrompt={storyPrompt}
              storyPromptDirty={storyPromptDirty}
              savingStoryPrompt={savingStoryPrompt}
              storyPromptNotice={storyPromptNotice}
              onChangeStoryPrompt={(value) => { setStoryPrompt(value); setStoryPromptNotice(null); }}
              onSaveStoryPrompt={handleSaveStoryPrompt}
              onSend={() => void handleSend()}
              onSelectChoice={(choice) => void handleSend(choice)}
              onInteractionModeChange={(mode) => void handleInteractionModeChange(mode)}
              onConsistencyModeChange={(mode) => void handleConsistencyModeChange(mode)}
              onStop={handleStopGeneration}
              onResync={() => void handleResyncWorkspace()}
              onContinue={() => void handleSend("继续当前场景，但不要替我做重大决定。")}
              onRegenerate={(messageId) => void handleMessageCommand(messageId, "regenerate")}
              onRewrite={(messageId) => void handleMessageCommand(messageId, "rewrite")}
              onConfirmConsistency={(messageId) => void handleMessageCommand(messageId, "rewrite", "修复后端一致性检查发现的全部参数、人物、剧情与世界设定冲突；保留原有文风、节奏和剧情意图，只输出修订后的正文。")}
            />
          </section>

          <aside className={`inspectorRail ${rightOpen ? "isOpen" : ""}`}>
              <RightInspector
              uiLanguage={uiLanguage}
              state={state}
              branches={branchList}
              activeBranchId={branchId}
              creatingBranch={creatingBranch}
              switchingBranchId={switchingBranchId}
              editingBranchId={editingBranchId}
              branchNameDraft={branchNameDraft}
              savingBranchId={savingBranchId}
              duplicatingBranchId={duplicatingBranchId}
              confirmDeleteBranchId={confirmDeleteBranchId}
              deletingBranchId={deletingBranchId}
              memoryItems={memoryItems}
              canonFactItems={canonFactItems}
              summaries={summaries}
              summarizing={summarizing}
              exportingFormat={exportingFormat}
              lastRun={lastRun}
              activeModel={activeModel}
              selectedPurpose={selectedPurpose}
              relationships={relationshipList}
              onCreateBranch={handleCreateBranch}
              onSwitchBranch={handleSwitchBranch}
              onStartEditBranch={handleStartEditBranch}
              onCancelEditBranch={handleCancelEditBranch}
              onChangeBranchName={setBranchNameDraft}
              onSaveBranch={handleSaveBranch}
              onDuplicateBranch={handleDuplicateBranch}
              onDeleteBranch={handleDeleteBranch}
              onGenerateSummary={handleGenerateSummary}
              onExportStory={handleExportStory}
              editingMemoryId={editingMemoryId}
              memoryDraft={memoryDraft}
              savingMemoryId={savingMemoryId}
              editingCanonFactId={editingCanonFactId}
              canonFactDraft={canonFactDraft}
              savingCanonFactId={savingCanonFactId}
              onStartEditMemory={handleStartEditMemory}
              onCancelEditMemory={handleCancelEditMemory}
              onChangeMemoryDraft={setMemoryDraft}
              onSaveMemory={handleSaveMemory}
              onStartEditCanonFact={handleStartEditCanonFact}
              onCancelEditCanonFact={handleCancelEditCanonFact}
              onChangeCanonFactDraft={setCanonFactDraft}
              onSaveCanonFact={handleSaveCanonFact}
            />
          </aside>

          {(leftOpen || rightOpen) && (
            <button
              className="drawerScrim"
              aria-label={uiText(uiLanguage, "关闭面板", "Close panel")}
              onClick={() => {
                setLeftOpen(false);
                setRightOpen(false);
              }}
            />
          )}

          <nav className="mobileTabs" aria-label={uiText(uiLanguage, "移动端导航", "Mobile navigation")}>
            <MobileTabButton active={mobileTab === "library"} onClick={() => setMobileTab("library")} icon={Globe2} label={uiText(uiLanguage, "资料库", "Library")} />
            <MobileTabButton active={mobileTab === "story"} onClick={() => setMobileTab("story")} icon={BookOpen} label={uiText(uiLanguage, "故事", "Story")} />
            <MobileTabButton active={mobileTab === "inspector"} onClick={() => setMobileTab("inspector")} icon={ClipboardList} label={uiText(uiLanguage, "检查器", "Inspector")} />
          </nav>
        </section>
      )}
    </main>
  );
}

function AuthLoading({ uiLanguage, label }: { uiLanguage: UiLanguage; label?: string }) {
  return (
    <main className="authShell">
      <div className="authLoading" aria-live="polite">
        <span className="makeLogo"><Feather size={17} /></span>
        <RefreshCw size={17} className="spinIcon" />
        <span>{label ?? uiText(uiLanguage, "正在检查登录状态", "Checking sign-in status")}</span>
      </div>
    </main>
  );
}

function WorkspaceSkeleton({ uiLanguage }: { uiLanguage: UiLanguage }) {
  return (
    <main className="makeShell workspaceSkeleton" aria-busy="true" aria-label={uiText(uiLanguage, "正在读取工作区", "Loading workspace")}>
      <header className="makeTopbar">
        <div className="makeBrand"><span className="makeLogo"><Feather size={16} /></span><strong>Witscraft</strong></div>
        <div className="skeletonLine short" />
        <div className="topbarSpacer" />
        <div className="skeletonControl" />
        <div className="skeletonControl" />
      </header>
      <section className="storyWorkspace">
        <aside className="libraryRail skeletonRail">
          <div className="skeletonLine medium" />
          {[0, 1, 2].map((item) => <div className="skeletonBlock" key={item} />)}
        </aside>
        <section className="storyStage skeletonStage">
          <div className="skeletonRibbon" />
          <div className="skeletonProse">
            <div className="skeletonLine medium" />
            <div className="skeletonLine full" />
            <div className="skeletonLine full" />
            <div className="skeletonLine wide" />
            <div className="skeletonLine full" />
            <div className="skeletonLine medium" />
          </div>
          <div className="skeletonComposer" />
        </section>
        <aside className="inspectorRail skeletonRail">
          <div className="skeletonLine medium" />
          {[0, 1, 2, 3].map((item) => <div className="skeletonBlock compact" key={item} />)}
        </aside>
      </section>
      <span className="srOnly" aria-live="polite">{uiText(uiLanguage, "正在读取工作区", "Loading workspace")}</span>
    </main>
  );
}

function AuthGate({
  uiLanguage,
  pending,
  error,
  notice,
  onSubmit,
  onRequestPasswordReset
}: {
  uiLanguage: UiLanguage;
  pending: boolean;
  error: string | null;
  notice: string | null;
  onSubmit: (mode: "login" | "register", input: LoginInput | RegisterInput) => void;
  onRequestPasswordReset: (email: string) => void;
}) {
  const [mode, setMode] = useState<"login" | "register" | "recovery">("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState("");
  const canSubmit = email.trim().length >= 3
    && (mode === "recovery" || password.length >= (mode === "register" ? 12 : 1))
    && (mode !== "register" || displayName.trim().length > 0);

  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="auth-title">
        <header className="authBrand">
          <span className="makeLogo"><Feather size={17} /></span>
          <strong>Witscraft</strong>
        </header>

        <div className="authHeading">
          <h1 id="auth-title">{mode === "login" ? uiText(uiLanguage, "登录", "Sign in") : mode === "register" ? uiText(uiLanguage, "创建账号", "Create account") : uiText(uiLanguage, "找回密码", "Reset password")}</h1>
          <p>{mode === "login" ? uiText(uiLanguage, "继续你的小说工作区", "Continue to your writing workspace") : mode === "register" ? uiText(uiLanguage, "建立你的私人小说工作区", "Create your private writing workspace") : uiText(uiLanguage, "我们会向注册邮箱发送一次性重置链接", "We will email a one-time reset link to your registered address")}</p>
        </div>

        {mode === "recovery" ? (
          <button className="authTextButton" type="button" onClick={() => setMode("login")} disabled={pending}>
            <ArrowRight size={13} className="authBackIcon" /> {uiText(uiLanguage, "返回登录", "Back to sign in")}
          </button>
        ) : (
          <div className="authMode" role="tablist" aria-label={uiText(uiLanguage, "认证方式", "Authentication method")}>
            <button type="button" role="tab" aria-selected={mode === "login"} className={mode === "login" ? "active" : undefined} onClick={() => setMode("login")} disabled={pending}>
              {uiText(uiLanguage, "登录", "Sign in")}
            </button>
            <button type="button" role="tab" aria-selected={mode === "register"} className={mode === "register" ? "active" : undefined} onClick={() => setMode("register")} disabled={pending}>
              {uiText(uiLanguage, "注册", "Register")}
            </button>
          </div>
        )}

        <form
          className="authForm"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit || pending) return;
            if (mode === "recovery") {
              onRequestPasswordReset(email.trim());
            } else if (mode === "register") {
              onSubmit(mode, { email: email.trim(), password, displayName: displayName.trim() });
            } else {
              onSubmit(mode, { email: email.trim(), password });
            }
          }}
        >
          {mode === "register" && (
            <label>
              <span>{uiText(uiLanguage, "显示名称", "Display name")}</span>
              <span className="authField">
                <UserRound size={15} />
                <input
                  type="text"
                  value={displayName}
                  onChange={(event) => setDisplayName(event.target.value)}
                  autoComplete="name"
                  maxLength={120}
                  aria-label={uiText(uiLanguage, "显示名称", "Display name")}
                  disabled={pending}
                />
              </span>
            </label>
          )}

          <label>
            <span>{uiText(uiLanguage, "邮箱", "Email")}</span>
            <span className="authField">
              <Mail size={15} />
              <input
                type="email"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                autoComplete="email"
                aria-label={uiText(uiLanguage, "邮箱", "Email")}
                disabled={pending}
              />
            </span>
          </label>

          {mode !== "recovery" && (
            <label>
              <span>{uiText(uiLanguage, "密码", "Password")}</span>
              <span className="authField">
                <Lock size={15} />
                <input
                  type="password"
                  value={password}
                  onChange={(event) => setPassword(event.target.value)}
                  autoComplete={mode === "register" ? "new-password" : "current-password"}
                  minLength={mode === "register" ? 12 : 1}
                  maxLength={128}
                  aria-label={uiText(uiLanguage, "密码", "Password")}
                  disabled={pending}
                />
              </span>
              {mode === "register" && <small>{uiText(uiLanguage, "至少 12 个字符", "At least 12 characters")}</small>}
            </label>
          )}

          {mode === "login" && (
            <button className="authTextButton authForgot" type="button" onClick={() => setMode("recovery")} disabled={pending}>
              {uiText(uiLanguage, "忘记密码？", "Forgot password?")}
            </button>
          )}

          {error && <div className="authError" role="alert">{error}</div>}
          {notice && <div className="authNotice" role="status">{notice}</div>}

          <button className="authSubmit" type="submit" disabled={!canSubmit || pending}>
            {pending ? <RefreshCw size={15} className="spinIcon" /> : <ArrowRight size={15} />}
            {pending ? uiText(uiLanguage, "请稍候", "Please wait") : mode === "login" ? uiText(uiLanguage, "登录工作区", "Open workspace") : mode === "register" ? uiText(uiLanguage, "创建账号", "Create account") : uiText(uiLanguage, "发送重置链接", "Send reset link")}
          </button>
        </form>
      </section>
    </main>
  );
}

function EmailVerificationGate({
  uiLanguage,
  email,
  pending,
  loggingOut,
  error,
  notice,
  onResend,
  onLogout
}: {
  uiLanguage: UiLanguage;
  email: string;
  pending: boolean;
  loggingOut: boolean;
  error: string | null;
  notice: string | null;
  onResend: () => void;
  onLogout: () => void;
}) {
  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="verification-title">
        <header className="authBrand">
          <span className="makeLogo"><Feather size={17} /></span>
          <strong>Witscraft</strong>
        </header>
        <div className="authStatusIcon"><Mail size={22} /></div>
        <div className="authHeading">
          <h1 id="verification-title">{uiText(uiLanguage, "验证你的邮箱", "Verify your email")}</h1>
          <p>{uiText(uiLanguage, "验证链接已发送到", "A verification link was sent to")} <b>{email}</b>{uiText(uiLanguage, "。完成验证后即可进入工作区。", ". Verify it to enter your workspace.")}</p>
        </div>
        {error && <div className="authError" role="alert">{error}</div>}
        {notice && <div className="authNotice" role="status">{notice}</div>}
        <div className="authActions">
          <button className="authSubmit" type="button" onClick={onResend} disabled={pending || loggingOut}>
            {pending ? <RefreshCw size={15} className="spinIcon" /> : <Send size={15} />}
            {pending ? uiText(uiLanguage, "正在发送", "Sending") : uiText(uiLanguage, "重新发送验证邮件", "Resend verification email")}
          </button>
          <button className="cmdButton" type="button" onClick={onLogout} disabled={pending || loggingOut}>
            {loggingOut ? <RefreshCw size={14} className="spinIcon" /> : <LogOut size={14} />}
            {uiText(uiLanguage, "退出账号", "Sign out")}
          </button>
        </div>
      </section>
    </main>
  );
}

function PasswordResetGate({
  uiLanguage,
  pending,
  error,
  onSubmit,
  onCancel
}: {
  uiLanguage: UiLanguage;
  pending: boolean;
  error: string | null;
  onSubmit: (password: string) => void;
  onCancel: () => void;
}) {
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const mismatch = confirmation.length > 0 && password !== confirmation;
  const canSubmit = password.length >= 12 && password === confirmation;

  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="reset-title">
        <header className="authBrand">
          <span className="makeLogo"><Feather size={17} /></span>
          <strong>Witscraft</strong>
        </header>
        <div className="authStatusIcon"><ShieldCheck size={22} /></div>
        <div className="authHeading">
          <h1 id="reset-title">{uiText(uiLanguage, "设置新密码", "Set a new password")}</h1>
          <p>{uiText(uiLanguage, "新密码至少需要 12 个字符，提交后所有旧登录会话都会失效。", "Use at least 12 characters. Submitting will sign out all existing sessions.")}</p>
        </div>
        <form className="authForm" onSubmit={(event) => { event.preventDefault(); if (canSubmit && !pending) onSubmit(password); }}>
          <label>
            <span>{uiText(uiLanguage, "新密码", "New password")}</span>
            <span className="authField"><Lock size={15} /><input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={password} onChange={(event) => setPassword(event.target.value)} disabled={pending} /></span>
          </label>
          <label>
            <span>{uiText(uiLanguage, "确认新密码", "Confirm new password")}</span>
            <span className="authField"><Lock size={15} /><input type="password" autoComplete="new-password" minLength={12} maxLength={128} value={confirmation} onChange={(event) => setConfirmation(event.target.value)} disabled={pending} /></span>
            {mismatch && <small className="fieldError">{uiText(uiLanguage, "两次输入的密码不一致", "Passwords do not match")}</small>}
          </label>
          {error && <div className="authError" role="alert">{error}</div>}
          <button className="authSubmit" type="submit" disabled={!canSubmit || pending}>
            {pending ? <RefreshCw size={15} className="spinIcon" /> : <Check size={15} />}
            {pending ? uiText(uiLanguage, "正在重置", "Resetting") : uiText(uiLanguage, "重置密码", "Reset password")}
          </button>
          <button className="authTextButton" type="button" onClick={onCancel} disabled={pending}>{uiText(uiLanguage, "返回登录", "Back to sign in")}</button>
        </form>
      </section>
    </main>
  );
}

function WorkspaceLoadFailure({
  uiLanguage,
  error,
  loading,
  onRetry,
  onLogout
}: {
  uiLanguage: UiLanguage;
  error: string;
  loading: boolean;
  onRetry: () => void;
  onLogout: () => void;
}) {
  return (
    <main className="authShell">
      <section className="authPanel" aria-labelledby="workspace-error-title">
        <header className="authBrand">
          <span className="makeLogo"><Feather size={17} /></span>
          <strong>Witscraft</strong>
        </header>
        <div className="authStatusIcon"><AlertTriangle size={22} /></div>
        <div className="authHeading">
          <h1 id="workspace-error-title">{uiText(uiLanguage, "工作区暂时不可用", "Workspace unavailable")}</h1>
          <p>{error}</p>
        </div>
        <div className="authActions">
          <button className="authSubmit" type="button" onClick={onRetry} disabled={loading}>
            {loading ? <RefreshCw size={15} className="spinIcon" /> : <RefreshCw size={15} />}
            {uiText(uiLanguage, "重新读取", "Retry")}
          </button>
          <button className="cmdButton" type="button" onClick={onLogout}><LogOut size={14} />{uiText(uiLanguage, "退出账号", "Sign out")}</button>
        </div>
      </section>
    </main>
  );
}

function StoryWizard({
  uiLanguage,
  storageKey,
  creating,
  error,
  canCancel,
  onCancel,
  onSubmit,
  onLogout
}: {
  uiLanguage: UiLanguage;
  storageKey: string;
  creating: boolean;
  error: string | null;
  canCancel: boolean;
  onCancel: () => void;
  onSubmit: (input: CreateStoryInput) => void;
  onLogout: () => void;
}) {
  const [interviewText, setInterviewText] = useState("");
  const [interviewPending, setInterviewPending] = useState(false);
  const [interviewError, setInterviewError] = useState<string | null>(null);
  const [streamedAssistant, setStreamedAssistant] = useState("");
  const [mobileWizardView, setMobileWizardView] = useState<"chat" | "card">("chat");
  const [customInterviewAnswerActive, setCustomInterviewAnswerActive] = useState(false);
  const [wizardHydrated, setWizardHydrated] = useState(false);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [interviewMessages, setInterviewMessages] = useState<StoryInterviewMessage[]>(initialStoryInterviewMessages);
  const [draft, setDraft] = useState<CreateStoryInput>(initialStoryDraft);
  const requiredFields = [
    ["title", uiText(uiLanguage, "书名", "Title"), draft.title],
    ["genre", uiText(uiLanguage, "类型", "Genre"), draft.genre],
    ["world_name", uiText(uiLanguage, "世界", "World"), draft.worldName],
    ["premise", uiText(uiLanguage, "故事前提", "Premise"), draft.premise],
    ["protagonist_name", uiText(uiLanguage, "主角", "Protagonist"), draft.protagonistName],
    ["protagonist_role", uiText(uiLanguage, "主角身份与目标", "Protagonist role and goal"), draft.protagonistRole],
    ["tone", uiText(uiLanguage, "叙事风格", "Narrative style"), draft.tone],
    ["custom_prompt", uiText(uiLanguage, "小说专属 Prompt", "Story prompt"), draft.customPrompt]
  ] as const;
  const missingFields: Array<{ id: string; label: string }> = requiredFields
    .filter(([, , value]) => !value.trim())
    .map(([id, label]) => ({ id, label }));
  if (draft.openingMode === "custom" && !draft.openingText.trim()) {
    missingFields.push({ id: "opening_text", label: uiText(uiLanguage, "开场正文", "Opening prose") });
  }
  const readyToCreate = missingFields.length === 0;

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored) as { messages?: StoryInterviewMessage[]; draft?: CreateStoryInput };
        if (Array.isArray(parsed.messages) && parsed.messages.length > 0) {
          setInterviewMessages(parsed.messages.slice(-40));
        }
        if (parsed.draft && typeof parsed.draft === "object") {
          setDraft({ ...initialStoryDraft(), ...parsed.draft });
        }
      }
    } catch {
      window.localStorage.removeItem(storageKey);
    } finally {
      setWizardHydrated(true);
    }
  }, [storageKey]);

  useEffect(() => {
    if (!wizardHydrated) return;
    window.localStorage.setItem(storageKey, JSON.stringify({ messages: interviewMessages, draft }));
  }, [draft, interviewMessages, storageKey, wizardHydrated]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;
    const frame = window.requestAnimationFrame(() => {
      transcript.scrollTop = transcript.scrollHeight;
    });
    return () => window.cancelAnimationFrame(frame);
  }, [interviewMessages, streamedAssistant, interviewPending]);

  const updateDraft = (next: Partial<CreateStoryInput>) => setDraft((current) => ({ ...current, ...next }));
  const sendInterviewMessage = async (answer?: string) => {
    const message = (answer ?? interviewText).trim();
    if (!message || interviewPending || creating) return;
    const history = interviewMessages.slice(-20);
    setInterviewMessages((current) => [...current, { role: "user", content: message }]);
    setInterviewText("");
    setCustomInterviewAnswerActive(false);
    setStreamedAssistant("");
    setInterviewPending(true);
    setInterviewError(null);
    setMobileWizardView("chat");
    let partial = "";
    try {
      await streamStoryInterview(
        { message, draft, history },
        {
          onDelta: (content) => {
            partial += content;
            setStreamedAssistant(partial);
          },
          onReplace: (content) => {
            partial = content;
            setStreamedAssistant(content);
          },
          onDone: (response) => {
            setDraft(response.draft);
            setInterviewMessages((current) => [
              ...current,
              {
                role: "assistant",
                content: response.assistantMessage,
                options: response.options,
                ready: response.readyForConfirmation
              }
            ]);
            setStreamedAssistant("");
          }
        }
      );
    } catch (caught) {
      if (partial) {
        setInterviewMessages((current) => [...current, { role: "assistant", content: `${partial}\n\n回复中断，请重试。` }]);
        setStreamedAssistant("");
      }
      setInterviewError(caught instanceof ApiError ? caught.message : "AI 采访暂时不可用；卡片内容已保留，你仍可直接编辑。");
    } finally {
      setInterviewPending(false);
    }
  };

  return (
    <main className="wizardShell">
      <section className="wizardPanel" aria-labelledby="wizard-title">
        <header className="wizardHeader">
          <div className="authBrand">
            <span className="makeLogo"><Feather size={17} /></span>
            <strong>Witscraft</strong>
          </div>
          <div className="wizardHeaderActions">
            {canCancel && <button className="plainIcon" type="button" aria-label={uiText(uiLanguage, "关闭创作向导", "Close creation guide")} title={uiText(uiLanguage, "关闭", "Close")} onClick={onCancel} disabled={creating}><X size={15} /></button>}
            <button className="plainIcon" type="button" aria-label={uiText(uiLanguage, "退出登录", "Sign out")} title={uiText(uiLanguage, "退出登录", "Sign out")} onClick={onLogout} disabled={creating}><LogOut size={15} /></button>
          </div>
        </header>
        <div className="wizardHeading">
          <div>
            <span>{uiText(uiLanguage, "AI 创作采访", "AI story interview")}</span>
            <h1 id="wizard-title">{uiText(uiLanguage, "聊出你的新小说", "Shape your new story")}</h1>
          </div>
          <span className={readyToCreate ? "wizardReady" : "wizardMissing"}>
            {readyToCreate ? <CheckCircle2 size={13} /> : <CircleDashed size={13} />}
            {readyToCreate ? uiText(uiLanguage, "可以确认", "Ready to confirm") : uiText(uiLanguage, `还缺 ${missingFields.length} 项`, `${missingFields.length} items missing`)}
          </span>
        </div>

        <div className="wizardMobileSwitch" role="tablist" aria-label={uiText(uiLanguage, "创作向导视图", "Creation guide view")}>
          <button type="button" role="tab" aria-selected={mobileWizardView === "chat"} className={mobileWizardView === "chat" ? "active" : undefined} onClick={() => setMobileWizardView("chat")}>
            <MessageCircle size={14} />{uiText(uiLanguage, "对话", "Chat")}
          </button>
          <button type="button" role="tab" aria-selected={mobileWizardView === "card"} className={mobileWizardView === "card" ? "active" : undefined} onClick={() => setMobileWizardView("card")}>
            <FileText size={14} />{uiText(uiLanguage, "故事卡", "Story card")}<span>{readyToCreate ? <Check size={12} /> : missingFields.length}</span>
          </button>
        </div>

        <div className={`interviewLayout mobile-${mobileWizardView}`}>
          <section className="interviewChat" aria-label={uiText(uiLanguage, "AI 创作采访", "AI story interview")}>
            <div className="interviewTranscript" aria-live="polite" ref={transcriptRef}>
              {interviewMessages.map((message, index) => (
                <article key={`${message.role}-${index}`} className={`interviewBubble ${message.role}`}>
                  <span>{message.role === "assistant" ? <Sparkles size={13} /> : <UserRound size={13} />}</span>
                  <div className="interviewBubbleBody">
                    <p>{message.content}</p>
                    {draft.interactionMode === "choices" && message.role === "assistant" && index === interviewMessages.length - 1 && !interviewPending && message.options && message.options.length > 0 && (
                      <div className="interviewOptions" aria-label={uiText(uiLanguage, "回答选项", "Answer options")}>
                        {message.options.map((option) => (
                          <button type="button" key={option} onClick={() => void sendInterviewMessage(option)}>{option}</button>
                        ))}
                        <button
                          type="button"
                          className="customOption"
                          onClick={() => {
                            setCustomInterviewAnswerActive(true);
                            composerRef.current?.focus();
                          }}
                        >
                          <PenLine size={13} />{uiText(uiLanguage, "自定义", "Custom")}
                        </button>
                      </div>
                    )}
                    {message.ready && index === interviewMessages.length - 1 && (
                      <button type="button" className="interviewReadyAction" onClick={() => setMobileWizardView("card")}>
                        <FileText size={13} />{uiText(uiLanguage, "查看故事确认卡", "Review story card")}
                      </button>
                    )}
                  </div>
                </article>
              ))}
              {streamedAssistant && (
                <article className="interviewBubble assistant streaming">
                  <span><Sparkles size={13} /></span><div className="interviewBubbleBody"><p>{streamedAssistant}<i className="streamCaret" /></p></div>
                </article>
              )}
              {interviewPending && !streamedAssistant && (
                <article className="interviewBubble assistant pending">
                  <span><RefreshCw size={13} className="spinIcon" /></span><div className="interviewBubbleBody"><p>{uiText(uiLanguage, "正在整理你的想法…", "Organizing your ideas...")}</p></div>
                </article>
              )}
            </div>
            {(error || interviewError) && <div className="authError" role="alert">{error || interviewError}</div>}
            {customInterviewAnswerActive && (
              <div className="interviewCustomHint" role="status"><PenLine size={13} />{uiText(uiLanguage, "请在下方输入你的自定义答案，然后点击发送。", "Enter your custom answer below, then send it.")}</div>
            )}
            <form className="interviewComposer" onSubmit={(event) => { event.preventDefault(); void sendInterviewMessage(); }}>
              <textarea
                rows={3}
                maxLength={4000}
                value={interviewText}
                placeholder={customInterviewAnswerActive ? uiText(uiLanguage, "输入你的自定义答案…", "Enter your custom answer...") : uiText(uiLanguage, "告诉 AI 你的想法，或纠正它对卡片的理解…", "Tell AI your ideas or correct its understanding of the card...")}
                onChange={(event) => setInterviewText(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    void sendInterviewMessage();
                  }
                }}
                disabled={interviewPending || creating}
                autoFocus
                ref={composerRef}
              />
              <button className="plainIcon" type="submit" aria-label={uiText(uiLanguage, "发送给创作助手", "Send to story assistant")} title={uiText(uiLanguage, "发送", "Send")} disabled={!interviewText.trim() || interviewPending || creating}>
                <Send size={15} />
              </button>
            </form>
          </section>

          <section className="storyDraftCard" aria-label={uiText(uiLanguage, "可编辑故事确认卡片", "Editable story confirmation card")}>
            <header><span><FileText size={15} /></span><div><b>{uiText(uiLanguage, "故事确认卡", "Story card")}</b><small>{uiText(uiLanguage, "AI 整理后仍可直接修改", "Review and edit anything AI collected")}</small></div></header>
            {missingFields.length > 0 && <p className="draftMissing">{uiText(uiLanguage, "待确认：", "Needs input: ")}{missingFields.map((item) => item.label).join(uiLanguage === "zh-CN" ? "、" : ", ")}</p>}
            <div className="draftCardFields">
              <label><span>{uiText(uiLanguage, "书名", "Title")}</span><input value={draft.title} onChange={(event) => updateDraft({ title: event.target.value })} maxLength={220} /></label>
              <div className="wizardFieldGrid">
                <label><span>{uiText(uiLanguage, "类型", "Genre")}</span><input value={draft.genre} onChange={(event) => updateDraft({ genre: event.target.value })} maxLength={120} /></label>
                <label><span>{uiText(uiLanguage, "叙事风格", "Narrative style")}</span><input value={draft.tone} onChange={(event) => updateDraft({ tone: event.target.value })} maxLength={500} /></label>
              </div>
              <label><span>{uiText(uiLanguage, "世界名称", "World name")}</span><input value={draft.worldName} onChange={(event) => updateDraft({ worldName: event.target.value })} maxLength={180} /></label>
              <label><span>{uiText(uiLanguage, "故事前提", "Premise")}</span><textarea value={draft.premise} onChange={(event) => updateDraft({ premise: event.target.value })} maxLength={4000} rows={4} /></label>
              <div className="wizardFieldGrid">
                <label><span>{uiText(uiLanguage, "主角姓名", "Protagonist name")}</span><input value={draft.protagonistName} onChange={(event) => updateDraft({ protagonistName: event.target.value })} maxLength={180} /></label>
                <label><span>{uiText(uiLanguage, "主角身份与目标", "Protagonist role and goal")}</span><textarea value={draft.protagonistRole} onChange={(event) => updateDraft({ protagonistRole: event.target.value })} maxLength={2000} rows={3} /></label>
              </div>
              <div className="draftPromptField">
                <span className="draftPromptHeader">
                  <span>{uiText(uiLanguage, "小说专属 Prompt", "Story prompt")}</span>
                  <button
                    type="button"
                    onClick={() => void sendInterviewMessage("请根据当前故事卡片中的信息，重新生成一份针对这个小说类型的专业创作 Prompt。只更新小说专属 Prompt，保持其他字段不变。")}
                    disabled={interviewPending || creating}
                  >
                    <Sparkles size={12} />{uiText(uiLanguage, "AI 优化", "Improve with AI")}
                  </button>
                </span>
                <textarea aria-label={uiText(uiLanguage, "小说专属 Prompt", "Story prompt")} value={draft.customPrompt} onChange={(event) => updateDraft({ customPrompt: event.target.value })} maxLength={12000} rows={6} placeholder={uiText(uiLanguage, "AI 会根据类型、主角、前提和文风生成可执行的专业 Prompt，你可以继续修改。", "AI will build a professional prompt from the genre, protagonist, premise, and style. You can edit it freely.")} />
              </div>
              <div className="wizardInteractionMode" role="radiogroup" aria-label={uiText(uiLanguage, "小说推进方式", "Story interaction mode")}>
                <button type="button" role="radio" aria-checked={draft.interactionMode === "choices"} className={draft.interactionMode === "choices" ? "active" : undefined} onClick={() => { updateDraft({ interactionMode: "choices" }); setCustomInterviewAnswerActive(false); }}>
                  <ListChecks size={16} /><span><b>{uiText(uiLanguage, "选择式", "Choices")}</b><small>{uiText(uiLanguage, "正文后显示推进选项与自定义入口", "Show next-step choices and a custom option after prose")}</small></span>
                </button>
                <button type="button" role="radio" aria-checked={draft.interactionMode === "open"} className={draft.interactionMode === "open" ? "active" : undefined} onClick={() => { updateDraft({ interactionMode: "open" }); setCustomInterviewAnswerActive(false); }}>
                  <PenLine size={16} /><span><b>{uiText(uiLanguage, "开放式", "Open")}</b><small>{uiText(uiLanguage, "不提供选项，由你自由推进剧情", "Write your own direction without suggested choices")}</small></span>
                </button>
              </div>
              <div className="wizardMode" role="radiogroup" aria-label={uiText(uiLanguage, "开场方式", "Opening mode")}>
                <button type="button" role="radio" aria-checked={draft.openingMode === "blank"} className={draft.openingMode === "blank" ? "active" : undefined} onClick={() => updateDraft({ openingMode: "blank" })}>
                  <BookOpen size={16} /><span><b>{uiText(uiLanguage, "空白开场", "Blank opening")}</b><small>{uiText(uiLanguage, "进入工作区后开始", "Start after entering the workspace")}</small></span>
                </button>
                <button type="button" role="radio" aria-checked={draft.openingMode === "custom"} className={draft.openingMode === "custom" ? "active" : undefined} onClick={() => updateDraft({ openingMode: "custom" })}>
                  <PenLine size={16} /><span><b>{uiText(uiLanguage, "自定义开场", "Custom opening")}</b><small>{uiText(uiLanguage, "保存第一段正文", "Save your first prose passage")}</small></span>
                </button>
              </div>
              {draft.openingMode === "custom" && <label><span>{uiText(uiLanguage, "开场正文", "Opening prose")}</span><textarea value={draft.openingText} onChange={(event) => updateDraft({ openingText: event.target.value })} maxLength={12000} rows={5} /></label>}
            </div>
            <button className="cmdButton primary confirmStoryButton" type="button" onClick={() => onSubmit(draft)} disabled={!readyToCreate || creating || interviewPending}>
              {creating ? <RefreshCw size={14} className="spinIcon" /> : <Check size={14} />}
              {creating ? uiText(uiLanguage, "正在创建", "Creating") : uiText(uiLanguage, "确认并创建小说", "Confirm and create story")}
            </button>
          </section>
        </div>
      </section>
    </main>
  );
}

function LeftRail({
  uiLanguage,
  stories,
  activeStoryId,
  world,
  worlds,
  characters,
  loading,
  creatingStory,
  editingStoryId,
  storyTitleDraft,
  savingStory,
  confirmDeleteStoryId,
  deletingStoryId,
  editingWorld,
  creatingWorld,
  worldDraft,
  savingWorld,
  switchingWorldId,
  confirmDeleteWorldId,
  deletingWorldId,
  editingCharacterId,
  creatingCharacter,
  characterDraft,
  savingCharacterId,
  confirmDeleteCharacterId,
  deletingCharacterId,
  onSelectStory,
  onCreateStory,
  onStartRename,
  onCancelRename,
  onChangeStoryTitleDraft,
  onSaveRename,
  onRequestDelete,
  onCancelDelete,
  onDeleteStory,
  onStartEditWorld,
  onStartCreateWorld,
  onCancelEditWorld,
  onChangeWorldDraft,
  onSaveWorld,
  onSelectWorld,
  onDeleteWorld,
  onStartEditCharacter,
  onStartCreateCharacter,
  onCancelEditCharacter,
  onChangeCharacterDraft,
  onSaveCharacter,
  onDeleteCharacter
}: {
  uiLanguage: UiLanguage;
  stories: StorySummary[];
  activeStoryId: string;
  world: Record<string, unknown>;
  worlds: WorldSummary[];
  characters: CharacterSummary[];
  loading: boolean;
  creatingStory: boolean;
  editingStoryId: string | null;
  storyTitleDraft: string;
  savingStory: boolean;
  confirmDeleteStoryId: string | null;
  deletingStoryId: string | null;
  editingWorld: boolean;
  creatingWorld: boolean;
  worldDraft: WorldDraft;
  savingWorld: boolean;
  switchingWorldId: string | null;
  confirmDeleteWorldId: string | null;
  deletingWorldId: string | null;
  editingCharacterId: string | null;
  creatingCharacter: boolean;
  characterDraft: CharacterDraft;
  savingCharacterId: string | null;
  confirmDeleteCharacterId: string | null;
  deletingCharacterId: string | null;
  onSelectStory: (storyId: string) => void;
  onCreateStory: () => void;
  onStartRename: (storyId: string, title: string) => void;
  onCancelRename: () => void;
  onChangeStoryTitleDraft: (value: string) => void;
  onSaveRename: () => void;
  onRequestDelete: (storyId: string) => void;
  onCancelDelete: () => void;
  onDeleteStory: (storyId: string) => void;
  onStartEditWorld: () => void;
  onStartCreateWorld: () => void;
  onCancelEditWorld: () => void;
  onChangeWorldDraft: (draft: WorldDraft) => void;
  onSaveWorld: () => void;
  onSelectWorld: (worldId: string) => void;
  onDeleteWorld: (worldId: string) => void;
  onStartEditCharacter: (character: CharacterSummary) => void;
  onStartCreateCharacter: () => void;
  onCancelEditCharacter: () => void;
  onChangeCharacterDraft: (draft: CharacterDraft) => void;
  onSaveCharacter: () => void;
  onDeleteCharacter: (character: CharacterSummary) => void;
}) {
  const worldName = String(world.name ?? uiText(uiLanguage, "未命名世界", "Untitled world"));
  const worldDescription = String(world.description ?? uiText(uiLanguage, "尚未写入世界简介。", "No world description yet."));
  const worldGenre = String(world.genre ?? uiText(uiLanguage, "未分类", "Uncategorized"));
  const worldRules = countWorldRules(world.rules);
  const worldLorebook = Array.isArray(world.lorebook) ? world.lorebook.length : 0;
  const canDeleteStories = stories.length > 0;

  return (
    <div className="railScroll">
      <Panel
        title={uiText(uiLanguage, "小说", "Stories")}
        icon={BookText}
        count={stories.length}
        action={
          <button className="plainIcon" aria-label={uiText(uiLanguage, "新建小说", "New story")} onClick={onCreateStory} disabled={creatingStory}>
            {creatingStory ? <RefreshCw size={15} className="spinIcon" /> : <Plus size={15} />}
          </button>
        }
      >
        {stories.length ? (
          <ul className="storyButtons">
            {stories.map((story) => {
              const isActive = story.id === activeStoryId;
              const isEditing = story.id === editingStoryId;
              const isConfirmingDelete = story.id === confirmDeleteStoryId;
              const isDeleting = story.id === deletingStoryId;
              return (
                <li key={story.id}>
                  <div className={`storyItem ${isActive ? "active" : ""} ${isEditing ? "editing" : ""} ${isConfirmingDelete ? "confirming" : ""}`}>
                    {isEditing ? (
                      <div className="storyRenameForm">
                        <input
                          value={storyTitleDraft}
                          onChange={(event) => onChangeStoryTitleDraft(event.target.value)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") onSaveRename();
                            if (event.key === "Escape") onCancelRename();
                          }}
                          aria-label={uiText(uiLanguage, "小说标题", "Story title")}
                          autoFocus
                        />
                        <button className="plainIcon" aria-label={uiText(uiLanguage, "保存小说标题", "Save story title")} onClick={onSaveRename} disabled={savingStory || !storyTitleDraft.trim()}>
                          {savingStory ? <RefreshCw size={15} className="spinIcon" /> : <Check size={15} />}
                        </button>
                        <button className="plainIcon" aria-label={uiText(uiLanguage, "取消编辑标题", "Cancel title edit")} onClick={onCancelRename} disabled={savingStory}>
                          <X size={15} />
                        </button>
                      </div>
                    ) : (
                      <>
                        <button
                          className="storyButton"
                          onClick={() => onSelectStory(story.id)}
                          disabled={loading}
                          aria-current={isActive ? "true" : undefined}
                        >
                          <span>{story.title}</span>
                          <small>
                            {story.world || uiText(uiLanguage, "未绑定世界", "No world")} · {(story.wordCount / 1000).toFixed(1)}k · {formatStoryUpdated(story.updated, uiLanguage)}
                          </small>
                        </button>
                        {isActive && (
                          <div className="storyActions">
                            <button className="plainIcon renameStoryButton" aria-label={uiText(uiLanguage, "重命名小说", "Rename story")} onClick={() => onStartRename(story.id, story.title)} disabled={Boolean(deletingStoryId)}>
                              <PenLine size={14} />
                            </button>
                            <button className="plainIcon deleteStoryButton" aria-label={uiText(uiLanguage, "删除小说", "Delete story")} onClick={() => onRequestDelete(story.id)} disabled={Boolean(deletingStoryId) || !canDeleteStories}>
                              <Trash2 size={14} />
                            </button>
                          </div>
                        )}
                        {!isActive && (
                          <div className="storyActions">
                            <button className="plainIcon deleteStoryButton" aria-label={uiText(uiLanguage, "删除小说", "Delete story")} onClick={() => onRequestDelete(story.id)} disabled={Boolean(deletingStoryId) || !canDeleteStories}>
                              <Trash2 size={14} />
                            </button>
                          </div>
                        )}
                      </>
                    )}
                    {isConfirmingDelete && !isEditing && (
                      <div className="storyDeleteConfirm">
                        <AlertTriangle size={13} />
                        <span>{uiText(uiLanguage, "删除这部小说？", "Delete this story?")}</span>
                        <button className="plainIcon deleteStoryButton danger" aria-label={uiText(uiLanguage, "确认删除小说", "Confirm story deletion")} onClick={() => onDeleteStory(story.id)} disabled={Boolean(deletingStoryId)}>
                          {isDeleting ? <RefreshCw size={14} className="spinIcon" /> : <Trash2 size={14} />}
                        </button>
                        <button className="plainIcon" aria-label={uiText(uiLanguage, "取消删除小说", "Cancel story deletion")} onClick={onCancelDelete} disabled={Boolean(deletingStoryId)}>
                          <X size={14} />
                        </button>
                      </div>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "还没有小说。", "No stories yet.")}</EmptyState>
        )}
      </Panel>

      <Panel
        title={uiText(uiLanguage, "当前世界", "Current world")}
        icon={Globe2}
        action={
          editingWorld ? undefined : (
            <span className="panelActions">
              <button className="plainIcon" aria-label={uiText(uiLanguage, "创建世界", "Create world")} onClick={onStartCreateWorld}>
                <Plus size={14} />
              </button>
              <button className="plainIcon" aria-label={uiText(uiLanguage, "编辑世界", "Edit world")} onClick={onStartEditWorld} disabled={!world.id}>
                <PenLine size={14} />
              </button>
            </span>
          )
        }
      >
        {editingWorld ? (
          <div className="worldEditForm">
            <label>
              <span>{uiText(uiLanguage, "名称", "Name")}</span>
              <input
                value={worldDraft.name}
                onChange={(event) => onChangeWorldDraft({ ...worldDraft, name: event.target.value })}
                aria-label={uiText(uiLanguage, "世界名称", "World name")}
              />
            </label>
            <label>
              <span>{uiText(uiLanguage, "类型", "Genre")}</span>
              <input
                value={worldDraft.genre}
                onChange={(event) => onChangeWorldDraft({ ...worldDraft, genre: event.target.value })}
                aria-label={uiText(uiLanguage, "世界类型", "World genre")}
              />
            </label>
            <label>
              <span>{uiText(uiLanguage, "简介", "Description")}</span>
              <textarea
                value={worldDraft.description}
                onChange={(event) => onChangeWorldDraft({ ...worldDraft, description: event.target.value })}
                aria-label={uiText(uiLanguage, "世界简介", "World description")}
                rows={4}
              />
            </label>
            <div className="formActions">
              <button className="cmdButton primary" onClick={onSaveWorld} disabled={savingWorld || !worldDraft.name.trim()}>
                {savingWorld ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
                {creatingWorld ? uiText(uiLanguage, "创建", "Create") : uiText(uiLanguage, "保存", "Save")}
              </button>
              <button className="cmdButton" onClick={onCancelEditWorld} disabled={savingWorld}>
                <X size={13} />
                {uiText(uiLanguage, "取消", "Cancel")}
              </button>
            </div>
          </div>
        ) : (
          <>
            <div className="worldCard">
              <div>
                <strong>{worldName}</strong>
                <Pill tone="teal">{worldGenre}</Pill>
              </div>
              <p>{worldDescription}</p>
              <dl className="worldStats">
                <div><dd>{worldRules}</dd><dt>{uiText(uiLanguage, "规则", "Rules")}</dt></div>
                <div><dd>{worldLorebook}</dd><dt>{uiText(uiLanguage, "设定", "Lore")}</dt></div>
                <div><dd>{characters.length}</dd><dt>{uiText(uiLanguage, "角色", "Characters")}</dt></div>
              </dl>
            </div>
            {worlds.length > 1 && (
              <ul className="worldList" aria-label={uiText(uiLanguage, "可用世界", "Available worlds")}>
                {worlds.map((item) => {
                  const active = item.id === world.id;
                  const confirming = item.id === confirmDeleteWorldId;
                  return (
                    <li key={item.id} className={active ? "active" : undefined}>
                      <button className="worldSelect" onClick={() => onSelectWorld(item.id)} disabled={active || Boolean(switchingWorldId)}>
                        <span>{item.name}</span>
                        <small>{item.genre || uiText(uiLanguage, "未分类", "Uncategorized")} · {item.story_count} {uiText(uiLanguage, "部小说", item.story_count === 1 ? "story" : "stories")}</small>
                      </button>
                      {!active && (
                        <button className={`plainIcon ${confirming ? "danger" : ""}`} aria-label={confirming ? uiText(uiLanguage, `确认删除世界 ${item.name}`, `Confirm delete world ${item.name}`) : uiText(uiLanguage, `删除世界 ${item.name}`, `Delete world ${item.name}`)} onClick={() => onDeleteWorld(item.id)} disabled={Boolean(deletingWorldId) || item.story_count > 0}>
                          {item.id === deletingWorldId ? <RefreshCw size={13} className="spinIcon" /> : <Trash2 size={13} />}
                        </button>
                      )}
                    </li>
                  );
                })}
              </ul>
            )}
          </>
        )}
      </Panel>

      <Panel
        title={uiText(uiLanguage, "活跃角色", "Active characters")}
        icon={Users}
        count={characters.filter((item) => item.present).length}
        action={
          <button className="plainIcon" aria-label={uiText(uiLanguage, "创建角色", "Create character")} onClick={onStartCreateCharacter} disabled={creatingCharacter || editingCharacterId !== null}>
            <Plus size={14} />
          </button>
        }
      >
        {creatingCharacter && (
          <CharacterForm
            uiLanguage={uiLanguage}
            draft={characterDraft}
            saving={savingCharacterId === "new"}
            onChange={onChangeCharacterDraft}
            onSave={onSaveCharacter}
            onCancel={onCancelEditCharacter}
          />
        )}
        {characters.length ? (
          <ul className="characterList">
            {characters.map((character) => {
              const isEditing = character.id === editingCharacterId;
              const isSaving = character.id === savingCharacterId;
              return (
                <li key={character.id} className={isEditing ? "editingCharacter" : undefined}>
                  {isEditing ? (
                    <CharacterForm uiLanguage={uiLanguage} draft={characterDraft} saving={isSaving} onChange={onChangeCharacterDraft} onSave={onSaveCharacter} onCancel={onCancelEditCharacter} />
                  ) : (
                    <>
                      <span className="avatar">{character.initials}</span>
                      <span className="characterMeta">
                        <b>{character.name}</b>
                        <small>{character.role}</small>
                      </span>
                      <span className={character.present ? "presence here" : "presence off"}>
                        {character.present ? <Circle size={7} /> : <Dot size={14} />}
                        {character.present ? uiText(uiLanguage, "在场", "here") : uiText(uiLanguage, "不在场", "away")}
                      </span>
                      {character.main && <span className="mainCharacterLabel">{uiText(uiLanguage, "主角", "main")}</span>}
                      <button className="plainIcon" aria-label={uiText(uiLanguage, `编辑角色 ${character.name}`, `Edit character ${character.name}`)} onClick={() => onStartEditCharacter(character)} disabled={Boolean(savingCharacterId)}>
                        <PenLine size={14} />
                      </button>
                      <button className={`plainIcon ${confirmDeleteCharacterId === character.id ? "danger" : ""}`} aria-label={confirmDeleteCharacterId === character.id ? uiText(uiLanguage, `确认删除角色 ${character.name}`, `Confirm delete character ${character.name}`) : uiText(uiLanguage, `删除角色 ${character.name}`, `Delete character ${character.name}`)} onClick={() => onDeleteCharacter(character)} disabled={character.main || Boolean(deletingCharacterId) || Boolean(savingCharacterId)}>
                        {deletingCharacterId === character.id ? <RefreshCw size={13} className="spinIcon" /> : <Trash2 size={13} />}
                      </button>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "还没有角色。", "No characters yet.")}</EmptyState>
        )}
      </Panel>
    </div>
  );
}

function CharacterForm({
  uiLanguage,
  draft,
  saving,
  onChange,
  onSave,
  onCancel
}: {
  uiLanguage: UiLanguage;
  draft: CharacterDraft;
  saving: boolean;
  onChange: (draft: CharacterDraft) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="worldEditForm characterEditForm">
      <label>
        <span>{uiText(uiLanguage, "名称", "Name")}</span>
        <input
          value={draft.name}
          onChange={(event) => onChange({ ...draft, name: event.target.value })}
          onKeyDown={(event) => {
            if (event.key === "Enter") onSave();
            if (event.key === "Escape") onCancel();
          }}
          aria-label={uiText(uiLanguage, "角色名称", "Character name")}
          autoFocus
        />
      </label>
      <label>
        <span>{uiText(uiLanguage, "身份", "Role")}</span>
        <textarea
          value={draft.role}
          onChange={(event) => onChange({ ...draft, role: event.target.value })}
          aria-label={uiText(uiLanguage, "角色身份", "Character role")}
          rows={3}
        />
      </label>
      <div className="formActions">
        <button className="cmdButton primary" onClick={onSave} disabled={saving || !draft.name.trim()}>
          {saving ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
          {uiText(uiLanguage, "保存", "Save")}
        </button>
        <button className="cmdButton" onClick={onCancel} disabled={saving}>
          <X size={13} />
          {uiText(uiLanguage, "取消", "Cancel")}
        </button>
      </div>
    </div>
  );
}

function Transcript({
  uiLanguage,
  messages,
  state,
  storyTitle,
  branchName,
  draft,
  setDraft,
  pending,
  error,
  recoveryKind,
  pendingModelLabel,
  interactionMode,
  savingInteractionMode,
  consistencyMode,
  savingConsistencyMode,
  storyPrompt,
  storyPromptDirty,
  savingStoryPrompt,
  storyPromptNotice,
  onChangeStoryPrompt,
  onSaveStoryPrompt,
  onSend,
  onSelectChoice,
  onInteractionModeChange,
  onConsistencyModeChange,
  onStop,
  onResync,
  onContinue,
  onRegenerate,
  onRewrite,
  onConfirmConsistency
}: {
  uiLanguage: UiLanguage;
  messages: Message[];
  state: StoryState;
  storyTitle: string;
  branchName: string;
  draft: string;
  setDraft: (value: string) => void;
  pending: boolean;
  error: string | null;
  recoveryKind: RecoveryKind | null;
  pendingModelLabel: string;
  interactionMode: InteractionMode;
  savingInteractionMode: boolean;
  consistencyMode: ConsistencyMode;
  savingConsistencyMode: boolean;
  storyPrompt: string;
  storyPromptDirty: boolean;
  savingStoryPrompt: boolean;
  storyPromptNotice: string | null;
  onChangeStoryPrompt: (value: string) => void;
  onSaveStoryPrompt: () => void;
  onSend: () => void;
  onSelectChoice: (choice: string) => void;
  onInteractionModeChange: (mode: InteractionMode) => void;
  onConsistencyModeChange: (mode: ConsistencyMode) => void;
  onStop: () => void;
  onResync: () => void;
  onContinue: () => void;
  onRegenerate: (messageId: string) => void;
  onRewrite: (messageId: string) => void;
  onConfirmConsistency: (messageId: string) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const [customChoiceActive, setCustomChoiceActive] = useState(false);
  const [dismissedConsistencyIds, setDismissedConsistencyIds] = useState<Set<string>>(new Set());
  const [promptOpen, setPromptOpen] = useState(false);
  const hasStreamingAssistant = pending && messages[messages.length - 1]?.role === "assistant";
  const lastAssistantIndex = messages.reduce((last, message, index) => message.role === "assistant" ? index : last, -1);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      if (scrollRef.current) {
        scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [messages, pending]);

  return (
    <div className="transcriptShell">
      <div className="sceneRibbon">
        <span className="sceneIdentity">
          <BookOpen size={13} />
          <strong>{storyTitle}</strong>
          <small>{branchName}</small>
        </span>
        <span className="scenePosition">
          <MapPin size={13} />
          <strong>{state.location}</strong>
          <i />
          <span>{state.time}</span>
          <button
            className="plainIcon scenePromptButton"
            type="button"
            aria-label={uiText(uiLanguage, "设置当前小说 Prompt", "Edit story prompt")}
            title={uiText(uiLanguage, "设置当前小说 Prompt", "Edit story prompt")}
            onClick={() => setPromptOpen(true)}
          >
            <Cog size={14} />
          </button>
        </span>
      </div>

      {promptOpen && (
        <div className="promptDialogScrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPromptOpen(false); }}>
          <section className="promptDialog" role="dialog" aria-modal="true" aria-labelledby="story-prompt-title">
            <header>
              <div>
                <h2 id="story-prompt-title">{uiText(uiLanguage, "当前小说 Prompt", "Story prompt")}</h2>
                <p>{uiText(uiLanguage, "只影响这部小说，并会在每轮生成时与全局创作偏好一起使用。", "Applies only to this story and is used with your global writing preferences on every generation.")}</p>
              </div>
              <button className="plainIcon" type="button" aria-label={uiText(uiLanguage, "关闭", "Close")} onClick={() => setPromptOpen(false)}><X size={15} /></button>
            </header>
            <textarea
              rows={10}
              maxLength={12000}
              value={storyPrompt}
              placeholder={uiText(uiLanguage, "例如：采用第三人称限知视角，保持轻悬疑，不提前揭示反派身份。", "Example: Use third-person limited perspective, maintain light suspense, and do not reveal the antagonist early.")}
              onChange={(event) => onChangeStoryPrompt(event.target.value)}
              autoFocus
            />
            <footer>
              {storyPromptNotice && <span role="status">{storyPromptNotice}</span>}
              <button className="cmdButton" type="button" onClick={() => setPromptOpen(false)}>{uiText(uiLanguage, "关闭", "Close")}</button>
              <button className="cmdButton primary" type="button" onClick={onSaveStoryPrompt} disabled={!storyPromptDirty || savingStoryPrompt}>
                {savingStoryPrompt ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
                {uiText(uiLanguage, "保存 Prompt", "Save prompt")}
              </button>
            </footer>
          </section>
        </div>
      )}

      <div ref={scrollRef} className="transcriptScroller">
        <div className="proseStack">
          {messages.length ? (
            messages.map((message, index) => (
              <TranscriptEntry
                uiLanguage={uiLanguage}
                key={message.id ?? `${message.role}-${index}`}
                message={message}
                pending={pending}
                latestAssistant={index === lastAssistantIndex}
                consistencyMode={consistencyMode}
                consistencyDismissed={Boolean(message.id && dismissedConsistencyIds.has(message.id))}
                onContinue={onContinue}
                onRegenerate={onRegenerate}
                onRewrite={onRewrite}
                onConfirmConsistency={onConfirmConsistency}
                onDismissConsistency={(messageId) => setDismissedConsistencyIds((current) => new Set(current).add(messageId))}
                choices={index === lastAssistantIndex ? message.choices ?? [] : []}
                onSelectChoice={(choice) => {
                  setCustomChoiceActive(false);
                  onSelectChoice(choice);
                }}
                onCustomChoice={() => {
                  setCustomChoiceActive(true);
                  composerRef.current?.focus();
                }}
              />
            ))
          ) : (
            <EmptyState>{uiText(uiLanguage, "当前小说还没有消息。", "This story has no messages yet.")}</EmptyState>
          )}
          {pending && !hasStreamingAssistant && (
            <article className="entry assistant">
              <header>
                <span>{pendingModelLabel}</span>
                <small>{uiText(uiLanguage, "正在生成", "Generating")}</small>
              </header>
              <p>
                {uiText(uiLanguage, "正在召回记忆、检查既定事实，并续写这一幕", "Recalling memories, checking canon, and continuing the scene")}
                <span className="cursorPulse" />
              </p>
            </article>
          )}
        </div>
      </div>

      {error && (
        <div className={`inlineNotice ${recoveryKind ?? "api"}`} role="alert">
          <AlertTriangle size={14} />
          <span><b>{recoveryKind === "database" ? uiText(uiLanguage, "数据库", "Database") : recoveryKind === "provider" ? uiText(uiLanguage, "模型服务", "Model provider") : recoveryKind === "stream" ? uiText(uiLanguage, "流连接", "Stream") : recoveryKind === "network" ? uiText(uiLanguage, "网络", "Network") : recoveryKind === "sync" ? uiText(uiLanguage, "同步", "Sync") : recoveryKind === "stopped" ? uiText(uiLanguage, "已停止", "Stopped") : "API"}</b>{error}</span>
          {recoveryKind !== "stopped" && (
            <button className="cmdButton" type="button" onClick={onResync}><RefreshCw size={13} />{uiText(uiLanguage, "重新同步", "Resync")}</button>
          )}
        </div>
      )}

      <div className="composerDock">
        <div className="composerSettingsRow">
          <SelectMenu
            className="consistencyMenu"
            icon={ShieldCheck}
            label={uiText(uiLanguage, "一致性验证", "Consistency check")}
            value={consistencyMode}
            options={[
              { value: "manual", label: uiText(uiLanguage, "开启", "On"), detail: uiText(uiLanguage, "冲突时人工确认", "Confirm conflicts manually"), icon: ShieldCheck },
              { value: "auto", label: "Auto", detail: uiText(uiLanguage, "冲突时自动重写", "Rewrite conflicts automatically"), icon: Sparkles },
              { value: "off", label: uiText(uiLanguage, "关闭", "Off"), detail: uiText(uiLanguage, "不执行检查", "Skip consistency checks"), icon: CircleDashed }
            ]}
            onChange={(value) => onConsistencyModeChange(value as ConsistencyMode)}
            disabled={savingConsistencyMode}
          />
          <div className="interactionModeToggle" role="group" aria-label={uiText(uiLanguage, "正文推进方式", "Story interaction mode")} aria-busy={savingInteractionMode}>
            <button type="button" className={interactionMode === "choices" ? "active" : undefined} aria-pressed={interactionMode === "choices"} onClick={() => onInteractionModeChange("choices")} disabled={savingInteractionMode}>
              <ListChecks size={13} />{uiText(uiLanguage, "选择式", "Choices")}
            </button>
            <button type="button" className={interactionMode === "open" ? "active" : undefined} aria-pressed={interactionMode === "open"} onClick={() => onInteractionModeChange("open")} disabled={savingInteractionMode}>
              <PenLine size={13} />{uiText(uiLanguage, "开放式", "Open")}
            </button>
          </div>
        </div>
        {customChoiceActive && (
          <div className="customChoiceHint" role="status">
            <PenLine size={13} />{uiText(uiLanguage, "请在下方输入你自己的推进方式，然后点击发送。", "Enter your own direction below, then send it.")}
            <button type="button" aria-label={uiText(uiLanguage, "关闭自定义输入提示", "Close custom input hint")} onClick={() => setCustomChoiceActive(false)}><X size={13} /></button>
          </div>
        )}
        <div className="composerBox">
          <textarea
            ref={composerRef}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            placeholder={customChoiceActive ? uiText(uiLanguage, "输入你自己的推进方式…", "Enter your own direction...") : uiText(uiLanguage, "引导下一幕…", "Direct the scene...")}
            rows={1}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) onSend();
            }}
          />
          <button className={pending ? "stopButton" : "sendButton"} onClick={pending ? onStop : onSend} disabled={!pending && !draft.trim()} aria-label={pending ? uiText(uiLanguage, "停止生成", "Stop generating") : uiText(uiLanguage, "发送", "Send")} title={pending ? uiText(uiLanguage, "停止生成", "Stop generating") : uiText(uiLanguage, "发送", "Send")}>
            {pending ? <Square size={13} /> : <Send size={13} />}
            <span>{pending ? uiText(uiLanguage, "生成中", "Generating") : uiText(uiLanguage, "发送", "Send")}</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function TranscriptEntry({
  uiLanguage,
  message,
  pending,
  latestAssistant,
  consistencyMode,
  consistencyDismissed,
  onContinue,
  onRegenerate,
  onRewrite,
  onConfirmConsistency,
  onDismissConsistency,
  choices,
  onSelectChoice,
  onCustomChoice
}: {
  uiLanguage: UiLanguage;
  message: Message;
  pending: boolean;
  latestAssistant: boolean;
  consistencyMode: ConsistencyMode;
  consistencyDismissed: boolean;
  onContinue: () => void;
  onRegenerate: (messageId: string) => void;
  onRewrite: (messageId: string) => void;
  onConfirmConsistency: (messageId: string) => void;
  onDismissConsistency: (messageId: string) => void;
  choices: string[];
  onSelectChoice: (choice: string) => void;
  onCustomChoice: () => void;
}) {
  if (message.role === "beat") {
    return (
      <div className="beatEntry" role="separator">
        <span />
        <b>{message.content}</b>
        <span />
      </div>
    );
  }

  const isUser = message.role === "user";
  const author = message.author === "你"
    ? uiText(uiLanguage, "你", "You")
    : message.author === "叙事引擎"
      ? uiText(uiLanguage, "叙事引擎", "Narrative engine")
      : message.author ?? (isUser ? uiText(uiLanguage, "你", "You") : uiText(uiLanguage, "叙事引擎", "Narrative engine"));
  return (
    <article className={`entry ${isUser ? "user" : "assistant"}`}>
      <header>
        <span>{author}</span>
        {message.time && <small>· {message.time}</small>}
      </header>
      <MessageContent content={message.content} />
      {!isUser && choices.length > 0 && (
        <div className="storyChoices" aria-label={uiText(uiLanguage, "剧情推进选项", "Story choices")}>
          {choices.map((choice) => (
            <button type="button" key={choice} onClick={() => onSelectChoice(choice)} disabled={pending}>{choice}</button>
          ))}
          <button type="button" className="customOption" onClick={onCustomChoice} disabled={pending}><PenLine size={13} />{uiText(uiLanguage, "自定义", "Custom")}</button>
        </div>
      )}
      {!isUser && message.id && latestAssistant && consistencyMode !== "off" && message.consistencyCheck?.status === "fail" && !consistencyDismissed && (
        <div className="consistencyReview" role="alert">
          <AlertTriangle size={14} />
          <span>
            <b>{uiText(uiLanguage, `发现 ${message.consistencyCheck.issue_count} 项一致性冲突`, `${message.consistencyCheck.issue_count} consistency conflicts found`)}</b>
            <small>{uiText(uiLanguage, "可确认由 AI 修订，或保留当前版本。", "Let AI revise the conflicts or keep this version.")}</small>
          </span>
          <button className="cmdButton primary" type="button" onClick={() => onConfirmConsistency(message.id!)} disabled={pending}><RefreshCw size={12} />{uiText(uiLanguage, "确认重写", "Revise")}</button>
          <button className="cmdButton" type="button" onClick={() => onDismissConsistency(message.id!)} disabled={pending}>{uiText(uiLanguage, "保留当前版本", "Keep version")}</button>
        </div>
      )}
      {!isUser && message.id && latestAssistant && (
        <div className="rowActions">
          <CommandButton icon={ArrowRight} label={uiText(uiLanguage, "继续", "Continue")} primary onClick={onContinue} disabled={pending} />
          <CommandButton icon={RefreshCw} label={uiText(uiLanguage, "重新生成", "Regenerate")} compact onClick={() => onRegenerate(message.id!)} disabled={pending} />
          <CommandButton icon={PenLine} label={uiText(uiLanguage, "重写", "Rewrite")} compact onClick={() => onRewrite(message.id!)} disabled={pending} />
        </div>
      )}
    </article>
  );
}

function MessageContent({ content }: { content: string }) {
  return (
    <div className="messageBody">
      <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
    </div>
  );
}

function RightInspector({
  uiLanguage,
  state,
  branches,
  activeBranchId,
  creatingBranch,
  switchingBranchId,
  editingBranchId,
  branchNameDraft,
  savingBranchId,
  duplicatingBranchId,
  confirmDeleteBranchId,
  deletingBranchId,
  memoryItems,
  canonFactItems,
  summaries,
  summarizing,
  exportingFormat,
  lastRun,
  activeModel,
  selectedPurpose,
  relationships,
  editingMemoryId,
  memoryDraft,
  savingMemoryId,
  editingCanonFactId,
  canonFactDraft,
  savingCanonFactId,
  onCreateBranch,
  onSwitchBranch,
  onStartEditBranch,
  onCancelEditBranch,
  onChangeBranchName,
  onSaveBranch,
  onDuplicateBranch,
  onDeleteBranch,
  onGenerateSummary,
  onExportStory,
  onStartEditMemory,
  onCancelEditMemory,
  onChangeMemoryDraft,
  onSaveMemory,
  onStartEditCanonFact,
  onCancelEditCanonFact,
  onChangeCanonFactDraft,
  onSaveCanonFact
}: {
  uiLanguage: UiLanguage;
  state: StoryState;
  branches: BranchSummary[];
  activeBranchId: string;
  creatingBranch: boolean;
  switchingBranchId: string | null;
  editingBranchId: string | null;
  branchNameDraft: string;
  savingBranchId: string | null;
  duplicatingBranchId: string | null;
  confirmDeleteBranchId: string | null;
  deletingBranchId: string | null;
  memoryItems: MemoryItemSummary[];
  canonFactItems: CanonFactSummary[];
  summaries: SessionSummary[];
  summarizing: boolean;
  exportingFormat: "markdown" | "json" | null;
  lastRun: ChatResponse["model_call"];
  activeModel: ModelOption | null;
  selectedPurpose: StoryPurpose;
  relationships: RelationshipSummary[];
  editingMemoryId: string | null;
  memoryDraft: KnowledgeDraft;
  savingMemoryId: string | null;
  editingCanonFactId: string | null;
  canonFactDraft: KnowledgeDraft;
  savingCanonFactId: string | null;
  onCreateBranch: () => void;
  onSwitchBranch: (branchId: string) => void;
  onStartEditBranch: (branch: BranchSummary) => void;
  onCancelEditBranch: () => void;
  onChangeBranchName: (name: string) => void;
  onSaveBranch: () => void;
  onDuplicateBranch: (branch: BranchSummary) => void;
  onDeleteBranch: (branch: BranchSummary) => void;
  onGenerateSummary: () => void;
  onExportStory: (format: "markdown" | "json") => void;
  onStartEditMemory: (memory: MemoryItemSummary) => void;
  onCancelEditMemory: () => void;
  onChangeMemoryDraft: (draft: KnowledgeDraft) => void;
  onSaveMemory: () => void;
  onStartEditCanonFact: (fact: CanonFactSummary) => void;
  onCancelEditCanonFact: () => void;
  onChangeCanonFactDraft: (draft: KnowledgeDraft) => void;
  onSaveCanonFact: () => void;
}) {
  const modelName = lastRun.model || activeModel?.model || uiText(uiLanguage, "未调用", "Not called");
  const providerName = lastRun.provider || activeModel?.provider || "deepinfra";
  const purposeKey = lastRun.purpose ?? selectedPurpose;
  const purposeName = uiLanguage === "zh-CN" ? purposeRoutesZh[purposeKey].label : purposeLabels[purposeKey] ?? "Prose generation";
  const [visibleCounts, setVisibleCounts] = useState<Partial<Record<InspectorCollection, number>>>({});

  useEffect(() => setVisibleCounts({}), [activeBranchId]);

  function visibleItems<T>(key: InspectorCollection, items: T[]): T[] {
    return items.slice(0, visibleCounts[key] ?? 3);
  }

  function showMore(key: InspectorCollection, total: number) {
    setVisibleCounts((current) => ({
      ...current,
      [key]: Math.min(total, (current[key] ?? 3) + 3)
    }));
  }

  function collapse(key: InspectorCollection) {
    setVisibleCounts((current) => ({ ...current, [key]: 3 }));
  }

  return (
    <div className="railScroll">
      <Panel title={uiText(uiLanguage, "当前场景", "Current scene")} icon={MapPin}>
        <div className="stateGrid">
          <Stat label={uiText(uiLanguage, "地点", "Location")} value={state.location} icon={MapPin} />
          <Stat label={uiText(uiLanguage, "时间", "Time")} value={state.time} icon={Clock} />
          <Stat label={uiText(uiLanguage, "目标", "Objective")} value={state.objective} icon={Target} accent="teal" />
          <Stat label={uiText(uiLanguage, "氛围", "Mood")} value={state.mood} icon={Waves} accent="amber" />
        </div>
      </Panel>

      <Panel
        title={uiText(uiLanguage, "分支", "Branches")}
        icon={GitBranch}
        count={branches.length}
        action={
          <button className="plainIcon" aria-label={uiText(uiLanguage, "创建分支", "Create branch")} onClick={onCreateBranch} disabled={creatingBranch}>
            {creatingBranch ? <RefreshCw size={15} className="spinIcon" /> : <Plus size={15} />}
          </button>
        }
      >
        {branches.length ? (
          <ul className="branchList">
            {visibleItems("branches", branches).map((branch) => {
              const active = branch.id === activeBranchId || branch.active;
              const switching = branch.id === switchingBranchId;
              const editing = branch.id === editingBranchId;
              const saving = branch.id === savingBranchId;
              const duplicating = branch.id === duplicatingBranchId;
              const deleting = branch.id === deletingBranchId;
              const confirmingDelete = branch.id === confirmDeleteBranchId;
              const branchBusy = Boolean(switchingBranchId || savingBranchId || duplicatingBranchId || deletingBranchId || creatingBranch);
              return (
                <li key={branch.id} className={active ? "active" : undefined}>
                  {editing ? (
                    <div className="branchEdit">
                      <input
                        aria-label={uiText(uiLanguage, "分支名称", "Branch name")}
                        value={branchNameDraft}
                        maxLength={120}
                        autoFocus
                        onChange={(event) => onChangeBranchName(event.target.value)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") onSaveBranch();
                          if (event.key === "Escape") onCancelEditBranch();
                        }}
                        disabled={saving}
                      />
                      <div className="branchActions">
                        <button className="plainIcon" type="button" title={uiText(uiLanguage, "保存分支名称", "Save branch name")} aria-label={uiText(uiLanguage, "保存分支名称", "Save branch name")} onClick={onSaveBranch} disabled={!branchNameDraft.trim() || saving}>
                          {saving ? <RefreshCw size={14} className="spinIcon" /> : <Check size={14} />}
                        </button>
                        <button className="plainIcon" type="button" title={uiText(uiLanguage, "取消重命名", "Cancel rename")} aria-label={uiText(uiLanguage, "取消重命名", "Cancel rename")} onClick={onCancelEditBranch} disabled={saving}>
                          <X size={14} />
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="branchRow">
                      <button
                        className="branchSelect"
                        type="button"
                        data-testid={`branch-${branch.id}`}
                        onClick={() => onSwitchBranch(branch.id)}
                        disabled={active || branchBusy}
                      >
                        <span>
                          <b>{branch.name}</b>
                          <small>{formatStoryUpdated(branch.created_at, uiLanguage)}</small>
                        </span>
                        <Pill tone={active ? "teal" : "neutral"}>{switching ? uiText(uiLanguage, "切换中", "switching") : active ? uiText(uiLanguage, "当前", "active") : uiText(uiLanguage, "切换", "switch")}</Pill>
                      </button>
                      <div className="branchActions">
                        <button className="plainIcon" type="button" title={uiText(uiLanguage, "重命名分支", "Rename branch")} aria-label={uiText(uiLanguage, `重命名 ${branch.name}`, `Rename ${branch.name}`)} onClick={() => onStartEditBranch(branch)} disabled={branchBusy}>
                          <PenLine size={14} />
                        </button>
                        <button className="plainIcon" type="button" title={uiText(uiLanguage, "复制分支", "Duplicate branch")} aria-label={uiText(uiLanguage, `复制 ${branch.name}`, `Duplicate ${branch.name}`)} onClick={() => onDuplicateBranch(branch)} disabled={branchBusy}>
                          {duplicating ? <RefreshCw size={14} className="spinIcon" /> : <Copy size={14} />}
                        </button>
                        <button
                          className={`plainIcon branchDelete${confirmingDelete ? " isConfirming" : ""}`}
                          type="button"
                          title={confirmingDelete ? uiText(uiLanguage, "再次点击确认删除", "Click again to delete") : uiText(uiLanguage, "删除分支", "Delete branch")}
                          aria-label={confirmingDelete ? uiText(uiLanguage, `确认删除 ${branch.name}`, `Confirm delete ${branch.name}`) : uiText(uiLanguage, `删除 ${branch.name}`, `Delete ${branch.name}`)}
                          onClick={() => onDeleteBranch(branch)}
                          disabled={branchBusy || branches.length <= 1}
                        >
                          {deleting ? <RefreshCw size={14} className="spinIcon" /> : confirmingDelete ? <AlertTriangle size={14} /> : <Trash2 size={14} />}
                        </button>
                      </div>
                    </div>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "还没有分支。", "No branches yet.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="branches" total={branches.length} visible={visibleCounts.branches ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "人物关系", "Relationships")} icon={HeartHandshake} count={relationships.length}>
        {relationships.length ? (
          <ul className="relationList">
            {visibleItems("relationships", relationships).map((relationship) => (
              <li key={`${relationship.from}-${relationship.to}`}>
                <div>
                  <span>{relationship.from} → {relationship.to}</span>
                  <Pill tone={relationship.value < 0 ? "danger" : "teal"}>{relationship.bond}</Pill>
                </div>
                <Meter value={relationship.value} tone={relationship.value < 0 ? "amber" : "teal"} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "还没有关系记录。", "No relationships yet.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="relationships" total={relationships.length} visible={visibleCounts.relationships ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "物品", "Inventory")} icon={Backpack} count={state.inventory.length}>
        {state.inventory.length ? (
          <ul className="simpleList">
            {visibleItems("inventory", state.inventory).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "当前没有物品。", "No items in the current state.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="inventory" total={state.inventory.length} visible={visibleCounts.inventory ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "开放线索", "Open plot threads")} icon={GitFork} count={state.open_threads.length}>
        {state.open_threads.length ? (
          <ul className="threadList">
            {visibleItems("threads", state.open_threads).map((thread) => (
              <li key={thread}>
                <div>
                  <span>{thread}</span>
                  <Pill tone="teal">{uiText(uiLanguage, "开放", "open")}</Pill>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "当前没有开放线索。", "No open plot threads.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="threads" total={state.open_threads.length} visible={visibleCounts.threads ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel
        title={uiText(uiLanguage, "会话摘要", "Session summaries")}
        icon={ClipboardList}
        count={summaries.length}
        action={
          <button className="plainIcon" aria-label={uiText(uiLanguage, "生成会话摘要", "Generate session summary")} onClick={onGenerateSummary} disabled={summarizing}>
            {summarizing ? <RefreshCw size={15} className="spinIcon" /> : <Plus size={15} />}
          </button>
        }
      >
        {summaries.length ? (
          <ul className="summaryCards">
            {visibleItems("summaries", summaries).map((summary) => (
              <li key={summary.id}>
                <h4>{summary.title}</h4>
                <p>{summary.content}</p>
                <div>
                  <Pill tone="amber">{summary.message_count} {uiText(uiLanguage, "轮", summary.message_count === 1 ? "turn" : "turns")}</Pill>
                  <Pill tone="graphite">{formatStoryUpdated(summary.created_at, uiLanguage)}</Pill>
                </div>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "当前分支还没有会话摘要。", "No session summaries for this branch.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="summaries" total={summaries.length} visible={visibleCounts.summaries ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "导出小说", "Export story")} icon={BookText}>
        <div className="exportActions">
          <button className="cmdButton primary" onClick={() => onExportStory("markdown")} disabled={Boolean(exportingFormat)}>
            {exportingFormat === "markdown" ? <RefreshCw size={13} className="spinIcon" /> : <BookText size={13} />}
            Markdown
          </button>
          <button className="cmdButton" onClick={() => onExportStory("json")} disabled={Boolean(exportingFormat)}>
            {exportingFormat === "json" ? <RefreshCw size={13} className="spinIcon" /> : <Braces size={13} />}
            JSON
          </button>
        </div>
      </Panel>

      <Panel title={uiText(uiLanguage, "既定事实", "Canon facts")} icon={Lock} count={canonFactItems.length}>
        {canonFactItems.length ? (
          <ul className="factList">
            {visibleItems("canon", canonFactItems).map((fact, index) => {
              const isEditing = fact.id === editingCanonFactId;
              const isSaving = fact.id === savingCanonFactId;
              return (
                <li key={fact.id || fact.content} className={isEditing ? "editingKnowledge" : undefined}>
                  {isEditing ? (
                    <KnowledgeEditForm
                      uiLanguage={uiLanguage}
                      type="canon"
                      draft={canonFactDraft}
                      saving={isSaving}
                      onChange={onChangeCanonFactDraft}
                      onSave={onSaveCanonFact}
                      onCancel={onCancelEditCanonFact}
                    />
                  ) : (
                    <>
                      <Lock size={13} />
                      <span>{fact.content}</span>
                      <span className="knowledgeActions">
                        <Pill tone="graphite">{uiText(uiLanguage, "事实", "canon")} {fact.importance}</Pill>
                        {fact.id && (
                          <button
                            className="plainIcon"
                            data-testid={`edit-canon-${fact.id}`}
                            aria-label={uiText(uiLanguage, `编辑既定事实 ${index + 1}`, `Edit canon fact ${index + 1}`)}
                            onClick={() => onStartEditCanonFact(fact)}
                            disabled={Boolean(savingCanonFactId)}
                          >
                            <PenLine size={14} />
                          </button>
                        )}
                      </span>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "还没有既定事实。", "No canon facts yet.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="canon" total={canonFactItems.length} visible={visibleCounts.canon ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "召回记忆", "Recalled memories")} icon={Brain} count={memoryItems.length}>
        {memoryItems.length ? (
          <ul className="memoryList">
            {visibleItems("memories", memoryItems).map((memory, index) => {
              const isEditing = memory.id === editingMemoryId;
              const isSaving = memory.id === savingMemoryId;
              return (
                <li key={memory.id || memory.content} className={isEditing ? "editingKnowledge" : undefined}>
                  {isEditing ? (
                    <KnowledgeEditForm
                      uiLanguage={uiLanguage}
                      type="memory"
                      draft={memoryDraft}
                      saving={isSaving}
                      onChange={onChangeMemoryDraft}
                      onSave={onSaveMemory}
                      onCancel={onCancelEditMemory}
                    />
                  ) : (
                    <>
                      <p>{memory.content}</p>
                      <div>
                        <Pill tone="teal">{uiText(uiLanguage, "记忆", "memory")} {memory.importance}</Pill>
                        {memory.id && (
                          <button
                            className="plainIcon"
                            data-testid={`edit-memory-${memory.id}`}
                            aria-label={uiText(uiLanguage, `编辑记忆 ${index + 1}`, `Edit memory ${index + 1}`)}
                            onClick={() => onStartEditMemory(memory)}
                            disabled={Boolean(savingMemoryId)}
                          >
                            <PenLine size={14} />
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </li>
              );
            })}
          </ul>
        ) : (
          <EmptyState>{uiText(uiLanguage, "本轮没有召回记忆。", "No memories recalled this turn.")}</EmptyState>
        )}
        <ProgressiveControls uiLanguage={uiLanguage} collection="memories" total={memoryItems.length} visible={visibleCounts.memories ?? 3} onMore={showMore} onCollapse={collapse} />
      </Panel>

      <Panel title={uiText(uiLanguage, "最近模型调用", "Last model call")} icon={Cpu}>
        <div className="callHeader">
          <span><Cpu size={13} /> {modelName}</span>
          <Pill tone={providerName === "openai" ? "amber" : "teal"}>{providerName}</Pill>
        </div>
        <dl className="telemetryGrid">
          <Telemetry label={uiText(uiLanguage, "延迟", "Latency")} value={lastRun.latency_ms ? `${(lastRun.latency_ms / 1000).toFixed(2)}s` : "-"} icon={Gauge} />
          <Telemetry label={uiText(uiLanguage, "温度", "Temperature")} value={activeModel?.temperature.toFixed(2) ?? "-"} />
          <Telemetry label={uiText(uiLanguage, "输入 tokens", "Input tokens")} value={lastRun.input_tokens?.toLocaleString() ?? "?"} />
          <Telemetry label={uiText(uiLanguage, "输出 tokens", "Output tokens")} value={lastRun.output_tokens?.toLocaleString() ?? "?"} />
          <Telemetry label={uiText(uiLanguage, "估算成本", "Est. cost")} value={lastRun.cost_estimate != null ? `$${lastRun.cost_estimate.toFixed(6)}` : "-"} />
        </dl>
        <p className="helperText">{uiText(uiLanguage, "用途：", "Purpose: ")}{purposeName}</p>
        <p className="helperText">{uiText(uiLanguage, "状态：", "Status: ")}{lastRun.dry_run ? uiText(uiLanguage, "模拟调用", "dry run") : uiText(uiLanguage, "真实服务调用", "live provider call")}</p>
      </Panel>
    </div>
  );
}

function KnowledgeEditForm({
  uiLanguage,
  type,
  draft,
  saving,
  onChange,
  onSave,
  onCancel
}: {
  uiLanguage: UiLanguage;
  type: "memory" | "canon";
  draft: KnowledgeDraft;
  saving: boolean;
  onChange: (draft: KnowledgeDraft) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const label = type === "memory" ? uiText(uiLanguage, "记忆", "Memory") : uiText(uiLanguage, "既定事实", "Canon fact");

  return (
    <div className="worldEditForm knowledgeEditForm">
      <label>
        <span>{label}</span>
        <textarea
          value={draft.content}
          onChange={(event) => onChange({ ...draft, content: event.target.value })}
          aria-label={`${label} content`}
          rows={4}
          autoFocus
        />
      </label>
      <label>
        <span>{uiText(uiLanguage, "重要度", "Importance")}</span>
        <input
          type="number"
          min={1}
          max={10}
          value={draft.importance}
          onChange={(event) => onChange({ ...draft, importance: Number(event.target.value) })}
          aria-label={`${label} ${uiText(uiLanguage, "重要度", "importance")}`}
        />
      </label>
      <div className="formActions">
        <button className="cmdButton primary" onClick={onSave} disabled={saving || !draft.content.trim()}>
          {saving ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
          {uiText(uiLanguage, "保存", "Save")}
        </button>
        <button className="cmdButton" onClick={onCancel} disabled={saving}>
          <X size={13} />
          {uiText(uiLanguage, "取消", "Cancel")}
        </button>
      </div>
    </div>
  );
}

function QuotaMeter({ quota, uiLanguage, compact = false }: { quota: QuotaUsage | null; uiLanguage: UiLanguage; compact?: boolean }) {
  if (!quota) {
    return <div className={`quotaMeter ${compact ? "compact" : ""} loading`}><span>{uiText(uiLanguage, "额度读取中", "Loading quota")}</span></div>;
  }
  const resetLabel = new Intl.DateTimeFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", {
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit"
  }).format(new Date(quota.resets_at));
  const percent = quota.unlimited ? 0 : Math.min(100, quota.percentage_used);
  const number = new Intl.NumberFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", { notation: compact ? "compact" : "standard", maximumFractionDigits: 1 });
  return (
    <div className={`quotaMeter ${compact ? "compact" : ""} ${quota.soft_limit_reached ? "warning" : ""}`} title={`${uiText(uiLanguage, "重置时间", "Resets")} ${resetLabel}`}>
      <div className="quotaMeterLabel">
        <span>{quota.unlimited ? uiText(uiLanguage, "管理员不限额", "Admin unlimited") : `${quota.percentage_used.toFixed(1)}%`}</span>
        {!compact && <small>{uiText(uiLanguage, "重置", "Resets")} {resetLabel}</small>}
      </div>
      {!quota.unlimited && <div className="quotaTrack" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}><span style={{ width: `${percent}%` }} /></div>}
      {!compact && quota.soft_limit_reached && !quota.unlimited && (
        <p className="quotaWarning">{uiText(uiLanguage, `已达到 ${quota.soft_limit_percentage}% 提醒线，请留意剩余额度。`, `${quota.soft_limit_percentage}% warning threshold reached. Monitor the remaining allowance.`)}</p>
      )}
      {!compact && (
        <div className="quotaNumbers">
          <span><b>{number.format(quota.used_tokens)}</b><small>{uiText(uiLanguage, "已用 tokens", "tokens used")}</small></span>
          <span><b>{quota.limit_tokens === null ? "∞" : number.format(quota.limit_tokens)}</b><small>{uiText(uiLanguage, "周额度", "weekly limit")}</small></span>
          <span><b>{quota.remaining_tokens === null ? "∞" : number.format(quota.remaining_tokens)}</b><small>{uiText(uiLanguage, "剩余", "remaining")}</small></span>
        </div>
      )}
    </div>
  );
}

function SettingsView({
  uiLanguage,
  onUiLanguageChange,
  authUser,
  quota,
  authSessions,
  loadingAuthSessions,
  revokingSessionId,
  confirmRevokeSessionId,
  sessionError,
  exportingAccount,
  deletingAccount,
  accountActionError,
  models,
  providers,
  selectedPurpose,
  routeModels,
  routeDirty,
  savingRoutes,
  routeNotice,
  routeError,
  checkingModelId,
  modelHealthNotice,
  modelHealthError,
  userPreferences,
  preferenceDirty,
  savingPreferences,
  preferenceNotice,
  preferenceError,
  onSelectPurpose,
  onSelectRouteModel,
  onRestoreSavedRoutes,
  onUseDefaultRoutes,
  onTestModel,
  onChangePreference,
  onSavePreferences,
  onRevokeSession,
  onCancelRevokeSession,
  onExportAccount,
  onDeleteAccount
}: {
  uiLanguage: UiLanguage;
  onUiLanguageChange: (language: UiLanguage) => void;
  authUser: AuthUser;
  quota: QuotaUsage | null;
  authSessions: AuthSessionSummary[];
  loadingAuthSessions: boolean;
  revokingSessionId: string | null;
  confirmRevokeSessionId: string | null;
  sessionError: string | null;
  exportingAccount: boolean;
  deletingAccount: boolean;
  accountActionError: string | null;
  models: ModelOption[];
  providers: ProvidersResponse | null;
  selectedPurpose: StoryPurpose;
  routeModels: Partial<Record<StoryPurpose, string>>;
  routeDirty: boolean;
  savingRoutes: boolean;
  routeNotice: string | null;
  routeError: string | null;
  checkingModelId: string | null;
  modelHealthNotice: string | null;
  modelHealthError: string | null;
  userPreferences: UserPreference[];
  preferenceDirty: boolean;
  savingPreferences: boolean;
  preferenceNotice: string | null;
  preferenceError: string | null;
  onSelectPurpose: (purpose: StoryPurpose) => void;
  onSelectRouteModel: (purpose: StoryPurpose, model: string) => void;
  onRestoreSavedRoutes: () => void;
  onUseDefaultRoutes: () => void;
  onTestModel: (model: ModelOption) => void;
  onChangePreference: (preferenceType: string, content: string) => void;
  onSavePreferences: () => void;
  onRevokeSession: (authSession: AuthSessionSummary) => void;
  onCancelRevokeSession: () => void;
  onExportAccount: () => void;
  onDeleteAccount: (password: string, confirmation: string) => void;
}) {
  const [showDeleteAccount, setShowDeleteAccount] = useState(false);
  const [deletePassword, setDeletePassword] = useState("");
  const [deleteConfirmation, setDeleteConfirmation] = useState("");
  const deleteReady = deletePassword.length > 0 && deleteConfirmation === "DELETE";

  return (
    <section className="settingsPage">
      <div className="settingsInner">
        <header>
          <h1>{uiText(uiLanguage, "设置", "Settings")}</h1>
          <p>{uiText(uiLanguage, "管理界面语言、账号安全、创作偏好与模型路由。", "Manage interface language, account security, writing preferences, and model routing.")}</p>
        </header>

        <Panel title={uiText(uiLanguage, "界面语言", "Interface language")} icon={Globe2}>
          <p className="languageDescription">
            {uiText(uiLanguage, "只更改按钮、标签和帮助文字，不会翻译或改写小说正文。", "Changes buttons, labels, and help text only. Your story prose is never translated or rewritten.")}
          </p>
          <div className="languageToggle" role="radiogroup" aria-label={uiText(uiLanguage, "界面语言", "Interface language")}>
            <button type="button" role="radio" aria-checked={uiLanguage === "zh-CN"} className={uiLanguage === "zh-CN" ? "active" : undefined} onClick={() => onUiLanguageChange("zh-CN")}>简体中文</button>
            <button type="button" role="radio" aria-checked={uiLanguage === "en"} className={uiLanguage === "en" ? "active" : undefined} onClick={() => onUiLanguageChange("en")}>English</button>
          </div>
        </Panel>

        <Panel title={uiText(uiLanguage, "账号会话", "Account sessions")} icon={ShieldCheck} count={authSessions.length}>
          <div className="accountIdentity">
            <span><UserRound size={15} /></span>
            <span>
              <b>{authUser.display_name}</b>
              <small>{authUser.email}</small>
            </span>
          </div>

          {sessionError && <div className="authError" role="alert">{sessionError}</div>}
          {loadingAuthSessions ? (
            <div className="sessionLoading"><RefreshCw size={14} className="spinIcon" /> {uiText(uiLanguage, "正在读取会话", "Loading sessions")}</div>
          ) : authSessions.length ? (
            <ul className="sessionList">
              {authSessions.map((authSession) => {
                const confirming = confirmRevokeSessionId === authSession.id;
                const revoking = revokingSessionId === authSession.id;
                return (
                  <li key={authSession.id}>
                    <MonitorSmartphone size={15} />
                    <span>
                      <b>{authSession.device_name || (authSession.current ? uiText(uiLanguage, "当前设备", "Current device") : uiText(uiLanguage, "旧版未知设备", "Legacy unknown device"))}</b>
                      <small>{authSession.current ? `${uiText(uiLanguage, "当前会话", "Current session")} · ` : ""}{authSession.ip_address || uiText(uiLanguage, "IP 未记录", "IP not recorded")} · {authSession.ip_region || uiText(uiLanguage, "地区未知", "Region unknown")}</small>
                      <small>{uiText(uiLanguage, "登录", "Signed in")} {formatStoryUpdated(authSession.created_at, uiLanguage)} · {uiText(uiLanguage, "到期", "Expires")} {formatStoryUpdated(authSession.expires_at, uiLanguage)}</small>
                    </span>
                    {confirming ? (
                      <span className="sessionActions">
                        <button className="plainIcon dangerAction" type="button" aria-label={authSession.current ? uiText(uiLanguage, "确认退出当前会话", "Confirm sign out on this device") : uiText(uiLanguage, "确认撤销会话", "Confirm session revocation")} title={uiText(uiLanguage, "再次点击确认", "Click again to confirm")} onClick={() => onRevokeSession(authSession)} disabled={revoking}>
                          {revoking ? <RefreshCw size={14} className="spinIcon" /> : <AlertTriangle size={14} />}
                        </button>
                        <button className="plainIcon" type="button" aria-label={uiText(uiLanguage, "取消撤销会话", "Cancel session revocation")} onClick={onCancelRevokeSession} disabled={revoking}>
                          <X size={14} />
                        </button>
                      </span>
                    ) : (
                      <button className="plainIcon" type="button" aria-label={authSession.current ? uiText(uiLanguage, "退出当前会话", "Sign out this session") : uiText(uiLanguage, "撤销会话", "Revoke session")} title={authSession.current ? uiText(uiLanguage, "退出当前会话", "Sign out this session") : uiText(uiLanguage, "撤销会话", "Revoke session")} onClick={() => onRevokeSession(authSession)} disabled={Boolean(revokingSessionId)}>
                        <LogOut size={14} />
                      </button>
                    )}
                  </li>
                );
              })}
            </ul>
          ) : (
            <EmptyState>{uiText(uiLanguage, "没有可用的登录会话。", "No active sign-in sessions.")}</EmptyState>
          )}
        </Panel>

        <Panel title={uiText(uiLanguage, "本周 AI 额度", "Weekly AI quota")} icon={Gauge}>
          <QuotaMeter quota={quota} uiLanguage={uiLanguage} />
        </Panel>

        <Panel title={uiText(uiLanguage, "数据与账户", "Data and account")} icon={Download}>
          <div className="accountDataRow">
            <span>
              <b>{uiText(uiLanguage, "导出全部数据", "Export all data")}</b>
              <small>{uiText(uiLanguage, "下载账号、故事、消息、世界观、记忆、偏好与脱敏模型调用元数据。", "Download your profile, stories, messages, worlds, memories, preferences, and sanitized model-call metadata.")}</small>
            </span>
            <button className="cmdButton" type="button" onClick={onExportAccount} disabled={exportingAccount || deletingAccount}>
              {exportingAccount ? <RefreshCw size={13} className="spinIcon" /> : <Download size={13} />}
              {uiText(uiLanguage, "导出 JSON", "Export JSON")}
            </button>
          </div>

          <div className="accountDangerZone">
            <span>
              <b>{uiText(uiLanguage, "永久删除账户", "Permanently delete account")}</b>
              <small>{uiText(uiLanguage, "删除账号、故事、消息、世界观、角色、记忆、偏好、会话与模型调用记录。此操作无法撤销。", "Deletes your account, stories, messages, worlds, characters, memories, preferences, sessions, and model-call records. This cannot be undone.")}</small>
            </span>
            {!showDeleteAccount ? (
              <button className="cmdButton dangerAction" type="button" onClick={() => setShowDeleteAccount(true)} disabled={exportingAccount}>
                <Trash2 size={13} /> {uiText(uiLanguage, "删除账户", "Delete account")}
              </button>
            ) : (
              <div className="accountDeleteForm">
                <label>
                  <span>{uiText(uiLanguage, "当前密码", "Current password")}</span>
                  <input type="password" autoComplete="current-password" maxLength={128} value={deletePassword} onChange={(event) => setDeletePassword(event.target.value)} disabled={deletingAccount} />
                </label>
                <label>
                  <span>{uiText(uiLanguage, "输入 DELETE 确认", "Type DELETE to confirm")}</span>
                  <input type="text" autoComplete="off" value={deleteConfirmation} onChange={(event) => setDeleteConfirmation(event.target.value)} disabled={deletingAccount} />
                </label>
                <div className="routingActions">
                  <button className="cmdButton dangerAction" type="button" disabled={!deleteReady || deletingAccount} onClick={() => onDeleteAccount(deletePassword, deleteConfirmation)}>
                    {deletingAccount ? <RefreshCw size={13} className="spinIcon" /> : <Trash2 size={13} />}
                    {uiText(uiLanguage, "永久删除", "Delete permanently")}
                  </button>
                  <button className="cmdButton" type="button" disabled={deletingAccount} onClick={() => { setShowDeleteAccount(false); setDeletePassword(""); setDeleteConfirmation(""); }}>
                    <X size={13} /> {uiText(uiLanguage, "取消", "Cancel")}
                  </button>
                </div>
              </div>
            )}
          </div>
          {accountActionError && <div className="authError" role="alert">{accountActionError}</div>}
        </Panel>

        <Panel
          title={uiText(uiLanguage, "创作偏好", "Writing preferences")}
          icon={Settings2}
          action={<span className={preferenceDirty ? "statusWarn" : "statusOk"}>{preferenceDirty ? uiText(uiLanguage, "未保存", "Unsaved") : uiText(uiLanguage, "已保存", "Saved")}</span>}
        >
          <p className="languageDescription">
            {uiText(uiLanguage, "这些偏好会在每一轮正文生成时加入上下文，并受固定 token 预算保护。", "These preferences are included in the context for every prose generation within a fixed token budget.")}
          </p>
          <div className="preferenceGrid">
            {preferenceFields.map((field) => {
              const copy = uiLanguage === "zh-CN" ? field : preferenceFieldsEn[field.id];
              return (
              <label key={field.id}>
                <span>{copy.label}</span>
                <textarea
                  rows={2}
                  maxLength={4000}
                  placeholder={copy.placeholder}
                  value={userPreferences.find((item) => item.preferenceType === field.id)?.content ?? ""}
                  onChange={(event) => onChangePreference(field.id, event.target.value)}
                />
              </label>
            );})}
          </div>
          <div className="routingActions">
            <button className="cmdButton primary" type="button" onClick={onSavePreferences} disabled={!preferenceDirty || savingPreferences}>
              {savingPreferences ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
              {uiText(uiLanguage, "保存偏好", "Save preferences")}
            </button>
          </div>
          {preferenceNotice && <div className="routingNotice" role="status">{preferenceNotice}</div>}
          {preferenceError && <div className="authError" role="alert">{preferenceError}</div>}
        </Panel>

        <div className="providerCards">
          {(["deepinfra", "openai"] as const).map((provider) => {
            const configured = providers?.availability[provider] ?? false;
            const statusText = providers ? (configured ? uiText(uiLanguage, "已配置", "Configured") : uiText(uiLanguage, "未配置", "Not configured")) : uiText(uiLanguage, "检查中", "Checking");
            return (
              <Panel
                key={provider}
                title={provider === "deepinfra" ? "DeepInfra" : "OpenAI"}
                icon={Cpu}
                action={<span className={configured ? "statusOk" : "statusWarn"}>{configured ? <KeyRound size={13} /> : <AlertTriangle size={13} />}{statusText}</span>}
              >
                <div className="serverCredentialStatus">
                  <KeyRound size={13} />
                  <span><b>{uiText(uiLanguage, "服务器托管凭据", "Server-managed credential")}</b><small>{uiText(uiLanguage, "通过后端环境配置，浏览器无法读取或修改密钥。", "Configured on the server; the browser cannot read or modify the key.")}</small></span>
                </div>
                <div className="modelPills">
                  {models.filter((model) => model.provider === provider).length ? (
                    models.filter((model) => model.provider === provider).map((model) => {
                      const health = providers?.model_health[model.model];
                      const checking = checkingModelId === model.model;
                      const status = !health || !health.fresh ? "unknown" : health.status;
                      const statusLabel = !health ? uiText(uiLanguage, "未检测", "Not checked") : !health.fresh ? uiText(uiLanguage, "结果已过期", "Expired") : health.status === "available" ? uiText(uiLanguage, "可用", "Available") : uiText(uiLanguage, "不可用", "Unavailable");
                      const StatusIcon = checking ? RefreshCw : status === "available" ? CheckCircle2 : status === "unavailable" ? AlertTriangle : CircleDashed;
                      return (
                        <button
                          key={model.model}
                          className={`modelHealthButton ${status} ${Object.values(routeModels).includes(model.model) ? "routed" : ""}`}
                          type="button"
                          aria-label={`${uiText(uiLanguage, "检测", "Check")} ${model.label}`}
                          title={health?.error || `${uiText(uiLanguage, "检测", "Check")} ${model.label}`}
                          disabled={!configured || Boolean(checkingModelId)}
                          onClick={() => onTestModel(model)}
                        >
                          <StatusIcon size={13} className={checking ? "spinIcon" : undefined} />
                          <span><b>{model.label}</b><small>{checking ? uiText(uiLanguage, "检测中", "Checking") : statusLabel}{health?.checked_at ? ` · ${formatStoryUpdated(health.checked_at, uiLanguage)}` : ""}</small></span>
                        </button>
                      );
                    })
                  ) : (
                    <EmptyState>{uiText(uiLanguage, `后端未返回 ${provider} 模型。`, `No ${provider} models returned by the server.`)}</EmptyState>
                  )}
                </div>
              </Panel>
            );
          })}
        </div>
        {modelHealthNotice && <div className="routingNotice" role="status">{modelHealthNotice}</div>}
        {modelHealthError && <div className="authError" role="alert">{modelHealthError}</div>}

        <Panel
          title={uiText(uiLanguage, "模型用途路由", "Purpose routing")}
          icon={Route}
          action={<span className={routeDirty || savingRoutes ? "statusWarn" : "statusOk"}>{savingRoutes ? uiText(uiLanguage, "保存中…", "Saving...") : routeDirty ? uiText(uiLanguage, "待保存", "Pending") : uiText(uiLanguage, "已保存", "Saved")}</span>}
        >
          <ul className="routingList">
            {purposeRoutes.map((route) => (
              <li key={route.id} className={selectedPurpose === route.id ? "active" : undefined}>
                <span>
                  <button type="button" onClick={() => onSelectPurpose(route.id)}>
                    <b>{uiLanguage === "zh-CN" ? purposeRoutesZh[route.id].label : route.label}</b>
                    <small>{uiLanguage === "zh-CN" ? purposeRoutesZh[route.id].description : route.description}</small>
                  </button>
                </span>
                <select
                  value={routeModels[route.id] ?? providers?.purpose_defaults[route.id] ?? ""}
                  disabled={!models.length}
                  onChange={(event) => onSelectRouteModel(route.id, event.target.value)}
                >
                  {models.length ? (
                    models.map((model) => (
                      <option
                        key={model.model}
                        value={model.model}
                        disabled={providers?.model_health[model.model]?.fresh && providers.model_health[model.model].status === "unavailable"}
                      >
                        {model.label} ({model.provider})
                      </option>
                    ))
                  ) : (
                    <option value="">{uiText(uiLanguage, "等待后端模型列表", "Waiting for server model list")}</option>
                  )}
                </select>
              </li>
            ))}
          </ul>
          <div className="routingActions">
            <button className="cmdButton" type="button" onClick={onRestoreSavedRoutes} disabled={!routeDirty || savingRoutes}>
              <RefreshCw size={13} /> {uiText(uiLanguage, "恢复已保存", "Restore saved")}
            </button>
            <button className="cmdButton" type="button" onClick={onUseDefaultRoutes} disabled={savingRoutes || !providers}>
              <Route size={13} /> {uiText(uiLanguage, "使用默认值", "Use defaults")}
            </button>
          </div>
          {routeNotice && <div className="routingNotice" role="status">{routeNotice}</div>}
          {routeError && <div className="authError" role="alert">{routeError}</div>}
        </Panel>
      </div>
    </section>
  );
}

function SelectMenu({
  className = "",
  icon: Icon,
  label,
  value,
  options,
  onChange,
  disabled = false,
  placeholder = "请选择"
}: {
  className?: string;
  icon: LucideIcon;
  label: string;
  value: string;
  options: Array<{ value: string; label: string; detail?: string; icon?: LucideIcon; disabled?: boolean }>;
  onChange: (value: string) => void;
  disabled?: boolean;
  placeholder?: string;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = options.find((option) => option.value === value);
  const SelectedIcon = selected?.icon ?? Icon;
  const hasOptionIcons = options.some((option) => option.icon);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("mousedown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={`selectMenu ${className} ${hasOptionIcons ? "hasOptionIcons" : ""} ${open ? "open" : ""}`}>
      <button
        type="button"
        className="selectMenuTrigger"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        disabled={disabled}
        onClick={() => setOpen((current) => !current)}
      >
        <SelectedIcon size={14} />
        <span>{selected?.label ?? placeholder}</span>
        <ChevronDown size={14} />
      </button>
      {open && (
        <div className="selectMenuPopover" role="listbox" aria-label={label}>
          {options.map((option) => {
            const OptionIcon = option.icon;
            return (
              <button
                key={option.value}
                type="button"
                role="option"
                aria-selected={option.value === value}
                disabled={option.disabled}
                onClick={() => {
                  onChange(option.value);
                  setOpen(false);
                }}
              >
                {OptionIcon && <i className="selectOptionIcon"><OptionIcon size={15} /></i>}
                <span>{option.label}</span>
                {option.detail && <small>{option.detail}</small>}
                {option.value === value && <Check className="selectOptionCheck" size={13} />}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Panel({ title, icon: Icon, action, count, children }: { title: string; icon?: LucideIcon; action?: ReactNode; count?: number; children: ReactNode }) {
  return (
    <section className="makePanel" aria-label={title}>
      <header>
        {Icon && <Icon size={14} />}
        <h3>{title}</h3>
        {typeof count === "number" && <span className="countBadge">{count}</span>}
        {action}
      </header>
      <div className="panelBody">{children}</div>
    </section>
  );
}

function Pill({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "teal" | "amber" | "graphite" | "danger" }) {
  return <span className={`pill ${tone}`}>{children}</span>;
}

function EmptyState({ children }: { children: ReactNode }) {
  return <p className="emptyState">{children}</p>;
}

function Stat({ label, value, icon: Icon, accent = "ink" }: { label: string; value: string; icon?: LucideIcon; accent?: "ink" | "teal" | "amber" }) {
  return (
    <div className="statTile">
      <div>{Icon && <Icon size={12} />}<span>{label}</span></div>
      <strong className={accent}>{value}</strong>
    </div>
  );
}

function Meter({ value, tone = "teal" }: { value: number; tone?: "teal" | "amber" | "graphite" }) {
  const pct = Math.max(0, Math.min(100, value < 0 ? 50 + value / 2 : value));
  return <span className="meter"><i className={tone} style={{ width: `${pct}%` }} /></span>;
}

function ProgressiveControls({
  uiLanguage,
  collection,
  total,
  visible,
  onMore,
  onCollapse
}: {
  uiLanguage: UiLanguage;
  collection: InspectorCollection;
  total: number;
  visible: number;
  onMore: (collection: InspectorCollection, total: number) => void;
  onCollapse: (collection: InspectorCollection) => void;
}) {
  if (total <= 3) return null;
  const shown = Math.min(total, visible);
  return (
    <div className="progressiveControls">
      <small>{shown} / {total}</small>
      <span />
      {shown > 3 && (
        <button className="cmdButton" type="button" onClick={() => onCollapse(collection)}>
          <ChevronsUp size={13} />{uiText(uiLanguage, "收起", "Collapse")}
        </button>
      )}
      {shown < total && (
        <button className="cmdButton" type="button" onClick={() => onMore(collection, total)}>
          <ChevronsDown size={13} />{uiText(uiLanguage, `再加载 ${Math.min(3, total - shown)} 条`, `Load ${Math.min(3, total - shown)} more`)}
        </button>
      )}
    </div>
  );
}

function countWorldRules(rules: unknown) {
  if (Array.isArray(rules)) return rules.length;
  if (!rules || typeof rules !== "object") return 0;
  return Object.values(rules).reduce((total, value) => total + (Array.isArray(value) ? value.length : 1), 0);
}

function formatStoryUpdated(value: string, uiLanguage: UiLanguage = "zh-CN") {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value || uiText(uiLanguage, "刚刚", "just now");
  return new Intl.DateTimeFormat(uiLanguage === "zh-CN" ? "zh-CN" : "en-AU", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit"
  }).format(date);
}

function normalizeImportance(value: number) {
  if (!Number.isFinite(value)) return 5;
  return Math.max(1, Math.min(10, Math.round(value)));
}

function Telemetry({ label, value, icon: Icon }: { label: string; value: string; icon?: LucideIcon }) {
  return (
    <div className="telemetry">
      <dt>{Icon && <Icon size={11} />} {label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function TabButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button type="button" className={active ? "active" : ""} onClick={onClick} aria-label={label}><Icon size={14} /><span>{label}</span></button>;
}

function IconToggle({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button className={`iconToggle ${active ? "active" : ""}`} onClick={onClick} aria-label={label} title={label}><Icon size={15} /></button>;
}

function MobileTabButton({ active, onClick, icon: Icon, label }: { active: boolean; onClick: () => void; icon: LucideIcon; label: string }) {
  return <button className={active ? "active" : ""} onClick={onClick} aria-label={label}><Icon size={18} /><span>{label}</span></button>;
}

function CommandButton({ icon: Icon, label, primary = false, compact = false, disabled = false, onClick }: { icon: LucideIcon; label: string; primary?: boolean; compact?: boolean; disabled?: boolean; onClick?: () => void }) {
  return <button className={`cmdButton ${primary ? "primary" : ""} ${compact ? "compact" : ""}`} disabled={disabled} onClick={onClick} aria-label={label} title={label}><Icon size={compact ? 11 : 13} /><span>{label}</span></button>;
}

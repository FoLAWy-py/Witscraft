"use client";

import {
  AlertTriangle,
  Backpack,
  Braces,
  BookOpen,
  BookText,
  Brain,
  Check,
  ClipboardList,
  Clock,
  Copy,
  Cpu,
  Feather,
  Gauge,
  GitBranch,
  GitFork,
  Globe2,
  HeartHandshake,
  Lock,
  LogOut,
  MapPin,
  Moon,
  PanelLeft,
  PanelRight,
  PenLine,
  Plus,
  RefreshCw,
  Settings2,
  ShieldCheck,
  Sun,
  Target,
  Trash2,
  UserRound,
  Waves,
  X
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AuthGate,
  AuthLoading,
  EmailVerificationGate,
  PasswordResetGate,
  WorkspaceLoadFailure,
  WorkspaceSkeleton
} from "./auth-gates";
import { QuotaMeter } from "./quota-meter";
import { LeftRail } from "./library-rail";
import { SettingsView } from "./settings-view";
import { StoryWizard } from "./story-wizard";
import { Transcript } from "./transcript";
import {
  purposeLabels,
  purposeRoutes,
  purposeRoutesZh,
  uiText,
  type UiLanguage
} from "./workspace-config";
import {
  EmptyState,
  IconToggle,
  Meter,
  MobileTabButton,
  Panel,
  Pill,
  ProgressiveControls,
  Stat,
  TabButton,
  Telemetry,
  formatStoryUpdated,
  normalizeImportance
} from "./workspace-ui";
import { ApiError, StreamInterruptedError, confirmEmailVerification, confirmPasswordReset, createBranch, createCharacter, createStory, deleteAccount, deleteBranch, deleteCharacter, deleteStory, downloadAccountExport, downloadStoryExport, duplicateBranch, generateSessionSummary, getAuthSessions, getCurrentUser, getMyQuota, getProviders, getUserPreferences, getWorkspace, login, logout, register, requestEmailVerification, requestPasswordReset, revertModelRoutes, revokeAuthSession, sendStoryMessage, streamStoryMessage, switchBranch, testProviderModel, updateBranch, updateCanonFact, updateCharacter, updateMemoryItem, updateModelRoutes, updateStory, updateUserPreferences, updateWorld } from "@/lib/api";
import type { AuthSessionSummary, AuthUser, CanonFactSummary, ChatResponse, ConsistencyCheck, CreateStoryInput, LoginInput, MemoryItemSummary, ModelOption, ModelRouteChange, ProvidersResponse, QuotaUsage, RegisterInput, SessionSummary, StoryPurpose, StoryState, UserPreference, WorkspaceResponse } from "@/lib/types";

type View = "story" | "settings";
type MobileTab = "library" | "story" | "inspector";
type InteractionMode = "choices" | "open";
type ConsistencyMode = "manual" | "auto" | "off";
type Message = { id?: string; role: "assistant" | "user" | "beat"; content: string; author?: string; time?: string; choices?: string[]; consistencyCheck?: ConsistencyCheck | null };
type StorySummary = WorkspaceResponse["stories"][number];
type BranchSummary = WorkspaceResponse["branches"][number];
type StoryChapterSummary = WorkspaceResponse["chapters"][number];
type CharacterSummary = WorkspaceResponse["characters"][number];
type RelationshipSummary = WorkspaceResponse["relationships"][number];
type WorldDraft = { name: string; description: string; genre: string };
type CharacterDraft = { name: string; role: string };
type KnowledgeDraft = { content: string; importance: number };
type AuthStatus = "checking" | "anonymous" | "authenticated";
type InspectorCollection = "branches" | "relationships" | "inventory" | "threads" | "summaries" | "canon" | "memories";
type WorkspaceHistoryMode = "push" | "replace";
type RecoveryKind = "api" | "database" | "network" | "provider" | "stream" | "sync" | "stopped";

const STORY_WIZARD_STORAGE_VERSION = 1;
const UI_LANGUAGE_KEY = "witscraft:ui-language";

function storyWizardStorageKey(userId: string) {
  return `witscraft:story-wizard:${userId}:v${STORY_WIZARD_STORAGE_VERSION}`;
}

function classifyFailure(caught: unknown, fallback: string): { message: string; kind: RecoveryKind } {
  if (caught instanceof StreamInterruptedError) {
    return { message: "生成连接在完成前中断。已保留当前内容，请重新同步数据库中的最终状态。", kind: "stream" };
  }
  if (caught instanceof ApiError) {
    if (caught.status === 429 && caught.message.toLowerCase().includes("quota")) {
      return { message: "账号本周 AI 额度不足。所有小说共享该额度，可在设置中查看使用百分比。", kind: "api" };
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
    if (caught.status === 422 && caught.message.startsWith("Action rejected:")) {
      return { message: `行动未成立：${caught.message.slice("Action rejected:".length).trim()}`, kind: "api" };
    }
    return { message: `API 请求失败（${caught.status}）：${caught.message}`, kind: "api" };
  }
  if (caught instanceof TypeError || (caught instanceof Error && caught.message === "Network request failed")) {
    return { message: "无法连接 Witscraft 服务。请检查网络后重试。", kind: "network" };
  }
  return { message: fallback, kind: "api" };
}


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

export default function WorkspaceClient() {
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
  const [characterList, setCharacterList] = useState<CharacterSummary[]>([]);
  const [relationshipList, setRelationshipList] = useState<RelationshipSummary[]>([]);
  const [selectedPurpose, setSelectedPurpose] = useState<StoryPurpose>("normal_chat");
  const [routeModels, setRouteModels] = useState<Partial<Record<StoryPurpose, string>>>({});
  const [savedRouteModels, setSavedRouteModels] = useState<Partial<Record<StoryPurpose, string>>>({});
  const [savingRoutes, setSavingRoutes] = useState(false);
  const [routeHistory, setRouteHistory] = useState<ModelRouteChange[]>([]);
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
  const [savingChapterCount, setSavingChapterCount] = useState(false);
  const [chapterCountNotice, setChapterCountNotice] = useState<string | null>(null);
  const [interactionMode, setInteractionMode] = useState<InteractionMode>("choices");
  const [savingInteractionMode, setSavingInteractionMode] = useState(false);
  const [consistencyMode, setConsistencyMode] = useState<ConsistencyMode>("auto");
  const [savingConsistencyMode, setSavingConsistencyMode] = useState(false);
  const [selectedModel, setSelectedModel] = useState("");
  const [messages, setMessages] = useState<Message[]>([]);
  const [chapters, setChapters] = useState<StoryChapterSummary[]>([]);
  const [plannedChapterCount, setPlannedChapterCount] = useState(12);
  const [minimumPlannedChapterCount, setMinimumPlannedChapterCount] = useState(3);
  const [roadmapVersion, setRoadmapVersion] = useState(0);
  const [minimumChapterLength, setMinimumChapterLength] = useState(1200);
  const [chapterLengthUnit, setChapterLengthUnit] = useState<"characters" | "words">("characters");
  const [endingTitle, setEndingTitle] = useState("");

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
  const [editingCanonFactOriginalContent, setEditingCanonFactOriginalContent] = useState("");
  const [canonFactDraft, setCanonFactDraft] = useState<KnowledgeDraft>({ content: "", importance: 5 });
  const [savingCanonFactId, setSavingCanonFactId] = useState<string | null>(null);
  const [confirmingCanonFactId, setConfirmingCanonFactId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [recoveryKind, setRecoveryKind] = useState<RecoveryKind | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const streamAssistantActiveRef = useRef(false);

  const refreshQuota = useCallback(async () => {
    try {
      setQuota(await getMyQuota());
    } catch {
      setQuota(null);
    }
  }, []);

  const applyWorkspace = useCallback((data: WorkspaceResponse, historyMode: WorkspaceHistoryMode = "replace") => {
    setStoryId(data.story_id);
    setBranchId(data.branch_id);
    setBranchList(data.branches ?? []);
    setStoryList(data.stories);
    setWorld(data.world ?? {});
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
    setChapters(data.chapters ?? []);
    setPlannedChapterCount(data.planned_chapter_count ?? 12);
    setMinimumPlannedChapterCount(data.minimum_planned_chapter_count ?? 3);
    setRoadmapVersion(data.roadmap_version ?? 0);
    setMinimumChapterLength(data.minimum_chapter_length ?? 1200);
    setChapterLengthUnit(data.chapter_length_unit ?? "characters");
    setEndingTitle(data.ending_title ?? "");
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
  }, []);

  const clearWorkspace = useCallback(() => {
    setStoryId("");
    setBranchId("");
    setBranchList([]);
    setStoryList([]);
    setWorld({});
    setCharacterList([]);
    setRelationshipList([]);
    setMessages([]);
    setChapters([]);
    setPlannedChapterCount(12);
    setMinimumPlannedChapterCount(3);
    setRoadmapVersion(0);
    setMinimumChapterLength(1200);
    setChapterLengthUnit("characters");
    setEndingTitle("");
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
    setChapterCountNotice(null);
    setInteractionMode("choices");
    setAuthSessions([]);
    setConfirmRevokeSessionId(null);
    setSessionError(null);
    setWorkspaceInitialized(false);
    setShowStoryWizard(false);
    syncWorkspaceLocation("", "", "replace");
  }, []);

  const loadWorkspace = useCallback(async (
    nextStoryId?: string,
    nextBranchId?: string,
    historyMode: WorkspaceHistoryMode = "replace"
  ) => {
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
      const issue = classifyFailure(caught, "小说数据读取失败。请稍后重试。");
      setError(issue.message);
      setRecoveryKind(issue.kind);
    } finally {
      setWorkspaceLoading(false);
    }
  }, [applyWorkspace, clearWorkspace]);

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
          setAuthNotice("邮箱验证成功，你的互动小说已解锁。");
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
        setRouteHistory(data.route_history);
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
      .catch(() => setPreferenceError("读取故事偏好失败，请稍后重试。"));
    void refreshQuota();
    void loadWorkspace();
  }, [authStatus, authUser?.email_verified, loadWorkspace, refreshQuota]);

  useEffect(() => {
    if (authStatus !== "authenticated" || !authUser?.email_verified) return;
    const restoreWorkspaceFromHistory = () => {
      const location = readWorkspaceLocation();
      setShowStoryWizard(new URL(window.location.href).searchParams.get("new_story") === "1");
      void loadWorkspace(location.storyId, location.branchId, "replace");
    };
    window.addEventListener("popstate", restoreWorkspaceFromHistory);
    return () => window.removeEventListener("popstate", restoreWorkspaceFromHistory);
  }, [authStatus, authUser?.email_verified, loadWorkspace]);

  const loadAuthSessions = useCallback(async () => {
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
  }, [clearWorkspace]);

  useEffect(() => {
    if (authStatus !== "authenticated" || view !== "settings") return;
    void loadAuthSessions();
  }, [authStatus, loadAuthSessions, view]);

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

  const models = useMemo(() => providers?.models ?? [], [providers]);
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

  const completeRoutes = useCallback((source: Partial<Record<StoryPurpose, string>>): Record<StoryPurpose, string> | null => {
    if (!providers) return null;
    const entries = purposeRoutes.map(({ id }) => [id, source[id] ?? providers.purpose_defaults[id]] as const);
    if (entries.some(([, model]) => !model)) return null;
    return Object.fromEntries(entries) as Record<StoryPurpose, string>;
  }, [providers]);

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
        if (response.route_change) {
          setRouteHistory((current) => [response.route_change!, ...current].slice(0, 10));
        }
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
  }, [completeRoutes, providers, routeDirty, routeModels]);

  function setRouteModel(purpose: StoryPurpose, modelId: string) {
    setRouteModels((current) => ({ ...current, [purpose]: modelId }));
    if (purpose === selectedPurpose) setSelectedModel(modelId);
    setRouteNotice(null);
    setRouteError(null);
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

  async function handleRevertRoutes() {
    if (savingRoutes || routeDirty || !routeHistory.length) return;
    routeSaveVersionRef.current += 1;
    setSavingRoutes(true);
    setRouteError(null);
    setRouteNotice("正在撤销最近一次模型路由变更…");
    try {
      const response = await revertModelRoutes();
      setRouteModels(response.purpose_routes);
      setSavedRouteModels(response.purpose_routes);
      if (response.route_change) {
        setRouteHistory((current) => [response.route_change!, ...current].slice(0, 10));
      }
      setRouteNotice("已撤销最近一次模型路由变更；撤销操作已写入审计历史。");
    } catch (caught) {
      setRouteError(caught instanceof ApiError ? caught.message : "撤销模型路由失败，请稍后重试。");
      setRouteNotice(null);
    } finally {
      setSavingRoutes(false);
    }
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
      setPreferenceNotice("故事偏好已保存，开篇设定和后续小说生成都会引用。");
    } catch (caught) {
      setPreferenceError(caught instanceof ApiError ? caught.message : "保存故事偏好失败，请稍后重试。");
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

  async function handleChapterCountChange(nextCount: number) {
    if (!storyId || !branchId || savingChapterCount || nextCount === plannedChapterCount) return;
    setSavingChapterCount(true);
    setChapterCountNotice(null);
    try {
      const data = await updateStory(storyId, {
        plannedChapterCount: nextCount,
        branchId,
        roadmapVersion
      });
      applyWorkspace(data);
      setChapterCountNotice(uiText(
        uiLanguage,
        `计划已调整为 ${nextCount} 章；新增远期章节会在接近时随剧情更新。`,
        `Plan updated to ${nextCount} chapters. New distant chapters will adapt as the story approaches them.`
      ));
    } catch (caught) {
      setChapterCountNotice(caught instanceof ApiError
        ? caught.message
        : uiText(uiLanguage, "调整章节数失败，请稍后重试。", "Could not change the chapter count. Please try again."));
    } finally {
      setSavingChapterCount(false);
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

  async function handleSend(override?: string, controlMode: "player_action" | "continue" = "player_action") {
    const text = (override ?? draft).trim();
    if (!text || pending) return;
    if (!storyId || !branchId) {
      setError("小说数据尚未加载完成，暂时不能发送。");
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
          purpose: selectedPurpose,
          storyId,
          branchId,
          idempotencyKey,
          branchVersion,
          signal: controller.signal,
          controlMode
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
            if (response.chapter_transition?.completed) {
              const transition = response.chapter_transition;
              setChapters((current) => current.map((chapter) => {
                if (chapter.number === transition.chapter_number) {
                  return { ...chapter, status: "completed" };
                }
                if (chapter.number === transition.next_chapter_number) {
                  return { ...chapter, status: "active" };
                }
                return chapter;
              }));
              setChapterCountNotice(
                transition.next_chapter_number
                  ? uiText(uiLanguage, `第 ${transition.chapter_number} 章自然收束，进入第 ${transition.next_chapter_number} 章。`, `Chapter ${transition.chapter_number} reached a natural close. Chapter ${transition.next_chapter_number} begins.`)
                  : uiText(uiLanguage, `第 ${transition.chapter_number} 章与故事已完成。`, `Chapter ${transition.chapter_number} and the story are complete.`)
              );
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
        setError("回复已保存，但 Inspector 暂时无法与数据库同步；重新读取小说即可恢复。");
        setRecoveryKind("sync");
      }
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === "AbortError") {
        setError("生成已停止。若模型已返回部分文本，后端会保存 partial 记录供后续恢复。");
        setRecoveryKind("stopped");
      } else {
        if (caught instanceof ApiError && caught.status === 422) {
          try {
            applyWorkspace(await getWorkspace(storyId));
          } catch {
            // Keep the explicit rejection even if the background resync is unavailable.
          }
        }
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
    if (!storyId || !branchId || pending) return;
    const instruction = command === "rewrite" ? overrideInstruction ?? draft.trim() : "";
    const idempotencyKey = window.crypto.randomUUID();
    const branchVersion = branchList.find((branch) => branch.id === branchId)?.version ?? 0;
    setPending(true);
    setError(null);
    if (command === "rewrite" && instruction && overrideInstruction === undefined) setDraft("");
    try {
      await sendStoryMessage({
        message: instruction,
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
    setEditingWorld(true);
    setWorldDraft({
      name: String(world.name ?? ""),
      description: String(world.description ?? ""),
      genre: String(world.genre ?? "")
    });
  }

  function handleCancelEditWorld() {
    setEditingWorld(false);
    setWorldDraft({ name: "", description: "", genre: "" });
  }

  async function handleSaveWorld() {
    const worldId = typeof world.id === "string" ? world.id : "";
    const name = worldDraft.name.trim();
    if (!worldId || !storyId || !name || savingWorld) return;

    setSavingWorld(true);
    setError(null);
    try {
      const input = {
        name,
        description: worldDraft.description.trim(),
        genre: worldDraft.genre.trim()
      };
      const data = await updateWorld(worldId, input, storyId);
      applyWorkspace(data);
      setEditingWorld(false);
    } catch {
      setError("更新世界设定失败。请确认数据库服务正在运行。");
    } finally {
      setSavingWorld(false);
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
    setConfirmingCanonFactId(null);
    setEditingCanonFactId(fact.id);
    setEditingCanonFactOriginalContent(fact.content);
    setCanonFactDraft({ content: fact.content, importance: fact.importance });
  }

  function handleCancelEditCanonFact() {
    setConfirmingCanonFactId(null);
    setEditingCanonFactId(null);
    setEditingCanonFactOriginalContent("");
    setCanonFactDraft({ content: "", importance: 5 });
  }

  async function handleSaveCanonFact() {
    const content = canonFactDraft.content.trim();
    if (!editingCanonFactId || !content || savingCanonFactId) return;
    const original = canonFactItems.find((fact) => fact.id === editingCanonFactId);
    if (!original || !editingCanonFactOriginalContent) return;
    const contentChanged = content !== editingCanonFactOriginalContent;
    if (contentChanged && confirmingCanonFactId !== editingCanonFactId) {
      setConfirmingCanonFactId(editingCanonFactId);
      return;
    }

    setSavingCanonFactId(editingCanonFactId);
    setError(null);
    try {
      const data = await updateCanonFact(
        editingCanonFactId,
        {
          content,
          importance: normalizeImportance(canonFactDraft.importance),
          ...(contentChanged
            ? {
                expectedContent: editingCanonFactOriginalContent,
                branchId,
                branchVersion: branchList.find((branch) => branch.id === branchId)?.version ?? 0,
                roadmapVersion,
                confirmFutureInvalidation: true
              }
            : {})
        },
        storyId
      );
      applyWorkspace(data);
      handleCancelEditCanonFact();
    } catch (saveError) {
      if (saveError instanceof ApiError && saveError.status === 409) {
        await loadWorkspace(storyId, branchId, "replace");
        setError(uiText(uiLanguage, "既定事实或路线图已变化，请重新检查后再修正。", "Canon or the roadmap changed. Review it again before correcting."));
      } else {
        setError(uiText(uiLanguage, "更新既定事实失败。请稍后重试。", "Could not update the canon fact. Try again."));
      }
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
          routeHistory={routeHistory}
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
          onRevertRoutes={() => void handleRevertRoutes()}
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
              characters={characterList}
              loading={workspaceLoading}
              creatingStory={creatingStory}
              editingStoryId={editingStoryId}
              storyTitleDraft={storyTitleDraft}
              savingStory={savingStory}
              confirmDeleteStoryId={confirmDeleteStoryId}
              deletingStoryId={deletingStoryId}
              editingWorld={editingWorld}
              worldDraft={worldDraft}
              savingWorld={savingWorld}
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
              onCancelEditWorld={handleCancelEditWorld}
              onChangeWorldDraft={setWorldDraft}
              onSaveWorld={handleSaveWorld}
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
              chapters={chapters}
              plannedChapterCount={plannedChapterCount}
              minimumPlannedChapterCount={minimumPlannedChapterCount}
              minimumChapterLength={minimumChapterLength}
              chapterLengthUnit={chapterLengthUnit}
              endingTitle={endingTitle}
              roadmapVersion={roadmapVersion}
              savingChapterCount={savingChapterCount}
              chapterCountNotice={chapterCountNotice}
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
              onChapterCountChange={(count) => void handleChapterCountChange(count)}
              onSend={() => void handleSend()}
              onSelectChoice={(choice) => void handleSend(choice)}
              onInteractionModeChange={(mode) => void handleInteractionModeChange(mode)}
              onConsistencyModeChange={(mode) => void handleConsistencyModeChange(mode)}
              onStop={handleStopGeneration}
              onResync={() => void handleResyncWorkspace()}
              onContinue={() => void handleSend(uiText(uiLanguage, "继续", "Continue"), "continue")}
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
              editingCanonFactOriginalContent={editingCanonFactOriginalContent}
              savingCanonFactId={savingCanonFactId}
              confirmingCanonFactId={confirmingCanonFactId}
              plannedFutureChapterCount={chapters.filter((chapter) => chapter.status === "planned").length}
              onStartEditMemory={handleStartEditMemory}
              onCancelEditMemory={handleCancelEditMemory}
              onChangeMemoryDraft={setMemoryDraft}
              onSaveMemory={handleSaveMemory}
              onStartEditCanonFact={handleStartEditCanonFact}
              onCancelEditCanonFact={handleCancelEditCanonFact}
              onChangeCanonFactDraft={(nextDraft) => {
                setCanonFactDraft(nextDraft);
                setConfirmingCanonFactId(null);
              }}
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
  editingCanonFactOriginalContent,
  savingCanonFactId,
  confirmingCanonFactId,
  plannedFutureChapterCount,
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
  editingCanonFactOriginalContent: string;
  savingCanonFactId: string | null;
  confirmingCanonFactId: string | null;
  plannedFutureChapterCount: number;
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

      <details className="inspectorArchive">
        <summary>
          <BookText size={14} />
          <span>{uiText(uiLanguage, "故事档案与高级工具", "Story records and advanced tools")}</span>
          <small>{uiText(uiLanguage, "关系、线索、导出、记忆与模型状态", "Relationships, threads, export, memory, and model status")}</small>
        </summary>
        <div className="inspectorArchiveBody">
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
                      originalContent={editingCanonFactOriginalContent}
                      confirmingCorrection={confirmingCanonFactId === fact.id}
                      affectedFutureCount={plannedFutureChapterCount}
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
      </details>
    </div>
  );
}

function KnowledgeEditForm({
  uiLanguage,
  type,
  draft,
  saving,
  originalContent,
  confirmingCorrection = false,
  affectedFutureCount = 0,
  onChange,
  onSave,
  onCancel
}: {
  uiLanguage: UiLanguage;
  type: "memory" | "canon";
  draft: KnowledgeDraft;
  saving: boolean;
  originalContent?: string;
  confirmingCorrection?: boolean;
  affectedFutureCount?: number;
  onChange: (draft: KnowledgeDraft) => void;
  onSave: () => void;
  onCancel: () => void;
}) {
  const label = type === "memory" ? uiText(uiLanguage, "记忆", "Memory") : uiText(uiLanguage, "既定事实", "Canon fact");
  const isCanonCorrection = type === "canon" && originalContent !== undefined && draft.content.trim() !== originalContent;

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
      {confirmingCorrection && isCanonCorrection && (
        <div className="canonCorrectionReview" data-testid="canon-correction-review" role="alert">
          <strong>{uiText(uiLanguage, "确认修正影响", "Confirm correction impact")}</strong>
          <dl>
            <div><dt>{uiText(uiLanguage, "修正前", "Before")}</dt><dd>{originalContent}</dd></div>
            <div><dt>{uiText(uiLanguage, "修正后", "After")}</dt><dd>{draft.content.trim()}</dd></div>
          </dl>
          <p>
            {uiText(
              uiLanguage,
              `不会改写已完成正文；将使 ${affectedFutureCount} 个未来章节计划和暂定结局失效。`,
              `Completed prose will remain unchanged; ${affectedFutureCount} future chapter plan(s) and the provisional ending will be invalidated.`
            )}
          </p>
        </div>
      )}
      <div className="formActions">
        <button className="cmdButton primary" onClick={onSave} disabled={saving || !draft.content.trim()}>
          {saving ? <RefreshCw size={13} className="spinIcon" /> : <Check size={13} />}
          {confirmingCorrection && isCanonCorrection
            ? uiText(uiLanguage, "确认修正", "Confirm correction")
            : isCanonCorrection
              ? uiText(uiLanguage, "检查影响", "Review impact")
              : uiText(uiLanguage, "保存", "Save")}
        </button>
        <button className="cmdButton" onClick={onCancel} disabled={saving}>
          <X size={13} />
          {uiText(uiLanguage, "取消", "Cancel")}
        </button>
      </div>
    </div>
  );
}

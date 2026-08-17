export type ProviderName = "openai" | "deepinfra";
export type StoryPurpose =
  | "critical_story_generation"
  | "normal_chat"
  | "state_update"
  | "event_extraction"
  | "summary_generation"
  | "consistency_check";

export type ModelOption = {
  provider: ProviderName;
  model: string;
  label: string;
  family: "gpt" | "deepseek" | "qwen" | string;
  best_for: string[];
  default_max_output_tokens: number;
  hard_max_output_tokens: number;
  temperature: number;
  top_p: number;
  reasoning_effort?: string | null;
  notes: string;
};

export type ModelHealth = {
  provider: ProviderName;
  model: string;
  status: "available" | "unavailable";
  latency_ms?: number | null;
  error?: string | null;
  checked_at: string;
  fresh: boolean;
};

export type ProvidersResponse = {
  models: ModelOption[];
  purpose_defaults: Record<StoryPurpose, string>;
  purpose_budgets: Record<StoryPurpose, {
    max_input_tokens: number;
    default_output_tokens: number;
    hard_output_tokens: number;
  }>;
  purpose_routes: Partial<Record<StoryPurpose, string>>;
  availability: {
    openai: boolean;
    deepinfra: boolean;
    database: boolean;
  };
  model_health: Record<string, ModelHealth>;
  deepinfra_base_url: string;
};

export type ModelHealthResponse = {
  ok: boolean;
  health: ModelHealth;
};

export type ModelRoutesResponse = {
  purpose_routes: Record<StoryPurpose, string>;
};

export type AuthUser = {
  id: string;
  email: string;
  display_name: string;
  email_verified: boolean;
  is_admin: boolean;
};

export type QuotaUsage = {
  limit_tokens: number | null;
  used_tokens: number;
  remaining_tokens: number | null;
  percentage_used: number;
  soft_limit_percentage: number;
  soft_limit_reached: boolean;
  period_started_at: string;
  resets_at: string;
  unlimited: boolean;
  story_id?: string | null;
  story_limit_tokens?: number | null;
  story_used_tokens?: number | null;
  story_remaining_tokens?: number | null;
  story_percentage_used?: number | null;
};

export type AdminUserQuota = QuotaUsage & {
  id: string;
  email: string;
  display_name: string;
  is_admin: boolean;
  created_at: string;
};

export type AdminQuotaResetEvent = {
  id: string;
  administrator_email: string | null;
  administrator_name: string | null;
  reason: string;
  effective_at: string;
};

export type AdminOverview = {
  total_users: number;
  administrator_count: number;
  weekly_token_quota: number;
  period_started_at: string;
  resets_at: string;
  total_used_tokens: number;
  filtered_users: number;
  page: number;
  page_size: number;
  total_pages: number;
  users: AdminUserQuota[];
  reset_events: AdminQuotaResetEvent[];
};

export type QuotaResetResponse = {
  reset_event_id: string;
  effective_at: string;
  resets_at: string;
};

export type AuthResponse = {
  user: AuthUser;
};

export type AuthSessionSummary = {
  id: string;
  created_at: string;
  expires_at: string;
  current: boolean;
  device_name?: string | null;
  ip_address?: string | null;
  ip_region?: string | null;
};

export type AuthSessionListResponse = {
  sessions: AuthSessionSummary[];
};

export type AuthMessageResponse = {
  message: string;
};

export type LoginInput = {
  email: string;
  password: string;
};

export type RegisterInput = LoginInput & {
  displayName: string;
};

export type StoryState = {
  location: string;
  time: string;
  mood: string;
  objective: string;
  inventory: string[];
  open_threads: string[];
};

export type WorkspaceMessage = {
  id: string;
  role: "assistant" | "user" | "beat" | string;
  content: string;
  author?: string | null;
  time?: string | null;
  choices?: string[];
  consistency_check?: ConsistencyCheck | null;
};

export type ConsistencyIssue = {
  severity: string;
  source: string;
  rule: string;
  reference: string;
  evidence: string;
  message: string;
};

export type ConsistencyCheck = {
  status: "pass" | "fail" | "off";
  issue_count: number;
  issues: ConsistencyIssue[];
};

export type MemoryItemSummary = {
  id: string;
  content: string;
  importance: number;
  type?: string;
  has_embedding?: boolean;
  embedding_dimensions?: number;
};

export type CanonFactSummary = {
  id: string;
  content: string;
  importance: number;
  type?: string;
};

export type SessionSummary = {
  id: string;
  title: string;
  content: string;
  type: string;
  message_count: number;
  token_count?: number | null;
  created_at: string;
};

export type WorkspaceResponse = {
  story_id: string;
  branch_id: string;
  branches: Array<{
    id: string;
    name: string;
    parent_branch_id?: string | null;
    created_at: string;
    active: boolean;
    version: number;
  }>;
  stories: Array<{
    id: string;
    title: string;
    world: string;
    updated: string;
    wordCount: number;
    status?: string;
  }>;
  world: Record<string, unknown>;
  worlds: Array<{
    id: string;
    name: string;
    genre: string;
    story_count: number;
  }>;
  characters: Array<{
    id: string;
    name: string;
    role: string;
    present: boolean;
    initials: string;
    main: boolean;
  }>;
  messages: WorkspaceMessage[];
  story_state: StoryState;
  relationships: Array<{
    from: string;
    to: string;
    bond: string;
    value: number;
  }>;
  retrieved_memories: string[];
  canon_facts: string[];
  memory_items: MemoryItemSummary[];
  canon_fact_items: CanonFactSummary[];
  summaries: SessionSummary[];
  model_call?: ChatResponse["model_call"] | null;
  onboarding_required: boolean;
  story_prompt: string;
  interaction_mode: "choices" | "open";
  consistency_mode: "manual" | "auto" | "off";
};

export type CreateStoryInput = {
  title: string;
  worldId?: string;
  genre: string;
  worldName: string;
  premise: string;
  protagonistName: string;
  protagonistRole: string;
  tone: string;
  openingMode: "blank" | "custom";
  openingText: string;
  customPrompt: string;
  interactionMode: "choices" | "open";
};

export type StoryDraftSuggestion = Omit<CreateStoryInput, "worldId" | "openingMode" | "customPrompt" | "interactionMode">;

export type StoryInterviewMessage = {
  role: "user" | "assistant";
  content: string;
  options?: string[];
  ready?: boolean;
};

export type StoryInterviewResponse = {
  assistantMessage: string;
  options: string[];
  draft: CreateStoryInput;
  missingFields: string[];
  readyForConfirmation: boolean;
};

export type UserPreference = {
  id?: string;
  preferenceType: string;
  content: string;
  strength: number;
};

export type UserPreferencesResponse = {
  preferences: UserPreference[];
};

export type CreateBranchInput = {
  name: string;
};

export type UpdateStoryInput = {
  title?: string;
  customPrompt?: string;
  interactionMode?: "choices" | "open";
  consistencyMode?: "manual" | "auto" | "off";
};

export type UpdateWorldInput = {
  name: string;
  description: string;
  genre: string;
};

export type UpdateCharacterInput = {
  name: string;
  role: string;
};

export type UpdateMemoryInput = {
  content: string;
  importance: number;
};

export type UpdateCanonFactInput = {
  content: string;
  importance: number;
};

export type ChatResponse = {
  message_id: string;
  content: string;
  story_state: StoryState;
  retrieved_memories: string[];
  canon_facts: string[];
  choices: string[];
  idempotency_key?: string | null;
  branch_version?: number | null;
  model_call: {
    id?: string;
    provider: ProviderName;
    model: string;
    purpose?: StoryPurpose;
    latency_ms?: number | null;
    input_tokens?: number | null;
    output_tokens?: number | null;
    cost_estimate?: number | null;
    turn_id?: string | null;
    request_id?: string | null;
    status?: string;
    pricing_version?: string | null;
    dry_run?: boolean;
    consistency_check?: ConsistencyCheck;
    consistency_revision?: {
      attempted: boolean;
      accepted: boolean;
      reason: string;
    };
  };
};

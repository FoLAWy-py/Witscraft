import { expect, test, type Page, type Route } from "@playwright/test";

const user = {
  id: "00000000-0000-0000-0000-000000000101",
  email: "player@example.invalid",
  display_name: "Test Player",
  email_verified: true,
  is_admin: false
};

const model = {
  provider: "deepinfra",
  model: "Qwen/Qwen3-Max",
  label: "Qwen 3 Max",
  family: "qwen",
  best_for: ["normal_chat"],
  default_max_output_tokens: 2400,
  hard_max_output_tokens: 8192,
  temperature: 0.8,
  top_p: 0.9,
  reasoning_effort: null,
  notes: "Deterministic browser fixture"
};

const purposes = [
  "critical_story_generation",
  "normal_chat",
  "state_update",
  "event_extraction",
  "summary_generation",
  "consistency_check"
] as const;

function json(route: Route, body: unknown, status = 200) {
  return route.fulfill({ status, contentType: "application/json", body: JSON.stringify(body) });
}

async function installApiFixture(page: Page) {
  let authenticated = false;
  let branchVersion = 0;
  let storyState = { location: "Archive", time: "Midnight", mood: "tense", objective: "Find the key", inventory: [] as string[], open_threads: [] as string[] };
  const messages = [
    {
      id: "00000000-0000-0000-0000-000000000501",
      role: "assistant",
      content: "The clockwork archive waits for your decision.",
      author: "Narrative engine",
      choices: []
    }
  ];

  const workspace = () => ({
    story_id: "00000000-0000-0000-0000-000000000301",
    branch_id: "00000000-0000-0000-0000-000000000401",
    branches: [{
      id: "00000000-0000-0000-0000-000000000401",
      name: "main",
      parent_branch_id: null,
      created_at: "2026-08-17T00:00:00Z",
      active: true,
      version: branchVersion
    }],
    stories: [{
      id: "00000000-0000-0000-0000-000000000301",
      title: "The Clockwork Key",
      world: "The Archive",
      updated: "now",
      wordCount: 42,
      status: "active"
    }],
    world: { name: "The Archive", genre: "mystery" },
    worlds: [{ id: "00000000-0000-0000-0000-000000000201", name: "The Archive", genre: "mystery", story_count: 1 }],
    characters: [{ id: "00000000-0000-0000-0000-000000000202", name: "Mira", role: "investigator", present: true, initials: "MI", main: true }],
    messages,
    story_state: storyState,
    relationships: [],
    retrieved_memories: [],
    canon_facts: [],
    memory_items: [],
    canon_fact_items: [],
    summaries: [],
    model_call: null,
    onboarding_required: false,
    story_prompt: "",
    interaction_mode: "open",
    consistency_mode: "auto"
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;

    if (path.endsWith("/api/auth/me")) {
      return authenticated ? json(route, { user }) : json(route, { detail: "Authentication required" }, 401);
    }
    if (path.endsWith("/api/auth/login")) {
      authenticated = true;
      return json(route, { user });
    }
    if (path.endsWith("/api/providers")) {
      const defaults = Object.fromEntries(purposes.map((purpose) => [purpose, model.model]));
      const budgets = Object.fromEntries(purposes.map((purpose) => [purpose, { max_input_tokens: 16000, default_output_tokens: 2400, hard_output_tokens: 8192 }]));
      return json(route, {
        models: [model],
        model_roles: [
          {
            id: "narrative_author",
            label: "AI author",
            description: "Authors prose and dialogue.",
            purposes: ["normal_chat", "critical_story_generation"],
            user_configurable: true,
            configuration_source: "purpose_routes",
            default_models: {
              normal_chat: model.model,
              critical_story_generation: model.model
            }
          },
          {
            id: "structured_extraction",
            label: "Structured extraction",
            description: "Extracts state and events.",
            purposes: ["state_update", "event_extraction"],
            user_configurable: true,
            configuration_source: "purpose_routes",
            default_models: { state_update: model.model, event_extraction: model.model }
          },
          {
            id: "continuity_revision",
            label: "Continuity revision",
            description: "Revises high-severity conflicts.",
            purposes: ["consistency_check"],
            user_configurable: true,
            configuration_source: "purpose_routes",
            default_models: { consistency_check: model.model }
          },
          {
            id: "summary",
            label: "Context summary",
            description: "Compresses completed narrative history.",
            purposes: ["summary_generation"],
            user_configurable: true,
            configuration_source: "purpose_routes",
            default_models: { summary_generation: model.model }
          },
          {
            id: "embedding",
            label: "Memory embedding",
            description: "Indexes eligible memories.",
            purposes: [],
            user_configurable: false,
            configuration_source: "deployment",
            default_models: {},
            deployment: { provider: "openai", model: "text-embedding-test", version: "test-v1" }
          }
        ],
        purpose_defaults: defaults,
        purpose_budgets: budgets,
        purpose_routes: {},
        availability: { openai: false, deepinfra: true, database: true },
        model_health: {},
        effective_routes: Object.fromEntries(purposes.map((purpose) => [purpose, {
          purpose,
          provider: "deepinfra",
          model: "Qwen/Qwen3-Max",
          source: "system_default",
          max_input_tokens: budgets[purpose].max_input_tokens,
          default_output_tokens: budgets[purpose].default_output_tokens,
          hard_output_tokens: budgets[purpose].hard_output_tokens
        }])),
        route_history: []
      });
    }
    if (path.endsWith("/api/workspace/preferences")) {
      return json(route, { preferences: [] });
    }
    if (path.endsWith("/api/quota/me")) {
      const storyId = url.searchParams.get("story_id");
      return json(route, {
        limit_tokens: 500000,
        used_tokens: 100,
        remaining_tokens: 499900,
        percentage_used: 0.02,
        soft_limit_percentage: 80,
        soft_limit_reached: false,
        period_started_at: "2026-08-17T00:00:00Z",
        resets_at: "2026-08-24T00:00:00Z",
        unlimited: false,
        story_id: storyId,
        story_limit_tokens: storyId ? 250000 : null,
        story_used_tokens: storyId ? 50 : null,
        story_remaining_tokens: storyId ? 249950 : null,
        story_percentage_used: storyId ? 0.02 : null
      });
    }
    if (path.endsWith("/api/workspace")) {
      return json(route, workspace());
    }
    if (path.endsWith("/api/chat/stream")) {
      const payload = request.postDataJSON();
      expect(payload).not.toHaveProperty("provider");
      expect(payload).not.toHaveProperty("model");
      expect(payload.purpose).toBe("normal_chat");
      const reply = "Mira turns the key, and the sealed archive answers.";
      branchVersion += 1;
      storyState = { location: "Sealed archive", time: "Midnight", mood: "tense", objective: "Read the answer", inventory: ["key"], open_threads: [] };
      messages.push(
        { id: crypto.randomUUID(), role: "user", content: payload.message, author: "You", choices: [] },
        { id: crypto.randomUUID(), role: "assistant", content: reply, author: "Narrative engine", choices: [] }
      );
      const response = {
        message_id: messages.at(-1)?.id,
        content: reply,
        story_state: storyState,
        retrieved_memories: [],
        canon_facts: [],
        choices: [],
        idempotency_key: payload.idempotency_key,
        branch_version: branchVersion,
        model_call: { provider: "deepinfra", model: model.model, purpose: "normal_chat", dry_run: true }
      };
      const body = [
        `event: start\ndata: ${JSON.stringify({ type: "start", provider: "deepinfra", model: model.model })}\n\n`,
        `event: delta\ndata: ${JSON.stringify({ type: "delta", content: reply })}\n\n`,
        `event: done\ndata: ${JSON.stringify({ type: "done", response })}\n\n`
      ].join("");
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    return json(route, { detail: `Unhandled fixture route: ${request.method()} ${path}` }, 501);
  });
}

test("player signs in and directs the next scene", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/witscraft/");

  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  await page.getByLabel("邮箱").fill(user.email);
  await page.getByLabel("密码").fill("browser-fixture-passphrase");
  await page.getByRole("button", { name: "进入小说" }).click();

  await expect(page.getByText("The Clockwork Key", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("The clockwork archive waits for your decision.")).toBeVisible();

  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page.getByText("小说周额度", { exact: true })).toBeVisible();
  await expect(page.getByText("249,950", { exact: true })).toBeVisible();
  await expect(page.getByTestId("model-role-narrative_author")).toContainText("AI 作者");
  await expect(page.getByTestId("model-role-structured_extraction")).toContainText("结构化提取");
  await expect(page.getByTestId("model-role-continuity_revision")).toContainText("连续性修订");
  await expect(page.getByTestId("model-role-summary")).toContainText("上下文摘要");
  await expect(page.getByTestId("model-role-embedding")).toContainText("text-embedding-test");
  await expect(page.getByTestId("model-role-embedding")).toContainText("更换模型需要受控重建索引");
  await page.getByRole("button", { name: "故事", exact: true }).click();

  const composer = page.getByPlaceholder("引导下一幕…");
  await composer.fill("I turn the key and enter the sealed room.");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("I turn the key and enter the sealed room.")).toBeVisible();
  await expect(page.getByText("Mira turns the key, and the sealed archive answers.")).toBeVisible();
  await expect(page.getByText("Sealed archive", { exact: true }).first()).toBeVisible();
});

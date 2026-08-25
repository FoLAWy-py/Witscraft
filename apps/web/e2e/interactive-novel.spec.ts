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
const styleProfileId = "00000000-0000-0000-0000-000000000777";

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
  let plannedChapterCount = 12;
  let roadmapVersion = 1;
  let canonContent = "The archive door has never opened.";
  let canonCorrected = false;
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
      version: branchVersion,
      roadmap_version: roadmapVersion,
      roadmap_source: roadmapVersion === 1 ? "provider" : "deterministic_fallback",
      ending_title: "The Last Archive"
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
    canon_facts: [canonContent],
    memory_items: [],
    canon_fact_items: [{
      id: "00000000-0000-0000-0000-000000000801",
      content: canonContent,
      importance: 8,
      type: canonCorrected ? "player_correction" : "llm_state_extraction"
    }],
    summaries: [],
    model_call: null,
    onboarding_required: false,
    story_prompt: "",
    interaction_mode: "open",
    consistency_mode: "auto",
    planned_chapter_count: plannedChapterCount,
    minimum_planned_chapter_count: 3,
    minimum_chapter_length: 1200,
    chapter_length_unit: "words",
    prose_language: "en",
    roadmap_version: roadmapVersion,
    roadmap_source: roadmapVersion === 1 ? "provider" : "deterministic_fallback",
    ending_title: canonCorrected ? "Awaiting the player's path" : "The Last Archive",
    chapters: Array.from({ length: plannedChapterCount }, (_, index) => ({
      id: `00000000-0000-0000-0000-${String(600 + index).padStart(12, "0")}`,
      number: index + 1,
      title: canonCorrected && index > 0 ? `Unwritten Chapter ${String(index + 1).padStart(2, "0")}` : `Chapter ${index + 1}`,
      objective: canonCorrected && index > 0 ? "Adapt this chapter to the player's established path and next decision." : `Objective ${index + 1}`,
      status: index === 0 ? "active" : "planned",
      roadmap_version: index < 12 ? 1 : roadmapVersion,
      message_id: null,
      completed_at: null
    }))
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
            deployment: { provider: "openai", model: "text-embedding-test", dimensions: 1024, version: "test-v1" }
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
      expect(url.searchParams.has("story_id")).toBe(false);
      return json(route, {
        limit_tokens: 500000,
        used_tokens: 100,
        remaining_tokens: 499900,
        percentage_used: 12.5,
        soft_limit_percentage: 80,
        soft_limit_reached: false,
        period_started_at: "2026-08-17T00:00:00Z",
        resets_at: "2026-08-24T00:00:00Z",
        unlimited: false
      });
    }
    if (path.endsWith("/api/workspace")) {
      return json(route, workspace());
    }
    if (path.endsWith("/api/workspace/style-profiles") && request.method() === "POST") {
      const payload = request.postDataJSON();
      expect(payload.rights_attested).toBe(true);
      expect(payload.source_type).toBe("public_domain");
      expect(payload.raw_text.replace(/\s/g, "").length).toBeGreaterThanOrEqual(500);
      return json(route, {
        id: styleProfileId,
        name: payload.name,
        source_type: payload.source_type,
        source_label: payload.source_label,
        content_hash: "a".repeat(64),
        analysis_version: "style-profile-v1",
        language: payload.language,
        features: { pacing: "moderate", viewpoint: "third" },
        reused: false
      });
    }
    if (path.endsWith("/api/workspace/stories") && request.method() === "POST") {
      const payload = request.postDataJSON();
      expect(payload.planned_chapter_count).toBe(24);
      expect(payload.minimum_chapter_length).toBe(2400);
      expect(payload.chapter_length_unit).toBe("words");
      expect(payload.prose_language).toBe("en");
      expect(payload.style_profile_id).toBe(styleProfileId);
      return json(route, workspace());
    }
    if (path.endsWith("/api/workspace/stories/00000000-0000-0000-0000-000000000301") && request.method() === "PATCH") {
      const payload = request.postDataJSON();
      if (payload.planned_chapter_count !== undefined) {
        expect(payload).toMatchObject({
          planned_chapter_count: 15,
          branch_id: "00000000-0000-0000-0000-000000000401",
          roadmap_version: 1
        });
        plannedChapterCount = payload.planned_chapter_count;
        roadmapVersion += 1;
      }
      return json(route, workspace());
    }
    if (path.endsWith("/api/workspace/canon-facts/00000000-0000-0000-0000-000000000801") && request.method() === "PATCH") {
      const payload = request.postDataJSON();
      expect(payload).toMatchObject({
        content: "The archive door opened before midnight.",
        importance: 8,
        expected_content: "The archive door has never opened.",
        branch_id: "00000000-0000-0000-0000-000000000401",
        branch_version: 0,
        roadmap_version: 2,
        confirm_future_invalidation: true
      });
      canonContent = payload.content;
      canonCorrected = true;
      roadmapVersion += 1;
      branchVersion += 1;
      return json(route, workspace());
    }
    if (path.endsWith("/api/chat/stream")) {
      const payload = request.postDataJSON();
      expect(payload).not.toHaveProperty("provider");
      expect(payload).not.toHaveProperty("model");
      expect(payload.purpose).toBe("normal_chat");
      expect(payload.control_mode).toBe(payload.message === "继续" ? "continue" : "player_action");
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
  const currentWorld = page.getByRole("region", { name: "当前世界" });
  await expect(currentWorld).toContainText("The Archive");
  await expect(currentWorld).toContainText("这套世界观仅属于当前小说。");
  const activeCharacters = page.getByRole("region", { name: "活跃角色" });
  await expect(activeCharacters).toContainText("Mira");
  await expect(activeCharacters).toContainText("investigator");
  await expect(activeCharacters).toContainText("主角");
  const currentScene = page.getByRole("region", { name: "当前场景" });
  await expect(currentScene).toContainText("Archive");
  await expect(currentScene).toContainText("Find the key");
  const branches = page.getByRole("region", { name: "分支" });
  await expect(branches).toContainText("main");
  await expect(branches).toContainText("当前");
  await expect(page.getByText("The clockwork archive waits for your decision.")).toBeVisible();
  const roadmap = page.getByText("章节路线图", { exact: true });
  await expect(roadmap).toBeVisible();
  await expect(page.getByText("当前结局：", { exact: false })).toBeHidden();
  await roadmap.click();
  await expect(page.getByText("当前结局：", { exact: false })).toBeVisible();
  await expect(page.getByText("The Last Archive", { exact: true })).toBeVisible();
  await page.getByLabel("调整计划总章节").fill("15");
  await page.getByRole("button", { name: "更新章节数" }).click();
  await expect(page.getByText("计划已调整为 15 章", { exact: false })).toBeVisible();
  await expect(page.getByText("Chapter 15", { exact: true })).toBeVisible();

  await page.locator("summary").filter({ hasText: "故事档案与高级工具" }).click();
  await page.getByTestId("edit-canon-00000000-0000-0000-0000-000000000801").click();
  await page.getByLabel("既定事实 content").fill("The archive door opened before midnight.");
  await page.getByRole("button", { name: "检查影响" }).click();
  const correctionReview = page.getByTestId("canon-correction-review");
  await expect(correctionReview).toContainText("The archive door has never opened.");
  await expect(correctionReview).toContainText("The archive door opened before midnight.");
  await expect(correctionReview).toContainText("14 个未来章节计划");
  const correctionResponse = page.waitForResponse(
    (response) =>
      response.url().includes("/api/workspace/canon-facts/") && response.status() === 200,
  );
  await page.getByRole("button", { name: "确认修正" }).click();
  await correctionResponse;
  await expect(correctionReview).toHaveCount(0);
  await expect(
    page
      .getByRole("region", { name: "既定事实" })
      .getByText("The archive door opened before midnight.", { exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Unwritten Chapter 15", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page.getByText("12.5%", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("500,000", { exact: true })).toHaveCount(0);
  await expect(page.getByText("499,900", { exact: true })).toHaveCount(0);
  await expect(page.getByTestId("model-role-narrative_author")).toContainText("AI 作者");
  await expect(page.getByTestId("model-role-structured_extraction")).toContainText("结构化提取");
  await expect(page.getByTestId("model-role-continuity_revision")).toContainText("连续性修订");
  await expect(page.getByTestId("model-role-summary")).toContainText("上下文摘要");
  await expect(page.getByTestId("model-role-embedding")).toContainText("text-embedding-test");
  await expect(page.getByTestId("model-role-embedding")).toContainText("更换模型需要受控重建索引");
  await page.getByRole("button", { name: "故事", exact: true }).click();

  const composer = page.getByPlaceholder("描述主角下一步行动…");
  await composer.fill("I turn the key and enter the sealed room.");
  await page.getByRole("button", { name: "发送" }).click();

  await expect(page.getByText("I turn the key and enter the sealed room.")).toBeVisible();
  await expect(page.getByText("Mira turns the key, and the sealed archive answers.")).toBeVisible();
  await expect(page.getByText("Sealed archive", { exact: true }).first()).toBeVisible();
  const continued = page.waitForRequest((request) => (
    request.url().endsWith("/api/chat/stream")
    && request.postDataJSON().control_mode === "continue"
  ));
  await page.getByRole("button", { name: "继续", exact: true }).last().click();
  await continued;
  await expect(page.getByText("继续", { exact: true }).last()).toBeVisible();
});

test("player configures chapter count and minimum development during story creation", async ({ page }) => {
  await installApiFixture(page);
  await page.goto("/witscraft/");
  await page.getByLabel("邮箱").fill(user.email);
  await page.getByLabel("密码").fill("browser-fixture-passphrase");
  await page.getByRole("button", { name: "进入小说" }).click();

  await page.getByRole("button", { name: "新建小说" }).click();
  await page.getByLabel("书名").fill("The Tidal Archive");
  await page.getByLabel("类型").fill("Mystery");
  await page.getByLabel("叙事风格").fill("Restrained and tense");
  await page.getByLabel("计划章节数").fill("24");
  await page.getByLabel("正文语言").selectOption("en");
  await page.getByLabel("自定义最低量").fill("2400");
  await page.getByLabel("世界名称").fill("The Tidal City");
  await page.getByLabel("故事前提").fill("A sealed archive opens only when the tide is lowest.");
  await page.getByLabel("主角姓名").fill("Mira");
  await page.getByLabel("主角身份与目标").fill("An archivist searching for a missing record.");
  await page.getByLabel("小说专属 Prompt").fill("Preserve player agency and build clues fairly.");
  await page.locator("summary").filter({ hasText: "可选：导入参考文风" }).click();
  await page.getByLabel("画像名称").fill("Public-domain harbor profile");
  await page.getByLabel("权利来源").selectOption("public_domain");
  await page.getByLabel("来源说明（不填作者模仿指令）").fill("Reviewed public-domain fixture");
  await page.getByLabel("粘贴参考文本（500–30,000 字符）").fill(
    Array.from({ length: 45 }, (_, index) => `Paragraph ${index + 1} observes the harbor light and tide without choosing for the traveler.`).join("\n")
  );
  await page.getByLabel("我确认拥有该文本、已获许可，或其属于公版。").check();
  await page.getByRole("button", { name: "提取并绑定抽象画像" }).click();
  await expect(page.getByText("Public-domain harbor profile 已绑定")).toBeVisible();
  await expect(page.getByLabel("粘贴参考文本（500–30,000 字符）")).toHaveValue("");
  await page.getByRole("button", { name: "确认并创建小说" }).click();

  await expect(page.getByText("The Clockwork Key", { exact: true }).first()).toBeVisible();
});

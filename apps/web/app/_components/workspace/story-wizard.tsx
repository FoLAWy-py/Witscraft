"use client";

import {
  BookOpen,
  Check,
  CheckCircle2,
  CircleDashed,
  Feather,
  FileText,
  ListChecks,
  LogOut,
  MessageCircle,
  PenLine,
  RefreshCw,
  Send,
  Sparkles,
  UserRound,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { ApiError, streamStoryInterview } from "@/lib/api";
import type { CreateStoryInput, StoryInterviewMessage } from "@/lib/types";
import { uiText } from "./workspace-ui";

type UiLanguage = "zh-CN" | "en";

function initialStoryInterviewMessages(): StoryInterviewMessage[] {
  return [{
    role: "assistant",
    content: "我们一起把新小说说清楚。你更想从哪一部分开始？",
    options: ["先说一个故事灵感", "先确定主角", "先搭建世界"]
  }];
}
function initialStoryDraft(uiLanguage: UiLanguage = "zh-CN"): CreateStoryInput {
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
    interactionMode: "choices",
    plannedChapterCount: 12,
    targetChapterLength: 1800,
    chapterLengthUnit: uiLanguage === "zh-CN" ? "characters" : "words",
    proseLanguage: uiLanguage
  };
}

export function StoryWizard({
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
  const [draft, setDraft] = useState<CreateStoryInput>(() => initialStoryDraft(uiLanguage));
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
  const chapterSettingsValid = draft.plannedChapterCount >= 3
    && draft.plannedChapterCount <= 120
    && draft.targetChapterLength >= 500
    && draft.targetChapterLength <= 5000;
  const readyToCreate = missingFields.length === 0 && chapterSettingsValid;

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(storageKey);
      if (stored) {
        const parsed = JSON.parse(stored) as { messages?: StoryInterviewMessage[]; draft?: CreateStoryInput };
        if (Array.isArray(parsed.messages) && parsed.messages.length > 0) {
          setInterviewMessages(parsed.messages.slice(-40));
        }
        if (parsed.draft && typeof parsed.draft === "object") {
          setDraft((current) => ({ ...current, ...parsed.draft }));
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
              <div className="wizardFieldGrid">
                <label>
                  <span>{uiText(uiLanguage, "计划章节数", "Planned chapters")}</span>
                  <input type="number" min={3} max={120} value={draft.plannedChapterCount} onChange={(event) => updateDraft({ plannedChapterCount: Number(event.target.value) })} />
                  <small>{uiText(uiLanguage, "可选 3–120 章，未来标题会随你的选择调整。", "Choose 3–120 chapters; future titles adapt to your choices.")}</small>
                </label>
                <label>
                  <span>{uiText(uiLanguage, "正文语言", "Prose language")}</span>
                  <select value={draft.proseLanguage} onChange={(event) => updateDraft({ proseLanguage: event.target.value, chapterLengthUnit: event.target.value.startsWith("zh") ? "characters" : "words" })}>
                    <option value="zh-CN">中文</option>
                    <option value="en">English</option>
                  </select>
                </label>
              </div>
              <div className="wizardFieldGrid">
                <label>
                  <span>{uiText(uiLanguage, "每章目标长度", "Target length per chapter")}</span>
                  <select value={[800, 1800, 3000].includes(draft.targetChapterLength) ? String(draft.targetChapterLength) : "custom"} onChange={(event) => { if (event.target.value !== "custom") updateDraft({ targetChapterLength: Number(event.target.value) }); }}>
                    <option value="800">{uiText(uiLanguage, "精简 · 800", "Concise · 800")}</option>
                    <option value="1800">{uiText(uiLanguage, "标准 · 1,800", "Standard · 1,800")}</option>
                    <option value="3000">{uiText(uiLanguage, "细致 · 3,000", "Detailed · 3,000")}</option>
                    <option value="custom">{uiText(uiLanguage, "自定义", "Custom")}</option>
                  </select>
                </label>
                <label>
                  <span>{uiText(uiLanguage, "自定义长度", "Custom length")}</span>
                  <input type="number" min={500} max={5000} step={100} value={draft.targetChapterLength} onChange={(event) => updateDraft({ targetChapterLength: Number(event.target.value) })} />
                  <small>{draft.chapterLengthUnit === "characters" ? uiText(uiLanguage, "按可见字符估算，允许约 ±15%。", "Measured in visible characters, approximately ±15%.") : uiText(uiLanguage, "按英文单词估算，允许约 ±15%。", "Measured in words, approximately ±15%.")}</small>
                </label>
              </div>
              {!chapterSettingsValid && <p className="fieldError">{uiText(uiLanguage, "章节数需为 3–120，每章长度需为 500–5,000。", "Use 3–120 chapters and a per-chapter length of 500–5,000.")}</p>}
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
                  <BookOpen size={16} /><span><b>{uiText(uiLanguage, "空白开场", "Blank opening")}</b><small>{uiText(uiLanguage, "进入小说后开始", "Start after entering the novel")}</small></span>
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

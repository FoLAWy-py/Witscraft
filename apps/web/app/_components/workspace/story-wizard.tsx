"use client";

import {
  BookOpen,
  Check,
  CheckCircle2,
  CircleDashed,
  Feather,
  FileUp,
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
import { analyzeStyleProfile, ApiError, streamStoryInterview } from "@/lib/api";
import type { CreateStoryInput, StoryInterviewMessage, StyleProfile } from "@/lib/types";
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
    minimumChapterLength: 1200,
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
  const [referenceText, setReferenceText] = useState("");
  const [referenceName, setReferenceName] = useState("");
  const [referenceSourceType, setReferenceSourceType] = useState<"user_owned" | "licensed" | "public_domain">("user_owned");
  const [referenceSourceLabel, setReferenceSourceLabel] = useState("");
  const [referenceRightsAttested, setReferenceRightsAttested] = useState(false);
  const [styleProfile, setStyleProfile] = useState<StyleProfile | null>(null);
  const [stylePending, setStylePending] = useState(false);
  const [styleError, setStyleError] = useState<string | null>(null);
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
    && draft.minimumChapterLength >= 500
    && draft.minimumChapterLength <= 5000;
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
  const resetStyleSelection = () => {
    setStyleProfile(null);
    updateDraft({ styleProfileId: undefined });
  };
  const handleReferenceFile = async (file?: File) => {
    if (!file) return;
    if (!/\.(txt|md)$/i.test(file.name) || file.size > 120_000) {
      setStyleError(uiText(uiLanguage, "仅支持不超过 120 KB 的 UTF-8 .txt 或 .md 文件。", "Use a UTF-8 .txt or .md file no larger than 120 KB."));
      return;
    }
    const text = await file.text();
    if (text.includes("\uFFFD")) {
      setStyleError(uiText(uiLanguage, "文件不是有效的 UTF-8 文本。", "The file is not valid UTF-8 text."));
      return;
    }
    if (text.length > 30_000) {
      setStyleError(uiText(uiLanguage, "参考文本最多 30,000 个字符。", "Reference text is limited to 30,000 characters."));
      return;
    }
    setReferenceText(text);
    if (!referenceName) setReferenceName(file.name.replace(/\.(txt|md)$/i, ""));
    resetStyleSelection();
    setStyleError(null);
  };
  const handleAnalyzeStyle = async () => {
    if (stylePending || !referenceRightsAttested || !referenceName.trim()) return;
    setStylePending(true);
    setStyleError(null);
    try {
      const profile = await analyzeStyleProfile({
        name: referenceName.trim(),
        sourceType: referenceSourceType,
        sourceLabel: referenceSourceLabel.trim(),
        language: draft.proseLanguage,
        rawText: referenceText,
        rightsAttested: true
      });
      setStyleProfile(profile);
      updateDraft({ styleProfileId: profile.id });
      setReferenceText("");
      setReferenceRightsAttested(false);
    } catch (caught) {
      setStyleError(caught instanceof ApiError ? caught.message : uiText(uiLanguage, "文风画像生成失败。", "Style profiling failed."));
    } finally {
      setStylePending(false);
    }
  };
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
                  <span>{uiText(uiLanguage, "章节最低展开量", "Minimum chapter development")}</span>
                  <select value={[800, 1200, 2000].includes(draft.minimumChapterLength) ? String(draft.minimumChapterLength) : "custom"} onChange={(event) => { if (event.target.value !== "custom") updateDraft({ minimumChapterLength: Number(event.target.value) }); }}>
                    <option value="800">{uiText(uiLanguage, "紧凑 · 至少 800", "Compact · at least 800")}</option>
                    <option value="1200">{uiText(uiLanguage, "自然 · 至少 1,200", "Natural · at least 1,200")}</option>
                    <option value="2000">{uiText(uiLanguage, "充分 · 至少 2,000", "Expansive · at least 2,000")}</option>
                    <option value="custom">{uiText(uiLanguage, "自定义", "Custom")}</option>
                  </select>
                </label>
                <label>
                  <span>{uiText(uiLanguage, "自定义最低量", "Custom minimum")}</span>
                  <input type="number" min={500} max={5000} step={100} value={draft.minimumChapterLength} onChange={(event) => updateDraft({ minimumChapterLength: Number(event.target.value) })} />
                  <small>{draft.chapterLengthUnit === "characters" ? uiText(uiLanguage, "仅防止过早断章；AI 按剧情节奏决定何时换章，不设目标或上限。", "Only prevents an early break; AI follows narrative rhythm with no target or maximum.") : uiText(uiLanguage, "仅防止过早断章；AI 按剧情节奏决定何时换章，不设目标或上限。", "Only prevents an early break; AI follows narrative rhythm with no target or maximum.")}</small>
                </label>
              </div>
              {!chapterSettingsValid && <p className="fieldError">{uiText(uiLanguage, "章节数需为 3–120，最低展开量需为 500–5,000。", "Use 3–120 chapters and a minimum chapter development of 500–5,000.")}</p>}
              <details className="draftPromptField wizardOptionalDisclosure">
                <summary className="draftPromptHeader">
                  <span>{uiText(uiLanguage, "可选：导入参考文风", "Optional: import a style reference")}</span>
                  <small>{uiText(uiLanguage, "展开", "Expand")}</small>
                </summary>
                <small>{uiText(uiLanguage, "原文仅用于本地抽象画像和非复现指纹；不会保存、生成 embedding 或作为作者模仿指令。", "Raw text is used only for local abstract profiling and a non-reproduction fingerprint; it is not retained, embedded, or turned into author-imitation instructions.")}</small>
                <div className="wizardFieldGrid">
                  <label><span>{uiText(uiLanguage, "画像名称", "Profile name")}</span><input value={referenceName} onChange={(event) => { setReferenceName(event.target.value); resetStyleSelection(); }} maxLength={180} placeholder={uiText(uiLanguage, "例如：克制的海港叙事", "For example: restrained harbor prose")} /></label>
                  <label><span>{uiText(uiLanguage, "权利来源", "Rights basis")}</span><select value={referenceSourceType} onChange={(event) => { setReferenceSourceType(event.target.value as typeof referenceSourceType); resetStyleSelection(); }}><option value="user_owned">{uiText(uiLanguage, "我拥有此文本", "I own this text")}</option><option value="licensed">{uiText(uiLanguage, "我已获许可", "I have permission")}</option><option value="public_domain">{uiText(uiLanguage, "公版文本", "Public domain")}</option></select></label>
                </div>
                <label><span>{uiText(uiLanguage, "来源说明（不填作者模仿指令）", "Source note (not an author-imitation instruction)")}</span><input value={referenceSourceLabel} onChange={(event) => { setReferenceSourceLabel(event.target.value); resetStyleSelection(); }} maxLength={220} placeholder={uiText(uiLanguage, "作品、版本或授权说明", "Work, edition, or permission note")} /></label>
                <label><span>{uiText(uiLanguage, "粘贴参考文本（500–30,000 字符）", "Paste reference text (500–30,000 characters)")}</span><textarea value={referenceText} onChange={(event) => { setReferenceText(event.target.value); resetStyleSelection(); }} maxLength={30000} rows={5} /></label>
                <label className="fileInputLabel"><span><FileUp size={13} />{uiText(uiLanguage, "或导入 UTF-8 .txt / .md", "Or import UTF-8 .txt / .md")}</span><input type="file" accept=".txt,.md,text/plain,text/markdown" onChange={(event) => void handleReferenceFile(event.target.files?.[0])} /></label>
                <label className="inlineCheck"><input type="checkbox" checked={referenceRightsAttested} onChange={(event) => setReferenceRightsAttested(event.target.checked)} /><span>{uiText(uiLanguage, "我确认拥有该文本、已获许可，或其属于公版。", "I confirm that I own this text, have permission, or it is public domain.")}</span></label>
                {styleError && <p className="fieldError" role="alert">{styleError}</p>}
                {(styleProfile || draft.styleProfileId) && <p className="wizardReady"><CheckCircle2 size={13} />{styleProfile ? uiText(uiLanguage, `${styleProfile.name} 已绑定${styleProfile.reused ? "（复用缓存）" : ""}`, `${styleProfile.name} attached${styleProfile.reused ? " (cached)" : ""}`) : uiText(uiLanguage, "已绑定缓存文风画像", "Cached style profile attached")}</p>}
                <button className="cmdButton" type="button" onClick={() => void handleAnalyzeStyle()} disabled={stylePending || referenceText.replace(/\s/g, "").length < 500 || !referenceName.trim() || !referenceRightsAttested || (referenceSourceType !== "user_owned" && !referenceSourceLabel.trim())}>
                  {stylePending ? <RefreshCw size={13} className="spinIcon" /> : <Sparkles size={13} />}{stylePending ? uiText(uiLanguage, "正在提取画像", "Profiling") : uiText(uiLanguage, "提取并绑定抽象画像", "Profile and attach")}
                </button>
              </details>
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

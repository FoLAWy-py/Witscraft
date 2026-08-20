"use client";

import {
  AlertTriangle,
  ArrowRight,
  BookOpen,
  Check,
  CircleDashed,
  Cog,
  ListChecks,
  MapPin,
  PenLine,
  RefreshCw,
  Send,
  ShieldCheck,
  Sparkles,
  Square,
  X
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ConsistencyCheck, StoryState, WorkspaceResponse } from "@/lib/types";
import { CommandButton, EmptyState, SelectMenu, uiText } from "./workspace-ui";

type UiLanguage = "zh-CN" | "en";
type InteractionMode = "choices" | "open";
type ConsistencyMode = "manual" | "auto" | "off";
type RecoveryKind = "api" | "database" | "network" | "provider" | "stream" | "sync" | "stopped";
type Message = {
  id?: string;
  role: "assistant" | "user" | "beat";
  content: string;
  author?: string;
  time?: string;
  choices?: string[];
  consistencyCheck?: ConsistencyCheck | null;
};

export function Transcript({
  uiLanguage,
  messages,
  state,
  storyTitle,
  branchName,
  chapters,
  plannedChapterCount,
  targetChapterLength,
  chapterLengthUnit,
  endingTitle,
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
  chapters: WorkspaceResponse["chapters"];
  plannedChapterCount: number;
  targetChapterLength: number;
  chapterLengthUnit: "characters" | "words";
  endingTitle: string;
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
  const currentChapter = chapters.find((chapter) => chapter.status === "active")
    ?? [...chapters].reverse().find((chapter) => chapter.status === "completed")
    ?? chapters[0];

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

      {chapters.length > 0 && (
        <details className="roadmapDisclosure">
          <summary>
            <span>
              <ListChecks size={14} />
              {uiText(uiLanguage, "章节路线图", "Chapter roadmap")}
            </span>
            <strong>
              {uiText(uiLanguage, "第", "Chapter")} {currentChapter?.number ?? 1} / {plannedChapterCount}
              {currentChapter?.title ? ` · ${currentChapter.title}` : ""}
            </strong>
            <small>
              {targetChapterLength.toLocaleString()} {uiText(
                uiLanguage,
                chapterLengthUnit === "characters" ? "字/章" : "词/章",
                chapterLengthUnit === "characters" ? "characters/chapter" : "words/chapter"
              )}
            </small>
          </summary>
          <div className="roadmapSpoilers">
            <p>{uiText(uiLanguage, "以下内容包含未来章节与结局标题。路线图会随玩家选择动态调整。", "The following contains future chapter and ending titles. The roadmap adapts to player choices.")}</p>
            <ol>
              {chapters.map((chapter) => (
                <li key={chapter.id} className={chapter.status}>
                  <span>{chapter.number}</span>
                  <div><strong>{chapter.title}</strong><small>{chapter.objective}</small></div>
                </li>
              ))}
            </ol>
            {endingTitle && <p className="roadmapEnding"><Sparkles size={14} />{uiText(uiLanguage, "当前结局：", "Current ending: ")}<strong>{endingTitle}</strong></p>}
          </div>
        </details>
      )}

      {promptOpen && (
        <div className="promptDialogScrim" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) setPromptOpen(false); }}>
          <section className="promptDialog" role="dialog" aria-modal="true" aria-labelledby="story-prompt-title">
            <header>
              <div>
                <h2 id="story-prompt-title">{uiText(uiLanguage, "当前小说 Prompt", "Story prompt")}</h2>
                <p>{uiText(uiLanguage, "只影响这部小说，并会在每轮生成时与全局故事偏好一起使用。", "Applies only to this story and is used with your global story preferences on every generation.")}</p>
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

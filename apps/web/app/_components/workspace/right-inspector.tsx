"use client";

import {
  AlertTriangle,
  Backpack,
  BookText,
  Brain,
  Braces,
  Check,
  ClipboardList,
  Clock,
  Copy,
  Cpu,
  Gauge,
  GitBranch,
  GitFork,
  HeartHandshake,
  Lock,
  MapPin,
  PenLine,
  Plus,
  RefreshCw,
  Target,
  Trash2,
  Waves,
  X
} from "lucide-react";
import { useEffect, useState } from "react";
import type {
  CanonFactSummary,
  ChatResponse,
  MemoryItemSummary,
  ModelOption,
  SessionSummary,
  StoryPurpose,
  StoryState,
  WorkspaceResponse
} from "@/lib/types";
import { purposeLabels, purposeRoutesZh, uiText, type UiLanguage } from "./workspace-config";
import {
  EmptyState,
  Meter,
  Panel,
  Pill,
  ProgressiveControls,
  Stat,
  Telemetry,
  formatStoryUpdated
} from "./workspace-ui";

type BranchSummary = WorkspaceResponse["branches"][number];
type RelationshipSummary = WorkspaceResponse["relationships"][number];
type KnowledgeDraft = { content: string; importance: number };
type InspectorCollection = "branches" | "relationships" | "inventory" | "threads" | "summaries" | "canon" | "memories";

export function RightInspector({
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

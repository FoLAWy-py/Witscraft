import {
  AlertTriangle,
  BookText,
  Check,
  Circle,
  Dot,
  Globe2,
  PenLine,
  Plus,
  RefreshCw,
  Trash2,
  Users,
  X
} from "lucide-react";
import type { WorkspaceResponse } from "@/lib/types";
import { uiText, type UiLanguage } from "./workspace-config";
import { EmptyState, Panel, Pill, countWorldRules, formatStoryUpdated } from "./workspace-ui";

type StorySummary = WorkspaceResponse["stories"][number];
type CharacterSummary = WorkspaceResponse["characters"][number];
type WorldDraft = { name: string; description: string; genre: string };
type CharacterDraft = { name: string; role: string };

export function LeftRail({
  uiLanguage,
  stories,
  activeStoryId,
  world,
  characters,
  loading,
  creatingStory,
  editingStoryId,
  storyTitleDraft,
  savingStory,
  confirmDeleteStoryId,
  deletingStoryId,
  editingWorld,
  worldDraft,
  savingWorld,
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
  onCancelEditWorld,
  onChangeWorldDraft,
  onSaveWorld,
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
  characters: CharacterSummary[];
  loading: boolean;
  creatingStory: boolean;
  editingStoryId: string | null;
  storyTitleDraft: string;
  savingStory: boolean;
  confirmDeleteStoryId: string | null;
  deletingStoryId: string | null;
  editingWorld: boolean;
  worldDraft: WorldDraft;
  savingWorld: boolean;
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
  onCancelEditWorld: () => void;
  onChangeWorldDraft: (draft: WorldDraft) => void;
  onSaveWorld: () => void;
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
            <button className="plainIcon" aria-label={uiText(uiLanguage, "编辑小说世界观", "Edit story world")} onClick={onStartEditWorld} disabled={!world.id}>
              <PenLine size={14} />
            </button>
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
                {uiText(uiLanguage, "保存", "Save")}
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
            <p className="worldOwnershipNote">{uiText(uiLanguage, "这套世界观仅属于当前小说。", "This world belongs only to the current novel.")}</p>
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

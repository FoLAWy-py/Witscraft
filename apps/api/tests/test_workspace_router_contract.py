from app.main import app


EXPECTED_WORKSPACE_OPERATIONS = {
    ("GET", "/api/workspace", "workspace_api_workspace_get"),
    (
        "PATCH",
        "/api/workspace/canon-facts/{fact_id}",
        "update_canon_fact_api_workspace_canon_facts__fact_id__patch",
    ),
    (
        "DELETE",
        "/api/workspace/characters/{character_id}",
        "delete_character_api_workspace_characters__character_id__delete",
    ),
    (
        "PATCH",
        "/api/workspace/characters/{character_id}",
        "update_character_api_workspace_characters__character_id__patch",
    ),
    (
        "PATCH",
        "/api/workspace/memories/{memory_id}",
        "update_memory_api_workspace_memories__memory_id__patch",
    ),
    (
        "GET",
        "/api/workspace/preferences",
        "get_user_preferences_api_workspace_preferences_get",
    ),
    (
        "PUT",
        "/api/workspace/preferences",
        "update_user_preferences_api_workspace_preferences_put",
    ),
    ("POST", "/api/workspace/stories", "create_story_api_workspace_stories_post"),
    (
        "DELETE",
        "/api/workspace/stories/{story_id}",
        "delete_story_api_workspace_stories__story_id__delete",
    ),
    (
        "PATCH",
        "/api/workspace/stories/{story_id}",
        "update_story_api_workspace_stories__story_id__patch",
    ),
    (
        "POST",
        "/api/workspace/stories/{story_id}/branches",
        "create_branch_api_workspace_stories__story_id__branches_post",
    ),
    (
        "DELETE",
        "/api/workspace/stories/{story_id}/branches/{branch_id}",
        "delete_branch_api_workspace_stories__story_id__branches__branch_id__delete",
    ),
    (
        "PATCH",
        "/api/workspace/stories/{story_id}/branches/{branch_id}",
        "update_branch_api_workspace_stories__story_id__branches__branch_id__patch",
    ),
    (
        "PATCH",
        "/api/workspace/stories/{story_id}/branches/{branch_id}/activate",
        "activate_branch_api_workspace_stories__story_id__branches__branch_id__activate_patch",
    ),
    (
        "POST",
        "/api/workspace/stories/{story_id}/branches/{branch_id}/duplicate",
        "duplicate_branch_api_workspace_stories__story_id__branches__branch_id__duplicate_post",
    ),
    (
        "GET",
        "/api/workspace/stories/{story_id}/branches/{branch_id}/export",
        "export_story_api_workspace_stories__story_id__branches__branch_id__export_get",
    ),
    (
        "POST",
        "/api/workspace/stories/{story_id}/branches/{branch_id}/summaries",
        "create_summary_api_workspace_stories__story_id__branches__branch_id__summaries_post",
    ),
    (
        "PATCH",
        "/api/workspace/stories/{story_id}/world",
        "set_story_world_api_workspace_stories__story_id__world_patch",
    ),
    (
        "POST",
        "/api/workspace/story-draft",
        "generate_story_draft_api_workspace_story_draft_post",
    ),
    (
        "POST",
        "/api/workspace/story-interview",
        "continue_story_interview_api_workspace_story_interview_post",
    ),
    (
        "POST",
        "/api/workspace/story-interview/stream",
        "stream_story_interview_api_workspace_story_interview_stream_post",
    ),
    (
        "POST",
        "/api/workspace/style-profiles",
        "analyze_style_profile_api_workspace_style_profiles_post",
    ),
    ("POST", "/api/workspace/worlds", "create_world_api_workspace_worlds_post"),
    (
        "DELETE",
        "/api/workspace/worlds/{world_id}",
        "delete_world_api_workspace_worlds__world_id__delete",
    ),
    (
        "PATCH",
        "/api/workspace/worlds/{world_id}",
        "update_world_api_workspace_worlds__world_id__patch",
    ),
    (
        "POST",
        "/api/workspace/worlds/{world_id}/characters",
        "create_character_api_workspace_worlds__world_id__characters_post",
    ),
}


def test_workspace_router_preserves_public_operation_contract() -> None:
    actual = {
        (method.upper(), path, operation["operationId"])
        for path, methods in app.openapi()["paths"].items()
        if path == "/api/workspace" or path.startswith("/api/workspace/")
        for method, operation in methods.items()
    }

    assert actual == EXPECTED_WORKSPACE_OPERATIONS

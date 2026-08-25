import warnings

from sqlalchemy.exc import SAWarning

from app.db.models import Base, StoryChapter


def test_model_metadata_dependency_graph_is_explicitly_sortable() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("error", SAWarning)
        table_names = [table.name for table in Base.metadata.sorted_tables]

    assert "messages" in table_names
    assert "story_chapters" in table_names
    deferred = next(
        constraint
        for constraint in StoryChapter.__table__.foreign_key_constraints
        if constraint.name == "fk_story_chapters_message_scope"
    )
    assert deferred.use_alter is True

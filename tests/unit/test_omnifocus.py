"""Unit tests for OmniFocus CLI."""

import json
from unittest.mock import patch, MagicMock
import pytest
from typer.testing import CliRunner
from datetime import datetime, timezone
from omnifocus import (
    app,
    sanitize_task_text,
    extract_tags_from_task,
    Task,
    OmniFocusManager,
    OSXSystem,
)

# Create mock system and manager for all tests
mock_system = MagicMock(spec=OSXSystem)
mock_manager = OmniFocusManager(mock_system)

# Patch the global instances
@pytest.fixture(autouse=True)
def patch_globals():
    """Patch global system and manager to prevent real task creation."""
    with patch("omnifocus.system", mock_system), patch("omnifocus.manager", mock_manager):
        yield

runner = CliRunner()


def test_sanitize_task_text():
    """Test task cleanup function."""
    assert sanitize_task_text("☐ Simple task") == "Simple task"
    assert sanitize_task_text("1. Task with number") == "Task with number"
    assert sanitize_task_text("☑ Completed task") == ""
    assert sanitize_task_text("Task with CUT") == ""
    assert sanitize_task_text("  2.  Indented task  ") == "Indented task"


def test_extract_tags_from_task():
    """Test task and tag extraction functionality."""
    task, tags = extract_tags_from_task("Simple task")
    assert task == "Simple task"
    assert tags == []

    task, tags = extract_tags_from_task("work: Test work task")
    assert task == "Test task"
    assert tags == ["work"]


@pytest.fixture
def mock_system():
    """Create a mock OSXSystem."""
    return MagicMock(spec=OSXSystem)


@pytest.fixture
def manager(mock_system):
    """Create an OmniFocusManager with a mock system."""
    return OmniFocusManager(mock_system)


def test_add_task(manager, mock_system):
    """Test adding a task to OmniFocus."""
    # Test normal task
    manager.add_task("Test task")
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&flag=true&project=today&tags="
    )

    # Test work task
    manager.add_task("Test task", tags=["work"])
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&flag=true&project=today&tags=work"
    )

    # Test short task (should not add)
    manager.add_task("ab")
    assert mock_system.open_url.call_count == 2  # Should not have increased


@patch("omnifocus.manager")
@patch("omnifocus.system")
def test_add_from_clipboard(mock_system_global, mock_manager_global):
    """Test adding tasks from clipboard."""
    # Setup mock clipboard content
    mock_system_global.get_clipboard_content.return_value = """
    1. Task one
    2. Task two
    ☑ Completed task
    work: Task three
    Duplicate task
    duplicate task
    """

    # Test preview mode
    result = runner.invoke(app, ["add-tasks-from-clipboard", "--print-only"])
    assert result.exit_code == 0
    assert "Task one" in result.stdout
    assert "Task two" in result.stdout
    assert "Task three" in result.stdout
    assert "Completed task" not in result.stdout
    assert mock_manager_global.add_task.call_count == 0  # Should not add tasks in preview mode

    # Reset mocks for actual add test
    mock_system_global.reset_mock()
    mock_manager_global.reset_mock()

    # Test actual add
    result = runner.invoke(app, ["add-tasks-from-clipboard"])
    assert result.exit_code == 0
    assert mock_manager_global.add_task.call_count == 4  # Should have added 4 tasks (including duplicates)


def test_get_all_tasks(manager, mock_system):
    """Test getting all tasks."""
    # Mock JavaScript execution result
    mock_system.run_javascript.return_value = json.dumps(
        [
            {
                "name": "Test task 1",
                "project": "today",
                "flagged": True,
                "tags": ["work"],
                "due_date": "2024-01-04T12:00:00Z",
                "creation_date": "2024-01-01T12:00:00Z",
            },
            {
                "name": "Test task 2",
                "project": "Personal",
                "flagged": False,
                "tags": [],
                "due_date": None,
                "creation_date": None,
            },
        ]
    )

    tasks = manager.get_all_tasks()
    assert len(tasks) == 2
    assert tasks[0].name == "Test task 1"
    assert tasks[0].project == "today"
    assert tasks[0].flagged is True
    assert tasks[0].tags == ["work"]
    assert tasks[0].due_date == datetime(2024, 1, 4, 12, 0, tzinfo=timezone.utc)
    assert tasks[0].creation_date == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)

    assert tasks[1].name == "Test task 2"
    assert tasks[1].project == "Personal"
    assert tasks[1].flagged is False
    assert tasks[1].tags == []
    assert tasks[1].due_date is None
    assert tasks[1].creation_date is None


def test_get_flagged_tasks(manager, mock_system):
    """Test getting flagged tasks."""
    # Mock JavaScript execution result
    mock_system.run_javascript.return_value = json.dumps(
        [
            {
                "name": "Flagged task",
                "project": "today",
                "flagged": True,
                "tags": ["work"],
                "due_date": "2024-01-04T12:00:00Z",
                "creation_date": "2024-01-01T12:00:00Z",
            }
        ]
    )

    tasks = manager.get_flagged_tasks()
    assert len(tasks) == 1
    assert tasks[0].name == "Flagged task"
    assert tasks[0].project == "today"
    assert tasks[0].flagged is True
    assert tasks[0].tags == ["work"]
    assert tasks[0].due_date == datetime(2024, 1, 4, 12, 0, tzinfo=timezone.utc)
    assert tasks[0].creation_date == datetime(2024, 1, 1, 12, 0, tzinfo=timezone.utc)


@patch("omnifocus.manager")
@patch("omnifocus.system")
def test_add_from_clipboard_with_existing_tasks(mock_system_global, mock_manager_global):
    """Test that existing tasks are not added when using add-tasks-from-clipboard."""
    # Setup mock clipboard content
    mock_system_global.get_clipboard_content.return_value = """
    1. Existing task
    2. New task
    3. Another existing task
    """

    # Mock existing tasks
    mock_manager_global.get_all_tasks.return_value = [
        Task(name="Existing task", project="today"),
        Task(name="Another existing task", project="Personal"),
    ]

    # Test actual add
    result = runner.invoke(app, ["add-tasks-from-clipboard"])
    assert result.exit_code == 0

    # Verify output shows which tasks already exist
    assert "Existing task (Already exists in project: today)" in result.stdout
    assert "Another existing task (Already exists in project: Personal)" in result.stdout

    # Verify only new tasks were added
    add_task_calls = [call[0][0] for call in mock_manager_global.add_task.call_args_list]
    assert len(add_task_calls) == 1
    assert "New task" in add_task_calls
    assert "Existing task" not in add_task_calls
    assert "Another existing task" not in add_task_calls

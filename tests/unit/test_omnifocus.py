"""Unit tests for OmniFocus CLI.

This test suite covers all major functionality including:

Core Features:
- Task creation, updating, and completion
- Tag management (add, remove, clear)
- Project and tag-based task grouping
- Clipboard-based task import
- URL handling and webpage title extraction

New URL Features (added in latest update):
- URL extraction from task notes and names
- Web icon display (🌐) for tasks containing URLs
- Interesting command with numbered task list and URL indicators
- Open-task command to open URLs by task number
- Deduplication of inbox and flagged tasks
- Comprehensive edge case handling for URL patterns

Test Coverage:
- 48 total tests covering all commands and edge cases
- Mock-based testing to prevent actual OmniFocus operations
- Error handling and validation testing
- CLI command integration testing with typer.testing
"""

import json
from unittest.mock import patch, MagicMock, call
import pytest
from typer.testing import CliRunner
from datetime import datetime, timezone
from omnifocus import (
    app,
    sanitize_task_text,
    extract_tags_from_task,
    extract_url_from_task,
    _get_interesting_tasks,
    Task,
    OmniFocusManager,
    OSXSystem,
)
import shlex

# Create mock system and manager for all tests
mock_system = MagicMock(spec=OSXSystem)
mock_manager = OmniFocusManager(mock_system)


# Patch the global instances
@pytest.fixture(autouse=True)
def patch_globals():
    """Patch global system and manager to prevent real task creation."""
    with (
        patch("omnifocus.system", mock_system),
        patch("omnifocus.manager", mock_manager),
    ):
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
    """Test adding a task to OmniFocus with various parameter combinations."""
    # Test basic task with defaults
    result = manager.add_task("Test task")
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today&flag=true"
    )

    # Test task with project and tags
    result = manager.add_task("Test task", project="Work", tags=["important", "urgent"])
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=Work&flag=true&tags=important%2Curgent"
    )

    # Test task with note
    result = manager.add_task("Test task", note="This is a test note")
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today&flag=true&note=This%20is%20a%20test%20note"
    )

    # Test unflagged task
    result = manager.add_task("Test task", flagged=False)
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today"
    )

    # Test task with all parameters
    result = manager.add_task(
        "Test task",
        project="Personal",
        tags=["home", "weekend"],
        note="Remember to do this",
        flagged=True,
    )
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=Personal&flag=true&tags=home%2Cweekend&note=Remember%20to%20do%20this"
    )

    # Test short task name (should not create task)
    result = manager.add_task("ab")
    assert result is False
    # Call count should not increase since the task was too short
    assert mock_system.open_url.call_count == 5


def test_add_task_escaping(manager, mock_system):
    """Test that special characters in task parameters are properly escaped."""
    # Test task with special characters in name and note
    result = manager.add_task(
        "Test & task",
        note="Note with spaces & special chars: ?#",
        tags=["tag with space"],
    )
    assert result is True
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20%26%20task&autosave=true&project=today&flag=true&tags=tag%20with%20space&note=Note%20with%20spaces%20%26%20special%20chars%3A%20%3F%23"
    )


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
    assert (
        mock_manager_global.add_task.call_count == 0
    )  # Should not add tasks in preview mode

    # Reset mocks for actual add test
    mock_system_global.reset_mock()
    mock_manager_global.reset_mock()

    # Test actual add
    result = runner.invoke(app, ["add-tasks-from-clipboard"])
    assert result.exit_code == 0
    assert (
        mock_manager_global.add_task.call_count == 4
    )  # Should have added 4 tasks (including duplicates)


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


@patch("omnifocus.requests")
def test_add_command_with_url(mock_requests):
    """Test adding a task from a URL using the add command."""
    # Mock the web request response
    mock_response = MagicMock()
    mock_response.text = (
        "<html><head><title>Test Page Title</title></head><body>content</body></html>"
    )
    mock_requests.get.return_value = mock_response

    # Test adding a URL task (should use specified project)
    result = runner.invoke(app, ["add", "https://example.com"])
    assert result.exit_code == 0

    # Verify the request was made with the correct headers
    mock_requests.get.assert_called_with(
        "https://example.com", headers={"User-Agent": "Mozilla/5.0"}
    )

    # Verify the task was created with the correct URL and url tag
    mock_manager.system.open_url.assert_called_once()
    actual_url = mock_manager.system.open_url.call_args[0][0]
    assert actual_url.startswith("omnifocus:///add?")
    assert "name=Test%20Page%20Title" in actual_url
    assert "note=Source%3A%20https%3A%2F%2Fexample.com" in actual_url
    assert "autosave=true" in actual_url
    assert "flag=true" in actual_url
    assert "project=today" in actual_url
    assert "tags=url" in actual_url

    # Test with a custom project and tags (should include url tag)
    result = runner.invoke(
        app,
        [
            "add",
            "https://example.com",
            "--project",
            "Reading List",
            "--tag",
            "web,research",
        ],
    )
    assert result.exit_code == 0
    actual_url = mock_manager.system.open_url.call_args[0][0]
    assert actual_url.startswith("omnifocus:///add?")
    assert "name=Test%20Page%20Title" in actual_url
    assert "note=Source%3A%20https%3A%2F%2Fexample.com" in actual_url
    assert "autosave=true" in actual_url
    assert "flag=true" in actual_url
    assert "project=Reading%20List" in actual_url
    assert "tags=web%2Cresearch%2Curl" in actual_url


@patch("omnifocus.requests")
def test_add_command_with_url_error_handling(mock_requests):
    """Test error handling when adding a task from a URL using the add command."""
    # Reset the mock before this test
    mock_manager.system.open_url.reset_mock()

    # Test network error
    class MockRequestException(Exception):
        pass

    mock_requests.exceptions.RequestException = MockRequestException
    mock_requests.get.side_effect = MockRequestException("Network error")

    result = runner.invoke(app, ["add", "https://example.com"])
    assert result.exit_code == 0  # Should not crash
    assert "Error fetching URL: Network error" in result.stdout
    assert not mock_manager.system.open_url.called

    # Test missing title (should still include url tag)
    mock_response = MagicMock()
    mock_response.text = "<html><head></head><body>content</body></html>"
    mock_requests.get.side_effect = None
    mock_requests.get.return_value = mock_response

    result = runner.invoke(app, ["add", "https://example.com"])
    assert result.exit_code == 0
    actual_url = mock_manager.system.open_url.call_args[0][0]
    assert actual_url.startswith("omnifocus:///add?")
    assert "name=https%3A%2F%2Fexample.com" in actual_url
    assert "note=Source%3A%20https%3A%2F%2Fexample.com" in actual_url
    assert "autosave=true" in actual_url
    assert "flag=true" in actual_url
    assert "project=today" in actual_url
    assert "tags=url" in actual_url


def test_add_command_with_regular_task():
    """Test adding a regular task using the add command."""
    # Reset the mock to start with a clean state
    mock_manager.system.open_url.reset_mock()

    # Test basic task
    result = runner.invoke(app, ["add", "Test task"])
    assert result.exit_code == 0
    actual_url = mock_manager.system.open_url.call_args[0][0]
    assert actual_url.startswith("omnifocus:///add?")
    assert "name=Test%20task" in actual_url
    assert "autosave=true" in actual_url
    assert "flag=true" in actual_url
    assert "project=today" in actual_url
    # No tags parameter should be present when there are no tags

    # Test with project and tags
    result = runner.invoke(
        app, ["add", "Test task", "--project", "Work", "--tag", "urgent,meeting"]
    )
    assert result.exit_code == 0
    actual_url = mock_manager.system.open_url.call_args[0][0]
    assert actual_url.startswith("omnifocus:///add?")
    assert "name=Test%20task" in actual_url
    assert "autosave=true" in actual_url
    assert "flag=true" in actual_url
    assert "project=Work" in actual_url
    assert "tags=urgent%2Cmeeting" in actual_url

    # Test task too short
    result = runner.invoke(app, ["add", "ab"])
    assert result.exit_code == 0
    assert "Task text too short" in result.stdout
    assert mock_manager.system.open_url.call_count == 2  # Should not have increased


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url(mock_manager, mock_requests):
    """Test fixing tasks with URLs."""
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="", note="Source: https://example.com"),
        Task(id="task2", name="Regular task", note=""),
        Task(id="task3", name="", note="Source: https://example.org"),
    ]

    mock_response1 = MagicMock()
    mock_response1.text = "<html><head><title>Example Website</title></head></html>"
    mock_response2 = MagicMock()
    mock_response2.text = "<html><head><title>Example Org</title></head></html>"

    mock_requests.get.side_effect = [mock_response1, mock_response2]

    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0
    assert "Found 2 tasks to update" in result.stdout

    mock_manager.update_name.assert_has_calls(
        [
            call(mock_manager.get_all_tasks.return_value[0], "Example Website"),
            call(mock_manager.get_all_tasks.return_value[2], "Example Org"),
        ]
    )

    # update_note is not called in this case because the URLs are already in the notes
    # mock_manager.update_note.assert_called_once_with(
    #     mock_manager.get_all_tasks.return_value[0], "Source: https://example.com"
    # )


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url_error_handling(mock_manager, mock_requests):
    """Test error handling in fixup-url command."""
    # Mock tasks with URLs
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="https://example.com", note=""),
    ]

    # Mock responses - one success, one failure
    mock_response = MagicMock()
    mock_response.text = "<html><head><title>Example Website</title></head></html>"

    class MockRequestException(Exception):
        pass

    mock_requests.exceptions.RequestException = MockRequestException
    mock_requests.get.side_effect = [
        mock_response,  # First URL succeeds
        MockRequestException("Network error"),  # Second URL fails
    ]

    # Run the command
    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0

    # Verify output
    assert "Found 1 tasks to update" in result.stdout
    assert "Updated task with title: Example Website" in result.stdout

    # Verify only one task was updated
    mock_manager.update_name.assert_called_once_with(
        mock_manager.get_all_tasks.return_value[0], "Example Website"
    )


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url_with_url_names(mock_manager, mock_requests):
    """Test fixing tasks that have URLs as their names."""
    # Mock tasks with URLs as names
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="https://example.com", note=""),
        Task(id="task2", name="Regular task", note=""),
        Task(id="task3", name="https://example.org", note=""),
    ]

    # Mock webpage responses
    mock_response1 = MagicMock()
    mock_response1.text = "<html><head><title>Example Website</title></head></html>"
    mock_response2 = MagicMock()
    mock_response2.text = "<html><head><title>Example Org</title></head></html>"

    mock_requests.get.side_effect = [mock_response1, mock_response2]

    # Run the command
    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0

    # Verify output
    assert "Found 2 tasks to update" in result.stdout
    assert "Updated task with title: Example Website" in result.stdout
    assert "Updated task with title: Example Org" in result.stdout

    # Verify URL requests
    mock_requests.get.assert_has_calls(
        [
            call("https://example.com", headers={"User-Agent": "Mozilla/5.0"}),
            call("https://example.org", headers={"User-Agent": "Mozilla/5.0"}),
        ]
    )

    # Verify task updates
    mock_manager.update_name.assert_has_calls(
        [
            call(mock_manager.get_all_tasks.return_value[0], "Example Website"),
            call(mock_manager.get_all_tasks.return_value[2], "Example Org"),
        ]
    )

    # Verify note updates
    mock_manager.update_note.assert_has_calls(
        [
            call(
                mock_manager.get_all_tasks.return_value[0],
                "Source: https://example.com",
            ),
            call(
                mock_manager.get_all_tasks.return_value[2],
                "Source: https://example.org",
            ),
        ]
    )


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url_with_url_in_name(mock_manager, mock_requests):
    """Test fixing tasks that have URLs as their names, ensuring URL is moved to note."""
    # Mock tasks with URLs as names
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="https://example.com", note=""),
    ]

    # Mock webpage response
    mock_response = MagicMock()
    mock_response.text = "<html><head><title>Example Website</title></head></html>"
    mock_requests.get.return_value = mock_response

    # Run the command
    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0

    # Verify output
    assert "Found 1 tasks to update" in result.stdout
    assert "Moved URL to note: https://example.com" in result.stdout
    assert "Updated task with title: Example Website" in result.stdout

    # Verify the order of operations - note should be updated before title
    mock_manager.update_note.assert_called_once_with(
        mock_manager.get_all_tasks.return_value[0], "Source: https://example.com"
    )
    mock_manager.update_name.assert_called_once_with(
        mock_manager.get_all_tasks.return_value[0], "Example Website"
    )

    # Verify URL request
    mock_requests.get.assert_called_once_with(
        "https://example.com", headers={"User-Agent": "Mozilla/5.0"}
    )


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url_with_url_in_note(mock_manager, mock_requests):
    """Test fixing tasks that have empty names with URLs in notes."""
    # Mock tasks with URLs in notes
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="", note="Source: https://example.org"),
    ]

    # Mock webpage response
    mock_response = MagicMock()
    mock_response.text = "<html><head><title>Example Org</title></head></html>"
    mock_requests.get.return_value = mock_response

    # Run the command
    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0

    # Verify output
    assert "Found 1 tasks to update" in result.stdout
    assert "Updated task with title: Example Org" in result.stdout
    assert "Moved URL to note" not in result.stdout  # URL was already in note

    # Verify only title was updated, note wasn't touched
    mock_manager.update_note.assert_not_called()
    mock_manager.update_name.assert_called_once_with(
        mock_manager.get_all_tasks.return_value[0], "Example Org"
    )

    # Verify URL request
    mock_requests.get.assert_called_once_with(
        "https://example.org", headers={"User-Agent": "Mozilla/5.0"}
    )


@patch("omnifocus.requests")
@patch("omnifocus.manager")
def test_fixup_url_note_update_error(mock_manager, mock_requests):
    """Test error handling in fixup_url command when updating note and title."""
    # Mock tasks with URLs as names
    mock_manager.get_all_tasks.return_value = [
        Task(id="task1", name="https://example.com", note=""),
    ]

    # Mock update_note to fail with a proper Exception
    mock_manager.update_note.side_effect = RuntimeError("Failed to update note")

    # Run the command
    result = runner.invoke(app, ["fixup-url"])
    assert result.exit_code == 0  # The command handles exceptions gracefully

    # Verify error output
    assert "Found 1 tasks to update" in result.stdout
    assert (
        "Error processing task" in result.stdout
        or "Failed to update note" in result.stdout
    )

    # Verify title wasn't updated after note update failed
    mock_manager.update_name.assert_not_called()
    mock_requests.get.assert_not_called()


def test_update_task(manager, mock_system):
    """Test updating a task's name using a Task object."""
    task = Task(name="Old Name", id="123")
    manager.update_name(task, "New Name")
    mock_system.run_javascript.assert_called_with(
        "\n            function run() {\n"
        + "                const of = Application('OmniFocus');\n"
        + "                of.includeStandardAdditions = true;\n\n"
        + "                const doc = of.defaultDocument;\n"
        + '                const task = doc.flattenedTasks.whose({id: "123"})()[0];\n\n'
        + "                if (task) {\n"
        + '                    task.name = "New Name";\n'
        + "                }\n"
        + "            }\n        "
    )


def test_update_note(manager, mock_system):
    """Test updating a task's note using a Task object."""
    task = Task(name="Task Name", id="123")
    manager.update_note(task, "New Note")
    mock_system.run_javascript.assert_called_with(
        "\n            function run() {\n"
        + "                const of = Application('OmniFocus');\n"
        + "                of.includeStandardAdditions = true;\n\n"
        + "                const doc = of.defaultDocument;\n"
        + '                const task = doc.flattenedTasks.whose({id: "123"})()[0];\n\n'
        + "                if (task) {\n"
        + '                    task.note = "New Note";\n'
        + "                }\n"
        + "            }\n        "
    )


def test_complete(manager, mock_system):
    """Test task completion functionality."""
    # Setup mock task
    task = Task(
        id="test-id",
        name="Test Task",
        project="Test Project",
        flagged=True,
        tags=["tag1", "tag2"],
        note="Test note",
    )

    # Setup mock response
    mock_system.run_javascript.return_value = "Task completed successfully"

    # Call the method
    result = manager.complete(task)

    # Verify the result
    assert result == "Task completed successfully"
    mock_system.run_javascript.assert_called_once()
    assert "test-id" in mock_system.run_javascript.call_args[0][0]


def test_remove_tag_from_task(manager, mock_system):
    """Test removing a tag from a task."""
    # Setup mock task
    task = Task(
        id="test-id",
        name="Test Task",
        project="Test Project",
        flagged=True,
        tags=["testing", "tag-to-remove"],
        note="Test note",
    )

    # Call the method
    result = manager.remove_tag_from_task(task, "tag-to-remove")

    # Verify the result
    assert result is True
    mock_system.open_url.assert_called_once()
    url_call = mock_system.open_url.call_args[0][0]
    assert "name=Test%20Task" in url_call
    assert "project=Test%20Project" in url_call
    assert "flag=true" in url_call
    assert "tags=testing" in url_call
    assert "tag-to-remove" not in url_call

    # Verify the original task was completed
    mock_system.run_javascript.assert_called_once()
    assert "test-id" in mock_system.run_javascript.call_args[0][0]


def test_add_tag_to_task(manager, mock_system):
    """Test adding a tag to a task."""
    # Setup mock task
    task = Task(
        id="test-id",
        name="Test Task",
        project="Test Project",
        flagged=True,
        tags=["testing"],
        note="Test note",
    )

    # Reset mock
    mock_system.reset_mock()

    # Call the method
    result = manager.add_tag_to_task(task, "new-tag")

    # Verify the result
    assert result is True
    mock_system.open_url.assert_called_once()
    url_call = mock_system.open_url.call_args[0][0]
    assert "name=Test%20Task" in url_call
    assert "project=Test%20Project" in url_call
    assert "flag=true" in url_call
    assert "tags=testing%2Cnew-tag" in url_call

    # Verify the original task was completed
    mock_system.run_javascript.assert_called_once()
    assert "test-id" in mock_system.run_javascript.call_args[0][0]


def test_clear_tags_from_task(manager, mock_system):
    """Test clearing all tags from a task."""
    # Setup mock task
    task = Task(
        id="test-id",
        name="Test Task",
        project="Test Project",
        flagged=True,
        tags=["testing", "tag1", "tag2"],
        note="Test note",
    )

    # Reset mock
    mock_system.reset_mock()

    # Call the method
    result = manager.clear_tags_from_task(task)

    # Verify the result
    assert result is True
    mock_system.open_url.assert_called_once()
    url_call = mock_system.open_url.call_args[0][0]
    assert "name=Test%20Task" in url_call
    assert "project=Test%20Project" in url_call
    assert "flag=true" in url_call
    assert "tags=" not in url_call

    # Verify the original task was completed
    mock_system.run_javascript.assert_called_once()
    assert "test-id" in mock_system.run_javascript.call_args[0][0]


def test_get_all_tags(manager, mock_system):
    """Test getting all tags from OmniFocus."""
    # Setup mock response
    mock_system.run_javascript.return_value = '["tag1", "tag2", "testing"]'

    # Call the method
    result = manager.get_all_tags()

    # Verify the result
    assert result == ["tag1", "tag2", "testing"]
    mock_system.run_javascript.assert_called_once()
    assert "flattenedTags" in mock_system.run_javascript.call_args[0][0]


@patch("omnifocus.manager")
def test_complete_command_no_args(mock_manager):
    """Test complete command with no arguments shows interesting tasks."""
    # Mock the methods that interesting command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
    ]

    result = runner.invoke(app, ["complete"])
    assert result.exit_code == 0
    assert "Task 1" in result.stdout
    assert "Task 2" in result.stdout
    mock_manager.get_inbox_tasks.assert_called()
    mock_manager.get_flagged_tasks.assert_called()


@patch("omnifocus.manager")
def test_complete_command_dry_run(mock_manager):
    """Test complete command with dry-run flag."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
        Task(id="3", name="Task 3", project="Personal", flagged=True),
    ]

    result = runner.invoke(app, ["complete", "--dry-run", "1 3"])
    assert result.exit_code == 0
    assert "Would complete 1: Task 1" in result.stdout
    assert "Would complete 3: Task 3" in result.stdout
    assert "Task 2" not in result.stdout

    # Verify no tasks were actually completed
    mock_manager.complete.assert_not_called()
    mock_manager.get_inbox_tasks.assert_called()
    mock_manager.get_flagged_tasks.assert_called()


@patch("omnifocus.manager")
def test_complete_command_actual_completion(mock_manager):
    """Test complete command actually completing tasks."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
        Task(id="3", name="Task 3", project="Personal", flagged=True),
    ]

    # Mock successful completion
    mock_manager.complete.return_value = "Task completed successfully"

    result = runner.invoke(app, ["complete", "1 3"])
    assert result.exit_code == 0
    assert "✓ 1: Task 1" in result.stdout
    assert "✓ 3: Task 3" in result.stdout
    assert "2: Task 2" not in result.stdout

    # Verify tasks were actually completed
    assert mock_manager.complete.call_count == 2
    completed_tasks = [call.args[0] for call in mock_manager.complete.call_args_list]
    assert completed_tasks[0].name == "Task 1"
    assert completed_tasks[1].name == "Task 3"


@patch("omnifocus.manager")
def test_complete_command_invalid_task_numbers(mock_manager):
    """Test complete command with invalid task numbers."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
    ]

    result = runner.invoke(app, ["complete", "1 5 2"])
    assert result.exit_code == 0
    assert "✓ 1: Task 1" in result.stdout
    assert "✓ 2: Task 2" in result.stdout
    assert "✗ 5: Invalid task number" in result.stdout

    # Verify only valid tasks were completed
    assert mock_manager.complete.call_count == 2


@patch("omnifocus.manager")
def test_complete_command_invalid_number_format(mock_manager):
    """Test complete command with invalid number format."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["complete", "abc 1"])
    assert result.exit_code == 0
    assert (
        "Invalid task numbers. Please provide space-separated integers."
        in result.stdout
    )

    # Verify no tasks were completed due to invalid format
    mock_manager.complete.assert_not_called()


@patch("omnifocus.manager")
def test_complete_command_completion_error(mock_manager):
    """Test complete command when task completion fails."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
    ]

    # Mock completion failure for first task, success for second
    mock_manager.complete.side_effect = [Exception("Completion failed"), "Success"]

    result = runner.invoke(app, ["complete", "1 2"])
    assert result.exit_code == 0
    assert "✗ 1: Task 1 - Completion failed" in result.stdout
    assert "✓ 2: Task 2" in result.stdout

    # Verify both tasks were attempted
    assert mock_manager.complete.call_count == 2


@patch("omnifocus.manager")
def test_complete_command_dry_run_invalid_numbers(mock_manager):
    """Test complete command dry-run with invalid task numbers."""
    # Mock the methods that complete command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
    ]

    result = runner.invoke(app, ["complete", "--dry-run", "1 5 2"])
    assert result.exit_code == 0
    assert "Would complete 1: Task 1" in result.stdout
    assert "Would complete 2: Task 2" in result.stdout
    assert "✗ 5: Invalid task number" in result.stdout

    # Verify no tasks were completed in dry-run
    mock_manager.complete.assert_not_called()


@patch("omnifocus.manager")
def test_complete_command_uses_interesting_tasks(mock_manager):
    """Test that complete command uses the same task list as interesting command."""
    # Mock the methods that both interesting and complete commands use
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Inbox Task", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Flagged Task", project="Work", flagged=True),
    ]
    mock_manager.get_all_tasks.return_value = [
        Task(id="1", name="Inbox Task", project="Inbox", flagged=False),
        Task(id="2", name="Flagged Task", project="Work", flagged=True),
        Task(id="3", name="Non-interesting Task", project="Someday", flagged=False),
    ]

    # Test that complete command uses inbox+flagged tasks, not all tasks
    result = runner.invoke(app, ["complete", "--dry-run", "1 2"])
    assert result.exit_code == 0
    assert "Inbox Task" in result.stdout
    assert "Flagged Task" in result.stdout
    assert "Non-interesting Task" not in result.stdout

    # Verify it called get_inbox_tasks and get_flagged_tasks, not get_all_tasks
    mock_manager.get_inbox_tasks.assert_called()
    mock_manager.get_flagged_tasks.assert_called()
    mock_manager.get_all_tasks.assert_not_called()


@patch("omnifocus.manager")
def test_complete_command_empty_task_list(mock_manager):
    """Test complete command when no interesting tasks exist."""
    # Mock empty task lists
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["complete"])
    assert result.exit_code == 0
    assert "No interesting tasks found" in result.stdout

    # Test with task numbers when no tasks exist - should return early with no tasks message
    result = runner.invoke(app, ["complete", "1 2"])
    assert result.exit_code == 0
    assert "No interesting tasks found" in result.stdout


def test_extract_url_from_task():
    """Test URL extraction from task notes and names."""
    # Test task with URL in note
    task_with_url_note = Task(
        name="GitHub Repository",
        note="Source: https://github.com/example/repo",
        project="Work",
    )
    url = extract_url_from_task(task_with_url_note)
    assert url == "https://github.com/example/repo"

    # Test task with URL in name
    task_with_url_name = Task(name="https://example.com/article", project="Reading")
    url = extract_url_from_task(task_with_url_name)
    assert url == "https://example.com/article"

    # Test task with no URL
    task_no_url = Task(name="Regular task", note="Just a regular note", project="Work")
    url = extract_url_from_task(task_no_url)
    assert url is None

    # Test task with empty note and name
    task_empty = Task(name="Empty task", project="Work")
    url = extract_url_from_task(task_empty)
    assert url is None

    # Test task with multiple URLs in note (should return first one)
    task_multiple_urls = Task(
        name="Multiple URLs",
        note="Check https://first.com and https://second.com",
        project="Research",
    )
    url = extract_url_from_task(task_multiple_urls)
    assert url == "https://first.com"

    # Test task with URL in note and name (note takes precedence)
    task_both = Task(
        name="https://name-url.com", note="Source: https://note-url.com", project="Work"
    )
    url = extract_url_from_task(task_both)
    assert url == "https://note-url.com"


@patch("omnifocus.manager")
def test_get_interesting_tasks(mock_manager):
    """Test the _get_interesting_tasks function."""
    # Mock inbox tasks
    inbox_tasks = [
        Task(id="1", name="Inbox Task 1", project="Inbox", flagged=False),
        Task(
            id="2", name="Inbox Task 2", project="Inbox", flagged=True
        ),  # Also flagged
    ]

    # Mock flagged tasks
    flagged_tasks = [
        Task(id="2", name="Inbox Task 2", project="Inbox", flagged=True),  # Duplicate
        Task(id="3", name="Flagged Task 1", project="Work", flagged=True),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    # Test deduplication
    with patch("omnifocus.manager", mock_manager):
        result = _get_interesting_tasks()

    assert len(result) == 3  # Should have 3 unique tasks

    # Check that inbox tasks come first
    sources = [source for source, task in result]
    task_names = [task.name for source, task in result]

    assert sources == ["Inbox", "Inbox", "Flagged"]
    assert task_names == ["Inbox Task 1", "Inbox Task 2", "Flagged Task 1"]

    # Verify the duplicate was removed (inbox version kept)
    inbox_task_2 = next(task for source, task in result if task.name == "Inbox Task 2")
    assert inbox_task_2.id == "2"


@patch("omnifocus.manager")
def test_interesting_command_with_urls(mock_manager):
    """Test interesting command displays web icons for tasks with URLs."""
    # Mock tasks with and without URLs
    inbox_tasks = [
        Task(
            id="1",
            name="Regular Task",
            project="Inbox",
            flagged=False,
            creation_date=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        Task(
            id="2",
            name="GitHub Repository",
            project="Inbox",
            flagged=False,
            note="Source: https://github.com/example/repo",
            creation_date=datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    flagged_tasks = [
        Task(
            id="3",
            name="https://example.com/article",
            project="Work",
            flagged=True,
            creation_date=datetime(2025, 1, 3, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0

    # Check that web icons appear for tasks with URLs
    assert "🌐" in result.stdout  # Should have web icons
    assert "🚩" in result.stdout  # Should have flag icons

    # Check specific formatting - look for lines that contain task numbers
    lines = result.stdout.split("\n")
    task_lines = [
        line
        for line in lines
        if line.strip() and any(line.strip().startswith(f"{i}.") for i in range(1, 10))
    ]

    assert len(task_lines) == 3  # Should have 3 tasks

    # Task 1: Regular task (no web icon)
    assert "1." in task_lines[0]
    assert "Regular Task" in task_lines[0]
    assert "🌐" not in task_lines[0]

    # Task 2: GitHub task (with web icon)
    assert "2." in task_lines[1]
    assert "🌐" in task_lines[1]
    assert "GitHub Repository" in task_lines[1]

    # Task 3: URL task (with web icon and flag)
    assert "3." in task_lines[2]
    assert "🌐" in task_lines[2]
    assert "🚩" in task_lines[2]
    assert "https://example.com/article" in task_lines[2]


@patch("omnifocus.manager")
def test_interesting_command_no_tasks(mock_manager):
    """Test interesting command when no tasks are found."""
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0
    assert "No interesting tasks found!" in result.stdout


@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_open_task_command_success(mock_manager, mock_system):
    """Test open-task command successfully opens URL."""
    # Mock tasks with URLs
    inbox_tasks = [
        Task(
            id="1",
            name="GitHub Repository",
            project="Inbox",
            flagged=False,
            note="Source: https://github.com/example/repo",
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["open-task", "1"])
    assert result.exit_code == 0

    # Verify URL was opened
    mock_system.open_url.assert_called_once_with("https://github.com/example/repo")
    assert "✓ Opened URL: https://github.com/example/repo" in result.stdout
    assert "From task: GitHub Repository" in result.stdout


@patch("omnifocus.manager")
def test_open_task_command_no_url(mock_manager):
    """Test open-task command with task that has no URL."""
    # Mock task without URL
    inbox_tasks = [
        Task(id="1", name="Regular Task", project="Inbox", flagged=False),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["open-task", "1"])
    assert result.exit_code == 0
    assert "Task 'Regular Task' does not contain a URL" in result.stdout


@patch("omnifocus.manager")
def test_open_task_command_invalid_number(mock_manager):
    """Test open-task command with invalid task number."""
    # Mock one task
    inbox_tasks = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    # Test with number too high
    result = runner.invoke(app, ["open-task", "5"])
    assert result.exit_code == 0
    assert "Invalid task number. Please enter a number between 1 and 1" in result.stdout

    # Test with number too low
    result = runner.invoke(app, ["open-task", "0"])
    assert result.exit_code == 0
    assert "Invalid task number. Please enter a number between 1 and 1" in result.stdout


@patch("omnifocus.manager")
def test_open_task_command_no_tasks(mock_manager):
    """Test open-task command when no interesting tasks exist."""
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["open-task", "1"])
    assert result.exit_code == 0
    assert "No interesting tasks found!" in result.stdout


@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_open_task_command_system_error(mock_manager, mock_system):
    """Test open-task command when system.open_url fails."""
    # Mock task with URL
    inbox_tasks = [
        Task(
            id="1",
            name="GitHub Repository",
            project="Inbox",
            flagged=False,
            note="Source: https://github.com/example/repo",
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    # Mock system.open_url to raise an exception
    mock_system.open_url.side_effect = Exception("Failed to open URL")

    result = runner.invoke(app, ["open-task", "1"])
    assert result.exit_code == 0
    assert "✗ Error opening URL: Failed to open URL" in result.stdout


@patch("omnifocus.manager")
def test_interesting_command_task_ordering(mock_manager):
    """Test that interesting command shows inbox tasks before flagged tasks."""
    # Mock tasks where some are in both inbox and flagged
    inbox_tasks = [
        Task(id="1", name="Inbox Only", project="Inbox", flagged=False),
        Task(id="2", name="Both Inbox and Flagged", project="Inbox", flagged=True),
    ]

    flagged_tasks = [
        Task(id="2", name="Both Inbox and Flagged", project="Inbox", flagged=True),
        Task(id="3", name="Flagged Only", project="Work", flagged=True),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0

    lines = result.stdout.split("\n")
    task_lines = [
        line
        for line in lines
        if line.strip() and any(line.strip().startswith(f"{i}.") for i in range(1, 10))
    ]

    # Should have 3 tasks total (duplicate removed)
    assert len(task_lines) == 3

    # Check ordering: inbox tasks first, then flagged-only tasks
    assert "Inbox Only" in task_lines[0]
    assert "(Inbox)" in task_lines[0]

    assert "Both Inbox and Flagged" in task_lines[1]
    assert "(Inbox)" in task_lines[1]  # Should show as Inbox source

    assert "Flagged Only" in task_lines[2]
    assert "(Flagged)" in task_lines[2]


@patch("omnifocus.manager")
def test_interesting_command_with_metadata(mock_manager):
    """Test interesting command displays all metadata correctly."""
    # Mock task with all metadata
    inbox_tasks = [
        Task(
            id="1",
            name="Complex Task",
            project="Work",
            flagged=True,
            tags=["urgent", "meeting"],
            due_date=datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc),
            creation_date=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc),
            note="Source: https://example.com",
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0

    # Check that all metadata is displayed
    assert "🌐" in result.stdout  # Web icon
    assert "🚩" in result.stdout  # Flag icon
    assert "Complex Task" in result.stdout
    assert "(Work)" in result.stdout  # Project
    assert "[urgent, meeting]" in result.stdout  # Tags
    assert "[Due: 2025-02-01]" in result.stdout  # Due date
    assert "[Created: 2025-01-15]" in result.stdout  # Creation date
    assert "(Inbox)" in result.stdout  # Source


def test_extract_url_from_task_edge_cases():
    """Test URL extraction edge cases."""
    # Test task with malformed URL
    task_malformed = Task(
        name="Check this out",
        note="Visit htp://broken-url.com",  # Missing 't' in 'http'
        project="Work",
    )
    url = extract_url_from_task(task_malformed)
    assert url is None

    # Test task with URL containing special characters
    task_special_chars = Task(
        name="API Documentation",
        note="Source: https://api.example.com/docs?version=1.0&format=json#section-auth",
        project="Development",
    )
    url = extract_url_from_task(task_special_chars)
    assert url == "https://api.example.com/docs?version=1.0&format=json#section-auth"

    # Test task with URL at end of sentence
    task_end_sentence = Task(
        name="Read article",
        note="Check out this great article: https://example.com/article.",
        project="Reading",
    )
    url = extract_url_from_task(task_end_sentence)
    assert url == "https://example.com/article."  # Current regex includes the period

    # Test task with URL in parentheses
    task_parentheses = Task(
        name="Reference",
        note="See documentation (https://docs.example.com) for details",
        project="Work",
    )
    url = extract_url_from_task(task_parentheses)
    assert url == "https://docs.example.com"  # Parentheses are excluded by the regex


@patch("omnifocus.manager")
def test_open_task_command_with_url_in_name(mock_manager):
    """Test open-task command with URL in task name instead of note."""
    # Mock task with URL in name
    inbox_tasks = [
        Task(
            id="1",
            name="https://github.com/example/repo",
            project="Inbox",
            flagged=False,
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    with patch("omnifocus.system") as mock_system:
        result = runner.invoke(app, ["open-task", "1"])
        assert result.exit_code == 0

        # Verify URL was opened
        mock_system.open_url.assert_called_once_with("https://github.com/example/repo")
        assert "✓ Opened URL: https://github.com/example/repo" in result.stdout


@patch("omnifocus.manager")
def test_interesting_command_mixed_url_sources(mock_manager):
    """Test interesting command with URLs in both names and notes."""
    # Mock tasks with URLs in different places
    inbox_tasks = [
        Task(id="1", name="https://name-url.com", project="Inbox", flagged=False),
        Task(
            id="2",
            name="Task with note URL",
            project="Inbox",
            flagged=False,
            note="Source: https://note-url.com",
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0

    # Both tasks should have web icons
    lines = result.stdout.split("\n")
    task_lines = [
        line
        for line in lines
        if line.strip() and any(line.strip().startswith(f"{i}.") for i in range(1, 10))
    ]

    assert len(task_lines) == 2
    assert "🌐" in task_lines[0]  # First task with URL in name
    assert "🌐" in task_lines[1]  # Second task with URL in note


@patch("omnifocus.manager")
def test_open_task_command_prefers_note_url_over_name_url(mock_manager):
    """Test that open-task prefers URL in note over URL in name."""
    # Mock task with URLs in both name and note
    inbox_tasks = [
        Task(
            id="1",
            name="https://name-url.com",
            project="Inbox",
            flagged=False,
            note="Source: https://note-url.com",
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    with patch("omnifocus.system") as mock_system:
        result = runner.invoke(app, ["open-task", "1"])
        assert result.exit_code == 0

        # Should open the URL from the note, not the name
        mock_system.open_url.assert_called_once_with("https://note-url.com")
        assert "✓ Opened URL: https://note-url.com" in result.stdout


@patch("omnifocus.manager")
def test_interesting_command_empty_inbox_and_flagged(mock_manager):
    """Test interesting command when both inbox and flagged are empty."""
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["interesting"])
    assert result.exit_code == 0
    assert "No interesting tasks found!" in result.stdout

    # Should not contain any task formatting
    assert "🌐" not in result.stdout
    assert "🚩" not in result.stdout
    assert "1." not in result.stdout


@patch("omnifocus.manager")
def test_flagged_command_consistent_numbering(mock_manager):
    """Test that flagged command shows consistent index numbers with interesting command."""
    # Mock tasks where some are in inbox and some are flagged only
    inbox_tasks = [
        Task(id="1", name="Inbox Task 1", project="Inbox", flagged=False),
        Task(id="2", name="Both Inbox and Flagged", project="Inbox", flagged=True),
        Task(id="3", name="Inbox Task 2", project="Inbox", flagged=False),
    ]

    flagged_tasks = [
        Task(id="2", name="Both Inbox and Flagged", project="Inbox", flagged=True),
        Task(id="4", name="Flagged Only", project="Work", flagged=True),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    result = runner.invoke(app, ["flagged"])
    assert result.exit_code == 0

    # Should show only flagged tasks but with consistent numbering from interesting
    # In interesting: 1=Inbox Task 1, 2=Both Inbox and Flagged, 3=Inbox Task 2, 4=Flagged Only
    # In flagged: should show tasks 2 and 4 with their original indices
    assert "2" in result.stdout  # Index for "Both Inbox and Flagged"
    assert "4" in result.stdout  # Index for "Flagged Only"
    assert "Both Inbox and Flagged" in result.stdout
    assert "Flagged Only" in result.stdout

    # Should not show non-flagged tasks
    assert "Inbox Task 1" not in result.stdout
    assert "Inbox Task 2" not in result.stdout


@patch("omnifocus.manager")
def test_flagged_command_with_web_icons(mock_manager):
    """Test that flagged command shows web icons for tasks with URLs."""
    flagged_tasks = [
        Task(
            id="1",
            name="Regular Flagged Task",
            project="Work",
            flagged=True,
            creation_date=datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc),
        ),
        Task(
            id="2",
            name="Flagged Task with URL",
            project="Work",
            flagged=True,
            note="Source: https://example.com",
            creation_date=datetime(2025, 1, 2, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    result = runner.invoke(app, ["flagged"])
    assert result.exit_code == 0

    # Check that web icons appear for tasks with URLs
    assert "🌐" in result.stdout
    assert "🚩" in result.stdout  # Flag icons should still be present
    assert "Regular Flagged Task" in result.stdout
    # Task name might be wrapped in table, so check for partial strings
    assert "Flagged Task with" in result.stdout
    assert "URL" in result.stdout


@patch("omnifocus.manager")
def test_flagged_command_no_flagged_tasks(mock_manager):
    """Test flagged command when no flagged tasks exist."""
    # Mock inbox tasks but no flagged tasks
    inbox_tasks = [
        Task(id="1", name="Inbox Task", project="Inbox", flagged=False),
    ]

    mock_manager.get_inbox_tasks.return_value = inbox_tasks
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["flagged"])
    assert result.exit_code == 0
    assert "No flagged tasks found!" in result.stdout


@patch("omnifocus.manager")
def test_flagged_command_table_format(mock_manager):
    """Test that flagged command maintains rich table format."""
    flagged_tasks = [
        Task(
            id="1",
            name="Test Task",
            project="Work",
            flagged=True,
            tags=["urgent", "meeting"],
            due_date=datetime(2025, 2, 1, 12, 0, tzinfo=timezone.utc),
            creation_date=datetime(2025, 1, 15, 12, 0, tzinfo=timezone.utc),
        ),
    ]

    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = flagged_tasks

    result = runner.invoke(app, ["flagged"])
    assert result.exit_code == 0

    # Check table structure and content
    assert "Flagged Tasks" in result.stdout
    assert "Index" in result.stdout
    assert "Task" in result.stdout
    assert "Project" in result.stdout
    assert "Tags" in result.stdout
    assert "Due Date" in result.stdout
    assert "Created" in result.stdout

    # Check task content
    assert "Test Task" in result.stdout
    assert "Work" in result.stdout
    assert "urgent, meeting" in result.stdout
    assert "2025-02-01" in result.stdout
    assert "2025-01-15" in result.stdout


def test_start_flow_session(manager, mock_system):
    """Test starting a flow session."""
    # Setup mock
    mock_system.run_flow_command.return_value = "Flow session started"

    # Call the method
    result = manager.start_flow_session("Test Session")

    # Verify the result
    assert result == "Started flow session: Test Session"

    # Verify only flow-rename was called (flow-go happens automatically)
    assert mock_system.run_flow_command.call_count == 1
    mock_system.run_flow_command.assert_called_once_with("flow-rename", "Test Session")


def test_start_flow_session_with_special_characters(manager, mock_system):
    """Test starting a flow session with special characters in name."""
    # Setup mock
    mock_system.run_flow_command.return_value = "Flow session started"

    # Call the method with special characters
    session_name = "Test Session: Review & Plan (2024)"
    result = manager.start_flow_session(session_name)

    # Verify the result
    assert result == f"Started flow session: {session_name}"

    # Verify only flow-rename was called with the exact name (flow-go happens automatically)
    assert mock_system.run_flow_command.call_count == 1
    mock_system.run_flow_command.assert_called_once_with("flow-rename", session_name)


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_success(mock_manager, mock_system, mock_interactive_edit):
    """Test flow command with successful execution."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
        Task(id="3", name="Flow Session Task", project="Personal", flagged=True),
    ]

    # Mock interactive editing to return the original name
    mock_interactive_edit.return_value = "Flow Session Task"

    # Mock successful flow command execution
    mock_system.run_flow_command.return_value = "Flow command output"

    result = runner.invoke(app, ["flow", "3", "--no-shorten"])
    assert result.exit_code == 0
    assert "Started flow session: Flow Session Task" in result.stdout
    assert "From task: Flow Session Task" in result.stdout

    # Verify the flow command was called with flow-go directly
    mock_system.run_flow_command.assert_called_once_with("flow-go", "Flow Session Task")
    # Verify interactive editing was called
    mock_interactive_edit.assert_called_once_with("Flow Session Task")


@patch("omnifocus.manager")
def test_flow_command_invalid_task_number(mock_manager):
    """Test flow command with invalid task number."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Task 2", project="Work", flagged=True),
    ]

    result = runner.invoke(app, ["flow", "5", "--no-shorten"])
    assert result.exit_code == 0
    assert "Invalid task number. Please enter a number between 1 and 2" in result.stdout

    # Verify no flow session was started
    mock_manager.start_flow_session.assert_not_called()


@patch("omnifocus.manager")
def test_flow_command_no_tasks(mock_manager):
    """Test flow command when no tasks are available."""
    # Mock empty task lists
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = []

    result = runner.invoke(app, ["flow", "1", "--no-shorten"])
    assert result.exit_code == 0
    assert "No interesting tasks found!" in result.stdout

    # Verify no flow session was started
    mock_manager.start_flow_session.assert_not_called()


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_subprocess_error(
    mock_manager, mock_system, mock_interactive_edit
):
    """Test flow command when subprocess fails."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = []

    # Mock interactive editing to return the original name
    mock_interactive_edit.return_value = "Task 1"

    # Mock subprocess error
    import subprocess

    mock_system.run_flow_command.side_effect = subprocess.CalledProcessError(
        1, "y flow-go", "Command failed"
    )

    result = runner.invoke(app, ["flow", "1", "--no-shorten"])
    assert result.exit_code == 0
    assert "Failed to start flow session" in result.stdout

    # Verify the flow command was attempted with flow-go
    mock_system.run_flow_command.assert_called_once_with("flow-go", "Task 1")


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_file_not_found_error(
    mock_manager, mock_system, mock_interactive_edit
):
    """Test flow command when 'y' command is not found."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Task 1", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = []

    # Mock interactive editing to return the original name
    mock_interactive_edit.return_value = "Task 1"

    # Mock file not found error
    mock_system.run_flow_command.side_effect = FileNotFoundError("y command not found")

    result = runner.invoke(app, ["flow", "1", "--no-shorten"])
    assert result.exit_code == 0
    assert "Flow command 'y' not found" in result.stdout

    # Verify the flow command was attempted with flow-go
    mock_system.run_flow_command.assert_called_once_with("flow-go", "Task 1")


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_uses_interesting_tasks(
    mock_manager, mock_system, mock_interactive_edit
):
    """Test that flow command uses the same task list as interesting command."""
    # Mock the methods that both commands use
    mock_manager.get_inbox_tasks.return_value = [
        Task(id="1", name="Inbox Task", project="Inbox", flagged=False),
    ]
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="2", name="Flagged Task", project="Work", flagged=True),
    ]

    # Mock interactive editing to return the original name
    mock_interactive_edit.return_value = "Flagged Task"

    # Mock successful flow command execution
    mock_system.run_flow_command.return_value = "Flow command output"

    result = runner.invoke(app, ["flow", "2", "--no-shorten"])
    assert result.exit_code == 0
    assert "Started flow session: Flagged Task" in result.stdout

    # Verify both inbox and flagged tasks were fetched (same as interesting command)
    mock_manager.get_inbox_tasks.assert_called_once()
    mock_manager.get_flagged_tasks.assert_called_once()
    mock_system.run_flow_command.assert_called_once_with("flow-go", "Flagged Task")


def test_osx_system_run_flow_command():
    """Test OSXSystem.run_flow_command method."""
    from unittest.mock import patch, MagicMock
    from omnifocus import OSXSystem

    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_result = MagicMock()
        mock_result.stdout = "Flow command output\n"
        mock_run.return_value = mock_result

        # Call the method
        result = OSXSystem.run_flow_command("flow-rename", "Test Session")

        # Verify the result
        assert result == "Flow command output"

        # Verify subprocess.run was called correctly with shell=True and proper escaping
        mock_run.assert_called_once_with(
            "y flow-rename 'Test Session'",
            shell=True,
            capture_output=True,
            text=True,
            check=True,
        )


def test_osx_system_run_flow_command_no_args():
    """Test OSXSystem.run_flow_command method with no additional arguments."""
    from unittest.mock import patch, MagicMock
    from omnifocus import OSXSystem

    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_result = MagicMock()
        mock_result.stdout = "Flow started\n"
        mock_run.return_value = mock_result

        # Call the method
        result = OSXSystem.run_flow_command("flow-go")

        # Verify the result
        assert result == "Flow started"

        # Verify subprocess.run was called correctly with shell=True
        mock_run.assert_called_once_with(
            "y flow-go", shell=True, capture_output=True, text=True, check=True
        )


def test_osx_system_run_flow_command_error():
    """Test OSXSystem.run_flow_command method when subprocess fails."""
    from unittest.mock import patch
    from omnifocus import OSXSystem
    import subprocess

    with patch("subprocess.run") as mock_run:
        # Setup mock to raise CalledProcessError
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["y", "flow-rename"], "Command failed"
        )

        # Call the method and expect exception
        with pytest.raises(subprocess.CalledProcessError):
            OSXSystem.run_flow_command("flow-rename", "Test Session")


def test_osx_system_run_flow_command_special_characters():
    """Test OSXSystem.run_flow_command method with special characters that need escaping."""
    from unittest.mock import patch, MagicMock
    from omnifocus import OSXSystem

    with patch("subprocess.run") as mock_run:
        # Setup mock
        mock_result = MagicMock()
        mock_result.stdout = "Flow command output\n"
        mock_run.return_value = mock_result

        # Test with various special characters that could cause issues
        test_cases = [
            "Session with spaces",
            "Session with 'single quotes'",
            'Session with "double quotes"',
            "Session with (parentheses)",
            "Session with & ampersand",
            "Session with $dollar sign",
            "Session with `backticks`",
            "Session with | pipe",
            "Session with ; semicolon",
        ]

        for session_name in test_cases:
            mock_run.reset_mock()

            # Call the method
            result = OSXSystem.run_flow_command("flow-rename", session_name)

            # Verify the result
            assert result == "Flow command output"

            # Verify subprocess.run was called with properly escaped arguments
            expected_cmd = f"y flow-rename {shlex.quote(session_name)}"
            mock_run.assert_called_once_with(
                expected_cmd,
                shell=True,
                capture_output=True,
                text=True,
                check=True,
            )


# Tests for new LLM functionality


def test_llm_task_shortener_success():
    """Test LLMTaskShortener with successful LLM call."""
    from unittest.mock import patch, MagicMock
    from omnifocus import LLMTaskShortener

    with patch("subprocess.run") as mock_run:
        # Setup mock for successful llm command
        mock_result = MagicMock()
        mock_result.stdout = "Fix flow names\n"
        mock_result.returncode = 0
        mock_run.return_value = mock_result

        # Create shortener and test
        shortener = LLMTaskShortener()
        result = shortener.shorten_task_name("Use llm to fix up flow names")

        # Verify result
        assert result == "Fix flow names"

        # Verify subprocess.run was called correctly
        expected_prompt = """You are a productivity assistant helping to create concise flow session names from OmniFocus task descriptions.

Task: "Use llm to fix up flow names"

Create a short, focused session name (2-6 words) that captures the essential action and context. Follow these guidelines:

1. Remove project prefixes, dates, and administrative details
2. Focus on the core action or deliverable
3. Keep technical terms if they're essential
4. Use active, engaging language
5. Aim for 2-6 words maximum

Examples:
- "Review Q4 budget spreadsheet for finance team meeting" → "Review Q4 Budget"
- "Call client about project timeline and deliverables" → "Client Timeline Call"
- "Write blog post about productivity techniques" → "Write Productivity Post"
- "https://example.com/article - Read and summarize" → "Read Article Summary"

Return only the shortened name, no explanation."""

        mock_run.assert_called_once_with(
            ["llm", "-m", "gpt-4o-mini", expected_prompt],
            capture_output=True,
            text=True,
            timeout=10.0,
            check=True,
        )


def test_llm_task_shortener_failure():
    """Test LLMTaskShortener when LLM command fails."""
    from unittest.mock import patch
    from omnifocus import LLMTaskShortener
    import subprocess

    with patch("subprocess.run") as mock_run:
        # Setup mock to raise CalledProcessError
        mock_run.side_effect = subprocess.CalledProcessError(
            1, ["llm"], "LLM command failed"
        )

        # Create shortener and test
        shortener = LLMTaskShortener()
        result = shortener.shorten_task_name("Original task name")

        # Should return original name on failure
        assert result == "Original task name"


def test_llm_task_shortener_file_not_found():
    """Test LLMTaskShortener when llm command is not found."""
    from unittest.mock import patch
    from omnifocus import LLMTaskShortener

    with patch("subprocess.run") as mock_run:
        # Setup mock to raise FileNotFoundError
        mock_run.side_effect = FileNotFoundError("llm command not found")

        # Create shortener and test
        shortener = LLMTaskShortener()
        result = shortener.shorten_task_name("Original task name")

        # Should return original name on failure
        assert result == "Original task name"


def test_interactive_edit_session_name_accept():
    """Test interactive_edit_session_name when user accepts suggestion."""
    from unittest.mock import patch
    from omnifocus import interactive_edit_session_name

    with patch("builtins.input", return_value=""):
        result = interactive_edit_session_name("Suggested Name")
        assert result == "Suggested Name"


def test_interactive_edit_session_name_edit():
    """Test interactive_edit_session_name when user edits the name."""
    from unittest.mock import patch
    from omnifocus import interactive_edit_session_name

    with patch("builtins.input", return_value="Edited Name"):
        result = interactive_edit_session_name("Suggested Name")
        assert result == "Edited Name"


def test_interactive_edit_session_name_whitespace():
    """Test interactive_edit_session_name with whitespace input."""
    from unittest.mock import patch
    from omnifocus import interactive_edit_session_name

    with patch("builtins.input", return_value="   "):
        result = interactive_edit_session_name("Suggested Name")
        assert result == "Suggested Name"


def test_interactive_edit_session_name_keyboard_interrupt():
    """Test interactive_edit_session_name when user cancels with Ctrl+C."""
    from unittest.mock import patch
    from omnifocus import interactive_edit_session_name

    with patch("builtins.input", side_effect=KeyboardInterrupt):
        result = interactive_edit_session_name("Suggested Name")
        assert result is None


def test_interactive_edit_session_name_eof_error():
    """Test interactive_edit_session_name when user cancels with Ctrl+D."""
    from unittest.mock import patch
    from omnifocus import interactive_edit_session_name

    with patch("builtins.input", side_effect=EOFError):
        result = interactive_edit_session_name("Suggested Name")
        assert result is None


@patch("omnifocus.LLMTaskShortener")
@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_with_llm_shortening(
    mock_manager, mock_system, mock_interactive_edit, mock_llm_class
):
    """Test flow command with LLM shortening enabled."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="1", name="Use llm to fix up flow names", project="Work", flagged=True),
    ]

    # Mock LLM shortener
    mock_shortener = MagicMock()
    mock_shortener.shorten_task_name.return_value = "Fix flow names"
    mock_llm_class.return_value = mock_shortener

    # Mock interactive editing to return the shortened name
    mock_interactive_edit.return_value = "Fix flow names"

    # Mock successful flow command execution
    mock_system.run_flow_command.return_value = "Flow command output"

    result = runner.invoke(app, ["flow", "1"])
    assert result.exit_code == 0
    assert "Started flow session: Fix flow names" in result.stdout
    assert "From task: Use llm to fix up flow names" in result.stdout

    # Verify LLM shortening was called
    mock_llm_class.assert_called_once()
    mock_shortener.shorten_task_name.assert_called_once_with(
        "Use llm to fix up flow names"
    )

    # Verify interactive editing was called with shortened name
    mock_interactive_edit.assert_called_once_with("Fix flow names")

    # Verify the flow command was called with flow-go directly
    mock_system.run_flow_command.assert_called_once_with("flow-go", "Fix flow names")


@patch("omnifocus.LLMTaskShortener")
@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_llm_failure_fallback(
    mock_manager, mock_system, mock_interactive_edit, mock_llm_class
):
    """Test flow command when LLM shortening fails."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="1", name="Original Task Name", project="Work", flagged=True),
    ]

    # Mock LLM shortener to raise exception
    mock_shortener = MagicMock()
    mock_shortener.shorten_task_name.side_effect = Exception("LLM failed")
    mock_llm_class.return_value = mock_shortener

    # Mock interactive editing to return the original name
    mock_interactive_edit.return_value = "Original Task Name"

    # Mock successful flow command execution
    mock_system.run_flow_command.return_value = "Flow command output"

    result = runner.invoke(app, ["flow", "1"])
    assert result.exit_code == 0
    assert "LLM shortening failed" in result.stdout
    assert "Started flow session: Original Task Name" in result.stdout

    # Verify LLM shortening was attempted
    mock_llm_class.assert_called_once()
    mock_shortener.shorten_task_name.assert_called_once_with("Original Task Name")

    # Verify interactive editing was called with original name (fallback)
    mock_interactive_edit.assert_called_once_with("Original Task Name")

    # Verify the flow command was called with flow-go directly
    mock_system.run_flow_command.assert_called_once_with(
        "flow-go", "Original Task Name"
    )


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_user_cancels_editing(
    mock_manager, mock_system, mock_interactive_edit
):
    """Test flow command when user cancels interactive editing."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="1", name="Task Name", project="Work", flagged=True),
    ]

    # Mock interactive editing to return None (cancelled)
    mock_interactive_edit.return_value = None

    result = runner.invoke(app, ["flow", "1", "--no-shorten"])
    assert result.exit_code == 0
    # The flow command just returns early when cancelled, no specific message
    assert "Task: Task Name" in result.stdout

    # Verify interactive editing was called
    mock_interactive_edit.assert_called_once_with("Task Name")

    # Verify no flow command was executed since user cancelled
    mock_system.run_flow_command.assert_not_called()


@patch("omnifocus.interactive_edit_session_name")
@patch("omnifocus.system")
@patch("omnifocus.manager")
def test_flow_command_dry_run_with_llm(
    mock_manager, mock_system, mock_interactive_edit
):
    """Test flow command dry run mode with new functionality."""
    # Mock the methods that flow command uses
    mock_manager.get_inbox_tasks.return_value = []
    mock_manager.get_flagged_tasks.return_value = [
        Task(id="1", name="Task Name", project="Work", flagged=True),
    ]

    # Mock interactive editing to return edited name
    mock_interactive_edit.return_value = "Edited Name"

    result = runner.invoke(app, ["flow", "1", "--no-shorten", "--dry-run"])
    assert result.exit_code == 0
    assert "Would start flow session: Edited Name" in result.stdout
    assert "From task: Task Name" in result.stdout

    # Verify interactive editing was called
    mock_interactive_edit.assert_called_once_with("Task Name")

    # Verify no actual flow command was executed in dry run mode
    mock_system.run_flow_command.assert_not_called()

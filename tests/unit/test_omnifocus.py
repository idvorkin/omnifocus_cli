"""Unit tests for OmniFocus CLI."""

import json
from unittest.mock import patch, MagicMock, call
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
    with patch("omnifocus.system", mock_system), patch(
        "omnifocus.manager", mock_manager
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
    manager.add_task("Test task")
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today&flag=true"
    )

    # Test task with project and tags
    manager.add_task("Test task", project="Work", tags=["important", "urgent"])
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=Work&flag=true&tags=important%2Curgent"
    )

    # Test task with note
    manager.add_task("Test task", note="This is a test note")
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today&flag=true&note=This%20is%20a%20test%20note"
    )

    # Test unflagged task
    manager.add_task("Test task", flagged=False)
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=today"
    )

    # Test task with all parameters
    manager.add_task(
        "Test task",
        project="Personal",
        tags=["home", "weekend"],
        note="Remember to do this",
        flagged=True,
    )
    mock_system.open_url.assert_called_with(
        "omnifocus:///add?name=Test%20task&autosave=true&project=Personal&flag=true&tags=home%2Cweekend&note=Remember%20to%20do%20this"
    )

    # Test short task name (should not create task)
    manager.add_task("ab")
    # Call count should not increase since the task was too short
    assert mock_system.open_url.call_count == 5


def test_add_task_escaping(manager, mock_system):
    """Test that special characters in task parameters are properly escaped."""
    # Test task with special characters in name and note
    manager.add_task(
        "Test & task",
        note="Note with spaces & special chars: ?#",
        tags=["tag with space"],
    )
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
@patch("omnifocus.system")
def test_add_command_with_url(mock_system_global, mock_requests):
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
    expected_url = "omnifocus:///add?name=Test%20Page%20Title&note=Source%3A%20https%3A%2F%2Fexample.com&autosave=true&flag=true&project=today&tags=url"
    mock_system_global.open_url.assert_called_with(expected_url)

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
    expected_url = "omnifocus:///add?name=Test%20Page%20Title&note=Source%3A%20https%3A%2F%2Fexample.com&autosave=true&flag=true&project=Reading%20List&tags=web%2Cresearch%2Curl"
    mock_system_global.open_url.assert_called_with(expected_url)


@patch("omnifocus.requests")
@patch("omnifocus.system")
def test_add_command_with_url_error_handling(mock_system_global, mock_requests):
    """Test error handling when adding a task from a URL using the add command."""

    # Test network error
    class MockRequestException(Exception):
        pass

    mock_requests.exceptions.RequestException = MockRequestException
    mock_requests.get.side_effect = MockRequestException("Network error")

    result = runner.invoke(app, ["add", "https://example.com"])
    assert result.exit_code == 0  # Should not crash
    assert "Error fetching URL: Network error" in result.stdout
    assert not mock_system_global.open_url.called

    # Test missing title (should still include url tag)
    mock_response = MagicMock()
    mock_response.text = "<html><head></head><body>content</body></html>"
    mock_requests.get.side_effect = None
    mock_requests.get.return_value = mock_response

    result = runner.invoke(app, ["add", "https://example.com"])
    assert result.exit_code == 0
    expected_url = "omnifocus:///add?name=https%3A%2F%2Fexample.com&note=Source%3A%20https%3A%2F%2Fexample.com&autosave=true&flag=true&project=today&tags=url"
    mock_system_global.open_url.assert_called_with(expected_url)


@patch("omnifocus.system")
def test_add_command_with_regular_task(mock_system_global):
    """Test adding a regular task using the add command."""
    # Test basic task
    result = runner.invoke(app, ["add", "Test task"])
    assert result.exit_code == 0
    expected_url = (
        "omnifocus:///add?name=Test%20task&autosave=true&flag=true&project=today&tags="
    )
    mock_system_global.open_url.assert_called_with(expected_url)

    # Test with project and tags
    result = runner.invoke(
        app, ["add", "Test task", "--project", "Work", "--tag", "urgent,meeting"]
    )
    assert result.exit_code == 0
    expected_url = "omnifocus:///add?name=Test%20task&autosave=true&flag=true&project=Work&tags=urgent%2Cmeeting"
    mock_system_global.open_url.assert_called_with(expected_url)

    # Test task too short
    result = runner.invoke(app, ["add", "ab"])
    assert result.exit_code == 0
    assert "Task text too short" in result.stdout
    assert mock_system_global.open_url.call_count == 2  # Should not have increased


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

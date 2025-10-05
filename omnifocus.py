#!uv run
# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "typer[all]",
#     "icecream",
#     "pyperclip",
#     "typing-extensions",
#     "pydantic",
#     "beautifulsoup4",
#     "requests",
#     "rich",
# ]
# ///

import subprocess
import urllib.parse
import typer
from icecream import ic
import pyperclip
from typing_extensions import Annotated
import re
import json
from enum import Enum
from pydantic import BaseModel, Field
from typing import List, Optional, Tuple
from datetime import datetime, timedelta
import requests
from bs4 import BeautifulSoup
import uuid
import time
from rich.console import Console
from rich.theme import Theme
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box
import shlex
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path


# Timing log configuration
TIMING_LOG_FILE = Path.home() / "tmp" / "omnifocus_timing.log"
_current_command_context = "unknown"


def set_command_context(command_name: str) -> None:
    """Set the current command context for timing logs.

    Args:
        command_name: Name of the command being executed
    """
    global _current_command_context
    _current_command_context = command_name


def log_timing(operation: str, duration: float, details: str = "") -> None:
    """Log timing information to the timing log file.

    Args:
        operation: Name of the operation being timed
        duration: Duration in seconds
        details: Optional additional details about the operation
    """
    try:
        # Ensure the directory exists
        TIMING_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

        # Format: timestamp | command | operation | duration_ms | details
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        duration_ms = f"{duration * 1000:.2f}ms"
        details_str = f" | {details}" if details else ""
        log_line = f"{timestamp} | {_current_command_context:15} | {operation:25} | {duration_ms:>10}{details_str}\n"

        with open(TIMING_LOG_FILE, "a") as f:
            f.write(log_line)
    except Exception as e:
        # Silently fail if logging doesn't work - don't break the main functionality
        pass


def parse_snooze_time(time_spec: str) -> datetime:
    """Parse snooze time specification into datetime.

    Args:
        time_spec: One of 'day', 'week', or 'month'

    Returns:
        datetime: The defer date

    Raises:
        ValueError: If time_spec is not supported
    """
    now = datetime.now()

    if time_spec == "day":
        return datetime(now.year, now.month, now.day) + timedelta(days=1)
    elif time_spec == "week":
        return datetime(now.year, now.month, now.day) + timedelta(weeks=1)
    elif time_spec == "month":
        # Add one month, handling year rollover
        if now.month == 12:
            return datetime(now.year + 1, 1, now.day)
        else:
            try:
                return datetime(now.year, now.month + 1, now.day)
            except ValueError:  # Handle month with fewer days
                # Go to last day of next month
                next_month = now.month + 1
                year = now.year
                if next_month > 12:
                    next_month = 1
                    year += 1
                # Find last day of next month
                if next_month == 2:
                    last_day = (
                        29
                        if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                        else 28
                    )
                elif next_month in [4, 6, 9, 11]:
                    last_day = 30
                else:
                    last_day = 31
                return datetime(year, next_month, min(now.day, last_day))
    else:
        raise ValueError(
            f"Unsupported time specification: {time_spec}. Use 'day', 'week', or 'month'."
        )


# Create a custom theme for consistent colors
custom_theme = Theme(
    {
        "info": "cyan",
        "warning": "yellow",
        "danger": "bold red",
        "success": "green",
        "project": "blue",
        "tag": "magenta",
        "date": "yellow",
        "flag": "bold red",
        "header": "bold cyan",
        "task": "white",
    }
)

# Create a console with our custom theme
console = Console(theme=custom_theme)

# Constants for better maintainability
TASK_NUMBER_RANGE_ERROR = "Invalid task number. Please enter a number between 1 and {}"
NO_TASKS_FOUND_ERROR = "No interesting tasks found!"
INVALID_TASK_NUMBERS_ERROR = (
    "Invalid task numbers. Please provide space-separated integers."
)

app = typer.Typer(
    help="OmniFocus CLI - Manage OmniFocus from the command line",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


class Task(BaseModel):
    """Represents a task in OmniFocus."""

    name: str
    project: str = "No Project"
    flagged: bool = False
    tags: List[str] = Field(default_factory=list)
    due_date: Optional[datetime] = None
    defer_date: Optional[datetime] = None
    estimated_minutes: Optional[int] = None
    completed: bool = False
    creation_date: Optional[datetime] = None
    id: Optional[str] = None
    note: Optional[str] = None


class OSXSystem:
    """Humble object for OSX system operations."""

    @staticmethod
    def run_javascript(script: str) -> str:
        """Run a JavaScript script using osascript."""
        start_time = time.perf_counter()
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = time.perf_counter() - start_time
        log_timing("run_javascript", duration, f"script_length={len(script)}")
        return result.stdout

    @staticmethod
    def run_omni_automation(script: str) -> str:
        """Run an Omni Automation script directly in OmniFocus (much faster than JXA).

        Uses AppleScript's 'evaluate javascript' which runs the script in the
        OmniFocus JavaScript context (OmniJS) instead of via Apple Events.
        This is typically 10-100x faster than JXA for complex operations.
        """
        start_time = time.perf_counter()
        # Escape the script for AppleScript string literal
        # Keep newlines for proper JavaScript parsing
        escaped = script.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        applescript = f'tell application "OmniFocus" to evaluate javascript "{escaped}"'
        result = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=True,
        )
        duration = time.perf_counter() - start_time
        log_timing("run_omni_automation", duration, f"script_length={len(script)}")
        return result.stdout.strip()

    @staticmethod
    def open_url(url: str) -> None:
        """Open a URL using the open command."""
        start_time = time.perf_counter()
        subprocess.run(["open", url], check=True)
        duration = time.perf_counter() - start_time
        # Extract scheme for logging (e.g., "omnifocus", "https")
        scheme = url.split("://")[0] if "://" in url else "unknown"
        log_timing("open_url", duration, f"scheme={scheme}")

    @staticmethod
    def get_clipboard_content() -> str:
        """Get content from clipboard."""
        return pyperclip.paste()

    @staticmethod
    def run_flow_command(command: str, *args: str) -> str:
        """Run a flow command using the y CLI tool.

        Args:
            command: The flow command to run (e.g., 'flow-rename', 'flow-go')
            *args: Additional arguments for the command

        Returns:
            str: Command output

        Raises:
            subprocess.CalledProcessError: If the command fails
        """
        start_time = time.perf_counter()
        # Use shell=True with proper escaping for arguments that might contain special characters
        if args:
            escaped_args = [shlex.quote(arg) for arg in args]
            cmd_str = f"y {command} {' '.join(escaped_args)}"
        else:
            cmd_str = f"y {command}"

        result = subprocess.run(
            cmd_str, shell=True, capture_output=True, text=True, check=True
        )
        duration = time.perf_counter() - start_time
        log_timing("run_flow_command", duration, f"command={command}")
        return result.stdout.strip()


class LLMTaskShortener:
    """Humble object for LLM-powered task name shortening using Simon Willison's llm CLI."""

    def __init__(self, model: str = "gpt-4o-mini"):
        """Initialize the LLM task shortener.

        Args:
            model: Model to use with llm CLI (defaults to gpt-4o-mini)
        """
        self.model = model

    def shorten_task_name(self, task_name: str) -> str:
        """Shorten a task name using LLM via the llm CLI tool.

        Args:
            task_name: The original task name to shorten

        Returns:
            str: Shortened task name, or original name if LLM fails
        """
        start_time = time.perf_counter()
        try:
            prompt = f"""You are a productivity assistant helping to create concise flow session names from OmniFocus task descriptions.

Task: "{task_name}"

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

            # Use llm CLI tool to get the shortened name
            result = subprocess.run(
                ["llm", "-m", self.model, prompt],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=True,
            )

            shortened_name = result.stdout.strip()

            # Validate the response isn't empty and isn't too long
            if shortened_name and len(shortened_name) <= 50:
                duration = time.perf_counter() - start_time
                log_timing("llm_shorten_task", duration, f"model={self.model}, success=True")
                return shortened_name
            else:
                duration = time.perf_counter() - start_time
                log_timing("llm_shorten_task", duration, f"model={self.model}, success=False, reason=invalid_response")
                return task_name

        except subprocess.CalledProcessError as e:
            # Fallback to original name if llm command fails
            duration = time.perf_counter() - start_time
            log_timing("llm_shorten_task", duration, f"model={self.model}, success=False, reason=command_failed")
            console.print(f"[warning]llm command failed: {e}[/]")
            return task_name
        except subprocess.TimeoutExpired:
            duration = time.perf_counter() - start_time
            log_timing("llm_shorten_task", duration, f"model={self.model}, success=False, reason=timeout")
            console.print("[warning]llm command timed out[/]")
            return task_name
        except FileNotFoundError:
            duration = time.perf_counter() - start_time
            log_timing("llm_shorten_task", duration, f"model={self.model}, success=False, reason=not_found")
            console.print(
                "[warning]llm command not found. Install with: pip install llm[/]"
            )
            return task_name
        except Exception as e:
            # Fallback to original name if LLM fails
            duration = time.perf_counter() - start_time
            log_timing("llm_shorten_task", duration, f"model={self.model}, success=False, reason=exception")
            console.print(f"[warning]LLM shortening failed: {e}[/]")
            return task_name


def interactive_edit_session_name(suggested_name: str) -> Optional[str]:
    """Allow user to edit session name interactively.

    Args:
        suggested_name: The suggested session name to edit

    Returns:
        Optional[str]: Final session name, or None if cancelled
    """
    try:
        console.print(f"[info]Suggested session name:[/] [bold]{suggested_name}[/]")
        console.print()

        # Use input() with the suggested name as default
        user_input = input("Edit session name (or press Enter to continue): ")

        # If user just pressed Enter, use the suggested name
        if not user_input.strip():
            return suggested_name

        # Return the edited name
        return user_input.strip()

    except KeyboardInterrupt:
        console.print("\n[warning]Session creation cancelled.[/]")
        return None
    except EOFError:
        console.print("\n[warning]Session creation cancelled.[/]")
        return None


class OmniFocusManager:
    """Manager for OmniFocus operations."""

    def __init__(self, system: OSXSystem):
        self.system = system

    def _get_tasks_with_filter(self, filter_conditions: dict) -> List[Task]:
        """Internal helper to get tasks matching specified conditions.

        Args:
            filter_conditions: Dictionary of conditions to filter tasks by
                             e.g. {'completed': false, 'flagged': true}
        """
        conditions_str = ", ".join(
            f"{k}: {str(v).lower()}" for k, v in filter_conditions.items()
        )
        javascript = f"""
            function run() {{
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const tasks = doc.flattenedTasks.whose({{{conditions_str}}})();

                const taskList = tasks.map(task => ({{
                    name: task.name(),
                    project: task.containingProject() ? task.containingProject().name() : "No Project",
                    flagged: task.flagged(),
                    tags: Array.from(task.tags()).map(t => t.name()),
                    due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                    defer_date: task.deferDate() ? task.deferDate().toISOString() : null,
                    estimated_minutes: task.estimatedMinutes(),
                    completed: task.completed(),
                    creation_date: task.creationDate() ? task.creationDate().toISOString() : null,
                    id: task.id(),
                    note: task.note()
                }}));

                return JSON.stringify(taskList);
            }}
        """
        result = self.system.run_javascript(javascript)
        tasks_data = json.loads(result)
        return [Task.model_validate(task) for task in tasks_data]

    def get_all_tasks(self) -> List[Task]:
        """Get all incomplete tasks from OmniFocus."""
        return self._get_tasks_with_filter({"completed": False})

    def get_flagged_tasks(self) -> List[Task]:
        """Get all flagged incomplete tasks."""
        return self._get_tasks_with_filter({"completed": False, "flagged": True})

    def add_task(
        self,
        task_name: str,
        project: str = "today",
        tags: List[str] | None = None,
        note: str = "",
        flagged: bool = True,
    ) -> bool:
        """Add a task to OmniFocus.

        Args:
            task_name: The name of the task
            project: The project to add the task to (defaults to "today")
            tags: List of tags to apply to the task
            note: Additional notes for the task
            flagged: Whether to flag the task (defaults to True)

        Returns:
            bool: True if task was created successfully, False if validation failed
        """
        if len(task_name) < 3:
            console.print("[danger]Task text too short[/]")
            return False

        params = {
            "name": task_name,
            "autosave": "true",
            "project": project,
        }

        if flagged:
            params["flag"] = "true"
        if tags:
            params["tags"] = ",".join(tags)
        if note:
            params["note"] = note

        url = "omnifocus:///add?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote
        )
        ic("Running", url)
        self.system.open_url(url)
        return True

    def get_incomplete_tasks(self) -> List[Task]:
        """Get all incomplete tasks with their IDs, names and notes using Omni Automation (fast)."""
        script = """
(() => {
    const tasks = flattenedTasks.filter(t => !t.completed);

    function taskToObj(task) {
        return {
            id: task.id.primaryKey,
            name: task.name,
            note: task.note,
            project: task.containingProject ? task.containingProject.name : "No Project",
            flagged: task.flagged,
            tags: task.tags.map(t => t.name),
            due_date: task.dueDate ? task.dueDate.toISOString() : null,
            defer_date: task.deferDate ? task.deferDate.toISOString() : null,
            estimated_minutes: task.estimatedMinutes || null,
            completed: task.completed,
            creation_date: task.added ? task.added.toISOString() : null
        };
    }

    return JSON.stringify(tasks.map(taskToObj));
})()
"""
        result = self.system.run_omni_automation(script)
        tasks_data = json.loads(result)
        return [Task.model_validate(task) for task in tasks_data]

    def update_name(self, task: Task, new_name: str) -> None:
        """Update a task's name using a Task object.

        Args:
            task: The Task object to update
            new_name: The new name for the task
        """
        update_script = f"""
            function run() {{
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const task = doc.flattenedTasks.whose({{id: "{task.id}"}})()[0];

                if (task) {{
                    task.name = "{new_name.replace('"', "'")}";
                }}
            }}
        """
        self.system.run_javascript(update_script)

    def update_task(self, task: Task, new_name: str) -> None:
        """Update a task's name using a Task object (alias for update_name).

        Args:
            task: The Task object to update
            new_name: The new name for the task

        Raises:
            ValueError: If task doesn't have an ID
        """
        return self.update_name(task, new_name)

    def update_note(self, task: Task, note: str) -> None:
        """Update a task's note using a Task object.

        Args:
            task: The Task object to update
            note: The new note for the task
        """
        update_script = f"""
            function run() {{
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const task = doc.flattenedTasks.whose({{id: "{task.id}"}})()[0];

                if (task) {{
                    task.note = "{note.replace('"', "'")}";
                }}
            }}
        """
        self.system.run_javascript(update_script)

    def append_to_task(self, task: Task, note_text: str) -> None:
        """Append text to a task's existing note using a Task object.

        Args:
            task: The Task object to append to
            note_text: The text to append to the task's note
        """
        append_script = f"""
            function run() {{
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const task = doc.flattenedTasks.whose({{id: "{task.id}"}})()[0];

                if (task) {{
                    const currentNote = task.note();
                    const separator = currentNote && currentNote.length > 0 ? "\n\n" : "";
                    task.note = currentNote + separator + "{note_text.replace('"', "'")}";
                    return "Note appended successfully";
                }} else {{
                    throw new Error("Task not found");
                }}
            }}
        """
        return self.system.run_javascript(append_script)

    def get_inbox_and_flagged_tasks_omni(self) -> Tuple[List[Task], List[Task]]:
        """Get inbox and flagged tasks using Omni Automation (OmniJS) - much faster.

        Returns:
            Tuple of (inbox_tasks, flagged_tasks)
        """
        # Omni Automation script runs directly in OmniFocus, no Apple Events overhead
        # Use 'inbox' property instead of filtering flattenedTasks for better performance
        script = """
(() => {
    const inboxTasks = inbox.filter(t => !t.completed);
    const flaggedTasks = flattenedTasks.filter(t => t.flagged && !t.completed);

    function taskToObj(task) {
        return {
            name: task.name,
            project: task.containingProject ? task.containingProject.name : "Inbox",
            flagged: task.flagged,
            tags: task.tags.map(t => t.name),
            due_date: task.dueDate ? task.dueDate.toISOString() : null,
            defer_date: task.deferDate ? task.deferDate.toISOString() : null,
            estimated_minutes: task.estimatedMinutes || null,
            completed: task.completed,
            creation_date: task.added ? task.added.toISOString() : null,
            id: task.id.primaryKey,
            note: task.note
        };
    }

    return JSON.stringify({
        inbox: inboxTasks.map(taskToObj),
        flagged: flaggedTasks.map(taskToObj)
    });
})()
"""
        result = self.system.run_omni_automation(script)
        data = json.loads(result)
        inbox_tasks = [Task.model_validate(task) for task in data["inbox"]]
        flagged_tasks = [Task.model_validate(task) for task in data["flagged"]]
        return inbox_tasks, flagged_tasks

    def get_inbox_and_flagged_tasks(self) -> Tuple[List[Task], List[Task]]:
        """Get inbox and flagged tasks in a single query for performance.

        Returns:
            Tuple of (inbox_tasks, flagged_tasks)
        """
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;

                // Get all incomplete tasks once
                const allTasks = doc.flattenedTasks.whose({completed: false})();

                const inboxTasks = [];
                const flaggedTasks = [];

                function taskToObj(task) {
                    return {
                        name: task.name(),
                        project: task.containingProject() ? task.containingProject().name() : "Inbox",
                        flagged: task.flagged(),
                        tags: Array.from(task.tags()).map(t => t.name()),
                        due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                        defer_date: task.deferDate() ? task.deferDate().toISOString() : null,
                        estimated_minutes: task.estimatedMinutes(),
                        completed: task.completed(),
                        creation_date: task.creationDate() ? task.creationDate().toISOString() : null,
                        id: task.id(),
                        note: task.note()
                    };
                }

                // Filter in JavaScript to avoid multiple OmniFocus queries
                for (let i = 0; i < allTasks.length; i++) {
                    const task = allTasks[i];
                    if (task.inInbox()) {
                        inboxTasks.push(taskToObj(task));
                    }
                    if (task.flagged()) {
                        flaggedTasks.push(taskToObj(task));
                    }
                }

                const result = {
                    inbox: inboxTasks,
                    flagged: flaggedTasks
                };

                return JSON.stringify(result);
            }
        """
        result = self.system.run_javascript(javascript)
        data = json.loads(result)
        inbox_tasks = [Task.model_validate(task) for task in data["inbox"]]
        flagged_tasks = [Task.model_validate(task) for task in data["flagged"]]
        return inbox_tasks, flagged_tasks

    def get_inbox_tasks(self) -> List[Task]:
        """Get all tasks from the inbox."""
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const tasks = doc.flattenedTasks.whose({inInbox: true, completed: false})();

                const taskList = tasks.map(task => ({
                    name: task.name(),
                    project: "Inbox",
                    flagged: task.flagged(),
                    tags: Array.from(task.tags()).map(t => t.name()),
                    due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                    defer_date: task.deferDate() ? task.deferDate().toISOString() : null,
                    estimated_minutes: task.estimatedMinutes(),
                    completed: task.completed(),
                    creation_date: task.creationDate() ? task.creationDate().toISOString() : null,
                    id: task.id(),
                    note: task.note()
                }));

                return JSON.stringify(taskList);
            }
        """
        result = self.system.run_javascript(javascript)
        tasks_data = json.loads(result)
        return [Task.model_validate(task) for task in tasks_data]

    def complete(self, task: Task) -> str:
        """Complete a task using a Task object.

        Args:
            task: The Task object to complete

        Returns:
            str: Success message if task was completed
        """
        javascript = f"""
            function run() {{
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const task = doc.flattenedTasks.whose({{id: "{task.id}"}})()[0];

                if (task) {{
                    task.markComplete();
                    return "Task completed successfully";
                }} else {{
                    throw new Error("Task not found");
                }}
            }}
        """
        return self.system.run_javascript(javascript)

    def delete_untitled_tags(self) -> int:
        """Delete all tags titled 'Untitled Tag' or with empty names.

        Returns:
            int: Number of tags deleted
        """
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const emptyTags = doc.flattenedTags.whose({name: ''})();
                const untitledTags = doc.flattenedTags.whose({name: 'Untitled Tag'})();
                
                const count = emptyTags.length + untitledTags.length;
                
                emptyTags.forEach(tag => {
                    tag.delete();
                });
                
                untitledTags.forEach(tag => {
                    tag.delete();
                });
                
                return count;
            }
        """
        result = self.system.run_javascript(javascript)
        return int(result)

    def get_all_tags(self) -> List[str]:
        """Get all tags from OmniFocus.

        Returns:
            List[str]: List of all tag names in OmniFocus
        """
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const tags = doc.flattenedTags();
                
                const tagNames = tags.map(tag => tag.name());
                return JSON.stringify(tagNames);
            }
        """
        result = self.system.run_javascript(javascript)
        return json.loads(result)

    def start_flow_session(self, session_name: str) -> str:
        """Start a flow session with the given name.

        Args:
            session_name: The name for the flow session

        Returns:
            str: Success message

        Raises:
            subprocess.CalledProcessError: If flow commands fail
        """
        # Rename the flow session (flow-go happens automatically)
        self.system.run_flow_command("flow-rename", session_name)

        return f"Started flow session: {session_name}"

    def remove_tag_from_task(self, task: Task, tag_name: str) -> bool:
        """Remove a tag from a task.

        Args:
            task: The Task object to remove the tag from
            tag_name: The name of the tag to remove

        Returns:
            bool: True if the tag was removed, False otherwise
        """
        # For debugging
        print(f"Attempting to remove tag '{tag_name}' from task with ID: {task.id}")

        # First, check if the tag is actually assigned to the task
        if tag_name not in task.tags:
            print(f"Tag '{tag_name}' is not assigned to this task")
            return False

        # Try using the URL scheme as a fallback method
        # This is a workaround since the JavaScript approach is having issues
        try:
            # Create a new task with the same properties but without the specific tag
            new_tags = [t for t in task.tags if t != tag_name]

            # Only proceed if we have the task name
            if not task.name:
                print("Cannot remove tag: task has no name")
                return False

            # Create a new task with the updated tags
            params = {
                "name": task.name,
                "autosave": "true",
                "project": task.project if task.project else "today",
            }

            if task.flagged:
                params["flag"] = "true"

            if new_tags:
                params["tags"] = ",".join(new_tags)

            if task.note:
                params["note"] = task.note

            # Add due date if present
            if task.due_date:
                # Format as YYYY-MM-DD
                due_date_str = task.due_date.strftime("%Y-%m-%d")
                params["due"] = due_date_str

            # Add defer date if present
            if task.defer_date:
                # Format as YYYY-MM-DD
                defer_date_str = task.defer_date.strftime("%Y-%m-%d")
                params["defer"] = defer_date_str

            # Add estimated duration if present
            if task.estimated_minutes:
                params["estimate"] = str(task.estimated_minutes)

            url = "omnifocus:///add?" + urllib.parse.urlencode(
                params, quote_via=urllib.parse.quote
            )

            print(f"Using URL scheme to create task without tag: {url}")
            self.system.open_url(url)

            # Mark the original task as complete to "remove" it
            self.complete(task)

            return True
        except Exception as e:
            print(f"Error using URL scheme to remove tag: {e}")
            return False

    def add_tag_to_task(self, task: Task, tag_name: str) -> bool:
        """Add a tag to a task.

        Args:
            task: The Task object to add the tag to
            tag_name: The name of the tag to add

        Returns:
            bool: True if the tag was added, False otherwise
        """
        # For debugging
        print(f"Attempting to add tag '{tag_name}' to task with ID: {task.id}")

        # First, check if the tag is already assigned to the task
        if tag_name in task.tags:
            print(f"Tag '{tag_name}' is already assigned to this task")
            return True

        # Try using the URL scheme as a fallback method
        try:
            # Create a new task with the same properties plus the new tag
            new_tags = task.tags.copy()
            new_tags.append(tag_name)

            # Only proceed if we have the task name
            if not task.name:
                print("Cannot add tag: task has no name")
                return False

            # Create a new task with the updated tags
            params = {
                "name": task.name,
                "autosave": "true",
                "project": task.project if task.project else "today",
            }

            if task.flagged:
                params["flag"] = "true"

            params["tags"] = ",".join(new_tags)

            if task.note:
                params["note"] = task.note

            # Add due date if present
            if task.due_date:
                # Format as YYYY-MM-DD
                due_date_str = task.due_date.strftime("%Y-%m-%d")
                params["due"] = due_date_str

            # Add defer date if present
            if task.defer_date:
                # Format as YYYY-MM-DD
                defer_date_str = task.defer_date.strftime("%Y-%m-%d")
                params["defer"] = defer_date_str

            # Add estimated duration if present
            if task.estimated_minutes:
                params["estimate"] = str(task.estimated_minutes)

            url = "omnifocus:///add?" + urllib.parse.urlencode(
                params, quote_via=urllib.parse.quote
            )

            print(f"Using URL scheme to create task with new tag: {url}")
            self.system.open_url(url)

            # Mark the original task as complete to "replace" it
            self.complete(task)

            return True
        except Exception as e:
            print(f"Error using URL scheme to add tag: {e}")
            return False

    def clear_tags_from_task(self, task: Task) -> bool:
        """Remove all tags from a task.

        Args:
            task: The Task object to clear tags from

        Returns:
            bool: True if the tags were cleared, False otherwise
        """
        # For debugging
        print(f"Attempting to clear all tags from task with ID: {task.id}")

        # First, check if the task has any tags
        if not task.tags:
            print("Task has no tags to clear")
            return True

        # Try using the URL scheme as a fallback method
        try:
            # Only proceed if we have the task name
            if not task.name:
                print("Cannot clear tags: task has no name")
                return False

            # Create a new task with the same properties but without any tags
            params = {
                "name": task.name,
                "autosave": "true",
                "project": task.project if task.project else "today",
            }

            if task.flagged:
                params["flag"] = "true"

            if task.note:
                params["note"] = task.note

            # Add due date if present
            if task.due_date:
                # Format as YYYY-MM-DD
                due_date_str = task.due_date.strftime("%Y-%m-%d")
                params["due"] = due_date_str

            # Add defer date if present
            if task.defer_date:
                # Format as YYYY-MM-DD
                defer_date_str = task.defer_date.strftime("%Y-%m-%d")
                params["defer"] = defer_date_str

            # Add estimated duration if present
            if task.estimated_minutes:
                params["estimate"] = str(task.estimated_minutes)

            url = "omnifocus:///add?" + urllib.parse.urlencode(
                params, quote_via=urllib.parse.quote
            )

            print(f"Using URL scheme to create task without tags: {url}")
            self.system.open_url(url)

            # Mark the original task as complete to "remove" it
            self.complete(task)

            return True
        except Exception as e:
            print(f"Error using URL scheme to clear tags: {e}")
            return False

    def snooze_task(self, task: Task, defer_until: datetime, time_spec: str) -> bool:
        """Snooze a task by setting defer/due dates, clearing flag, adding snoozed tag, and moving from inbox to Followups.

        Args:
            task: The Task object to snooze
            defer_until: When to defer the task until (also sets due date to same date)
            time_spec: The original time specification (for note)

        Returns:
            bool: True if the task was snoozed successfully, False otherwise
        """
        try:
            # Prepare new tag list
            new_tags = task.tags.copy() if task.tags else []
            if "snoozed" not in new_tags:
                new_tags.append("snoozed")

            # Determine new project - move inbox tasks to Followups
            new_project = task.project
            if task.project == "Inbox":
                new_project = "Followups"

            # Prepare snooze note to append
            snooze_note = (
                f"Snoozed for {time_spec} until {defer_until.strftime('%Y-%m-%d')}"
            )

            # Combine existing note with snooze note
            if task.note:
                new_note = f"{task.note}\n\n{snooze_note}"
            else:
                new_note = snooze_note

            # Create new task with updated properties using URL scheme
            params = {
                "name": task.name,
                "autosave": "true",
                "project": new_project,
                "defer": defer_until.strftime("%Y-%m-%d"),
                "due": defer_until.strftime(
                    "%Y-%m-%d"
                ),  # Set due date same as defer date
                "tags": ",".join(new_tags),
                "note": new_note,
            }

            # Don't add flag=true (this clears the flag when snoozing)

            # Add estimated duration if present
            if task.estimated_minutes:
                params["estimate"] = str(task.estimated_minutes)

            url = "omnifocus:///add?" + urllib.parse.urlencode(
                params, quote_via=urllib.parse.quote
            )

            print(f"Snoozing task with URL: {url}")
            self.system.open_url(url)

            # Complete the original task to "replace" it
            self.complete(task)

            return True
        except Exception as e:
            print(f"Error snoozing task: {e}")
            return False


def sanitize_task_text(task: str) -> str:
    """Clean up a task string by removing markers and formatting."""
    # remove task markers, and markdown headers
    task = task.replace("☐", "")
    # replace start of line with a {number}. to nothing, e.g. 1., or 2. or 3.
    task = re.sub(r"^\s*\d+\.\s*", "", task)
    task = task.strip()

    if "☑" in task or "CUT" in task:
        return ""

    return task


def extract_tags_from_task(task: str) -> tuple[str, List[str]]:
    """Process a task string and extract any tags.

    Currently supports:
    - work tag: extracts from 'work:' prefix or 'work' keyword

    Returns:
        tuple[str, List[str]]: (cleaned task text, list of extracted tags)
    """
    tags = []
    if "work" in task.lower():
        tags.append("work")
        task = re.sub(r"work:\s*", "", task, flags=re.IGNORECASE)
        task = re.sub(r"\bwork\b", "", task, flags=re.IGNORECASE)
        task = task.strip()
        task = re.sub(r"\s+", " ", task)
    return task, tags


# Initialize system and manager
system = OSXSystem()
manager = OmniFocusManager(system)


def _process_clipboard_tasks(
    manager: OmniFocusManager, system: OSXSystem, print_only: bool = False
):
    """Helper function to process tasks from clipboard."""
    ic(print_only)
    clipboard_content = system.get_clipboard_content()

    # Get existing tasks for duplicate checking
    existing_tasks = {task.name.lower(): task for task in manager.get_all_tasks()}

    # Split into lines and clean up each line
    lines = [line.strip() for line in clipboard_content.split("\n") if line.strip()]

    # First clean up all tasks
    cleaned_tasks = []
    for line in lines:
        task_text = sanitize_task_text(line)
        if task_text:  # Only include non-empty tasks
            cleaned_tasks.append(task_text)

    # Then deduplicate, keeping order
    seen = set()
    unique_tasks = []
    for task_text in cleaned_tasks:
        if task_text.lower() not in seen:  # Case-insensitive deduplication
            seen.add(task_text.lower())
            unique_tasks.append(task_text)

    if len(unique_tasks) > 25:
        console.print("[warning]Too many tasks from clipboard (max 25). Aborting.[/]")
        return

    # Print summary
    console.print(
        f"\nFound {len(lines)} lines, {len(cleaned_tasks)} valid tasks, {len(unique_tasks)} unique tasks"
    )
    console.print("\n[header]Tasks to process:[/header]")
    console.print("----------------")

    for task_text in unique_tasks:
        task_name, tags = extract_tags_from_task(task_text)
        if task_name.lower() in existing_tasks:
            existing_task = existing_tasks[task_name.lower()]
            console.print(
                f"• {task_name} ([dim]Already exists in project: {existing_task.project}[/dim])"
            )
        else:
            console.print(f"• {task_name}")
            if not print_only:
                success = manager.add_task(task_name, tags=tags)
                if not success:
                    console.print(
                        f"  [danger]✗ Failed to add task: {task_name}[/danger]"
                    )


@app.command(name="add-clipboard")
def add_tasks_from_clipboard(
    print_only: Annotated[
        bool, typer.Option(help="Preview tasks without adding them")
    ] = False,
):
    """Add tasks from clipboard to OmniFocus (one task per line)"""
    _process_clipboard_tasks(manager, system, print_only)


class View(str, Enum):
    by_project = "by_project"
    by_tag = "by_tag"


@app.command()
def list_grouped_tasks(
    view: Annotated[
        View, typer.Option(help="Group tasks by 'by_project' or 'by_tag'")
    ] = View.by_project,
):
    """List all tasks, grouped by either project or tag"""
    set_command_context("list_grouped_tasks")
    tasks = manager.get_all_tasks()

    if view == View.by_project:
        # Group tasks by project
        groups = {}
        for task in tasks:
            if task.project not in groups:
                groups[task.project] = []
            groups[task.project].append(task)

        # Sort projects by name, with "today" first if it exists
        sorted_groups = sorted(groups.keys())
        if "today" in sorted_groups:
            sorted_groups.remove("today")
            sorted_groups.insert(0, "today")

        console.print(Panel.fit("[header]Tasks by Project[/]", border_style="cyan"))

    else:  # by_tag
        # Group tasks by tag
        groups = {"No Tags": []}  # Default group for untagged tasks
        for task in tasks:
            if not task.tags:
                groups["No Tags"].append(task)
            else:
                for tag in task.tags:
                    if tag not in groups:
                        groups[tag] = []
                    groups[tag].append(task)

        sorted_groups = sorted(groups.keys())
        console.print(Panel.fit("[header]Tasks by Tag[/]", border_style="cyan"))

    for group in sorted_groups:
        if group not in groups or not groups[group]:
            continue

        task_count = len(groups[group])
        console.print(f"\n[bold][project]{group}[/] [white]({task_count})[/][/bold]")

        for task in groups[group]:
            # Build task display with rich formatting
            task_text = Text()

            # Add flag emoji if flagged
            if task.flagged:
                task_text.append("🚩 ", style="flag")

            # Add task name
            task_text.append(task.name, style="task")

            # Add project info if in tag view
            if view == View.by_tag and task.project:
                task_text.append(" (", style="white")
                task_text.append(f"{task.project}", style="project")
                task_text.append(")", style="white")

            # Add tags if in project view
            if view == View.by_project and task.tags:
                tag_str = ", ".join(task.tags)
                task_text.append(" [", style="white")
                task_text.append(tag_str, style="tag")
                task_text.append("]", style="white")

            # Add due date if present
            if task.due_date:
                task_text.append(" [Due: ", style="white")
                task_text.append(f"{task.due_date.date()}", style="date")
                task_text.append("]", style="white")

            console.print("  • ", end="")
            console.print(task_text)


@app.command(name="flagged")
def list_flagged():
    """Show flagged tasks with consistent index numbers from interesting command"""
    set_command_context("flagged")
    # Get the same task list as interesting command for consistent numbering
    all_interesting_tasks = _get_interesting_tasks()

    # Filter to only flagged tasks but keep their original index numbers
    flagged_with_indices = []
    for i, (source, task) in enumerate(all_interesting_tasks, 1):
        if task.flagged:
            flagged_with_indices.append((i, task))

    # Early return if no flagged tasks
    if not flagged_with_indices:
        console.print("[dim]No flagged tasks found![/]")
        return

    console.print(Panel.fit("[header]Flagged Tasks[/]", border_style="red"))

    # Create a table for flagged tasks with index column
    table = Table(box=box.ROUNDED, border_style="red", expand=True)
    table.add_column("Index", style="bold cyan", width=6, justify="center")
    table.add_column("Task", style="task")
    table.add_column("Project", style="project")
    table.add_column("Tags", style="tag")
    table.add_column("Due Date", style="date")
    table.add_column("Created", style="date")

    for index, task in flagged_with_indices:
        # Format tags as comma-separated list
        tags_str = ", ".join(task.tags) if task.tags else ""

        # Format dates
        due_date = task.due_date.date() if task.due_date else ""
        created_date = task.creation_date.date() if task.creation_date else ""

        # Build task display with icons
        task_display = "🚩 "
        if extract_url_from_task(task):
            task_display += "🌐 "
        task_display += task.name

        # Add row to table
        table.add_row(
            str(index),
            task_display,
            task.project,
            tags_str,
            str(due_date),
            str(created_date),
        )

    console.print(table)


@app.command()
def add(
    task: Annotated[
        Optional[str], typer.Argument(help="The task or URL to create a task from")
    ] = None,
    project: Annotated[str, typer.Option(help="Project to add the task to")] = "today",
    tags: Annotated[
        Optional[str],
        typer.Option(
            "--tag", help="Tags to add to the task (can be specified multiple times)"
        ),
    ] = None,
    clipboard: Annotated[
        bool, typer.Option("--clipboard", help="Add tasks from clipboard")
    ] = False,
):
    """Create a task. If the input looks like a URL, it will fetch the page title and use it as the task name."""
    set_command_context("add")
    if clipboard:
        if task is not None:  # Check if task was explicitly provided
            console.print("[warning]Ignoring task argument as --clipboard is used.[/]")
        _process_clipboard_tasks(manager, system, print_only=False)
        return

    # If not using clipboard, task is required
    if task is None:
        console.print(
            "[danger]Error: Task description or URL is required when not using --clipboard.[/danger]"
        )
        raise typer.Exit(code=1)

    # Convert tags string to list if provided
    tag_list = []
    if tags:
        tag_list.extend(tags.split(","))

    # Check if the input looks like a URL
    if task.startswith(("http://", "https://")):
        try:
            # Add url tag for URL tasks
            tag_list.append("url")

            # Fetch the webpage
            response = requests.get(task, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

            # Parse the HTML and extract the title
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title else task

            # Create the task with the title and URL in the note
            new_task = Task(
                name=title, project=project, tags=tag_list, note=f"Source: {task}"
            )
            success = manager.add_task(
                task_name=new_task.name,
                project=new_task.project,
                tags=new_task.tags,
                note=new_task.note,
            )

            # Show success message with rich formatting only if task was created
            if success:
                console.print(
                    Panel.fit(
                        f"[success]✓ Created task from URL:[/]\n"
                        f"[task]{title}[/]\n"
                        f"[info]Project:[/] [project]{project}[/]\n"
                        f"[info]Tags:[/] [tag]{', '.join(tag_list)}[/]\n"
                        f"[info]URL:[/] {task}",
                        title="Task Created",
                        border_style="green",
                    )
                )
        except requests.exceptions.RequestException as e:
            # Show error message with rich formatting
            console.print(f"[danger]Error fetching URL: {e}[/]")
            # Don't create a fallback task for network errors
            return
        except Exception as e:
            # Show error message with rich formatting
            console.print(f"[danger]Error creating task from URL: {e}[/]")
            # Fallback to creating a regular task with the URL as the name
            new_task = Task(name=task, project=project, tags=tag_list)
            success = manager.add_task(
                task_name=new_task.name, project=new_task.project, tags=new_task.tags
            )
            if success:
                console.print("[warning]Created task with URL as name instead.[/]")
    else:
        # Create a regular task
        new_task = Task(name=task, project=project, tags=tag_list)
        success = manager.add_task(
            task_name=new_task.name, project=new_task.project, tags=new_task.tags
        )

        # Show success message with rich formatting only if task was created
        if success:
            tag_display = (
                f"[tag]{', '.join(tag_list)}[/]" if tag_list else "[dim]None[/]"
            )
            console.print(
                Panel.fit(
                    f"[success]✓ Created task:[/]\n"
                    f"[task]{task}[/]\n"
                    f"[info]Project:[/] [project]{project}[/]\n"
                    f"[info]Tags:[/] {tag_display}",
                    title="Task Created",
                    border_style="green",
                )
            )


@app.command()
def fixup_url():
    """Find tasks that have empty names or URLs as names, and update them with webpage titles."""
    set_command_context("fixup_url")
    # Use faster method to get incomplete tasks
    all_tasks = manager.get_incomplete_tasks()

    # Find tasks with URLs in notes or as names
    url_pattern = r'(https?://[^\s)"]+)'
    tasks_to_update = []
    for task in all_tasks:
        # Check if there's a URL in the note and the task name is empty
        if hasattr(task, "note") and task.note:
            urls = re.findall(url_pattern, task.note)
            if urls and not task.name.strip():  # Empty name with URL in note
                tasks_to_update.append(
                    (task, urls[0], task.note)
                )  # Take the first URL found
        # Also check if the task name itself is a URL
        elif re.match(url_pattern, task.name.strip()):
            tasks_to_update.append((task, task.name.strip(), ""))

    if not tasks_to_update:
        print("No tasks found that need URL fixup")
        return

    print(f"Found {len(tasks_to_update)} tasks to update")

    # Update each task
    for task, url, existing_note in tasks_to_update:
        try:
            # First, ensure URL is in the note if it was in the name
            if not existing_note:
                try:
                    note = f"Source: {url}"
                    manager.update_note(task, note)
                    print(f"✓ Moved URL to note: {url}")
                except Exception as e:
                    print(f"✗ Error processing task: {str(e)}")
                    continue

            # Then fetch and update the title
            response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()

            # Parse the HTML and extract the title
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title else url

            # Update the task name
            manager.update_name(task, title)
            print(f"✓ Updated task with title: {title}")

        except requests.exceptions.RequestException as e:
            print(f"✗ Error fetching URL: {e}")
        except Exception as e:
            print(f"✗ Error processing task: {e}")


@app.command()
def test_tag(
    tag_name: Annotated[str, typer.Argument(help="Name of tag to create and assign")],
):
    """Test tag creation, removal, and re-addition on a task"""
    # Create a unique test task name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"

    # Step 1: Create a task with the tag
    print(f"Step 1: Creating test task '{test_name}' with tag '{tag_name}'")
    # Always add to Testing project and include the testing tag
    success = manager.add_task(
        test_name,
        project="Testing",
        tags=["testing", tag_name],
        note=f"Test task with tag: {tag_name}",
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Verify tag was assigned
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    if tag_name in test_task.tags:
        print(f"✓ Successfully verified tag '{tag_name}' was assigned to task")
    else:
        print(f"✗ Could not verify tag '{tag_name}' was assigned to task")
        return

    # Step 2: Remove the tag from the task
    print(f"\nStep 2: Removing tag '{tag_name}' from test task")
    if manager.remove_tag_from_task(test_task, tag_name):
        print(f"✓ Successfully removed tag '{tag_name}' from task")
    else:
        print(f"✗ Failed to remove tag '{tag_name}' from task")
        # Continue anyway to try the next steps

    # Verify tag was removed
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if test_task and tag_name not in test_task.tags:
        print(f"✓ Successfully verified tag '{tag_name}' was removed from task")
    else:
        print(f"✗ Could not verify tag '{tag_name}' was removed from task")
        # Continue anyway to try the next steps

    # Step 3: Add the tag back to the task
    print(f"\nStep 3: Adding tag '{tag_name}' back to test task")
    if manager.add_tag_to_task(test_task, tag_name):
        print(f"✓ Successfully added tag '{tag_name}' back to task")
    else:
        print(f"✗ Failed to add tag '{tag_name}' back to task")
        # Continue anyway to try the next steps

    # Verify tag was added back
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if test_task and tag_name in test_task.tags:
        print(f"✓ Successfully verified tag '{tag_name}' was added back to task")
    else:
        print(f"✗ Could not verify tag '{tag_name}' was added back to task")

    # Step 4: Clear all tags from the task
    print("\nStep 4: Clearing all tags from test task")
    if manager.clear_tags_from_task(test_task):
        print("✓ Successfully cleared all tags from task")
    else:
        print("✗ Failed to clear all tags from task")

    # Verify tags were cleared
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if test_task and not test_task.tags:
        print("✓ Successfully verified all tags were cleared from task")
    else:
        print("✗ Could not verify all tags were cleared from task")

    print("\nTag testing completed.")


@app.command()
def test_update():
    """Test task name update functionality by creating a task and updating its name"""
    # Create a unique test task name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"

    # Create a task
    print(f"Creating test task '{test_name}'")
    success = manager.add_task(
        test_name,
        project="Testing",
        tags=["testing"],
        note="Test task for update functionality",
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Get the task
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    # Update the task name
    new_name = f"UPDATED-{uuid.uuid4().hex[:8]}"
    print(f"Updating task name to '{new_name}'")
    manager.update_name(test_task, new_name)
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Verify the update
    tasks = manager.get_all_tasks()
    updated_task = next((task for task in tasks if task.name == new_name), None)

    if updated_task:
        print(f"✓ Successfully updated task name to '{new_name}'")
    else:
        print(f"✗ Failed to update task name to '{new_name}'")


@app.command()
def test_append():
    """Test appending to a task's note by creating a task and appending to its note"""
    # Create a unique test task name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"

    # Create a task
    print(f"Creating test task '{test_name}'")
    success = manager.add_task(
        test_name, project="Testing", tags=["testing"], note="Initial note"
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Get the task
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    # Append to the task note
    append_text = f"Appended text at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    print(f"Appending text to task note: '{append_text}'")
    manager.append_to_task(test_task, append_text)
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Verify the append
    tasks = manager.get_all_tasks()
    updated_task = next((task for task in tasks if task.name == test_name), None)

    if updated_task and updated_task.note and append_text in updated_task.note:
        print("✓ Successfully appended text to task note")
    else:
        print("✗ Failed to append text to task note")


@app.command()
def test_append_pydantic():
    """Test appending to a task's note using a Pydantic Task object"""
    # Create a unique test task name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"

    # Create a task
    print(f"Creating test task '{test_name}'")
    success = manager.add_task(
        test_name, project="Testing", tags=["testing"], note="Initial note"
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Get the task
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    # Create a Pydantic Task object with the same ID but different note
    append_text = f"Appended text at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    print(f"Appending text to task note using Pydantic Task object: '{append_text}'")
    manager.append_to_task(test_task, append_text)
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Verify the append
    tasks = manager.get_all_tasks()
    updated_task = next((task for task in tasks if task.name == test_name), None)

    if updated_task and updated_task.note and append_text in updated_task.note:
        print("✓ Successfully appended text to task note using Pydantic Task object")
    else:
        print("✗ Failed to append text to task note using Pydantic Task object")


@app.command()
def test_snooze():
    """Test snooze functionality by creating a task and snoozing it"""
    # Create a unique test task name
    test_name = f"TEST-SNOOZE-{uuid.uuid4().hex[:8]}"

    # Create a flagged task in inbox
    print(f"Creating test task '{test_name}' in Inbox (flagged)")
    success = manager.add_task(
        test_name,
        project="Inbox",
        tags=["testing"],
        note="Test task for snooze functionality",
        flagged=True,
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Get the task
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    # Test snoozing the task for 1 day
    print(f"Snoozing test task '{test_name}' for 1 day")
    defer_until = parse_snooze_time("day")

    if manager.snooze_task(test_task, defer_until, "day"):
        print(f"✓ Successfully snoozed task until {defer_until.strftime('%Y-%m-%d')}")

        # Wait and verify the snooze worked
        time.sleep(2)
        tasks = manager.get_all_tasks()

        # Look for a task with the same name in Followups project with snoozed tag
        snoozed_task = None
        for task in tasks:
            if (
                task.name == test_name
                and "snoozed" in (task.tags or [])
                and task.project == "Followups"
            ):
                snoozed_task = task
                break

        if snoozed_task:
            print("✓ Successfully verified task was moved to Followups project")
            print("✓ Successfully verified 'snoozed' tag was added")
            if not snoozed_task.flagged:
                print("✓ Successfully verified flag was cleared")
            else:
                print("✗ Failed to verify flag was cleared")
            if snoozed_task.note and "Snoozed for day" in snoozed_task.note:
                print("✓ Successfully verified snooze note was appended")
            else:
                print("✗ Failed to verify snooze note was appended")
            if snoozed_task.defer_date:
                print(
                    f"✓ Successfully verified defer date was set to {snoozed_task.defer_date.date()}"
                )
            else:
                print("✗ Failed to verify defer date was set")
            if snoozed_task.due_date:
                print(
                    f"✓ Successfully verified due date was set to {snoozed_task.due_date.date()}"
                )
            else:
                print("✗ Failed to verify due date was set")
        else:
            print("✗ Could not find snoozed task in Followups project")
    else:
        print("✗ Failed to snooze task")

    print("\nSnooze testing completed.")


def extract_url_from_task(task: Task) -> Optional[str]:
    """Extract the first URL found in a task's note or name.

    Args:
        task: The task to extract URL from

    Returns:
        The first URL found, or None if no URL is present
    """
    url_pattern = r'(https?://[^\s)"]+)'

    # Check note first
    if task.note:
        urls = re.findall(url_pattern, task.note)
        if urls:
            return urls[0]

    # Check name if no URL in note
    if re.match(url_pattern, task.name.strip()):
        return task.name.strip()

    return None


def _get_interesting_tasks() -> List[Tuple[str, Task]]:
    """Get deduplicated list of inbox and flagged tasks with their sources."""
    # Use Omni Automation for much faster performance
    inbox_tasks, flagged_tasks = manager.get_inbox_and_flagged_tasks_omni()

    # Remove duplicates (tasks that are both in inbox and flagged)
    seen_names = set()
    all_tasks = []

    # Process inbox tasks first
    for task in inbox_tasks:
        if task.name.lower() not in seen_names:
            seen_names.add(task.name.lower())
            all_tasks.append(("Inbox", task))

    # Then process flagged tasks
    for task in flagged_tasks:
        if task.name.lower() not in seen_names:
            seen_names.add(task.name.lower())
            all_tasks.append(("Flagged", task))

    return all_tasks


def _format_task_line(index: int, source: str, task: Task) -> str:
    """Format a single task line for display.

    Args:
        index: Task number (1-based)
        source: Source of the task ("Inbox" or "Flagged")
        task: The task object

    Returns:
        Formatted string for display
    """
    # Build optional components
    project = f" ({task.project})" if task.project != "Inbox" else ""
    tags = f" [{', '.join(task.tags)}]" if task.tags else ""
    due = f" [Due: {task.due_date.date()}]" if task.due_date else ""
    created = f" [Created: {task.creation_date.date()}]" if task.creation_date else ""

    # Build icons
    flag = "🚩 " if task.flagged else ""
    web_icon = "🌐 " if extract_url_from_task(task) else ""

    return f"{index:2d}. {web_icon}{flag}{task.name}{project}{tags}{due}{created} ({source})"


def _get_task_by_number(task_num: int) -> Tuple[str, Task]:
    """Get a task by its number from the interesting tasks list.

    Args:
        task_num: The task number (1-based)

    Returns:
        Tuple of (source, task) if valid

    Raises:
        ValueError: If no tasks available or invalid task number
    """
    all_tasks = _get_interesting_tasks()

    if not all_tasks:
        raise ValueError(NO_TASKS_FOUND_ERROR)

    if not _validate_task_number(task_num, len(all_tasks)):
        raise ValueError(TASK_NUMBER_RANGE_ERROR.format(len(all_tasks)))

    return all_tasks[task_num - 1]


@app.command()
def interesting():
    """Show numbered list of inbox and flagged tasks"""
    set_command_context("interesting")
    all_tasks = _get_interesting_tasks()

    # Early return if no tasks
    if not all_tasks:
        print(f"\n{NO_TASKS_FOUND_ERROR}")
        return

    print("\nInteresting Tasks:")
    print("=================")

    # Print formatted tasks
    for i, (source, task) in enumerate(all_tasks, 1):
        print(_format_task_line(i, source, task))


@app.command()
def ainteresting():
    """Output interesting tasks in Alfred JSON format for workflow integration"""
    set_command_context("ainteresting")
    all_tasks = _get_interesting_tasks()

    # Sort by creation date, most recent first
    all_tasks_sorted = sorted(
        all_tasks,
        key=lambda x: x[1].creation_date if x[1].creation_date else datetime.min,
        reverse=True,
    )

    # Build Alfred JSON format
    items = []
    for i, (source, task) in enumerate(all_tasks_sorted, 1):
        # Build subtitle with metadata
        subtitle_parts = []
        if task.project and task.project != "Inbox":
            subtitle_parts.append(f"📁 {task.project}")
        if task.tags:
            subtitle_parts.append(f"🏷️ {', '.join(task.tags)}")
        if task.due_date:
            subtitle_parts.append(f"📅 Due: {task.due_date.date()}")
        if task.creation_date:
            subtitle_parts.append(f"Created: {task.creation_date.date()}")
        subtitle_parts.append(f"({source})")

        subtitle = " · ".join(subtitle_parts) if subtitle_parts else source

        # Build title with icons
        title_parts = []
        if task.flagged:
            title_parts.append("🚩")
        if extract_url_from_task(task):
            title_parts.append("🌐")
        title_parts.append(task.name)
        title = " ".join(title_parts)

        # Build Alfred item
        item = {
            "uid": task.id or f"task-{i}",
            "title": title,
            "subtitle": subtitle,
            "arg": str(i),  # Pass task number for use in other commands
            "autocomplete": task.name,
            "valid": True,
            "match": task.name,  # Allow Alfred to match on task name
            "text": {
                "copy": task.name,
                "largetype": f"{task.name}\n\nProject: {task.project}\nTags: {', '.join(task.tags) if task.tags else 'None'}",
            },
        }

        # Add URL if present for quicklook
        url = extract_url_from_task(task)
        if url:
            item["quicklookurl"] = url

        items.append(item)

    # Output Alfred JSON format
    alfred_output = {"items": items}
    print(json.dumps(alfred_output, indent=2))


@app.command()
def test_complete():
    """Test the task completion functionality by completing a test task."""
    # Create a unique test task name
    test_name = f"TEST-COMPLETE-{uuid.uuid4().hex[:8]}"

    # Create a task
    print(f"Creating test task '{test_name}'")
    success = manager.add_task(
        test_name,
        project="Testing",
        tags=["testing"],
        note="Test task for completion functionality",
    )
    if not success:
        print(f"✗ Failed to create test task '{test_name}'")
        return
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Get the task
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)

    if not test_task:
        print(f"✗ Could not find the test task '{test_name}'")
        return

    # Complete the task
    print(f"Completing test task '{test_name}'")
    manager.complete(test_task)
    time.sleep(1)  # Brief pause to ensure OmniFocus has time to process

    # Verify the task was completed
    tasks = manager.get_all_tasks()
    completed_task = next((task for task in tasks if task.name == test_name), None)

    if not completed_task:
        print(
            f"✓ Successfully completed task '{test_name}' (task no longer appears in incomplete tasks)"
        )
    else:
        print(
            f"✗ Failed to complete task '{test_name}' (task still appears in incomplete tasks)"
        )


def _parse_task_numbers(task_nums_str: str) -> Optional[List[int]]:
    """Parse space-separated task numbers from string.

    Returns:
        List of integers or None if parsing fails
    """
    if not task_nums_str:
        return None

    try:
        return [int(n.strip()) for n in task_nums_str.split()]
    except ValueError:
        return None


def _validate_task_number(num: int, max_tasks: int) -> bool:
    """Validate if task number is within valid range."""
    return 1 <= num <= max_tasks


def _get_tasks_for_completion(
    task_nums_str: str,
) -> Optional[List[Tuple[int, str, Task]]]:
    """Parse task numbers and get corresponding task objects upfront.

    Args:
        task_nums_str: Space-separated task numbers

    Returns:
        List of (task_num, source, task) tuples or None if invalid
    """
    nums = _parse_task_numbers(task_nums_str)
    if nums is None:
        typer.echo(INVALID_TASK_NUMBERS_ERROR)
        return None

    all_interesting_tasks = _get_interesting_tasks()
    if not all_interesting_tasks:
        typer.echo(NO_TASKS_FOUND_ERROR)
        return None

    max_tasks = len(all_interesting_tasks)
    tasks_to_complete = []

    for num in nums:
        if not _validate_task_number(num, max_tasks):
            typer.echo(
                f"✗ Invalid task number {num}. Please enter a number between 1 and {max_tasks}"
            )
            return None

        source, task = all_interesting_tasks[num - 1]
        tasks_to_complete.append((num, source, task))

    return tasks_to_complete


def _get_tasks_for_completion_from_list(
    task_nums: List[int],
) -> Optional[List[Tuple[int, str, Task]]]:
    """Get task objects from a list of task numbers.

    Args:
        task_nums: List of task numbers

    Returns:
        List of (task_num, source, task) tuples or None if invalid
    """
    if not task_nums:
        return None

    all_interesting_tasks = _get_interesting_tasks()
    if not all_interesting_tasks:
        typer.echo(NO_TASKS_FOUND_ERROR)
        return None

    max_tasks = len(all_interesting_tasks)
    tasks_to_complete = []

    for num in task_nums:
        if not _validate_task_number(num, max_tasks):
            typer.echo(
                f"✗ Invalid task number {num}. Please enter a number between 1 and {max_tasks}"
            )
            return None

        source, task = all_interesting_tasks[num - 1]
        tasks_to_complete.append((num, source, task))

    return tasks_to_complete


@app.command()
def complete(
    task_nums: Annotated[
        List[int], typer.Argument(help="Task numbers to complete (space separated)")
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Show what would be completed without actually completing"
        ),
    ] = False,
    no_confirm: Annotated[
        bool,
        typer.Option(
            "--no-confirm",
            help="Skip confirmation prompts when completing multiple tasks",
        ),
    ] = False,
):
    """List interesting tasks and complete specified task numbers.

    When completing multiple tasks, each task will be shown with a confirmation
    prompt before completion. Use --no-confirm to skip prompts for automation.
    Single task completion never requires confirmation.

    Examples:
        omnifocus complete 1
        omnifocus complete 1 3 5
        todo complete 2 4 --dry-run
    """
    set_command_context("complete")
    # Early return if no task numbers provided
    if not task_nums:
        interesting()
        return

    # Get and validate all tasks upfront to prevent task number shifting
    tasks_to_complete = _get_tasks_for_completion_from_list(task_nums)
    if tasks_to_complete is None:
        return

    single_task = len(tasks_to_complete) == 1
    completed, errors, skipped = [], [], []

    for num, source, task in tasks_to_complete:
        if dry_run:
            completed.append(f"Would complete {num}: {task.name} ({source})")
            continue

        # Show confirmation for multi-task operations unless explicitly disabled
        if not single_task and not no_confirm:
            typer.echo(f"\nTask {num}: {task.name}")
            typer.echo(f"Project: {task.project}")
            if task.tags:
                typer.echo(f"Tags: {', '.join(task.tags)}")

            try:
                if not typer.confirm("Complete this task?"):
                    skipped.append(f"⏭ {num}: {task.name} (skipped)")
                    continue
            except (KeyboardInterrupt, typer.Abort):
                typer.echo("\nOperation cancelled")
                return

        try:
            manager.complete(task)
            completed.append(f"✓ {num}: {task.name}")
        except Exception as e:
            errors.append(f"✗ {num}: {task.name} - {str(e)}")

    # Display results
    for results, header in [
        (completed, "\nDry run - would complete:" if dry_run else "\nCompleted tasks:"),
        (skipped, "\nSkipped tasks:"),
        (errors, "\nErrors:"),
    ]:
        if results:
            typer.echo(header)
            for msg in results:
                typer.echo(msg)


@app.command(name="list-tags")
def list_tags():
    """List all tags in OmniFocus."""
    system = OSXSystem()
    manager = OmniFocusManager(system)
    tags = manager.get_all_tags()

    # Create a panel with all tags
    tag_panel = Panel.fit(
        "\n".join([f"[tag]{tag}[/]" for tag in sorted(tags)]),
        title="[header]Available Tags[/]",
        border_style="magenta",
        padding=(1, 2),
    )

    console.print(tag_panel)
    console.print(f"[info]Total tags:[/] [bold]{len(tags)}[/bold]")


@app.command(name="cleanup-tags")
def cleanup_tags():
    """Delete all empty tags and 'Untitled Tag' tags from OmniFocus."""
    system = OSXSystem()
    manager = OmniFocusManager(system)
    count = manager.delete_untitled_tags()

    if count == 0:
        console.print(
            Panel("[info]No empty or untitled tags found.[/]", border_style="green")
        )
    else:
        console.print(
            Panel(
                f"[success]Deleted {count} empty/untitled tag{'s' if count > 1 else ''}.[/]",
                border_style="green",
                title="Cleanup Complete",
            )
        )


@app.command(name="manage-tags")
def manage_tags(
    task_num: Annotated[int, typer.Argument(help="Task number from the list command")],
    add: Annotated[
        Optional[str], typer.Option("--add", "-a", help="Tag to add to the task")
    ] = None,
    remove: Annotated[
        Optional[str],
        typer.Option("--remove", "-r", help="Tag to remove from the task"),
    ] = None,
    clear: Annotated[
        bool, typer.Option("--clear", "-c", help="Clear all tags from the task")
    ] = False,
):
    """Manage tags on an existing task.

    First use the 'list' command to see task numbers, then use this command to manage tags.
    """
    # Get all tasks
    tasks = manager.get_all_tasks()

    # Check if task_num is valid
    if task_num < 1 or task_num > len(tasks):
        typer.echo(
            f"Error: Task number {task_num} is out of range. Use 'list' command to see valid task numbers."
        )
        return

    # Get the task
    task = tasks[task_num - 1]

    # Show current tags
    current_tags = ", ".join(task.tags) if task.tags else "None"
    typer.echo(f"Task: {task.name}")
    typer.echo(f"Current tags: {current_tags}")

    # Process operations
    if clear:
        if manager.clear_tags_from_task(task):
            typer.echo("✓ Successfully cleared all tags from task")
        else:
            typer.echo("✗ Failed to clear all tags from task")
        return

    if remove:
        if remove in task.tags:
            if manager.remove_tag_from_task(task, remove):
                typer.echo(f"✓ Successfully removed tag '{remove}' from task")
            else:
                typer.echo(f"✗ Failed to remove tag '{remove}' from task")
        else:
            typer.echo(f"Tag '{remove}' is not assigned to this task")

    if add:
        if add not in task.tags:
            if manager.add_tag_to_task(task, add):
                typer.echo(f"✓ Successfully added tag '{add}' to task")
            else:
                typer.echo(f"✗ Failed to add tag '{add}' to task")
        else:
            typer.echo(f"Tag '{add}' is already assigned to this task")

    # If no operation was specified
    if not (clear or remove or add):
        typer.echo(
            "No tag operation specified. Use --add, --remove, or --clear to manage tags."
        )


@app.command()
def open_task(
    task_num: Annotated[
        int,
        typer.Argument(
            help="Task number from the interesting command to open URL from"
        ),
    ],
):
    """Open the URL from a task by its number from the interesting command."""
    set_command_context("open_task")
    try:
        source, selected_task = _get_task_by_number(task_num)

        # Early return if no URL found
        url = extract_url_from_task(selected_task)
        if not url:
            print(f"Task '{selected_task.name}' does not contain a URL")
            return

        # Attempt to open URL
        system.open_url(url)
        print(f"✓ Opened URL: {url}")
        print(f"  From task: {selected_task.name}")

    except ValueError as e:
        print(str(e))
    except Exception as e:
        print(f"✗ Error opening URL: {e}")


@app.command()
def flow(
    task_num: Annotated[
        int,
        typer.Argument(
            help="Task number from the interesting command to use as flow session name"
        ),
    ],
    no_shorten: Annotated[
        bool,
        typer.Option("--no-shorten", help="Disable LLM-powered task name shortening"),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Show what would happen without starting the session"
        ),
    ] = False,
):
    """Start a flow session with task name using flow-go directly."""
    set_command_context("flow")
    try:
        source, selected_task = _get_task_by_number(task_num)

        console.print(f"[info]Task:[/] [bold]{selected_task.name}[/]")

        # Start with the original task name
        session_name = selected_task.name

        # Apply LLM shortening if enabled
        if not no_shorten:
            try:
                shortener = LLMTaskShortener()
                session_name = shortener.shorten_task_name(selected_task.name)
            except Exception as e:
                console.print(f"[warning]LLM shortening failed: {e}[/]")
                console.print("[info]Continuing with original task name...[/]")

        # Interactive editing
        final_session_name = interactive_edit_session_name(session_name)

        # Early return if user cancelled
        if final_session_name is None:
            return

        # Show what would happen in dry run mode
        if dry_run:
            console.print("\n[info]Dry run - would execute:[/]")
            console.print(f"  y flow-go '{final_session_name}'")
            console.print(
                f"\n[success]✓ Would start flow session:[/] [bold]{final_session_name}[/]"
            )
            console.print(f"  [info]From task:[/] {selected_task.name}")
            return

        # Execute the flow command using flow-go directly
        system.run_flow_command("flow-go", final_session_name)
        result = f"Started flow session: {final_session_name}"

        console.print(f"\n[green]✓[/] {result}")
        console.print(f"  [info]From task:[/] {selected_task.name}")

    except ValueError as e:
        console.print(f"[red]✗[/] {str(e)}")
    except subprocess.CalledProcessError as e:
        console.print(f"[red]✗[/] Failed to start flow session: {e}")
    except FileNotFoundError:
        console.print(
            "[red]✗[/] Flow command 'y' not found. Make sure it's installed and in your PATH."
        )
    except Exception as e:
        console.print(f"[red]✗[/] Error starting flow session: {e}")


@app.command()
def snooze(
    task_num: Annotated[
        int,
        typer.Argument(help="Task number from the interesting command to snooze"),
    ],
    time_spec: Annotated[
        str,
        typer.Argument(help="Snooze duration: 'day', 'week', or 'month'"),
    ],
    dry_run: Annotated[
        bool,
        typer.Option(
            "--dry-run", help="Show what would happen without actually snoozing"
        ),
    ] = False,
):
    """Snooze a task by setting defer/due dates, clearing flag, adding 'snoozed' tag, and moving inbox tasks to 'Followups' project.

    Examples:
        omnifocus snooze 1 day
        omnifocus snooze 3 week
        omnifocus snooze 5 month
    """
    set_command_context("snooze")
    try:
        # Validate time specification
        try:
            defer_until = parse_snooze_time(time_spec)
        except ValueError as e:
            console.print(f"[red]✗[/] {str(e)}")
            return

        # Get the task
        source, selected_task = _get_task_by_number(task_num)

        console.print(f"[info]Task:[/] [bold]{selected_task.name}[/]")
        console.print(f"[info]Current project:[/] [project]{selected_task.project}[/]")

        if selected_task.tags:
            console.print(
                f"[info]Current tags:[/] [tag]{', '.join(selected_task.tags)}[/]"
            )

        # Determine new project
        new_project = selected_task.project
        if selected_task.project == "Inbox":
            new_project = "Followups"

        # Show what will happen
        console.print(
            f"\n[info]Will snooze until:[/] [date]{defer_until.strftime('%Y-%m-%d')}[/]"
        )
        console.print(
            f"[info]Will set both defer and due date to:[/] [date]{defer_until.strftime('%Y-%m-%d')}[/]"
        )
        console.print("[info]Will add tag:[/] [tag]snoozed[/]")
        console.print(f"[info]Will move to project:[/] [project]{new_project}[/]")
        if selected_task.flagged:
            console.print("[info]Will clear flag[/] (task is currently flagged)")
        console.print(
            f"[info]Will append to note:[/] Snoozed for {time_spec} until {defer_until.strftime('%Y-%m-%d')}"
        )

        if dry_run:
            console.print("\n[success]✓ Dry run complete - task would be snoozed[/]")
            return

        # Execute the snooze
        if manager.snooze_task(selected_task, defer_until, time_spec):
            console.print(
                f"\n[green]✓[/] Successfully snoozed task until {defer_until.strftime('%Y-%m-%d')}"
            )
            console.print(f"  [info]Task:[/] {selected_task.name}")
            console.print(
                f"  [info]Set defer and due date to:[/] [date]{defer_until.strftime('%Y-%m-%d')}[/]"
            )
            console.print("  [info]Added tag:[/] [tag]snoozed[/]")
            if selected_task.flagged:
                console.print("  [info]Cleared flag[/]")
            if selected_task.project == "Inbox":
                console.print(
                    "  [info]Moved from:[/] [project]Inbox[/] [info]to:[/] [project]Followups[/]"
                )
        else:
            console.print("[red]✗[/] Failed to snooze task")

    except ValueError as e:
        console.print(f"[red]✗[/] {str(e)}")
    except Exception as e:
        console.print(f"[red]✗[/] Error snoozing task: {e}")


if __name__ == "__main__":
    app()

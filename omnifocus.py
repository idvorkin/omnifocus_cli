#!/python3

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
from typing import List, Optional
from datetime import datetime
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

app = typer.Typer(
    help="OmniFocus CLI - Manage OmniFocus from the command line",
    rich_markup_mode="rich",
    no_args_is_help=True,
)


# Add a custom callback for the help option
@app.callback()
def main(
    ctx: typer.Context,
    help: bool = typer.Option(
        False, "--help", "-h", help="Show this help message and exit", is_eager=True
    ),
):
    """OmniFocus CLI - Manage OmniFocus from the command line."""
    if help:
        # Create a rich help display
        console.print(
            Panel.fit(
                "[bold cyan]OmniFocus CLI[/bold cyan]\n\n"
                "[white]A command-line interface for managing OmniFocus tasks.[/white]",
                border_style="cyan",
                title="About",
                subtitle="v0.1.0",
            )
        )

        # Display available commands
        commands_table = Table(
            title="Available Commands", box=box.ROUNDED, border_style="cyan"
        )
        commands_table.add_column("Command", style="green")
        commands_table.add_column("Description", style="white")

        # Add rows for each command
        commands_table.add_row("list", "List all tasks")
        commands_table.add_row(
            "list-grouped-tasks", "List tasks grouped by project or tag"
        )
        commands_table.add_row("flagged", "Show all flagged tasks")
        commands_table.add_row("add", "Create a new task")
        commands_table.add_row("complete", "Mark a task as completed")
        commands_table.add_row("flag", "Flag a task")
        commands_table.add_row("unflag", "Unflag a task")

        console.print(commands_table)

        # Display usage examples
        examples = Panel(
            "[bold green]Examples:[/bold green]\n\n"
            "[cyan]$ omnifocus add 'Buy groceries' --project 'Errands' --tag 'shopping'[/cyan]\n"
            "[white]Creates a new task in the Errands project with the shopping tag[/white]\n\n"
            "[cyan]$ omnifocus list-grouped-tasks --view by_project[/cyan]\n"
            "[white]Lists all tasks grouped by their projects[/white]\n\n"
            "[cyan]$ omnifocus flagged[/cyan]\n"
            "[white]Shows all flagged tasks[/white]",
            border_style="green",
            title="Usage Examples",
        )
        console.print(examples)

        raise typer.Exit()


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
        result = subprocess.run(
            ["osascript", "-l", "JavaScript", "-e", script],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout

    @staticmethod
    def open_url(url: str) -> None:
        """Open a URL using the open command."""
        subprocess.run(["open", url], check=True)

    @staticmethod
    def get_clipboard_content() -> str:
        """Get content from clipboard."""
        return pyperclip.paste()


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
    ) -> None:
        """Add a task to OmniFocus.

        Args:
            task_name: The name of the task
            project: The project to add the task to (defaults to "today")
            tags: List of tags to apply to the task
            note: Additional notes for the task
            flagged: Whether to flag the task (defaults to True)
        """
        if len(task_name) < 3:
            return

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

    def get_incomplete_tasks(self) -> List[Task]:
        """Get all incomplete tasks with their IDs, names and notes."""
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;

                const doc = of.defaultDocument;
                const tasks = doc.flattenedTasks.whose({completed: false})();

                const taskList = tasks.map(task => ({
                    id: task.id(),
                    name: task.name(),
                    note: task.note(),
                    project: task.containingProject() ? task.containingProject().name() : "No Project",
                    flagged: task.flagged(),
                    tags: Array.from(task.tags()).map(t => t.name()),
                    due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                    defer_date: task.deferDate() ? task.deferDate().toISOString() : null,
                    estimated_minutes: task.estimatedMinutes(),
                    completed: task.completed(),
                    creation_date: task.creationDate() ? task.creationDate().toISOString() : null
                }));

                return JSON.stringify(taskList);
            }
        """
        result = self.system.run_javascript(javascript)
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


@app.command()
def add_tasks_from_clipboard(
    print_only: Annotated[
        bool, typer.Option(help="Preview tasks without adding them")
    ] = False,
):
    """Add tasks from clipboard to OmniFocus (one task per line)"""
    ic(print_only)
    clipboard_content = system.get_clipboard_content()

    # Get existing tasks for duplicate checking
    existing_tasks = {task.name.lower(): task for task in manager.get_all_tasks()}

    # Split into lines and clean up each line
    lines = [line.strip() for line in clipboard_content.split("\n") if line.strip()]

    # First clean up all tasks
    cleaned_tasks = []
    for line in lines:
        task = sanitize_task_text(line)
        if task:  # Only include non-empty tasks
            cleaned_tasks.append(task)

    # Then deduplicate, keeping order
    seen = set()
    unique_tasks = []
    for task in cleaned_tasks:
        if task.lower() not in seen:  # Case-insensitive deduplication
            seen.add(task.lower())
            unique_tasks.append(task)

    if len(unique_tasks) > 25:
        print("Probably a bug you have too much clipboard")
        return

    # Print summary
    print(
        f"\nFound {len(lines)} lines, {len(cleaned_tasks)} valid tasks, {len(unique_tasks)} unique tasks"
    )
    print("\nTasks to process:")
    print("----------------")

    for task in unique_tasks:
        task_name, tags = extract_tags_from_task(task)
        if task_name.lower() in existing_tasks:
            existing_task = existing_tasks[task_name.lower()]
            print(f"• {task_name} (Already exists in project: {existing_task.project})")
        else:
            print(f"• {task_name}")
            if not print_only:
                manager.add_task(task_name, tags=tags)


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
    """Show all flagged tasks with their creation dates"""
    tasks = manager.get_flagged_tasks()

    console.print(Panel.fit("[header]Flagged Tasks[/]", border_style="red"))

    # Create a table for flagged tasks
    table = Table(box=box.ROUNDED, border_style="red", expand=True)
    table.add_column("Task", style="task")
    table.add_column("Project", style="project")
    table.add_column("Tags", style="tag")
    table.add_column("Due Date", style="date")
    table.add_column("Created", style="date")

    for task in tasks:
        # Format tags as comma-separated list
        tags_str = ", ".join(task.tags) if task.tags else ""

        # Format dates
        due_date = task.due_date.date() if task.due_date else ""
        created_date = task.creation_date.date() if task.creation_date else ""

        # Add row to table
        table.add_row(
            f"🚩 {task.name}", task.project, tags_str, str(due_date), str(created_date)
        )

    console.print(table)


@app.command()
def add(
    task: Annotated[str, typer.Argument(help="The task or URL to create a task from")],
    project: Annotated[str, typer.Option(help="Project to add the task to")] = "today",
    tags: Annotated[
        Optional[str],
        typer.Option(
            "--tag", help="Tags to add to the task (can be specified multiple times)"
        ),
    ] = None,
):
    """Create a task. If the input looks like a URL, it will fetch the page title and use it as the task name."""
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
            response = requests.get(task, timeout=10)
            response.raise_for_status()

            # Parse the HTML and extract the title
            soup = BeautifulSoup(response.text, "html.parser")
            title = soup.title.string.strip() if soup.title else task

            # Create the task with the title and URL in the note
            new_task = Task(name=title, project=project, tags=tag_list, note=task)
            manager.add_task(
                task_name=new_task.name,
                project=new_task.project,
                tags=new_task.tags,
                note=new_task.note,
            )

            # Show success message with rich formatting
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
        except Exception as e:
            # Show error message with rich formatting
            console.print(f"[danger]Error creating task from URL: {e}[/]")
            # Fallback to creating a regular task with the URL as the name
            new_task = Task(name=task, project=project, tags=tag_list)
            manager.add_task(
                task_name=new_task.name, project=new_task.project, tags=new_task.tags
            )
            console.print("[warning]Created task with URL as name instead.[/]")
    else:
        # Create a regular task
        new_task = Task(name=task, project=project, tags=tag_list)
        manager.add_task(
            task_name=new_task.name, project=new_task.project, tags=new_task.tags
        )

        # Show success message with rich formatting
        tag_display = f"[tag]{', '.join(tag_list)}[/]" if tag_list else "[dim]None[/]"
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
    all_tasks = manager.get_all_tasks()

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
    manager.add_task(
        test_name,
        project="Testing",
        tags=["testing", tag_name],
        note=f"Test task with tag: {tag_name}",
    )
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
        # Continue anyway to try the next steps

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
    manager.add_task(
        test_name,
        project="Testing",
        tags=["testing"],
        note="Test task for update functionality",
    )
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
    manager.add_task(
        test_name, project="Testing", tags=["testing"], note="Initial note"
    )
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
    manager.add_task(
        test_name, project="Testing", tags=["testing"], note="Initial note"
    )
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
def interesting():
    """Show numbered list of inbox and flagged tasks"""
    # Get both inbox and flagged tasks
    inbox_tasks = manager.get_inbox_tasks()
    flagged_tasks = manager.get_flagged_tasks()

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

    if not all_tasks:
        print("\nNo interesting tasks found!")
        return

    print("\nInteresting Tasks:")
    print("=================")

    # Print tasks with numbers
    for i, (source, task) in enumerate(all_tasks, 1):
        project = f" ({task.project})" if task.project != "Inbox" else ""
        tags = f" [{', '.join(task.tags)}]" if task.tags else ""
        due = f" [Due: {task.due_date.date()}]" if task.due_date else ""
        created = (
            f" [Created: {task.creation_date.date()}]" if task.creation_date else ""
        )
        flag = "🚩 " if task.flagged else ""
        print(f"{i:2d}. {flag}{task.name}{project}{tags}{due}{created} ({source})")


@app.command()
def test_complete():
    """Test the task completion functionality by completing a test task."""
    # Create a unique test task name
    test_name = f"TEST-COMPLETE-{uuid.uuid4().hex[:8]}"

    # Create a task
    print(f"Creating test task '{test_name}'")
    manager.add_task(
        test_name,
        project="Testing",
        tags=["testing"],
        note="Test task for completion functionality",
    )
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


@app.command()
def complete(
    task_nums: Annotated[
        str, typer.Argument(help="Space separated list of task numbers to complete")
    ] = "",
):
    """List interesting tasks and complete specified task numbers."""
    # Get all tasks
    tasks = manager.get_all_tasks()

    # If no task numbers provided, just list tasks
    if not task_nums:
        interesting()
        return

    # Parse task numbers
    try:
        nums = [int(n.strip()) for n in task_nums.split()]
    except ValueError:
        typer.echo("Invalid task numbers. Please provide space-separated integers.")
        return

    # Complete tasks
    completed = []
    errors = []
    for num in nums:
        if num < 1 or num > len(tasks):
            errors.append(f"✗ {num}: Invalid task number")
            continue

        selected_task = tasks[num - 1]
        try:
            manager.complete(selected_task)
            completed.append(f"✓ {num}: {selected_task.name}")
        except Exception as e:
            errors.append(f"✗ {num}: {selected_task.name} - {str(e)}")

    # Show results
    if completed:
        typer.echo("\nCompleted tasks:")
        for msg in completed:
            typer.echo(msg)

    if errors:
        typer.echo("\nErrors:")
        for msg in errors:
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


if __name__ == "__main__":
    app()

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
    creation_date: Optional[datetime] = None


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

    def get_all_tasks(self) -> List[Task]:
        """Get all incomplete tasks from OmniFocus."""
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;
                
                const doc = of.defaultDocument;
                const tasks = doc.flattenedTasks.whose({completed: false})();
                
                const taskList = tasks.map(task => ({
                    name: task.name(),
                    project: task.containingProject() ? task.containingProject().name() : "No Project",
                    flagged: task.flagged(),
                    tags: Array.from(task.tags()).map(t => t.name()),
                    due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                    creation_date: task.creationDate() ? task.creationDate().toISOString() : null
                }));
                
                return JSON.stringify(taskList);
            }
        """
        result = self.system.run_javascript(javascript)
        tasks_data = json.loads(result)
        return [Task.model_validate(task) for task in tasks_data]

    def get_flagged_tasks(self) -> List[Task]:
        """Get all flagged incomplete tasks."""
        javascript = """
            function run() {
                const of = Application('OmniFocus');
                of.includeStandardAdditions = true;
                
                const doc = of.defaultDocument;
                const tasks = doc.flattenedTasks.whose({completed: false, flagged: true})();
                
                const taskList = tasks.map(task => ({
                    name: task.name(),
                    project: task.containingProject() ? task.containingProject().name() : "No Project",
                    flagged: true,
                    tags: Array.from(task.tags()).map(t => t.name()),
                    due_date: task.dueDate() ? task.dueDate().toISOString() : null,
                    creation_date: task.creationDate() ? task.creationDate().toISOString() : null
                }));
                
                return JSON.stringify(taskList);
            }
        """
        result = self.system.run_javascript(javascript)
        tasks_data = json.loads(result)
        return [Task.model_validate(task) for task in tasks_data]

    def add_task(
        self, task_name: str, project: str = "today", tags: List[str] | None = None
    ) -> None:
        """Add a task to OmniFocus."""
        if len(task_name) < 3:
            return

        params = {
            "name": task_name,
            "autosave": "true",
            "flag": "true",
            "project": project,
            "tags": ",".join(tags or []),
        }

        url = "omnifocus:///add?" + urllib.parse.urlencode(
            params, quote_via=urllib.parse.quote
        )
        ic("Running", url)
        self.system.open_url(url)


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

        print("\nTasks by Project:")
        print("================")

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
        print("\nTasks by Tag:")
        print("============")

    for group in sorted_groups:
        if group not in groups or not groups[group]:
            continue

        task_count = len(groups[group])
        print(f"\n{group} ({task_count}):")
        for task in groups[group]:
            project = f" ({task.project})" if view == View.by_tag else ""
            flag = "🚩 " if task.flagged else ""
            tags = (
                f" [{', '.join(task.tags)}]"
                if view == View.by_project and task.tags
                else ""
            )
            due = f" [Due: {task.due_date.date()}]" if task.due_date else ""
            print(f"  • {flag}{task.name}{project}{tags}{due}")


@app.command(name="flagged")
def list_flagged():
    """Show all flagged tasks with their creation dates"""
    tasks = manager.get_flagged_tasks()

    print("\nFlagged Tasks:")
    print("=============")
    for task in tasks:
        project = f" ({task.project})"
        tags = f" [{', '.join(task.tags)}]" if task.tags else ""
        due = f" [Due: {task.due_date.date()}]" if task.due_date else ""
        created = (
            f" [Created: {task.creation_date.date()}]" if task.creation_date else ""
        )
        print(f"• {task.name}{project}{tags}{due}{created}")


if __name__ == "__main__":
    app()

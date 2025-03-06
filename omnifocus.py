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
from typing import List, Optional, Union
from datetime import datetime
import requests
from bs4 import BeautifulSoup
import uuid
import time

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
        conditions_str = ", ".join(f"{k}: {str(v).lower()}" for k, v in filter_conditions.items())
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
        return self._get_tasks_with_filter({'completed': False})

    def get_flagged_tasks(self) -> List[Task]:
        """Get all flagged incomplete tasks."""
        return self._get_tasks_with_filter({'completed': False, 'flagged': True})

    def add_task(
        self,
        task_name: str,
        project: str = "today",
        tags: List[str] | None = None,
        note: str = "",
        flagged: bool = True
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
                    task.name = "{new_name.replace('"', '\"')}";
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
                    task.note = "{note.replace('"', '\"')}";
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
                    task.note = currentNote + separator + "{note_text.replace('"', '\"')}";
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


@app.command()
def add(
    task: Annotated[str, typer.Argument(help="The task or URL to create a task from")],
    project: Annotated[str, typer.Option(help="Project to add the task to")] = "today",
    tags: Annotated[Optional[str], typer.Option("--tag", help="Tags to add to the task (can be specified multiple times)")] = None,
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
            response = requests.get(task, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()

            # Parse the HTML and extract the title
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else task

            # Create the task with the URL as a note
            params = {
                "name": title,
                "note": f"Source: {task}",
                "autosave": "true",
                "flag": "true",
                "project": project,
                "tags": ",".join(tag_list),
            }

        except requests.exceptions.RequestException as e:
            print(f"Error fetching URL: {e}")
            return
        except Exception as e:
            print(f"Error processing URL: {e}")
            return
    else:
        # Regular task
        if len(task) < 3:
            print("Task text too short (minimum 3 characters)")
            return

        params = {
            "name": task,
            "autosave": "true",
            "flag": "true",
            "project": project,
            "tags": ",".join(tag_list),
        }

    omnifocus_url = "omnifocus:///add?" + urllib.parse.urlencode(
        params, quote_via=urllib.parse.quote
    )
    ic("Creating task", task)
    system.open_url(omnifocus_url)


@app.command()
def fixup_url():
    """Find tasks that have empty names or URLs as names, and update them with webpage titles."""
    all_tasks = manager.get_all_tasks()

    # Find tasks with URLs in notes or as names
    url_pattern = r'(https?://[^\s)"]+)'
    tasks_to_update = []
    for task in all_tasks:
        # Check if there's a URL in the note and the task name is empty
        if hasattr(task, 'note') and task.note:
            urls = re.findall(url_pattern, task.note)
            if urls and not task.name.strip():  # Empty name with URL in note
                tasks_to_update.append((task, urls[0], task.note))  # Take the first URL found
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
            response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()

            # Parse the HTML and extract the title
            soup = BeautifulSoup(response.text, 'html.parser')
            title = soup.title.string.strip() if soup.title else url

            # Update the task name
            manager.update_name(task, title)
            print(f"✓ Updated task with title: {title}")

        except requests.exceptions.RequestException as e:
            print(f"✗ Error fetching URL: {e}")
        except Exception as e:
            print(f"✗ Error processing task: {e}")


@app.command()
def test_tag(tag_name: Annotated[str, typer.Argument(help="Name of tag to create and assign")]):
    """Test tag creation and assignment by creating a test task with the specified tag"""
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"
    manager.add_task(test_name, tags=[tag_name], note=f"Test task with tag: {tag_name}")
    print(f"Created test task '{test_name}' with tag '{tag_name}'")
    
    # Get tasks to verify tag was assigned
    tasks = manager.get_all_tasks()
    test_task = next((task for task in tasks if task.name == test_name), None)
    
    if test_task and tag_name in test_task.tags:
        print(f"✓ Successfully verified tag '{tag_name}' was assigned to task")
    else:
        print(f"✗ Could not verify tag '{tag_name}' was assigned to task")


@app.command()
def test_update():
    """Test task name update functionality by creating a task and updating its name"""
    # First create a task with a unique name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"
    manager.add_task(test_name, note="This is a test task")

    # Get all tasks and find our test task
    all_tasks = manager.get_all_tasks()
    test_task = next((task for task in all_tasks if task.name == test_name), None)

    if test_task:
        # Update the task name using the Task object
        new_name = f"UPDATED-{uuid.uuid4().hex[:8]}"
        print(f"Updating task name from '{test_name}' to '{new_name}'")
        manager.update_name(test_task, new_name)
    else:
        print("Could not find test task to update")


@app.command()
def test_append():
    """Test appending to a task's note by creating a task and appending to its note"""
    # First create a task with a unique name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"
    manager.add_task(test_name, note="This is the initial note")
    
    # Get all tasks and find our test task
    all_tasks = manager.get_all_tasks()
    test_task = next((task for task in all_tasks if task.name == test_name), None)
    
    if test_task:
        # Append to the task note
        append_text = f"Appended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        print(f"Appending to task '{test_name}' note: '{append_text}'")
        print(f"Original note: '{test_task.note}'")
        
        # Use the append_to_task method
        result = manager.append_to_task(test_task, append_text)
        print(f"Result: {result}")
        
        # Verify the note was updated
        updated_tasks = manager.get_all_tasks()
        updated_task = next((task for task in updated_tasks if task.name == test_name), None)
        if updated_task:
            print(f"Updated note: '{updated_task.note}'")
    else:
        print("Could not find test task to update")


@app.command()
def test_append_pydantic():
    """Test appending to a task's note using a Pydantic Task object"""
    # First create a task with a unique name
    test_name = f"TEST-{uuid.uuid4().hex[:8]}"
    manager.add_task(test_name, note="This is the initial note")
    
    # Get all tasks and find our test task
    all_tasks = manager.get_all_tasks()
    test_task = next((task for task in all_tasks if task.name == test_name), None)
    
    if test_task:
        # Append to the task note
        append_text = f"Appended at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        print(f"Appending to task '{test_name}' note: '{append_text}'")
        
        # Use the append_to_task method with a Pydantic Task object
        result = manager.append_to_task(test_task, append_text)
        print(f"Result: {result}")
        
        # Verify the note was updated by getting the task again
        updated_tasks = manager.get_all_tasks()
        updated_task = next((task for task in updated_tasks if task.name == test_name), None)
        if updated_task:
            print(f"Updated note: '{updated_task.note}'")
    else:
        print("Could not find test task to update")


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
        created = f" [Created: {task.creation_date.date()}]" if task.creation_date else ""
        flag = "🚩 " if task.flagged else ""
        print(f"{i:2d}. {flag}{task.name}{project}{tags}{due}{created} ({source})")


@app.command()
def test_complete():
    """Test the task completion functionality by completing a test task."""
    # First create a test task
    test_task_name = f"Test task {uuid.uuid4()}"
    manager.add_task(test_task_name, project="today", flagged=True)
    
    # Get all tasks and find our test task
    all_tasks = manager.get_all_tasks()
    test_task = next((task for task in all_tasks if task.name == test_task_name), None)
    
    if test_task:
        try:
            result = manager.complete(test_task)
            typer.echo(f"Successfully completed test task: {test_task_name}")
            typer.echo(f"Result: {result}")
        except Exception as e:
            typer.echo(f"Error completing task: {str(e)}", err=True)
    else:
        typer.echo("Could not find the test task. It may not have been created properly.", err=True)


@app.command()
def complete(
    task_nums: Annotated[str, typer.Argument(help="Space separated list of task numbers to complete")] = "",
):
    """List interesting tasks and complete specified task numbers."""
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
        created = f" [Created: {task.creation_date.date()}]" if task.creation_date else ""
        flag = "🚩 " if task.flagged else ""
        print(f"{i:2d}. {flag}{task.name}{project}{tags}{due}{created} ({source})")

    # If no task numbers provided, prompt for input
    if not task_nums:
        try:
            task_nums = typer.prompt("\nEnter task numbers to complete (space separated, or Ctrl+C to cancel)")
        except (KeyboardInterrupt, typer.Abort):
            typer.echo("\nOperation cancelled")
            return

    # Process task numbers
    try:
        numbers = [int(num) for num in task_nums.split()]
        invalid_nums = [num for num in numbers if num < 1 or num > len(all_tasks)]
        
        if invalid_nums:
            typer.echo(f"Invalid task numbers: {invalid_nums}. Please enter numbers between 1 and {len(all_tasks)}")
            return
        
        # Complete each task
        completed = []
        errors = []
        
        for num in numbers:
            selected_task = all_tasks[num - 1][1]
            
            try:
                result = manager.complete(selected_task)
                completed.append(f"✓ {num}: {selected_task.name}")
            except Exception as e:
                errors.append(f"Error completing task {num}: {selected_task.name} - {str(e)}")
        
        # Print results
        if completed:
            typer.echo("\nCompleted tasks:")
            for msg in completed:
                typer.echo(msg)
                
        if errors:
            typer.echo("\nErrors:")
            for msg in errors:
                typer.echo(msg)
                
    except ValueError as e:
        typer.echo("Please enter valid numbers separated by spaces")
        return
    except Exception as e:
        typer.echo(f"Error: {str(e)}")
        return


@app.command(name="list-tags")
def list_tags():
    """List all tags in OmniFocus."""
    system = OSXSystem()
    manager = OmniFocusManager(system)
    tags = manager.get_all_tags()
    for tag in sorted(tags):
        typer.echo(tag)

@app.command(name="cleanup-tags")
def cleanup_tags():
    """Delete all empty tags and 'Untitled Tag' tags from OmniFocus."""
    system = OSXSystem()
    manager = OmniFocusManager(system)
    count = manager.delete_untitled_tags()
    if count == 0:
        typer.echo("No empty or untitled tags found.")
    else:
        typer.echo(f"Deleted {count} empty/untitled tag{'s' if count > 1 else ''}.")


if __name__ == "__main__":
    app()

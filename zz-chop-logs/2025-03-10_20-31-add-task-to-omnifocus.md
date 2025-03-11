## SpecStory

## Add Task to OmniFocus (3/10/2025, 8:31:39 PM)

_**User**_

Try running 

❯ omnifocus add "Setup Ant Traps in Office"

---

_**Assistant**_

I'll help you run the `omnifocus add` command to add a task to OmniFocus. Let me first check if this command is available in your system.

---

_****_

```bash
which omnifocus
```

```
$HOME/gits/omnifocus_cli/.venv/bin/omnifocus

```

---

_****_

Great! I can see that the `omnifocus` command is available in your virtual environment. Now let's run the command you requested to add a task to OmniFocus:

---

_****_

```bash
omnifocus add "Setup Ant Traps in Office"
```

```
❯ omnifocus add "Setup Ant Traps in Office"
╭─────────────────────────────────── Traceback (most recent call last) ────────────────────────────────────╮
│ $HOME/gits/omnifocus_cli/omnifocus.py:952 in add                                               │
│                                                                                                          │
│    949 │   else:                                                                                         │
│    950 │   │   # Create a regular task                                                                   │
│    951 │   │   new_task = Task(name=task, project=project, tags=tag_list)                                │
│ ❱  952 │   │   manager.create_task(new_task)                                                             │
│    953 │   │                                                                                             │
│    954 │   │   # Show success message with rich formatting                                               │
│    955 │   │   tag_display = f"[tag]{', '.join(tag_list)}[/]" if tag_list else "[dim]None[/]"            │
│                                                                                                          │
│ ╭───────────────────── locals ─────────────────────╮                                                     │
│ │ new_task = Task(                                 │                                                     │
│ │            │   name='Setup Ant Traps in Office', │                                                     │
│ │            │   project='today',                  │                                                     │
│ │            │   flagged=False,                    │                                                     │
│ │            │   tags=[],                          │                                                     │
│ │            │   due_date=None,                    │                                                     │
│ │            │   defer_date=None,                  │                                                     │
│ │            │   estimated_minutes=None,           │                                                     │
│ │            │   completed=False,                  │                                                     │
│ │            │   creation_date=None,               │                                                     │
│ │            │   id=None,                          │                                                     │
│ │            │   note=None                         │                                                     │
│ │            )                                     │                                                     │
│ │  project = 'today'                               │                                                     │
│ │ tag_list = []                                    │                                                     │
│ │     tags = None                                  │                                                     │
│ │     task = 'Setup Ant Traps in Office'           │                                                     │
│ ╰──────────────────────────────────────────────────╯                                                     │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────╯
AttributeError: 'OmniFocusManager' object has no attribute 'create_task'

igors-Mac-mini in omnifocus_cli on  main [$!] via 🐍 v3.13.0 (omnifocus_cli) on ☁️   
❯
```

---

_****_

I see there's an error when running the command. The error shows that the `OmniFocusManager` object doesn't have a `create_task` method, which is being called in the code. Let's examine the code to understand what's happening and how to fix it.

---

_****_

Read file: undefined

---

_****_

Let's look at the `OmniFocusManager` class to see what methods are available for creating tasks:

---

_****_

Read file: undefined

---

_****_

Now let's look at the `add` command implementation to see how it's supposed to work:

---

_****_

Read file: undefined

---

_****_

I see the issue now. The code is trying to use a method called `create_task()` on the `OmniFocusManager` object, but that method doesn't exist. Instead, the `OmniFocusManager` class has an `add_task()` method.

Let's fix this by editing the file to use the correct method:

---

_****_

```diff
              # Create the task with the title and URL in the note
              new_task = Task(name=title, project=project, tags=tag_list, note=task)
-             manager.create_task(new_task)
+             manager.add_task(task_name=new_task.name, project=new_task.project, tags=new_task.tags)
  
              # Show success message with rich formatting
              # Fallback to creating a regular task with the URL as the name
              new_task = Task(name=task, project=project, tags=tag_list)
-             manager.create_task(new_task)
+             manager.add_task(task_name=new_task.name, project=new_task.project, tags=new_task.tags)
              console.print("[warning]Created task with URL as name instead.[/]")
      else:
          # Create a regular task
          new_task = Task(name=task, project=project, tags=tag_list)
-         manager.create_task(new_task)
+         manager.add_task(task_name=new_task.name, project=new_task.project, tags=new_task.tags)
  
          # Show success message with rich formatting
```

---

_****_

I need to fix one more instance of `create_task` that was missed in the edit:

---

_****_

Read file: undefined

---

_****_

Great! All instances of `create_task` have been replaced with `add_task`. However, I notice that we're not passing the `note` parameter when it's available. Let's fix that for the URL case:

---

_****_

```diff
              # Create the task with the title and URL in the note
              new_task = Task(name=title, project=project, tags=tag_list, note=task)
-             manager.add_task(task_name=new_task.name, project=new_task.project, tags=new_task.tags)
+             manager.add_task(task_name=new_task.name, project=new_task.project, tags=new_task.tags, note=new_task.note)
  
              # Show success message with rich formatting
```

---

_****_

Now let's try running the command again:

---

_****_

```bash
omnifocus add "Setup Ant Traps in Office"
```

```
❯ omnifocus add "Setup Ant Traps in Office"
ic| "Running": 'Running'
    url: 'omnifocus:///add?name=Setup%20Ant%20Traps%20in%20Office&autosave=true&project=today&flag=true'
╭────── Task Created ───────╮
│ ✓ Created task:           │
│ Setup Ant Traps in Office │
│ Project: today            │
│ Tags: None                │
╰───────────────────────────╯

igors-Mac-mini in omnifocus_cli on  main [$!] via 🐍 v3.13.0 (omnifocus_cli) on ☁️   
❯
```

---

_****_

Great! The command has successfully executed and added the task "Setup Ant Traps in Office" to your OmniFocus. The task has been added to the "today" project (which is the default) and has been flagged (which is also the default behavior).

The issue was that the code was trying to use a method called `create_task()` on the `OmniFocusManager` object, but that method didn't exist. Instead, the `OmniFocusManager` class has an `add_task()` method. I fixed this by replacing all instances of `manager.create_task(new_task)` with `manager.add_task()` and passing the appropriate parameters from the Task object.

Is there anything else you'd like to do with your OmniFocus CLI?

---



---


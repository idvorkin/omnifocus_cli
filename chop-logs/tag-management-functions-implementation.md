## SpecStory

## Tag Management Functions Implementation (2/15/2025, 9:12:46 AM)

_**User**_

Add a function to list all tags, and another one to erase all tags titled "Untitled Tag"

---

_**Assistant**_

I'll help you add these functions. First, let me check the existing codebase to understand the current implementation and where to add these new functions.

---

_\*\*\*\*_

Read file: omnifocus.py

---

_\*\*\*\*_

Now I'll add the two new functions to list all tags and erase "Untitled Tag" tags. I'll add these functions to the `OmniFocusManager` class.

---

_\*\*\*\*_

```diff
          return self.system.run_javascript(javascript)

+     def get_all_tags(self) -> List[str]:
+         """Get all tags from OmniFocus.
+
+         Returns:
+             List[str]: List of all tag names in OmniFocus
+         """
+         javascript = """
+             function run() {
+                 const of = Application('OmniFocus');
+                 of.includeStandardAdditions = true;
+
+                 const doc = of.defaultDocument;
+                 const tags = doc.flattenedTags();
+
+                 const tagNames = tags.map(tag => tag.name());
+                 return JSON.stringify(tagNames);
+             }
+         """
+         result = self.system.run_javascript(javascript)
+         return json.loads(result)
+
+     def delete_untitled_tags(self) -> int:
+         """Delete all tags titled 'Untitled Tag'.
+
+         Returns:
+             int: Number of tags deleted
+         """
+         javascript = """
+             function run() {
+                 const of = Application('OmniFocus');
+                 of.includeStandardAdditions = true;
+
+                 const doc = of.defaultDocument;
+                 const untitledTags = doc.flattenedTags.whose({name: 'Untitled Tag'})();
+                 const count = untitledTags.length;
+
+                 untitledTags.forEach(tag => {
+                     tag.delete();
+                 });
+
+                 return count;
+             }
+         """
+         result = self.system.run_javascript(javascript)
+         return int(result)
+

  def sanitize_task_text(task: str) -> str:
```

---

_\*\*\*\*_

Now I'll add CLI commands to expose these new functions to the user. I'll add them to the bottom of the file with the other commands.

---

_\*\*\*\*_

```diff
          return

+
+ @app.command(name="list-tags")
+ def list_tags():
+     """List all tags in OmniFocus."""
+     system = OSXSystem()
+     manager = OmniFocusManager(system)
+     tags = manager.get_all_tags()
+     for tag in sorted(tags):
+         typer.echo(tag)
+
+ @app.command(name="cleanup-tags")
+ def cleanup_tags():
+     """Delete all 'Untitled Tag' tags from OmniFocus."""
+     system = OSXSystem()
+     manager = OmniFocusManager(system)
+     count = manager.delete_untitled_tags()
+     if count == 0:
+         typer.echo("No untitled tags found.")
+     else:
+         typer.echo(f"Deleted {count} untitled tag{'s' if count > 1 else ''}.")
+

  if __name__ == "__main__":
```

---

_\*\*\*\*_

I've added two new features to your OmniFocus CLI:

1. A `get_all_tags()` method in the `OmniFocusManager` class that retrieves all tags from OmniFocus, exposed through the `list-tags` command.
2. A `delete_untitled_tags()` method that finds and deletes all tags titled "Untitled Tag", exposed through the `cleanup-tags` command.

You can now use these commands as follows:

- To list all tags: `python omnifocus.py list-tags`
- To delete untitled tags: `python omnifocus.py cleanup-tags`

The `cleanup-tags` command will tell you how many untitled tags were deleted, or let you know if none were found.

Would you like me to add any additional features or make any modifications to these new functions?

---

_**User**_

Hymn, I think untitled might be blank, erase ones with blank titles

---

_**Assistant**_

I'll modify the code to handle both "Untitled Tag" and blank/empty tag names. Let me update the `delete_untitled_tags` method and its corresponding CLI command.

---

_\*\*\*\*_

```diff

      def delete_untitled_tags(self) -> int:
-         """Delete all tags titled 'Untitled Tag'.
+         """Delete all tags titled 'Untitled Tag' or with empty names.

          Returns:

                  const doc = of.defaultDocument;
+                 const emptyTags = doc.flattenedTags.whose({name: ''})();
                  const untitledTags = doc.flattenedTags.whose({name: 'Untitled Tag'})();
-                 const count = untitledTags.length;
+
+                 const count = emptyTags.length + untitledTags.length;
+
+                 emptyTags.forEach(tag => {
+                     tag.delete();
+                 });

                  untitledTags.forEach(tag => {
  @app.command(name="cleanup-tags")
  def cleanup_tags():
-     """Delete all 'Untitled Tag' tags from OmniFocus."""
+     """Delete all empty tags and 'Untitled Tag' tags from OmniFocus."""
      system = OSXSystem()
      manager = OmniFocusManager(system)
      count = manager.delete_untitled_tags()
      if count == 0:
-         typer.echo("No untitled tags found.")
+         typer.echo("No empty or untitled tags found.")
      else:
-         typer.echo(f"Deleted {count} untitled tag{'s' if count > 1 else ''}.")
+         typer.echo(f"Deleted {count} empty/untitled tag{'s' if count > 1 else ''}.")


```

---

_\*\*\*\*_

I've updated the code to handle both cases:

1. Tags with empty names (blank titles)
2. Tags named "Untitled Tag"

The `delete_untitled_tags` method now:

- Finds tags with empty names using `name: ''`
- Finds tags named "Untitled Tag"
- Deletes both types of tags
- Returns the total count of deleted tags

The CLI command's messages have been updated to reflect that it handles both empty and untitled tags.

You can run the cleanup command the same way:

```bash
python omnifocus.py cleanup-tags
```

Would you like me to make any other changes to how this handles empty or untitled tags?

---

---

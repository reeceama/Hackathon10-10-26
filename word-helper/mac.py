"""Word for Mac, driven with AppleScript (osascript).

Ranges are character positions in the document's text, as Word counts them. Each call is
one short script; text is passed as arguments, never pasted into the script, so nothing in
a document can change what runs.
"""

import subprocess
from typing import List, Optional, Tuple

COLOURS = {"supports": "bright green", "warn": "yellow", "contradicts": "red"}


def _run(script: str, *args: str) -> str:

    result = subprocess.run(["osascript", "-e", script, *map(str, args)],
                            capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return result.stdout.rstrip("\n")


class MacWord:

    def available(self) -> bool:

        """
        Word is open with a document. Never starts Word itself.
        """

        try:
            return _run('''
                if application "Microsoft Word" is not running then return "no"
                tell application "Microsoft Word" to if (count of (every document)) is 0 then return "no"
                return "yes"''') == "yes"
        except RuntimeError:
            return False

    def document(self) -> Optional[Tuple[str, str]]:

        """
        (name, text) of the document being written in.
        """

        try:
            out = _run('''
                tell application "Microsoft Word"
                    set d to active document
                    return (full name of d) & (ASCII character 0) & (content of text object of d)
                end tell''')
        except RuntimeError:
            return None
        name, _, text = out.partition("\x00")
        return name, text

    def text_at(self, start: int, end: int) -> str:

        return _run('''on run argv
            tell application "Microsoft Word" to return content of (create range active document start (item 1 of argv as integer) end (item 2 of argv as integer))
            end run''', start, end)

    def mark(self, start: int, end: int, kind: str) -> None:

        _run(f'''on run argv
            tell application "Microsoft Word"
                set highlight color index of (create range active document start (item 1 of argv as integer) end (item 2 of argv as integer)) to {COLOURS[kind]}
            end tell
            end run''', start, end)

    def insert(self, position: int, text: str) -> None:

        _run('''on run argv
            tell application "Microsoft Word"
                set r to create range active document start (item 1 of argv as integer) end (item 1 of argv as integer)
                set content of r to item 2 of argv
            end tell
            end run''', position, text)

    def comment(self, start: int, end: int, text: str) -> None:

        _run('''on run argv
            tell application "Microsoft Word"
                set r to create range active document start (item 1 of argv as integer) end (item 2 of argv as integer)
                make new Word comment at r with properties {comment text:(item 3 of argv)}
            end tell
            end run''', start, end, text)

    def comments(self) -> List[Tuple[int, int, str]]:

        """
        (start, end, text) of every comment, so Referee doesn't add the same one twice.
        """

        # Built as one string with ASCII separators: inside a Word block, words like "end", "tab" and "found" are Word's own terms.
        out = _run('''
            tell application "Microsoft Word"
                set d to active document
                set listing to ""
                repeat with i from 1 to (count of Word comments of d)
                    set c to Word comment i of d
                    set r to scope of c
                    set listing to listing & ((start of content of r) as text) & (ASCII character 9) & ((end of content of r) as text) & (ASCII character 9) & (content of (comment text of c)) & (ASCII character 0)
                end repeat
                return listing
            end tell''')
        found = []
        for line in filter(None, out.split("\x00")):
            start, end, text = line.split("\t", 2)
            found.append((int(start), int(end), text))
        return found

    def append(self, text: str) -> None:

        """
        Adds text at the very end of the document.
        """

        _run('''on run argv
            tell application "Microsoft Word"
                set d to active document
                set n to end of content of text object of d
                set content of (create range d start (n - 1) end (n - 1)) to item 1 of argv
            end tell
            end run''', text)

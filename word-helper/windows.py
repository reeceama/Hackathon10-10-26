"""Word for Windows, driven through its COM automation interface (pywin32).

Ranges are character positions in the document's text, as Word counts them, the same as
on the Mac.
"""

from typing import List, Optional, Tuple

import pythoncom
import win32com.client

COLOURS = {"supports": 4, "warn": 7, "contradicts": 6}  # wdBrightGreen, wdYellow, wdRed


class WindowsWord:

    def __init__(self):

        pythoncom.CoInitialize()

    def _word(self):

        # Attach to a running Word only; never start one.
        return win32com.client.GetActiveObject("Word.Application")

    def _doc(self):

        return self._word().ActiveDocument

    def available(self) -> bool:

        try:
            return self._word().Documents.Count > 0
        except Exception:
            return False

    def document(self) -> Optional[Tuple[str, str]]:

        try:
            doc = self._doc()
            return doc.FullName, doc.Content.Text
        except Exception:
            return None

    def text_at(self, start: int, end: int) -> str:

        return self._doc().Range(start, end).Text

    def mark(self, start: int, end: int, kind: str) -> None:

        self._doc().Range(start, end).HighlightColorIndex = COLOURS[kind]

    def insert(self, position: int, text: str) -> None:

        self._doc().Range(position, position).InsertAfter(text)

    def comment(self, start: int, end: int, text: str) -> None:

        doc = self._doc()
        doc.Comments.Add(doc.Range(start, end), text)

    def comments(self) -> List[Tuple[int, int, str]]:

        return [(c.Scope.Start, c.Scope.End, c.Range.Text) for c in self._doc().Comments]

    def append(self, text: str) -> None:

        doc = self._doc()
        end = doc.Content.End - 1
        doc.Range(end, end).InsertAfter(text)

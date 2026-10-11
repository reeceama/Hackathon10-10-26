"""Word for Windows, driven through its COM automation interface (pywin32).

Ranges are character positions in the document's text, as Word counts them, the same as
on the Mac.
"""

from typing import List, Optional, Tuple

import pythoncom
import win32com.client

COLOURS = {"supports": 4, "warn": 7, "contradicts": 6, "none": 0}  # wdBrightGreen, wdYellow, wdRed, wdNoHighlight
# wdUnderlineSingle 1, wdUnderlineWavy 11, wdUnderlineNone 0, with RGB colours.
UNDERLINES = {"supports": (1, (40, 167, 69)), "warn": (11, (230, 160, 0)), "contradicts": (11, (220, 53, 69)), "none": (0, None)}


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

    def underline(self, start: int, end: int, kind: str) -> None:

        style, colour = UNDERLINES[kind]
        font = self._doc().Range(start, end).Font
        font.Underline = style
        if colour is not None:
            red, green, blue = colour
            font.UnderlineColor = red + green * 256 + blue * 65536

    def insert(self, position: int, text: str) -> None:

        self._doc().Range(position, position).InsertAfter(text)

    def comment(self, start: int, end: int, text: str) -> None:

        doc = self._doc()
        doc.Comments.Add(doc.Range(start, end), text)

    def comments(self) -> List[Tuple[int, int, str]]:

        return [(c.Scope.Start, c.Scope.End, c.Range.Text) for c in self._doc().Comments]

    def page_break(self) -> None:

        """
        Adds a page break at the very end, with Word's own command (wdPageBreak), not a typed
        page-break character.
        """

        doc = self._doc()
        end = doc.Content.End - 1
        doc.Range(end, end).InsertBreak(7)

    def append(self, text: str) -> None:

        doc = self._doc()
        end = doc.Content.End - 1
        doc.Range(end, end).InsertAfter(text)

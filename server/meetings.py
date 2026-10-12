"""Meeting notes: supervisor meetings and group project meetings, kept by project.

Each meeting has a date, title, attendees, notes, decisions and action points (what, who, by
when, done). Action points not yet done are carried into the next meeting, and a project's log
exports as Markdown (to paste into Teams or a shared document) or LaTeX (for Overleaf), so a
group can share it.

A project can be linked to its shared workspace folder (a GitHub repository or shared drive);
its notes/decision-notes.md and notes/who-did-what.md are then rewritten whenever its meetings
change, so the record a group project asks for is always current.
"""

import json
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional


class Meetings:

    def __init__(self, path: Path):

        self.path = path
        self.workspaces_path = path.with_name(path.stem + "-workspaces.json")
        try:
            self.items: List[Dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []
        try:
            self.workspaces: Dict[str, str] = json.loads(self.workspaces_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.workspaces = {}

    def _save(self, projects: Optional[set] = None) -> None:

        self.path.write_text(json.dumps(self.items, indent=1), encoding="utf-8")
        for project in projects if projects is not None else set(self.workspaces):
            self.write_notes(project)

    def set_workspace(self, project: str, folder: str) -> Dict:

        """
        Links a project to its shared workspace folder ("" to unlink), and writes its notes there.
        """

        if folder:
            self.workspaces[project] = folder
        else:
            self.workspaces.pop(project, None)
        self.workspaces_path.write_text(json.dumps(self.workspaces, indent=1), encoding="utf-8")
        return {"folder": folder, "written": self.write_notes(project) if folder else []}

    def write_notes(self, project: str) -> List[str]:

        """
        Rewrites notes/decision-notes.md and notes/who-did-what.md in the project's workspace.
        """

        folder = self.workspaces.get(project)
        if not folder or not Path(folder).is_dir():
            return []
        notes = Path(folder) / "notes"
        notes.mkdir(exist_ok=True)
        written = []
        for name in ("decision-notes", "who-did-what"):
            target = notes / f"{name}.md"
            text = self.export(project, name)
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                target.write_text(text, encoding="utf-8")
            written.append(str(target))
        return written

    def all(self, project: Optional[str] = None) -> List[Dict]:

        """
        Newest first. project: None for every meeting, "" for meetings in no project.
        """

        found = [m for m in self.items if project is None or (m.get("project") or "") == project]
        return sorted(found, key=lambda m: (m.get("date") or "", m.get("created") or 0), reverse=True)

    def save(self, meeting: Dict) -> Dict:

        """
        Adds a meeting, or replaces the one with the same id.
        """

        clean = {
            "id": meeting.get("id") or uuid.uuid4().hex,
            "project": meeting.get("project") or "",
            "date": meeting.get("date") or date.today().isoformat(),
            "title": (meeting.get("title") or "").strip(),
            "attendees": (meeting.get("attendees") or "").strip(),
            "notes": meeting.get("notes") or "",
            "decisions": meeting.get("decisions") or "",
            "actions": [{"id": a.get("id") or uuid.uuid4().hex, "text": (a.get("text") or "").strip(),
                         "who": (a.get("who") or "").strip(), "due": (a.get("due") or "").strip(), "done": bool(a.get("done")),
                         **self._todoist(meeting.get("id"), a)}
                        for a in meeting.get("actions") or []],
            "created": meeting.get("created") or time.time(),
        }
        old = next((m.get("project") or "" for m in self.items if m["id"] == clean["id"]), clean["project"])
        self.items = [m for m in self.items if m["id"] != clean["id"]] + [clean]
        self._save({clean["project"], old})
        return clean

    def _todoist(self, meeting_id: Optional[str], action: Dict) -> Dict:

        """
        An action point's link to its Todoist task. The app doesn't send these back, so they're
        kept from the saved copy of the same action point.
        """

        saved = next((a for m in self.items if m["id"] == meeting_id for a in m.get("actions", []) if a.get("id") == action.get("id")), {})
        return {k: action.get(k, saved.get(k)) for k in ("todoist_id", "todoist_sent", "todoist_gone") if action.get(k, saved.get(k)) is not None}

    def delete(self, meeting_id: str) -> bool:

        before = len(self.items)
        project = next((m.get("project") or "" for m in self.items if m["id"] == meeting_id), "")
        self.items = [m for m in self.items if m["id"] != meeting_id]
        self._save({project})
        return len(self.items) < before

    def rename_project(self, old: str, new: Optional[str]) -> None:

        for meeting in self.items:
            if meeting.get("project") == old:
                meeting["project"] = new or ""
        if old in self.workspaces:
            folder = self.workspaces.pop(old)
            if new:
                self.workspaces[new] = folder
            self.workspaces_path.write_text(json.dumps(self.workspaces, indent=1), encoding="utf-8")
        self._save()

    def export(self, project: Optional[str], format: str = "markdown") -> str:

        """
        The project's meetings, oldest first, as Markdown or LaTeX.
        """

        meetings = list(reversed(self.all(project)))
        name = project if project else "All meetings" if project is None else "Meetings"
        if format == "decision-notes":
            return _decisions(name, meetings)
        if format == "who-did-what":
            return _who(name, meetings)
        return _latex(name, meetings) if format == "latex" else _markdown(name, meetings)


def _when(day: str) -> str:

    try:
        return date.fromisoformat(day).strftime("%-d %B %Y")
    except ValueError:
        return day


def _markdown(name: str, meetings: List[Dict]) -> str:

    lines = [f"# Meeting log: {name}", ""]
    for m in meetings:
        lines += [f"## {_when(m['date'])}" + (f": {m['title']}" if m["title"] else ""), ""]
        if m["attendees"]:
            lines += [f"**Attendees:** {m['attendees']}", ""]
        if m["notes"].strip():
            lines += ["**Notes**", "", m["notes"].strip(), ""]
        if m["decisions"].strip():
            lines += ["**Decisions**", "", m["decisions"].strip(), ""]
        if m["actions"]:
            lines += ["**Action points**", ""]
            for a in m["actions"]:
                extra = ", ".join(v for v in [a["who"], f"by {a['due']}" if a["due"] else ""] if v)
                lines.append(f"- [{'x' if a['done'] else ' '}] {a['text']}" + (f" ({extra})" if extra else ""))
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _decisions(name: str, meetings: List[Dict]) -> str:

    """
    decision-notes.md: what was decided, when, and (from the notes) why, meeting by meeting.
    """

    lines = [f"# Decision notes: {name}", ""]
    for m in meetings:
        if not m["decisions"].strip():
            continue
        lines += [f"## {_when(m['date'])}" + (f": {m['title']}" if m["title"] else ""), ""]
        if m["attendees"]:
            lines += [f"Present: {m['attendees']}", ""]
        lines += ["**Decided**", "", m["decisions"].strip(), ""]
        if m["notes"].strip():
            lines += ["**Discussion**", "", m["notes"].strip(), ""]
    if len(lines) == 2:
        lines.append("No decisions recorded yet.")
    return "\n".join(lines).rstrip() + "\n"


def _who(name: str, meetings: List[Dict]) -> str:

    """
    who-did-what.md: each person's action points, done and still to do, with the meeting they came from.
    """

    people: Dict[str, List[str]] = {}
    for m in meetings:
        for a in m["actions"]:
            if not a["text"]:
                continue
            for person in [p.strip() for p in re.split(r",|&|\band\b", a["who"]) if p.strip()] or ["Unassigned"]:
                due = f", due {a['due']}" if a["due"] else ""
                people.setdefault(person, []).append(f"- [{'x' if a['done'] else ' '}] {a['text']} (from {_when(m['date'])}{due})")
    lines = [f"# Who did what: {name}", ""]
    for person in sorted(people, key=lambda p: (p == "Unassigned", p.lower())):
        lines += [f"## {person}", "", *people[person], ""]
    if len(lines) == 2:
        lines.append("No action points recorded yet.")
    return "\n".join(lines).rstrip() + "\n"


def _tex(text: str) -> str:

    replacements = {"\\": r"\textbackslash{}", "&": r"\&", "%": r"\%", "$": r"\$", "#": r"\#", "_": r"\_",
                    "{": r"\{", "}": r"\}", "~": r"\textasciitilde{}", "^": r"\textasciicircum{}"}
    return re.sub(r"[\\&%$#_{}~^]", lambda m: replacements[m.group()], text)


def _latex(name: str, meetings: List[Dict]) -> str:

    out = ["% Needs \\usepackage{amssymb} for the tick boxes.", r"\section*{Meeting log: " + _tex(name) + "}", ""]
    for m in meetings:
        out.append(r"\subsection*{" + _tex(_when(m["date"]) + (f": {m['title']}" if m["title"] else "")) + "}")
        if m["attendees"]:
            out.append(r"\textbf{Attendees:} " + _tex(m["attendees"]) + "\n")
        for heading, body in (("Notes", m["notes"]), ("Decisions", m["decisions"])):
            if body.strip():
                out.append(r"\paragraph{" + heading + "}\n" + _tex(body.strip()).replace("\n", "\n\n") + "\n")
        if m["actions"]:
            out.append(r"\paragraph{Action points}" + "\n" + r"\begin{itemize}")
            for a in m["actions"]:
                extra = ", ".join(v for v in [a["who"], f"by {a['due']}" if a["due"] else ""] if v)
                mark = r"[$\boxtimes$]" if a["done"] else r"[$\square$]"
                out.append(rf"  \item{mark} " + _tex(a["text"]) + (f" ({_tex(extra)})" if extra else ""))
            out.append(r"\end{itemize}" + "\n")
    return "\n".join(out).rstrip() + "\n"

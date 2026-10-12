"""A running record of AI use, and the declaration drafted from it.

Universities ask for AI use to be declared specifically: which tools, used for what, how the
output was checked, and what the work doesn't depend on. Keeping the record as you go is far
easier than reconstructing it at the end. Each entry has a date, tool, purpose, the key prompt,
what came back and how it was checked.

The declaration is assembled from the entries with a fixed template, not written by AI: every
sentence traces back to something the person logged. Referee's own checks are included from its
claim log. It is a draft to edit, not a finished statement.
"""

import json
import platform
import re
import time
import uuid
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

from meetings import _tex, _when


# Declaration templates. Placeholders are filled from the log: {tools}, {system}, {purposes}, {checks}.
# No institution's wording is built in: each person enters theirs once, as their default for every
# project ("*"), or for one project.
PRESETS = {
    "paragraph": {  # in the style of a paper's AI acknowledgement
        "used": ("Generative AI ({tools}) was used for {purposes}. Its output was checked by {checks}. I independently "
                 "checked everything the tools contributed and take full responsibility for the contents."),
        "unused": "No generative AI tools were used in this work.",
    },
}
DEFAULT = "*"  # the template for projects without their own

class AILog:

    def __init__(self, path: Path):

        self.path = path
        self.templates_path = path.with_name(path.stem + "-templates.json")
        try:
            self.items: List[Dict] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.items = []
        try:
            self.templates: Dict[str, Dict] = json.loads(self.templates_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.templates = {}

    def template(self, project: Optional[str]) -> Dict:

        """
        A project's declaration template: {"preset", "used", "unused"}. Its own if set, else the
        person's default, else empty (to be filled in with their institution's wording).
        """

        return (self.templates.get(project or "") or self.templates.get(DEFAULT)
                or {"preset": "custom", "used": "", "unused": ""})

    def set_template(self, project: Optional[str], preset: str, used: str = "", unused: str = "") -> Dict:

        """
        Sets a project's template, or the default with project "*": a preset as it is, or custom
        wording. Choosing "default" removes a project's own template, so it uses the default again.
        """

        key = project or ""
        if preset == "default" and key != DEFAULT:
            self.templates.pop(key, None)
        elif preset in PRESETS and not used and not unused:
            self.templates[key] = {"preset": preset, **PRESETS[preset]}
        else:
            self.templates[key] = {"preset": "custom", "used": used, "unused": unused}
        self.templates_path.write_text(json.dumps(self.templates, indent=1), encoding="utf-8")
        return self.template(project)

    def _save(self) -> None:

        self.path.write_text(json.dumps(self.items, indent=1), encoding="utf-8")

    def all(self, project: Optional[str] = None) -> List[Dict]:

        found = [e for e in self.items if project is None or (e.get("project") or "") == project]
        return sorted(found, key=lambda e: (e.get("date") or "", e.get("created") or 0), reverse=True)

    def save(self, entry: Dict) -> Dict:

        clean = {
            "id": entry.get("id") or uuid.uuid4().hex,
            "project": entry.get("project") or "",
            "date": entry.get("date") or date.today().isoformat(),
            "tool": (entry.get("tool") or "").strip(),
            "version": (entry.get("version") or "").strip(),
            "purpose": (entry.get("purpose") or "").strip(),
            "prompt": entry.get("prompt") or "",
            "response": entry.get("response") or "",
            "checked": (entry.get("checked") or "").strip(),
            "created": entry.get("created") or time.time(),
        }
        self.items = [e for e in self.items if e["id"] != clean["id"]] + [clean]
        self._save()
        return clean

    def delete(self, entry_id: str) -> bool:

        before = len(self.items)
        self.items = [e for e in self.items if e["id"] != entry_id]
        self._save()
        return len(self.items) < before

    def rename_project(self, old: str, new: Optional[str]) -> None:

        for entry in self.items:
            if entry.get("project") == old:
                entry["project"] = new or ""
        self._save()
        if old in self.templates:
            moved = self.templates.pop(old)
            if new:
                self.templates[new] = moved
            self.templates_path.write_text(json.dumps(self.templates, indent=1), encoding="utf-8")

    def fields(self, project: Optional[str], referee_claims: int = 0) -> Optional[Dict[str, str]]:

        """
        What the templates are filled with, from the log; None when no AI use is logged. Referee
        counts as generative AI use when it has checked claims, since it uses Claude to do so.
        """

        entries = [e for e in reversed(self.all(project)) if e["tool"]]
        tools = list(dict.fromkeys(f"{e['tool']} {e['version']}".strip() for e in entries))
        purposes = list(dict.fromkeys(_clause(e["purpose"]) for e in entries if e["purpose"]))
        checks = list(dict.fromkeys(_clause(e["checked"]) for e in entries if e["checked"]))
        if referee_claims:
            tools.append("Referee (a citation checker I developed, using Anthropic Claude)")
            purposes.append("checking that the sources I cite support the claims I make")
            checks.append("reviewing every issue it flagged and correcting the text myself")
        if not tools:
            return None
        system = platform.mac_ver()[0]
        return {"tools": "; ".join(tools), "system": f"macOS {system}" if system else platform.system(),
                "purposes": _join(purposes, "; ") if purposes else "[fill in]",
                "checks": _join(checks, "; ") if checks else "[fill in]"}

    def declaration(self, project: Optional[str], referee_claims: int = 0) -> str:

        """
        The project's declaration, from its template and the log.
        """

        template = self.template(project)
        fields = self.fields(project, referee_claims)
        if not template["used"].strip() and not template["unused"].strip():
            return ""  # no wording yet: the app asks for the institution's
        if fields is None:
            return template["unused"]
        return re.sub(r"\{(tools|system|purposes|checks)\}", lambda m: fields[m.group(1)], template["used"])

    def export(self, project: Optional[str], format: str = "markdown", referee_claims: int = 0) -> str:

        entries = list(reversed(self.all(project)))
        name = project if project else "All projects" if project is None else "No project"
        declared = self.declaration(project, referee_claims) or "[Set your declaration's wording in Referee: AI Use, Declaration.]"
        if format == "latex":
            # Paragraphs, with the form's lines kept apart by line breaks (never on an empty line).
            form = "\n\n".join(" \\\\\n".join(_tex(line) for line in block.split("\n")) for block in declared.split("\n\n"))
            out = [r"\section*{Declaration of AI use}", form, "", r"\subsection*{Record of use: " + _tex(name) + "}"]
            for e in entries:
                out.append(r"\paragraph{" + _tex(f"{_when(e['date'])}, {(e['tool'] + ' ' + e['version']).strip() or 'AI tool'}") + "}")
                for label, key in (("Used for", "purpose"), ("Prompt", "prompt"), ("Output", "response"), ("Checked by", "checked")):
                    if e[key].strip():
                        out.append(r"\textit{" + label + r":} " + _tex(e[key].strip()).replace("\n", "\n\n") + "\n")
            return "\n".join(out).rstrip() + "\n"
        lines = ["# Declaration of AI use", "", declared, "", f"## Record of use: {name}", ""]
        for e in entries:
            lines += [f"### {_when(e['date'])}, {(e['tool'] + ' ' + e['version']).strip() or 'AI tool'}", ""]
            for label, key in (("Used for", "purpose"), ("Prompt", "prompt"), ("Output", "response"), ("Checked by", "checked")):
                if e[key].strip():
                    lines += [f"**{label}:** {e[key].strip()}", ""]
        return "\n".join(lines).rstrip() + "\n"


def _clause(text: str) -> str:

    """
    A logged phrase made to fit mid-sentence: "Checked each step by hand." -> "checked each step by hand".
    """

    text = text.strip().rstrip(".")
    first = text.split(" ", 1)[0]
    # Only an ordinarily capitalised word is lowered: "Checked" -> "checked", but not "LaTeX", "R" or "GUDHI".
    ordinary = len(first) > 1 and first[0].isupper() and first[1:].islower()
    return text[:1].lower() + text[1:] if ordinary else text


def _join(items: List[str], separator: str = ", ") -> str:

    """
    "a", "a and b", "a, b and c"; with separator "; ", "a; b; and c" (for phrases containing "and").
    """

    if len(items) == 1:
        return items[0]
    return separator.join(items[:-1]) + (" and " if separator == ", " else "; and ") + items[-1]

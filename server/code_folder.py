"""The programming side of a piece of writing: the code folder chosen in Referee's settings.

Two checks against the LaTeX being written:
    software: libraries the code imports that ask to be cited (GUDHI, Ripser, scikit-learn...)
              but that the writing never cites, each with its BibTeX entry.
    numbers:  figures in the writing that are close to, but not the same as, a value in the
              code's results (CSV, JSON, notebook outputs): usually a result that changed when
              the code was re-run, or a typo. Figures nowhere near any result are left alone,
              as they probably come from the literature.
"""

import csv
import json
import math
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterator, List, Optional, Tuple

CONFIG = Path.home() / ".referee" / "config.json"
SKIP_FOLDERS = {".git", ".venv", "venv", "env", "node_modules", "__pycache__", ".ipynb_checkpoints", "site-packages"}
MAX_FILES = 2000
MAX_BYTES = 5_000_000
CLOSE = 0.05  # a figure within 5% of a result, but not equal to it at its precision, is flagged

# Libraries that ask to be cited, by import name: (name, other names writers use, key, BibTeX).
SOFTWARE = {
    "gudhi": ("GUDHI", [], "gudhi", """@book{gudhi,
  author = {{The GUDHI Project}},
  title = {{GUDHI} User and Reference Manual},
  publisher = {GUDHI Editorial Board},
  year = {2015},
  url = {https://gudhi.inria.fr/doc/latest/}
}"""),
    "ripser": ("Ripser", ["ripser.py"], "tralie2018ripser", """@article{tralie2018ripser,
  author = {Tralie, Christopher and Saul, Nathaniel and Bar-On, Rann},
  title = {{Ripser.py}: A Lean Persistent Homology Library for Python},
  journal = {Journal of Open Source Software},
  volume = {3}, number = {29}, pages = {925}, year = {2018},
  doi = {10.21105/joss.00925}
}"""),
    "gtda": ("giotto-tda", ["giotto"], "tauzin2021giotto", """@article{tauzin2021giotto,
  author = {Tauzin, Guillaume and Lupo, Umberto and Tunstall, Lewis and P\\'erez, Julian Burella and Caorsi, Matteo and Medina-Mardones, Anibal M. and Dassatti, Alberto and Hess, Kathryn},
  title = {giotto-tda: A Topological Data Analysis Toolkit for Machine Learning and Data Exploration},
  journal = {Journal of Machine Learning Research},
  volume = {22}, number = {39}, pages = {1--6}, year = {2021}
}"""),
    "kmapper": ("Kepler Mapper", ["KeplerMapper", "kmapper"], "vanveen2019kepler", """@article{vanveen2019kepler,
  author = {van Veen, Hendrik Jacob and Saul, Nathaniel and Eargle, David and Mangham, Sam W.},
  title = {Kepler Mapper: A flexible Python implementation of the Mapper algorithm},
  journal = {Journal of Open Source Software},
  volume = {4}, number = {42}, pages = {1315}, year = {2019},
  doi = {10.21105/joss.01315}
}"""),
    "hdbscan": ("hdbscan", ["HDBSCAN"], "mcinnes2017hdbscan", """@article{mcinnes2017hdbscan,
  author = {McInnes, Leland and Healy, John and Astels, Steve},
  title = {hdbscan: Hierarchical density based clustering},
  journal = {Journal of Open Source Software},
  volume = {2}, number = {11}, pages = {205}, year = {2017},
  doi = {10.21105/joss.00205}
}"""),
    "umap": ("UMAP", [], "mcinnes2018umap", """@article{mcinnes2018umap,
  author = {McInnes, Leland and Healy, John and Melville, James},
  title = {{UMAP}: Uniform Manifold Approximation and Projection for Dimension Reduction},
  journal = {arXiv preprint arXiv:1802.03426},
  year = {2018}
}"""),
    "sklearn": ("scikit-learn", ["sklearn", "scikit learn"], "pedregosa2011scikit", """@article{pedregosa2011scikit,
  author = {Pedregosa, F. and Varoquaux, G. and Gramfort, A. and Michel, V. and Thirion, B. and Grisel, O. and Blondel, M. and Prettenhofer, P. and Weiss, R. and Dubourg, V. and Vanderplas, J. and Passos, A. and Cournapeau, D. and Brucher, M. and Perrot, M. and Duchesnay, E.},
  title = {Scikit-learn: Machine Learning in {P}ython},
  journal = {Journal of Machine Learning Research},
  volume = {12}, pages = {2825--2830}, year = {2011}
}"""),
    "numpy": ("NumPy", [], "harris2020array", """@article{harris2020array,
  author = {Harris, Charles R. and Millman, K. Jarrod and van der Walt, St{\\'e}fan J. and others},
  title = {Array programming with {NumPy}},
  journal = {Nature},
  volume = {585}, number = {7825}, pages = {357--362}, year = {2020},
  doi = {10.1038/s41586-020-2649-2}
}"""),
    "scipy": ("SciPy", [], "virtanen2020scipy", """@article{virtanen2020scipy,
  author = {Virtanen, Pauli and Gommers, Ralf and Oliphant, Travis E. and others},
  title = {{SciPy} 1.0: Fundamental Algorithms for Scientific Computing in {P}ython},
  journal = {Nature Methods},
  volume = {17}, pages = {261--272}, year = {2020},
  doi = {10.1038/s41592-019-0686-2}
}"""),
    "networkx": ("NetworkX", [], "hagberg2008networkx", """@inproceedings{hagberg2008networkx,
  author = {Hagberg, Aric A. and Schult, Daniel A. and Swart, Pieter J.},
  title = {Exploring Network Structure, Dynamics, and Function using {NetworkX}},
  booktitle = {Proceedings of the 7th Python in Science Conference},
  pages = {11--15}, year = {2008}
}"""),
    "pandas": ("pandas", [], "mckinney2010data", """@inproceedings{mckinney2010data,
  author = {McKinney, Wes},
  title = {Data Structures for Statistical Computing in {P}ython},
  booktitle = {Proceedings of the 9th Python in Science Conference},
  pages = {56--61}, year = {2010},
  doi = {10.25080/Majora-92bf1922-00a}
}"""),
    "matplotlib": ("Matplotlib", [], "hunter2007matplotlib", """@article{hunter2007matplotlib,
  author = {Hunter, J. D.},
  title = {Matplotlib: A 2D graphics environment},
  journal = {Computing in Science \\& Engineering},
  volume = {9}, number = {3}, pages = {90--95}, year = {2007},
  doi = {10.1109/MCSE.2007.55}
}"""),
}

IMPORT = re.compile(r"^\s*(?:import|from)\s+([A-Za-z_]\w*)", re.MULTILINE)
NUMBER = re.compile(r"-?\d+\.\d+(?:[eE][-+]?\d+)?|-?\d+[eE][-+]?\d+")
CITE = re.compile(r"\\(?:cite|citep|citet|parencite|textcite|autocite)\w*\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}")


def folder() -> Optional[Path]:

    try:
        chosen = json.loads(CONFIG.read_text(encoding="utf-8")).get("code_folder")
    except (OSError, ValueError):
        return None
    return Path(chosen) if chosen and Path(chosen).is_dir() else None


def _files(root: Path) -> Iterator[Path]:

    count = 0
    for directory, folders, names in os.walk(root):
        folders[:] = [f for f in folders if f not in SKIP_FOLDERS and not f.startswith(".")]
        for name in names:
            path = Path(directory) / name
            if path.suffix.lower() in {".py", ".ipynb", ".csv", ".tsv", ".json", ".txt"}:
                try:
                    if path.stat().st_size > MAX_BYTES:
                        continue
                except OSError:
                    continue
                yield path
                count += 1
                if count >= MAX_FILES:
                    return


def _notebook(path: Path) -> Tuple[str, str]:

    """
    (code, outputs) of a Jupyter notebook as text.
    """

    try:
        cells = json.loads(path.read_text(encoding="utf-8")).get("cells", [])
    except (OSError, ValueError):
        return "", ""
    code, outputs = [], []
    for cell in cells:
        if cell.get("cell_type") == "code":
            code.append("".join(cell.get("source", [])))
            for output in cell.get("outputs", []):
                outputs.append("".join(output.get("text", [])))
                outputs.append("".join((output.get("data") or {}).get("text/plain", [])))
    return "\n".join(code), "\n".join(outputs)


class Scan:

    """
    The code folder's imports and result values, re-read only when a file changes.
    """

    def __init__(self):

        self.seen: Dict[str, float] = {}
        self.imports: Dict[str, str] = {}               # import name -> first file using it
        self.values: List[Tuple[float, str, float]] = []  # (value, file, modified)

    def update(self, root: Path) -> None:

        files = list(_files(root))
        stamps = {str(f): f.stat().st_mtime for f in files}
        if stamps == self.seen:
            return
        self.seen, self.imports, self.values = stamps, {}, []
        for path in files:
            relative, modified = str(path.relative_to(root)), stamps[str(path)]
            suffix = path.suffix.lower()
            try:
                if suffix == ".ipynb":
                    code, outputs = _notebook(path)
                    self._imports(code, relative)
                    self._numbers(outputs, relative, modified)
                elif suffix == ".py":
                    self._imports(path.read_text(encoding="utf-8", errors="ignore"), relative)
                elif suffix in {".csv", ".tsv"}:
                    with open(path, newline="", encoding="utf-8", errors="ignore") as handle:
                        for row in csv.reader(handle, delimiter="\t" if suffix == ".tsv" else ","):
                            self._numbers(" ".join(row), relative, modified)
                elif suffix == ".json":
                    self._numbers(path.read_text(encoding="utf-8", errors="ignore"), relative, modified)
                elif "result" in relative.lower() or "output" in relative.lower():  # .txt only from results folders
                    self._numbers(path.read_text(encoding="utf-8", errors="ignore"), relative, modified)
            except OSError:
                continue

    def _imports(self, code: str, file: str) -> None:

        for name in IMPORT.findall(code):
            self.imports.setdefault(name, file)

    def _numbers(self, text: str, file: str, modified: float) -> None:

        for match in NUMBER.findall(text):
            try:
                value = float(match)
            except ValueError:
                continue
            if math.isfinite(value) and value != 0:
                self.values.append((value, file, modified))


scan = Scan()


def _line(text: str, index: int) -> int:

    return text.count("\n", 0, index) + 1


def _body(latex: str) -> str:

    """
    The LaTeX with comments, the preamble and labels blanked, keeping positions for line numbers.
    """

    blank = lambda m: re.sub(r"[^\n]", " ", m.group())
    text = re.sub(r"(?<!\\)%.*$", blank, latex, flags=re.MULTILINE)
    start = text.find("\\begin{document}")
    if start > 0:
        text = re.sub(r"[^\n]", " ", text[:start]) + text[start:]
    return re.sub(r"\\(?:label|ref|eqref|cref|Cref|cite\w*|includegraphics|input|include|usepackage)\*?(?:\[[^\]]*\])*\{[^}]*\}", blank, text)


def software(latex: str) -> List[Dict]:

    """
    Libraries the code uses that ask to be cited, and that the writing doesn't cite.
    """

    keys = {k.strip() for found in CITE.findall(latex) for k in found.split(",")}
    missing = []
    for module, file in sorted(scan.imports.items()):
        if module not in SOFTWARE:
            continue
        name, others, key, entry = SOFTWARE[module]
        names = [n.lower() for n in [name, *others]]
        # Cited by its key, or by a \cite shortly after its name ("GUDHI~\cite{...}", "Ripser [\cite{...}]").
        near = [re.compile(re.escape(n) + r"[^.;]{0,40}?\\(?:cite|citep|citet|parencite|textcite|autocite)", re.IGNORECASE) for n in names]
        cited = key in keys or any(pattern.search(latex) for pattern in near)
        if not cited:
            missing.append({"name": name, "file": file, "key": key, "bibtex": entry})
    return missing


def numbers(latex: str) -> List[Dict]:

    """
    Figures in the writing close to a result but not equal to it at the precision written.
    """

    if not scan.values:
        return []
    body = _body(latex)
    flagged = []
    figure = re.compile(r"(?<![\w.\\])(\d+\.\d+)(\\?%)?(?![\w.])")
    for match in figure.finditer(body):
        before = body[max(0, match.start() - 12):match.start()]
        if re.search(r"(Theorem|Lemma|Section|Chapter|Figure|Fig\.|Table|Eq\.|Definition|Proposition|version|v)\W*$", before, re.IGNORECASE):
            continue
        written = match.group(1)
        places = len(written.split(".")[1])
        x = float(written)
        targets = [x / 100, x] if match.group(2) else [x]
        if any(round(v, places + (2 if t != x else 0)) == t for v, _, _ in scan.values for t in targets):
            continue
        close = [(abs(v - t) / abs(t), v, f, m) for v, f, m in scan.values for t in targets if t and abs(v - t) / abs(t) <= CLOSE]
        if not close:
            continue  # nothing like it in the results: probably from the literature
        _, value, file, modified = min(close)
        flagged.append({"line": _line(latex, match.start()), "wrote": match.group(0), "closest": value, "file": file,
                        "modified": datetime.fromtimestamp(modified).strftime("%-d %b %H:%M")})
    return flagged


def check(latex: str) -> Dict:

    root = folder()
    if root is None:
        return {"folder": None}
    scan.update(root)
    return {"folder": str(root), "software": software(latex), "numbers": numbers(latex)}

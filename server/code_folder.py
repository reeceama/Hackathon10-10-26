"""The programming side of a piece of writing: the code folder chosen in Referee's settings.

Two checks against the LaTeX being written:
    software: libraries the code imports that ask to be cited (GUDHI, Ripser, scikit-learn...;
              in R, R itself and packages such as ggplot2, MASS and lme4; in C and C++, libraries
              such as Eigen, GSL, FFTW, CGAL and PHAT) but that the writing
              never cites, each with its BibTeX entry.
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

# R packages that ask to be cited, by package name, in the same form. R itself is cited whenever
# the code is R: its year is the current one, as R's citation() gives for the installed version.
SOFTWARE_R = {
    "ggplot2": ("ggplot2", [], "wickham2016ggplot2", """@book{wickham2016ggplot2,
  author = {Wickham, Hadley},
  title = {ggplot2: Elegant Graphics for Data Analysis},
  publisher = {Springer-Verlag New York},
  year = {2016},
  isbn = {978-3-319-24277-4}
}"""),
    "MASS": ("MASS", [], "venables2002modern", """@book{venables2002modern,
  author = {Venables, W. N. and Ripley, B. D.},
  title = {Modern Applied Statistics with {S}},
  edition = {Fourth},
  publisher = {Springer},
  address = {New York},
  year = {2002}
}"""),
    "lme4": ("lme4", [], "bates2015lme4", """@article{bates2015lme4,
  author = {Bates, Douglas and M{\\"a}chler, Martin and Bolker, Ben and Walker, Steve},
  title = {Fitting Linear Mixed-Effects Models Using {lme4}},
  journal = {Journal of Statistical Software},
  volume = {67}, number = {1}, pages = {1--48}, year = {2015},
  doi = {10.18637/jss.v067.i01}
}"""),
    "mgcv": ("mgcv", [], "wood2017generalized", """@book{wood2017generalized,
  author = {Wood, S. N.},
  title = {Generalized Additive Models: An Introduction with {R}},
  edition = {2},
  publisher = {Chapman and Hall/CRC},
  year = {2017}
}"""),
    "car": ("car", [], "fox2019companion", """@book{fox2019companion,
  author = {Fox, John and Weisberg, Sanford},
  title = {An {R} Companion to Applied Regression},
  edition = {Third},
  publisher = {Sage},
  address = {Thousand Oaks, CA},
  year = {2019}
}"""),
    "glmnet": ("glmnet", [], "friedman2010regularization", """@article{friedman2010regularization,
  author = {Friedman, Jerome and Hastie, Trevor and Tibshirani, Robert},
  title = {Regularization Paths for Generalized Linear Models via Coordinate Descent},
  journal = {Journal of Statistical Software},
  volume = {33}, number = {1}, pages = {1--22}, year = {2010},
  doi = {10.18637/jss.v033.i01}
}"""),
    "tidyverse": ("tidyverse", ["dplyr", "tidyr", "readr", "purrr", "tibble", "stringr", "forcats"], "wickham2019welcome", """@article{wickham2019welcome,
  author = {Wickham, Hadley and Averick, Mara and Bryan, Jennifer and others},
  title = {Welcome to the {tidyverse}},
  journal = {Journal of Open Source Software},
  volume = {4}, number = {43}, pages = {1686}, year = {2019},
  doi = {10.21105/joss.01686}
}"""),
}
for part in SOFTWARE_R["tidyverse"][1]:  # the tidyverse's own packages are cited through it
    SOFTWARE_R[part] = SOFTWARE_R["tidyverse"]


def r_itself() -> Tuple[str, List[str], str, str]:

    year = datetime.now().year
    return ("R", ["R Core Team"], f"rcore{year}", f"""@manual{{rcore{year},
  author = {{{{R Core Team}}}},
  title = {{R: A Language and Environment for Statistical Computing}},
  organization = {{R Foundation for Statistical Computing}},
  address = {{Vienna, Austria}},
  year = {{{year}}},
  url = {{https://www.R-project.org/}}
}}""")


# C and C++ libraries that ask to be cited, by the first part of their #include path.
SOFTWARE_C = {
    "eigen": ("Eigen", [], "eigenweb", """@misc{eigenweb,
  author = {Guennebaud, Ga{\\"e}l and Jacob, Beno{\\^i}t and others},
  title = {Eigen v3},
  howpublished = {http://eigen.tuxfamily.org},
  year = {2010}
}"""),
    "gsl": ("GSL", ["GNU Scientific Library"], "galassi2009gsl", """@book{galassi2009gsl,
  author = {Galassi, M. and Davies, J. and Theiler, J. and Gough, B. and Jungman, G. and Alken, P. and Booth, M. and Rossi, F.},
  title = {{GNU} Scientific Library Reference Manual},
  edition = {Third},
  publisher = {Network Theory Ltd},
  year = {2009}
}"""),
    "fftw3": ("FFTW", [], "frigo2005fftw", """@article{frigo2005fftw,
  author = {Frigo, Matteo and Johnson, Steven G.},
  title = {The Design and Implementation of {FFTW3}},
  journal = {Proceedings of the IEEE},
  volume = {93}, number = {2}, pages = {216--231}, year = {2005},
  doi = {10.1109/JPROC.2004.840301}
}"""),
    "gmp": ("GMP", ["GNU MP"], "gmp", """@manual{gmp,
  author = {Granlund, Torbj{\\"o}rn and {the GMP development team}},
  title = {{GNU MP}: The {GNU} Multiple Precision Arithmetic Library},
  url = {https://gmplib.org/}
}"""),
    "armadillo": ("Armadillo", [], "sanderson2016armadillo", """@article{sanderson2016armadillo,
  author = {Sanderson, Conrad and Curtin, Ryan},
  title = {Armadillo: a template-based {C++} library for linear algebra},
  journal = {Journal of Open Source Software},
  volume = {1}, number = {2}, pages = {26}, year = {2016},
  doi = {10.21105/joss.00026}
}"""),
    "cgal": ("CGAL", [], "cgal", """@manual{cgal,
  author = {{The CGAL Project}},
  title = {{CGAL} User and Reference Manual},
  organization = {CGAL Editorial Board},
  url = {https://doc.cgal.org}
}"""),
    "phat": ("PHAT", [], "bauer2017phat", """@article{bauer2017phat,
  author = {Bauer, Ulrich and Kerber, Michael and Reininghaus, Jan and Wagner, Hubert},
  title = {Phat -- Persistent Homology Algorithms Toolbox},
  journal = {Journal of Symbolic Computation},
  volume = {78}, pages = {76--90}, year = {2017},
  doi = {10.1016/j.jsc.2016.03.009}
}"""),
    "ripser": ("Ripser", [], "bauer2021ripser", """@article{bauer2021ripser,
  author = {Bauer, Ulrich},
  title = {Ripser: efficient computation of {V}ietoris--{R}ips persistence barcodes},
  journal = {Journal of Applied and Computational Topology},
  volume = {5}, pages = {391--423}, year = {2021},
  doi = {10.1007/s41468-021-00071-5}
}"""),
    "gudhi": SOFTWARE["gudhi"],
}
C_INCLUDE = re.compile(r"^\s*#\s*include\s*[<\"]([^>\"]+)[>\"]", re.MULTILINE)
C_FILES = {".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hh", ".hxx"}


def c_library(include: str) -> Optional[str]:

    """
    "Eigen/Dense" -> "eigen", "gsl/gsl_rng.h" -> "gsl", "fftw3.h" -> "fftw3", "gmpxx.h" -> "gmp".
    """

    first = include.split("/")[0].lower()
    first = re.sub(r"\.(h|hpp|hh)$", "", first)
    first = {"gmpxx": "gmp", "ripser.cpp": "ripser"}.get(first, first)
    return first if first in SOFTWARE_C else None


R_IMPORT = re.compile(r"(?:library|require|requireNamespace)\(\s*[\"']?([A-Za-z][\w.]*)|\b([A-Za-z][\w.]*)::")
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
            if path.suffix.lower() in {".py", ".ipynb", ".r", ".rmd", ".qmd", ".csv", ".tsv", ".json", ".txt", *C_FILES}:
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
        self.r_packages: Dict[str, str] = {}            # R package -> first file using it
        self.r_file: Optional[str] = None               # an R file, if the code is R
        self.c_libraries: Dict[str, str] = {}           # C/C++ library -> first file including it
        self.values: List[Tuple[float, str, float]] = []  # (value, file, modified)

    def update(self, root: Path) -> None:

        files = list(_files(root))
        stamps = {str(f): f.stat().st_mtime for f in files}
        if stamps == self.seen:
            return
        self.seen, self.imports, self.values, self.r_packages, self.r_file, self.c_libraries = stamps, {}, [], {}, None, {}
        for path in files:
            relative, modified = str(path.relative_to(root)), stamps[str(path)]
            suffix = path.suffix.lower()
            try:
                if suffix == ".ipynb":
                    code, outputs = _notebook(path)
                    self._imports(code, relative)
                    self._numbers(outputs, relative, modified)
                elif suffix in {".r", ".rmd", ".qmd"}:
                    self.r_file = self.r_file or relative
                    for match in R_IMPORT.finditer(path.read_text(encoding="utf-8", errors="ignore")):
                        self.r_packages.setdefault(match.group(1) or match.group(2), relative)
                elif suffix in C_FILES:
                    for include in C_INCLUDE.findall(path.read_text(encoding="utf-8", errors="ignore")):
                        library = c_library(include)
                        if library:
                            self.c_libraries.setdefault(library, relative)
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
    used = [(SOFTWARE[m], f) for m, f in sorted(scan.imports.items()) if m in SOFTWARE]
    used += [(SOFTWARE_R[p], f) for p, f in sorted(scan.r_packages.items()) if p in SOFTWARE_R]
    used += [(SOFTWARE_C[c], f) for c, f in sorted(scan.c_libraries.items())]
    if scan.r_file:
        used.insert(0, (r_itself(), scan.r_file))
    missing, listed = [], set()
    for (name, others, key, entry), file in used:
        if key in listed:  # several tidyverse packages share one citation
            continue
        listed.add(key)
        # Cited by its key, or by a \cite shortly after its name ("GUDHI~\cite{...}"). Short names
        # like "R" must match as whole words, in their own case.
        near = [re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])[^.;]{0,40}?\\(?:cite|citep|citet|parencite|textcite|autocite)",
                           re.IGNORECASE if len(n) > 2 else 0) for n in [name, *others]]
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
    figure = re.compile(r"(?<![\w.\\])(\d+\.\d+)(\\?%)?(?!\w|\.\d)")  # a full stop after it ends the sentence
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

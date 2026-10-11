// The prose sentences in a LaTeX file, each with the keys it cites. Maths, proofs, figures and
// commands are left out: Referee checks claims about the literature, not derivations.

const Latex = (() => {
  const SKIPPED = "equation|align|gather|multline|eqnarray|displaymath|proof|figure|table|tabular|tikzpicture|verbatim|lstlisting|minted|thebibliography";
  const CITE = /\\(?:cite|citep|citet|parencite|textcite|autocite|footcite)\*?(?:\[[^\]]*\]){0,2}\{([^}]*)\}/g;
  const ABBREVIATIONS = /\b(e\.g|i\.e|et al|cf|resp|w\.r\.t|etc|vs|Fig|Thm|Def|Prop|Lem|Cor|Sec|Ch|Eq|pp?|no|vol)\./gi;
  const SENTENCE = /[^.!?]+[.!?]+["”’')\]]*/g;
  const MIN_WORDS = 5;

  function body(text) {
    const start = text.indexOf("\\begin{document}");
    const end = text.indexOf("\\end{document}");
    return text.slice(start < 0 ? 0 : start + 16, end < 0 ? text.length : end);
  }

  function prose(text) {
    let t = body(text).replace(/(^|[^\\])%.*$/gm, "$1");                       // comments
    t = t.replace(new RegExp(`\\\\begin\\{(${SKIPPED})\\*?\\}[\\s\\S]*?\\\\end\\{\\1\\*?\\}`, "g"), " ");
    t = t.replace(/\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]/g, " ");                  // display maths
    t = t.replace(/\\(?:part|chapter|(?:sub)*section|paragraph|caption|title|author)\*?(?:\[[^\]]*\])?\{[^}]*\}/g, "\n\n");
    t = t.replace(/\\item\b|\\(?:begin|end)\{[^}]*\}(?:\[[^\]]*\])?/g, "\n\n");
    t = t.replace(/\\(?:label|bibliography|bibliographystyle|usepackage|input|include)\{[^}]*\}/g, " ");
    t = t.replace(/\\(?:eq)?ref\{[^}]*\}/g, "(1)");
    t = t.replace(CITE, (_, keys) => `\u0001${keys}\u0002`);                     // marked, read per sentence
    for (let i = 0; i < 3; i++) t = t.replace(/\\(?:emph|textbf|textit|texttt|underline|text|mbox)\{([^{}]*)\}/g, "$1");
    return t.replace(/~/g, " ").replace(/``|''/g, "\"").replace(/\\\\|\\(?:noindent|maketitle|newpage|clearpage|medskip|bigskip|smallskip)\b/g, " ");
  }

  function sentences(text) {
    const found = [];
    for (const paragraph of prose(text).split(/\n\s*\n/)) {
      const masked = paragraph.replace(/\s+/g, " ").replace(ABBREVIATIONS, (m) => m.replace(/\./g, "․"))
        .replace(/\u0001[^\u0002]*\u0002/g, (m) => m.replace(/\./g, "․"));
      for (const match of masked.match(SENTENCE) || []) {
        const raw = match.replace(/․/g, ".");
        const keys = [...raw.matchAll(/\u0001([^\u0002]*)\u0002/g)].flatMap((m) => m[1].split(",").map((k) => k.trim())).filter(Boolean);
        const sentence = raw.replace(/\s*\u0001[^\u0002]*\u0002/g, "").replace(/\s+([.,;:])/g, "$1").trim();
        if (sentence.split(/\s+/).length >= MIN_WORDS) found.push({ sentence, keys });
      }
    }
    return found;
  }

  return { sentences };
})();

if (typeof module !== "undefined") module.exports = Latex;

// Citation formatting from the metadata the server returns:
// { title, author, date, site, url, captured_at, type }.
//
// Two families of style:
//   author-date: APA 7 and Harvard (Cite Them Right). "(Smith, 2023)", alphabetical list.
//   numbered:    IEEE (computing and engineering) and AMS (mathematics). "[1]", listed in
//                order of first citation.
// Page numbers (from PDFs) are added to in-text citations when known.

const Cite = (() => {
  const MONTHS = ["January", "February", "March", "April", "May", "June", "July",
    "August", "September", "October", "November", "December"];
  const SHORT_MONTHS = ["Jan.", "Feb.", "Mar.", "Apr.", "May", "Jun.", "Jul.", "Aug.",
    "Sep.", "Oct.", "Nov.", "Dec."];

  // Drop " - Wikipedia", " | BBC News" style suffixes when they name the site.
  function cleanTitle(source) {
    const t = (source.title || source.url || "Untitled").trim();
    const m = /^(.+?)\s+[-|–—]\s+([^-|–—]+)$/.exec(t);
    if (!m) return t;
    const tail = m[2].trim().toLowerCase();
    const squash = (s) => (s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
    let host = "";
    try { host = new URL(source.url).hostname; } catch { /* no URL */ }
    const namesSite =
      tail.split(/\s+/).length <= 4 &&
      (squash(source.site).includes(squash(tail)) || squash(host).includes(squash(tail)) ||
       squash(tail).includes(squash(source.site)));
    return namesSite ? m[1].trim() : t;
  }

  const endStop = (s) => (/[.!?]$/.test(s) ? s : `${s}.`);
  const site = (source) => (source.site || "").replace(/,?\s*(Inc|Ltd|LLC|plc)\.?$/i, "").replace(/\.$/, "").trim();

  // Page metadata often has junk in the author field (Wikipedia's is a list of catalogue
  // names), so anything long or catalogue-like is treated as no author.
  function splitAuthors(author) {
    if (!author || author.split(/\s+/).length > 8 || /databases|authority control/i.test(author)) return [];
    return author.split(/;|\band\b|&/).map((a) => a.trim()).filter(Boolean);
  }

  // "Jane Q. Smith" -> { last: "Smith", firsts: ["Jane", "Q."] }
  function parseName(name) {
    if (name.includes(",")) {
      const [last, first] = name.split(",").map((s) => s.trim());
      return { last, firsts: (first || "").split(/\s+/).filter(Boolean) };
    }
    const parts = name.split(/\s+/);
    if (parts.length === 1) return { last: parts[0], firsts: [] };
    return { last: parts.pop(), firsts: parts };
  }

  const initials = (firsts, separator) =>
    firsts.flatMap((f) => f.split("-")).filter(Boolean).map((f) => f[0].toUpperCase() + ".").join(separator);

  function parseDate(date) {
    const m = /^(\d{4})(?:-(\d{2}))?(?:-(\d{2}))?/.exec(date || "");
    if (!m) return null;
    return { year: m[1], month: m[2] ? Number(m[2]) : null, day: m[3] ? Number(m[3]) : null };
  }

  function accessed(source) {
    return parseDate(source.captured_at || new Date().toISOString().slice(0, 10));
  }

  // "Smith, J., & Jones, T." (APA) / "Smith, J. and Jones, T." (Harvard)
  function listAuthors(names, separator, and) {
    const people = names.map(parseName).map((n) => (n.firsts.length ? `${n.last}, ${initials(n.firsts, separator)}` : n.last));
    if (people.length === 1) return people[0];
    return `${people.slice(0, -1).join(", ")}${and}${people[people.length - 1]}`;
  }

  // "J. Smith and T. Jones" (IEEE and AMS put initials first)
  function initialsFirst(names) {
    const people = names.map(parseName).map((n) => (n.firsts.length ? `${initials(n.firsts, " ")} ${n.last}` : n.last));
    if (people.length <= 2) return people.join(" and ");
    return `${people.slice(0, -1).join(", ")}, and ${people[people.length - 1]}`;
  }

  function surnames(source) {
    const names = splitAuthors(source.author).map(parseName).map((n) => n.last);
    if (names.length === 1) return names[0];
    if (names.length === 2) return `${names[0]} & ${names[1]}`;
    if (names.length > 2) return `${names[0]} et al.`;
    return null;
  }

  function shortTitle(source) {
    const t = cleanTitle(source);
    const short = t.split(/\s+/).slice(0, 4).join(" ");
    return short.length < t.length ? `${short}…` : short;
  }

  const pageNote = (page, prefix = "p.") => (page ? `, ${prefix} ${page}` : "");

  const STYLES = {
    apa: {
      name: "APA 7",
      numbered: false,
      inText(source, { page } = {}) {
        const d = parseDate(source.date);
        const who = surnames(source) || `“${shortTitle(source)},”`;
        const year = d ? d.year : "n.d.";
        return who.endsWith(",”") ? `(${who} ${year}${pageNote(page)})` : `(${who}, ${year}${pageNote(page)})`;
      },
      // Author. (Year, Month Day). Title. Site. URL
      reference(source) {
        const names = splitAuthors(source.author);
        const title = cleanTitle(source);
        const d = parseDate(source.date);
        let date = "(n.d.)";
        if (d) date = `(${d.year}${d.month ? `, ${MONTHS[d.month - 1]}` : ""}${d.month && d.day ? ` ${d.day}` : ""})`;
        const where = site(source) ? ` ${endStop(site(source))}` : "";
        const url = source.url ? ` ${source.url}` : "";
        if (names.length) return `${listAuthors(names, " ", ", & ")} ${date}. ${endStop(title)}${where}${url}`;
        return `${endStop(title)} ${date}.${where}${url}`;
      },
    },

    harvard: {
      name: "Harvard",
      numbered: false,
      inText(source, { page } = {}) {
        const d = parseDate(source.date);
        const who = (surnames(source) || site(source) || shortTitle(source)).replace(" & ", " and ");
        return `(${who}, ${d ? d.year : "no date"}${pageNote(page)})`;
      },
      // Author (Year) Title. Available at: URL (Accessed: Day Month Year).
      reference(source) {
        const names = splitAuthors(source.author);
        const who = names.length ? listAuthors(names, "", " and ") : site(source) || cleanTitle(source);
        const d = parseDate(source.date);
        const a = accessed(source);
        return `${who} (${d ? d.year : "no date"}) ${endStop(cleanTitle(source))} ` +
          `Available at: ${source.url} (Accessed: ${a.day} ${MONTHS[a.month - 1]} ${a.year}).`;
      },
    },

    ieee: {
      name: "IEEE",
      numbered: true,
      inText(source, { number, page } = {}) {
        return `[${number}${pageNote(page)}]`;
      },
      // [n] J. Smith, "Title," Site, Year. [Online]. Available: URL (Accessed: Mon. Day, Year).
      reference(source, { number } = {}) {
        const names = splitAuthors(source.author);
        const who = names.length ? `${initialsFirst(names)}, ` : "";
        const d = parseDate(source.date);
        const a = accessed(source);
        const rest = [site(source), d ? d.year : null].filter(Boolean).join(", ");
        const parts = rest ? endStop(`“${cleanTitle(source)},” ${rest}`) : `“${endStop(cleanTitle(source))}”`;
        return `[${number}] ${who}${parts} [Online]. Available: ${source.url} ` +
          `(Accessed: ${SHORT_MONTHS[a.month - 1]} ${a.day}, ${a.year}).`;
      },
    },

    ams: {
      name: "AMS (mathematics)",
      numbered: true,
      inText(source, { number, page } = {}) {
        return `[${number}${pageNote(page)}]`;
      },
      // [n] J. Smith, Title, Site, Year. Available at URL (accessed Day Month Year).
      reference(source, { number } = {}) {
        const names = splitAuthors(source.author);
        const who = names.length ? `${initialsFirst(names)}, ` : "";
        const d = parseDate(source.date);
        const a = accessed(source);
        const parts = [cleanTitle(source), site(source), d ? d.year : null].filter(Boolean).join(", ");
        return `[${number}] ${who}${endStop(parts)} Available at ${source.url} ` +
          `(accessed ${a.day} ${MONTHS[a.month - 1]} ${a.year}).`;
      },
    },
  };

  // Sort key for author-date reference lists (alphabetical by first element).
  function sortKey(source) {
    const names = splitAuthors(source.author);
    return (names.length ? parseName(names[0]).last : site(source) || cleanTitle(source)).toLowerCase();
  }

  // The part of a reference that is italic in the style (titles, or nothing for IEEE).
  function italicPart(styleName, source) {
    return styleName === "ieee" ? null : cleanTitle(source);
  }

  return { STYLES, sortKey, cleanTitle, italicPart };
})();

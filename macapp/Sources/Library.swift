import AppKit
import SwiftUI
import UniformTypeIdentifiers

/// The library: your reading, projects, reference list and proof-of-work report, in the app,
/// so Referee needs no browser extension to manage what it knows.
@MainActor
final class LibraryModel: ObservableObject {

    @Published var sources: [[String: Any]] = []
    @Published var claims: [[String: Any]] = []
    @Published var notes: [String: [String]] = [:]   // source URL -> what was highlighted on it
    @Published var projects: [String] = []
    @Published var current = ""
    @Published var links: [String: [String]] = [:]
    @Published var references: [String] = []
    @Published var filter = "all"            // "all", "none" or a project name
    @Published var style = WordSettings.style
    @Published var search = ""
    @Published var audits: [(document: String, issues: [(entry: String, note: String)])] = []
    @Published var warnings: [(document: String, issues: [(entry: String, note: String)])] = []

    func load() {
        Task {
            sources = await API.getList("sources")
            claims = await API.getList("claims")
            let found = await API.get("highlights") ?? [:]
            notes = found.mapValues { ($0 as? [[String: Any]] ?? []).compactMap { $0["text"] as? String } }
            if let settings = await API.get("settings") {
                projects = settings["projects"] as? [String] ?? []
                current = settings["project"] as? String ?? ""
                links = settings["links"] as? [String: [String]] ?? [:]
            }
            if filter != "all" && filter != "none" && !projects.contains(filter) { filter = "all" }
            audits = LibraryModel.findings(await API.get("audit") ?? [:])
            warnings = LibraryModel.findings(await API.get("warnings") ?? [:])
            await loadReferences()
        }
    }

    /// Per-document findings from the Word helper, as (document, [(entry, note)]).
    static func findings(_ found: [String: Any]) -> [(document: String, issues: [(entry: String, note: String)])] {
            found.compactMap { document, value in
                let issues = ((value as? [String: Any])?["issues"] as? [[String: Any]] ?? [])
                    .compactMap { issue -> (entry: String, note: String)? in
                        guard let entry = issue["entry"] as? String, let note = issue["note"] as? String else { return nil }
                        return (entry, note)
                    }
                return issues.isEmpty ? nil : (document, issues)
            }.sorted { $0.document < $1.document }
    }

    func loadReferences() async {
        let query = "references?project=\(filter.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "all")&style=\(style)"
        references = (await API.getPath(query))?["entries"] as? [String] ?? []
    }

    func inFilter(_ project: Any?) -> Bool {
        let name = project as? String ?? ""
        switch filter {
        case "all": return true
        case "none": return name.isEmpty
        default: return name == filter
        }
    }

    var shown: [[String: Any]] {
        let query = search.lowercased()
        return sources
            .filter { inFilter($0["project"]) }
            .filter { source in
                query.isEmpty || ["title", "site", "author", "url"].contains { (source[$0] as? String ?? "").lowercased().contains(query) }
            }
            .sorted { ($0["captured_ts"] as? Double ?? 0) > ($1["captured_ts"] as? Double ?? 0) }
    }

    func backs(_ url: String) -> Int {
        claims.filter { ($0["label"] as? String) == "supports" && (($0["source"] as? [String: Any])?["url"] as? String) == url && inFilter($0["project"]) }.count
    }

    var summary: String {
        let mine = claims.filter { inFilter($0["project"]) }
        let backed = mine.filter { ($0["label"] as? String) == "supports" }
        if mine.isEmpty { return "No claims checked yet." }
        var line = "\(backed.count) claim\(backed.count == 1 ? "" : "s") backed by your reading"
        let against = mine.filter { ($0["label"] as? String) == "contradicts" }.count
        let unsupported = mine.filter { ($0["label"] as? String) == "needs_source" }.count
        if against > 0 { line += " · \(against) contradicted by a source" }
        if unsupported > 0 { line += " · \(unsupported) need\(unsupported == 1 ? "s" : "") a source" }
        var perSource: [String: Int] = [:]
        for claim in backed { perSource[(claim["source"] as? [String: Any])?["url"] as? String ?? "", default: 0] += 1 }
        if backed.count >= 4, let top = perSource.values.max(), Double(top) / Double(backed.count) > 0.5 {
            line += ". \(top) of them rest on one source; consider backing some with others."
        }
        return line
    }

    // Actions, each followed by a reload.
    func setCurrent(_ name: String) { Task { _ = await API.post("settings", ["project": name]); load() } }
    func rename(_ old: String, to new: String) { Task { _ = await API.post("projects/rename", ["old": old, "new": new]); if filter == old { filter = new.isEmpty ? "all" : new }; load() } }
    func setLinks(_ project: String, _ others: [String]) { Task { var all = links; all[project] = others; _ = await API.post("settings", ["links": all]); load() } }
    func move(_ url: String, to project: String) { Task { _ = await API.post("sources/move", ["url": url, "project": project]); load() } }
    func keep(_ url: String) { Task { _ = await API.post("sources/keep", ["url": url]); load() } }
    func forget(_ url: String) { Task { _ = await API.delete("sources?url=\(url.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "")"); load() } }
    @Published var rereading: Set<String> = []

    /// Reads a saved paper again with its maths and abstract, keeping its project and notes.
    func reread(_ url: String) {
        rereading.insert(url)
        Task {
            _ = await API.post("sources/reread", ["url": url], timeout: 120)
            rereading.remove(url)
            load()
        }
    }

    func forgetEverything() { Task { _ = await API.post("clear", [:]); load() } }

    /// Opens one of the server's report pages (proof of work, before you submit, research trail) in the browser.
    func open(_ page: String, named name: String) {
        Task {
            let query = "\(page)?project=\(filter.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "all")&style=\(style)"
            guard let html = await API.request(query, timeout: 30) else { return }
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("Referee \(name).html")
            try? html.write(to: file)
            NSWorkspace.shared.open(file)
        }
    }

    /// Saves this view's saved sources as BibTeX or RIS, for Zotero, Mendeley or LaTeX.
    func export() {
        let panel = NSSavePanel()
        panel.nameFieldStringValue = "Referee sources.bib"
        panel.allowedContentTypes = [.init(filenameExtension: "bib")!, .init(filenameExtension: "ris")!]
        panel.message = "Save as .bib (BibTeX, for Zotero or LaTeX) or .ris (for Zotero, Mendeley or EndNote)."
        guard panel.runModal() == .OK, let file = panel.url else { return }
        Task {
            let format = file.pathExtension.lowercased() == "ris" ? "ris" : "bibtex"
            let query = "export?format=\(format)&project=\(filter.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "all")"
            guard let data = await API.request(query) else { return }
            try? data.write(to: file)
        }
    }

    /// Imports a BibTeX or RIS file: each entry is fetched and saved to the current project.
    func importFile() {
        let panel = NSOpenPanel()
        panel.allowedContentTypes = [.init(filenameExtension: "bib")!, .init(filenameExtension: "ris")!]
        panel.message = "Choose a .bib or .ris file, for example exported from Zotero."
        guard panel.runModal() == .OK, let file = panel.url, let text = try? String(contentsOf: file, encoding: .utf8) else { return }
        importing = true
        Task {
            let result = await API.post("import", ["text": text], timeout: 600)
            importing = false
            load()
            let added = result?["added"] as? Int ?? 0
            let failed = result?["failed"] as? [String] ?? []
            let alert = NSAlert()
            alert.messageText = result == nil ? "Import didn't finish" : "Imported \(added) source\(added == 1 ? "" : "s")"
            alert.informativeText = result == nil ? "Referee's server didn't answer in time. Try a smaller file."
                : failed.isEmpty ? "Each one was read and saved to your current project." : "Couldn't read:\n" + failed.prefix(12).joined(separator: "\n")
            alert.runModal()
        }
    }

    @Published var importing = false
}

struct LibraryView: View {

    @StateObject private var library = LibraryModel()
    @State private var newProject = ""
    @State private var renaming: String?
    @State private var renameTo = ""
    @State private var armed: String?           // a saved source or project waiting for its second click
    @State private var confirmEverything = ""
    @State private var copied = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                header
                Text(library.summary).font(.callout).foregroundStyle(.secondary)
                card(title: "Projects", symbol: "folder") { projectsCard }
                card(title: "References", symbol: "text.quote") { referencesCard }
                if !library.warnings.isEmpty {
                    card(title: "Warnings", symbol: "exclamationmark.triangle") { findingsCard(library.warnings) }
                }
                if !library.audits.isEmpty {
                    card(title: "Reference Check", symbol: "checklist") { findingsCard(library.audits) }
                }
                card(title: "Reading", symbol: "books.vertical") { readingCard }
                forgetEverything
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
            .padding(.top, 4)
        }
        .frame(minWidth: 640, idealWidth: 720, minHeight: 520, idealHeight: 720)
        .background(WindowGlass().ignoresSafeArea())
        .onAppear { library.load() }
    }

    // MARK: Header: which reading, search, report.

    private var header: some View {
        HStack(spacing: 10) {
            Image(nsImage: whistle(false)).resizable().frame(width: 24, height: 24)
            Text("Library").font(.title2.weight(.semibold))
            Spacer()
            Picker("Show", selection: $library.filter) {
                Text("All Reading").tag("all")
                ForEach(library.projects, id: \.self) { Text($0).tag($0) }
                Text("No Project").tag("none")
            }
            .labelsHidden()
            .fixedSize()
            .onChange(of: library.filter) { _, _ in Task { await library.loadReferences() } }
            TextField("Search", text: $library.search)
                .textFieldStyle(.plain)
                .frame(width: 140)
                .padding(.horizontal, 10).padding(.vertical, 6)
                .glassCard()
            Menu("Reports") {
                Button("Before You Submit") { library.open("presubmission", named: "before you submit") }
                Button("Research Trail") { library.open("trail", named: "research trail") }
                Button("Proof of Work") { library.open("report", named: "proof of work") }
            }
            .fixedSize()
            .glassButton()
            Menu(library.importing ? "Importing…" : "Zotero") {
                Button("Import .bib or .ris…") { library.importFile() }
                Button("Export Saved Sources…") { library.export() }
            }
            .fixedSize()
            .disabled(library.importing)
            .glassButton()
        }
    }

    // MARK: Projects

    private var projectsCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            if library.projects.isEmpty {
                Text("No projects yet. Writing is checked against all your reading until you choose one.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            ForEach(library.projects, id: \.self) { name in
                HStack(spacing: 10) {
                    if renaming == name {
                        TextField("Project name", text: $renameTo)
                            .textFieldStyle(.roundedBorder)
                            .onSubmit { finishRename(name) }
                        Button("Rename") { finishRename(name) }.glassButton()
                        Button("Cancel") { renaming = nil }.glassButton()
                    } else {
                        Text(name).fontWeight(.semibold)
                        Text("\(library.sources.filter { ($0["project"] as? String) == name }.count) sources")
                            .font(.caption).foregroundStyle(.secondary)
                        Spacer()
                        if library.current == name {
                            Text("Current").font(.caption.weight(.semibold)).foregroundStyle(.green)
                        } else {
                            Button("Make Current") { library.setCurrent(name) }.glassButton()
                        }
                        Button("Rename") { renaming = name; renameTo = name }.glassButton()
                        Button(armed == "project:" + name ? "Click Again" : "Delete") { twoClicks("project:" + name) { library.rename(name, to: "") } }
                            .glassButton()
                            .help("Its sources stay, with no project")
                    }
                }
            }
            HStack(spacing: 8) {
                TextField("New project name", text: $newProject)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .glassCard()
                    .onSubmit(createProject)
                Button("Create", action: createProject)
                    .disabled(newProject.trimmingCharacters(in: .whitespaces).isEmpty)
                    .prominentGlassButton()
            }
            if library.projects.contains(library.filter) && library.projects.count > 1 {
                Divider().opacity(0.4)
                Text("\(library.filter) can also cite references from:").font(.callout).foregroundStyle(.secondary)
                ForEach(library.projects.filter { $0 != library.filter }, id: \.self) { other in
                    Toggle(other, isOn: Binding(
                        get: { library.links[library.filter]?.contains(other) ?? false },
                        set: { on in
                            var others = library.links[library.filter] ?? []
                            if on { others.append(other) } else { others.removeAll { $0 == other } }
                            library.setLinks(library.filter, others)
                        }))
                }
            }
        }
    }

    private func createProject() {
        let name = newProject.trimmingCharacters(in: .whitespaces)
        guard !name.isEmpty else { return }
        newProject = ""
        library.setCurrent(name)
    }

    private func finishRename(_ old: String) {
        let new = renameTo.trimmingCharacters(in: .whitespaces)
        renaming = nil
        if !new.isEmpty && new != old { library.rename(old, to: new) }
    }

    // MARK: References

    private var referencesCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Picker("Style", selection: $library.style) {
                    ForEach(styles, id: \.0) { Text($0.1).tag($0.0) }
                }
                .labelsHidden()
                .fixedSize()
                .onChange(of: library.style) { _, _ in Task { await library.loadReferences() } }
                Spacer()
                Button(copied ? "Copied" : "Copy") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(library.references.joined(separator: "\n"), forType: .string)
                    copied = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) { copied = false }
                }
                .disabled(library.references.isEmpty)
                .glassButton()
            }
            if library.references.isEmpty {
                Text("Sources appear here once they back a claim in your writing.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            ForEach(Array(library.references.enumerated()), id: \.offset) { _, entry in
                Text(entry).font(.system(.body, design: .serif)).textSelection(.enabled)
            }
        }
    }

    // MARK: Reference check, from the Word helper

    private func findingsCard(_ findings: [(document: String, issues: [(entry: String, note: String)])]) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            ForEach(findings, id: \.document) { audit in
                Text(audit.document).fontWeight(.semibold)
                ForEach(Array(audit.issues.enumerated()), id: \.offset) { _, issue in
                    VStack(alignment: .leading, spacing: 2) {
                        Text(issue.note).font(.callout).foregroundStyle(.orange)
                        Text(issue.entry).font(.system(.caption, design: .serif)).foregroundStyle(.secondary).lineLimit(2)
                    }
                }
            }
        }
    }

    // MARK: Reading

    private var readingCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            if library.shown.isEmpty {
                Text(library.sources.isEmpty ? "Nothing yet. Add sources with Add Source, or read with the browser extension." : "Nothing matches.")
                    .font(.callout).foregroundStyle(.secondary)
            }
            ForEach(Array(library.shown.enumerated()), id: \.offset) { index, source in
                if index > 0 { Divider().opacity(0.4).padding(.vertical, 8) }
                sourceRow(source)
            }
        }
    }

    private func sourceRow(_ source: [String: Any]) -> some View {
        let url = source["url"] as? String ?? ""
        let temporary = (source["kept"] as? Bool) == false
        let backs = library.backs(url)
        let type = source["type"] as? String == "pdf" ? "PDF" : source["type"] as? String == "video" ? "Video" : "Web page"
        let read = [source["site"] as? String, source["captured_at"] as? String].compactMap { $0 }.filter { !$0.isEmpty }.joined(separator: " · ")
        return HStack(alignment: .center, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                if let link = URL(string: url), url.hasPrefix("http") {
                    Link(title(source), destination: link).fontWeight(.semibold)
                } else {
                    Text(title(source)).fontWeight(.semibold)
                }
                if !read.isEmpty { Text(read).font(.caption).foregroundStyle(.secondary) }
                ForEach(Array((library.notes[url] ?? []).prefix(3).enumerated()), id: \.offset) { _, note in
                    Text("“\(note)”")
                        .font(.caption)
                        .italic()
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .padding(.leading, 8)
                        .overlay(alignment: .leading) { Rectangle().fill(.yellow.opacity(0.6)).frame(width: 2) }
                }
                HStack(spacing: 6) {
                    if source["retracted"] as? Bool == true { tag("Retracted", colour: .red) }
                    tag(temporary ? "Temporary" : "Saved", colour: temporary ? .orange : .green)
                    tag(type, colour: .secondary)
                    if backs > 0 { tag("Backs \(backs) claim\(backs == 1 ? "" : "s")", colour: .green) }
                }
            }
            Spacer()
            Menu(source["project"] as? String ?? "No Project") {
                Button("No Project") { library.move(url, to: "") }
                ForEach(library.projects, id: \.self) { name in Button(name) { library.move(url, to: name) } }
            }
            .fixedSize()
            if !temporary {
                if library.rereading.contains(url) {
                    ProgressView().controlSize(.small)
                } else {
                    Button { library.reread(url) } label: { Image(systemName: "arrow.clockwise") }
                        .buttonStyle(.borderless)
                        .help("Read again, keeping maths and the abstract")
                }
            }
            if let key = source["cite_key"] as? String {
                Button {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString("\\cite{\(key)}", forType: .string)
                } label: { Image(systemName: "text.quote") }
                .buttonStyle(.borderless)
                .help("Copy \\cite{\(key)} for LaTeX")
            }
            if temporary {
                Button("Save") { library.keep(url) }.glassButton()
            }
            Button {
                if temporary { library.forget(url) } else { twoClicks("source:" + url) { library.forget(url) } }
            } label: {
                Image(systemName: "xmark").foregroundStyle(armed == "source:" + url ? .red : .secondary)
            }
            .buttonStyle(.plain)
            .help(temporary ? "Forget this source" : armed == "source:" + url ? "Click again to forget" : "Forget this source")
        }
    }

    private func title(_ source: [String: Any]) -> String {
        let title = source["title"] as? String ?? source["url"] as? String ?? "Untitled"
        return title.replacingOccurrences(of: #"\s+[-|–—]\s+[^-|–—]+$"#, with: "", options: .regularExpression)
    }

    private func tag(_ text: String, colour: Color) -> some View {
        Text(text)
            .font(.caption2.weight(.medium))
            .foregroundStyle(colour)
            .padding(.horizontal, 7).padding(.vertical, 2)
            .background(colour.opacity(0.12), in: Capsule())
    }

    // MARK: Forget everything, behind a typed confirmation.

    private var forgetEverything: some View {
        HStack {
            Spacer()
            TextField("Type forget to confirm", text: $confirmEverything)
                .textFieldStyle(.roundedBorder)
                .frame(width: 180)
            Button("Forget All Reading") {
                library.forgetEverything()
                confirmEverything = ""
            }
            .disabled(confirmEverything.trimmingCharacters(in: .whitespaces).lowercased() != "forget")
            .foregroundStyle(.red)
            .glassButton()
        }
        .font(.callout)
    }

    // Saved things take two clicks: the first arms the button for three seconds.
    private func twoClicks(_ key: String, action: @escaping () -> Void) {
        if armed == key {
            armed = nil
            action()
        } else {
            armed = key
            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { if armed == key { armed = nil } }
        }
    }

    private func card<Content: View>(title: String, symbol: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            content()
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .glassCard()
        }
    }
}

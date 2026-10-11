import AppKit
import SwiftUI

/// The library: your reading, projects, reference list and proof-of-work report, in the app,
/// so Referee needs no browser extension to manage what it knows.
@MainActor
final class LibraryModel: ObservableObject {

    @Published var sources: [[String: Any]] = []
    @Published var claims: [[String: Any]] = []
    @Published var projects: [String] = []
    @Published var current = ""
    @Published var links: [String: [String]] = [:]
    @Published var references: [String] = []
    @Published var filter = "all"            // "all", "none" or a project name
    @Published var style = WordSettings.style
    @Published var search = ""

    func load() {
        Task {
            sources = await API.getList("sources")
            claims = await API.getList("claims")
            if let settings = await API.get("settings") {
                projects = settings["projects"] as? [String] ?? []
                current = settings["project"] as? String ?? ""
                links = settings["links"] as? [String: [String]] ?? [:]
            }
            if filter != "all" && filter != "none" && !projects.contains(filter) { filter = "all" }
            await loadReferences()
        }
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
        if mine.count > backed.count { line += " · \(mine.count - backed.count) contradicted by a source" }
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
    func forgetEverything() { Task { _ = await API.post("clear", [:]); load() } }

    func openReport() {
        Task {
            let query = "report?project=\(filter.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? "all")&style=\(style)"
            guard let page = await API.request(query) else { return }
            let file = FileManager.default.temporaryDirectory.appendingPathComponent("Referee proof of work.html")
            try? page.write(to: file)
            NSWorkspace.shared.open(file)
        }
    }
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
            Button("Proof of Work") { library.openReport() }.glassButton()
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

    // MARK: Reading

    private var readingCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            if library.shown.isEmpty {
                Text(library.sources.isEmpty ? "Nothing yet. Add sources with Add Source…, or read with the browser extension." : "Nothing matches.")
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
                HStack(spacing: 6) {
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

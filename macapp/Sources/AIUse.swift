import AppKit
import SwiftUI

/// A running record of AI use, by project, and the declaration drafted from it. The draft is
/// assembled from the entries by the server with a fixed template, not written by AI.
struct AIUse: Codable, Identifiable, Equatable {
    var id = UUID().uuidString
    var project = ""
    var date = Meeting.today
    var tool = ""
    var version = ""
    var purpose = ""
    var prompt = ""
    var response = ""
    var checked = ""
    var created: Double?

    var day: String { Meeting(date: date).day }
}

let aiTools = ["Microsoft Copilot", "ChatGPT", "Claude", "Gemini", "Overleaf AI (Writefull)", "GitHub Copilot"]

@MainActor
final class AIUseModel: ObservableObject {

    @Published var entries: [AIUse] = []
    @Published var projects: [String] = []
    @Published var filter = "all"
    @Published var selected: String?
    @Published var declaration = ""
    @Published var preset = "standard"       // this project's template: "standard", "paragraph" or "custom"
    @Published var used = ""                 // its wording when AI was used, with {tools} and so on
    @Published var unused = ""               // and when it wasn't
    private var current = ""
    private var pending: Task<Void, Never>?

    private var query: String { filter.addingPercentEncoding(withAllowedCharacters: .alphanumerics) ?? "all" }

    func load() {
        Task {
            if let settings = await API.get("settings") {
                projects = settings["projects"] as? [String] ?? []
                current = settings["project"] as? String ?? ""
            }
            await reload()
        }
    }

    func reload() async {
        guard let data = await API.request("ai-log?project=\(query)"),
              let found = try? JSONDecoder().decode([AIUse].self, from: data) else { return }
        entries = found
        if selected == nil || !found.contains(where: { $0.id == selected }) { selected = found.first?.id }
        await draft()
    }

    func draft() async {
        let found = await API.getPath("ai-log/declaration?project=\(query)") ?? [:]
        declaration = found["text"] as? String ?? ""
        preset = found["preset"] as? String ?? "standard"
        used = found["used"] as? String ?? ""
        unused = found["unused"] as? String ?? ""
    }

    /// Sets this project's template: a preset as it is, or custom wording.
    func setTemplate(_ preset: String, used: String = "", unused: String = "") {
        Task {
            _ = await API.post("ai-log/template", ["project": filter, "preset": preset, "used": used, "unused": unused])
            await draft()
        }
    }

    func add() {
        var entry = AIUse()
        entry.project = filter == "all" ? current : filter == "none" ? "" : filter
        entries.insert(entry, at: 0)
        selected = entry.id
        save(entry, now: true)
    }

    func save(_ entry: AIUse, now: Bool = false) {
        if let index = entries.firstIndex(where: { $0.id == entry.id }) { entries[index] = entry }
        pending?.cancel()
        pending = Task {
            if !now { try? await Task.sleep(nanoseconds: 700_000_000) }
            guard !Task.isCancelled, let body = try? JSONSerialization.jsonObject(with: JSONEncoder().encode(entry)) as? [String: Any] else { return }
            _ = await API.post("ai-log", body)
            await draft()
        }
    }

    func delete(_ id: String) {
        entries.removeAll { $0.id == id }
        selected = entries.first?.id
        Task {
            _ = await API.delete("ai-log?id=\(id)")
            await draft()
        }
    }

    func export(_ format: String) async -> String? {
        guard let data = await API.request("ai-log/export?project=\(query)&format=\(format)", timeout: 10) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

struct AIUseView: View {

    @StateObject private var model = AIUseModel()
    @State private var armed = false
    @State private var copied = ""
    @State private var showDeclaration = false

    var body: some View {
        HStack(spacing: 0) {
            sidebar.frame(width: 230)
            Divider().opacity(0.4)
            if showDeclaration {
                declaration
            } else if let entry = model.entries.first(where: { $0.id == model.selected }) {
                AIUseEditor(model: model, entry: entry, armed: $armed).id(entry.id)
            } else {
                VStack(spacing: 10) {
                    Text("No AI use logged").font(.title3.weight(.semibold))
                    Text("Note each substantive use of an AI tool as it happens: what you used it for, and how you checked what it gave you. Your declaration is drafted from these notes.")
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Log AI Use") { model.add() }.glassButton()
                }
                .padding(40)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            }
        }
        .frame(minWidth: 760, idealWidth: 860, minHeight: 520, idealHeight: 680)
        .background(WindowGlass().ignoresSafeArea())
        .onAppear { model.load() }
        .onChange(of: model.filter) { _, _ in Task { await model.reload() } }
        .onChange(of: model.selected) { _, _ in showDeclaration = false }
    }

    private var sidebar: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("AI Use").font(.title2.weight(.semibold))
                Spacer()
                Button { showDeclaration = false; model.add() } label: { Image(systemName: "plus") }
                    .buttonStyle(.borderless)
                    .help("Log AI use")
            }
            .padding(.top, 28)
            Picker("Project", selection: $model.filter) {
                Text("All Projects").tag("all")
                ForEach(model.projects, id: \.self) { Text($0).tag($0) }
                Text("No Project").tag("none")
            }
            .labelsHidden()
            Button { showDeclaration = true; Task { await model.draft() } } label: {
                Label("Declaration", systemImage: "checkmark.seal").frame(maxWidth: .infinity, alignment: .leading)
            }
            .glassButton()
            List(model.entries, selection: $model.selected) { entry in
                VStack(alignment: .leading, spacing: 2) {
                    Text(entry.tool.isEmpty ? "AI tool" : entry.tool).fontWeight(.medium).lineLimit(1)
                    Text([entry.day, entry.purpose].filter { !$0.isEmpty }.joined(separator: " · "))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
                .tag(entry.id)
            }
            .scrollContentBackground(.hidden)
            Menu {
                Button(copied == "markdown" ? "Copied" : "Copy as Markdown") { copy("markdown") }
                Button("Save as LaTeX…") { saveLatex() }
            } label: {
                Label("Export", systemImage: "square.and.arrow.up")
            }
            .help("The declaration and the full record, for an appendix")
            .padding(.bottom, 14)
        }
        .padding(.horizontal, 14)
    }

    private var declaration: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 14) {
                Text("Declaration").font(.title2.weight(.semibold)).padding(.top, 6)
                if model.filter == "all" {
                    Text("Choose a project above to set its own declaration. Each project keeps its own wording: the standard form for a mini-project, a paragraph for a dissertation, or your own.")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                } else {
                    Picker("Template", selection: Binding(get: { model.preset }, set: { model.setTemplate($0) })) {
                        Text("Standard form (A or B)").tag("standard")
                        Text("Paragraph").tag("paragraph")
                        if model.preset == "custom" { Text("Custom").tag("custom") }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .fixedSize()
                }
                Text("Filled in from your log with a fixed template, not by AI: every line comes from an entry you made, plus Referee's own checks (Referee uses Claude, so it counts as AI use). Check it before use.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                Text(model.declaration)
                    .textSelection(.enabled)
                    .padding(14)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .glassCard()
                Button(copied == "declaration" ? "Copied" : "Copy Declaration") {
                    NSPasteboard.general.clearContents()
                    NSPasteboard.general.setString(model.declaration, forType: .string)
                    flash("declaration")
                }
                .glassButton()
                if model.filter != "all" {
                    DisclosureGroup("Edit wording for this project") {
                        VStack(alignment: .leading, spacing: 10) {
                            Text("{tools}, {system}, {purposes} and {checks} are filled in from your log.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            Text("When AI was used").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                            TextEditor(text: $model.used).font(.body).scrollContentBackground(.hidden).padding(6).frame(minHeight: 140).glassCard()
                            Text("When AI wasn't used").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
                            TextEditor(text: $model.unused).font(.body).scrollContentBackground(.hidden).padding(6).frame(minHeight: 60).glassCard()
                            Button("Save Wording") { model.setTemplate("custom", used: model.used, unused: model.unused) }.glassButton()
                        }
                        .padding(.top, 8)
                    }
                }
            }
            .padding(24)
        }
    }

    private func flash(_ what: String) {
        copied = what
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { if copied == what { copied = "" } }
    }

    private func copy(_ format: String) {
        Task {
            guard let text = await model.export(format) else { return }
            NSPasteboard.general.clearContents()
            NSPasteboard.general.setString(text, forType: .string)
            flash(format)
        }
    }

    private func saveLatex() {
        Task {
            guard let text = await model.export("latex") else { return }
            let panel = NSSavePanel()
            panel.nameFieldStringValue = "ai-use.tex"
            guard panel.runModal() == .OK, let file = panel.url else { return }
            try? text.write(to: file, atomically: true, encoding: .utf8)
        }
    }
}

struct AIUseEditor: View {

    @ObservedObject var model: AIUseModel
    @State var entry: AIUse
    @Binding var armed: Bool

    private var date: Binding<Date> {
        Binding(get: {
            let format = DateFormatter()
            format.dateFormat = "yyyy-MM-dd"
            return format.date(from: entry.date) ?? Date()
        }, set: { value in
            let format = DateFormatter()
            format.dateFormat = "yyyy-MM-dd"
            entry.date = format.string(from: value)
        })
    }

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                HStack {
                    TextField("Tool", text: $entry.tool)
                        .textFieldStyle(.plain)
                        .font(.title2.weight(.semibold))
                    Menu("Choose") {
                        ForEach(aiTools, id: \.self) { tool in Button(tool) { entry.tool = tool } }
                    }
                    .fixedSize()
                    DatePicker("Date", selection: date, displayedComponents: .date).labelsHidden().fixedSize()
                }
                TextField("Version, e.g. GPT-5 or Claude Opus 5.5, as the tool shows it", text: $entry.version)
                    .textFieldStyle(.roundedBorder)
                Picker("Project", selection: $entry.project) {
                    Text("No Project").tag("")
                    ForEach(model.projects, id: \.self) { Text($0).tag($0) }
                }
                .fixedSize()
                section("What you used it for", hint: "e.g. brainstorming project questions; debugging a Python script") {
                    TextField("Used for", text: $entry.purpose).textFieldStyle(.roundedBorder)
                }
                section("Key prompt", hint: "The substantive part of what you asked") { editor($entry.prompt, height: 80) }
                section("What it gave you", hint: "A short summary, or the key part of its answer") { editor($entry.response, height: 80) }
                section("How you checked it", hint: "e.g. checked each step by hand; re-ran the code; found the references in MathSciNet") {
                    TextField("Checked by", text: $entry.checked).textFieldStyle(.roundedBorder)
                }
                HStack {
                    Spacer()
                    Button(armed ? "Click Again to Delete" : "Delete Entry") {
                        if armed { model.delete(entry.id); armed = false } else {
                            armed = true
                            DispatchQueue.main.asyncAfter(deadline: .now() + 3) { armed = false }
                        }
                    }
                    .foregroundStyle(armed ? .red : .secondary)
                    .buttonStyle(.borderless)
                }
            }
            .padding(24)
        }
        .onChange(of: entry) { _, changed in model.save(changed) }
    }

    private func editor(_ text: Binding<String>, height: CGFloat) -> some View {
        TextEditor(text: text)
            .font(.body)
            .scrollContentBackground(.hidden)
            .padding(6)
            .frame(minHeight: height)
            .glassCard()
    }

    private func section<Content: View>(_ title: String, hint: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title).font(.subheadline.weight(.semibold)).foregroundStyle(.secondary)
            content()
            Text(hint).font(.caption).foregroundStyle(.tertiary)
        }
    }
}

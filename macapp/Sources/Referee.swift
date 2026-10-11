import AppKit
import ServiceManagement
import SwiftUI

let server = URL(string: "http://localhost:8000")!

/// What the menu shows, refreshed every few seconds from the server.
@MainActor
final class Model: ObservableObject {

    @Published var online = false
    @Published var focus = false
    @Published var writing = false
    @Published var helper = false
    @Published var project = ""
    @Published var projects: [String] = []
    @Published var keepMinutes = 15
    @Published var saved = 0
    @Published var temporary = 0
    @Published var style = WordSettings.style
    @Published var openAtLogin = SMAppService.mainApp.status == .enabled
    @Published var hasKey = true
    @Published var keyEnds = ""
    @Published var keySource = ""

    var capturing: Bool { focus || writing }
    private var timer: Timer?

    init() {
        refresh()
        timer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { _ in
            Task { @MainActor in self.refresh() }
        }
    }

    func refresh() {
        Task {
            let status = await API.get("writing")
            let settings = await API.get("settings")
            let sources = await API.getList("sources")
            online = status != nil && settings != nil
            focus = status?["focus"] as? Bool ?? false
            writing = status?["active"] as? Bool ?? false
            helper = status?["helper"] as? Bool ?? false
            project = settings?["project"] as? String ?? ""
            projects = settings?["projects"] as? [String] ?? []
            keepMinutes = settings?["keep_minutes"] as? Int ?? 15
            temporary = sources.filter { ($0["kept"] as? Bool) == false }.count
            saved = sources.count - temporary
            style = WordSettings.style
            if let key = await API.get("api-key") {
                hasKey = key["has_key"] as? Bool ?? false
                keyEnds = key["ends"] as? String ?? ""
                keySource = key["source"] as? String ?? ""
            }
        }
    }

    /// Checks the key with Anthropic and saves it in the Keychain. Returns a problem, or nil.
    func saveKey(_ key: String) async -> String? {
        let result = await API.post("api-key", ["key": key])
        refresh()
        if result == nil { return "Referee's server isn't running." }
        return (result?["ok"] as? Bool ?? false) ? nil : result?["reason"] as? String
    }

    func removeKey() {
        Task {
            var request = URLRequest(url: server.appendingPathComponent("api-key"))
            request.httpMethod = "DELETE"
            request.setValue("1", forHTTPHeaderField: "X-Referee")
            _ = try? await URLSession.shared.data(for: request)
            refresh()
        }
    }

    func setResearch(_ on: Bool) {
        Task { _ = await API.post("focus", ["on": on]); refresh() }
    }

    func setProject(_ name: String) {
        Task { _ = await API.post("settings", ["project": name]); refresh() }
    }

    func setKeep(_ minutes: Int) {
        Task { _ = await API.post("settings", ["keep_minutes": minutes]); refresh() }
    }

    func setStyle(_ value: String) {
        WordSettings.style = value
        style = value
    }

    func setOpenAtLogin(_ on: Bool) {
        do {
            if on { try SMAppService.mainApp.register() } else { try SMAppService.mainApp.unregister() }
        } catch {
            NSLog("Referee couldn't change Open at Login: \(error)")
        }
        openAtLogin = SMAppService.mainApp.status == .enabled
    }
}

/// The server's JSON API. Requests carry the header the server requires of Referee's apps.
enum API {

    static func request(_ path: String, body: [String: Any]? = nil) async -> Data? {
        var request = URLRequest(url: server.appendingPathComponent(path), timeoutInterval: 4)
        request.setValue("1", forHTTPHeaderField: "X-Referee")
        if let body {
            request.httpMethod = "POST"
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = try? JSONSerialization.data(withJSONObject: body)
        }
        return try? await URLSession.shared.data(for: request).0
    }

    static func get(_ path: String) async -> [String: Any]? {
        guard let data = await request(path) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }

    static func getList(_ path: String) async -> [[String: Any]] {
        guard let data = await request(path) else { return [] }
        return (try? JSONSerialization.jsonObject(with: data)) as? [[String: Any]] ?? []
    }

    static func post(_ path: String, _ body: [String: Any]) async -> [String: Any]? {
        guard let data = await request(path, body: body) else { return nil }
        return (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
    }
}

/// The Word helper's citation style, kept in ~/.referee/config.json.
enum WordSettings {

    static let file = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent(".referee/config.json")

    static var style: String {
        get {
            guard let data = try? Data(contentsOf: file),
                  let config = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return "apa" }
            return config["style"] as? String ?? "apa"
        }
        set {
            var config: [String: Any] = [:]
            if let data = try? Data(contentsOf: file),
               let existing = try? JSONSerialization.jsonObject(with: data) as? [String: Any] { config = existing }
            config["style"] = newValue
            try? FileManager.default.createDirectory(at: file.deletingLastPathComponent(), withIntermediateDirectories: true)
            if let data = try? JSONSerialization.data(withJSONObject: config, options: .prettyPrinted) { try? data.write(to: file) }
        }
    }
}

/// Finds the browser the Referee extension is loaded in, and its ID, from the browser's own settings.
enum Library {

    static let browsers = [("BraveSoftware/Brave-Browser", "Brave Browser"), ("Google/Chrome", "Google Chrome"), ("Chromium", "Chromium")]

    static func open(repo: URL) {
        let extensionDir = repo.appendingPathComponent("extension").path
        let support = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Application Support")
        for (folder, app) in browsers {
            let base = support.appendingPathComponent(folder)
            let profiles = (try? FileManager.default.contentsOfDirectory(atPath: base.path)) ?? []
            for profile in profiles {
                for name in ["Secure Preferences", "Preferences"] {
                    let file = base.appendingPathComponent(profile).appendingPathComponent(name)
                    guard let data = try? Data(contentsOf: file),
                          let json = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
                          let settings = (json["extensions"] as? [String: Any])?["settings"] as? [String: Any] else { continue }
                    for (id, info) in settings {
                        let path = ((info as? [String: Any])?["path"] as? String ?? "").trimmingCharacters(in: CharacterSet(charactersIn: "/"))
                        if path == extensionDir.trimmingCharacters(in: CharacterSet(charactersIn: "/")) {
                            let url = "chrome-extension://\(id)/library/library.html"
                            let task = Process()
                            task.executableURL = URL(fileURLWithPath: "/usr/bin/open")
                            task.arguments = ["-a", app, url]
                            try? task.run()
                            return
                        }
                    }
                }
            }
        }
        let alert = NSAlert()
        alert.messageText = "Couldn't find the Referee extension"
        alert.informativeText = "Load the extension folder in Brave or Chrome first."
        alert.runModal()
    }
}

let styles = [("apa", "APA 7"), ("harvard", "Harvard"), ("mla", "MLA 9"), ("ieee", "IEEE (Numbered)"), ("ams", "AMS (Numbered)")]
let keepOptions = [(15, "15 Minutes"), (60, "1 Hour"), (1440, "1 Day")]

struct MenuContent: View {

    @ObservedObject var model: Model
    let repo: URL
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        Text(statusLine)
        Text("\(model.saved) Saved · \(model.temporary) Temporary")
        if model.online && !model.hasKey {
            Button("Add API Key…") { show("settings") }
        }
        Divider()
        Toggle("Research Mode", isOn: Binding(get: { model.focus }, set: { model.setResearch($0) }))
        Menu("Project") {
            Picker("Project", selection: Binding(get: { model.project }, set: { model.setProject($0) })) {
                Text("No Project").tag("")
                ForEach(model.projects, id: \.self) { Text($0).tag($0) }
            }
            .pickerStyle(.inline)
            .labelsHidden()
            Divider()
            Button("New Project…") { show("new-project") }
        }
        Menu("Citation Style in Word") {
            Picker("Style", selection: Binding(get: { model.style }, set: { model.setStyle($0) })) {
                ForEach(styles, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.inline)
            .labelsHidden()
        }
        Menu("Keep Unsaved Reading For") {
            Picker("Keep", selection: Binding(get: { model.keepMinutes }, set: { model.setKeep($0) })) {
                ForEach(keepOptions, id: \.0) { Text($0.1).tag($0.0) }
            }
            .pickerStyle(.inline)
            .labelsHidden()
        }
        Divider()
        Button("Open Library") { Library.open(repo: repo) }
        Button("Settings…") { show("settings") }
            .keyboardShortcut(",")
        Divider()
        Button("Quit Referee") { NSApp.terminate(nil) }
            .keyboardShortcut("q")
    }

    private var statusLine: String {
        if !model.online { return "Server Not Running" }
        if !model.hasKey { return "No API Key" }
        let state = model.focus ? "Research Mode On" : model.writing ? "Writing: Capturing" : "Not Capturing"
        return model.helper ? state : "\(state) · Word Helper Not Running"
    }

    private func show(_ id: String) {
        openWindow(id: id)
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct NewProjectView: View {

    @ObservedObject var model: Model
    @State private var name = ""
    @FocusState private var focused: Bool
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 10) {
                Image(systemName: "folder.badge.plus")
                    .font(.title2)
                    .foregroundStyle(.secondary)
                Text("New Project").font(.title3.weight(.semibold))
            }
            Text("It becomes the current project, so reading you save or cite goes into it.")
                .font(.callout)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            TextField("Project name", text: $name)
                .textFieldStyle(.plain)
                .font(.body)
                .focused($focused)
                .onSubmit(create)
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .glassCard()
            HStack {
                Spacer()
                Button("Cancel") { dismiss() }
                    .keyboardShortcut(.cancelAction)
                    .glassButton()
                Button("Create", action: create)
                    .keyboardShortcut(.defaultAction)
                    .disabled(name.trimmingCharacters(in: .whitespaces).isEmpty)
                    .prominentGlassButton()
            }
        }
        .padding(.horizontal, 22)
        .padding(.bottom, 20)
        .padding(.top, 4)
        .frame(width: 360)
        .fixedSize(horizontal: false, vertical: true)
        .background(WindowGlass().ignoresSafeArea())
        .onAppear { focused = true }
    }

    private func create() {
        let trimmed = name.trimmingCharacters(in: .whitespaces)
        guard !trimmed.isEmpty else { return }
        model.setProject(trimmed)
        name = ""
        dismiss()
    }
}

struct SettingsView: View {

    @ObservedObject var model: Model
    @Environment(\.openWindow) private var openWindow

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            header
            card(title: "Reading", symbol: "books.vertical") {
                row("Project") {
                    HStack(spacing: 8) {
                        Menu {
                            Picker("Project", selection: Binding(get: { model.project }, set: { model.setProject($0) })) {
                                Text("No Project").tag("")
                                ForEach(model.projects, id: \.self) { Text($0).tag($0) }
                            }
                            .pickerStyle(.inline)
                            .labelsHidden()
                        } label: {
                            Text(model.project.isEmpty ? "No Project" : model.project)
                        }
                        .fixedSize()
                        .glassButton()
                        Button {
                            openWindow(id: "new-project")
                            NSApp.activate(ignoringOtherApps: true)
                        } label: {
                            Image(systemName: "plus")
                        }
                        .help("New project")
                        .glassButton()
                    }
                }
                Divider().opacity(0.4)
                VStack(alignment: .leading, spacing: 8) {
                    Text("Keep unsaved reading for")
                    Picker("Keep unsaved reading for", selection: Binding(get: { model.keepMinutes }, set: { model.setKeep($0) })) {
                        ForEach(keepOptions, id: \.0) { Text($0.1).tag($0.0) }
                    }
                    .pickerStyle(.segmented)
                    .labelsHidden()
                    .frame(maxWidth: .infinity)
                }
            }
            card(title: "Word", symbol: "doc.text") {
                row("Citation style") {
                    Menu {
                        Picker("Style", selection: Binding(get: { model.style }, set: { model.setStyle($0) })) {
                            ForEach(styles, id: \.0) { Text($0.1).tag($0.0) }
                        }
                        .pickerStyle(.inline)
                        .labelsHidden()
                    } label: {
                        Text(styles.first { $0.0 == model.style }?.1 ?? "APA 7")
                    }
                    .fixedSize()
                    .glassButton()
                }
            }
            card(title: "Anthropic", symbol: "key") {
                ApiKeyView(model: model)
            }
            card(title: "General", symbol: "gearshape") {
                row("Open Referee at login") {
                    Toggle("Open Referee at login", isOn: Binding(get: { model.openAtLogin }, set: { model.setOpenAtLogin($0) }))
                        .toggleStyle(.switch)
                        .labelsHidden()
                }
            }
        }
        .padding(.horizontal, 22)
        .padding(.bottom, 22)
        .padding(.top, 4)
        .frame(width: 400)
        .fixedSize(horizontal: false, vertical: true)
        .background(WindowGlass().ignoresSafeArea())
    }

    private var header: some View {
        HStack(spacing: 12) {
            Image(nsImage: whistle(model.capturing))
                .resizable()
                .frame(width: 26, height: 26)
            Text("Referee").font(.title2.weight(.semibold))
            Spacer()
            HStack(spacing: 6) {
                Circle().fill(model.online ? (model.capturing ? Color.green : Color.secondary) : Color.orange)
                    .frame(width: 7, height: 7)
                Text(!model.online ? "Server not running" : model.capturing ? "Capturing" : "Not capturing")
                    .font(.callout)
                    .foregroundStyle(.secondary)
            }
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .glassCapsule()
        }
    }

    private func card<Content: View>(title: String, symbol: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Label(title, systemImage: symbol)
                .font(.subheadline.weight(.semibold))
                .foregroundStyle(.secondary)
            VStack(alignment: .leading, spacing: 12) { content() }
                .padding(14)
                .frame(maxWidth: .infinity, alignment: .leading)
                .glassCard()
        }
    }

    private func row<Control: View>(_ label: String, @ViewBuilder control: () -> Control) -> some View {
        HStack {
            Text(label)
            Spacer()
            control()
        }
    }
}

/// Paste-in API key: checked with Anthropic, then kept in the Keychain. The key is never shown again.
struct ApiKeyView: View {

    @ObservedObject var model: Model
    @State private var key = ""
    @State private var problem: String?
    @State private var checking = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            if model.hasKey {
                HStack {
                    Label("Key saved, ending …\(model.keyEnds)", systemImage: "checkmark.seal.fill")
                        .foregroundStyle(.green)
                    Spacer()
                    if model.keySource == "password store" {
                        Button("Remove") { model.removeKey() }.glassButton()
                    }
                }
                if model.keySource == "env" {
                    Text("From server/.env. Paste a key below to keep it in the Keychain instead.")
                        .font(.caption).foregroundStyle(.secondary)
                }
            } else {
                Text("Referee checks claims with Claude, using your own Anthropic API key. Create one at console.anthropic.com.")
                    .font(.callout).foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            HStack(spacing: 8) {
                SecureField(model.hasKey ? "Replace with a new key" : "Paste your API key (sk-ant-…)", text: $key)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 10)
                    .padding(.vertical, 7)
                    .glassCard()
                    .onSubmit(save)
                Button(checking ? "Checking…" : "Save", action: save)
                    .disabled(key.trimmingCharacters(in: .whitespaces).isEmpty || checking)
                    .prominentGlassButton()
            }
            if let problem {
                Text(problem).font(.caption).foregroundStyle(.orange)
            }
        }
    }

    private func save() {
        let entered = key
        checking = true
        problem = nil
        Task {
            problem = await model.saveKey(entered)
            checking = false
            if problem == nil { key = "" }
        }
    }
}

func whistle(_ filled: Bool) -> NSImage {
    let image = Bundle.main.image(forResource: filled ? "whistleOnTemplate" : "whistleOffTemplate") ?? NSImage()
    image.isTemplate = true
    return image
}

// Liquid Glass on macOS 26, frosted material on earlier versions.
extension View {

    @ViewBuilder func glassCard() -> some View {
        if #available(macOS 26.0, *) {
            self.glassEffect(.regular, in: .rect(cornerRadius: 16))
        } else {
            self.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16))
        }
    }

    @ViewBuilder func glassCapsule() -> some View {
        if #available(macOS 26.0, *) {
            self.glassEffect(.regular, in: .capsule)
        } else {
            self.background(.regularMaterial, in: Capsule())
        }
    }

    @ViewBuilder func prominentGlassButton() -> some View {
        if #available(macOS 26.0, *) {
            self.buttonStyle(.glassProminent)
        } else {
            self.buttonStyle(.borderedProminent)
        }
    }

    @ViewBuilder func glassButton() -> some View {
        if #available(macOS 26.0, *) {
            self.buttonStyle(.glass)
        } else {
            self.buttonStyle(.bordered)
        }
    }
}

/// Makes the settings window itself translucent, with its title bar hidden.
struct WindowGlass: NSViewRepresentable {

    func makeNSView(context: Context) -> NSView {
        let view = NSVisualEffectView()
        view.material = .underWindowBackground
        view.blendingMode = .behindWindow
        view.state = .active
        DispatchQueue.main.async {
            guard let window = view.window else { return }
            window.titlebarAppearsTransparent = true
            window.titleVisibility = .hidden
            window.styleMask.insert(.fullSizeContentView)
            window.isMovableByWindowBackground = true
            window.backgroundColor = .clear
        }
        return view
    }

    func updateNSView(_ nsView: NSView, context: Context) {}
}

/// The repository this app was built from: its Python parts and the extension folder.
let repository = URL(fileURLWithPath: Bundle.main.object(forInfoDictionaryKey: "RefereeRepository") as? String ?? "")

final class AppDelegate: NSObject, NSApplicationDelegate {

    let services: Services? = Services(repo: repository)

    func applicationDidFinishLaunching(_ notification: Notification) {
        services?.startAll()
    }

    func applicationWillTerminate(_ notification: Notification) {
        services?.stopAll()
    }
}

@main
struct RefereeApp: App {

    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var model = Model()
    let repo = repository

    var body: some Scene {
        MenuBarExtra {
            MenuContent(model: model, repo: repo)
        } label: {
            // The whistle: filled while capturing, an outline when idle.
            Image(nsImage: icon(model.capturing ? "whistleOnTemplate" : "whistleOffTemplate"))
            if !model.online { Text("⚠︎") }
        }
        Window("New Project", id: "new-project") {
            NewProjectView(model: model)
        }
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
        Window("Referee Settings", id: "settings") {
            SettingsView(model: model)
        }
        .windowResizability(.contentSize)
        .windowStyle(.hiddenTitleBar)
    }

    private func icon(_ name: String) -> NSImage {
        let image = Bundle.main.image(forResource: name) ?? NSImage()
        image.size = NSSize(width: 18, height: 18)
        image.isTemplate = true
        return image
    }
}

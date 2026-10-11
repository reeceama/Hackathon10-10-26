import AppKit
import Carbon
import SwiftUI

extension Notification.Name {
    static let researchChanged = Notification.Name("RefereeResearchChanged")
}

/// A global keyboard shortcut that switches research mode on or off from any app. Uses macOS's
/// hotkey service, which needs no extra permissions. Saved as a key code and modifiers.
@MainActor
final class Shortcut: ObservableObject {

    static let shared = Shortcut()

    @Published private(set) var keyCode: UInt32? = nil
    @Published private(set) var modifiers: UInt32 = 0
    private var hotKey: EventHotKeyRef?
    private var installed = false

    private init() {
        let defaults = UserDefaults.standard
        if defaults.object(forKey: "shortcutKey") != nil {
            keyCode = UInt32(defaults.integer(forKey: "shortcutKey"))
            modifiers = UInt32(defaults.integer(forKey: "shortcutModifiers"))
        }
    }

    /// Called at launch: listen for the saved shortcut.
    func start() {
        installHandler()
        register()
    }

    func set(keyCode: UInt32, flags: NSEvent.ModifierFlags) {
        self.keyCode = keyCode
        modifiers = Shortcut.carbon(flags)
        UserDefaults.standard.set(Int(keyCode), forKey: "shortcutKey")
        UserDefaults.standard.set(Int(modifiers), forKey: "shortcutModifiers")
        register()
    }

    func clear() {
        keyCode = nil
        UserDefaults.standard.removeObject(forKey: "shortcutKey")
        UserDefaults.standard.removeObject(forKey: "shortcutModifiers")
        register()
    }

    /// The shortcut as macOS shows them, e.g. ⌃⌥⌘R.
    var label: String? {
        guard let keyCode else { return nil }
        var text = ""
        if modifiers & UInt32(controlKey) != 0 { text += "⌃" }
        if modifiers & UInt32(optionKey) != 0 { text += "⌥" }
        if modifiers & UInt32(shiftKey) != 0 { text += "⇧" }
        if modifiers & UInt32(cmdKey) != 0 { text += "⌘" }
        return text + Shortcut.keyName(keyCode)
    }

    private func register() {
        if let hotKey { UnregisterEventHotKey(hotKey); self.hotKey = nil }
        guard let keyCode else { return }
        let id = EventHotKeyID(signature: OSType(0x52464545), id: 1)  // "RFEE"
        RegisterEventHotKey(keyCode, modifiers, id, GetApplicationEventTarget(), 0, &hotKey)
    }

    private func installHandler() {
        guard !installed else { return }
        installed = true
        var type = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
            Task { @MainActor in await Shortcut.toggleResearch() }
            return noErr
        }, 1, &type, nil, nil)
    }

    /// Flips research mode, as the menu's Research Mode switch does.
    static func toggleResearch() async {
        let on = (await API.get("writing"))?["focus"] as? Bool ?? false
        _ = await API.post("focus", ["on": !on])
        NSSound(named: on ? "Pop" : "Tink")?.play()  // a quiet cue, since nothing else is on screen
        NotificationCenter.default.post(name: .researchChanged, object: nil)  // update the whistle now
    }

    static func carbon(_ flags: NSEvent.ModifierFlags) -> UInt32 {
        var value: UInt32 = 0
        if flags.contains(.command) { value |= UInt32(cmdKey) }
        if flags.contains(.option) { value |= UInt32(optionKey) }
        if flags.contains(.control) { value |= UInt32(controlKey) }
        if flags.contains(.shift) { value |= UInt32(shiftKey) }
        return value
    }

    static func keyName(_ keyCode: UInt32) -> String {
        let special: [UInt32: String] = [49: "Space", 36: "↩", 48: "⇥", 53: "⎋", 51: "⌫", 123: "←", 124: "→", 125: "↓", 126: "↑",
                                          122: "F1", 120: "F2", 99: "F3", 118: "F4", 96: "F5", 97: "F6", 98: "F7", 100: "F8", 101: "F9", 109: "F10", 103: "F11", 111: "F12"]
        if let name = special[keyCode] { return name }
        let letters: [UInt32: String] = [0: "A", 11: "B", 8: "C", 2: "D", 14: "E", 3: "F", 5: "G", 4: "H", 34: "I", 38: "J", 40: "K", 37: "L", 46: "M",
                                         45: "N", 31: "O", 35: "P", 12: "Q", 15: "R", 1: "S", 17: "T", 32: "U", 9: "V", 13: "W", 7: "X", 16: "Y", 6: "Z",
                                         29: "0", 18: "1", 19: "2", 20: "3", 21: "4", 23: "5", 22: "6", 26: "7", 28: "8", 25: "9"]
        return letters[keyCode] ?? "Key \(keyCode)"
    }
}

/// Settings row: click, then press the keys. Escape cancels; Delete clears. A shortcut needs
/// ⌘, ⌥ or ⌃, so it can't take over ordinary typing.
struct ShortcutRecorder: View {

    @ObservedObject private var shortcut = Shortcut.shared
    @State private var recording = false
    @State private var monitor: Any?

    var body: some View {
        HStack(spacing: 8) {
            Button(recording ? "Press keys…" : shortcut.label ?? "Record Shortcut") {
                recording ? stop() : start()
            }
            .glassButton()
            if shortcut.label != nil && !recording {
                Button { shortcut.clear() } label: { Image(systemName: "xmark.circle.fill") }
                    .buttonStyle(.plain)
                    .foregroundStyle(.secondary)
                    .help("Remove the shortcut")
            }
        }
    }

    private func start() {
        recording = true
        monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { event in
            let flags = event.modifierFlags.intersection([.command, .option, .control, .shift])
            switch event.keyCode {
            case 53: stop()                                   // Escape: cancel
            case 51, 117: shortcut.clear(); stop()            // Delete: remove
            default:
                if flags.contains(.command) || flags.contains(.option) || flags.contains(.control) {
                    shortcut.set(keyCode: UInt32(event.keyCode), flags: flags)
                    stop()
                } else {
                    NSSound.beep()                            // needs ⌘, ⌥ or ⌃
                }
            }
            return nil
        }
    }

    private func stop() {
        recording = false
        if let monitor { NSEvent.removeMonitor(monitor) }
        monitor = nil
    }
}

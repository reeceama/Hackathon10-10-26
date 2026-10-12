import SwiftUI

/// Third-party services Referee connects to, in one window: the AI that checks your writing, and
/// Todoist for meeting action points. More AI providers can be added here later.
struct IntegrationsView: View {

    @ObservedObject var model: Model
    @State private var open: String? = "anthropic"
    @State private var todoist = false

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Integrations").font(.title2.weight(.semibold)).padding(.top, 28)
                Text("Services Referee connects to. Keys and tokens are kept in your Keychain.")
                    .font(.callout)
                    .foregroundStyle(.secondary)
                Text("AI").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 4)
                service("anthropic", name: "Anthropic Claude", symbol: "sparkles",
                        about: "Checks your claims and theorems against your reading. Required for checking.",
                        connected: model.hasKey) {
                    ApiKeyView(model: model)
                }
                Text("Tasks").font(.subheadline.weight(.semibold)).foregroundStyle(.secondary).padding(.top, 4)
                service("todoist", name: "Todoist", symbol: "checklist",
                        about: "Your meeting action points as Todoist tasks, ticked off in both.",
                        connected: todoist) {
                    TodoistView()
                }
            }
            .padding(.horizontal, 24)
            .padding(.bottom, 24)
        }
        .frame(minWidth: 520, idealWidth: 560, minHeight: 440, idealHeight: 560)
        .background(WindowGlass().ignoresSafeArea())
        .task { await refresh() }
        .onChange(of: open) { _, _ in Task { await refresh() } }
    }

    private func refresh() async {
        todoist = (await API.get("todoist"))?["connected"] as? Bool ?? false
    }

    /// One service: a row with its status that opens to connect or disconnect it.
    private func service<Content: View>(_ id: String, name: String, symbol: String, about: String, connected: Bool,
                                        @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Button {
                open = open == id ? nil : id
            } label: {
                HStack(spacing: 12) {
                    Image(systemName: symbol).font(.title3).frame(width: 28)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(name).fontWeight(.semibold)
                        Text(about).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
                    }
                    Spacer()
                    Text(connected ? "Connected" : "Not connected")
                        .font(.caption)
                        .foregroundStyle(connected ? .green : .secondary)
                        .fixedSize()
                    Image(systemName: open == id ? "chevron.up" : "chevron.down").foregroundStyle(.secondary)
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)
            if open == id {
                Divider().opacity(0.4)
                content()
            }
        }
        .padding(14)
        .frame(maxWidth: .infinity, alignment: .leading)
        .glassCard()
    }
}

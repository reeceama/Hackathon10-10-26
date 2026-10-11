import Foundation

/// Starts Referee's Python parts (the server, the Word helper and the Word add-in's HTTPS
/// server) when the app opens, restarts any that stop, and stops them all when it quits.
final class Services {

    struct Service {
        let name: String
        let folder: String
        let arguments: [String]
    }

    let repo: URL
    private var processes: [String: Process] = [:]
    private var stopping = false
    private let logs = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/Referee")

    init(repo: URL) {
        self.repo = repo
    }

    var services: [Service] {
        [
            Service(name: "server", folder: "server", arguments: ["-m", "uvicorn", "main:app", "--port", "8000"]),
            Service(name: "helper", folder: "word-helper", arguments: ["helper.py"]),
            Service(name: "word", folder: "word-addin", arguments: ["server.py"]),
        ]
    }

    func startAll() {
        try? FileManager.default.createDirectory(at: logs, withIntermediateDirectories: true)
        stopping = false
        for service in services { start(service) }
    }

    func stopAll() {
        stopping = true
        for process in processes.values where process.isRunning { process.terminate() }
        processes.removeAll()
    }

    func isRunning(_ name: String) -> Bool {
        processes[name]?.isRunning ?? false
    }

    private func start(_ service: Service) {
        let process = Process()
        process.executableURL = repo.appendingPathComponent(".venv/bin/python")
        process.arguments = service.arguments
        process.currentDirectoryURL = repo.appendingPathComponent(service.folder)
        let log = logs.appendingPathComponent("\(service.name).log")
        if !FileManager.default.fileExists(atPath: log.path) {
            FileManager.default.createFile(atPath: log.path, contents: nil)
        }
        if let handle = try? FileHandle(forWritingTo: log) {
            handle.seekToEndOfFile()
            process.standardOutput = handle
            process.standardError = handle
        }
        process.terminationHandler = { [weak self] _ in
            // Restart anything that stops, after a pause so a crash can't spin.
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
                guard let self, !self.stopping else { return }
                self.start(service)
            }
        }
        do {
            try process.run()
            processes[service.name] = process
        } catch {
            NSLog("Referee couldn't start \(service.name): \(error)")
        }
    }
}

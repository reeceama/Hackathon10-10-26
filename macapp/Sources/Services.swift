import Foundation

/// Runs referee.py, the cross-platform launcher for Referee's Python parts (the server, the Word
/// helper and the Word add-in's HTTPS server), while the app is open. The launcher restarts any
/// part that stops; this restarts the launcher itself if it stops, and stops it when the app quits.
final class Services {

    let repo: URL
    private var launcher: Process?
    private var stopping = false

    init(repo: URL) {
        self.repo = repo
    }

    func startAll() {
        stopping = false
        let process = Process()
        process.executableURL = repo.appendingPathComponent(".venv/bin/python")
        process.arguments = ["referee.py"]
        process.currentDirectoryURL = repo
        process.terminationHandler = { [weak self] _ in
            DispatchQueue.main.asyncAfter(deadline: .now() + 5) {
                guard let self, !self.stopping else { return }
                self.startAll()
            }
        }
        do {
            try process.run()
            launcher = process
        } catch {
            NSLog("Referee couldn't start its launcher: \(error)")
        }
    }

    func stopAll() {
        stopping = true
        launcher?.terminate()  // the launcher stops every part before it exits
        launcher?.waitUntilExit()
    }
}

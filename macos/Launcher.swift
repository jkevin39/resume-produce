import Cocoa

final class Launcher: NSObject, NSApplicationDelegate {
    var process: Process?
    var reused = false
    let repo = Bundle.main.object(forInfoDictionaryKey: "ResumeProjectPath") as! String
    let logURL = FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Library/Logs/ResumeProduce/launcher.log")
    func alert(_ message: String) {
        NSApp.activate(ignoringOtherApps: true)
        let a = NSAlert(); a.messageText = "简历工作台"; a.informativeText = message; a.runModal()
    }
    func command(_ args: [String]) -> Process {
        let p = Process()
        p.executableURL = URL(fileURLWithPath: repo + "/.venv/bin/python")
        p.currentDirectoryURL = URL(fileURLWithPath: repo)
        p.arguments = ["-m", "resume_app.local"] + args
        if let directory = Bundle.main.object(forInfoDictionaryKey: "ResumeDataDirectory") as? String {
            p.arguments! += ["--data-dir", directory]
        }
        var env = ProcessInfo.processInfo.environment
        env["PYTHONDONTWRITEBYTECODE"] = "1"; p.environment = env
        return p
    }
    func applicationDidFinishLaunching(_ note: Notification) {
        let menu = NSMenu(); let root = NSMenuItem(); menu.addItem(root)
        let actions = NSMenu(); root.submenu = actions
        actions.addItem(withTitle: "打开工作台", action: #selector(openPage), keyEquivalent: "o").target = self
        actions.addItem(withTitle: "查看启动日志", action: #selector(openLog), keyEquivalent: "l").target = self
        actions.addItem(NSMenuItem.separator())
        actions.addItem(withTitle: "退出简历工作台", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        NSApp.mainMenu = menu
        startService()
    }
    func startService() {
        guard process?.isRunning != true else { return }
        do {
            try FileManager.default.createDirectory(at: logURL.deletingLastPathComponent(), withIntermediateDirectories: true)
            if !FileManager.default.fileExists(atPath: logURL.path) { FileManager.default.createFile(atPath: logURL.path, contents: nil) }
            let log = try FileHandle(forWritingTo: logURL); log.seekToEndOfFile()
            let p = command(["start", "--reuse"])
            p.standardOutput = log; p.standardError = log
            p.terminationHandler = { child in DispatchQueue.main.async {
                self.process = nil
                if child.terminationStatus != 0 {
                    self.alert("启动未完成。请通过“查看启动日志”检查原因。\n日志：" + self.logURL.path)
                } else {
                    self.reused = true
                    self.alert("已打开原启动入口管理的服务。退出本应用不会停止该服务，请在原入口停止。")
                }
            }}
            try p.run(); process = p
        } catch { alert("无法启动，请确认项目位置及 .venv 依赖可用。\n" + error.localizedDescription) }
    }
    @objc func openPage() {
        guard process?.isRunning == true else { startService(); return }
        do {
            let p = command(["open"])
            let log = try FileHandle(forWritingTo: logURL); log.seekToEndOfFile()
            p.standardOutput = log; p.standardError = log
            p.terminationHandler = { child in
                if child.terminationStatus != 0 { DispatchQueue.main.async {
                    self.alert("页面尚未就绪或无法打开，请稍后重试；详情见启动日志。")
                }}
            }
            try p.run()
        }
        catch { alert("打开失败：" + error.localizedDescription) }
    }
    @objc func openLog() { NSWorkspace.shared.open(logURL) }
    func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows: Bool) -> Bool { openPage(); return true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        guard let p = process, p.isRunning else { return .terminateNow }
        let a = NSAlert(); a.messageText = "停止服务并退出？"
        a.informativeText = "未正式保存的草稿会丢失。已保存的历史不受影响。关闭网页不会停止服务。"
        a.addButton(withTitle: "停止并退出"); a.addButton(withTitle: "取消")
        guard a.runModal() == .alertFirstButtonReturn else { return .terminateCancel }
        p.terminationHandler = { _ in DispatchQueue.main.async { NSApp.reply(toApplicationShouldTerminate: true) } }
        p.terminate(); return .terminateLater
    }
}
let app = NSApplication.shared
let delegate = Launcher(); app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()

// Qorgan iOS SDK (reference implementation, embed into the bank's app).
//
// CXCallObserver reports every call the system knows about, including VoIP calls of apps
// that use CallKit (WhatsApp, Telegram). Only the fact and timing of the call are used:
// iOS does not expose the number or audio, and Qorgan does not need them.
import CallKit
import Foundation

public protocol QorganSignalSink: AnyObject {
    func callStarted(callID: UUID, outgoing: Bool)
    func callEnded(callID: UUID)
}

public final class QorganCallObserver: NSObject, CXCallObserverDelegate {
    private let observer = CXCallObserver()
    private weak var sink: QorganSignalSink?
    private var reported = Set<UUID>()

    public init(sink: QorganSignalSink) {
        self.sink = sink
        super.init()
        observer.setDelegate(self, queue: nil)
        // Calls already in progress when the bank app is opened (the typical scam case).
        observer.calls.filter { $0.hasConnected && !$0.hasEnded }.forEach(report)
    }

    public var hasActiveCall: Bool { observer.calls.contains { !$0.hasEnded } }

    public func callObserver(_ callObserver: CXCallObserver, callChanged call: CXCall) {
        if call.hasEnded {
            if reported.remove(call.uuid) != nil { sink?.callEnded(callID: call.uuid) }
        } else if call.hasConnected {
            report(call)
        }
    }

    private func report(_ call: CXCall) {
        guard !reported.contains(call.uuid) else { return }
        reported.insert(call.uuid)
        sink?.callStarted(callID: call.uuid, outgoing: call.isOutgoing)
    }
}

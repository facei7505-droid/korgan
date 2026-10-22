// Qorgan Android SDK (reference implementation, embed into the bank's app).
//
// Reports ONLY call metadata to the bank backend: a call started/ended, and whether it is
// a cellular call or a VoIP/messenger call (WhatsApp, Telegram). No audio, no transcript,
// no phone number (that would need READ_CALL_LOG; the operator signal covers numbers).
//
// Requires: <uses-permission android:name="android.permission.READ_PHONE_STATE"/> (runtime consent).
package kz.qorgan.sdk

import android.content.Context
import android.media.AudioManager
import android.os.Build
import android.telephony.TelephonyCallback
import android.telephony.TelephonyManager
import androidx.annotation.RequiresApi
import java.util.concurrent.Executors

interface SignalSink {
    fun callStarted(channel: String)   // "cellular" | "voip"
    fun callEnded()
}

@RequiresApi(Build.VERSION_CODES.S)
class QorganCallSignals(context: Context, private val sink: SignalSink) {
    private val telephony = context.getSystemService(TelephonyManager::class.java)
    private val audio = context.getSystemService(AudioManager::class.java)
    private val executor = Executors.newSingleThreadExecutor()
    private var active: String? = null

    private val cellular = object : TelephonyCallback(), TelephonyCallback.CallStateListener {
        override fun onCallStateChanged(state: Int) {
            when (state) {
                TelephonyManager.CALL_STATE_OFFHOOK -> start("cellular")
                TelephonyManager.CALL_STATE_IDLE -> if (active == "cellular") end()
            }
        }
    }

    // Messenger calls do not go through telephony, but they switch audio to MODE_IN_COMMUNICATION.
    private val voip = AudioManager.OnModeChangedListener { mode ->
        if (mode == AudioManager.MODE_IN_COMMUNICATION) start("voip")
        else if (mode == AudioManager.MODE_NORMAL && active == "voip") end()
    }

    fun start() {
        telephony.registerTelephonyCallback(executor, cellular)
        audio.addOnModeChangedListener(executor, voip)
    }

    fun stop() {
        telephony.unregisterTelephonyCallback(cellular)
        audio.removeOnModeChangedListener(voip)
    }

    private fun start(channel: String) {
        if (active != null) return
        active = channel
        sink.callStarted(channel)   // bank backend -> POST /v1/signals/call
    }

    private fun end() {
        active = null
        sink.callEnded()            // bank backend -> POST /v1/signals/call/{id}/end
    }
}

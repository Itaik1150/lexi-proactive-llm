package com.example.lexiparticipant

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.RingtoneManager
import android.os.Build
import android.os.PowerManager
import android.util.Log
import androidx.core.app.NotificationCompat
import com.google.firebase.messaging.FirebaseMessagingService
import com.google.firebase.messaging.RemoteMessage

class LexiMessagingService : FirebaseMessagingService() {

    override fun onNewToken(token: String) {
        // The token identifies this device to the server; never write it to the log.
        Log.d("FCM", "New token received (${token.length} characters)")
        val prefs = getSharedPreferences(AndroidBridge.PREFS_NAME, MODE_PRIVATE)
        prefs.edit().putString(AndroidBridge.KEY_FCM_TOKEN, token).apply()
    }

    override fun onMessageReceived(message: RemoteMessage) {
        super.onMessageReceived(message)

        val title          = message.notification?.title ?: message.data["title"] ?: "Lexi"
        val body           = message.notification?.body  ?: message.data["body"]  ?: "Tap to open chat"
        val conversationId = message.data["conversationId"]
        val experimentId   = message.data["experimentId"]

        // Build a direct deep-link URL when both IDs are present so the
        // notification tap lands in the exact conversation rather than home.
        // Both ids must be exactly 24 hex characters; anything else is ignored rather than put into a URL.
        val deepLinkUrl: String? = if (JoinLink.isExperimentId(conversationId) && JoinLink.isExperimentId(experimentId)) {
            "${BuildConfig.FRONTEND_BASE_URL}/e/$experimentId/c/$conversationId"
        } else {
            null  // fallback: MainActivity will load the cached experiment URL
        }

        showNotification(title, body, deepLinkUrl)
    }

    private fun wakeScreen() {
        // Briefly acquire a wake lock to power the screen on before posting the
        // notification. This is the most reliable cross-version approach — it works
        // on Android 8–14+ without requiring a manual user grant in Settings.
        // ACQUIRE_CAUSES_WAKEUP is what actually turns the display on.
        val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
        @Suppress("DEPRECATION")
        val wakeLock = powerManager.newWakeLock(
            PowerManager.FULL_WAKE_LOCK or
            PowerManager.ACQUIRE_CAUSES_WAKEUP or
            PowerManager.ON_AFTER_RELEASE,
            "lexi:nudge_wake"
        )
        wakeLock.acquire(5_000L)   // hold for 5 s — enough to read the heads-up banner
        wakeLock.release()
    }

    private fun showNotification(title: String, body: String, deepLinkUrl: String? = null) {
        wakeScreen()

        // lexi_nudges_v2: IMPORTANCE_HIGH channel.
        // A new channel ID is required because Android locks in a channel's
        // importance once created — the old lexi_nudges (IMPORTANCE_DEFAULT)
        // cannot be upgraded in-place on a device that already has it.
        val channelId = "lexi_nudges_v2"

        val intent = Intent(this, MainActivity::class.java).apply {
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
            if (deepLinkUrl != null) {
                putExtra("deepLinkUrl", deepLinkUrl)
            }
        }

        // Use a unique request code per nudge so each PendingIntent is distinct
        // and notifications don't silently replace each other.
        val requestCode = (System.currentTimeMillis() % Int.MAX_VALUE).toInt()
        val immutableFlag = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M)
            PendingIntent.FLAG_IMMUTABLE else 0

        val pendingIntent = PendingIntent.getActivity(
            this,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or immutableFlag
        )

        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val channel = NotificationChannel(
                channelId,
                "Lexi Nudges",
                NotificationManager.IMPORTANCE_HIGH   // heads-up banner + sound + vibration
            ).apply {
                description = "Proactive conversation starters from Lexi"
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 400, 200, 400)
            }
            manager.createNotificationChannel(channel)
        }

        val soundUri = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION)

        val notification = NotificationCompat.Builder(this, channelId)
            .setSmallIcon(R.mipmap.faviconh)
            .setContentTitle(title)
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))  // expand long messages
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)   // pre-Oreo heads-up fallback
            .setSound(soundUri)
            .setVibrate(longArrayOf(0, 400, 200, 400))
            .setContentIntent(pendingIntent)
            .setFullScreenIntent(pendingIntent, true)        // wake screen + show over lock screen
            .apply {
                if (BuildConfig.HIDE_TEXT_ON_LOCK_SCREEN) {
                    // On a locked phone show only a generic notification; the message itself appears after unlocking.
                    setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                    setPublicVersion(
                        NotificationCompat.Builder(this@LexiMessagingService, channelId)
                            .setSmallIcon(R.mipmap.faviconh)
                            .setContentTitle(title)
                            .setContentText("You have a new message")
                            .build()
                    )
                }
            }
            .build()

        // Unique notification ID ensures each nudge appears as a separate entry
        // rather than silently updating the previous one.
        val notificationId = (System.currentTimeMillis() % Int.MAX_VALUE).toInt()
        manager.notify(notificationId, notification)
    }
}

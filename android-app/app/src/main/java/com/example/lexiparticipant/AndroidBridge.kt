package com.example.lexiparticipant

import android.content.Context
import android.content.SharedPreferences
import android.webkit.JavascriptInterface
import org.json.JSONObject

/**
 * The JavaScript interface the study's web app can call as `window.Android`.
 *
 * Keep it as small as possible: every method here is callable by any page shown in the WebView.
 * MainActivity only ever shows pages from this build's own web app (see UrlPolicy), and the web app
 * uses exactly the five methods below. Methods the web app does not call (reading the user id back,
 * forging the "opened from notification" flag, posting the token from native code) were removed.
 * Nothing secret (token, user id) is written to the log.
 */
class AndroidBridge(context: Context) {

    private val sharedPreferences: SharedPreferences =
        context.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)

    // The web app registers this token with the server after the participant logs in.
    @JavascriptInterface
    fun getFCMToken(): String = sharedPreferences.getString(KEY_FCM_TOKEN, "") ?: ""

    @JavascriptInterface
    fun isTokenAvailable(): Boolean = getFCMToken().isNotEmpty()

    @JavascriptInterface
    fun setCurrentUserId(userId: String) {
        sharedPreferences.edit().putString(KEY_USER_ID, userId.take(64)).apply()
    }

    @JavascriptInterface
    fun getDeviceInfo(): String {
        return JSONObject().apply {
            put("manufacturer", android.os.Build.MANUFACTURER)
            put("model", android.os.Build.MODEL)
            put("version", android.os.Build.VERSION.RELEASE)
            put("sdk", android.os.Build.VERSION.SDK_INT)
        }.toString()
    }

    // True once after the app was opened by tapping a proactive notification; reading it clears it.
    @JavascriptInterface
    fun wasOpenedFromNotification(): Boolean {
        val wasOpened = sharedPreferences.getBoolean(KEY_OPENED_FROM_NOTIFICATION, false)
        if (wasOpened) {
            sharedPreferences.edit().putBoolean(KEY_OPENED_FROM_NOTIFICATION, false).apply()
        }
        return wasOpened
    }

    companion object {
        // One preferences file for everything the bridge and the rest of the app share.
        const val PREFS_NAME = "lexi"
        const val KEY_FCM_TOKEN = "fcmToken"
        const val KEY_USER_ID = "userId"
        const val KEY_OPENED_FROM_NOTIFICATION = "openedFromNotification"
    }
}

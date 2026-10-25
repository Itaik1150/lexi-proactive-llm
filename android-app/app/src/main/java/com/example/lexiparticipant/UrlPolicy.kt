package com.example.lexiparticipant

import java.net.URI

/**
 * Decides which web addresses may load inside the app's WebView.
 *
 * The WebView has a JavaScript bridge attached (token, user id, device info), so only the study's own
 * web app may ever be shown there. Everything else (another site, a link inside a message) must open in
 * the normal browser instead. Plain Kotlin with no Android types, so it is covered by JVM unit tests.
 */
object UrlPolicy {
    /** "scheme://host:port" of an http(s) URL in a normalised form, or null if it is not a plain http(s) URL. */
    fun origin(url: String?): String? {
        if (url.isNullOrBlank()) return null
        return try {
            val uri = URI(url.trim())
            val scheme = uri.scheme?.lowercase() ?: return null
            if (scheme != "http" && scheme != "https") return null
            val host = uri.host?.lowercase() ?: return null // user@host tricks parse to the REAL host
            val port = if (uri.port == -1) (if (scheme == "https") 443 else 80) else uri.port
            "$scheme://$host:$port"
        } catch (e: Exception) {
            null // malformed (e.g. backslashes, spaces): never allowed
        }
    }

    /** True if [url] has exactly the same scheme, host and port as [allowedBase] (this build's FRONTEND_BASE_URL). */
    fun isAllowed(url: String?, allowedBase: String): Boolean {
        val allowed = origin(allowedBase) ?: return false
        return origin(url) == allowed
    }
}

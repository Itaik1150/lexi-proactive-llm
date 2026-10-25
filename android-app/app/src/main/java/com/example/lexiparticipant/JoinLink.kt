package com.example.lexiparticipant

/**
 * Reading and building experiment links.
 *
 * Plain Kotlin with no Android types, so it is covered by ordinary JVM unit tests.
 * Two rules keep the app safe:
 *  - an experiment id is accepted only if it is exactly 24 hexadecimal characters;
 *  - every URL the app opens is BUILT from this build's own FRONTEND_BASE_URL and a validated id,
 *    never taken from a link or from text the participant pasted.
 */
object JoinLink {
    private const val HEX_ID = "[a-fA-F0-9]{24}"

    private val ID_ONLY = Regex("^$HEX_ID$")

    // lexi://join/<id>  (the "Open Lexi" button on the invitation page)
    private val DEEP_LINK = Regex("^lexi://join/($HEX_ID)/?$")

    // https://host/join/<id> (invitation link) or https://host/e/<id>[/...] (web app link)
    private val WEB_LINK = Regex("^https?://[^\\s/]+/(?:e|join)/($HEX_ID)(?:[/?#].*)?$")

    fun isExperimentId(text: String?): Boolean = text != null && ID_ONLY.matches(text)

    /** The experiment id in a lexi://join/<id> link, or null if it is anything else. */
    fun idFromDeepLink(data: String?): String? =
        data?.trim()?.let { DEEP_LINK.find(it)?.groupValues?.get(1)?.lowercase() }

    /** The experiment id in a link the participant pasted (invitation or web app link), or null. */
    fun idFromPastedLink(text: String?): String? =
        text?.trim()?.let { WEB_LINK.find(it)?.groupValues?.get(1)?.lowercase() }

    /**
     * The URL a notification tap opens: this build's own frontend plus two validated ids.
     * Null unless BOTH ids are exactly 24 hex characters.
     */
    fun conversationUrl(frontendBase: String, experimentId: String?, conversationId: String?): String? =
        if (isExperimentId(experimentId) && isExperimentId(conversationId)) {
            "${experimentUrl(frontendBase, experimentId!!)}/c/${conversationId!!.lowercase()}"
        } else {
            null
        }

    /** The URL the app loads for an experiment: always this build's own frontend plus a validated id. */
    fun experimentUrl(frontendBase: String, experimentId: String): String =
        "${frontendBase.trimEnd('/')}/e/${experimentId.lowercase()}"
}

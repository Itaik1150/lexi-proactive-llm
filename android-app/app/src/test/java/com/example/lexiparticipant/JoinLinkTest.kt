package com.example.lexiparticipant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class JoinLinkTest {
    private val id = "64b7f0f0f0f0f0f0f0f0f0a1"

    @Test
    fun deepLinkYieldsTheExperimentId() {
        assertEquals(id, JoinLink.idFromDeepLink("lexi://join/$id"))
        assertEquals(id, JoinLink.idFromDeepLink("lexi://join/$id/"))
        assertEquals(id, JoinLink.idFromDeepLink("  lexi://join/$id  "))
    }

    @Test
    fun deepLinkIdIsNormalisedToLowerCase() {
        assertEquals(id, JoinLink.idFromDeepLink("lexi://join/${id.uppercase()}"))
    }

    @Test
    fun deepLinkRejectsAnythingElse() {
        assertNull(JoinLink.idFromDeepLink(null))
        assertNull(JoinLink.idFromDeepLink(""))
        assertNull(JoinLink.idFromDeepLink("lexi://join/"))
        assertNull(JoinLink.idFromDeepLink("lexi://join/abc"))
        assertNull(JoinLink.idFromDeepLink("lexi://join/${id}0"))                // 25 characters
        assertNull(JoinLink.idFromDeepLink("lexi://other/$id"))                  // wrong host
        assertNull(JoinLink.idFromDeepLink("http://join/$id"))                   // wrong scheme
        assertNull(JoinLink.idFromDeepLink("lexi://join/$id/extra"))             // trailing path
        assertNull(JoinLink.idFromDeepLink("lexi://join/$id?next=https://evil")) // query is not accepted
        assertNull(JoinLink.idFromDeepLink("lexi://join/${"g".repeat(24)}"))     // not hexadecimal
    }

    @Test
    fun pastedInvitationLinkAndWebLinkBothWork() {
        assertEquals(id, JoinLink.idFromPastedLink("https://lexi-server.example.com/join/$id"))
        assertEquals(id, JoinLink.idFromPastedLink("https://study.example.org/e/$id"))
        assertEquals(id, JoinLink.idFromPastedLink("https://study.example.org/e/$id/c/64b7f0f0f0f0f0f0f0f0f0b2"))
        assertEquals(id, JoinLink.idFromPastedLink("http://192.168.0.5:3000/e/$id"))
        assertEquals(id, JoinLink.idFromPastedLink("  https://study.example.org/join/$id  "))
    }

    @Test
    fun pastedLinkRejectsThingsThatAreNotExperimentLinks() {
        assertNull(JoinLink.idFromPastedLink(null))
        assertNull(JoinLink.idFromPastedLink(""))
        assertNull(JoinLink.idFromPastedLink("not a url"))
        assertNull(JoinLink.idFromPastedLink("ftp://host/e/$id"))
        assertNull(JoinLink.idFromPastedLink("https://host/other/$id"))
        assertNull(JoinLink.idFromPastedLink("https://host/e/abc"))
        assertNull(JoinLink.idFromPastedLink("https://host/e/${id}0"))
    }

    @Test
    fun theUrlTheAppLoadsIsBuiltFromTheBuildsOwnFrontendNeverFromPastedText() {
        assertEquals("https://app.example.org/e/$id", JoinLink.experimentUrl("https://app.example.org", id))
        assertEquals("https://app.example.org/e/$id", JoinLink.experimentUrl("https://app.example.org/", id))
        // a participant pasting a link on another host cannot redirect the app: only the id is used
        val pasted = "https://evil.example.com/join/$id"
        val built = JoinLink.experimentUrl("https://app.example.org", JoinLink.idFromPastedLink(pasted)!!)
        assertFalse(built.contains("evil"))
        assertTrue(built.startsWith("https://app.example.org/e/"))
    }

    @Test
    fun aNotificationTapOpensTheConversationBuiltFromValidatedIds() {
        val conv = "64b7f0f0f0f0f0f0f0f0f0b2"
        assertEquals(
            "https://app.example.org/e/$id/c/$conv",
            JoinLink.conversationUrl("https://app.example.org/", id, conv),
        )
        assertEquals(
            "https://app.example.org/e/$id/c/$conv",
            JoinLink.conversationUrl("https://app.example.org", id.uppercase(), conv.uppercase()),
        )
    }

    @Test
    fun aNotificationWithAMissingOrMalformedIdOpensNothing() {
        val conv = "64b7f0f0f0f0f0f0f0f0f0b2"
        assertNull(JoinLink.conversationUrl("https://app.example.org", null, conv))
        assertNull(JoinLink.conversationUrl("https://app.example.org", id, null))
        assertNull(JoinLink.conversationUrl("https://app.example.org", id, "abc"))
        assertNull(JoinLink.conversationUrl("https://app.example.org", "../evil", conv))
        assertNull(JoinLink.conversationUrl("https://app.example.org", id, "$conv/../x"))
    }

    @Test
    fun experimentIdValidation() {
        assertTrue(JoinLink.isExperimentId(id))
        assertTrue(JoinLink.isExperimentId(id.uppercase()))
        assertFalse(JoinLink.isExperimentId(null))
        assertFalse(JoinLink.isExperimentId(""))
        assertFalse(JoinLink.isExperimentId("$id\n"))
        assertFalse(JoinLink.isExperimentId("{\"\$ne\":\"\"}"))
    }
}

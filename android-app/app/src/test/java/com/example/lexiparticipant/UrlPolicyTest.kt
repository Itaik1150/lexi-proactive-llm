package com.example.lexiparticipant

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class UrlPolicyTest {
    private val base = "https://app.example.org"

    @Test
    fun theStudysOwnPagesAreAllowed() {
        assertTrue(UrlPolicy.isAllowed("https://app.example.org", base))
        assertTrue(UrlPolicy.isAllowed("https://app.example.org/e/64b7f0f0f0f0f0f0f0f0f0a1", base))
        assertTrue(UrlPolicy.isAllowed("https://app.example.org/e/x/c/y?z=1#frag", base))
        assertTrue(UrlPolicy.isAllowed("HTTPS://APP.EXAMPLE.ORG/e/x", base))
        assertTrue("default port is the same origin", UrlPolicy.isAllowed("https://app.example.org:443/e/x", base))
    }

    @Test
    fun otherSitesAreRefused() {
        assertFalse(UrlPolicy.isAllowed("https://evil.example.com/e/x", base))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org.evil.com/e/x", base))
        assertFalse(UrlPolicy.isAllowed("https://evil-app.example.org/e/x", base))
        assertFalse("subdomains are other origins", UrlPolicy.isAllowed("https://sub.app.example.org/e/x", base))
    }

    @Test
    fun differentSchemeOrPortIsADifferentOrigin() {
        assertFalse(UrlPolicy.isAllowed("http://app.example.org/e/x", base))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org:8443/e/x", base))
    }

    @Test
    fun userInfoTricksResolveToTheRealHost() {
        assertFalse(UrlPolicy.isAllowed("https://app.example.org@evil.example.com/e/x", base))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org:pw@evil.example.com/", base))
    }

    @Test
    fun nonWebAndMalformedUrlsAreRefused() {
        assertFalse(UrlPolicy.isAllowed(null, base))
        assertFalse(UrlPolicy.isAllowed("", base))
        assertFalse(UrlPolicy.isAllowed("   ", base))
        assertFalse(UrlPolicy.isAllowed("javascript:alert(1)", base))
        assertFalse(UrlPolicy.isAllowed("file:///data/data/com.example.lexiparticipant/shared_prefs/lexi.xml", base))
        assertFalse(UrlPolicy.isAllowed("content://com.example/x", base))
        assertFalse(UrlPolicy.isAllowed("intent://x#Intent;scheme=lexi;end", base))
        assertFalse(UrlPolicy.isAllowed("mailto:someone@example.org", base))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org\\@evil.example.com/", base))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org/with space", base))
        assertFalse("scheme-relative is not a full URL", UrlPolicy.isAllowed("//app.example.org/e/x", base))
    }

    @Test
    fun anInvalidAllowedBaseAllowsNothing() {
        assertFalse(UrlPolicy.isAllowed("https://app.example.org/e/x", "not a url"))
        assertFalse(UrlPolicy.isAllowed("https://app.example.org/e/x", ""))
    }

    @Test
    fun originIsNormalised() {
        assertEquals("https://app.example.org:443", UrlPolicy.origin("https://App.Example.org/path"))
        assertEquals("http://10.0.2.2:3000", UrlPolicy.origin("http://10.0.2.2:3000/e/x"))
        assertNull(UrlPolicy.origin("ftp://app.example.org"))
    }
}

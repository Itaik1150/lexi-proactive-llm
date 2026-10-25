package com.example.lexiparticipant

import android.annotation.SuppressLint
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.os.Build
import android.os.Bundle
import android.webkit.CookieManager
import android.webkit.JavascriptInterface
import android.webkit.WebChromeClient
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URL

private const val PREFS_NAME         = "lexi_prefs"
private const val KEY_EXPERIMENT_URL = "experiment_url"
private const val KEY_VERSION_CODE   = "version_code"

class MainActivity : ComponentActivity() {

    private val prefs: SharedPreferences by lazy {
        getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
    }

    // Held so onNewIntent can navigate without recreating the composable tree.
    private var activeWebView: WebView? = null

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)

        // "Open Lexi" button on the invitation page: lexi://join/<experimentId>
        val joinId = JoinLink.idFromDeepLink(intent.dataString)
        if (joinId != null) {
            handleJoinLink(joinId)
            return
        }

        val deepLinkUrl = intent.getStringExtra("deepLinkUrl")
        if (!deepLinkUrl.isNullOrEmpty()) {
            // Mark that we opened from notification (for React app to check)
            prefs.edit().putBoolean("openedFromNotification", true).apply()
            android.util.Log.d("Lexi", "onNewIntent: navigating to $deepLinkUrl (from notification)")
            activeWebView?.loadUrl(deepLinkUrl)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            requestPermissions(arrayOf(android.Manifest.permission.POST_NOTIFICATIONS), 1001)
        }

        // If a new APK version was installed, clear the cached experiment URL so
        // match-session runs again and picks up the correct experiment for this build.
        val currentVersion = BuildConfig.VERSION_CODE
        val storedVersion  = prefs.getInt(KEY_VERSION_CODE, -1)
        if (storedVersion != currentVersion) {
            prefs.edit()
                .remove(KEY_EXPERIMENT_URL)
                .putInt(KEY_VERSION_CODE, currentVersion)
                .apply()
        }

        val deepLinkUrl = intent?.getStringExtra("deepLinkUrl")

        // If this launch came from a notification tap, honour the deep link
        // immediately — regardless of whether a savedUrl exists.
        // Also restore the base experiment URL from the deep link so future
        // regular launches (without a notification) still work correctly.
        if (!deepLinkUrl.isNullOrEmpty()) {
            // Mark that we opened from notification (for React app to check)
            prefs.edit().putBoolean("openedFromNotification", true).apply()
            android.util.Log.d("Lexi", "onCreate: Opened from notification with URL: $deepLinkUrl")
            
            // Extract base experiment URL: everything up to and including /e/:id
            // e.g. https://host/e/abc123/c/def456  →  https://host/e/abc123
            val baseUrl = Regex("(https?://[^/]+/e/[a-fA-F0-9]{24})").find(deepLinkUrl)?.groupValues?.get(1)
            if (baseUrl != null) {
                prefs.edit().putString(KEY_EXPERIMENT_URL, baseUrl).apply()
            }
            setContent { MaterialTheme { ChatScreen(url = deepLinkUrl, onWebViewCreated = { activeWebView = it }) } }
            return
        }

        // "Open Lexi" button on the invitation page: lexi://join/<experimentId>
        val joinId = JoinLink.idFromDeepLink(intent?.dataString)
        if (joinId != null) {
            handleJoinLink(joinId)
            return
        }

        val savedUrl = prefs.getString(KEY_EXPERIMENT_URL, null)

        if (savedUrl != null) {
            setContent { MaterialTheme { ChatScreen(url = savedUrl, onWebViewCreated = { activeWebView = it }) } }
        } else {
            // First launch (or after version upgrade with no notification context):
            // try to auto-match this device to a recent APK download session.
            setContent { MaterialTheme { MatchingScreen() } }

            CoroutineScope(Dispatchers.IO).launch {
                val match = tryMatchSession()
                withContext(Dispatchers.Main) {
                    if (match != null) {
                        // A match by network address can be wrong (shared Wi-Fi): always let the participant confirm it.
                        showJoinConfirmation(match.experimentId, match.title)
                    } else {
                        // No automatic match (or an ambiguous one) - fall back to the manual setup screen.
                        showManualSetup()
                    }
                }
            }
        }
    }

    // A join link (lexi://join/<id>) was opened. If it is the experiment this phone is already set up for,
    // just open it; otherwise ask the participant to confirm before switching.
    private fun handleJoinLink(experimentId: String) {
        val savedUrl = prefs.getString(KEY_EXPERIMENT_URL, null)
        if (savedUrl != null && JoinLink.idFromPastedLink(savedUrl) == experimentId) {
            setContent { MaterialTheme { ChatScreen(url = savedUrl, onWebViewCreated = { activeWebView = it }) } }
        } else {
            showJoinConfirmation(experimentId, null)
        }
    }

    // "You are joining <study>" - the choice is stored permanently, so the participant confirms it.
    private fun showJoinConfirmation(experimentId: String, knownTitle: String?) {
        setContent {
            MaterialTheme {
                JoinConfirmScreen(
                    experimentId = experimentId,
                    knownTitle = knownTitle,
                    onConfirm = {
                        // The URL is built from this build's own frontend and the validated id only.
                        val url = JoinLink.experimentUrl(BuildConfig.FRONTEND_BASE_URL, experimentId)
                        prefs.edit().putString(KEY_EXPERIMENT_URL, url).apply()
                        setContent { MaterialTheme { ChatScreen(url = url, onWebViewCreated = { activeWebView = it }) } }
                    },
                    onReject = { showManualSetup() },
                )
            }
        }
    }

    private fun showManualSetup() {
        setContent {
            MaterialTheme {
                SetupScreen(onContinue = { url ->
                    prefs.edit().putString(KEY_EXPERIMENT_URL, url).apply()
                    setContent { MaterialTheme { ChatScreen(url = url, onWebViewCreated = { activeWebView = it }) } }
                })
            }
        }
    }

    // Calls GET /experiments/match-session on the server.
    // Returns the matched experiment (id and title) if the server found one, null otherwise.
    // The server answers "no experiment" both when nothing matches and when the network address is
    // ambiguous (it was used to download for different experiments); either way the participant is asked.
    // Retries once to handle Render's ~40s cold-start on the free tier.
    private fun tryMatchSession(): ExperimentMatch? {
        repeat(2) { attempt ->
            try {
                val url = URL("${BuildConfig.SERVER_URL}/experiments/match-session")
                val conn = url.openConnection() as HttpURLConnection
                conn.requestMethod = "GET"
                // 45s covers Render's worst-case cold start (~40s).
                conn.connectTimeout = 45_000
                conn.readTimeout   = 45_000
                conn.setRequestProperty("Accept", "application/json")

                val code = conn.responseCode
                if (code == 200) {
                    val body = conn.inputStream.bufferedReader().readText()
                    val json = JSONObject(body)
                    val experimentId = json.stringOrNull("experimentId")
                    if (JoinLink.isExperimentId(experimentId)) {
                        return ExperimentMatch(experimentId!!.lowercase(), json.stringOrNull("experimentTitle"))
                    }
                    // Server responded but no match found — don't retry.
                    android.util.Log.w("Lexi", "match-session: no match (attempt ${attempt + 1})")
                    return null
                } else {
                    android.util.Log.w("Lexi", "match-session HTTP $code (attempt ${attempt + 1})")
                }
            } catch (e: Exception) {
                android.util.Log.e("Lexi", "match-session failed (attempt ${attempt + 1}): ${e.message}")
            }
        }
        return null
    }
}

// Shown while the app is trying to auto-detect the experiment.
@Composable
private fun MatchingScreen() {
    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier.fillMaxSize(),
            verticalArrangement = Arrangement.Center,
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            CircularProgressIndicator()
            Spacer(modifier = Modifier.height(20.dp))
            Text(
                text = "Connecting to experiment…",
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(modifier = Modifier.height(8.dp))
            Text(
                text = "This may take up to 30 seconds on first launch.",
                style = MaterialTheme.typography.bodySmall,
            )
        }
    }
}

// Fallback: participant can paste a URL manually.
// Validates that the URL contains a known experiment before accepting it.
@Composable
private fun SetupScreen(onContinue: (String) -> Unit) {
    var input    by remember { mutableStateOf(TextFieldValue("")) }
    var error    by remember { mutableStateOf<String?>(null) }
    var checking by remember { mutableStateOf(false) }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(20.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(text = "Lexi Experiment", style = MaterialTheme.typography.headlineMedium)
            Spacer(modifier = Modifier.height(12.dp))
            Text(
                text = "Could not detect your experiment automatically. Please paste the invitation link you received.",
                style = MaterialTheme.typography.bodyMedium,
            )
            Spacer(modifier = Modifier.height(12.dp))
            OutlinedTextField(
                value = input,
                onValueChange = { input = it; error = null },
                label = { Text("Participant URL") },
                modifier = Modifier.fillMaxWidth(),
                singleLine = true,
                isError = error != null,
            )
            if (error != null) {
                Spacer(modifier = Modifier.height(8.dp))
                Text(text = error!!, color = MaterialTheme.colorScheme.error)
            }
            Spacer(modifier = Modifier.height(16.dp))
            Button(
                onClick = {
                    val url = input.text.trim()
                    if (url.isEmpty()) { error = "Please enter a URL."; return@Button }
                    if (!url.startsWith("http://") && !url.startsWith("https://")) {
                        error = "URL must start with http:// or https://"; return@Button
                    }
                    // Accepts the invitation link (.../join/<id>) or a web app link (.../e/<id>).
                    val experimentId = JoinLink.idFromPastedLink(url)
                    if (experimentId == null) {
                        error = "Invalid link - experiment ID not found in URL."; return@Button
                    }
                    checking = true
                    error = null
                    CoroutineScope(Dispatchers.IO).launch {
                        val result = lookupExperiment(experimentId)
                        withContext(Dispatchers.Main) {
                            checking = false
                            when (result) {
                                is Lookup.Found -> {
                                    // Only the id is taken from what was pasted; the URL is this build's own.
                                    onContinue(JoinLink.experimentUrl(BuildConfig.FRONTEND_BASE_URL, experimentId))
                                }
                                is Lookup.NotFound -> {
                                    error = "Experiment not found. Please check the link."
                                }
                                is Lookup.Unreachable -> {
                                    error = "Could not reach the server. Check your connection and try again."
                                }
                            }
                        }
                    }
                },
                modifier = Modifier.fillMaxWidth(),
                enabled = !checking,
            ) {
                Text(if (checking) "Checking…" else "Continue")
            }
        }
    }
}

// Result of asking the server about an experiment before the participant joins it.
private sealed class Lookup {
    data class Found(val title: String?) : Lookup()
    object NotFound : Lookup()
    object Unreachable : Lookup()
}

// An experiment the server matched to this phone's first launch.
private data class ExperimentMatch(val experimentId: String, val title: String?)

// A string field of a JSON object, or null if it is missing, null or blank.
// (org.json's optString turns a JSON null into the text "null".)
private fun JSONObject.stringOrNull(name: String): String? =
    if (isNull(name)) null else optString(name).ifBlank { null }

// Calls GET /experiments/:id/public: the title and whether the experiment is active, nothing else.
private fun lookupExperiment(experimentId: String): Lookup {
    return try {
        val url  = URL("${BuildConfig.SERVER_URL}/experiments/$experimentId/public")
        val conn = url.openConnection() as HttpURLConnection
        conn.requestMethod  = "GET"
        conn.connectTimeout = 15_000
        conn.readTimeout    = 15_000
        conn.setRequestProperty("Accept", "application/json")
        if (conn.responseCode == 200) {
            val json = JSONObject(conn.inputStream.bufferedReader().readText())
            if (json.optBoolean("isActive", true)) Lookup.Found(json.stringOrNull("title")) else Lookup.NotFound
        } else {
            Lookup.NotFound
        }
    } catch (e: Exception) {
        android.util.Log.e("Lexi", "lookupExperiment failed: ${e.message}")
        Lookup.Unreachable
    }
}

// "You are joining <study>" - shown before the experiment is stored on the phone.
@Composable
private fun JoinConfirmScreen(
    experimentId: String,
    knownTitle: String?,
    onConfirm: () -> Unit,
    onReject: () -> Unit,
) {
    var lookup by remember { mutableStateOf<Lookup?>(if (knownTitle != null) Lookup.Found(knownTitle) else null) }
    var attempt by remember { mutableStateOf(0) }

    LaunchedEffect(experimentId, attempt) {
        if (knownTitle == null) {
            lookup = null
            lookup = withContext(Dispatchers.IO) { lookupExperiment(experimentId) }
        }
    }

    Surface(modifier = Modifier.fillMaxSize()) {
        Column(
            modifier = Modifier
                .fillMaxSize()
                .padding(20.dp),
            verticalArrangement = Arrangement.Center,
        ) {
            Text(text = "Lexi", style = MaterialTheme.typography.headlineMedium)
            Spacer(modifier = Modifier.height(12.dp))

            when (val result = lookup) {
                null -> {
                    Text(text = "Checking your invitation...", style = MaterialTheme.typography.bodyMedium)
                }
                is Lookup.Found -> {
                    Text(text = "You are joining:", style = MaterialTheme.typography.bodyMedium)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(text = result.title ?: "this study", style = MaterialTheme.typography.titleLarge)
                    Spacer(modifier = Modifier.height(8.dp))
                    Text(
                        text = "Please make sure this is the study you were invited to.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = onConfirm, modifier = Modifier.fillMaxWidth()) {
                        Text("Continue")
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(onClick = onReject, modifier = Modifier.fillMaxWidth()) {
                        Text("This is not my study")
                    }
                }
                is Lookup.NotFound -> {
                    Text(
                        text = "This invitation is not valid, or the study is closed.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = onReject, modifier = Modifier.fillMaxWidth()) {
                        Text("Enter my link manually")
                    }
                }
                is Lookup.Unreachable -> {
                    Text(
                        text = "Could not reach the server. Please check your internet connection.",
                        style = MaterialTheme.typography.bodyMedium,
                    )
                    Spacer(modifier = Modifier.height(16.dp))
                    Button(onClick = { attempt += 1 }, modifier = Modifier.fillMaxWidth()) {
                        Text("Try again")
                    }
                    Spacer(modifier = Modifier.height(8.dp))
                    OutlinedButton(onClick = onReject, modifier = Modifier.fillMaxWidth()) {
                        Text("Enter my link manually")
                    }
                }
            }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun ChatScreen(url: String, onWebViewCreated: ((WebView) -> Unit)? = null) {
    Box(modifier = Modifier.fillMaxSize()) {
        AndroidView(
            modifier = Modifier.fillMaxSize(),
            factory = { context ->
                WebView(context).apply {
                    layoutParams = android.view.ViewGroup.LayoutParams(
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                        android.view.ViewGroup.LayoutParams.MATCH_PARENT,
                    )
                    settings.javaScriptEnabled = true
                    settings.domStorageEnabled = true
                    settings.useWideViewPort = true
                    settings.loadWithOverviewMode = true
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                        settings.mixedContentMode =
                            android.webkit.WebSettings.MIXED_CONTENT_COMPATIBILITY_MODE
                    }
                    // The auth cookie is set by the API server (Render domain) while the
                    // page is served from Vercel — a cross-origin (third-party) cookie.
                    // Android 5+ blocks these by default; explicitly allow them so the
                    // session persists across launches.
                    CookieManager.getInstance().setAcceptCookie(true)
                    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP) {
                        CookieManager.getInstance().setAcceptThirdPartyCookies(this, true)
                    }
                    webViewClient = object : WebViewClient() {
                        override fun onReceivedError(
                            view: WebView?,
                            request: android.webkit.WebResourceRequest?,
                            error: android.webkit.WebResourceError?,
                        ) {
                            super.onReceivedError(view, request, error)
                            android.util.Log.e("Lexi", "WebView Error: ${error?.description}")
                        }
                    }
                    webChromeClient = WebChromeClient()
                    addJavascriptInterface(AndroidBridge(context), "Android")
                    android.util.Log.d("Lexi", "Loading URL: $url")
                    loadUrl(url)
                }.also { onWebViewCreated?.invoke(it) }
            },
        )
    }
}

plugins {
    alias(libs.plugins.android.application)
    alias(libs.plugins.kotlin.android)
    alias(libs.plugins.kotlin.compose)

    id("com.google.gms.google-services")

}

android {
    namespace = "com.example.lexiparticipant"
    compileSdk {
        version = release(36)
    }

    defaultConfig {
        applicationId = "com.example.lexiparticipant"
        minSdk = 26
        targetSdk = 36
        versionCode = 5
        versionName = "1.4"

        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"

        // Backend server URL — used for match-session call on first launch.
        buildConfigField("String", "SERVER_URL", "\"https://lexi-server-1rx9.onrender.com\"")
        // Frontend base URL — experiment WebView loads <FRONTEND_BASE_URL>/e/<experimentId>
        buildConfigField("String", "FRONTEND_BASE_URL", "\"https://master-thesis-2026-2027-code-base.vercel.app\"")
        // Notification text on a LOCKED phone. true: only "You have a new message" is shown and the real text
        // appears after unlocking (private by default; emotional messages must not be readable by bystanders).
        // false: the full message is shown on the lock screen. This decides what participants see without
        // unlocking, so set it deliberately for the study.
        buildConfigField("boolean", "HIDE_TEXT_ON_LOCK_SCREEN", "true")
        // LOCAL dev overrides (swap comments as needed):
        // buildConfigField("String", "SERVER_URL", "\"http://192.168.31.200:5000\"")
        // buildConfigField("String", "FRONTEND_BASE_URL", "\"http://192.168.31.200:3000\"")
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_11
        targetCompatibility = JavaVersion.VERSION_11
    }
    kotlinOptions {
        jvmTarget = "11"
    }
    buildFeatures {
        compose = true
        buildConfig = true
    }
}

dependencies {
    implementation(libs.androidx.core.ktx)
    implementation(libs.androidx.lifecycle.runtime.ktx)
    implementation(libs.androidx.activity.compose)
    implementation(platform(libs.androidx.compose.bom))
    implementation(libs.androidx.compose.ui)
    implementation(libs.androidx.compose.ui.graphics)
    implementation(libs.androidx.compose.ui.tooling.preview)
    implementation(libs.androidx.compose.material3)
    testImplementation(libs.junit)
    androidTestImplementation(libs.androidx.junit)
    androidTestImplementation(libs.androidx.espresso.core)
    androidTestImplementation(platform(libs.androidx.compose.bom))
    androidTestImplementation(libs.androidx.compose.ui.test.junit4)
    debugImplementation(libs.androidx.compose.ui.tooling)
    debugImplementation(libs.androidx.compose.ui.test.manifest)

    implementation(platform("com.google.firebase:firebase-bom:33.7.0"))
    implementation("com.google.firebase:firebase-messaging")
    
    // Coroutines for async operations
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.7.3")



}
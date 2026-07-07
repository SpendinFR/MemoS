// MLOmega V19 — E26 — ReflexVision Android library.
//
// The on-device Ultra-Live sensing back-ends (handoff §3.2: NO LLM / NO VLM on
// this path — small specialised calculators only, < 100 ms on the device):
//   * GesturePipeline — MediaPipe Tasks Vision HandLandmarker + GestureRecognizer
//     in LIVE_STREAM mode (pinch → continuous zoom, held open palm → menu,
//     lateral swipe → hide UI).
//   * AsrKwsService — sherpa-onnx VAD + streaming zipformer ASR (FR/EN) +
//     KeywordSpotter (configurable wake word).
//
// Produces an .aar consumed by the Unity XR app (Assets/Plugins/Android) and
// driven from C# via GestureBridge.cs / AsrBridge.cs (AndroidJavaObject). Pure
// library: no Activity, no UI. Same conventions as the E24 `livetransport`
// module (pinned versions, KDoc, JNI-friendly public surface).
//
// Compiled in E46 against Android SDK 34/JDK 17. Hardware execution remains the
// S25/PhoneOnly validation gate (ADR docs/DECISIONS §E26).

plugins {
    id("com.android.library") version "8.5.2"
    id("org.jetbrains.kotlin.android") version "1.9.24"
}

android {
    namespace = "com.mlomega.xr.reflexvision"
    compileSdk = 34

    defaultConfig {
        // MediaPipe Tasks Vision requires API 24+; sherpa-onnx runs on 21+.
        // 26 matches the livetransport floor (stable Camera2/AudioRecord).
        minSdk = 26
        targetSdk = 34

        consumerProguardFiles("consumer-rules.pro")
    }

    buildTypes {
        release {
            isMinifyEnabled = false // the app (Unity) controls final shrinking
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro",
            )
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlinOptions {
        jvmTarget = "17"
    }

    // Unity vendors the .aar; keep it lean and reproducible.
    packaging {
        resources {
            excludes += setOf("META-INF/*.kotlin_module")
        }
    }

    testOptions {
        unitTests {
            // The pure GesturePipeline on-demand tests (E47-B) never touch a real
            // recognizer; stub android.* calls to their type defaults so the pipeline
            // can be exercised on the JVM without a device.
            isReturnDefaultValues = true
        }
    }
}

dependencies {
    // MediaPipe Tasks Vision — HandLandmarker + GestureRecognizer, LIVE_STREAM.
    // Pinned to the last stable release verified on Maven Central (0.10.29,
    // 2025-09). Apache-2.0. The `.task` bundle models are downloaded to app
    // storage (see README), never committed. ADR docs/DECISIONS.md §E26.
    implementation("com.google.mediapipe:tasks-vision:0.10.29")

    // sherpa-onnx Android AAR (JNI) — VAD + streaming zipformer ASR + KeywordSpotter.
    // Apache-2.0. Official release AAR vendored because the old JitPack coordinate
    // is not public (HTTP 401). SHA256:
    // F51F59368674FAEE85B655129C52F9E87BEEF287BF22F35D023BAB83BECAD74C
    // compileOnly is intentional: Android Gradle Plugin refuses to embed a local
    // AAR inside another AAR. exportUnityRelease copies both sibling AARs, so
    // Unity/Gradle packages the native sherpa library exactly once.
    compileOnly(files("libs/sherpa-onnx-1.12.10.aar"))

    // Kotlin coroutines for the audio pump + reconnect-free streaming loop.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    implementation("androidx.annotation:annotation:1.8.0")

    // Pure-JVM unit tests for the gesture state machine / config encoding /
    // frame throttle / on-demand pipeline lifecycle (no device, no native models).
    testImplementation("junit:junit:4.13.2")
    // Mockito supplies a stub android.content.Context for the on-demand pipeline
    // tests (E47-B); the tests never call start(), so the Context is never used.
    testImplementation("org.mockito:mockito-core:5.11.0")
}

tasks.register<Copy>("exportUnityRelease") {
    dependsOn("assembleRelease")
    into(layout.projectDirectory.dir("../../Assets/Plugins/Android"))
    from(layout.buildDirectory.file("outputs/aar/reflexvision-release.aar")) {
        rename { "mlomega-reflexvision.aar" }
    }
    from(layout.projectDirectory.file("libs/sherpa-onnx-1.12.10.aar"))
    from(configurations.named("releaseRuntimeClasspath")) {
        include("*.aar", "*.jar")
    }
}

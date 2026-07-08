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

    // ONNX Runtime Java API for the E48-A offline translation reflex
    // (OfflineTranslator / MarianTokenizer). Apache-2.0. Pinned to 1.17.1 — the
    // SAME ORT version the sherpa AAR bundles as libonnxruntime.so — so the two
    // coexist without a native-version clash (ADR docs/DECISIONS §E48-A risk 1).
    // compileOnly: the AAR only provides the ai.onnxruntime classes at compile
    // time here. exportUnityRelease vendors a STRIPPED copy of this AAR into Unity
    // that keeps the Java API + the unique libonnxruntime4j_jni.so but DROPS its
    // duplicate libonnxruntime.so, so Unity/Gradle packages sherpa's single copy.
    compileOnly("com.microsoft.onnxruntime:onnxruntime-android:1.17.1")

    // Kotlin coroutines for the audio pump + reconnect-free streaming loop.
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")

    implementation("androidx.annotation:annotation:1.8.0")

    // Pure-JVM unit tests for the gesture state machine / config encoding /
    // frame throttle / on-demand pipeline lifecycle (no device, no native models).
    testImplementation("junit:junit:4.13.2")
    // Mockito supplies a stub android.content.Context for the on-demand pipeline
    // tests (E47-B); the tests never call start(), so the Context is never used.
    testImplementation("org.mockito:mockito-core:5.11.0")
    // The Android `org.json` on the unit-test classpath is an unmocked stub; the
    // real implementation lets MarianTokenizer.fromJson run on the JVM (E48-A).
    testImplementation("org.json:json:20240303")
    // ONNX Runtime on the JVM classpath so the opt-in desktop integration test
    // (OfflineTranslatorIntegrationTest) can load the real int8 models when they
    // are present; skipped otherwise. Not shipped by this test dep.
    testImplementation("com.microsoft.onnxruntime:onnxruntime:1.17.1")
}

// E48-A: resolve the onnxruntime-android AAR (compileOnly above is not in any
// runtime classpath, so exportUnityRelease cannot pick it up). A dedicated
// configuration pins exactly the AAR we vendor into Unity.
val onnxruntimeAar: Configuration by configurations.creating {
    isCanBeConsumed = false
    isCanBeResolved = true
}
dependencies { onnxruntimeAar("com.microsoft.onnxruntime:onnxruntime-android:1.17.1@aar") }

// E48-A: produce a STRIPPED onnxruntime AAR that keeps the ai.onnxruntime classes
// + the unique libonnxruntime4j_jni.so but DROPS the duplicate libonnxruntime.so
// (sherpa already ships an identical 1.17.1 copy). Vendoring this into Unity means
// exactly one libonnxruntime.so is packaged — no native collision, no gradle
// template (ADR §E48-A risk 1).
val stripOnnxruntimeAar = tasks.register<Jar>("stripOnnxruntimeAar") {
    archiveFileName.set("onnxruntime-android-1.17.1-noort.aar")
    destinationDirectory.set(layout.buildDirectory.dir("e48a"))
    from(provider { onnxruntimeAar.singleFile.let { zipTree(it) } })
    // Drop every embedded full ORT lib; keep the JNI bridge the Java API needs.
    exclude("jni/**/libonnxruntime.so")
}

tasks.register<Copy>("exportUnityRelease") {
    dependsOn("assembleRelease", stripOnnxruntimeAar)
    into(layout.projectDirectory.dir("../../Assets/Plugins/Android"))
    from(layout.buildDirectory.file("outputs/aar/reflexvision-release.aar")) {
        rename { "mlomega-reflexvision.aar" }
    }
    from(layout.projectDirectory.file("libs/sherpa-onnx-1.12.10.aar"))
    // The de-duplicated onnxruntime AAR (E48-A translation reflex).
    from(stripOnnxruntimeAar.map { it.archiveFile }) {
        rename { "mlomega-onnxruntime.aar" }
    }
    from(configurations.named("releaseRuntimeClasspath")) {
        include("*.aar", "*.jar")
    }
}

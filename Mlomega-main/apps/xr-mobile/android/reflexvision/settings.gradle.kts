// MLOmega V19 — E26 — standalone Gradle library for the reflex vision/audio
// back-ends (MediaPipe gestures + sherpa-onnx ASR/KWS).
//
// Kept self-contained (its own settings) so it can be built in isolation for CI
// or vendored as an .aar into the Unity project (Assets/Plugins/Android). When
// consumed inside a larger Unity/Gradle build, add ":reflexvision" via that
// build's settings.
//
// sherpa-onnx is the official release AAR vendored under libs/ with a pinned
// checksum; no JitPack repository is needed.

pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.PREFER_SETTINGS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "reflexvision"

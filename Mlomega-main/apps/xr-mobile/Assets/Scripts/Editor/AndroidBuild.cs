// MLOmega V19 â€” E46-D
// Reproducible batchmode Android APK build for the PhoneOnly profile.
//
// Runs headless:
//   Unity.exe -batchmode -quit -projectPath <apps/xr-mobile> \
//     -executeMethod MLOmega.XR.Editor.AndroidBuild.BuildApk -logFile -
//
// It (1) points Unity at the external Android toolchain configured by
// scripts/BUILD_ANDROID_PLUGINS.ps1 (JDK 17 + system SDK + NDK r23b) so no
// Hub-embedded module is required, (2) forces the PhoneOnly player settings
// (IL2CPP, ARM64, min/target SDK, the PhoneOnly adapter/define), (3) ensures the
// PhoneOnly scene exists, and (4) writes the APK to build/android/.
//
// Overridable by environment variable:
//   MLOMEGA_ANDROID_SDK   â€” Android SDK root      (default %LOCALAPPDATA%\Android\Sdk)
//   MLOMEGA_ANDROID_NDK   â€” NDK root              (default <sdk>\ndk\23.1.7779620)
//   MLOMEGA_ANDROID_JDK   â€” JDK 17 home           (default Microsoft OpenJDK 17.0.19)
//   MLOMEGA_GRADLE_HOME   â€” Gradle 8.7 home       (default <repo>\.tools\gradle-8.7)
//   MLOMEGA_APK_OUT       â€” APK output path       (default build/android/mlomega-phoneonly.apk)
//   MLOMEGA_PC_HOST       â€” LAN/Tailscale host injected into MLOmegaConfig
//   MLOMEGA_PC_PORT       â€” SessionHub port
using System;
using System.IO;
using MLOmega.XR.Core;
using UnityEditor;
using UnityEditor.Android;
using UnityEditor.Build.Reporting;
using UnityEngine;

namespace MLOmega.XR.Editor
{
    public static class AndroidBuild
    {
        private const string ScenePath = "Assets/Scenes/PhoneOnly.unity";
        private const string ConfigPath = "Assets/Config/MLOmegaPhoneOnly.asset";
        private const string NdkVersion = "23.1.7779620";

        [MenuItem("MLOmega/Build PhoneOnly APK")]
        public static void BuildApk()
        {
            ConfigureExternalTools();
            ConfigurePlayerSettings();
            EnsureScene();
            ApplyEndpointOverride();

            string outPath = Env("MLOMEGA_APK_OUT",
                Path.GetFullPath(Path.Combine("build", "android", "mlomega-phoneonly.apk")));
            Directory.CreateDirectory(Path.GetDirectoryName(outPath));

            var options = new BuildPlayerOptions
            {
                scenes = new[] { ScenePath },
                locationPathName = outPath,
                target = BuildTarget.Android,
                targetGroup = BuildTargetGroup.Android,
                options = BuildOptions.None,
            };

            BuildReport report = BuildPipeline.BuildPlayer(options);
            BuildSummary summary = report.summary;
            if (summary.result != BuildResult.Succeeded)
            {
                throw new Exception(
                    $"[AndroidBuild] APK build failed: {summary.result} " +
                    $"({summary.totalErrors} errors) -> {outPath}");
            }
            Debug.Log($"[AndroidBuild] APK OK: {outPath} ({summary.totalSize} bytes)");
        }

        // --- toolchain -------------------------------------------------------
        private static void ConfigureExternalTools()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string sdk = Env("MLOMEGA_ANDROID_SDK", Path.Combine(localAppData, "Android", "Sdk"));
            string ndk = Env("MLOMEGA_ANDROID_NDK", Path.Combine(sdk, "ndk", NdkVersion));
            string jdk = Env("MLOMEGA_ANDROID_JDK",
                @"C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot");
            string gradle = Env("MLOMEGA_GRADLE_HOME",
                Path.GetFullPath(Path.Combine("..", "..", ".tools", "gradle-8.7")));

            Require(sdk, "Android SDK");
            Require(ndk, "Android NDK r23b");
            Require(jdk, "JDK 17");

            // Tell Unity to use these external tools rather than the (absent)
            // Hub-embedded ones. Both the legacy EditorPrefs keys and the Unity 6
            // AndroidExternalToolsSettings API are set for robustness.
            EditorPrefs.SetBool("SdkUseEmbedded", false);
            EditorPrefs.SetBool("NdkUseEmbedded", false);
            EditorPrefs.SetBool("JdkUseEmbedded", false);
            EditorPrefs.SetBool("GradleUseEmbedded", Directory.Exists(gradle) ? false : true);
            EditorPrefs.SetString("AndroidSdkRoot", sdk);
            EditorPrefs.SetString("AndroidNdkRootR23", ndk);
            EditorPrefs.SetString("AndroidNdkRoot", ndk);
            EditorPrefs.SetString("JdkPath", jdk);
            if (Directory.Exists(gradle)) EditorPrefs.SetString("GradlePath", gradle);

#if UNITY_2022_2_OR_NEWER
            AndroidExternalToolsSettings.sdkRootPath = sdk;
            AndroidExternalToolsSettings.ndkRootPath = ndk;
            AndroidExternalToolsSettings.jdkRootPath = jdk;
            if (Directory.Exists(gradle)) AndroidExternalToolsSettings.gradlePath = gradle;
#endif
            Debug.Log($"[AndroidBuild] SDK={sdk} NDK={ndk} JDK={jdk} Gradle={gradle}");
        }

        // --- player settings -------------------------------------------------
        private static void ConfigurePlayerSettings()
        {
            EditorUserBuildSettings.SwitchActiveBuildTarget(BuildTargetGroup.Android, BuildTarget.Android);

            PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel34;

            if (string.IsNullOrEmpty(PlayerSettings.applicationIdentifier) ||
                PlayerSettings.applicationIdentifier.Contains("DefaultCompany"))
            {
                PlayerSettings.SetApplicationIdentifier(
                    BuildTargetGroup.Android, "com.mlomega.xr.phoneonly");
            }

            // PhoneOnly profile: no XREAL SDK. The proprietary tarball define stays
            // absent so the guarded adapters compile without it.
            string defines = PlayerSettings.GetScriptingDefineSymbolsForGroup(BuildTargetGroup.Android);
            if (!defines.Contains("MLOMEGA_PHONE_ONLY"))
            {
                defines = string.IsNullOrEmpty(defines)
                    ? "MLOMEGA_PHONE_ONLY"
                    : defines + ";MLOMEGA_PHONE_ONLY";
                PlayerSettings.SetScriptingDefineSymbolsForGroup(BuildTargetGroup.Android, defines);
            }
        }

        private static void EnsureScene()
        {
            if (File.Exists(ScenePath)) return;
            // Delegate to the canonical scene builder so the scene contents match.
            PhoneOnlySceneBuilder.BuildScene();
            if (!File.Exists(ScenePath))
                throw new Exception($"[AndroidBuild] PhoneOnly scene missing after build: {ScenePath}");
        }

        // --- endpoint injection ---------------------------------------------
        private static void ApplyEndpointOverride()
        {
            string host = Environment.GetEnvironmentVariable("MLOMEGA_PC_HOST");
            string port = Environment.GetEnvironmentVariable("MLOMEGA_PC_PORT");
            if (string.IsNullOrEmpty(host) && string.IsNullOrEmpty(port)) return;

            var config = AssetDatabase.LoadAssetAtPath<MLOmegaConfig>(ConfigPath);
            if (config == null) return;
            var so = new SerializedObject(config);
            if (!string.IsNullOrEmpty(host)) so.FindProperty("_pcHost").stringValue = host;
            if (!string.IsNullOrEmpty(port) && int.TryParse(port, out int p))
                so.FindProperty("_sessionHubPort").intValue = p;
            so.ApplyModifiedPropertiesWithoutUndo();
            EditorUtility.SetDirty(config);
            AssetDatabase.SaveAssets();
            Debug.Log($"[AndroidBuild] Endpoint override host={host} port={port}");
        }

        // --- helpers ---------------------------------------------------------
        private static string Env(string key, string fallback)
        {
            string v = Environment.GetEnvironmentVariable(key);
            return string.IsNullOrEmpty(v) ? fallback : v;
        }

        private static void Require(string path, string what)
        {
            if (!Directory.Exists(path))
                throw new Exception($"[AndroidBuild] {what} not found at: {path}");
        }
    }
}

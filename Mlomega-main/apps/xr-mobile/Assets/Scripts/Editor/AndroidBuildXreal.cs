// MLOmega V19 — E49 / Gate G1
// Reproducible batchmode Android APK build for the XREAL glasses profile.
//
// Runs headless:
//   Unity.exe -batchmode -quit -projectPath <apps/xr-mobile> \
//     -executeMethod MLOmega.XR.Editor.AndroidBuildXreal.BuildApk -logFile -
//
// Differences from the PhoneOnly build (AndroidBuild.cs):
//   * enables the XREAL_SDK_PRESENT define (activates the real XrealDeviceAdapter),
//     NOT MLOMEGA_PHONE_ONLY;
//   * injects the com.xreal.xr file: dependency into Packages/manifest.json at build
//     time (the proprietary tarball lives under Packages/xreal-sdk/, git-ignored — so
//     the committed manifest stays XREAL-free and a PhoneOnly clone without the SDK
//     keeps building);
//   * activates the XREAL XR loader for Android (XR Plug-in Management);
//   * builds the full product scene with XrealDeviceAdapter. G1Gate remains a
//     separate hardware diagnostic scene, never the shipped product APK.
//
// PrepareDefines is a separate entry point so a first pass can set the define + import
// the SDK before the compile that exercises the real adapter path.
using System;
using System.IO;
using System.Text.RegularExpressions;
using UnityEditor;
using UnityEditor.Android;
using UnityEditor.Build.Reporting;
using UnityEngine;
using UnityEngine.Rendering;

namespace MLOmega.XR.Editor
{
    public static class AndroidBuildXreal
    {
        private const string ScenePath = PhoneOnlySceneBuilder.XrealScenePath;
        private const string ManifestPath = "Packages/manifest.json";
        private const string TarballRel = "Packages/xreal-sdk/com.xreal.xr.tar.gz";
        private const string XrealDep = "\"com.xreal.xr\": \"file:xreal-sdk/com.xreal.xr.tar.gz\"";
        private const string XrealLoader = "Unity.XR.XREAL.XREALXRLoader";
        private const string NdkVersion = "23.1.7779620";
        private const string AndroidManifestPath = "Assets/Plugins/Android/AndroidManifest.xml";

        // Pass 1: ensure the SDK is referenced + the define is on, so the next compile
        // exercises the real XrealDeviceAdapter path. Safe to run repeatedly.
        [MenuItem("MLOmega/XREAL/1. Prepare (SDK + define)")]
        public static void PrepareDefines()
        {
            EnsureXrealPackage();
            SetDefine();
            AssetDatabase.Refresh();
            Debug.Log("[AndroidBuildXreal] Prepared: XREAL package referenced + XREAL_SDK_PRESENT set. " +
                      "Re-open/rebuild to compile the real adapter path.");
        }

        [MenuItem("MLOmega/XREAL/2. Build Glasses APK (G1)")]
        public static void BuildApk()
        {
            EnsureXrealPackage();
            SetDefine();
            ConfigureExternalTools();
            using (var xrealSettings = new XrealBuildSettingsScope())
            {
                ConfigurePlayerSettings();
                EnableXrealLoader();
                EnsureScene();
                AndroidBuild.EmbedSmallDeviceModels();
                AndroidBuild.ApplyEndpointOverride(PhoneOnlySceneBuilder.XrealConfigPath);
                ValidateXrealBuildSettings();

                string outPath = Env("MLOMEGA_APK_OUT",
                    Path.GetFullPath(Path.Combine("build", "android", "mlomega-xreal.apk")));
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
                        $"[AndroidBuildXreal] Glasses APK build failed: {summary.result} " +
                        $"({summary.totalErrors} errors) -> {outPath}");
                }
                Debug.Log($"[AndroidBuildXreal] Glasses PRODUCT APK OK: {outPath} ({summary.totalSize} bytes)");
            }
        }

        // --- SDK package injection (keeps the committed manifest XREAL-free) -------
        private static void EnsureXrealPackage()
        {
            if (!File.Exists(TarballRel))
            {
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL SDK tarball missing: {TarballRel}. " +
                    "Download SDK 3.1.0 from your XREAL developer account and place it there.");
            }
            string manifest = File.ReadAllText(ManifestPath);
            if (manifest.Contains("com.xreal.xr"))
            {
                return;
            }
            // Insert the dependency as the last entry of the "dependencies" object.
            int deps = manifest.IndexOf("\"dependencies\"", StringComparison.Ordinal);
            int brace = manifest.IndexOf('{', deps);
            // Find the matching closing brace of the dependencies object.
            int depth = 0, close = -1;
            for (int i = brace; i < manifest.Length; i++)
            {
                if (manifest[i] == '{') depth++;
                else if (manifest[i] == '}') { depth--; if (depth == 0) { close = i; break; } }
            }
            if (close < 0) throw new Exception("[AndroidBuildXreal] manifest.json: dependencies block not found.");
            // last existing entry gets a trailing comma; insert before the close brace.
            string head = manifest.Substring(0, close).TrimEnd();
            string tail = manifest.Substring(close);
            string sep = head.EndsWith(",") ? "" : ",";
            manifest = head + sep + "\n    " + XrealDep + "\n  " + tail;
            File.WriteAllText(ManifestPath, manifest);
            Debug.Log("[AndroidBuildXreal] Injected com.xreal.xr into manifest.json (local build only).");
        }

        private static void SetDefine()
        {
            foreach (var group in new[] { BuildTargetGroup.Android, BuildTargetGroup.Standalone })
            {
                string d = PlayerSettings.GetScriptingDefineSymbolsForGroup(group);
                if (!d.Contains("XREAL_SDK_PRESENT"))
                {
                    d = string.IsNullOrEmpty(d) ? "XREAL_SDK_PRESENT" : d + ";XREAL_SDK_PRESENT";
                }
                // The glasses build is NOT PhoneOnly — drop that define if present.
                d = d.Replace(";MLOMEGA_PHONE_ONLY", "").Replace("MLOMEGA_PHONE_ONLY;", "").Replace("MLOMEGA_PHONE_ONLY", "");
                PlayerSettings.SetScriptingDefineSymbolsForGroup(group, d);
            }
        }

        // --- XR Plug-in Management: enable the XREAL loader for Android ------------
        private static void EnableXrealLoader()
        {
            try
            {
                var settings = UnityEngine.XR.Management.XRGeneralSettings.Instance;
                var buildSettings = GetOrCreateAndroidBuildSettings();
                if (buildSettings == null)
                {
                    Debug.LogWarning("[AndroidBuildXreal] XR settings for Android not available; " +
                        "enable XREAL in Edit > Project Settings > XR Plug-in Management (Android) once, then rebuild.");
                    return;
                }
                var manager = buildSettings.Manager;
                bool ok = UnityEditor.XR.Management.Metadata.XRPackageMetadataStore.AssignLoader(
                    manager, XrealLoader, BuildTargetGroup.Android);
                Debug.Log(ok
                    ? "[AndroidBuildXreal] XREAL XR loader assigned for Android."
                    : "[AndroidBuildXreal] XREAL loader assignment returned false — enable it once via the XR Plug-in Management GUI.");
            }
            catch (Exception ex)
            {
                Debug.LogWarning("[AndroidBuildXreal] Could not enable the XREAL loader programmatically " +
                    $"({ex.Message}). Enable XREAL in Edit > Project Settings > XR Plug-in Management (Android) once, then rebuild.");
            }
        }

        private static UnityEngine.XR.Management.XRGeneralSettings GetOrCreateAndroidBuildSettings()
        {
            UnityEditor.EditorBuildSettings.TryGetConfigObject(
                UnityEngine.XR.Management.XRGeneralSettings.k_SettingsKey,
                out UnityEditor.XR.Management.XRGeneralSettingsPerBuildTarget perBuildTarget);
            if (perBuildTarget == null)
            {
                perBuildTarget = ScriptableObject.CreateInstance<UnityEditor.XR.Management.XRGeneralSettingsPerBuildTarget>();
                const string dir = "Assets/XR";
                Directory.CreateDirectory(dir);
                AssetDatabase.CreateAsset(perBuildTarget, dir + "/XRGeneralSettingsPerBuildTarget.asset");
                UnityEditor.EditorBuildSettings.AddConfigObject(
                    UnityEngine.XR.Management.XRGeneralSettings.k_SettingsKey, perBuildTarget, true);
            }
            if (!perBuildTarget.HasManagerSettingsForBuildTarget(BuildTargetGroup.Android))
            {
                perBuildTarget.CreateDefaultManagerSettingsForBuildTarget(BuildTargetGroup.Android);
            }
            return perBuildTarget.SettingsForBuildTarget(BuildTargetGroup.Android);
        }

        // --- toolchain (mirrors AndroidBuild) -------------------------------------
        private static void ConfigureExternalTools()
        {
            string localAppData = Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData);
            string sdk = Env("MLOMEGA_ANDROID_SDK", Path.Combine(localAppData, "Android", "Sdk"));
            string ndk = Env("MLOMEGA_ANDROID_NDK", Path.Combine(sdk, "ndk", NdkVersion));
            string jdk = Env("MLOMEGA_ANDROID_JDK", @"C:\Program Files\Microsoft\jdk-17.0.19.10-hotspot");
            string gradle = Env("MLOMEGA_GRADLE_HOME", Path.GetFullPath(Path.Combine("..", "..", ".tools", "gradle-8.7")));
            EditorPrefs.SetBool("SdkUseEmbedded", false);
            EditorPrefs.SetBool("NdkUseEmbedded", false);
            EditorPrefs.SetBool("JdkUseEmbedded", false);
            EditorPrefs.SetString("AndroidSdkRoot", sdk);
            EditorPrefs.SetString("AndroidNdkRootR23", ndk);
            EditorPrefs.SetString("AndroidNdkRoot", ndk);
            EditorPrefs.SetString("JdkPath", jdk);
            if (Directory.Exists(gradle)) { EditorPrefs.SetBool("GradleUseEmbedded", false); EditorPrefs.SetString("GradlePath", gradle); }
#if UNITY_2022_2_OR_NEWER
            AndroidExternalToolsSettings.sdkRootPath = sdk;
            AndroidExternalToolsSettings.ndkRootPath = ndk;
            AndroidExternalToolsSettings.jdkRootPath = jdk;
            if (Directory.Exists(gradle)) AndroidExternalToolsSettings.gradlePath = gradle;
#endif
            Debug.Log($"[AndroidBuildXreal] SDK={sdk} NDK={ndk} JDK={jdk} Gradle={gradle}");
        }

        private static void ConfigurePlayerSettings()
        {
            PlayerSettings.SetScriptingBackend(BuildTargetGroup.Android, ScriptingImplementation.IL2CPP);
            PlayerSettings.Android.targetArchitectures = AndroidArchitecture.ARM64;
            PlayerSettings.Android.minSdkVersion = AndroidSdkVersions.AndroidApiLevel29;
            PlayerSettings.Android.targetSdkVersion = AndroidSdkVersions.AndroidApiLevel34;
            PlayerSettings.runInBackground = true;
            PlayerSettings.productName = "MLOmega XREAL";
            PlayerSettings.SetApplicationIdentifier(BuildTargetGroup.Android, "com.mlomega.xr.glasses");
        }

        private static void ValidateXrealBuildSettings()
        {
            GraphicsDeviceType[] graphics =
                PlayerSettings.GetGraphicsAPIs(BuildTarget.Android);
            if (PlayerSettings.GetUseDefaultGraphicsAPIs(BuildTarget.Android) ||
                graphics == null ||
                graphics.Length != 1 ||
                graphics[0] != GraphicsDeviceType.OpenGLES3)
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREAL build requires OpenGLES3 only.");
            }
            if (PlayerSettings.defaultInterfaceOrientation != UIOrientation.Portrait)
                throw new Exception(
                    "[AndroidBuildXreal] XREAL build requires Portrait orientation.");
            if (QualitySettings.vSyncCount != 0)
                throw new Exception(
                    "[AndroidBuildXreal] XREAL build requires VSync Don't Sync.");
            if (!File.ReadAllText(AndroidManifestPath)
                    .Contains("android:screenOrientation=\"portrait\""))
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREAL manifest orientation was not isolated to portrait.");
            }
            if (File.ReadAllText(AndroidManifestPath)
                    .Contains("com.mlomega.xrg1gate.EyeCaptureService"))
            {
                throw new Exception(
                    "[AndroidBuildXreal] Stale EyeCaptureService leaked into XREAL manifest.");
            }
            if (AssetDatabase.LoadAssetAtPath<Shader>(
                    PhoneOnlySceneBuilder.XrealYuvShaderPath) == null)
            {
                throw new Exception("[AndroidBuildXreal] XREAL YUV shader asset missing.");
            }
        }

        private static void EnsureScene()
        {
            PhoneOnlySceneBuilder.BuildXrealScene();
            if (!File.Exists(ScenePath))
                throw new Exception($"[AndroidBuildXreal] XREAL product scene missing after build: {ScenePath}");
        }

        /// <summary>
        /// Applies XREAL's documented Android graphics/orientation/VSync settings
        /// only while the glasses player is built. Dispose restores the exact
        /// PhoneOnly project state, including on build failure.
        /// </summary>
        private sealed class XrealBuildSettingsScope : IDisposable
        {
            private readonly bool _automaticGraphics;
            private readonly GraphicsDeviceType[] _graphics;
            private readonly UIOrientation _orientation;
            private readonly string _productName;
            private readonly string _applicationIdentifier;
            private readonly ScriptingImplementation _scriptingBackend;
            private readonly AndroidArchitecture _targetArchitectures;
            private readonly AndroidSdkVersions _minSdkVersion;
            private readonly AndroidSdkVersions _targetSdkVersion;
            private readonly bool _runInBackground;
            private readonly int _activeQuality;
            private readonly int[] _vSync;
            private readonly string _manifest;
            private bool _disposed;

            public XrealBuildSettingsScope()
            {
                _automaticGraphics =
                    PlayerSettings.GetUseDefaultGraphicsAPIs(BuildTarget.Android);
                _graphics = PlayerSettings.GetGraphicsAPIs(BuildTarget.Android);
                _orientation = PlayerSettings.defaultInterfaceOrientation;
                _productName = PlayerSettings.productName;
                _applicationIdentifier =
                    PlayerSettings.GetApplicationIdentifier(BuildTargetGroup.Android);
                _scriptingBackend =
                    PlayerSettings.GetScriptingBackend(BuildTargetGroup.Android);
                _targetArchitectures = PlayerSettings.Android.targetArchitectures;
                _minSdkVersion = PlayerSettings.Android.minSdkVersion;
                _targetSdkVersion = PlayerSettings.Android.targetSdkVersion;
                _runInBackground = PlayerSettings.runInBackground;
                _activeQuality = QualitySettings.GetQualityLevel();
                _vSync = new int[QualitySettings.names.Length];
                for (int i = 0; i < _vSync.Length; i++)
                {
                    QualitySettings.SetQualityLevel(i, false);
                    _vSync[i] = QualitySettings.vSyncCount;
                    QualitySettings.vSyncCount = 0;
                }
                QualitySettings.SetQualityLevel(_activeQuality, false);

                _manifest = File.ReadAllText(AndroidManifestPath);
                string xrealManifest = _manifest.Replace(
                    "android:screenOrientation=\"landscape\"",
                    "android:screenOrientation=\"portrait\"");
                if (xrealManifest == _manifest)
                    throw new Exception(
                        "[AndroidBuildXreal] Expected landscape orientation marker missing.");
                xrealManifest = Regex.Replace(
                    xrealManifest,
                    @"\s*<!-- Foreground service used by the Eye capture path \(media projection class\)\. -->\s*" +
                    @"<service\s+android:name=""com\.mlomega\.xrg1gate\.EyeCaptureService""[\s\S]*?/>\s*",
                    Environment.NewLine,
                    RegexOptions.CultureInvariant);
                File.WriteAllText(AndroidManifestPath, xrealManifest);

                PlayerSettings.SetUseDefaultGraphicsAPIs(BuildTarget.Android, false);
                PlayerSettings.SetGraphicsAPIs(
                    BuildTarget.Android,
                    new[] { GraphicsDeviceType.OpenGLES3 });
                PlayerSettings.defaultInterfaceOrientation = UIOrientation.Portrait;
                AssetDatabase.SaveAssets();
            }

            public void Dispose()
            {
                if (_disposed) return;
                _disposed = true;
                try
                {
                    PlayerSettings.SetUseDefaultGraphicsAPIs(
                        BuildTarget.Android, _automaticGraphics);
                    if (_graphics != null && _graphics.Length > 0)
                        PlayerSettings.SetGraphicsAPIs(BuildTarget.Android, _graphics);
                    PlayerSettings.defaultInterfaceOrientation = _orientation;
                    PlayerSettings.productName = _productName;
                    PlayerSettings.SetApplicationIdentifier(
                        BuildTargetGroup.Android, _applicationIdentifier);
                    PlayerSettings.SetScriptingBackend(
                        BuildTargetGroup.Android, _scriptingBackend);
                    PlayerSettings.Android.targetArchitectures = _targetArchitectures;
                    PlayerSettings.Android.minSdkVersion = _minSdkVersion;
                    PlayerSettings.Android.targetSdkVersion = _targetSdkVersion;
                    PlayerSettings.runInBackground = _runInBackground;
                    for (int i = 0; i < _vSync.Length; i++)
                    {
                        QualitySettings.SetQualityLevel(i, false);
                        QualitySettings.vSyncCount = _vSync[i];
                    }
                    QualitySettings.SetQualityLevel(_activeQuality, false);
                    File.WriteAllText(AndroidManifestPath, _manifest);
                    AssetDatabase.SaveAssets();
                }
                catch (Exception ex)
                {
                    Debug.LogError(
                        $"[AndroidBuildXreal] Failed to restore PhoneOnly settings: {ex}");
                    throw;
                }
            }
        }

        private static string Env(string key, string fallback)
        {
            string v = Environment.GetEnvironmentVariable(key);
            return string.IsNullOrEmpty(v) ? fallback : v;
        }
    }
}

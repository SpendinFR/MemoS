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
using System.Collections;
using System.IO;
using System.Reflection;
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
        private const string ArFoundationDep =
            "\"com.unity.xr.arfoundation\": \"6.0.6\"";
        private const string XrHandsDep =
            "\"com.unity.xr.hands\": \"1.5.0\"";
        private const string XrInteractionDep =
            "\"com.unity.xr.interaction.toolkit\": \"3.0.9\"";
        private const string XrealLoader = "Unity.XR.XREAL.XREALXRLoader";
        private const string XrealSettingsType = "Unity.XR.XREAL.XREALSettings";
        private const string XrealSettingsKey = "com.unity.xr.management.xrealsettings";
        private const string XrealSettingsAssetPath = "Assets/XR/Settings/XREALSettings.asset";
        private const string NdkVersion = "23.1.7779620";
        private const string AndroidManifestPath = "Assets/Plugins/Android/AndroidManifest.xml";

        // Pass 1: ensure the SDK is referenced + the define is on, so the next compile
        // exercises the real XrealDeviceAdapter path. Safe to run repeatedly.
        [MenuItem("MLOmega/XREAL/1. Prepare (SDK + define)")]
        public static void PrepareDefines()
        {
            EnsureXrealPackage();
            // XREAL 3.1 implements its own planes/depth mesh/anchors through
            // AR Foundation. This package is injected only by the glasses build;
            // the committed manifest and PhoneOnly build remain dependency-free.
            EnsureArFoundationPackage();
            EnsurePackageDependency(XrHandsDep, "com.unity.xr.hands");
            EnsurePackageDependency(
                XrInteractionDep, "com.unity.xr.interaction.toolkit");
            SetDefine();
            AssetDatabase.Refresh();
            Debug.Log("[AndroidBuildXreal] Prepared: XREAL package referenced + XREAL_SDK_PRESENT set. " +
                      "Re-open/rebuild to compile the real adapter path.");
        }

        [MenuItem("MLOmega/XREAL/2. Build Glasses APK (G1)")]
        public static void BuildApk()
        {
            EnsureXrealPackage();
            EnsureArFoundationPackage();
            EnsurePackageDependency(XrHandsDep, "com.unity.xr.hands");
            EnsurePackageDependency(
                XrInteractionDep, "com.unity.xr.interaction.toolkit");
            SetDefine();
            ConfigureExternalTools();
            using (var xrealSettings = new XrealBuildSettingsScope())
            {
                ConfigurePlayerSettings();
                ConfigureXrealSdkSettings();
                EnableXrealLoader();
                ValidateArFoundationLoaded();
                EnsureScene();
                string buildScene = ScenePath;
                if (IsProviderGate())
                {
                    AugmentedRealityGateSceneBuilder.BuildXrealProviderGateScene();
                    buildScene = AugmentedRealityGateSceneBuilder.GateScenePath;
                }
                AndroidBuild.EmbedSmallDeviceModels();
                AndroidBuild.ApplyEndpointOverride(PhoneOnlySceneBuilder.XrealConfigPath);
                ValidateXrealBuildSettings();

                string defaultName = IsProviderGate()
                    ? "mlomega-xreal-provider-gate.apk"
                    : "mlomega-xreal.apk";
                string outPath = Env("MLOMEGA_APK_OUT",
                    Path.GetFullPath(Path.Combine("build", "android", defaultName)));
                Directory.CreateDirectory(Path.GetDirectoryName(outPath));

                var options = new BuildPlayerOptions
                {
                    scenes = new[] { buildScene },
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
                string profile = IsProviderGate()
                    ? "isolated AR provider gate"
                    : "Glasses PRODUCT";
                Debug.Log($"[AndroidBuildXreal] {profile} APK OK: {outPath} ({summary.totalSize} bytes)");
            }
        }

        [MenuItem("MLOmega/XREAL/3. Build World Atelier APK")]
        public static void BuildCreatorApk()
        {
            EnsureXrealPackage();
            EnsureArFoundationPackage();
            EnsurePackageDependency(XrHandsDep, "com.unity.xr.hands");
            EnsurePackageDependency(
                XrInteractionDep, "com.unity.xr.interaction.toolkit");
            SetDefine();
            ConfigureExternalTools();
            using (var xrealSettings = new XrealBuildSettingsScope())
            {
                ConfigurePlayerSettings();
                PlayerSettings.productName = "MLOmega World Atelier";
                PlayerSettings.SetApplicationIdentifier(
                    BuildTargetGroup.Android,
                    "com.mlomega.xr.worldatelier");
                ConfigureXrealSdkSettings();
                EnableXrealLoader();
                ValidateArFoundationLoaded();
                WorldCreatorSceneBuilder.BuildScene();
                ValidateXrealBuildSettings();
                if (!File.Exists(WorldCreatorSceneBuilder.ScenePath))
                    throw new Exception(
                        "[AndroidBuildXreal] World Atelier scene missing.");

                string outPath = Env(
                    "MLOMEGA_CREATOR_APK_OUT",
                    Path.GetFullPath(Path.Combine(
                        "build",
                        "android",
                        "mlomega-xreal-world-atelier.apk")));
                Directory.CreateDirectory(Path.GetDirectoryName(outPath));
                BuildReport report = BuildPipeline.BuildPlayer(
                    new BuildPlayerOptions
                    {
                        scenes = new[] { WorldCreatorSceneBuilder.ScenePath },
                        locationPathName = outPath,
                        target = BuildTarget.Android,
                        targetGroup = BuildTargetGroup.Android,
                        options = BuildOptions.None,
                    });
                BuildSummary summary = report.summary;
                if (summary.result != BuildResult.Succeeded)
                    throw new Exception(
                        "[AndroidBuildXreal] World Atelier APK failed: " +
                        summary.result + " (" + summary.totalErrors +
                        " errors) -> " + outPath);
                Debug.Log(
                    "[AndroidBuildXreal] World Atelier APK OK: " +
                    outPath + " (" + summary.totalSize + " bytes)");
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

        private static void EnsureArFoundationPackage()
            => EnsurePackageDependency(ArFoundationDep, "com.unity.xr.arfoundation");

        private static void EnsurePackageDependency(
            string dependency,
            string packageName)
        {
            string manifest = File.ReadAllText(ManifestPath);
            if (manifest.Contains("\"" + packageName + "\""))
                return;
            int deps = manifest.IndexOf("\"dependencies\"", StringComparison.Ordinal);
            int brace = manifest.IndexOf('{', deps);
            int depth = 0, close = -1;
            for (int i = brace; i < manifest.Length; i++)
            {
                if (manifest[i] == '{') depth++;
                else if (manifest[i] == '}')
                {
                    depth--;
                    if (depth == 0)
                    {
                        close = i;
                        break;
                    }
                }
            }
            if (close < 0)
                throw new Exception(
                    "[AndroidBuildXreal] manifest.json dependencies block not found.");
            string head = manifest.Substring(0, close).TrimEnd();
            string tail = manifest.Substring(close);
            string separator = head.EndsWith(",") ? string.Empty : ",";
            File.WriteAllText(
                ManifestPath,
                head + separator + "\n    " + dependency + "\n  " + tail);
            Debug.Log(
                "[AndroidBuildXreal] XREAL-only dependency injected: " +
                packageName);
        }

        private static void ValidateArFoundationLoaded()
        {
            bool arFoundation = false;
            bool xrHands = false;
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                if (assembly.GetType(
                        "UnityEngine.XR.ARFoundation.ARSession",
                        false) != null)
                    arFoundation = true;
                if (assembly.GetType(
                        "UnityEngine.XR.Hands.XRHandSubsystem",
                        false) != null)
                    xrHands = true;
            }
            if (!arFoundation || !xrHands)
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREAL spatial product dependencies are " +
                    $"not loaded (ARFoundation={arFoundation}, XRHands={xrHands}). " +
                    "Run PrepareDefines as a separate first pass.");
            }
        }

        private static bool IsProviderGate() =>
            string.Equals(
                Environment.GetEnvironmentVariable("MLOMEGA_XREAL_PROVIDER_GATE"),
                "1",
                StringComparison.Ordinal);

        private static void SetDefine()
        {
            foreach (var group in new[] { BuildTargetGroup.Android, BuildTargetGroup.Standalone })
            {
                string d = PlayerSettings.GetScriptingDefineSymbolsForGroup(group);
                foreach (string define in new[] { "XREAL_SDK_PRESENT", "XR_HANDS" })
                {
                    if (!d.Contains(define))
                        d = string.IsNullOrEmpty(d) ? define : d + ";" + define;
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

        /// <summary>
        /// XRPackageMetadataStore may create the XREAL settings asset without
        /// registering it as an EditorBuildSettings config object in batchmode.
        /// The SDK's own build processor then dereferences null but Unity still
        /// emits a superficially successful APK. Configure and register the exact
        /// SDK 3.1 settings explicitly so its official build/manifest callbacks run.
        /// Reflection keeps a clean PhoneOnly checkout compilable without the
        /// proprietary XREAL package installed.
        /// </summary>
        private static void ConfigureXrealSdkSettings()
        {
            Type settingsType = FindLoadedType(XrealSettingsType);
            if (settingsType == null || !typeof(ScriptableObject).IsAssignableFrom(settingsType))
            {
                throw new Exception(
                    $"[AndroidBuildXreal] SDK type '{XrealSettingsType}' is unavailable. " +
                    "Run PrepareDefines, let Unity import com.xreal.xr 3.1.0, then run the build pass.");
            }

            Directory.CreateDirectory(Path.GetDirectoryName(XrealSettingsAssetPath));
            var settings = AssetDatabase.LoadAssetAtPath(
                XrealSettingsAssetPath, settingsType) as ScriptableObject;
            if (settings == null)
            {
                settings = ScriptableObject.CreateInstance(settingsType);
                settings.name = "XREALSettings";
                AssetDatabase.CreateAsset(settings, XrealSettingsAssetPath);
            }

            SetEnumField(settings, "StereoRendering", "SinglePassInstanced");
            SetEnumField(settings, "InitialTrackingType", "MODE_6DOF");
            // Product spatial tools (ballistic guide and direct manipulation)
            // consume XREAL's real XR Hands joints. Eye/MediaPipe remains the
            // fallback gesture path used by PhoneOnly and legacy commands.
            SetEnumField(settings, "InitialInputSource", "Hands");
            SetBoolField(settings, "SupportMultiResume", true);
            SetBoolField(settings, "EnableNativeSessionManager", false);
            SetBoolField(
                settings,
                "EnableAutoLogcat",
                !string.Equals(
                    Env("MLOMEGA_XREAL_AUTO_LOGCAT", "1"),
                    "0",
                    StringComparison.OrdinalIgnoreCase));
            SetEnumListField(
                settings,
                "SupportDevices",
                "XREAL_DEVICE_CATEGORY_REALITY",
                "XREAL_DEVICE_CATEGORY_VISION");
            AssignXrealVirtualController(settings);

            EditorUtility.SetDirty(settings);
            AssetDatabase.SaveAssets();
            EditorBuildSettings.AddConfigObject(XrealSettingsKey, settings, true);
            if (!EditorBuildSettings.TryGetConfigObject(
                    XrealSettingsKey, out ScriptableObject registered) ||
                registered == null)
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREALSettings registration did not persist.");
            }
            Debug.Log(
                "[AndroidBuildXreal] XREAL SDK settings registered: " +
                "SinglePassInstanced, MODE_6DOF, Hands, MultiResume, " +
                $"AutoLogcat={GetFieldValue(settings, "EnableAutoLogcat")}.");
        }

        private static Type FindLoadedType(string fullName)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type type = assembly.GetType(fullName, false);
                if (type != null) return type;
            }
            return null;
        }

        private static FieldInfo RequireField(ScriptableObject target, string fieldName)
        {
            FieldInfo field = target.GetType().GetField(
                fieldName, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            if (field == null)
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL SDK field missing: {fieldName}.");
            return field;
        }

        private static object GetFieldValue(ScriptableObject target, string fieldName) =>
            RequireField(target, fieldName).GetValue(target);

        private static void SetBoolField(
            ScriptableObject target,
            string fieldName,
            bool value)
        {
            FieldInfo field = RequireField(target, fieldName);
            if (field.FieldType != typeof(bool))
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL field {fieldName} is not Boolean.");
            field.SetValue(target, value);
        }

        private static void SetEnumField(
            ScriptableObject target,
            string fieldName,
            string valueName)
        {
            FieldInfo field = RequireField(target, fieldName);
            if (!field.FieldType.IsEnum)
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL field {fieldName} is not an enum.");
            field.SetValue(target, Enum.Parse(field.FieldType, valueName));
        }

        private static void SetEnumListField(
            ScriptableObject target,
            string fieldName,
            params string[] valueNames)
        {
            FieldInfo field = RequireField(target, fieldName);
            if (!(field.GetValue(target) is IList list) ||
                !field.FieldType.IsGenericType)
            {
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL field {fieldName} is not an enum list.");
            }
            Type elementType = field.FieldType.GetGenericArguments()[0];
            if (!elementType.IsEnum)
                throw new Exception(
                    $"[AndroidBuildXreal] XREAL field {fieldName} element is not enum.");
            list.Clear();
            foreach (string valueName in valueNames)
                list.Add(Enum.Parse(elementType, valueName));
        }

        private static void AssignXrealVirtualController(ScriptableObject settings)
        {
            FieldInfo field = RequireField(settings, "VirtualController");
            if (field.GetValue(settings) != null) return;
            string[] guids = AssetDatabase.FindAssets(
                "XREALVirtualController t:Prefab",
                new[] { "Packages/com.xreal.xr" });
            if (guids.Length == 0)
                throw new Exception(
                    "[AndroidBuildXreal] XREALVirtualController prefab missing from SDK.");
            GameObject prefab = AssetDatabase.LoadAssetAtPath<GameObject>(
                AssetDatabase.GUIDToAssetPath(guids[0]));
            if (prefab == null)
                throw new Exception(
                    "[AndroidBuildXreal] XREALVirtualController prefab could not be loaded.");
            field.SetValue(settings, prefab);
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
            if (AssetDatabase.LoadAssetAtPath<Shader>(
                    PhoneOnlySceneBuilder.XrealDepthOcclusionShaderPath) == null ||
                AssetDatabase.LoadAssetAtPath<Shader>(
                    PhoneOnlySceneBuilder.XrealFreeGuyMeshShaderPath) == null)
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREAL depth occlusion/FreeGuy shader " +
                    "assets are missing.");
            }
            if (!EditorBuildSettings.TryGetConfigObject(
                    XrealSettingsKey, out ScriptableObject xrealSettings) ||
                xrealSettings == null)
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREALSettings is not registered; " +
                    "the SDK manifest/build callbacks would silently fail.");
            }
            if (!string.Equals(
                    GetFieldValue(xrealSettings, "StereoRendering").ToString(),
                    "SinglePassInstanced",
                    StringComparison.Ordinal) ||
                !string.Equals(
                    GetFieldValue(xrealSettings, "InitialTrackingType").ToString(),
                    "MODE_6DOF",
                    StringComparison.Ordinal) ||
                !string.Equals(
                    GetFieldValue(xrealSettings, "InitialInputSource").ToString(),
                    "Hands",
                    StringComparison.Ordinal) ||
                !Equals(GetFieldValue(xrealSettings, "SupportMultiResume"), true))
            {
                throw new Exception(
                    "[AndroidBuildXreal] XREAL settings are not " +
                    "SinglePassInstanced + MODE_6DOF + Hands + MultiResume.");
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
            private readonly bool _hadXrealSettingsConfig;
            private readonly ScriptableObject _previousXrealSettingsConfig;
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
                _hadXrealSettingsConfig =
                    EditorBuildSettings.TryGetConfigObject(
                        XrealSettingsKey,
                        out _previousXrealSettingsConfig);
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
                const string networkPermission =
                    "<uses-permission android:name=\"android.permission.ACCESS_NETWORK_STATE\" />";
                if (!xrealManifest.Contains(
                        "android.permission.ACCESS_WIFI_STATE",
                        StringComparison.Ordinal))
                {
                    xrealManifest = xrealManifest.Replace(
                        networkPermission,
                        networkPermission + Environment.NewLine +
                        "    <uses-permission android:name=\"android.permission.ACCESS_WIFI_STATE\" />" +
                        Environment.NewLine +
                        "    <uses-permission android:name=\"android.permission.ACCESS_FINE_LOCATION\" />" +
                        Environment.NewLine +
                        "    <uses-permission android:name=\"android.permission.NEARBY_WIFI_DEVICES\" " +
                        "android:usesPermissionFlags=\"neverForLocation\" />");
                }
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
                    if (_hadXrealSettingsConfig && _previousXrealSettingsConfig != null)
                    {
                        EditorBuildSettings.AddConfigObject(
                            XrealSettingsKey, _previousXrealSettingsConfig, true);
                    }
                    else
                    {
                        EditorBuildSettings.RemoveConfigObject(XrealSettingsKey);
                    }
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

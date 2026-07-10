using System;
using System.Collections.Generic;
using System.IO;
using MLOmega.XR.Core;
using MLOmega.XR.Reflex;
using MLOmega.XR.Reflex.Skills;
using MLOmega.XR.Scene;
using MLOmega.XR.Transport;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.SceneManagement;

namespace MLOmega.XR.Editor
{
    public static class PhoneOnlySceneBuilder
    {
        private const string ScenePath = "Assets/Scenes/PhoneOnly.unity";
        private const string ConfigPath = "Assets/Config/MLOmegaPhoneOnly.asset";
        private const string CacheConfigPath = "Assets/Settings/PhoneOnlySceneCacheConfig.asset";
        private const string ThemePath = "Assets/Settings/PhoneOnlyUITheme.asset";

        [MenuItem("MLOmega/Build PhoneOnly Scene")]
        public static void BuildScene()
        {
            UnityEngine.SceneManagement.Scene scene = EditorSceneManager.NewScene(NewSceneSetup.EmptyScene, NewSceneMode.Single);
            var config = LoadOrCreateConfig();

            var cameraGo = new GameObject("Phone Camera");
            cameraGo.tag = "MainCamera";
            var camera = cameraGo.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.black;
            cameraGo.AddComponent<AudioListener>();

            var root = new GameObject("PhoneOnly Session");
            var permissions = root.AddComponent<PermissionGate>();
            var session = root.AddComponent<XrSessionController>();
            var pairing = root.AddComponent<SessionPairing>();
            var pose = root.AddComponent<PosePublisher>();
            var capture = root.AddComponent<EyeCaptureSource>();
            var transport = root.AddComponent<LiveTransportBridge>();
            // E48-A: install APK-embedded small models at first launch, then
            // download any still-missing device models in the background.
            var modelInstaller = root.AddComponent<StreamingAssetsModelInstaller>();
            var provisioning = root.AddComponent<ModelProvisioningBridge>();
            var coordinator = root.AddComponent<PhoneOnlySessionCoordinator>();
            var preview = cameraGo.AddComponent<PhoneCameraPreview>();

            // Real phone UI path: consume PC UIIntent/SceneDelta messages and
            // render the same component registry as the glasses, without the E25
            // demo driver or any simulated source.
            var cacheConfig = LoadOrCreate<SceneCacheConfig>(CacheConfigPath);
            var theme = LoadOrCreate<UITheme>(ThemePath);
            var cache = root.AddComponent<SceneCache>();
            var tracks = root.AddComponent<LocalTrackStore>();
            var broker = root.AddComponent<UIIntentBroker>();
            var intentSource = root.AddComponent<TransportIntentSource>();
            var sourceBootstrap = root.AddComponent<E25SourceBootstrap>();
            var receiptSink = root.AddComponent<UIReceiptTransportSink>();
            var uiRuntime = root.AddComponent<UIRuntime>();
            var statusBar = root.AddComponent<StatusBar>();
            var entityHot = root.AddComponent<EntityHotUpdateHandler>();
            var sceneDelta = root.AddComponent<SceneDeltaTransportHandler>();
            var appLauncher = root.AddComponent<AppLauncherBridge>();
            var commands = root.AddComponent<DeviceCommandHandler>();

            // E48-A: the Ultra-Live reflex layer (E26/E47). GAP FIX — these components
            // were never added to the PhoneOnly scene, so the E47 device gates (wake
            // word, gestures, offline subtitles) had nothing to run them. The skills
            // emit through their own LocalIntentSource (priority-2 UL seam), registered
            // with the broker by a second E25SourceBootstrap.
            var localIntents = root.AddComponent<LocalIntentSource>();
            var localBootstrap = root.AddComponent<E25SourceBootstrap>();
            var asrBridge = root.AddComponent<AsrBridge>();
            var gestureBridge = root.AddComponent<GestureBridge>();
            var wakeGate = root.AddComponent<WakeWordGate>();
            var stableTrack = root.AddComponent<StableTrackSkill>();
            var lensWindow = root.AddComponent<LensWindowSkill>();
            var motionProximity = root.AddComponent<MotionProximitySkill>();
            var focusSearch = root.AddComponent<FocusSearchSkill>();
            var subtitle = root.AddComponent<SubtitleSkill>();
            var translate = root.AddComponent<TranslateBridge>();
            // E59: hand window-management (grab/resize/close/minimise of manipulable panels).
            var panelManipulator = root.AddComponent<PanelManipulator>();
            var reflex = root.AddComponent<ReflexScheduler>();

            Assign(session, "_config", config);
            Assign(session, "_permissions", permissions);
            Assign(pairing, "_config", config);
            Assign(capture, "_session", session);
            Assign(capture, "_pairing", pairing);
            Assign(capture, "_pose", pose);
            Assign(transport, "_pairing", pairing);
            Assign(transport, "_capture", capture);
            Assign(coordinator, "_pairing", pairing);
            Assign(coordinator, "_transport", transport);
            Assign(coordinator, "_session", session);
            Assign(preview, "_session", session);
            Assign(preview, "_camera", camera);
            Assign(cache, "_config", cacheConfig);
            Assign(tracks, "_sceneCache", cache);
            Assign(broker, "_sceneCache", cache);
            Assign(broker, "_config", cacheConfig);
            Assign(intentSource, "_bridge", transport);
            Assign(sourceBootstrap, "_broker", broker);
            Assign(sourceBootstrap, "_source", intentSource);
            Assign(receiptSink, "_bridge", transport);
            Assign(uiRuntime, "_broker", broker);
            Assign(uiRuntime, "_sceneCache", cache);
            Assign(uiRuntime, "_theme", theme);
            Assign(uiRuntime, "_camera", camera);
            Assign(uiRuntime, "_receiptSinkBehaviour", receiptSink);
            Assign(statusBar, "_theme", theme);
            Assign(statusBar, "_camera", camera);
            Assign(statusBar, "_transport", transport);
            Assign(statusBar, "_session", session);
            Assign(statusBar, "_provisioning", provisioning);
            // E48-A provisioning wiring.
            Assign(provisioning, "_pairing", pairing);
            Assign(provisioning, "_installer", modelInstaller);
            Assign(entityHot, "_sceneCache", cache);
            Assign(entityHot, "_transport", transport);
            Assign(sceneDelta, "_transport", transport);
            Assign(sceneDelta, "_sceneCache", cache);
            Assign(sceneDelta, "_tracks", tracks);
            Assign(commands, "_broker", broker);
            Assign(commands, "_statusBar", statusBar);
            Assign(commands, "_appLauncher", appLauncher);
            Assign(commands, "_transport", transport);
            // E48-A reflex wiring (the rest self-finds in Awake at scene load).
            Assign(translate, "_commands", commands);
            Assign(translate, "_statusBar", statusBar);
            Assign(localBootstrap, "_broker", broker);
            Assign(localBootstrap, "_source", localIntents);
            Assign(reflex, "_gestureBridge", gestureBridge);
            Assign(reflex, "_asrBridge", asrBridge);
            Assign(reflex, "_stableTrack", stableTrack);
            Assign(reflex, "_lensWindow", lensWindow);
            Assign(reflex, "_motionProximity", motionProximity);
            Assign(reflex, "_focusSearch", focusSearch);
            Assign(reflex, "_subtitle", subtitle);
            // E59: the manipulator runs BEFORE the lens on the pinch stream (claim → no zoom).
            Assign(reflex, "_panelManipulator", panelManipulator);
            Assign(panelManipulator, "_camera", camera);
            Assign(wakeGate, "_asr", asrBridge);
            Assign(translate, "_asrBridge", asrBridge);
            Assign(translate, "_subtitle", subtitle);
            Assign(translate, "_config", config);

            new GameObject("EventSystem",
                typeof(UnityEngine.EventSystems.EventSystem),
                typeof(UnityEngine.EventSystems.StandaloneInputModule));

            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
            if (!EditorSceneManager.SaveScene(scene, ScenePath))
                throw new System.InvalidOperationException("Unable to save PhoneOnly scene");
            var scenes = new List<EditorBuildSettingsScene>(EditorBuildSettings.scenes);
            scenes.RemoveAll(s => s.path == ScenePath);
            scenes.Insert(0, new EditorBuildSettingsScene(ScenePath, true));
            EditorBuildSettings.scenes = scenes.ToArray();
            AssetDatabase.SaveAssets();
            Debug.Log("[PhoneOnlySceneBuilder] Scene and config ready. Set the PC endpoint before Android build.");
        }

        private static MLOmegaConfig LoadOrCreateConfig()
        {
            var config = AssetDatabase.LoadAssetAtPath<MLOmegaConfig>(ConfigPath);
            if (config != null) return config;
            Directory.CreateDirectory(Path.GetDirectoryName(ConfigPath));
            config = ScriptableObject.CreateInstance<MLOmegaConfig>();
            var so = new SerializedObject(config);
            so.FindProperty("_adapter").enumValueIndex = (int)XrAdapterKind.PhoneOnly;
            so.FindProperty("_deviceId").stringValue = "phone-only-primary";
            so.ApplyModifiedPropertiesWithoutUndo();
            AssetDatabase.CreateAsset(config, ConfigPath);
            return config;
        }

        private static T LoadOrCreate<T>(string path) where T : ScriptableObject
        {
            var existing = AssetDatabase.LoadAssetAtPath<T>(path);
            if (existing != null) return existing;
            Directory.CreateDirectory(Path.GetDirectoryName(path));
            var asset = ScriptableObject.CreateInstance<T>();
            AssetDatabase.CreateAsset(asset, path);
            AssetDatabase.SaveAssets();
            return asset;
        }

        private static void Assign(UnityEngine.Object target, string field, UnityEngine.Object value)
        {
            var so = new SerializedObject(target);
            var property = so.FindProperty(field);
            if (property == null) throw new MissingFieldException(target.GetType().Name, field);
            property.objectReferenceValue = value;
            so.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}

using System;
using System.IO;
using MLOmega.XR.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.Rendering;
using UnityEngine.Rendering.Universal;

namespace MLOmega.XR.Editor
{
    public static class WorldCreatorSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/XrealWorldCreator.unity";
        private const string OfficialRigPrefabPath =
            "Packages/com.xreal.xr/Runtime/Prefabs/" +
            "XR Interaction Hands Setup.prefab";

        [MenuItem("MLOmega/XREAL/Build World Atelier Scene")]
        public static void BuildScene()
        {
            var scene = EditorSceneManager.NewScene(
                NewSceneSetup.EmptyScene,
                NewSceneMode.Single);

            // HelloMR is the hardware-proven reference for One Pro + Eye on
            // the S24. Reuse its exact XREAL/XRI rig instead of rebuilding a
            // partial XR Origin by hand. This also brings the official input
            // actions, EventSystem and controller/hand interactors with it.
            GameObject rigPrefab =
                AssetDatabase.LoadAssetAtPath<GameObject>(
                    OfficialRigPrefabPath);
            if (rigPrefab == null)
                throw new FileNotFoundException(
                    "Official XREAL interaction rig missing.",
                    OfficialRigPrefabPath);
            GameObject rig = PrefabUtility.InstantiatePrefab(
                rigPrefab,
                scene) as GameObject;
            if (rig == null)
                throw new InvalidOperationException(
                    "Unable to instantiate the official XREAL interaction rig.");
            rig.name = "XR Interaction Hands Setup (Official)";

            Camera camera = rig.GetComponentInChildren<Camera>(true);
            if (camera == null)
                throw new InvalidOperationException(
                    "Official XREAL interaction rig has no camera.");
            // Match the hardware-proven XREAL template exactly. Its camera uses
            // the Built-in Skybox clear path with no skybox material; black
            // pixels are therefore unlit on the optical display. SolidColor is
            // not equivalent in the XREAL compositor and produced its violet
            // diagnostic clear on the One Pro.
            RenderSettings.skybox = null;
            camera.clearFlags = CameraClearFlags.Skybox;
            camera.backgroundColor = new Color(0f, 0f, 0f, 0f);
            camera.allowHDR = true;
            camera.nearClipPlane = .01f;
            camera.fieldOfView = 25f;
            UniversalAdditionalCameraData cameraData =
                camera.GetComponent<UniversalAdditionalCameraData>();
            if (GraphicsSettings.defaultRenderPipeline != null)
            {
                cameraData ??=
                    camera.gameObject.AddComponent<UniversalAdditionalCameraData>();
                // UniversalRenderPipelineAsset.Create() does not populate
                // postProcessData. Enabling UberPost with that null resource
                // paints the whole optical surface magenta.
                cameraData.renderPostProcessing = false;
            }
            else if (cameraData != null)
            {
                // The hardware-proven XREAL template is Built-in and has no
                // URP camera extension. Mirror it exactly for the Atelier.
                UnityEngine.Object.DestroyImmediate(cameraData);
            }

            var root = new GameObject("MLOmega World Atelier");
            var exchange = root.AddComponent<WorldMapDocumentExchange>();
            Type spatialType = Type.GetType(
                "MLOmega.XR.UI.XrealSpatialProvider, MLOmega.XR.XrealSpatial",
                false);
            if (
                spatialType == null ||
                !typeof(MonoBehaviour).IsAssignableFrom(spatialType))
                throw new InvalidOperationException(
                    "XREAL spatial assembly unavailable; run PrepareDefines first.");
            Component spatial = root.AddComponent(spatialType);
            Assign(spatial, "_creatorMode", true);
            Assign(spatial, "_camera", camera);
            Assign(
                spatial,
                "_depthOcclusionShader",
                RequiredShader(PhoneOnlySceneBuilder.XrealDepthOcclusionShaderPath));
            Assign(
                spatial,
                "_freeGuyMeshShader",
                RequiredShader(PhoneOnlySceneBuilder.XrealFreeGuyMeshShaderPath));

            var creator = root.AddComponent<WorldCreatorController>();
            Assign(creator, "_spatialBehaviour", spatial);
            Assign(creator, "_camera", camera);
            Assign(creator, "_exchange", exchange);
            Type pointerType = Type.GetType(
                "MLOmega.XR.UI.XrealNativeHandPointer, " +
                "MLOmega.XR.XrealSpatial",
                false);
            if (
                pointerType == null ||
                !typeof(MonoBehaviour).IsAssignableFrom(pointerType))
                throw new InvalidOperationException(
                    "XREAL native hand pointer assembly unavailable.");
            Component pointer = root.AddComponent(pointerType);
            Assign(pointer, "_camera", camera);
            Assign(pointer, "_creator", creator);

            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
            if (!EditorSceneManager.SaveScene(scene, ScenePath))
                throw new InvalidOperationException(
                    "Unable to save World Atelier scene.");
            AssetDatabase.SaveAssets();
            Debug.Log(
                "[WorldCreatorSceneBuilder] isolated XREAL Atelier ready: " +
                ScenePath);
        }

        private static Shader RequiredShader(string path)
        {
            Shader shader = AssetDatabase.LoadAssetAtPath<Shader>(path);
            if (shader == null)
                throw new FileNotFoundException("Required shader missing: " + path);
            return shader;
        }

        private static void Assign(
            UnityEngine.Object target,
            string field,
            UnityEngine.Object value)
        {
            var serialized = new SerializedObject(target);
            SerializedProperty property = serialized.FindProperty(field);
            if (property == null)
                throw new MissingFieldException(target.GetType().Name, field);
            property.objectReferenceValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }

        private static void Assign(
            UnityEngine.Object target,
            string field,
            bool value)
        {
            var serialized = new SerializedObject(target);
            SerializedProperty property = serialized.FindProperty(field);
            if (property == null)
                throw new MissingFieldException(target.GetType().Name, field);
            property.boolValue = value;
            serialized.ApplyModifiedPropertiesWithoutUndo();
        }
    }
}

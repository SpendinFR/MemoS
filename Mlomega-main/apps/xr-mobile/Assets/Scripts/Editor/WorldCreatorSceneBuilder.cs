using System;
using System.IO;
using MLOmega.XR.UI;
using UnityEditor;
using UnityEditor.SceneManagement;
using UnityEngine;
using UnityEngine.InputSystem;
using UnityEngine.InputSystem.XR;
using Unity.XR.CoreUtils;

namespace MLOmega.XR.Editor
{
    public static class WorldCreatorSceneBuilder
    {
        public const string ScenePath = "Assets/Scenes/XrealWorldCreator.unity";

        [MenuItem("MLOmega/XREAL/Build World Atelier Scene")]
        public static void BuildScene()
        {
            var scene = EditorSceneManager.NewScene(
                NewSceneSetup.EmptyScene,
                NewSceneMode.Single);
            var cameraGo = new GameObject("Atelier Camera");
            cameraGo.tag = "MainCamera";
            Camera camera = cameraGo.AddComponent<Camera>();
            camera.clearFlags = CameraClearFlags.SolidColor;
            camera.backgroundColor = Color.black;
            camera.nearClipPlane = .1f;
            camera.fieldOfView = 25f;
            cameraGo.AddComponent<AudioListener>();
            BuildXrealRig(cameraGo, camera);

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

            Directory.CreateDirectory(Path.GetDirectoryName(ScenePath));
            if (!EditorSceneManager.SaveScene(scene, ScenePath))
                throw new InvalidOperationException(
                    "Unable to save World Atelier scene.");
            AssetDatabase.SaveAssets();
            Debug.Log(
                "[WorldCreatorSceneBuilder] isolated XREAL Atelier ready: " +
                ScenePath);
        }

        private static void BuildXrealRig(GameObject cameraGo, Camera camera)
        {
            var originGo = new GameObject("XR Origin (XREAL Atelier)");
            var offset = new GameObject("Camera Offset");
            offset.transform.SetParent(originGo.transform, false);
            cameraGo.transform.SetParent(offset.transform, false);
            var origin = originGo.AddComponent<XROrigin>();
            origin.Origin = originGo;
            origin.Camera = camera;
            origin.CameraFloorOffsetObject = offset;
            origin.RequestedTrackingOriginMode =
                XROrigin.TrackingOriginMode.Device;
            var pose = cameraGo.AddComponent<TrackedPoseDriver>();
            pose.trackingType =
                TrackedPoseDriver.TrackingType.RotationAndPosition;
            pose.updateType =
                TrackedPoseDriver.UpdateType.UpdateAndBeforeRender;
            pose.positionInput = new InputActionProperty(new InputAction(
                "Atelier Head Position",
                InputActionType.Value,
                "<XRHMD>/centerEyePosition",
                expectedControlType: "Vector3"));
            pose.rotationInput = new InputActionProperty(new InputAction(
                "Atelier Head Rotation",
                InputActionType.Value,
                "<XRHMD>/centerEyeRotation",
                expectedControlType: "Quaternion"));
            pose.trackingStateInput = new InputActionProperty(new InputAction(
                "Atelier Tracking State",
                InputActionType.Value,
                "<XRHMD>/trackingState",
                expectedControlType: "Integer"));
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

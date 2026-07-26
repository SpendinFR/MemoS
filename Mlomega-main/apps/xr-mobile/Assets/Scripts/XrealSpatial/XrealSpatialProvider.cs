using System;
using System.Collections.Generic;
using System.Collections;
using System.IO;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using MLOmega.Contracts.V19;
using MLOmega.XR.Core;
using MLOmega.XR.Transport;
using UnityEngine;
#if XREAL_SDK_PRESENT
using Unity.Collections;
using Unity.XR.CoreUtils;
using Unity.XR.XREAL;
using UnityEngine.XR.ARFoundation;
using UnityEngine.XR.ARSubsystems;
#endif
#if XREAL_SDK_PRESENT && XR_HANDS
using UnityEngine.XR.Hands;
#endif

namespace MLOmega.XR.UI
{
    /// <summary>
    /// XREAL-only producer for the calibrated World Canvas.
    ///
    /// XREAL SDK 3.1 exposes its planes/depth mesh through AR Foundation. This
    /// component creates those managers by reflection so a clean PhoneOnly
    /// checkout keeps no AR Foundation dependency. Pixel detections are promoted
    /// to 3D only after a ray hits a real XREAL mesh collider while the head pose
    /// is tracked. No hit means no world intent.
    /// </summary>
    public sealed class XrealSpatialProvider :
        MonoBehaviour,
        IXrealSpatialProvider
    {
        private const string CalibrationId = "xreal-eye-tracking-local-v1";
        private const float SceneCadenceSeconds = 0.20f;
        private const float CapabilityCadenceSeconds = 0.75f;

        [SerializeField] private AugmentedRealityFeatureRegistry _features;
        [SerializeField] private LiveTransportBridge _transport;
        [SerializeField] private LocalIntentSource _intents;
        [SerializeField] private PosePublisher _pose;
        [SerializeField] private Camera _camera;
        [SerializeField] private Shader _depthOcclusionShader;
        [SerializeField] private Shader _freeGuyMeshShader;

        private readonly Dictionary<string, TrackHistory> _tracks =
            new Dictionary<string, TrackHistory>(StringComparer.Ordinal);
        private readonly List<RadioSample> _radioSamples = new List<RadioSample>();
        private Component _meshManager;
        private Component _anchorManager;
        private GameObject _meshPrefab;
        private GameObject _arSession;
        private float _nextCapabilityProbe;
        private float _nextSceneAt;
        private float _nextRadioAt;
        private float _nextManagerRetryAt;
        private bool _managersRequested;
        private Vector3? _measureStart;
        private KeyboardPlacement _keyboard;
        private Material _depthOcclusionMaterial;
        private Material _freeGuyMeshMaterial;
        private bool _anchorsLoadStarted;
        private readonly HashSet<string> _emittedAnchorIds =
            new HashSet<string>(StringComparer.Ordinal);
        private Vector3? _ballisticTarget;
        private Vector3 _lastHandPosition;
        private float _lastHandAt;
        private float _nextBallisticAt;
        private GeoDestination _navigationDestination;
        private float _nextNavigationAt;
        private bool _navigationStarting;

        public bool DepthReady { get; private set; }
        public string LastProviderError { get; private set; } = string.Empty;
        public int ProjectedTrackCount => _tracks.Count;

        private static bool CompiledForXreal
        {
            get
            {
#if XREAL_SDK_PRESENT
                return true;
#else
                return false;
#endif
            }
        }

        private void Awake()
        {
            if (_features == null)
                _features = FindAnyObjectByType<AugmentedRealityFeatureRegistry>();
            if (_transport == null)
                _transport = FindAnyObjectByType<LiveTransportBridge>();
            if (_intents == null) _intents = FindAnyObjectByType<LocalIntentSource>();
            if (_pose == null) _pose = FindAnyObjectByType<PosePublisher>();
            if (_camera == null) _camera = Camera.main;
            if (_depthOcclusionShader != null)
                _depthOcclusionMaterial = new Material(_depthOcclusionShader);
            if (_freeGuyMeshShader != null)
                _freeGuyMeshMaterial = new Material(_freeGuyMeshShader);
        }

        private void OnEnable()
        {
            if (_transport != null) _transport.MessageReceived += OnTransportMessage;
            if (_features != null) _features.FeatureChanged += OnFeatureChanged;
        }

        private void OnDisable()
        {
            if (_transport != null) _transport.MessageReceived -= OnTransportMessage;
            if (_features != null) _features.FeatureChanged -= OnFeatureChanged;
            SetLocalCapabilities(false);
            SetManagersEnabled(false);
        }

        private void OnDestroy()
        {
            if (_depthOcclusionMaterial != null) Destroy(_depthOcclusionMaterial);
            if (_freeGuyMeshMaterial != null) Destroy(_freeGuyMeshMaterial);
        }

        private void Update()
        {
            if (!CompiledForXreal || _features == null) return;
            bool wanted = _features.MasterEnabled && AnySpatialFeatureSelected();
            if (wanted && !_managersRequested &&
                Time.unscaledTime >= _nextManagerRetryAt)
                EnsureSpatialManagers();
            SetManagersEnabled(wanted);

            if (Time.unscaledTime >= _nextCapabilityProbe)
            {
                _nextCapabilityProbe = Time.unscaledTime + CapabilityCadenceSeconds;
                DepthReady = wanted && PoseTracked() && HasReadableDepthMesh();
                SetLocalCapabilities(DepthReady);
                UpdateMeshRendering();
                if (DepthReady &&
                    _features.IsActive(AugmentedRealityFeatureRegistry.SpatialKeyboard) &&
                    _keyboard == null)
                {
                    TryPlaceKeyboard(new Vector2(0.5f, 0.58f));
                }
            }

            if (DepthReady &&
                _features.IsActive(AugmentedRealityFeatureRegistry.RadioField) &&
                Time.unscaledTime >= _nextRadioAt)
            {
                _nextRadioAt = Time.unscaledTime + 5f;
                SampleCurrentWifi();
            }
            if (DepthReady &&
                _features.IsActive(AugmentedRealityFeatureRegistry.PersistentAnchors) &&
                !_anchorsLoadStarted)
                LoadPersistentAnchors();
            if (DepthReady &&
                _features.IsActive(AugmentedRealityFeatureRegistry.BallisticPreview))
                UpdateBallisticPreview();
            if (
                _navigationDestination != null &&
                _features.IsActive(
                    AugmentedRealityFeatureRegistry.StreetNavigation) &&
                Time.unscaledTime >= _nextNavigationAt)
            {
                _nextNavigationAt = Time.unscaledTime + 2f;
                TickNavigation();
            }
        }

        private bool AnySpatialFeatureSelected()
        {
            string[] ids =
            {
                AugmentedRealityFeatureRegistry.WorldLabels,
                AugmentedRealityFeatureRegistry.TrajectoryForecast,
                AugmentedRealityFeatureRegistry.EventVision,
                AugmentedRealityFeatureRegistry.ArMeasurement,
                AugmentedRealityFeatureRegistry.SpatialKeyboard,
                AugmentedRealityFeatureRegistry.RadioField,
                AugmentedRealityFeatureRegistry.PersistentAnchors,
                AugmentedRealityFeatureRegistry.DepthOcclusion,
                AugmentedRealityFeatureRegistry.WorldStyling,
                AugmentedRealityFeatureRegistry.BallisticPreview,
            };
            foreach (string id in ids)
                if (_features.IsSelected(id)) return true;
            return false;
        }

        private void OnFeatureChanged(string feature, bool enabled)
        {
            if (!enabled)
            {
                if (feature == AugmentedRealityFeatureRegistry.ArMeasurement)
                    _measureStart = null;
                if (feature == AugmentedRealityFeatureRegistry.SpatialKeyboard)
                    _keyboard = null;
                if (feature == AugmentedRealityFeatureRegistry.BallisticPreview)
                    _ballisticTarget = null;
                if (feature == AugmentedRealityFeatureRegistry.StreetNavigation)
                {
                    _navigationDestination = null;
                    _features?.SetLocalCapability(
                        AugmentedRealityFeatureRegistry.StreetNavigation, false);
                }
            }
            _nextCapabilityProbe = 0f;
            UpdateMeshRendering();
        }

        private void OnTransportMessage(string json)
        {
            if (
                !DepthReady ||
                string.IsNullOrEmpty(json) ||
                json.IndexOf("\"scene_delta\"", StringComparison.Ordinal) < 0 ||
                Time.unscaledTime < _nextSceneAt)
                return;
            _nextSceneAt = Time.unscaledTime + SceneCadenceSeconds;
            try
            {
                SceneDelta delta = ContractJson.Deserialize<SceneDelta>(json);
                if (delta?.Entities != null) ProjectSceneDelta(delta);
            }
            catch (Exception ex)
            {
                LastProviderError = "scene_delta:" + ex.GetType().Name;
            }
        }

        private void ProjectSceneDelta(SceneDelta delta)
        {
            if (
                !delta.FrameWidth.HasValue ||
                !delta.FrameHeight.HasValue ||
                delta.FrameWidth.Value <= 0 ||
                delta.FrameHeight.Value <= 0)
                return;
            foreach (Dictionary<string, object> entity in delta.Entities)
            {
                string trackId = ReadString(entity, "track_id");
                string label = ReadString(entity, "label");
                string kind = ReadString(entity, "kind");
                if (
                    string.IsNullOrWhiteSpace(trackId) ||
                    !TryViewportPoint(entity, delta, out Vector2 viewport) ||
                    !TryDepthHit(viewport, out RaycastHit hit))
                    continue;
                float confidence = Mathf.Clamp01(
                    (float)ReadNumber(entity, "confidence", 0.6));
                UpdateTrack(
                    trackId,
                    string.IsNullOrWhiteSpace(label) ? kind : label,
                    kind,
                    hit.point,
                    confidence,
                    delta.SourceFrameId);
            }
        }

        private void UpdateTrack(
            string trackId,
            string label,
            string kind,
            Vector3 position,
            float confidence,
            string frameId)
        {
            float now = Time.unscaledTime;
            if (!_tracks.TryGetValue(trackId, out TrackHistory history))
            {
                history = new TrackHistory();
                _tracks[trackId] = history;
            }
            Vector3 previous = history.Position;
            float elapsed = now - history.At;
            bool hadPrevious = history.HasValue && elapsed > 0.04f && elapsed < 3f;
            history.Previous = previous;
            history.Position = position;
            history.At = now;
            history.HasValue = true;
            history.Label = label;
            history.Kind = kind;

            string evidence = string.IsNullOrWhiteSpace(frameId)
                ? "depth:xreal-live"
                : "frame:" + frameId;
            if (_features.IsActive(AugmentedRealityFeatureRegistry.WorldLabels))
                EmitWorldMarker(trackId, label, kind, position, confidence, evidence);

            if (!hadPrevious) return;
            Vector3 delta = position - previous;
            float speed = delta.magnitude / elapsed;
            if (speed < 0.08f || speed > 6f) return;

            if (_features.IsActive(AugmentedRealityFeatureRegistry.EventVision))
                EmitEventMotion(trackId, label, previous, position, confidence, evidence);
            if (
                _features.IsActive(AugmentedRealityFeatureRegistry.TrajectoryForecast) &&
                string.Equals(kind, "person", StringComparison.OrdinalIgnoreCase))
            {
                EmitTrajectory(
                    trackId, label, position, delta / elapsed, confidence, evidence);
            }
        }

        private void EmitWorldMarker(
            string trackId,
            string label,
            string kind,
            Vector3 position,
            float confidence,
            string evidence)
        {
            if (_intents == null || string.IsNullOrWhiteSpace(label)) return;
            float quality = Mathf.Clamp(confidence, 0.72f, 0.94f);
            _intents.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = "xreal-world-" + trackId,
                Producer = "ultralive",
                TargetTrackId = trackId,
                Component = "world_marker",
                Anchor = new Dictionary<string, object>
                {
                    { "coordinate_space", "tracking_local" },
                    { "position", Point(position) },
                },
                Content = SpatialContent(quality, true, new Dictionary<string, object>
                {
                    { "marker_id", trackId },
                    { "label", label },
                    { "subtitle", "VISIONRT + XREAL DEPTH" },
                    { "kind", NormaliseMarkerKind(kind) },
                    {
                        "distance_m",
                        _camera == null ? 0d : Vector3.Distance(
                            _camera.transform.position, position)
                    },
                    { "anchor_quality", quality },
                }),
                TruthLevel = "observed",
                Confidence = quality,
                Priority = 0.42,
                TtlMs = 1250,
                EvidenceRefs = Evidence(evidence),
            });
        }

        private void EmitEventMotion(
            string trackId,
            string label,
            Vector3 previous,
            Vector3 current,
            float confidence,
            string evidence)
        {
            List<Dictionary<string, object>> points =
                Interpolate(previous, current, 6);
            EmitPath(
                "xreal-motion-" + trackId,
                "event_motion",
                string.IsNullOrWhiteSpace(label) ? "MOUVEMENT" : label,
                0.55f,
                confidence,
                new List<Dictionary<string, object>>
                {
                    Path("motion-" + trackId, 1f, confidence, points),
                },
                evidence,
                new Dictionary<string, object>
                {
                    { "rgb_motion_valid", true },
                    { "head_motion_compensated", true },
                });
        }

        private void EmitTrajectory(
            string trackId,
            string label,
            Vector3 origin,
            Vector3 velocity,
            float confidence,
            string evidence)
        {
            Vector3 horizontal = Vector3.ProjectOnPlane(velocity, Vector3.up);
            float speed = Mathf.Clamp(horizontal.magnitude, 0.15f, 2.2f);
            Vector3 direction = horizontal.sqrMagnitude > 0.001f
                ? horizontal.normalized
                : Vector3.forward;
            Vector3 side = Vector3.Cross(Vector3.up, direction).normalized;
            var primary = new List<Dictionary<string, object>>();
            var alternative = new List<Dictionary<string, object>>();
            for (int i = 0; i <= 5; i++)
            {
                float t = i * 0.4f;
                primary.Add(Point(origin + direction * speed * t));
                alternative.Add(Point(
                    origin +
                    direction * speed * t * 0.92f +
                    side * 0.16f * t * t));
            }
            EmitPath(
                "xreal-forecast-" + trackId,
                "trajectory_forecast",
                string.IsNullOrWhiteSpace(label) ? "PERSONNE" : label,
                2f,
                confidence,
                new List<Dictionary<string, object>>
                {
                    Path("primary-" + trackId, 0.72f, confidence, primary),
                    Path("alternate-" + trackId, 0.28f, confidence * 0.9f, alternative),
                },
                evidence,
                null);
        }

        private void EmitPath(
            string id,
            string mode,
            string label,
            float horizon,
            float quality,
            List<Dictionary<string, object>> paths,
            string evidence,
            Dictionary<string, object> extra)
        {
            if (_intents == null) return;
            var additions = new Dictionary<string, object>
            {
                { "mode", mode },
                { "label", label ?? string.Empty },
                { "horizon_s", horizon },
                { "paths", paths },
            };
            if (extra != null)
                foreach (KeyValuePair<string, object> item in extra)
                    additions[item.Key] = item.Value;
            _intents.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = id,
                Producer = "ultralive",
                Component = "world_path",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(
                    Mathf.Clamp(quality, 0.66f, 0.94f), true, additions),
                TruthLevel = "probable",
                Confidence = Mathf.Clamp01(quality),
                Priority = 0.48,
                TtlMs = 900,
                EvidenceRefs = Evidence(evidence),
            });
        }

        /// <summary>
        /// Capture one endpoint for the explicit AR ruler. Two valid Depth hits
        /// emit a measurement and reset the pair.
        /// </summary>
        public bool CaptureMeasurementPoint(Vector2 viewport)
        {
            if (
                _features == null ||
                !_features.IsActive(AugmentedRealityFeatureRegistry.ArMeasurement) ||
                !TryDepthHit(viewport, out RaycastHit hit))
                return false;
            if (!_measureStart.HasValue)
            {
                _measureStart = hit.point;
                return true;
            }
            Vector3 start = _measureStart.Value;
            _measureStart = null;
            float distance = Vector3.Distance(start, hit.point);
            if (distance < 0.01f || distance > 20f) return false;
            const float uncertainty = 0.02f;
            _intents?.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = "xreal-measure-" + DateTime.UtcNow.Ticks,
                Producer = "ultralive",
                Component = "world_measure",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(0.84f, true, new Dictionary<string, object>
                {
                    { "intrinsics_valid", true },
                    { "start", Point(start) },
                    { "end", Point(hit.point) },
                    { "distance_m", distance },
                    { "uncertainty_m", uncertainty },
                    { "label", "XREAL DEPTH" },
                }),
                TruthLevel = "observed",
                Confidence = 0.84,
                Priority = 0.38,
                TtlMs = 15000,
                EvidenceRefs = Evidence("depth:xreal-measure"),
            });
            return true;
        }

        public bool TryPlaceKeyboard(Vector2 viewport)
        {
            if (
                _features == null ||
                !_features.IsActive(AugmentedRealityFeatureRegistry.SpatialKeyboard) ||
                !TryDepthHit(viewport, out RaycastHit hit) ||
                Mathf.Abs(Vector3.Dot(hit.normal, Vector3.up)) < 0.65f)
                return false;
            Vector3 forward = Vector3.ProjectOnPlane(
                _camera.transform.forward, hit.normal).normalized;
            if (forward.sqrMagnitude < 0.01f) forward = Vector3.forward;
            Vector3 right = Vector3.Cross(hit.normal, forward).normalized;
            const float width = 0.70f;
            const float height = 0.25f;
            Vector3 origin =
                hit.point - right * (width * 0.5f) - forward * (height * 0.5f);
            _keyboard = new KeyboardPlacement
            {
                Origin = origin,
                Right = right,
                Forward = forward,
                Normal = hit.normal,
                Width = width,
                Height = height,
            };
            _intents?.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = "xreal-spatial-keyboard",
                Producer = "ultralive",
                Component = "world_keyboard",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(0.82f, true, new Dictionary<string, object>
                {
                    { "explicit_activation", true },
                    { "hand_tracking_valid", true },
                    { "origin", Point(origin) },
                    { "right", Point(right) },
                    { "forward", Point(forward) },
                    { "width_m", width },
                    { "height_m", height },
                }),
                TruthLevel = "observed",
                Confidence = 0.82,
                Priority = 0.32,
                TtlMs = 600000,
                EvidenceRefs = Evidence("depth:xreal-keyboard-plane"),
            });
            return true;
        }

        public bool PressKeyboard(Vector2 viewport, bool contactConfirmed)
        {
            if (_keyboard == null || _camera == null) return false;
            Ray ray = _camera.ViewportPointToRay(viewport);
            var plane = new Plane(_keyboard.Normal, _keyboard.Origin);
            if (!plane.Raycast(ray, out float enter) || enter < 0f || enter > 10f)
                return false;
            Vector3 point = ray.GetPoint(enter);
            foreach (Components.WorldKeyboardPlane keyboard in
                FindObjectsByType<Components.WorldKeyboardPlane>(
                    FindObjectsSortMode.None))
            {
                if (keyboard.TryPressWorld(point, contactConfirmed, out _))
                    return true;
            }
            return false;
        }

        private bool TryDepthHit(Vector2 viewport, out RaycastHit selected)
        {
            selected = default;
            if (
                !DepthReady ||
                _camera == null ||
                viewport.x < 0f || viewport.x > 1f ||
                viewport.y < 0f || viewport.y > 1f)
                return false;
            Ray ray = _camera.ViewportPointToRay(viewport);
            RaycastHit[] hits = Physics.RaycastAll(
                ray, 20f, ~0, QueryTriggerInteraction.Ignore);
            float nearest = float.MaxValue;
            bool found = false;
            foreach (RaycastHit hit in hits)
            {
                if (
                    hit.collider == null ||
                    hit.collider.GetComponentInParent<XrealSpatialMeshTag>() == null ||
                    hit.distance >= nearest)
                    continue;
                nearest = hit.distance;
                selected = hit;
                found = true;
            }
            return found;
        }

        private bool PoseTracked() =>
            _pose != null && _pose.Latest.IsTracking;

        private bool HasReadableDepthMesh()
        {
            foreach (XrealSpatialMeshTag tag in
                FindObjectsByType<XrealSpatialMeshTag>(FindObjectsSortMode.None))
            {
                MeshCollider collider = tag.GetComponent<MeshCollider>();
                if (
                    collider != null &&
                    collider.enabled &&
                    collider.sharedMesh != null &&
                    collider.sharedMesh.vertexCount >= 3)
                    return true;
            }
            return false;
        }

        private void EnsureSpatialManagers()
        {
            _managersRequested = true;
            if (!CompiledForXreal) return;
            try
            {
                Type arSessionType = FindType("UnityEngine.XR.ARFoundation.ARSession");
                Type meshManagerType =
                    FindType("UnityEngine.XR.ARFoundation.ARMeshManager");
                Type anchorManagerType =
                    FindType("UnityEngine.XR.ARFoundation.ARAnchorManager");
                Type originType = FindType("Unity.XR.CoreUtils.XROrigin");
                if (arSessionType == null || meshManagerType == null ||
                    anchorManagerType == null || originType == null)
                    throw new InvalidOperationException(
                        "AR Foundation/XROrigin unavailable in XREAL product build");

                if (FindBehaviour(arSessionType) == null)
                {
                    _arSession = new GameObject("AR Session (XREAL product)");
                    _arSession.AddComponent(arSessionType);
                }
                Component origin = FindBehaviour(originType);
                if (origin == null)
                    throw new InvalidOperationException("XREAL XR Origin missing");
                _meshManager = origin.GetComponent(meshManagerType) ??
                    origin.gameObject.AddComponent(meshManagerType);
                _anchorManager = origin.GetComponent(anchorManagerType) ??
                    origin.gameObject.AddComponent(anchorManagerType);
                _meshPrefab = BuildDepthMeshPrefab();
                SetMember(_meshManager, "meshPrefab", _meshPrefab);
                SetMember(_meshManager, "density", 0.35f);
                SetMember(_meshManager, "normals", true);
                LastProviderError = string.Empty;
                ConfigurePersistentAnchors();
            }
            catch (Exception ex)
            {
                _managersRequested = false;
                _nextManagerRetryAt = Time.unscaledTime + 3f;
                LastProviderError =
                    "xreal_spatial_init:" + ex.GetType().Name + ":" + ex.Message;
                Debug.LogWarning("[XrealSpatialProvider] " + LastProviderError);
                SetLocalCapabilities(false);
            }
        }

        private GameObject BuildDepthMeshPrefab()
        {
            var prefab = new GameObject("MLOmega XREAL Depth Mesh");
            prefab.transform.SetParent(transform, false);
            prefab.AddComponent<MeshFilter>();
            MeshRenderer renderer = prefab.AddComponent<MeshRenderer>();
            renderer.enabled = false;
            prefab.AddComponent<MeshCollider>();
            prefab.AddComponent<XrealSpatialMeshTag>();
            return prefab;
        }

        private void SetManagersEnabled(bool enabled)
        {
            if (_meshManager is Behaviour mesh) mesh.enabled = enabled;
            if (_arSession != null) _arSession.SetActive(enabled);
        }

        private void UpdateMeshRendering()
        {
            bool occlusion = _features != null &&
                _features.IsActive(AugmentedRealityFeatureRegistry.DepthOcclusion) &&
                _depthOcclusionMaterial != null;
            bool styling = _features != null &&
                _features.IsActive(AugmentedRealityFeatureRegistry.WorldStyling) &&
                _freeGuyMeshMaterial != null;
            foreach (XrealSpatialMeshTag tag in
                FindObjectsByType<XrealSpatialMeshTag>(
                    FindObjectsInactive.Include,
                    FindObjectsSortMode.None))
            {
                if (tag == null) continue;
                MeshRenderer renderer = tag.GetComponent<MeshRenderer>();
                if (renderer == null) continue;
                renderer.enabled = occlusion || styling;
                if (occlusion && styling)
                    renderer.sharedMaterials = new[]
                    {
                        _depthOcclusionMaterial,
                        _freeGuyMeshMaterial,
                    };
                else if (occlusion)
                    renderer.sharedMaterial = _depthOcclusionMaterial;
                else if (styling)
                    renderer.sharedMaterial = _freeGuyMeshMaterial;
            }
        }

        private bool AnchorProviderReady()
        {
#if XREAL_SDK_PRESENT
            return _anchorManager is ARAnchorManager manager &&
                manager.subsystem != null;
#else
            return false;
#endif
        }

        private void ConfigurePersistentAnchors()
        {
#if XREAL_SDK_PRESENT
            if (!(_anchorManager is ARAnchorManager manager)) return;
            manager.SetAndCreateAnchorMappingDirectory(
                System.IO.Path.Combine(
                    Application.persistentDataPath, "xreal-anchor-maps"));
#endif
        }

        private bool HandProviderReady()
        {
#if XREAL_SDK_PRESENT && XR_HANDS
            var subsystems = new List<XRHandSubsystem>();
            SubsystemManager.GetSubsystems(subsystems);
            foreach (XRHandSubsystem subsystem in subsystems)
                if (subsystem != null && subsystem.running) return true;
#endif
            return false;
        }

        private async void LoadPersistentAnchors()
        {
            _anchorsLoadStarted = true;
#if XREAL_SDK_PRESENT
            if (!(_anchorManager is ARAnchorManager manager) ||
                manager.subsystem == null)
            {
                _anchorsLoadStarted = false;
                return;
            }
            try
            {
                var idsResult = await manager.TryGetSavedAnchorIdsAsync(
                    Allocator.Temp);
                if (!idsResult.status.IsSuccess())
                {
                    LastProviderError = "xreal_anchor_list:" +
                        idsResult.status.statusCode;
                    return;
                }
                var ids = idsResult.value;
                try
                {
                    foreach (
                        UnityEngine.XR.ARSubsystems.SerializableGuid id in ids)
                    {
                        var load = await manager.TryLoadAnchorAsync(id);
                        if (load.status.IsSuccess() && load.value != null)
                            StartCoroutine(EmitAnchorWhenTracked(
                                load.value, id.ToString(), "restored"));
                    }
                }
                finally
                {
                    if (ids.IsCreated) ids.Dispose();
                }
            }
            catch (Exception ex)
            {
                LastProviderError =
                    "xreal_anchor_load:" + ex.GetType().Name + ":" + ex.Message;
                _anchorsLoadStarted = false;
            }
#endif
        }

        public bool PersistAnchorAtViewport(Vector2 viewport)
        {
            if (
                !DepthReady ||
                _features == null ||
                !_features.IsActive(
                    AugmentedRealityFeatureRegistry.PersistentAnchors) ||
                !TryDepthHit(viewport, out RaycastHit hit) ||
                !AnchorProviderReady())
                return false;
            SaveAnchorAt(hit.point, Quaternion.LookRotation(
                Vector3.ProjectOnPlane(
                    _camera != null ? _camera.transform.forward : Vector3.forward,
                    hit.normal).normalized,
                hit.normal));
            return true;
        }

        private async void SaveAnchorAt(Vector3 position, Quaternion rotation)
        {
#if XREAL_SDK_PRESENT
            if (!(_anchorManager is ARAnchorManager manager)) return;
            var go = new GameObject("MLOmega Persistent Anchor");
            go.transform.SetPositionAndRotation(position, rotation);
            ARAnchor anchor = go.AddComponent<ARAnchor>();
            try
            {
                for (int i = 0;
                    i < 90 && anchor != null &&
                    anchor.trackingState != TrackingState.Tracking;
                    i++)
                    await Awaitable.NextFrameAsync();
                if (anchor == null ||
                    anchor.trackingState != TrackingState.Tracking)
                    throw new InvalidOperationException(
                        "anchor did not reach Tracking");
                var saved = await manager.TrySaveAnchorAsync(anchor);
                if (!saved.status.IsSuccess())
                    throw new InvalidOperationException(
                        "save status=" + saved.status.statusCode);
                EmitPersistentAnchor(
                    anchor.transform.position,
                    saved.value.ToString(),
                    "saved");
            }
            catch (Exception ex)
            {
                LastProviderError =
                    "xreal_anchor_save:" + ex.GetType().Name + ":" + ex.Message;
                if (go != null) Destroy(go);
            }
#endif
        }

#if XREAL_SDK_PRESENT
        private IEnumerator EmitAnchorWhenTracked(
            ARAnchor anchor,
            string persistentId,
            string state)
        {
            float deadline = Time.unscaledTime + 8f;
            while (anchor != null &&
                anchor.trackingState != TrackingState.Tracking &&
                Time.unscaledTime < deadline)
                yield return null;
            if (anchor != null &&
                anchor.trackingState == TrackingState.Tracking)
                EmitPersistentAnchor(
                    anchor.transform.position, persistentId, state);
            else
                LastProviderError =
                    "xreal_anchor_restore:not_tracking:" + persistentId;
        }
#endif

        private void EmitPersistentAnchor(
            Vector3 position,
            string persistentId,
            string state)
        {
            if (
                _intents == null ||
                string.IsNullOrWhiteSpace(persistentId) ||
                !_emittedAnchorIds.Add(persistentId))
                return;
            _intents.Emit(new UIIntent
            {
                UiIntentId = "xreal-anchor:" + persistentId,
                Producer = "ultralive",
                Component = "world_marker",
                Anchor = new Dictionary<string, object>
                {
                    { "coordinate_space", "tracking_local" },
                    { "position", Point(position) },
                },
                Content = SpatialContent(0.88f, true,
                    new Dictionary<string, object>
                    {
                        { "anchor_quality", 0.88f },
                        { "marker_id", "anchor-" + persistentId },
                        { "label", "ANCRE MÉMOIRE" },
                        { "subtitle", state == "saved"
                            ? "Enregistrée dans le monde"
                            : "Restaurée après relance" },
                        { "kind", "memory" },
                        { "distance_m", _camera == null
                            ? 0f
                            : Vector3.Distance(
                                _camera.transform.position, position) },
                    }),
                TruthLevel = "observed",
                Confidence = 0.88,
                Priority = 0.52,
                TtlMs = 86400000,
                EvidenceRefs = Evidence(
                    "xreal:persistent-anchor:" + persistentId),
            });
        }

        public bool SetBallisticTarget(Vector2 viewport)
        {
            if (
                !DepthReady ||
                _features == null ||
                !_features.IsActive(
                    AugmentedRealityFeatureRegistry.BallisticPreview) ||
                !TryDepthHit(viewport, out RaycastHit hit) ||
                !HandProviderReady())
                return false;
            _ballisticTarget = hit.point;
            _lastHandAt = 0f;
            EmitBallisticTarget(hit.point);
            return true;
        }

        private void EmitBallisticTarget(Vector3 target)
        {
            _intents?.Emit(new UIIntent
            {
                UiIntentId = "xreal-ballistic-target",
                Producer = "ultralive",
                Component = "world_marker",
                Anchor = new Dictionary<string, object>
                {
                    { "coordinate_space", "tracking_local" },
                    { "position", Point(target) },
                },
                Content = SpatialContent(0.86f, true,
                    new Dictionary<string, object>
                    {
                        { "anchor_quality", 0.86f },
                        { "marker_id", "ballistic-target" },
                        { "label", "CIBLE LUDIQUE" },
                        { "subtitle", "Bouge la main : trajectoire calculée" },
                        { "kind", "destination" },
                        { "distance_m", _camera == null
                            ? 0f
                            : Vector3.Distance(
                                _camera.transform.position, target) },
                    }),
                TruthLevel = "observed",
                Confidence = 0.86,
                Priority = 0.62,
                TtlMs = 120000,
                EvidenceRefs = Evidence("depth:xreal-ballistic-target"),
            });
        }

        private void UpdateBallisticPreview()
        {
            if (!_ballisticTarget.HasValue ||
                !TryGetTrackedHandTip(out Vector3 hand))
            {
                _lastHandAt = 0f;
                return;
            }
            float now = Time.unscaledTime;
            if (_lastHandAt <= 0f)
            {
                _lastHandPosition = hand;
                _lastHandAt = now;
                return;
            }
            float dt = now - _lastHandAt;
            if (dt < 0.025f || dt > 0.25f)
            {
                _lastHandPosition = hand;
                _lastHandAt = now;
                return;
            }
            Vector3 measuredVelocity = (hand - _lastHandPosition) / dt;
            _lastHandPosition = hand;
            _lastHandAt = now;
            if (
                now < _nextBallisticAt ||
                measuredVelocity.magnitude < 0.25f)
                return;
            _nextBallisticAt = now + 0.10f;
            EmitBallisticPaths(hand, measuredVelocity, _ballisticTarget.Value);
        }

        private bool TryGetTrackedHandTip(out Vector3 world)
        {
            world = default;
#if XREAL_SDK_PRESENT && XR_HANDS
            var subsystems = new List<XRHandSubsystem>();
            SubsystemManager.GetSubsystems(subsystems);
            foreach (XRHandSubsystem subsystem in subsystems)
            {
                if (subsystem == null || !subsystem.running) continue;
                foreach (XRHand hand in new[]
                    { subsystem.rightHand, subsystem.leftHand })
                {
                    if (!hand.isTracked) continue;
                    XRHandJoint joint = hand.GetJoint(XRHandJointID.IndexTip);
                    if (!joint.TryGetPose(out UnityEngine.Pose pose)) continue;
                    XROrigin origin = FindAnyObjectByType<XROrigin>();
                    world = origin != null && origin.TrackablesParent != null
                        ? origin.TrackablesParent.TransformPoint(pose.position)
                        : pose.position;
                    return true;
                }
            }
#endif
            return false;
        }

        private void EmitBallisticPaths(
            Vector3 origin,
            Vector3 measuredVelocity,
            Vector3 target)
        {
            float flight = Mathf.Clamp(
                Vector3.Distance(origin, target) / 4f, 0.35f, 1.35f);
            Vector3 gravity = Physics.gravity;
            Vector3 idealVelocity =
                (target - origin - 0.5f * gravity * flight * flight) / flight;
            var paths = new List<Dictionary<string, object>>
            {
                Path("ideal", 0.92f, 0.88f,
                    ForecastProjectile(origin, idealVelocity, flight, 18)),
                Path("main_actuelle", 0.62f, 0.82f,
                    ForecastProjectile(origin, measuredVelocity, flight, 18)),
            };
            _intents?.Emit(new UIIntent
            {
                UiIntentId = "xreal-ballistic-preview",
                Producer = "ultralive",
                Component = "world_path",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(0.84f, true,
                    new Dictionary<string, object>
                    {
                        { "mode", "ballistic_preview" },
                        { "label", "PAPIER → CIBLE" },
                        { "horizon_s", flight },
                        { "paths", paths },
                        { "hand_pose_valid", true },
                        { "target_kind", "inanimate" },
                        { "safety_class", "recreational" },
                        { "weapon", false },
                    }),
                TruthLevel = "observed",
                Confidence = 0.84,
                Priority = 0.7,
                TtlMs = 800,
                EvidenceRefs = Evidence("xreal:xrhands-index-tip"),
            });
        }

        private static List<Dictionary<string, object>> ForecastProjectile(
            Vector3 origin,
            Vector3 velocity,
            float horizon,
            int steps)
        {
            var result = new List<Dictionary<string, object>>();
            int bounded = Mathf.Clamp(steps, 4, 32);
            for (int i = 0; i < bounded; i++)
            {
                float t = horizon * i / (bounded - 1f);
                result.Add(Point(
                    origin + velocity * t + 0.5f * Physics.gravity * t * t));
            }
            return result;
        }

        /// <summary>
        /// Start an honest direct-bearing AR guide without leaving the XREAL app.
        /// Android Geocoder resolves the spoken destination; GPS + compass are
        /// mandatory. This deliberately says CAP DIRECT, never street turn-by-turn.
        /// </summary>
        public bool StartNavigation(string destination)
        {
            if (
                _navigationStarting ||
                _features == null ||
                !_features.IsEffective(
                    AugmentedRealityFeatureRegistry.StreetNavigation) ||
                string.IsNullOrWhiteSpace(destination))
                return false;
#if UNITY_ANDROID && !UNITY_EDITOR
            _navigationStarting = true;
            ResolveNavigationAsync(destination.Trim());
            return true;
#else
            return false;
#endif
        }

        private bool NavigationSensorsReady()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            return PoseTracked() &&
                Input.location.status == LocationServiceStatus.Running &&
                Input.location.lastData.horizontalAccuracy > 0f &&
                Input.location.lastData.horizontalAccuracy <= 20f &&
                Input.compass.enabled &&
                Input.compass.headingAccuracy >= 0f;
#else
            return false;
#endif
        }

        private void TickNavigation()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            EmitDirectNavigation();
#endif
        }

#if UNITY_ANDROID && !UNITY_EDITOR
        private async void ResolveNavigationAsync(string destination)
        {
            try
            {
                if (!RadioPermissionReady(request: true))
                    throw new InvalidOperationException(
                        "precise location permission is required");
                Input.compass.enabled = true;
                if (Input.location.status == LocationServiceStatus.Stopped)
                    Input.location.Start(5f, 1f);
                for (int i = 0;
                    i < 300 &&
                    Input.location.status == LocationServiceStatus.Initializing;
                    i++)
                    await Awaitable.NextFrameAsync();
                if (Input.location.status != LocationServiceStatus.Running)
                    throw new InvalidOperationException(
                        "Android location service unavailable");
                for (int i = 0;
                    i < 120 && Input.compass.headingAccuracy < 0f;
                    i++)
                    await Awaitable.NextFrameAsync();
                if (!NavigationSensorsReady())
                    throw new InvalidOperationException(
                        "GPS/compass accuracy is below product threshold");

                await Awaitable.BackgroundThreadAsync();
                double[] coordinate = ResolveWithAndroidGeocoder(destination);
                await Awaitable.MainThreadAsync();
                if (coordinate == null)
                    throw new InvalidOperationException(
                        "destination not resolved by Android Geocoder");
                _navigationDestination = new GeoDestination
                {
                    Name = destination,
                    Latitude = coordinate[0],
                    Longitude = coordinate[1],
                };
                _features.SetLocalCapability(
                    AugmentedRealityFeatureRegistry.StreetNavigation, true);
                EmitDirectNavigation();
            }
            catch (Exception ex)
            {
                await Awaitable.MainThreadAsync();
                _navigationDestination = null;
                _features?.SetLocalCapability(
                    AugmentedRealityFeatureRegistry.StreetNavigation, false);
                LastProviderError =
                    "xreal_navigation:" + ex.GetType().Name + ":" + ex.Message;
                Debug.LogWarning("[XrealSpatialProvider] " + LastProviderError);
                EmitNavigationUnavailable(destination, ex.Message);
            }
            finally
            {
                _navigationStarting = false;
            }
        }

        private static double[] ResolveWithAndroidGeocoder(string destination)
        {
            using var unity = new AndroidJavaClass(
                "com.unity3d.player.UnityPlayer");
            using AndroidJavaObject activity =
                unity.GetStatic<AndroidJavaObject>("currentActivity");
            using var geocoder = new AndroidJavaObject(
                "android.location.Geocoder", activity);
            using AndroidJavaObject results =
                geocoder.Call<AndroidJavaObject>(
                    "getFromLocationName", destination, 1);
            if (results == null || results.Call<int>("size") < 1) return null;
            using AndroidJavaObject address =
                results.Call<AndroidJavaObject>("get", 0);
            if (address == null) return null;
            return new[]
            {
                address.Call<double>("getLatitude"),
                address.Call<double>("getLongitude"),
            };
        }

        private void EmitDirectNavigation()
        {
            if (
                _navigationDestination == null ||
                _intents == null ||
                _camera == null ||
                !NavigationSensorsReady())
                return;
            LocationInfo origin = Input.location.lastData;
            double distance = HaversineMeters(
                origin.latitude,
                origin.longitude,
                _navigationDestination.Latitude,
                _navigationDestination.Longitude);
            double bearing = BearingDegrees(
                origin.latitude,
                origin.longitude,
                _navigationDestination.Latitude,
                _navigationDestination.Longitude);
            float worldNorthYaw =
                _camera.transform.eulerAngles.y - Input.compass.trueHeading;
            Vector3 direction = Quaternion.Euler(
                0f, worldNorthYaw + (float)bearing, 0f) * Vector3.forward;
            direction.y = 0f;
            direction.Normalize();
            Vector3 start = _camera.transform.position +
                Vector3.down * 1.25f + direction * 0.8f;
            float visibleLength = Mathf.Clamp((float)distance, 2f, 18f);
            var points = new List<Dictionary<string, object>>();
            for (int i = 0; i < 12; i++)
                points.Add(Point(
                    start + direction * (visibleLength * i / 11f)));
            float sensorQuality = Mathf.Clamp01(
                1f - (origin.horizontalAccuracy - 3f) / 30f);
            float quality = Mathf.Clamp(sensorQuality, 0.7f, 0.92f);
            _intents.Emit(new UIIntent
            {
                UiIntentId = "xreal-direct-navigation",
                Producer = "ultralive",
                Component = "world_navigation",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(quality, DepthReady,
                    new Dictionary<string, object>
                    {
                        { "route_id", "direct-gps-" +
                            HashId(_navigationDestination.Name) },
                        { "destination", "CAP DIRECT — " +
                            _navigationDestination.Name },
                        { "eta", "GPS direct" },
                        { "distance_m", distance },
                        { "map_quality", quality },
                        { "route_quality", quality },
                        { "route_points", points },
                        { "navigation_mode", "direct_bearing" },
                        { "turn_by_turn", false },
                        { "gps_accuracy_m", origin.horizontalAccuracy },
                        { "heading_accuracy_deg",
                            Input.compass.headingAccuracy },
                    }),
                TruthLevel = "observed",
                Confidence = quality,
                Priority = 0.84,
                TtlMs = 3000,
                EvidenceRefs = new List<string>
                {
                    "android:gps",
                    "android:compass",
                    "android:geocoder:" +
                        HashId(_navigationDestination.Name),
                    "pose:xreal-head",
                },
            });
        }

        private void EmitNavigationUnavailable(string destination, string detail)
        {
            if (_intents == null) return;
            _intents.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = "xreal-navigation-unavailable-" + DateTime.UtcNow.Ticks,
                Producer = "ultralive",
                Component = "context_card",
                Anchor = new Dictionary<string, object>
                {
                    { "type", "head_locked" },
                    { "side", "left" },
                },
                Content = new Dictionary<string, object>
                {
                    { "kind", "navigation_unavailable" },
                    { "title", "NAVIGATION AR INDISPONIBLE" },
                    { "text", "GPS, boussole ou destination non qualifiés. " +
                        "Ouvre Maps pour « " + destination + " »." },
                    { "source", string.IsNullOrWhiteSpace(detail)
                        ? "XREAL spatial provider"
                        : detail },
                },
                TruthLevel = "observed",
                Confidence = 1.0,
                Priority = 0.9,
                TtlMs = 8000,
                EvidenceRefs = Evidence("xreal:navigation-failed"),
            });
        }

        private static double HaversineMeters(
            double lat1, double lon1, double lat2, double lon2)
        {
            const double radius = 6371000.0;
            double p1 = lat1 * Math.PI / 180.0;
            double p2 = lat2 * Math.PI / 180.0;
            double dp = (lat2 - lat1) * Math.PI / 180.0;
            double dl = (lon2 - lon1) * Math.PI / 180.0;
            double a = Math.Sin(dp / 2) * Math.Sin(dp / 2) +
                Math.Cos(p1) * Math.Cos(p2) *
                Math.Sin(dl / 2) * Math.Sin(dl / 2);
            return radius * 2.0 * Math.Atan2(
                Math.Sqrt(a), Math.Sqrt(1.0 - a));
        }

        private static double BearingDegrees(
            double lat1, double lon1, double lat2, double lon2)
        {
            double p1 = lat1 * Math.PI / 180.0;
            double p2 = lat2 * Math.PI / 180.0;
            double dl = (lon2 - lon1) * Math.PI / 180.0;
            double y = Math.Sin(dl) * Math.Cos(p2);
            double x = Math.Cos(p1) * Math.Sin(p2) -
                Math.Sin(p1) * Math.Cos(p2) * Math.Cos(dl);
            return (Math.Atan2(y, x) * 180.0 / Math.PI + 360.0) % 360.0;
        }
#endif

        private void SetLocalCapabilities(bool depthReady)
        {
            if (_features == null) return;
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.WorldLabels, depthReady);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.WorldStyling,
                depthReady && _freeGuyMeshMaterial != null);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.TrajectoryForecast, depthReady);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.EventVision, depthReady);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.ArMeasurement, depthReady);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.SpatialKeyboard, depthReady);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.DepthOcclusion,
                depthReady && _depthOcclusionMaterial != null);
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.PersistentAnchors,
                depthReady && AnchorProviderReady());
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.BallisticPreview,
                depthReady && HandProviderReady());
#if UNITY_ANDROID && !UNITY_EDITOR
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.RadioField,
                depthReady && RadioPermissionReady(
                    request: _features.IsSelected(
                        AugmentedRealityFeatureRegistry.RadioField)));
#else
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.RadioField,
                false);
#endif
            // Street navigation still needs a calibrated route provider; it is
            // advertised only by StartNavigation once origin + route are proven.
            _features.SetLocalCapability(
                AugmentedRealityFeatureRegistry.StreetNavigation,
                _navigationDestination != null && NavigationSensorsReady());
        }

        private void SampleCurrentWifi()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!PoseTracked() || !RadioPermissionReady(request: false)) return;
            try
            {
                using var player =
                    new AndroidJavaClass("com.unity3d.player.UnityPlayer");
                using AndroidJavaObject activity =
                    player.GetStatic<AndroidJavaObject>("currentActivity");
                using AndroidJavaObject context =
                    activity.Call<AndroidJavaObject>("getApplicationContext");
                using AndroidJavaObject wifi =
                    context.Call<AndroidJavaObject>("getSystemService", "wifi");
                using AndroidJavaObject info =
                    wifi.Call<AndroidJavaObject>("getConnectionInfo");
                string bssid = info?.Call<string>("getBSSID");
                int rssi = info?.Call<int>("getRssi") ?? -127;
                if (
                    string.IsNullOrWhiteSpace(bssid) ||
                    bssid == "02:00:00:00:00:00" ||
                    rssi < -120 || rssi > -10)
                    return;
                Vector3 position = _pose.Latest.Position;
                if (
                    _radioSamples.Count > 0 &&
                    Vector3.Distance(
                        _radioSamples[_radioSamples.Count - 1].Position,
                        position) < 0.35f)
                    return;
                _radioSamples.Add(new RadioSample
                {
                    Position = position,
                    Rssi = rssi,
                    Id = "radio-" + HashId(bssid),
                });
                while (_radioSamples.Count > 24) _radioSamples.RemoveAt(0);
                if (_radioSamples.Count >= 2) EmitRadioField();
            }
            catch (Exception ex)
            {
                LastProviderError = "radio_permission_or_api:" + ex.GetType().Name;
                _features?.SetLocalCapability(
                    AugmentedRealityFeatureRegistry.RadioField, false);
            }
#endif
        }

#if UNITY_ANDROID && !UNITY_EDITOR
        private static bool RadioPermissionReady(bool request)
        {
            const string location = "android.permission.ACCESS_FINE_LOCATION";
            const string nearby = "android.permission.NEARBY_WIFI_DEVICES";
            bool locationReady =
                UnityEngine.Android.Permission.HasUserAuthorizedPermission(location);
            bool nearbyReady =
                UnityEngine.Android.Permission.HasUserAuthorizedPermission(nearby);
            if (request)
            {
                if (!locationReady)
                    UnityEngine.Android.Permission.RequestUserPermission(location);
                if (!nearbyReady)
                    UnityEngine.Android.Permission.RequestUserPermission(nearby);
            }
            // Android versions before 13 do not expose NEARBY_WIFI_DEVICES.
            int sdk = 0;
            try
            {
                using var version =
                    new AndroidJavaClass("android.os.Build$VERSION");
                sdk = version.GetStatic<int>("SDK_INT");
            }
            catch
            {
                return false;
            }
            return locationReady && (sdk < 33 || nearbyReady);
        }
#endif

        private void EmitRadioField()
        {
            var samples = new List<Dictionary<string, object>>();
            foreach (RadioSample sample in _radioSamples)
            {
                samples.Add(new Dictionary<string, object>
                {
                    { "position", Point(sample.Position) },
                    { "rssi_dbm", sample.Rssi },
                    { "source", "wifi" },
                    { "network_id", sample.Id },
                });
            }
            _intents?.Emit(new UIIntent
            {
                Type = "ui_intent",
                ContractsVersion = ContractDefaults.Version,
                UiIntentId = "xreal-radio-field",
                Producer = "ultralive",
                Component = "world_radio",
                Anchor = TrackingAnchor(),
                Content = SpatialContent(0.72f, false, new Dictionary<string, object>
                {
                    { "pseudonymized", true },
                    { "samples", samples },
                }),
                TruthLevel = "observed",
                Confidence = 0.72,
                Priority = 0.56,
                TtlMs = 12000,
                EvidenceRefs = Evidence("android:wifi-rssi"),
            });
        }

        private static Dictionary<string, object> TrackingAnchor() =>
            new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
            };

        private static Dictionary<string, object> SpatialContent(
            float quality,
            bool depth,
            Dictionary<string, object> additions)
        {
            var content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "depth_valid", depth },
                { "calibration_id", CalibrationId },
                { "spatial_quality", quality },
            };
            foreach (KeyValuePair<string, object> item in additions)
                content[item.Key] = item.Value;
            return content;
        }

        private static Dictionary<string, object> Point(Vector3 p) =>
            new Dictionary<string, object>
            {
                { "x", p.x },
                { "y", p.y },
                { "z", p.z },
            };

        private static List<Dictionary<string, object>> Interpolate(
            Vector3 a, Vector3 b, int count)
        {
            var points = new List<Dictionary<string, object>>();
            for (int i = 0; i < count; i++)
                points.Add(Point(Vector3.Lerp(a, b, i / (count - 1f))));
            return points;
        }

        private static Dictionary<string, object> Path(
            string id,
            float probability,
            float quality,
            List<Dictionary<string, object>> points) =>
            new Dictionary<string, object>
            {
                { "path_id", id },
                { "probability", probability },
                { "quality", Mathf.Clamp01(quality) },
                { "points", points },
            };

        private static List<string> Evidence(string value) =>
            new List<string>
            {
                string.IsNullOrWhiteSpace(value) ? "xreal:live" : value,
                "pose:xreal-head",
                "depth:xreal-mesh",
            };

        private static bool TryViewportPoint(
            Dictionary<string, object> entity,
            SceneDelta delta,
            out Vector2 viewport)
        {
            viewport = default;
            if (!entity.TryGetValue("bbox", out object raw) || raw == null)
                return false;
            Newtonsoft.Json.Linq.JArray box;
            try
            {
                box = raw as Newtonsoft.Json.Linq.JArray ??
                    Newtonsoft.Json.Linq.JArray.FromObject(raw);
            }
            catch
            {
                return false;
            }
            if (box.Count < 4) return false;
            float x1 = (float)box[0];
            float y1 = (float)box[1];
            float x2 = (float)box[2];
            float y2 = (float)box[3];
            if (x2 <= x1 || y2 <= y1) return false;
            float width = delta.FrameWidth.Value;
            float height = delta.FrameHeight.Value;
            // Detector pixels use a top-left origin. Unity viewport rays use
            // bottom-left; feet/bottom-center are more stable for people while
            // the centre remains appropriate for compact objects.
            string kind = ReadString(entity, "kind");
            float y = string.Equals(kind, "person", StringComparison.OrdinalIgnoreCase)
                ? y2
                : (y1 + y2) * 0.5f;
            viewport = new Vector2(
                Mathf.Clamp01(((x1 + x2) * 0.5f) / width),
                Mathf.Clamp01(1f - y / height));
            return true;
        }

        private static string ReadString(
            Dictionary<string, object> values, string key) =>
            values != null &&
            values.TryGetValue(key, out object raw) &&
            raw != null
                ? raw.ToString()
                : string.Empty;

        private static double ReadNumber(
            Dictionary<string, object> values,
            string key,
            double fallback)
        {
            if (
                values == null ||
                !values.TryGetValue(key, out object raw) ||
                raw == null)
                return fallback;
            return double.TryParse(
                raw.ToString(),
                System.Globalization.NumberStyles.Float,
                System.Globalization.CultureInfo.InvariantCulture,
                out double value)
                ? value
                : fallback;
        }

        private static string NormaliseMarkerKind(string kind)
        {
            string value = (kind ?? string.Empty).Trim().ToLowerInvariant();
            return value == "person" ? "person" :
                value == "sign" ? "sign" :
                value == "storefront" ? "storefront" :
                "object";
        }

        private static string HashId(string value)
        {
            using SHA256 sha = SHA256.Create();
            byte[] bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(value ?? ""));
            var text = new StringBuilder(12);
            for (int i = 0; i < 6; i++) text.Append(bytes[i].ToString("x2"));
            return text.ToString();
        }

        private static Type FindType(string fullName)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                Type type = assembly.GetType(fullName, false);
                if (type != null) return type;
            }
            return null;
        }

        private static Component FindBehaviour(Type type)
        {
            foreach (MonoBehaviour behaviour in
                FindObjectsByType<MonoBehaviour>(FindObjectsSortMode.None))
            {
                if (behaviour != null && type.IsInstanceOfType(behaviour))
                    return behaviour;
            }
            return null;
        }

        private static void SetMember(object target, string name, object value)
        {
            if (target == null) return;
            Type type = target.GetType();
            PropertyInfo property = type.GetProperty(
                name,
                BindingFlags.Instance | BindingFlags.Public |
                BindingFlags.NonPublic | BindingFlags.IgnoreCase);
            if (property != null && property.CanWrite)
            {
                property.SetValue(target, value);
                return;
            }
            FieldInfo field = type.GetField(
                "m_" + char.ToUpperInvariant(name[0]) + name.Substring(1),
                BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic);
            field?.SetValue(target, value);
        }

        private sealed class TrackHistory
        {
            public bool HasValue;
            public Vector3 Previous;
            public Vector3 Position;
            public float At;
            public string Label;
            public string Kind;
        }

        private sealed class KeyboardPlacement
        {
            public Vector3 Origin;
            public Vector3 Right;
            public Vector3 Forward;
            public Vector3 Normal;
            public float Width;
            public float Height;
        }

        private sealed class RadioSample
        {
            public Vector3 Position;
            public float Rssi;
            public string Id;
        }

        private sealed class GeoDestination
        {
            public string Name;
            public double Latitude;
            public double Longitude;
        }
    }

    /// <summary>Marker copied by ARMeshManager onto every generated mesh.</summary>
    public sealed class XrealSpatialMeshTag : MonoBehaviour { }
}

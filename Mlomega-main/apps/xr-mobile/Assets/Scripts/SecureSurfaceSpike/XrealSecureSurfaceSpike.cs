using System;
using System.Collections;
using System.Runtime.InteropServices;
using MLOmega.XR.UI;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace MLOmega.XR.SecureSurfaceSpike
{
    /// <summary>
    /// Isolated feasibility probe for Android protected video composition through
    /// XREAL SDK 3.1. It deliberately does not share package state or build output
    /// with Product, Atelier or the validated Browser Lab.
    ///
    /// A public Widevine sample is decoded by Android Media3 into the protected
    /// Android Surface. This validates a legitimate secure-composition path
    /// without extracting, weakening or bypassing DRM.
    /// </summary>
    public sealed class XrealSecureSurfaceSpike : MonoBehaviour
    {
        private const string Tag = "[SECURE-SURFACE-SPIKE]";
        private const int LayerId = 9107;
        private const string WidevineManifest =
            "https://storage.googleapis.com/shaka-demo-assets/sintel-widevine/dash.mpd";
        private const string WidevineLicense =
            "https://cwip-shaka-proxy.appspot.com/no_auth";
        private const string WidevineBridge =
            "com.mlomega.xr.securesurface.SecureWidevinePlayer";

        [StructLayout(LayoutKind.Explicit, Size = 96, Pack = 4)]
        private struct QuadCompositionLayer
        {
            [FieldOffset(0)] public int layerId;
            [FieldOffset(4)] public int compositionOrder;
            [FieldOffset(8)] public int pixelWidth;
            [FieldOffset(12)] public int pixelHeight;
            [FieldOffset(16)] public int format;
            [FieldOffset(20)] public byte cropEnabled;
            [FieldOffset(24)] public float viewportX;
            [FieldOffset(28)] public float viewportY;
            [FieldOffset(32)] public float viewportWidth;
            [FieldOffset(36)] public float viewportHeight;
            [FieldOffset(40)] public float sourceX;
            [FieldOffset(44)] public float sourceY;
            [FieldOffset(48)] public float sourceWidth;
            [FieldOffset(52)] public float sourceHeight;
            [FieldOffset(56)] public byte poseValid;
            [FieldOffset(60)] public float positionX;
            [FieldOffset(64)] public float positionY;
            [FieldOffset(68)] public float positionZ;
            [FieldOffset(72)] public float rotationX;
            [FieldOffset(76)] public float rotationY;
            [FieldOffset(80)] public float rotationZ;
            [FieldOffset(84)] public float rotationW;
            [FieldOffset(88)] public float widthMeters;
            [FieldOffset(92)] public float heightMeters;
        }

#if UNITY_ANDROID && !UNITY_EDITOR
        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void SetPersistentProtect();

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void CreateDisplayLayer();

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern IntPtr CreateQuadSurfaceLayer(
            ref QuadCompositionLayer layer,
            [MarshalAs(UnmanagedType.I1)] bool useProtectedContent,
            [MarshalAs(UnmanagedType.I1)] bool useSrgb);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void SetActiveCompositionLayer(int layerId);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void ModifyQuadCompositionLayer(
            ref QuadCompositionLayer layer);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void RemoveCompositionLayer(int layerId);
#endif

        private AndroidJavaObject _surface;
        private AndroidJavaClass _widevine;
        private AndroidJavaObject _activity;
        private bool _layerCreated;
        private bool _windowVisible;
        private Camera _xrCamera;
        private WorldCreatorController _creator;
        private RectTransform _windowRect;
        private RectTransform _videoRect;
        private QuadCompositionLayer _layer;
        private readonly Vector3[] _videoCorners = new Vector3[4];
        private string _status = "initialisation XR";
        private float _nextStatusPoll;

        private void OnEnable()
        {
            Application.onBeforeRender += SubmitProtectedLayer;
        }

        private void OnDisable()
        {
            Application.onBeforeRender -= SubmitProtectedLayer;
        }

        private IEnumerator Start()
        {
            Debug.Log(Tag + " runtime started; waiting for XREAL compositor");
#if UNITY_ANDROID && !UNITY_EDITOR
            yield return new WaitForSecondsRealtime(3f);
            BuildSpatialVideoWindow();
            CreateProtectedVideoLayer();
#else
            BuildSpatialVideoWindow();
            _status = "ERREUR: test Android uniquement";
            Debug.LogError(Tag + " Android player required");
            yield break;
#endif
        }

        private void CreateProtectedVideoLayer()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                _layer = new QuadCompositionLayer
                {
                    layerId = LayerId,
                    compositionOrder = 10,
                    pixelWidth = 1280,
                    pixelHeight = 720,
                    format = 1,
                    cropEnabled = 0,
                    poseValid = 1,
                    positionX = 0f,
                    positionY = 0f,
                    positionZ = 2.2f,
                    rotationX = 0f,
                    rotationY = 0f,
                    rotationZ = 0f,
                    rotationW = 1f,
                    widthMeters = 1.6f,
                    heightMeters = 0.9f,
                };
                UpdateLayerPoseFromWorldWindow();

                SetPersistentProtect();
                CreateDisplayLayer();
                IntPtr nativeSurface = CreateQuadSurfaceLayer(
                    ref _layer,
                    true,
                    false);
                if (nativeSurface == IntPtr.Zero)
                {
                    Fail("CreateQuadSurfaceLayer returned NULL");
                    return;
                }

                _layerCreated = true;
                SetActiveCompositionLayer(LayerId);
                Debug.Log(Tag + " protected XREAL quad created; surface=" + nativeSurface);

                _surface = new AndroidJavaObject(nativeSurface);
                using (var unityPlayer = new AndroidJavaClass(
                           "com.unity3d.player.UnityPlayer"))
                {
                    _activity = unityPlayer.GetStatic<AndroidJavaObject>(
                        "currentActivity");
                }

                _widevine = new AndroidJavaClass(WidevineBridge);
                _widevine.CallStatic(
                    "start",
                    _activity,
                    _surface,
                    WidevineManifest,
                    WidevineLicense);
                _status = "WIDEVINE: demarrage";
                Debug.Log(Tag + " Widevine Media3 started on protected XREAL surface");
            }
            catch (Exception ex)
            {
                Fail(ex.GetType().Name + ": " + ex.Message);
            }
#endif
        }

        private void Update()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_widevine == null || Time.unscaledTime < _nextStatusPoll) return;
            _nextStatusPoll = Time.unscaledTime + 0.5f;
            try
            {
                string value = _widevine.CallStatic<string>("getStatus");
                if (!string.IsNullOrWhiteSpace(value) && value != _status)
                {
                    _status = value;
                    Debug.Log(Tag + " " + value);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " status poll: " + ex.Message);
            }
#endif
        }

        private void SubmitProtectedLayer()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            // XREAL clears OverlayBase::active while preparing every XR frame.
            // Submit immediately before rendering so the layer cannot be cleared
            // by an asynchronous 60 Hz XR frame between ordinary Update calls.
            if (_layerCreated && _windowVisible &&
                _windowRect != null && _windowRect.gameObject.activeInHierarchy)
            {
                // XREAL surface quads use a view-relative compositor pose. Keep a
                // Unity world-space target and counter-transform the latest head
                // pose immediately before submission. This makes protected video
                // world-locked without ever copying protected pixels into Unity.
                UpdateLayerPoseFromWorldWindow();
                ModifyQuadCompositionLayer(ref _layer);
                SetActiveCompositionLayer(LayerId);
            }
#endif
        }

        private void UpdateLayerPoseFromWorldWindow()
        {
            if (_xrCamera == null || _videoRect == null) return;

            _videoRect.GetWorldCorners(_videoCorners);
            Vector3 worldPosition =
                (_videoCorners[0] + _videoCorners[1] +
                 _videoCorners[2] + _videoCorners[3]) * 0.25f;
            float worldWidth = Vector3.Distance(
                _videoCorners[0], _videoCorners[3]);
            float worldHeight = Vector3.Distance(
                _videoCorners[0], _videoCorners[1]);

            Transform view = _xrCamera.transform;
            Vector3 positionInView = view.InverseTransformPoint(
                worldPosition);
            Quaternion rotationInView = Quaternion.Inverse(view.rotation) *
                                        _videoRect.rotation;

            _layer.positionX = positionInView.x;
            _layer.positionY = positionInView.y;
            _layer.positionZ = positionInView.z;
            _layer.rotationX = rotationInView.x;
            _layer.rotationY = rotationInView.y;
            _layer.rotationZ = rotationInView.z;
            _layer.rotationW = rotationInView.w;
            _layer.widthMeters = Mathf.Max(0.2f, worldWidth);
            _layer.heightMeters = Mathf.Max(0.12f, worldHeight);
        }

        private void BuildSpatialVideoWindow()
        {
            _xrCamera = Camera.main ?? FindAnyObjectByType<Camera>();
            if (_xrCamera == null) return;

            var root = new GameObject("Secure Widevine spatial window");
            Canvas canvas = root.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = _xrCamera;
            canvas.sortingOrder = 240;
            root.AddComponent<GraphicRaycaster>();
            _windowRect = root.GetComponent<RectTransform>();
            _windowRect.sizeDelta = new Vector2(1120f, 760f);
            _windowRect.localScale = Vector3.one * 0.0012f;

            Vector3 forward = _xrCamera.transform.forward.normalized;
            _windowRect.SetPositionAndRotation(
                _xrCamera.transform.position + forward * 1.45f,
                Quaternion.LookRotation(forward, Vector3.up));

            Image frame = MakeImage(
                _windowRect,
                "Secure video glass",
                Vector2.zero,
                _windowRect.sizeDelta,
                new Color(0.035f, 0.045f, 0.06f, 0.82f));
            frame.raycastTarget = true;
            Image header = MakeImage(
                _windowRect,
                "Secure video header",
                new Vector2(0f, 334f),
                new Vector2(1080f, 72f),
                new Color(0.10f, 0.12f, 0.15f, 0.94f));
            header.raycastTarget = true;
            MakeLabel(
                header.rectTransform,
                "Video securisee  •  Widevine",
                new Vector2(-280f, 0f),
                new Vector2(480f, 42f),
                22f);

            var video = new GameObject("Protected native video area");
            video.transform.SetParent(_windowRect, false);
            _videoRect = video.AddComponent<RectTransform>();
            LayoutVideoArea();

            _creator = FindAnyObjectByType<WorldCreatorController>();
            if (_creator != null)
            {
                _creator.RegisterExternalSpatialWindow(
                    _windowRect,
                    "secure.widevine.video",
                    CloseSpatialVideoWindow,
                    ApplySpatialWindowSize);
                _creator.FocusExternalSpatialWindow(_windowRect);
            }
            else
            {
                Debug.LogWarning(Tag + " Atelier window controller unavailable");
            }
            _windowVisible = true;
        }

        private void ApplySpatialWindowSize(Vector2 requested, bool final)
        {
            if (_windowRect == null) return;
            _windowRect.sizeDelta = new Vector2(
                Mathf.Clamp(requested.x, 620f, 1800f),
                Mathf.Clamp(requested.y, 420f, 1200f));
            LayoutVideoArea();
            if (final) Debug.Log(Tag + " secure window resized " + _windowRect.sizeDelta);
        }

        private void LayoutVideoArea()
        {
            if (_windowRect == null || _videoRect == null) return;
            Vector2 size = _windowRect.sizeDelta;
            _videoRect.anchorMin = _videoRect.anchorMax = new Vector2(0.5f, 0.5f);
            _videoRect.anchoredPosition = new Vector2(0f, -42f);
            _videoRect.sizeDelta = new Vector2(
                Mathf.Max(560f, size.x - 60f),
                Mathf.Max(315f, size.y - 164f));
        }

        private void CloseSpatialVideoWindow()
        {
            _windowVisible = false;
            if (_creator != null && _windowRect != null)
                _creator.UnregisterExternalSpatialWindow(_windowRect);
            if (_windowRect != null) _windowRect.gameObject.SetActive(false);
        }

        private static Image MakeImage(
            RectTransform parent,
            string name,
            Vector2 position,
            Vector2 size,
            Color color)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            Image image = go.AddComponent<Image>();
            image.color = color;
            RectTransform rect = image.rectTransform;
            rect.anchorMin = rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            return image;
        }

        private static TextMeshProUGUI MakeLabel(
            RectTransform parent,
            string text,
            Vector2 position,
            Vector2 size,
            float fontSize)
        {
            var go = new GameObject("Secure video title");
            go.transform.SetParent(parent, false);
            TextMeshProUGUI label = go.AddComponent<TextMeshProUGUI>();
            label.text = text;
            label.fontSize = fontSize;
            label.color = new Color(0.90f, 0.94f, 1f, 0.98f);
            label.alignment = TextAlignmentOptions.Left;
            label.raycastTarget = false;
            RectTransform rect = label.rectTransform;
            rect.anchorMin = rect.anchorMax = new Vector2(0.5f, 0.5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            return label;
        }

        private void Fail(string reason)
        {
            _status = "ERREUR: " + reason;
            Debug.LogError(Tag + " " + reason);
        }

        private void OnGUI()
        {
            var style = new GUIStyle(GUI.skin.label)
            {
                fontSize = 28,
                normal = { textColor = Color.cyan },
            };
            GUI.Label(new Rect(24, 24, 1200, 100),
                "XREAL SECURE SURFACE - " + _status,
                style);
        }

        private void OnDestroy()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                if (_widevine != null && _activity != null)
                    _widevine.CallStatic("release", _activity);
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " Widevine cleanup: " + ex.Message);
            }
            if (_layerCreated)
            {
                try { RemoveCompositionLayer(LayerId); }
                catch (Exception ex)
                {
                    Debug.LogWarning(Tag + " layer cleanup: " + ex.Message);
                }
            }
#endif
            if (_creator != null && _windowRect != null)
                _creator.UnregisterExternalSpatialWindow(_windowRect);
            _widevine?.Dispose();
            _activity?.Dispose();
            _surface?.Dispose();
            _widevine = null;
            _activity = null;
            _surface = null;
        }
    }
}

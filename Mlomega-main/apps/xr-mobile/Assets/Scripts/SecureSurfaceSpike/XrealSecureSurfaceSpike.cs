using System;
using System.Collections;
using System.Runtime.InteropServices;
using System.Threading;
using MLOmega.XR.UI;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
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
        private const int LegacyLayerId = 9107;
        private const int FirstMultiLayerId = 9200;
        private const string WidevineManifest =
            "https://storage.googleapis.com/shaka-demo-assets/sintel-widevine/dash.mpd";
        private const string WidevineLicense =
            "https://cwip-shaka-proxy.appspot.com/no_auth";
        private const string YoutubeHome = "https://www.youtube.com/";
        private const string YoutubePackage = "com.google.android.youtube";
        private const string WidevineBridge =
            "com.mlomega.xr.securesurface.SecureWidevinePlayer";
        private const string MultiAppBridge =
            "com.mlomega.xr.securesurface.MultiAppDisplayBridge";
        private static int _nextMultiIdentity;

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
        private static extern IntPtr CreateProjectionSurfaceLayer(
            ref QuadCompositionLayer layer,
            int sourceComponent,
            [MarshalAs(UnmanagedType.I1)] bool useProtectedContent,
            [MarshalAs(UnmanagedType.I1)] bool useSrgb);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void SetActiveCompositionLayer(int layerId);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void ModifyQuadCompositionLayer(
            ref QuadCompositionLayer layer);

        [DllImport("XREALXRPlugin", CallingConvention = CallingConvention.Cdecl)]
        private static extern void ModifyProjectionCompositionLayer(
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
        private string _startupPackageName = YoutubePackage;
        private string _startupUri = YoutubeHome;
        private string _startupLabel = "YouTube";
        private bool _labHosted;
        private bool _runtimeReleased;
        private bool _useMultiSession;
        private int _sessionId;
        private int _layerId = LegacyLayerId;
        private int _initialSlot;

        public event Action<XrealSecureSurfaceSpike> Closed;
        public event Action<XrealSecureSurfaceSpike> Focused;
        public RectTransform WindowRect => _windowRect;
        public string HostedPackage => _startupPackageName;
        public string HostedLabel => _startupLabel;
        public bool UsesCommercialCinema => !_useMultiSession;
        public bool IsWindowVisible =>
            _windowVisible && _windowRect != null &&
            _windowRect.gameObject.activeInHierarchy;

        public void ConfigureLabApplication(
            string packageName,
            string launchUri,
            string label,
            int initialSlot = 0)
        {
            _labHosted = true;
            _startupPackageName = string.IsNullOrWhiteSpace(packageName)
                ? YoutubePackage
                : packageName.Trim();
            _startupUri = (launchUri ?? string.Empty).Trim();
            _startupLabel = string.IsNullOrWhiteSpace(label)
                ? _startupPackageName
                : label.Trim();
            _initialSlot = Mathf.Max(0, initialSlot);
            _useMultiSession = !IsCommercialPackage(_startupPackageName);
            if (_useMultiSession)
            {
                int identity = Interlocked.Increment(ref _nextMultiIdentity);
                _sessionId = identity;
                _layerId = FirstMultiLayerId + identity;
            }
            else
            {
                _sessionId = 0;
                _layerId = LegacyLayerId;
            }
        }

        public static bool IsCommercialPackage(string packageName) =>
            string.Equals(packageName, "com.netflix.mediaclient", StringComparison.Ordinal) ||
            string.Equals(packageName, "com.amazon.avod.thirdpartyclient", StringComparison.Ordinal) ||
            (!string.IsNullOrWhiteSpace(packageName) &&
             packageName.IndexOf("canal", StringComparison.OrdinalIgnoreCase) >= 0);

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
                    layerId = _layerId,
                    compositionOrder = _useMultiSession ? 11 + (_sessionId % 8) : 10,
                    pixelWidth = 1920,
                    pixelHeight = 1080,
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
                // v14 baseline: the Android application is rendered into the
                // protected XREAL Quad while Unity retains the world-space
                // window, controls and session. DRM playback later hands the
                // physical panel to Android without replacing this path.
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
                SetActiveCompositionLayer(_layerId);
                Debug.Log(Tag + " protected XREAL quad created; surface=" + nativeSurface);

                _surface = new AndroidJavaObject(nativeSurface);
                using (var unityPlayer = new AndroidJavaClass(
                           "com.unity3d.player.UnityPlayer"))
                {
                    _activity = unityPlayer.GetStatic<AndroidJavaObject>(
                        "currentActivity");
                }

                _widevine = new AndroidJavaClass(
                    _useMultiSession ? MultiAppBridge : WidevineBridge);
                if (_useMultiSession)
                {
                    _widevine.CallStatic(
                        "startApplicationDisplay",
                        _sessionId,
                        _activity,
                        _surface,
                        _layer.pixelWidth,
                        _layer.pixelHeight,
                        240,
                        _startupPackageName,
                        _startupUri);
                }
                else
                {
                    _widevine.CallStatic(
                        "startApplicationDisplay",
                        _activity,
                        _surface,
                        _layer.pixelWidth,
                        _layer.pixelHeight,
                        240,
                        _startupPackageName,
                        _startupUri);
                }
                _status = _startupLabel + ": demarrage application";
                Debug.Log(Tag + " " + _startupLabel +
                          " display started on protected XREAL surface");
            }
            catch (Exception ex)
            {
                Fail(ex.GetType().Name + ": " + ex.Message);
            }
#endif
        }

        /// <summary>
        /// Called by the Android cinema bridge after the XREAL panel has returned
        /// from 2D system-mirror mode to the 3D compositor. The DP switch destroys
        /// the native protected quad surface, but the trusted VirtualDisplay and
        /// its Android task remain alive. Recreate only the native quad and bind
        /// that existing display to it so Netflix returns at the exact browse/
        /// detail position it had before cinema mode.
        /// </summary>
        public void OnCinemaReturned(string ignored)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_useMultiSession) return;
            StartCoroutine(ReattachProtectedVideoLayer());
#endif
        }

        private IEnumerator ReattachProtectedVideoLayer()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            // NRXRActivity has already been relaunched by Android. Leave one XR
            // frame boundary for XREALXRPlugin to recreate its display layer.
            yield return new WaitForSecondsRealtime(0.25f);

            AndroidJavaObject previousSurface = _surface;
            AndroidJavaObject replacementSurface = null;
            try
            {
                if (_layerCreated)
                {
                    RemoveCompositionLayer(_layerId);
                    _layerCreated = false;
                }

                UpdateLayerPoseFromWorldWindow();
                SetPersistentProtect();
                CreateDisplayLayer();
                IntPtr nativeSurface = CreateQuadSurfaceLayer(
                    ref _layer,
                    true,
                    false);
                if (nativeSurface == IntPtr.Zero)
                    throw new InvalidOperationException(
                        "cinema return CreateQuadSurfaceLayer returned NULL");

                replacementSurface = new AndroidJavaObject(nativeSurface);
                bool attached = _widevine != null && _widevine.CallStatic<bool>(
                    "reattachTrustedSurface",
                    replacementSurface,
                    _layer.pixelWidth,
                    _layer.pixelHeight);
                if (!attached)
                {
                    RemoveCompositionLayer(_layerId);
                    throw new InvalidOperationException(
                        "cinema return trusted surface reattach refused");
                }

                _surface = replacementSurface;
                replacementSurface = null;
                _layerCreated = true;
                SetActiveCompositionLayer(_layerId);
                _status = "MLOMEGA 3D: application restauree";
                Debug.Log(Tag + " protected quad recreated after cinema; Android task preserved");
            }
            catch (Exception ex)
            {
                Fail("cinema return " + ex.GetType().Name + ": " + ex.Message);
            }
            finally
            {
                replacementSurface?.Dispose();
                if (!ReferenceEquals(previousSurface, _surface))
                    previousSurface?.Dispose();
            }
#else
            yield break;
#endif
        }

        private void Update()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_widevine == null || Time.unscaledTime < _nextStatusPoll) return;
            _nextStatusPoll = Time.unscaledTime + 0.5f;
            try
            {
                string value = _useMultiSession
                    ? _widevine.CallStatic<string>("getStatus", _sessionId)
                    : _widevine.CallStatic<string>("getStatus");
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
                // Preserve the validated world lock while the navigation window
                // is active. In cinema mode Android temporarily owns the panel;
                // this state keeps running and is restored on return.
                UpdateLayerPoseFromWorldWindow();
                ModifyQuadCompositionLayer(ref _layer);
                SetActiveCompositionLayer(_layerId);
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

            var root = new GameObject("Secure Android app spatial window");
            Canvas canvas = root.AddComponent<Canvas>();
            canvas.renderMode = RenderMode.WorldSpace;
            canvas.worldCamera = _xrCamera;
            canvas.sortingOrder = 240;
            root.AddComponent<GraphicRaycaster>();
            _windowRect = root.GetComponent<RectTransform>();
            // The Android display itself is the window. Keep the default at
            // 16:9 and leave transient handles to WorldCreatorController.
            // Invisible 36 px interaction gutter around a 1120x630 (16:9)
            // native surface. The compositor otherwise covers Unity handles.
            _windowRect.sizeDelta = new Vector2(1192f, 702f);
            _windowRect.localScale = Vector3.one * 0.0012f;

            Vector3 forward = _xrCamera.transform.forward.normalized;
            float[] initialOffsets = { 0f, .62f, -.62f };
            float initialX = initialOffsets[
                Mathf.Clamp(_initialSlot, 0, initialOffsets.Length - 1)];
            _windowRect.SetPositionAndRotation(
                _xrCamera.transform.position +
                forward * (1.45f + Mathf.Abs(initialX) * .10f) +
                _xrCamera.transform.right * initialX,
                Quaternion.LookRotation(forward, Vector3.up));

            Image frame = MakeImage(
                _windowRect,
                "Secure video glass",
                Vector2.zero,
                _windowRect.sizeDelta,
                Color.clear);
            frame.raycastTarget = false;
            frame.rectTransform.anchorMin = Vector2.zero;
            frame.rectTransform.anchorMax = Vector2.one;
            frame.rectTransform.offsetMin = Vector2.zero;
            frame.rectTransform.offsetMax = Vector2.zero;
            Image header = MakeImage(
                _windowRect,
                "Secure video header",
                new Vector2(0f, 334f),
                new Vector2(1080f, 72f),
                new Color(0.10f, 0.12f, 0.15f, 0.94f));
            header.raycastTarget = true;
            MakeLabel(
                header.rectTransform,
                _startupLabel + "  •  application Android spatiale",
                new Vector2(-280f, 0f),
                new Vector2(480f, 42f),
                22f);
            header.gameObject.SetActive(false);

            var video = new GameObject("Protected native video area");
            video.transform.SetParent(_windowRect, false);
            _videoRect = video.AddComponent<RectTransform>();
            Image videoHitSurface = video.AddComponent<Image>();
            videoHitSurface.color = Color.clear;
            videoHitSurface.raycastTarget = true;
            var appPointer = video.AddComponent<SecureAndroidAppPointer>();
            appPointer.Configure(
                _videoRect,
                new Vector2Int(1920, 1080),
                _useMultiSession,
                _sessionId,
                NotifyFocused);
            LayoutVideoArea();
            MakeTopActionHandle(
                _windowRect, -84f, "\u25B2", SecureAndroidAppAction.ScrollUp, appPointer);
            MakeTopActionHandle(
                _windowRect, -28f, "\u25BC", SecureAndroidAppAction.ScrollDown, appPointer);
            MakeTopActionHandle(
                _windowRect, 28f, "\u2328", SecureAndroidAppAction.Keyboard, appPointer);
            if (!_useMultiSession)
            {
                MakeTopActionHandle(
                    _windowRect, 84f, "TV", SecureAndroidAppAction.Cinema, appPointer);
            }

            _creator = FindAnyObjectByType<WorldCreatorController>();
            if (_creator != null)
            {
                _creator.RegisterExternalSpatialWindow(
                    _windowRect,
                    "secure.android." + _startupPackageName,
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

        private void NotifyFocused()
        {
            if (_creator != null && _windowRect != null)
                _creator.FocusExternalSpatialWindow(_windowRect);
            Focused?.Invoke(this);
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
            _videoRect.anchoredPosition = Vector2.zero;
            _videoRect.sizeDelta = new Vector2(
                Mathf.Max(560f, size.x - 72f),
                Mathf.Max(315f, size.y - 72f));
        }

        private void CloseSpatialVideoWindow()
        {
            _windowVisible = false;
            if (_creator != null && _windowRect != null)
                _creator.UnregisterExternalSpatialWindow(_windowRect);
            if (!_labHosted)
            {
                if (_windowRect != null) _windowRect.gameObject.SetActive(false);
                return;
            }

            RectTransform closedWindow = _windowRect;
            _windowRect = null;
            _videoRect = null;
            ReleaseHostedApplication();
            if (closedWindow != null) Destroy(closedWindow.gameObject);
            Closed?.Invoke(this);
            Destroy(this);
        }

        public void CloseHostedWindow() => CloseSpatialVideoWindow();

        public void ReleaseHostedApplication()
        {
            if (_runtimeReleased) return;
            _runtimeReleased = true;
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                if (_widevine != null && _activity != null)
                {
                    if (_useMultiSession)
                        _widevine.CallStatic(
                            "releaseAndStop", _activity, _sessionId);
                    else
                        _widevine.CallStatic("releaseAndStop", _activity);
                }
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " hosted app cleanup: " + ex.Message);
            }
            if (_layerCreated)
            {
                try { RemoveCompositionLayer(_layerId); }
                catch (Exception ex)
                {
                    Debug.LogWarning(Tag + " layer cleanup: " + ex.Message);
                }
                _layerCreated = false;
            }
#endif
            _surface?.Dispose();
            _surface = null;
        }

        public bool SendHostedText(string text)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_widevine == null || string.IsNullOrEmpty(text)) return false;
            try
            {
                return _useMultiSession
                    ? _widevine.CallStatic<bool>("inputText", _sessionId, text)
                    : _widevine.CallStatic<bool>("inputText", text);
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " hosted text: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
        }

        public bool SendHostedKey(int keyCode)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_widevine == null) return false;
            try
            {
                return _useMultiSession
                    ? _widevine.CallStatic<bool>("inputKey", _sessionId, keyCode)
                    : _widevine.CallStatic<bool>("inputKey", keyCode);
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " hosted key: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
        }

        public bool ClearHostedText()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_widevine == null) return false;
            try
            {
                return _useMultiSession
                    ? _widevine.CallStatic<bool>("clearText", _sessionId)
                    : _widevine.CallStatic<bool>("clearText");
            }
            catch (Exception ex)
            {
                Debug.LogWarning(Tag + " hosted clear: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
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

        private static void MakeTopActionHandle(
            RectTransform parent,
            float x,
            string glyph,
            SecureAndroidAppAction action,
            SecureAndroidAppPointer pointer)
        {
            Image handle = MakeImage(
                parent,
                "Android app " + action,
                Vector2.zero,
                new Vector2(42f, 28f),
                new Color(.12f, .15f, .19f, .78f));
            RectTransform rect = handle.rectTransform;
            rect.anchorMin = rect.anchorMax = new Vector2(.5f, 1f);
            rect.anchoredPosition = new Vector2(x, -18f);
            handle.raycastTarget = true;
            TextMeshProUGUI label = MakeLabel(
                rect,
                glyph,
                Vector2.zero,
                new Vector2(34f, 24f),
                18f);
            label.alignment = TextAlignmentOptions.Center;
            var control = handle.gameObject.AddComponent<SecureAndroidAppActionHandle>();
            control.Configure(handle, pointer, action);
        }

        private void Fail(string reason)
        {
            _status = "ERREUR: " + reason;
            Debug.LogError(Tag + " " + reason);
        }

        private void OnGUI()
        {
            // The successful path is deliberately chrome-free. Diagnostics stay
            // in logcat; only a fatal probe error may overlay the optical view.
            if (string.IsNullOrEmpty(_status) ||
                (!_status.StartsWith("ERREUR", StringComparison.Ordinal) &&
                 _status.IndexOf("EXCEPTION", StringComparison.OrdinalIgnoreCase) < 0))
                return;
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
            ReleaseHostedApplication();
            if (_creator != null && _windowRect != null)
                _creator.UnregisterExternalSpatialWindow(_windowRect);
            _widevine?.Dispose();
            _activity?.Dispose();
            _widevine = null;
            _activity = null;
            _surface = null;
        }
    }

    public enum SecureAndroidAppAction
    {
        YouTube,
        Netflix,
        ScrollUp,
        ScrollDown,
        Keyboard,
        Cinema,
    }

    public sealed class SecureAndroidAppActionHandle : MonoBehaviour,
        IPointerEnterHandler,
        IPointerExitHandler,
        IPointerClickHandler
    {
        private Image _image;
        private CanvasGroup _group;
        private SecureAndroidAppPointer _pointer;
        private SecureAndroidAppAction _action;

        public void Configure(
            Image image,
            SecureAndroidAppPointer pointer,
            SecureAndroidAppAction action)
        {
            _image = image;
            _pointer = pointer;
            _action = action;
            _group = gameObject.AddComponent<CanvasGroup>();
            _group.alpha = 0f;
            _group.interactable = true;
            _group.blocksRaycasts = true;
        }

        public void OnPointerEnter(PointerEventData eventData)
        {
            if (_image != null)
                _image.color = new Color(.78f, .84f, .92f, .94f);
            if (_group != null) _group.alpha = 1f;
        }

        public void OnPointerExit(PointerEventData eventData)
        {
            if (_image != null)
                _image.color = new Color(.12f, .15f, .19f, .78f);
            if (_group != null) _group.alpha = 0f;
        }

        public void OnPointerClick(PointerEventData eventData)
        {
            if (_pointer == null) return;
            switch (_action)
            {
                case SecureAndroidAppAction.YouTube:
                    _pointer.LaunchYouTube();
                    break;
                case SecureAndroidAppAction.Netflix:
                    _pointer.LaunchNetflix();
                    break;
                case SecureAndroidAppAction.Keyboard:
                    _pointer.OpenKeyboard();
                    break;
                case SecureAndroidAppAction.Cinema:
                    _pointer.EnterCinemaMode();
                    break;
                default:
                    _pointer.ScrollPage(
                        _action == SecureAndroidAppAction.ScrollUp ? -1 : 1);
                    break;
            }
        }
    }

    /// <summary>
    /// Converts the already-proven Atelier gaze/pinch pointer into Android touch
    /// coordinates for the app hosted on the Shizuku virtual display. Kept in
    /// this isolated spike so Product, Atelier and Browser Lab remain untouched.
    /// </summary>
    public sealed class SecureAndroidAppPointer : MonoBehaviour,
        IPointerEnterHandler,
        IPointerExitHandler,
        IPointerDownHandler,
        IPointerUpHandler,
        IPointerClickHandler,
        IDragHandler
    {
        private const string Tag = "[SECURE-ANDROID-POINTER]";
        private const string Bridge =
            "com.mlomega.xr.securesurface.SecureWidevinePlayer";
        private const string MultiBridge =
            "com.mlomega.xr.securesurface.MultiAppDisplayBridge";

        private RectTransform _contentRect;
        private Vector2Int _displayPixels;
        private AndroidJavaClass _bridge;
        private Camera _camera;
        private Vector2Int _lastPoint;
        private Vector2Int _lastRawPoint;
        private Vector2Int _downRawPoint;
        private float _rawDragDistance;
        private float _nextHoverAt;
        private bool _down;
        private bool _dragStarted;
        private bool _actionRunning;
        private bool _multiSession;
        private int _sessionId;
        private Action _focused;

        public void Configure(
            RectTransform contentRect,
            Vector2Int displayPixels,
            bool multiSession,
            int sessionId,
            Action focused)
        {
            _contentRect = contentRect;
            _displayPixels = displayPixels;
            _multiSession = multiSession;
            _sessionId = sessionId;
            _focused = focused;
            _camera = Camera.main;
#if UNITY_ANDROID && !UNITY_EDITOR
            try
            {
                _bridge = new AndroidJavaClass(
                    _multiSession ? MultiBridge : Bridge);
            }
            catch (Exception ex)
            {
                Debug.LogError(Tag + " bridge unavailable: " + ex.Message);
            }
#endif
        }

        public void OnPointerEnter(PointerEventData eventData) { }

        public void OnPointerExit(PointerEventData eventData)
        {
            ReleasePointer();
        }

        public void OnPointerDown(PointerEventData eventData)
        {
            _focused?.Invoke();
            _lastPoint = DisplayPoint(eventData);
            _lastRawPoint = _lastPoint;
            _downRawPoint = _lastPoint;
            _rawDragDistance = 0f;
            _dragStarted = false;
            _down = Send("pointerDown", _lastPoint);
        }

        public void OnDrag(PointerEventData eventData)
        {
            if (!_down) return;
            Vector2Int raw = DisplayPoint(eventData);
            Vector2Int delta = raw - _lastRawPoint;
            _lastRawPoint = raw;
            Vector2Int displacement = raw - _downRawPoint;
            _rawDragDistance = displacement.magnitude;
            // Cumulative jitter used to turn a stationary pinch into a scroll.
            // Require a real displacement from the original down point.
            if (!_dragStarted && _rawDragDistance < 26f) return;
            if (!_dragStarted)
            {
                _dragStarted = true;
                delta = raw - _downRawPoint;
            }
            _lastPoint = AmplifiedPoint(_lastPoint, delta);
            if (!Send("pointerMove", _lastPoint))
                Debug.LogWarning(Tag + " move injection rejected");
        }

        public void OnPointerUp(PointerEventData eventData)
        {
            if (!_down) return;
            if (!_dragStarted) _lastPoint = _downRawPoint;
            Send("pointerUp", _lastPoint);
            _down = false;
            _dragStarted = false;
        }

        // Required by the shared world-space target resolver. Android receives
        // the actual gesture through down/move/up above, so no second tap here.
        public void OnPointerClick(PointerEventData eventData) { }

        public void ScrollPage(int direction)
        {
            if (!_down) StartCoroutine(ScrollPageRoutine(direction));
        }

        public void OpenKeyboard()
        {
            _focused?.Invoke();
            SendNoCoordinates("openKeyboard");
        }

        public void EnterCinemaMode()
        {
            if (_multiSession) return;
            SendNoCoordinates("enterCinemaMode");
        }

        public void LaunchYouTube()
        {
            LaunchApp("com.google.android.youtube", "https://www.youtube.com/");
        }

        public void LaunchNetflix()
        {
            LaunchApp("com.netflix.mediaclient", "https://www.netflix.com/browse");
        }

        private void Update()
        {
            if (_down || _actionRunning || Time.unscaledTime < _nextHoverAt ||
                _contentRect == null || !_contentRect.gameObject.activeInHierarchy)
                return;
            _nextHoverAt = Time.unscaledTime + (1f / 30f);
            if (_camera == null) _camera = Camera.main;
            if (_camera == null) return;
            Ray gaze = _camera.ViewportPointToRay(new Vector3(.5f, .5f, 0f));
            var plane = new Plane(_contentRect.forward, _contentRect.position);
            if (!plane.Raycast(gaze, out float distance)) return;
            Vector3 world = gaze.GetPoint(distance);
            Vector3 local = _contentRect.InverseTransformPoint(world);
            if (!_contentRect.rect.Contains(new Vector2(local.x, local.y))) return;
            Vector2Int point = DisplayPoint(world);
            if ((point - _lastPoint).sqrMagnitude < 4) return;
            _lastPoint = point;
            Send("pointerHover", point);
        }

        private Vector2Int DisplayPoint(PointerEventData eventData)
        {
            if (_contentRect == null || eventData == null)
                return Vector2Int.zero;
            return DisplayPoint(eventData.pointerCurrentRaycast.worldPosition);
        }

        private Vector2Int DisplayPoint(Vector3 world)
        {
            if (_contentRect == null) return Vector2Int.zero;
            Vector3 local = _contentRect.InverseTransformPoint(world);
            Rect rect = _contentRect.rect;
            float nx = Mathf.Clamp01(local.x / rect.width + _contentRect.pivot.x);
            float ny = 1f - Mathf.Clamp01(
                local.y / rect.height + _contentRect.pivot.y);
            return new Vector2Int(
                Mathf.Clamp(
                    Mathf.RoundToInt(nx * (_displayPixels.x - 1)),
                    0,
                    _displayPixels.x - 1),
                Mathf.Clamp(
                    Mathf.RoundToInt(ny * (_displayPixels.y - 1)),
                    0,
                    _displayPixels.y - 1));
        }

        private Vector2Int AmplifiedPoint(Vector2Int point, Vector2Int delta) =>
            new Vector2Int(
                Mathf.Clamp(
                    point.x + Mathf.RoundToInt(delta.x * 3.0f),
                    0,
                    _displayPixels.x - 1),
                Mathf.Clamp(
                    point.y + Mathf.RoundToInt(delta.y * 4.2f),
                    0,
                    _displayPixels.y - 1));

        private IEnumerator ScrollPageRoutine(int direction)
        {
            _actionRunning = true;
            Vector2Int start = new Vector2Int(
                _displayPixels.x / 2,
                direction < 0 ? _displayPixels.y / 3 : _displayPixels.y * 2 / 3);
            Vector2Int end = new Vector2Int(
                start.x,
                direction < 0 ? _displayPixels.y * 5 / 6 : _displayPixels.y / 6);
            if (!Send("pointerDown", start))
            {
                _actionRunning = false;
                yield break;
            }
            for (int i = 1; i <= 8; i++)
            {
                Vector2 point = Vector2.Lerp(start, end, i / 8f);
                _lastPoint = Vector2Int.RoundToInt(point);
                Send("pointerMove", _lastPoint);
                yield return null;
            }
            Send("pointerUp", end);
            _lastPoint = end;
            _actionRunning = false;
        }

        private bool Send(string method, Vector2Int point)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_bridge == null) return false;
            try
            {
                return _multiSession
                    ? _bridge.CallStatic<bool>(
                        method, _sessionId, (float)point.x, (float)point.y)
                    : _bridge.CallStatic<bool>(
                        method, (float)point.x, (float)point.y);
            }
            catch (Exception ex)
            {
                Debug.LogError(Tag + " " + method + " failed: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
        }

        private bool SendNoCoordinates(string method)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_bridge == null) return false;
            try
            {
                return _multiSession
                    ? _bridge.CallStatic<bool>(method, _sessionId)
                    : _bridge.CallStatic<bool>(method);
            }
            catch (Exception ex)
            {
                Debug.LogError(Tag + " " + method + " failed: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
        }

        private bool LaunchApp(string packageName, string uri)
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (_bridge == null) return false;
            if (_multiSession) return false;
            try { return _bridge.CallStatic<bool>("launchApp", packageName, uri); }
            catch (Exception ex)
            {
                Debug.LogError(Tag + " launch " + packageName + " failed: " + ex.Message);
                return false;
            }
#else
            return true;
#endif
        }

        private void ReleasePointer()
        {
            if (!_down) return;
            Send("pointerUp", _lastPoint);
            _down = false;
            _dragStarted = false;
        }

        private void OnDisable()
        {
            if (_actionRunning)
            {
                Send("pointerUp", _lastPoint);
                _actionRunning = false;
            }
            ReleasePointer();
        }

        private void OnDestroy()
        {
            ReleasePointer();
            _bridge?.Dispose();
            _bridge = null;
        }
    }
}

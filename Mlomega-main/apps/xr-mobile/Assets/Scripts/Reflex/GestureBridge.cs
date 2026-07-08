// MLOmega V19 — E26
// Unity-side bridge to the native Android gesture pipeline
// (com.mlomega.xr.reflexvision.GesturePipeline, MediaPipe HandLandmarker +
// GestureRecognizer). Owns the AndroidJavaObject, activates/deactivates it on
// demand for the ReflexScheduler (battery — §9.4), feeds the eye/phone texture
// from EyeCaptureSource.OnFrame up the pipeline, and re-emits recognised gestures
// as C# events on the main thread.
//
// Editor / Windows dev has no Android plugin, so a REAL simulated recogniser runs
// instead (keyboard/mouse): so the whole reflex chain (LensWindow zoom, menu,
// hide-UI) can be developed and tested without a device. Same DIRECT_ANDROID /
// editor-sim split as LiveTransportBridge (DECISIONS §E24/§E26).
using System;
using System.Collections.Generic;
using MLOmega.Contracts.V19;
using MLOmega.XR.Core;
using UnityEngine;

namespace MLOmega.XR.Reflex
{
    /// <summary>A recognised gesture surfaced to the reflex layer (main thread).</summary>
    public readonly struct GestureEvent
    {
        public readonly GestureKind Kind;
        public readonly float ZoomFactor;
        public readonly Vector2 ScreenPoint; // normalised 0..1; (-1,-1) if n/a
        public readonly long TimestampMs;

        public GestureEvent(GestureKind kind, float zoom, Vector2 point, long tsMs)
        {
            Kind = kind;
            ZoomFactor = zoom;
            ScreenPoint = point;
            TimestampMs = tsMs;
        }
    }

    public sealed class GestureBridge : MonoBehaviour
    {
        [SerializeField] private EyeCaptureSource _capture;

        [Tooltip("Relative path (under getExternalFilesDir()/models) of the MediaPipe " +
                 "gesture .task bundle. Provisioned at first run (E47), not shipped in the APK.")]
        [SerializeField] private string _modelRelativePath = "models/gesture_recognizer.task";

        [Tooltip("Max hands tracked (1 keeps latency lowest).")]
        [Min(1)]
        [SerializeField] private int _numHands = 1;

        [Tooltip("Longest side (px) the capture texture is downscaled to before the " +
                 "native gesture graph. 256 is plenty for hand landmarks and keeps the " +
                 "GPU readback + JNI Bitmap copy cheap. Never full capture resolution.")]
        [Min(64)]
        [SerializeField] private int _maxDimension = 256;

        [Tooltip("Target gesture cadence (fps), clamped 10-15 on the native side. The " +
                 "capture texture arrives at up to 30 fps; we only sample this often " +
                 "(battery, §9.4). The native FrameThrottle is authoritative; this gates " +
                 "the GPU readback so we do not even pay for dropped frames.")]
        [Range(10f, 15f)]
        [SerializeField] private float _targetFps = 12f;

        /// <summary>Raised on the main thread for each recognised gesture.</summary>
        public event Action<GestureEvent> GestureRecognized;

        /// <summary>Whether the native/simulated pipeline is currently running.</summary>
        public bool IsRunning { get; private set; }

        private readonly Queue<Action> _mainThreadQueue = new Queue<Action>();
        private readonly object _queueLock = new object();

        // Client-side readback gate: skip the GPU readback for frames the native
        // throttle would drop anyway, so downscale + Bitmap copy only run 10-15x/s.
        private float _readbackAccum;
        private float _readbackPeriod;

#if UNITY_ANDROID && !UNITY_EDITOR
        private AndroidJavaObject _pipeline;
        private GestureProxy _proxy;
        private Texture2D _readback;      // reused downscaled ARGB readback target
        private AndroidJavaObject _bitmap; // reused native ARGB_8888 Bitmap
        private int[] _argbBuffer;         // reused packed-ARGB scratch for setPixels
        private int _bitmapW, _bitmapH;
#endif

        private void Awake()
        {
            if (_capture == null) _capture = FindAnyObjectByType<EyeCaptureSource>();
            _readbackPeriod = _targetFps > 0f ? 1f / _targetFps : 0f;
        }

        private void OnEnable()
        {
            if (_capture != null) _capture.OnFrame += HandleFrame;
        }

        private void OnDisable()
        {
            if (_capture != null) _capture.OnFrame -= HandleFrame;
            Deactivate();
        }

        private void Update()
        {
            DrainMainThread();
#if UNITY_EDITOR
            if (IsRunning) SimulateFromInput();
#endif
        }

        /// <summary>
        /// Feed one capture frame to the native gesture graph. Only runs while the
        /// recogniser is active (ReflexScheduler on-demand — §9.4); throttled to the
        /// gesture cadence and downscaled so we never read back at full res/30 fps.
        /// No-op in the editor (the simulator drives gestures from input instead).
        /// </summary>
        private void HandleFrame(Texture texture, FrameEnvelope envelope)
        {
            if (!IsRunning || texture == null) return;

            // Client-side cadence gate: avoid the GPU readback for frames the native
            // FrameThrottle would drop. period == 0 means feed every frame.
            _readbackAccum += Time.unscaledDeltaTime;
            if (_readbackPeriod > 0f && _readbackAccum < _readbackPeriod) return;
            _readbackAccum = 0f;

#if UNITY_ANDROID && !UNITY_EDITOR
            long tsMs = envelope != null ? envelope.CaptureMonotonicNs / 1_000_000L : 0L;
            PushDownscaledFrame(texture, tsMs);
#endif
        }

        /// <summary>
        /// Activate the recogniser. Called by the ReflexScheduler when a
        /// gesture-relevant signal is active. Idempotent.
        /// </summary>
        public void Activate()
        {
            if (IsRunning) return;
            IsRunning = true;
            _readbackAccum = _readbackPeriod; // feed the first frame immediately
#if UNITY_ANDROID && !UNITY_EDITOR
            // E48-A: the MediaPipe .task bundle may still be provisioning (or absent);
            // native construction then throws. Reset IsRunning so the scheduler retries
            // later / next launch once the model lands — honest degraded, no crash.
            try
            {
                StartAndroid();
            }
            catch (Exception ex)
            {
                IsRunning = false;
                Debug.LogWarning($"[GestureBridge] activation deferred (model not ready?): {ex.Message}");
            }
#else
            Debug.Log("[GestureBridge] editor: simulated gestures (mouse wheel = pinch zoom, " +
                      "M = menu, H = hide).");
#endif
        }

        /// <summary>Deactivate the recogniser (tears down the native graph — §9.4). Idempotent.</summary>
        public void Deactivate()
        {
            if (!IsRunning) return;
            IsRunning = false;
#if UNITY_ANDROID && !UNITY_EDITOR
            _pipeline?.Call("stop");
            ReleaseBitmap();
#endif
        }

        // --- native plumbing ------------------------------------------------------

#if UNITY_ANDROID && !UNITY_EDITOR
        private void StartAndroid()
        {
            using var activity = new AndroidJavaClass("com.unity3d.player.UnityPlayer")
                .GetStatic<AndroidJavaObject>("currentActivity");
            using var ctx = activity.Call<AndroidJavaObject>("getApplicationContext");

            // Models are provisioned to getExternalFilesDir()/models at first run
            // (E47), never shipped in the APK. getExternalFilesDir(null) is the
            // app-private external files dir (no permission required).
            using var extDir = ctx.Call<AndroidJavaObject>("getExternalFilesDir", (object)null);
            string filesDir = extDir != null
                ? extDir.Call<string>("getAbsolutePath")
                : ctx.Call<AndroidJavaObject>("getFilesDir").Call<string>("getAbsolutePath");
            string modelPath = filesDir + "/" + _modelRelativePath;

            var cfg = new AndroidJavaClass("com.mlomega.xr.reflexvision.GestureConfigFactory")
                .CallStatic<AndroidJavaObject>("forUnity", modelPath, _numHands, _targetFps);
            _proxy = new GestureProxy(this);
            _pipeline = new AndroidJavaObject(
                "com.mlomega.xr.reflexvision.GesturePipeline", ctx, cfg, _proxy);
            _pipeline.Call("start");
        }

        /// <summary>
        /// Downscale the capture texture to at most <see cref="_maxDimension"/> on its
        /// longest side, read it back to CPU, pack it into a reused ARGB_8888 Android
        /// Bitmap over JNI, and hand it to the native <c>GesturePipeline.pushFrame</c>.
        /// The native FrameThrottle drops anything above the gesture cadence, so this
        /// pushes at most ~15 fps of small frames — never full res, never 30 fps.
        /// </summary>
        private void PushDownscaledFrame(Texture source, long timestampMs)
        {
            if (_pipeline == null) return;

            int sw = source.width, sh = source.height;
            if (sw <= 0 || sh <= 0) return;
            int longSide = Mathf.Max(sw, sh);
            float scale = longSide > _maxDimension ? (float)_maxDimension / longSide : 1f;
            int w = Mathf.Max(1, Mathf.RoundToInt(sw * scale));
            int h = Mathf.Max(1, Mathf.RoundToInt(sh * scale));

            // Blit into a small temporary RT (GPU downscale), then read that back.
            var rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
            var previous = RenderTexture.active;
            Graphics.Blit(source, rt);
            RenderTexture.active = rt;
            if (_readback == null || _readback.width != w || _readback.height != h)
            {
                if (_readback != null) Destroy(_readback);
                _readback = new Texture2D(w, h, TextureFormat.RGBA32, false);
            }
            _readback.ReadPixels(new Rect(0, 0, w, h), 0, 0, false);
            _readback.Apply(false, false);
            RenderTexture.active = previous;
            RenderTexture.ReleaseTemporary(rt);

            EnsureBitmap(w, h);
            if (_bitmap == null) return;

            // Pack RGBA32 -> Android's packed-int ARGB_8888 (0xAARRGGBB), flipping
            // vertically because ReadPixels is bottom-up but Bitmap rows are top-down.
            Color32[] px = _readback.GetPixels32();
            if (_argbBuffer == null || _argbBuffer.Length != w * h)
                _argbBuffer = new int[w * h];
            for (int y = 0; y < h; y++)
            {
                int srcRow = (h - 1 - y) * w;
                int dstRow = y * w;
                for (int x = 0; x < w; x++)
                {
                    Color32 c = px[srcRow + x];
                    _argbBuffer[dstRow + x] =
                        (c.a << 24) | (c.r << 16) | (c.g << 8) | c.b;
                }
            }

            _bitmap.Call("setPixels", _argbBuffer, 0, w, 0, 0, w, h);
            _pipeline.Call("pushFrame", _bitmap, timestampMs);
        }

        private void EnsureBitmap(int w, int h)
        {
            if (_bitmap != null && _bitmapW == w && _bitmapH == h) return;
            ReleaseBitmap();
            using var cfg = new AndroidJavaClass("android.graphics.Bitmap$Config")
                .GetStatic<AndroidJavaObject>("ARGB_8888");
            _bitmap = new AndroidJavaClass("android.graphics.Bitmap")
                .CallStatic<AndroidJavaObject>("createBitmap", w, h, cfg);
            _bitmapW = w;
            _bitmapH = h;
        }

        private void ReleaseBitmap()
        {
            if (_bitmap != null)
            {
                try { _bitmap.Call("recycle"); } catch { /* best-effort */ }
                _bitmap.Dispose();
                _bitmap = null;
            }
            _bitmapW = _bitmapH = 0;
        }

        internal void EnqueueMainThread(Action a) { lock (_queueLock) { _mainThreadQueue.Enqueue(a); } }
#endif

        internal void OnNativeGesture(string kindName, float zoom, float x, float y, long tsMs)
        {
            GestureKind kind = MapKind(kindName);
            Enqueue(() => GestureRecognized?.Invoke(
                new GestureEvent(kind, zoom, new Vector2(x, y), tsMs)));
        }

        internal void OnNativeError(string message) =>
            Debug.LogWarning($"[GestureBridge] native error: {message}");

        private static GestureKind MapKind(string name) => name switch
        {
            "PINCH_BEGIN" => GestureKind.PinchBegin,
            "PINCH_UPDATE" => GestureKind.PinchUpdate,
            "PINCH_END" => GestureKind.PinchEnd,
            "OPEN_PALM_MENU" => GestureKind.OpenPalmMenu,
            "SWIPE_HIDE" => GestureKind.SwipeHide,
            _ => GestureKind.PinchUpdate
        };

        private void Enqueue(Action a) { lock (_queueLock) { _mainThreadQueue.Enqueue(a); } }

        private void DrainMainThread()
        {
            while (true)
            {
                Action work = null;
                lock (_queueLock) { if (_mainThreadQueue.Count > 0) work = _mainThreadQueue.Dequeue(); }
                if (work == null) break;
                try { work(); } catch (Exception ex) { Debug.LogError($"[GestureBridge] {ex}"); }
            }
        }

        // --- editor simulation (real input, not a stub) ---------------------------

#if UNITY_EDITOR
        private bool _simPinching;
        private float _simZoom = 1f;

        private void SimulateFromInput()
        {
            long now = (long)(Time.unscaledTimeAsDouble * 1000.0);
            Vector2 pt = new Vector2(0.5f, 0.5f);

            // Mouse wheel drives a pinch zoom: first scroll begins, subsequent update, release with right-click.
            float wheel = Input.mouseScrollDelta.y;
            if (Mathf.Abs(wheel) > 0.01f)
            {
                _simZoom = Mathf.Clamp(_simZoom + wheel * 0.4f, 1f, 6f);
                if (!_simPinching)
                {
                    _simPinching = true;
                    RaiseSim(GestureKind.PinchBegin, _simZoom, pt, now);
                }
                else
                {
                    RaiseSim(GestureKind.PinchUpdate, _simZoom, pt, now);
                }
            }
            if (_simPinching && Input.GetMouseButtonDown(1))
            {
                _simPinching = false;
                _simZoom = 1f;
                RaiseSim(GestureKind.PinchEnd, 1f, pt, now);
            }
            if (Input.GetKeyDown(KeyCode.M)) RaiseSim(GestureKind.OpenPalmMenu, 0f, pt, now);
            if (Input.GetKeyDown(KeyCode.H)) RaiseSim(GestureKind.SwipeHide, 0f, pt, now);
        }

        private void RaiseSim(GestureKind kind, float zoom, Vector2 pt, long tsMs) =>
            GestureRecognized?.Invoke(new GestureEvent(kind, zoom, pt, tsMs));
#endif

        /// <summary>
        /// Directly inject a gesture (used by EditMode tests and the demo driver to
        /// prove the reflex chain without any device/native pipeline).
        /// </summary>
        public void InjectGesture(GestureEvent ev) => GestureRecognized?.Invoke(ev);

#if UNITY_ANDROID && !UNITY_EDITOR
        private sealed class GestureProxy : AndroidJavaProxy
        {
            private readonly GestureBridge _bridge;
            public GestureProxy(GestureBridge b)
                : base("com.mlomega.xr.reflexvision.GestureCallbacks") { _bridge = b; }

            void onGesture(AndroidJavaObject kind, float zoom, float x, float y, long tsMs)
            {
                string name = kind != null ? kind.Call<string>("name") : "PINCH_UPDATE";
                _bridge.OnNativeGesture(name, zoom, x, y, tsMs);
            }
            void onError(string message) => _bridge.OnNativeError(message);
        }
#endif
    }
}

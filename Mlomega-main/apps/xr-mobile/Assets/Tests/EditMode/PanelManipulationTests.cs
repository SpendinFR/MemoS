// MLOmega V19 — E59 EditMode tests (hand window management)
// The PanelManipulator turns the pinch stream into direct manipulation of the video
// window (VirtualScreen) and opt-in cards, WITHOUT ever stealing the existing
// pinch→LensWindow zoom: a pinch begun ON a manipulable panel grabs/resizes/closes
// it (and is claimed so the lens does not zoom); a pinch begun elsewhere is not
// claimed. Resize clamps + keeps the video aspect ratio; close/minimise/restore work;
// placement persists per type; object-anchored atoms are never manipulable.
//
// All deterministic: gestures are injected by hand (no device), Camera + world-space
// raycasts drive the hit-test. Awake does not run for AddComponent in EditMode, so we
// build panels via Configure/Admit (their real init path) exactly like the 59 existing
// EditMode tests, and reflect the manipulator's serialized camera field.
using System.Collections.Generic;
using System.Reflection;
using MLOmega.Contracts.V19;
using MLOmega.XR.Reflex;
using MLOmega.XR.Scene;
using MLOmega.XR.UI.Components;
using NUnit.Framework;
using UnityEngine;
// TaskAtoms also declares a GestureKind (task trajectory kinds); alias its anchor
// component rather than `using` the whole namespace, so GestureKind stays the Reflex one.
using TaskAnchorComponent = MLOmega.XR.UI.Components.TaskAtoms.TaskAnchorComponent;

namespace MLOmega.XR.Tests
{
    public sealed class PanelManipulationTests
    {
        private readonly List<GameObject> _spawned = new List<GameObject>();
        private Camera _camera;

        [SetUp]
        public void SetUp()
        {
            ManipulablePanelRegistry.Clear();
            PanelPlacementStore.Reset();

            var camGo = New("Cam");
            _camera = camGo.AddComponent<Camera>();
            _camera.fieldOfView = 60f;
            _camera.aspect = 1f;
            camGo.transform.position = Vector3.zero;
            camGo.transform.rotation = Quaternion.identity; // looking +Z
        }

        [TearDown]
        public void TearDown()
        {
            foreach (GameObject go in _spawned) if (go != null) Object.DestroyImmediate(go);
            _spawned.Clear();
            ManipulablePanelRegistry.Clear();
            PanelPlacementStore.Reset();
        }

        private GameObject New(string name)
        {
            var go = new GameObject(name);
            _spawned.Add(go);
            return go;
        }

        private PanelManipulator MakeManipulator()
        {
            var go = New("PanelManipulator");
            var m = go.AddComponent<PanelManipulator>();
            typeof(PanelManipulator)
                .GetField("_camera", BindingFlags.NonPublic | BindingFlags.Instance)
                .SetValue(m, _camera);
            return m;
        }

        // Build a VirtualScreen the way the runtime does (Configure builds the panel,
        // Admit drives the lifecycle so Phase becomes non-Idle and it registers). The
        // transform is overridden to a known flat-facing world spot for the hit-test.
        private VirtualScreen MakeVirtualScreen(Vector3 pos)
        {
            VirtualScreen vs = AdmitVirtualScreen();
            vs.PanelTransform.SetPositionAndRotation(pos, Quaternion.LookRotation(Vector3.forward, Vector3.up));
            Pump(vs);
            return vs;
        }

        // Admit a VirtualScreen WITHOUT overriding its transform (used to observe the
        // runtime's own placement — e.g. remembered-placement restore).
        private VirtualScreen AdmitVirtualScreen()
        {
            var go = New("virtual_screen");
            var vs = go.AddComponent<VirtualScreen>();
            vs.Configure(new UIComponentContext(null, null, _camera), null);
            vs.Admit(ScreenIntent(), null, _ => { });
            return vs;
        }

        // Drive the component's deterministic lifecycle until it is Visible + registered.
        private void Pump(UIComponentBase c)
        {
            for (int i = 0; i < 30; i++) c.Tick(0.02f * i, 0.02f);
            // Update() (which registers + re-places) does not run headlessly; call the
            // registration path directly through a Tick-equivalent: the component's own
            // Update registers, so invoke it via SendMessage-free reflection of Update.
            typeof(UIComponentBase).GetMethod("Update", BindingFlags.NonPublic | BindingFlags.Instance)
                ?.Invoke(c, null);
        }

        private static UIIntent ScreenIntent() => new UIIntent
        {
            ContractsVersion = "v19.0",
            UiIntentId = "vs-1",
            DeliveryId = "del-vs",
            Component = "virtual_screen",
            TruthLevel = "observed",
            Content = new Dictionary<string, object> { { "title", "Replay" } },
        };

        private GestureEvent Pinch(GestureKind kind, Vector2 viewport, long ts) =>
            new GestureEvent(kind, kind == GestureKind.PinchBegin ? 1.0f : 1.2f, viewport, ts);

        // Viewport point that rays onto the panel centre (or an offset in metres in the
        // panel's local X/Y plane).
        private Vector2 ViewportOnPanel(Transform panel, Vector2 localOffset)
        {
            Vector3 world = panel.TransformPoint(new Vector3(localOffset.x, localOffset.y, 0f));
            Vector3 vp = _camera.WorldToViewportPoint(world);
            return new Vector2(vp.x, vp.y);
        }

        // ---- grab-drag on the panel body -----------------------------------

        [Test]
        public void PinchOnBody_GrabsAndFollowsHand_AndClaimsThePinch()
        {
            PanelManipulator m = MakeManipulator();
            VirtualScreen vs = MakeVirtualScreen(new Vector3(0f, 0f, 3f));
            Assert.IsTrue(vs.IsManipulable);
            Vector3 before = vs.PanelTransform.position;

            // Begin on the body centre.
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, Vector2.zero), 0));
            Assert.IsTrue(m.HasClaim, "grab on the body must claim the pinch (no zoom)");
            Assert.AreEqual(ManipulationKind.Move, m.ActiveKind);
            Assert.AreSame(vs, m.ActivePanel);

            // Move the hand to the right (higher viewport x): the panel follows.
            Vector2 rightVp = ViewportOnPanel(vs.PanelTransform, new Vector2(0.25f, 0f));
            m.OnGesture(Pinch(GestureKind.PinchUpdate, rightVp, 100));
            Vector3 after = vs.PanelTransform.position;
            Assert.Greater(after.x, before.x, "panel must follow the hand to the right");

            m.OnGesture(Pinch(GestureKind.PinchEnd, rightVp, 200));
            Assert.IsFalse(m.HasClaim, "claim released on pinch end");
        }

        // ---- pinch elsewhere = existing zoom preserved ---------------------

        [Test]
        public void PinchOffPanel_IsNotClaimed_ZoomPreserved()
        {
            PanelManipulator m = MakeManipulator();
            MakeVirtualScreen(new Vector3(0f, 0f, 3f));

            // A pinch far to the side, missing the panel entirely.
            m.OnGesture(Pinch(GestureKind.PinchBegin, new Vector2(0.02f, 0.02f), 0));
            Assert.IsFalse(m.HasClaim, "pinch that misses every panel must NOT be claimed");
            Assert.IsNull(m.ActivePanel);
            Assert.AreEqual(ManipulationKind.None, m.ActiveKind);
        }

        // ---- resize by corner: clamp + aspect ratio ------------------------

        [Test]
        public void PinchOnCorner_Resizes_ClampsAndKeepsAspect()
        {
            PanelManipulator m = MakeManipulator();
            VirtualScreen vs = MakeVirtualScreen(new Vector3(0f, 0f, 3f));
            Vector2 size0 = vs.PanelSize;
            float aspect0 = size0.x / size0.y;

            // Begin on the BOTTOM-right corner handle (top corners are the ✕/– buttons).
            Vector2 corner = new Vector2(size0.x * 0.5f * 0.98f, -size0.y * 0.5f * 0.98f);
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, corner), 0));
            Assert.AreEqual(ManipulationKind.Resize, m.ActiveKind, "corner hit → resize");
            Assert.IsTrue(m.HasClaim);

            // Drag the corner far outward: size grows but clamps to MaxSize, aspect held.
            Vector2 farOut = new Vector2(size0.x * 4f, -size0.y * 4f);
            m.OnGesture(Pinch(GestureKind.PinchUpdate, ViewportOnPanel(vs.PanelTransform, farOut), 100));

            Vector2 size1 = vs.PanelSize;
            Assert.LessOrEqual(size1.x, vs.MaxSize.x + 1e-3f, "width clamped to max");
            Assert.LessOrEqual(size1.y, vs.MaxSize.y + 1e-3f, "height clamped to max");
            Assert.Greater(size1.x, size0.x, "resize grew the panel");
            Assert.AreEqual(aspect0, size1.x / size1.y, 0.02f, "video window keeps its aspect ratio");

            m.OnGesture(Pinch(GestureKind.PinchEnd, Vector2.zero, 200));
        }

        // ---- close / minimise / restore ------------------------------------

        [Test]
        public void PinchTapCloseButton_DismissesPanel()
        {
            PanelManipulator m = MakeManipulator();
            VirtualScreen vs = MakeVirtualScreen(new Vector3(0f, 0f, 3f));
            Vector2 size0 = vs.PanelSize;

            // Top-right button zone = ✕. Tap = quick begin→end.
            Vector2 xBtn = new Vector2(size0.x * 0.48f, size0.y * 0.48f);
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, xBtn), 0));
            m.OnGesture(Pinch(GestureKind.PinchEnd, ViewportOnPanel(vs.PanelTransform, xBtn), 50));

            // Dismissed → the component begins fading (Phase becomes Fading, then Idle).
            Assert.AreNotEqual(UIComponentPhase.Visible, vs.Phase,
                "a ✕ pinch-tap must dismiss (fade) the panel");
        }

        [Test]
        public void PinchTapMinimiseButton_ThenRestore()
        {
            PanelManipulator m = MakeManipulator();
            VirtualScreen vs = MakeVirtualScreen(new Vector3(0f, 0f, 3f));
            Vector2 size0 = vs.PanelSize;

            // The – button sits just left of ✕ in the top-right zone.
            float btn = Mathf.Min(size0.x, size0.y) * 0.16f;
            Vector2 minusLocal = new Vector2(size0.x * 0.5f - btn * 1.4f, size0.y * 0.5f - btn * 0.4f);
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, minusLocal), 0));
            m.OnGesture(Pinch(GestureKind.PinchEnd, ViewportOnPanel(vs.PanelTransform, minusLocal), 50));
            Assert.IsTrue(vs.IsMinimised, "– pinch-tap minimises to a pastille");
            Vector2 pastille = vs.PanelSize;
            Assert.Less(pastille.x, size0.x, "minimised panel collapses to a small pastille");

            // Pinch-tap the pastille to restore it.
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, Vector2.zero), 100));
            Assert.IsTrue(m.HasClaim, "pinch on the pastille is claimed (restore)");
            m.OnGesture(Pinch(GestureKind.PinchEnd, ViewportOnPanel(vs.PanelTransform, Vector2.zero), 130));
            Assert.IsFalse(vs.IsMinimised, "pinch-tap on the pastille restores the panel");
            Assert.AreEqual(size0.x, vs.PanelSize.x, 1e-3f, "restored to its previous size");
        }

        // ---- placement persistence -----------------------------------------

        [Test]
        public void DragThenReopen_RestoresRememberedPlacement()
        {
            PanelManipulator m = MakeManipulator();
            VirtualScreen vs = MakeVirtualScreen(new Vector3(0f, 0f, 3f));

            // Grab and drop at a new spot; End persists the placement per type.
            m.OnGesture(Pinch(GestureKind.PinchBegin, ViewportOnPanel(vs.PanelTransform, Vector2.zero), 0));
            Vector2 rightVp = ViewportOnPanel(vs.PanelTransform, new Vector2(0.3f, 0f));
            m.OnGesture(Pinch(GestureKind.PinchUpdate, rightVp, 100));
            Vector3 placed = vs.PanelTransform.position;
            m.OnGesture(Pinch(GestureKind.PinchEnd, rightVp, 200));

            Assert.IsTrue(PanelPlacementStore.TryGet(vs.PersistenceKey, out PanelPlacement saved),
                "placement is remembered per panel type on drop");
            Assert.AreEqual(placed.x, saved.Position.x, 1e-3f);

            // A freshly opened virtual screen reads back the remembered placement in its
            // own Place() (Bind path), without any manipulator override.
            VirtualScreen vs2 = AdmitVirtualScreen();
            Assert.AreEqual(saved.Position.x, vs2.PanelTransform.position.x, 1e-2f,
                "re-opened panel returns to the remembered position");
        }

        // ---- object-anchored atoms are NEVER manipulable -------------------

        [Test]
        public void ObjectAnchoredAtom_IsNotManipulable()
        {
            // A cache + task_anchor: it follows the world, so it must not appear in the
            // manipulable registry and a pinch over it must not be claimed.
            var cacheGo = New("SceneCache");
            var cache = cacheGo.AddComponent<SceneCache>();
            typeof(SceneCache).GetField("_config", BindingFlags.NonPublic | BindingFlags.Instance)
                .SetValue(cache, SceneCacheConfig.CreateDefault());
            cache.Tick(0);

            var anchorGo = New("task_anchor");
            var anchor = anchorGo.AddComponent<TaskAnchorComponent>();
            anchor.Configure(new UIComponentContext(cache, null, _camera), null);

            Assert.IsFalse(anchor is IManipulablePanel,
                "object-anchored atoms must not implement IManipulablePanel (they follow the world)");
            Assert.AreEqual(0, ManipulablePanelRegistry.Panels.Count,
                "no object-anchored atom self-registers as manipulable");
        }

        // ---- opt-in card is manipulable only when flagged ------------------

        [Test]
        public void ContextCard_ManipulableOnlyWhenOptedIn()
        {
            var go = New("context_card");
            var card = go.AddComponent<ContextCard>();
            card.Configure(new UIComponentContext(null, null, _camera), null);
            var intent = new UIIntent
            {
                ContractsVersion = "v19.0", UiIntentId = "cc-1", DeliveryId = "d",
                Component = "context_card", TruthLevel = "probable",
                Content = new Dictionary<string, object> { { "title", "x" }, { "text", "y" } },
            };
            card.Admit(intent, null, _ => { });

            // Default (not opted-in) → not manipulable.
            Assert.IsFalse(card.IsManipulable, "a plain contextual card is not hand-manipulable by default");
        }
    }
}

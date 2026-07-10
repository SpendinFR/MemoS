// MLOmega V19 — E53 EditMode tests (Viki mode aide)
// The task-overlay renderers compose the right atoms from the FROZEN task_anchor /
// task_panel contract, follow the live track, degrade honestly when the track is
// lost, disambiguate multiple candidates, and promote the ghost step in place. All
// deterministic: SceneCache.Tick and the renderers' TickAtoms are driven by hand,
// mirroring the 59 existing EditMode tests — no running player loop.
using System.Collections.Generic;
using MLOmega.Contracts.V19;
using MLOmega.XR.Scene;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using MLOmega.XR.UI.Components.TaskAtoms;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class TaskAtomsCompositionTests
    {
        private readonly List<GameObject> _spawned = new List<GameObject>();
        private SceneCache _cache;
        private Camera _camera;

        [SetUp]
        public void SetUp()
        {
            var cacheGo = New("SceneCache");
            _cache = cacheGo.AddComponent<SceneCache>();
            // EditMode: Awake() does NOT run for plain AddComponent, so _config stays
            // null and Tick() would NRE. Mirror Awake by injecting the default config
            // via reflection (same pattern as ReflexOfflineTests' private-field setup).
            typeof(SceneCache)
                .GetField("_config", System.Reflection.BindingFlags.NonPublic | System.Reflection.BindingFlags.Instance)
                .SetValue(_cache, SceneCacheConfig.CreateDefault());
            _cache.Tick(0);

            var camGo = New("Cam");
            _camera = camGo.AddComponent<Camera>();
            camGo.transform.position = Vector3.zero;
            camGo.transform.rotation = Quaternion.identity;
        }

        [TearDown]
        public void TearDown()
        {
            foreach (GameObject go in _spawned) if (go != null) Object.DestroyImmediate(go);
            _spawned.Clear();
        }

        private GameObject New(string name)
        {
            var go = new GameObject(name);
            _spawned.Add(go);
            return go;
        }

        private UIComponentContext Ctx() => new UIComponentContext(_cache, null, _camera);

        private void SubmitTrack(string id, float x, float y, float w, float h, long nowMs)
        {
            _cache.SubmitLocalTrack(new LocalTrack
            {
                TrackId = id,
                Kind = "object",
                Visibility = 1.0,
                Confidence = 0.9,
                BboxOrMask = new Dictionary<string, object> { { "x", x }, { "y", y }, { "w", w }, { "h", h } }
            });
            _cache.Tick(nowMs); // drain ingress so the track is live
        }

        private TaskAnchorComponent MakeAnchor(UIIntent intent)
        {
            var go = New("task_anchor");
            var comp = go.AddComponent<TaskAnchorComponent>();
            comp.Configure(Ctx(), null);
            comp.Admit(intent, null, _ => { });
            return comp;
        }

        private static UIIntent AnchorIntent(Dictionary<string, object> content,
            string trackId = null, Dictionary<string, object> hint = null) => new UIIntent
        {
            ContractsVersion = "v19.0",
            UiIntentId = "anchor-1",
            DeliveryId = "del-1",
            Component = "task_anchor",
            TruthLevel = "observed",
            TargetTrackId = trackId,
            Content = content,
            UiHint = hint
        };

        // ---- registry -------------------------------------------------------

        [Test]
        public void Registry_MapsTaskPanelAndTaskAnchor()
        {
            Assert.AreEqual(typeof(TaskPanelComponent), UIComponentRegistry.ResolveType("task_panel"));
            Assert.AreEqual(typeof(TaskAnchorComponent), UIComponentRegistry.ResolveType("task_anchor"));
            // Case/separator-insensitive like the rest of the design system.
            Assert.AreEqual(typeof(TaskAnchorComponent), UIComponentRegistry.ResolveType("TaskAnchor"));
            Assert.AreEqual(typeof(TaskAnchorComponent), UIComponentRegistry.ResolveType("object anchor"));
        }

        // ---- composition ----------------------------------------------------

        [Test]
        public void ArcQuantityTimer_InstantiatesTheRightAtoms()
        {
            SubmitTrack("bowl-1", 0.5f, 0.5f, 0.2f, 0.2f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "bowl" }, { "name", "le bol" }, { "role", "target" },
                { "track_id", "bowl-1" },
                { "gesture", new Dictionary<string, object> { { "kind", "arc" } } },
                { "quantity", "200 g" },
                { "timer_seconds", 30.0 },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "bowl-1"));
            c.TickAtoms(0.02f, 0.02f);

            Assert.IsTrue(c.RingActive, "ring anchored on the live track");
            Assert.IsTrue(c.GestureActive, "arc gesture present");
            Assert.IsTrue(c.QuantityActive, "quantity chip present");
            Assert.IsTrue(c.TimerActive, "timer ring present (coexists with gesture)");
            Assert.IsFalse(c.ArrowActive, "no directional arrow when the track is live");
            Assert.IsFalse(c.SelectionActive, "single candidate → no selection highlight");
        }

        [Test]
        public void GhostAnchor_IsPrebuiltInvisible_ThenRefreshesInPlace()
        {
            SubmitTrack("cup-1", 0.5f, 0.5f, 0.2f, 0.2f, 10);
            var ghost = new Dictionary<string, object>
            {
                { "label_en", "cup" }, { "track_id", "cup-1" }, { "ghost", true },
                { "gesture", new Dictionary<string, object> { { "kind", "pulse" } } },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(ghost, "cup-1"));
            Assert.IsTrue(c.IsGhost);
            Assert.IsNotNull(c.RingAtom, "ghost pre-creates its atoms");
            Assert.IsFalse(c.RingActive, "ghost must not render before promotion");
            Assert.IsFalse(c.GestureActive);

            var current = new Dictionary<string, object>(ghost) { ["ghost"] = false };
            c.Refresh(AnchorIntent(current, "cup-1"));
            c.TickAtoms(0.02f, 0.02f);
            Assert.IsFalse(c.IsGhost);
            Assert.IsTrue(c.RingActive, "same-id refresh promotes the preloaded anchor");
            Assert.IsTrue(c.GestureActive);
        }

        [Test]
        public void Gesture_FromAndToTracks_DrawsAcrossTheTwoObjects()
        {
            SubmitTrack("bottle-1", 0.20f, 0.50f, 0.12f, 0.18f, 10);
            SubmitTrack("kettle-1", 0.75f, 0.50f, 0.16f, 0.20f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "bottle" }, { "track_id", "bottle-1" },
                { "from_track_id", "bottle-1" }, { "to_track_id", "kettle-1" },
                { "gesture", new Dictionary<string, object> { { "kind", "arc" } } },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "bottle-1"));
            c.TickAtoms(0.83f, 0.83f);
            LineRenderer trace = c.GestureAtom.GetComponent<LineRenderer>();
            Assert.Greater(trace.GetPosition(trace.positionCount - 1).x,
                trace.GetPosition(0).x + 0.15f,
                "arc must travel from the source track toward the target track");
        }

        [Test]
        public void CautionContent_ShowsCautionCue()
        {
            SubmitTrack("pan-1", 0.5f, 0.5f, 0.2f, 0.2f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "pan" }, { "track_id", "pan-1" },
                { "caution", "plaque chaude" },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "pan-1"));
            c.TickAtoms(0.02f, 0.02f);
            Assert.IsTrue(c.CautionActive);
        }

        // ---- anchoring: follows the object ---------------------------------

        [Test]
        public void Ring_FollowsTrack_WhenTheObjectMoves()
        {
            SubmitTrack("bowl-1", 0.30f, 0.50f, 0.2f, 0.2f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "bowl" }, { "track_id", "bowl-1" },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "bowl-1"));
            c.TickAtoms(0.02f, 0.02f);
            float leftX = FirstRingX(c);

            // The user slides the bowl to the right: a new track observation.
            SubmitTrack("bowl-1", 0.70f, 0.50f, 0.2f, 0.2f, 20);
            c.TickAtoms(0.04f, 0.02f);
            float rightX = FirstRingX(c);

            Assert.Greater(rightX, leftX,
                "the anchor ring must follow the track to the right when the object moves");
        }

        private static float FirstRingX(TaskAnchorComponent c)
        {
            LineRenderer lr = c.RingAtom.GetComponent<LineRenderer>();
            return lr.GetPosition(0).x;
        }

        // ---- track absent → directional arrow ------------------------------

        [Test]
        public void NoTrack_UsesDirectionalArrow_NotRing()
        {
            // No track submitted, and never resolved: fall back to the arrow.
            var content = new Dictionary<string, object>
            {
                { "label_en", "whisk" }, { "name", "le fouet" },
                { "entity_id", "whisk-e" },
            };
            var intent = AnchorIntent(content);
            intent.EntityId = "whisk-e";
            TaskAnchorComponent c = MakeAnchor(intent);
            c.TickAtoms(0.02f, 0.02f);

            Assert.IsTrue(c.ArrowActive, "no live track → directional arrow toward last-known bearing");
            Assert.IsFalse(c.RingActive, "no ring when the object was never anchored");
        }

        [Test]
        public void TrackLost_RingEntersSearching_AndArrowIsPromoted()
        {
            SubmitTrack("bowl-1", 0.5f, 0.5f, 0.2f, 0.2f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "bowl" }, { "name", "le bol" },
                { "track_id", "bowl-1" }, { "entity_id", "bowl-e" },
            };
            var intent = AnchorIntent(content, "bowl-1");
            intent.EntityId = "bowl-e";
            TaskAnchorComponent c = MakeAnchor(intent);
            c.TickAtoms(0.02f, 0.02f);
            Assert.IsTrue(c.RingActive);
            Assert.IsTrue(c.RingAtom.IsSearching == false, "ring locked while track present");

            // Age the track out (TrackTtl default 600ms) then tick past it.
            _cache.Tick(2000);
            c.TickAtoms(2.1f, 0.02f);

            Assert.IsTrue(c.RingAtom.IsSearching, "lost track → ring switches to searching");
            Assert.IsTrue(c.ArrowActive, "lost track → directional arrow is promoted");
        }

        // ---- multi-candidate → selection -----------------------------------

        [Test]
        public void MultipleCandidates_ShowSelectionHighlight()
        {
            SubmitTrack("bowl-1", 0.30f, 0.5f, 0.15f, 0.15f, 10);
            SubmitTrack("bowl-2", 0.70f, 0.5f, 0.15f, 0.15f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "bowl" }, { "track_id", "bowl-1" },
            };
            var hint = new Dictionary<string, object>
            {
                { "candidate_track_ids", new List<object> { "bowl-1", "bowl-2" } }
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "bowl-1", hint));
            c.TickAtoms(0.02f, 0.02f);

            Assert.IsTrue(c.SelectionActive, "several same-label tracks → selection highlight");
            Assert.IsFalse(c.ArrowActive, "multi-candidate is not a track-loss case");
        }

        // ---- timer elapses --------------------------------------------------

        [Test]
        public void TimerRing_FiresAtZero()
        {
            SubmitTrack("pot-1", 0.5f, 0.5f, 0.2f, 0.2f, 10);
            var content = new Dictionary<string, object>
            {
                { "label_en", "pot" }, { "track_id", "pot-1" }, { "timer_seconds", 1.0 },
            };
            TaskAnchorComponent c = MakeAnchor(AnchorIntent(content, "pot-1"));
            Assert.IsTrue(c.TimerActive);

            for (float t = 0f; t < 1.3f; t += 0.1f) c.TickAtoms(t, 0.1f);
            Assert.IsTrue(c.TimerAtom.Elapsed, "timer must fire once it reaches zero");
        }

        // ---- panel: ghost promoted in place --------------------------------

        [Test]
        public void TaskPanel_PromotesGhostToCurrent_WithoutRecreation()
        {
            var go = New("task_panel");
            var comp = go.AddComponent<TaskPanelComponent>();
            comp.Configure(Ctx(), null);

            comp.Admit(PanelIntent(current: 0), null, _ => { });
            comp.TickAtoms(0.02f, 0.02f);
            TaskPanel panelAtom = comp.PanelAtom;
            InstructionCard instrAtom = comp.InstructionAtom;
            Assert.IsNotNull(panelAtom);

            // Step advances: the PC re-sends the SAME intent id → Refresh path.
            comp.Refresh(PanelIntent(current: 1));
            comp.TickAtoms(0.04f, 0.02f);

            Assert.AreSame(panelAtom, comp.PanelAtom, "panel atom is reused, not recreated");
            Assert.AreSame(instrAtom, comp.InstructionAtom, "instruction atom is reused, not recreated");
        }

        private static UIIntent PanelIntent(int current) => new UIIntent
        {
            ContractsVersion = "v19.0",
            UiIntentId = "panel-1",
            DeliveryId = "del-p",
            Component = "task_panel",
            TruthLevel = "observed",
            Content = new Dictionary<string, object>
            {
                { "title", "Crêpes" }, { "domain", "cuisine" }, { "progress", 0.3 }, { "ghost_next", true },
                { "steps", new List<object>
                    {
                        Step(0, "Mélanger la farine", current == 0 ? "current" : "done"),
                        Step(1, "Ajouter les œufs", current == 1 ? "current" : (current < 1 ? "next" : "done")),
                        Step(2, "Verser le lait", "next"),
                    }
                },
            }
        };

        private static Dictionary<string, object> Step(int i, string text, string status) =>
            new Dictionary<string, object> { { "index", i }, { "text", text }, { "status", status } };
    }
}

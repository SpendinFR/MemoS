using System.Collections.Generic;
using MLOmega.Contracts.V19;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using NUnit.Framework;

namespace MLOmega.XR.Tests
{
    public sealed class WorldCanvasLot3Tests
    {
        [Test]
        public void RegistryResolvesEveryLot3Renderer()
        {
            Assert.AreEqual(
                typeof(WorldPathOverlay),
                UIComponentRegistry.ResolveType("trajectory_forecast"));
            Assert.AreEqual(
                typeof(WorldPathOverlay),
                UIComponentRegistry.ResolveType("event_vision"));
            Assert.AreEqual(
                typeof(WorldPathOverlay),
                UIComponentRegistry.ResolveType("ballistic_preview"));
            Assert.AreEqual(
                typeof(WorldMeasureTape),
                UIComponentRegistry.ResolveType("ar_measurement"));
            Assert.AreEqual(
                typeof(WorldRadioField),
                UIComponentRegistry.ResolveType("radio_field"));
            Assert.AreEqual(
                typeof(WorldKeyboardPlane),
                UIComponentRegistry.ResolveType("spatial_keyboard"));
        }

        [Test]
        public void HumanForecastAcceptsSeveralProbabilisticFutures()
        {
            UIIntent intent = PathIntent("trajectory_forecast");
            intent.Content["paths"] = new List<Dictionary<string, object>>
            {
                Path("person-1-main", 0.72, 0.84, 0f),
                Path("person-1-alt", 0.28, 0.79, 0.8f),
            };
            Assert.IsTrue(
                WorldPathOverlay.TryReadPaths(
                    intent,
                    out WorldPathOverlay.PathSet paths,
                    out string error),
                error);
            Assert.AreEqual(2, paths.Paths.Count);
            Assert.AreEqual(0.72f, paths.Paths[0].Probability, 0.001f);

            intent.Anchor["coordinate_space"] = "screen_normalized";
            Assert.IsFalse(
                WorldPathOverlay.TryReadPaths(intent, out _, out error));
            Assert.AreEqual("unsupported_coordinate_space", error);
        }

        [Test]
        public void BallisticPreviewIsRecreationalAndNeverWeaponTargeting()
        {
            UIIntent intent = PathIntent("ballistic_preview");
            intent.Content["hand_pose_valid"] = true;
            intent.Content["safety_class"] = "recreational";
            intent.Content["target_kind"] = "play_target";
            intent.Content["weapon"] = false;
            Assert.IsTrue(
                WorldPathOverlay.TryReadPaths(intent, out _, out string error),
                error);

            intent.Content["weapon"] = true;
            Assert.IsFalse(
                WorldPathOverlay.TryReadPaths(intent, out _, out error));
            Assert.AreEqual("unsafe_ballistic_contract", error);
        }

        [Test]
        public void EventVisionRequiresHeadMotionCompensation()
        {
            UIIntent intent = PathIntent("event_motion");
            intent.Content["rgb_motion_valid"] = true;
            intent.Content["head_motion_compensated"] = false;
            Assert.IsFalse(
                WorldPathOverlay.TryReadPaths(
                    intent, out _, out string error));
            Assert.AreEqual("motion_compensation_required", error);

            intent.Content["head_motion_compensated"] = true;
            Assert.IsTrue(
                WorldPathOverlay.TryReadPaths(intent, out _, out error),
                error);
        }

        [Test]
        public void MeasureMustMatchItsDepthEndpoints()
        {
            UIIntent intent = SpatialIntent("world_measure");
            intent.Content["intrinsics_valid"] = true;
            intent.Content["start"] = Point(0, 0, 2);
            intent.Content["end"] = Point(1.2, 0, 2);
            intent.Content["distance_m"] = 1.2;
            intent.Content["uncertainty_m"] = 0.015;
            Assert.IsTrue(
                WorldMeasureTape.TryReadMeasure(
                    intent,
                    out WorldMeasureTape.Measure measure,
                    out string error),
                error);
            Assert.AreEqual(1.2f, measure.DistanceM, 0.001f);

            intent.Content["distance_m"] = 2.4;
            Assert.IsFalse(
                WorldMeasureTape.TryReadMeasure(intent, out _, out error));
            Assert.AreEqual("measurement_consistency_failed", error);
        }

        [Test]
        public void RadioFieldRequiresPseudonymizedMeasuredSamples()
        {
            UIIntent intent = SpatialIntent("world_radio");
            intent.Content["depth_valid"] = false;
            intent.Content["spatial_quality"] = 0.72;
            intent.Content["pseudonymized"] = true;
            intent.Content["samples"] = new List<Dictionary<string, object>>
            {
                Radio("radio-a12", -48, 0f),
                Radio("radio-a12", -61, 1f),
            };
            Assert.IsTrue(
                WorldRadioField.TryReadField(
                    intent,
                    out WorldRadioField.Field field,
                    out string error),
                error);
            Assert.AreEqual(2, field.Samples.Count);

            intent.Content["pseudonymized"] = false;
            Assert.IsFalse(
                WorldRadioField.TryReadField(intent, out _, out error));
            Assert.AreEqual("radio_identity_not_pseudonymized", error);
        }

        [Test]
        public void KeyboardRequiresExplicitActivationHandsAndOrthogonalPlane()
        {
            UIIntent intent = SpatialIntent("world_keyboard");
            intent.Content["explicit_activation"] = true;
            intent.Content["hand_tracking_valid"] = true;
            intent.Content["origin"] = Point(-0.35, 0.75, 1.2);
            intent.Content["right"] = Point(1, 0, 0);
            intent.Content["forward"] = Point(0, 0, 1);
            intent.Content["width_m"] = 0.7;
            intent.Content["height_m"] = 0.25;
            Assert.IsTrue(
                WorldKeyboardPlane.TryReadKeyboard(
                    intent,
                    out WorldKeyboardPlane.Keyboard keyboard,
                    out string error),
                error);
            Assert.AreEqual(0.7f, keyboard.Width, 0.001f);

            intent.Content["forward"] = Point(1, 0, 0);
            Assert.IsFalse(
                WorldKeyboardPlane.TryReadKeyboard(intent, out _, out error));
            Assert.AreEqual("keyboard_basis_not_orthogonal", error);
        }

        private static UIIntent PathIntent(string mode)
        {
            UIIntent intent = SpatialIntent("world_path");
            intent.Content["mode"] = mode;
            intent.Content["horizon_s"] = 2.0;
            intent.Content["label"] = "Personne";
            intent.Content["paths"] = new List<Dictionary<string, object>>
            {
                Path("primary", 0.8, 0.86, 0f),
            };
            return intent;
        }

        private static UIIntent SpatialIntent(string component) => new UIIntent
        {
            UiIntentId = component + "-1",
            Producer = "spatial_provider",
            Component = component,
            TruthLevel = "observed",
            TtlMs = 1200,
            EvidenceRefs = new List<string>
            {
                "pose:eye-42",
                "depth:frame-42",
            },
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "depth_valid", true },
                { "calibration_id", "calib-eye-s24-1" },
                { "spatial_quality", 0.86 },
            },
        };

        private static Dictionary<string, object> Path(
            string id, double probability, double quality, float offset) =>
            new Dictionary<string, object>
            {
                { "path_id", id },
                { "probability", probability },
                { "quality", quality },
                {
                    "points",
                    new List<Dictionary<string, object>>
                    {
                        Point(offset, 0, 1),
                        Point(offset + 0.2, 0, 2),
                        Point(offset + 0.5, 0, 3),
                    }
                },
            };

        private static Dictionary<string, object> Radio(
            string id, double rssi, float x) =>
            new Dictionary<string, object>
            {
                { "network_id", id },
                { "source", "wifi" },
                { "rssi_dbm", rssi },
                { "position", Point(x, 0, 1) },
            };

        private static Dictionary<string, object> Point(
            double x, double y, double z) =>
            new Dictionary<string, object>
            {
                { "x", x }, { "y", y }, { "z", z },
            };
    }
}

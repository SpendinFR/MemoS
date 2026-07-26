using System;
using System.Collections.Generic;
using System.IO;
using MLOmega.Contracts.V19;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class WorldFreeGuyT0Tests
    {
        [Test]
        public void RegistryResolvesProceduralHolograms()
        {
            Assert.AreEqual(
                typeof(WorldHologram),
                UIComponentRegistry.ResolveType("world_hologram"));
            Assert.AreEqual(
                typeof(WorldHologram),
                UIComponentRegistry.ResolveType("freeguy_hologram"));
        }

        [Test]
        public void HologramRequiresProvenDepthAnchorAndKnownTemplate()
        {
            UIIntent intent = HologramIntent();
            Assert.IsTrue(
                WorldHologram.TryReadHologram(
                    intent,
                    out WorldHologram.Hologram hologram,
                    out string error),
                error);
            Assert.AreEqual("holo_billboard", hologram.TemplateId);
            Assert.AreEqual(new Vector3(1f, 1.4f, 3f), hologram.Position);

            intent.Content["template_id"] = "fake_2d_overlay";
            Assert.IsFalse(
                WorldHologram.TryReadHologram(intent, out _, out error));
            Assert.AreEqual("hologram_template_invalid", error);

            intent = HologramIntent();
            intent.Content["pose_valid"] = false;
            Assert.IsFalse(
                WorldHologram.TryReadHologram(intent, out _, out error));
            Assert.AreEqual("unproven_tracking_calibration", error);
        }

        [Test]
        public void WorldMapEarthToTrackingConversionIsDeterministic()
        {
            string directory = Path.Combine(
                Path.GetTempPath(), "mlomega-world-map-" + Guid.NewGuid());
            try
            {
                var store = new WorldMapStore(directory, "xreal-test");
                Assert.IsTrue(store.SetGeoOrigin(
                    48.8566,
                    2.3522,
                    35,
                    3,
                    0,
                    new Vector3(10f, 1f, 20f),
                    force: true));
                Assert.IsTrue(store.TryGeoToLocal(
                    48.8567,
                    2.3522,
                    35,
                    out Vector3 north));
                Assert.AreEqual(10f, north.x, 0.05f);
                Assert.Greater(north.z, 31f);
                Assert.AreEqual(1f, north.y, 0.01f);
            }
            finally
            {
                if (Directory.Exists(directory))
                    Directory.Delete(directory, true);
            }
        }

        private static UIIntent HologramIntent() => new UIIntent
        {
            UiIntentId = "freeguy-store-1",
            Producer = "ultralive",
            Component = "world_hologram",
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
                {
                    "position",
                    new Dictionary<string, object>
                    {
                        { "x", 1f }, { "y", 1.4f }, { "z", 3f },
                    }
                },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "depth_valid", true },
                { "calibration_id", "xreal-test" },
                { "anchor_quality", 0.88f },
                { "marker_id", "store-1" },
                { "template_id", "holo_billboard" },
                { "label", "Boulangerie" },
                { "subtitle", "HOLO DISPLAY // LIVE" },
                { "kind", "storefront" },
            },
            TruthLevel = "observed",
            Confidence = 0.88,
            TtlMs = 900,
            EvidenceRefs = new List<string>
            {
                "frame:42", "pose:xreal-head", "depth:xreal-mesh",
            },
        };
    }
}

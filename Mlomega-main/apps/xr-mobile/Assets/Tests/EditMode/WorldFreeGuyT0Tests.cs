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

        [Test]
        public void CreatorCatalogueProvidesHundredsOfBoundedProceduralPresets()
        {
            Assert.GreaterOrEqual(WorldCreatorCatalog.Entries.Count, 500);
            Assert.GreaterOrEqual(
                WorldCreatorCatalog.ForCategory("urban").Count, 20);
            foreach (WorldCreatorCatalog.Entry entry in WorldCreatorCatalog.Entries)
            {
                Assert.IsNotEmpty(entry.presetId);
                Assert.IsNotEmpty(entry.templateId);
                Assert.AreEqual(6, entry.accentHex.Length);
                Assert.GreaterOrEqual(entry.defaultScale.x, 0.1f);
                Assert.LessOrEqual(entry.defaultScale.x, 4f);
            }
        }

        [Test]
        public void ImportedAnchorGeometryAllowsRigidOriginShiftButRejectsDrift()
        {
            Quaternion shift = Quaternion.Euler(0f, 37f, 0f);
            Vector3 offset = new Vector3(12f, .4f, -8f);
            var valid = new[]
            {
                new WorldAnchorGeometryGuard.Sample(
                    "a",
                    Vector3.zero,
                    Quaternion.identity,
                    offset,
                    shift),
                new WorldAnchorGeometryGuard.Sample(
                    "b",
                    new Vector3(2f, 0f, 1f),
                    Quaternion.Euler(0f, 25f, 0f),
                    offset + shift * new Vector3(2f, 0f, 1f),
                    shift * Quaternion.Euler(0f, 25f, 0f)),
            };
            Assert.IsTrue(
                WorldAnchorGeometryGuard.TryValidate(
                    valid,
                    out string error),
                error);

            var drifted = new[]
            {
                valid[0],
                new WorldAnchorGeometryGuard.Sample(
                    "b",
                    valid[1].ExpectedPosition,
                    valid[1].ExpectedRotation,
                    valid[1].ObservedPosition + Vector3.right,
                    valid[1].ObservedRotation),
            };
            Assert.IsFalse(
                WorldAnchorGeometryGuard.TryValidate(drifted, out error));
            Assert.AreEqual("distance_drift", error);
        }

        [Test]
        public void AtelierPackageRoundTripsWithDigestAndNoMemoryPayload()
        {
            string sourceDir = Path.Combine(
                Path.GetTempPath(), "mlomega-atelier-source-" + Guid.NewGuid());
            string targetDir = Path.Combine(
                Path.GetTempPath(), "mlomega-atelier-target-" + Guid.NewGuid());
            string package = Path.Combine(sourceDir, "paris-night.world-map-v1.json");
            try
            {
                var source = new WorldMapStore(sourceDir, "xreal-test");
                string nativeMapDir = Path.Combine(sourceDir, "native-maps");
                Directory.CreateDirectory(nativeMapDir);
                string anchorGuid =
                    "0000000000000001-0000000000000002";
                File.WriteAllBytes(
                    Path.Combine(
                        nativeMapDir,
                        "00000001-0000-0000-0200-000000000000"),
                    new byte[] { 1, 4, 9, 16, 25, 36 });
                WorldCreatorCatalog.Entry preset =
                    WorldCreatorCatalog.ForCategory("cinematic")[0];
                WorldMapStore.WorldContent item = source.Upsert(
                    "world-content-1",
                    anchorGuid,
                    preset.templateId,
                    "RUE CYBER",
                    "ATELIER",
                    "",
                    "manual",
                    "atelier:xreal-depth",
                    new Vector3(1f, 1.5f, 3f),
                    Quaternion.Euler(0f, 25f, 0f),
                    preset.defaultScale,
                    0.91f);
                source.ApplyVisualPreset(item.worldContentId, preset);
                Assert.IsTrue(
                    source.CaptureAnchorMappings(
                        nativeMapDir,
                        out string error),
                    error);

                Assert.IsTrue(source.ExportPackage(package, out error), error);
                string exported = File.ReadAllText(package);
                StringAssert.Contains("\"packageType\": \"mlomega.world-map\"", exported);
                StringAssert.DoesNotContain("memory.db", exported);
                StringAssert.DoesNotContain("brainlive", exported.ToLowerInvariant());

                var target = new WorldMapStore(targetDir, "xreal-target");
                Assert.IsTrue(target.ReplaceFromPackage(package, out error), error);
                Assert.AreEqual(1, target.Contents.Count);
                Assert.AreEqual(
                    preset.presetId,
                    target.Contents[0].presetId);
                Assert.AreEqual(
                    anchorGuid,
                    target.Contents[0].anchorGuid);
                string installed = Path.Combine(targetDir, "installed-maps");
                Assert.IsTrue(target.InstallAnchorMappings(installed, out error), error);
                Assert.IsTrue(File.Exists(Path.Combine(
                    installed,
                    "00000001-0000-0000-0200-000000000000")));
            }
            finally
            {
                if (Directory.Exists(sourceDir)) Directory.Delete(sourceDir, true);
                if (Directory.Exists(targetDir)) Directory.Delete(targetDir, true);
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

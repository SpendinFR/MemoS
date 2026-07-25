using System.Collections.Generic;
using MLOmega.Contracts.V19;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using NUnit.Framework;

namespace MLOmega.XR.Tests
{
    public sealed class WorldCanvasTests
    {
        [Test]
        public void RegistryResolvesNavigationAndWorldMarkers()
        {
            Assert.AreEqual(
                typeof(WorldNavigationRibbon),
                UIComponentRegistry.ResolveType("world_navigation"));
            Assert.AreEqual(
                typeof(WorldNavigationRibbon),
                UIComponentRegistry.ResolveType("street_navigation"));
            Assert.AreEqual(
                typeof(WorldSemanticMarker),
                UIComponentRegistry.ResolveType("world_label"));
            Assert.AreEqual(
                typeof(WorldSemanticMarker),
                UIComponentRegistry.ResolveType("poi"));
            Assert.AreEqual(
                typeof(WorldSemanticSurface),
                UIComponentRegistry.ResolveType("facade_overlay"));
        }

        [Test]
        public void QualifiedTrackingRouteIsAcceptedLosslessly()
        {
            UIIntent intent = RouteIntent();
            Assert.IsTrue(
                WorldNavigationRibbon.TryReadRoute(
                    intent,
                    out WorldNavigationRibbon.Route route,
                    out string error),
                error);
            Assert.AreEqual("route-home", route.RouteId);
            Assert.AreEqual("calib-eye-s24-1", route.CalibrationId);
            Assert.AreEqual(3, route.Points.Count);
            Assert.AreEqual(6f, route.Points[2].z, 0.001f);
        }

        [Test]
        public void NavigationRefusesPersuasiveButUncalibratedGeometry()
        {
            UIIntent intent = RouteIntent();
            intent.Content["pose_valid"] = false;
            Assert.IsFalse(
                WorldNavigationRibbon.TryReadRoute(intent, out _, out string error));
            Assert.AreEqual("unproven_tracking_calibration", error);

            intent = RouteIntent();
            intent.EvidenceRefs.Clear();
            Assert.IsFalse(
                WorldNavigationRibbon.TryReadRoute(intent, out _, out error));
            Assert.AreEqual("route_provenance_missing", error);

            intent = RouteIntent();
            intent.Anchor["coordinate_space"] = "wgs84";
            Assert.IsFalse(
                WorldNavigationRibbon.TryReadRoute(intent, out _, out error));
            Assert.AreEqual("unsupported_coordinate_space", error);
        }

        [Test]
        public void QualifiedSemanticMarkerRequiresEvidenceAndLocalPose()
        {
            UIIntent intent = MarkerIntent();
            Assert.IsTrue(
                WorldSemanticMarker.TryReadMarker(
                    intent,
                    out WorldSemanticMarker.Marker marker,
                    out string error),
                error);
            Assert.AreEqual("Boulangerie", marker.Label);
            Assert.AreEqual("storefront", marker.Kind);
            Assert.AreEqual(2.2f, marker.Position.z, 0.001f);

            intent.EvidenceRefs.Clear();
            Assert.IsFalse(
                WorldSemanticMarker.TryReadMarker(intent, out _, out error));
            Assert.AreEqual("evidence_missing", error);
        }

        [Test]
        public void SemanticMarkerRefusesLowQualityOrRemoteCoordinates()
        {
            UIIntent intent = MarkerIntent();
            intent.Content["anchor_quality"] = 0.4;
            Assert.IsFalse(
                WorldSemanticMarker.TryReadMarker(intent, out _, out string error));
            Assert.AreEqual("anchor_quality_below_threshold", error);

            intent = MarkerIntent();
            intent.Anchor["coordinate_space"] = "geodetic";
            Assert.IsFalse(
                WorldSemanticMarker.TryReadMarker(intent, out _, out error));
            Assert.AreEqual("unsupported_coordinate_space", error);
        }

        [Test]
        public void SemanticMarkerRefusesScreenSpaceFallback()
        {
            UIIntent intent = MarkerIntent();
            intent.Anchor["coordinate_space"] = "screen_normalized";
            Assert.IsFalse(
                WorldSemanticMarker.TryReadMarker(
                    intent, out _, out string error));
            Assert.AreEqual("unsupported_coordinate_space", error);
        }

        [Test]
        public void SemanticSurfaceRequiresCalibratedDepthAndEvidence()
        {
            UIIntent intent = SurfaceIntent();
            Assert.IsTrue(
                WorldSemanticSurface.TryReadSurface(
                    intent,
                    out WorldSemanticSurface.Surface surface,
                    out string error),
                error);
            Assert.AreEqual("facade-42", surface.SurfaceId);
            Assert.AreEqual("building", surface.Kind);
            Assert.AreEqual(4, surface.Points.Count);

            intent.Content["depth_valid"] = false;
            Assert.IsFalse(
                WorldSemanticSurface.TryReadSurface(intent, out _, out error));
            Assert.AreEqual("unproven_surface_geometry", error);
        }

        [Test]
        public void SemanticSurfaceRefusesUnprovenOrSyntheticGeometry()
        {
            UIIntent intent = SurfaceIntent();
            intent.Content["surface_quality"] = 0.5;
            Assert.IsFalse(
                WorldSemanticSurface.TryReadSurface(
                    intent, out _, out string error));
            Assert.AreEqual("surface_quality_below_threshold", error);

            intent = SurfaceIntent();
            intent.EvidenceRefs.Clear();
            Assert.IsFalse(
                WorldSemanticSurface.TryReadSurface(intent, out _, out error));
            Assert.AreEqual("surface_evidence_missing", error);

            intent = SurfaceIntent();
            intent.Anchor["coordinate_space"] = "screen_normalized";
            Assert.IsFalse(
                WorldSemanticSurface.TryReadSurface(intent, out _, out error));
            Assert.AreEqual("unsupported_coordinate_space", error);

            intent = SurfaceIntent();
            intent.Content["surface_points"] =
                new List<Dictionary<string, object>>
                {
                    new Dictionary<string, object>
                    {
                        { "x", 0.0 }, { "y", 0.0 }, { "z", 4.0 },
                    },
                    new Dictionary<string, object>
                    {
                        { "x", 1.0 }, { "y", 0.0 }, { "z", 4.0 },
                    },
                    new Dictionary<string, object>
                    {
                        { "x", 2.0 }, { "y", 0.0 }, { "z", 4.0 },
                    },
                };
            Assert.IsFalse(
                WorldSemanticSurface.TryReadSurface(intent, out _, out error));
            Assert.AreEqual("surface_geometry_degenerate", error);
        }

        private static UIIntent RouteIntent() => new UIIntent
        {
            UiIntentId = "nav-1",
            Producer = "ultralive",
            Component = "world_navigation",
            TruthLevel = "observed",
            TtlMs = 8000,
            EvidenceRefs = new List<string> { "route:maps-42", "pose:eye-42" },
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "calibration_id", "calib-eye-s24-1" },
                { "map_quality", 0.92 },
                { "route_quality", 0.86 },
                { "route_id", "route-home" },
                { "destination", "Maison" },
                { "distance_m", 6.2 },
                {
                    "route_points",
                    new List<Dictionary<string, object>>
                    {
                        new Dictionary<string, object>
                        {
                            { "x", 0.0 }, { "y", 0.0 }, { "z", 0.0 },
                        },
                        new Dictionary<string, object>
                        {
                            { "x", 0.4 }, { "y", 0.0 }, { "z", 3.0 },
                        },
                        new Dictionary<string, object>
                        {
                            { "x", 1.0 }, { "y", 0.0 }, { "z", 6.0 },
                        },
                    }
                },
            },
        };

        private static UIIntent MarkerIntent() => new UIIntent
        {
            UiIntentId = "marker-1",
            Producer = "visionrt",
            Component = "world_marker",
            TruthLevel = "observed",
            TtlMs = 5000,
            EvidenceRefs = new List<string> { "frame:42", "track:shop-1" },
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
                {
                    "position",
                    new Dictionary<string, object>
                    {
                        { "x", 0.3 }, { "y", 1.1 }, { "z", 2.2 },
                    }
                },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "calibration_id", "calib-eye-s24-1" },
                { "anchor_quality", 0.91 },
                { "marker_id", "storefront-42" },
                { "label", "Boulangerie" },
                { "subtitle", "Ouvert" },
                { "kind", "storefront" },
                { "distance_m", 2.3 },
                { "depth_valid", true },
            },
        };

        private static UIIntent SurfaceIntent() => new UIIntent
        {
            UiIntentId = "surface-1",
            Producer = "spatial_provider",
            Component = "world_surface",
            TruthLevel = "observed",
            TtlMs = 1500,
            EvidenceRefs = new List<string>
            {
                "depth:frame-42",
                "semantic:building-42",
                "pose:eye-42",
            },
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "depth_valid", true },
                { "convex", true },
                { "calibration_id", "calib-eye-s24-1" },
                { "surface_quality", 0.88 },
                { "surface_id", "facade-42" },
                { "surface_kind", "building" },
                { "label", "Boulangerie" },
                {
                    "surface_points",
                    new List<Dictionary<string, object>>
                    {
                        new Dictionary<string, object>
                        {
                            { "x", -1.0 }, { "y", 0.0 }, { "z", 4.0 },
                        },
                        new Dictionary<string, object>
                        {
                            { "x", -1.0 }, { "y", 2.0 }, { "z", 4.0 },
                        },
                        new Dictionary<string, object>
                        {
                            { "x", 1.0 }, { "y", 2.0 }, { "z", 4.0 },
                        },
                        new Dictionary<string, object>
                        {
                            { "x", 1.0 }, { "y", 0.0 }, { "z", 4.0 },
                        },
                    }
                },
            },
        };
    }
}

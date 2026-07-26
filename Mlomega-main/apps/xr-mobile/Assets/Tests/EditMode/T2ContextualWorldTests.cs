using System;
using System.IO;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class T2ContextualWorldTests
    {
        private string _directory;

        [SetUp]
        public void SetUp()
        {
            _directory = Path.Combine(
                Path.GetTempPath(),
                "mlomega-t2-" + Guid.NewGuid().ToString("N"));
        }

        [TearDown]
        public void TearDown()
        {
            if (Directory.Exists(_directory))
                Directory.Delete(_directory, true);
        }

        [Test]
        public void IndoorMapLearnsWalkedGraphAndRelocalisesOnNextSession()
        {
            var first = new IndoorLiveMapStore(_directory);
            Assert.IsTrue(first.Observe(
                Vector3.zero, 10f, Fingerprint("a", -45), out string state));
            Assert.AreEqual("mapping_started", state);
            Assert.IsTrue(first.NameCurrent("entrée"));

            Assert.IsTrue(first.Observe(
                new Vector3(1.5f, 0f, 0f), 10f,
                Fingerprint("a", -46), out state));
            Assert.AreEqual("node_added", state,
                "stable room Wi-Fi must not collapse a walked trail");
            Assert.IsTrue(first.Observe(
                new Vector3(3.0f, 0f, 0f), 10f,
                Fingerprint("b", -62), out state));
            Assert.AreEqual("node_added", state);
            Assert.IsTrue(first.NameCurrent("cuisine"));
            Assert.AreEqual(3, first.NodeCount);
            Assert.AreEqual(2, first.EdgeCount);

            Assert.IsTrue(first.TryRoute(
                "entrée", out IndoorLiveMapStore.RouteResult outbound));
            Assert.GreaterOrEqual(outbound.TrackingLocalPoints.Count, 3);
            Assert.Greater(outbound.DistanceM, 2.5f);

            var nextSession = new IndoorLiveMapStore(_directory);
            Assert.IsTrue(nextSession.Observe(
                new Vector3(100f, 0f, 20f), -20f,
                Fingerprint("b", -62), out state));
            Assert.AreEqual("relocalised", state);
            Assert.IsTrue(nextSession.TryRoute(
                "entrée", out IndoorLiveMapStore.RouteResult returnRoute));
            Assert.GreaterOrEqual(returnRoute.Quality, 0.72f);
            Assert.GreaterOrEqual(returnRoute.TrackingLocalPoints.Count, 3);
        }

        [Test]
        public void PlanetariumHasAnExplicitWorldSpaceRenderer()
        {
            Assert.AreEqual(
                typeof(SkyDome),
                UIComponentRegistry.ResolveType("sky_dome"));
            Assert.AreEqual(
                typeof(SkyDome),
                UIComponentRegistry.ResolveType("planetarium"));
        }

        private static string Fingerprint(string prefix, int rssi) =>
            "{\"schema_version\":1,\"radio_permission\":true," +
            "\"wifi\":[" +
            Row(prefix + "1", rssi) + "," +
            Row(prefix + "2", rssi - 2) + "," +
            Row(prefix + "3", rssi - 4) + "," +
            Row(prefix + "4", rssi - 6) + "]," +
            "\"ble\":[],\"magnetic\":{\"x_ut\":20,\"y_ut\":5," +
            "\"z_ut\":42,\"magnitude_ut\":46.75}}";

        private static string Row(string id, int rssi) =>
            "{\"id\":\"" + id + "\",\"rssi\":" + rssi +
            ",\"frequency_mhz\":2412}";
    }
}

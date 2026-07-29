using System;
using System.IO;
using System.Text;
using MLOmega.XR.UI;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class WorldMapLibraryTests
    {
        [Test]
        public void RuntimeGlbEnvelopeAcceptsAtLeastThirtyMegabytesPerAsset()
        {
            Assert.GreaterOrEqual(WorldMapStore.MaxAssetBytes, 30 * 1024 * 1024);
            Assert.GreaterOrEqual(
                WorldMapStore.MaxTotalAssetBytes,
                2 * WorldMapStore.MaxAssetBytes);
        }

        [Test]
        public void DynamicOnlyMapsComposeAndCanBeToggledIndependently()
        {
            string root = Path.Combine(
                Path.GetTempPath(), "mlomega-map-library-" + Guid.NewGuid());
            try
            {
                string packageA = CreateDynamicPackage(root, "Paris", "vehicle");
                string packageB = CreateDynamicPackage(root, "Maison", "object");
                var library = new WorldMapLibrary(Path.Combine(root, "library"));
                Assert.IsTrue(library.InstallPackage(
                    packageA, true, out string mapA, out string error), error);
                Assert.IsTrue(library.InstallPackage(
                    packageB, true, out string mapB, out error), error);
                Assert.AreNotEqual(mapA, mapB);
                Assert.IsTrue(library.TryComposeActive(
                    out WorldMapStore.MapDocument composed, out error), error);
                Assert.AreEqual(2, composed.dynamicBindings.Count);
                Assert.AreEqual(0, composed.contents.Count);
                Assert.AreEqual(2, library.Selections.Count);

                Assert.IsTrue(library.SetActive(mapA, false));
                Assert.IsTrue(library.TryComposeActive(out composed, out error), error);
                Assert.AreEqual(1, composed.dynamicBindings.Count);
                Assert.AreEqual(mapB, composed.dynamicBindings[0].sourceMapId);
            }
            finally
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        [Test]
        public void GlbImportAcceptsBoundedEmbeddedTriangleAndRejectsGarbage()
        {
            byte[] glb = TinyTriangleGlb();
            Assert.IsTrue(RuntimeGlbModel.TryValidate(glb, out string error), error);
            var parent = new GameObject("GLB Test Parent");
            try
            {
                Assert.IsTrue(RuntimeGlbModel.TryInstantiate(
                    glb,
                    parent.transform,
                    null,
                    out GameObject model,
                    out error), error);
                Assert.NotNull(model.GetComponentInChildren<MeshRenderer>());
            }
            finally
            {
                UnityEngine.Object.DestroyImmediate(parent);
            }
            Assert.IsFalse(RuntimeGlbModel.TryValidate(
                new byte[] { 1, 2, 3, 4 }, out _));

            string root = Path.Combine(
                Path.GetTempPath(), "mlomega-glb-store-" + Guid.NewGuid());
            try
            {
                Directory.CreateDirectory(root);
                string path = Path.Combine(root, "triangle.glb");
                File.WriteAllBytes(path, glb);
                var store = new WorldMapStore(root, "xreal-test");
                Assert.IsTrue(
                    store.TryAddGlbAsset(path, out string assetId, out error),
                    error);
                Assert.AreEqual("glb_model", store.FindAsset(assetId).kind);
                Assert.AreEqual(
                    "model/gltf-binary",
                    store.FindAsset(assetId).mimeType);
            }
            finally
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        [Test]
        public void ProductLibraryExtractsAndDeduplicatesAssetsByDigest()
        {
            string root = Path.Combine(
                Path.GetTempPath(), "mlomega-asset-library-" + Guid.NewGuid());
            try
            {
                byte[] glb = TinyTriangleGlb();
                string packageA = CreateDynamicPackage(
                    root, "Map A", "vehicle", glb);
                string packageB = CreateDynamicPackage(
                    root, "Map B", "object", glb);
                string libraryRoot = Path.Combine(root, "library");
                var library = new WorldMapLibrary(libraryRoot);
                Assert.IsTrue(library.InstallPackage(
                    packageA, true, out _, out string error), error);
                Assert.IsTrue(library.InstallPackage(
                    packageB, true, out _, out error), error);
                Assert.AreEqual(
                    1,
                    Directory.GetFiles(Path.Combine(libraryRoot, "assets"))
                        .Length);
                Assert.IsTrue(library.TryComposeActive(
                    out WorldMapStore.MapDocument composed, out error), error);
                Assert.AreEqual(1, composed.assets.Count);
                Assert.IsEmpty(composed.assets[0].base64Data);
                Assert.IsTrue(File.Exists(composed.assets[0].localFilePath));
            }
            finally
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        [Test]
        public void AnchoredContentSupportsGiantScaleAndBoundedMotion()
        {
            string root = Path.Combine(
                Path.GetTempPath(), "mlomega-motion-" + Guid.NewGuid());
            try
            {
                var store = new WorldMapStore(root, "xreal-test");
                WorldMapStore.WorldContent content = store.Upsert(
                    null,
                    "anchor-test",
                    "holo_billboard",
                    "Giant",
                    "Patrol",
                    string.Empty,
                    "manual",
                    "test",
                    Vector3.zero,
                    Quaternion.identity,
                    Vector3.one * 80f,
                    .9f,
                    motionPath: "figure8",
                    motionRadiusM: 100f,
                    motionSpeed: 20f,
                    motionHeightM: 100f);
                Assert.AreEqual(50f, content.localScale.x);
                Assert.AreEqual("figure8", content.motionPath);
                Assert.AreEqual(40f, content.motionRadiusM);
                Assert.AreEqual(5f, content.motionSpeed);
                Assert.AreEqual(20f, content.motionHeightM);
            }
            finally
            {
                if (Directory.Exists(root)) Directory.Delete(root, true);
            }
        }

        private static string CreateDynamicPackage(
            string root,
            string name,
            string kind,
            byte[] glb = null)
        {
            string directory = Path.Combine(root, name);
            Directory.CreateDirectory(directory);
            var store = new WorldMapStore(directory, "xreal-test");
            Assert.IsTrue(store.SetDisplayName(name));
            WorldCreatorCatalog.Entry preset =
                WorldCreatorCatalog.ForCategory("urban")[0];
            string assetId = string.Empty;
            if (glb != null)
            {
                string glbPath = Path.Combine(directory, "shared.glb");
                File.WriteAllBytes(glbPath, glb);
                Assert.IsTrue(store.TryAddGlbAsset(
                    glbPath, out assetId, out string assetError), assetError);
            }
            Assert.NotNull(store.UpsertDynamicBinding(
                null,
                preset,
                assetId,
                kind,
                "above",
                name,
                "DYNAMIC",
                string.Empty,
                Vector3.zero,
                preset.defaultScale));
            string package = Path.Combine(
                directory, name + ".world-map-v1.json");
            Assert.IsTrue(store.ExportPackage(package, out string error), error);
            return package;
        }

        private static byte[] TinyTriangleGlb()
        {
            byte[] bin = new byte[44];
            float[] vertices =
            {
                0f, 0f, 0f,
                1f, 0f, 0f,
                0f, 1f, 0f,
            };
            Buffer.BlockCopy(vertices, 0, bin, 0, 36);
            Buffer.BlockCopy(
                new ushort[] { 0, 1, 2 }, 0, bin, 36, 6);
            string json =
                "{\"asset\":{\"version\":\"2.0\"}," +
                "\"buffers\":[{\"byteLength\":44}]," +
                "\"bufferViews\":[" +
                "{\"buffer\":0,\"byteOffset\":0,\"byteLength\":36}," +
                "{\"buffer\":0,\"byteOffset\":36,\"byteLength\":6}]," +
                "\"accessors\":[" +
                "{\"bufferView\":0,\"componentType\":5126,\"count\":3," +
                "\"type\":\"VEC3\",\"min\":[0,0,0],\"max\":[1,1,0]}," +
                "{\"bufferView\":1,\"componentType\":5123,\"count\":3," +
                "\"type\":\"SCALAR\"}]," +
                "\"meshes\":[{\"primitives\":[{" +
                "\"attributes\":{\"POSITION\":0},\"indices\":1,\"mode\":4}]}]," +
                "\"nodes\":[{\"mesh\":0}],\"scenes\":[{\"nodes\":[0]}]," +
                "\"scene\":0}";
            byte[] jsonBytes = Encoding.UTF8.GetBytes(json);
            int jsonPadded = (jsonBytes.Length + 3) & ~3;
            int total = 12 + 8 + jsonPadded + 8 + bin.Length;
            var glb = new byte[total];
            WriteUInt(glb, 0, 0x46546C67);
            WriteUInt(glb, 4, 2);
            WriteUInt(glb, 8, (uint)total);
            WriteUInt(glb, 12, (uint)jsonPadded);
            WriteUInt(glb, 16, 0x4E4F534A);
            Buffer.BlockCopy(jsonBytes, 0, glb, 20, jsonBytes.Length);
            for (int i = 20 + jsonBytes.Length; i < 20 + jsonPadded; i++)
                glb[i] = 0x20;
            int binHeader = 20 + jsonPadded;
            WriteUInt(glb, binHeader, (uint)bin.Length);
            WriteUInt(glb, binHeader + 4, 0x004E4942);
            Buffer.BlockCopy(bin, 0, glb, binHeader + 8, bin.Length);
            return glb;
        }

        private static void WriteUInt(byte[] target, int offset, uint value)
        {
            byte[] bytes = BitConverter.GetBytes(value);
            Buffer.BlockCopy(bytes, 0, target, offset, 4);
        }
    }
}

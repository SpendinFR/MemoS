using MLOmega.XR.Transport;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class XrealEyeTransportTests
    {
        [Test]
        public void NativeEyePlanesPackLosslesslyAsI420()
        {
            var y = new Texture2D(4, 2, TextureFormat.Alpha8, false);
            var u = new Texture2D(2, 1, TextureFormat.Alpha8, false);
            var v = new Texture2D(2, 1, TextureFormat.Alpha8, false);
            try
            {
                byte[] yBytes = { 16, 32, 48, 64, 80, 96, 112, 128 };
                byte[] uBytes = { 140, 150 };
                byte[] vBytes = { 160, 170 };
                y.LoadRawTextureData(yBytes);
                u.LoadRawTextureData(uBytes);
                v.LoadRawTextureData(vBytes);
                y.Apply();
                u.Apply();
                v.Apply();

                byte[] packed = null;
                Assert.That(
                    LiveTransportBridge.TryPackNativeI420(y, u, v, ref packed),
                    Is.True);
                CollectionAssert.AreEqual(
                    new byte[]
                    {
                        16, 32, 48, 64, 80, 96, 112, 128,
                        140, 150,
                        160, 170
                    },
                    packed);
            }
            finally
            {
                Object.DestroyImmediate(y);
                Object.DestroyImmediate(u);
                Object.DestroyImmediate(v);
            }
        }

        [Test]
        public void NativeEyePlanesRejectWrongChromaGeometry()
        {
            var y = new Texture2D(4, 2, TextureFormat.Alpha8, false);
            var u = new Texture2D(1, 1, TextureFormat.Alpha8, false);
            var v = new Texture2D(2, 1, TextureFormat.Alpha8, false);
            try
            {
                byte[] packed = null;
                Assert.That(
                    LiveTransportBridge.TryPackNativeI420(y, u, v, ref packed),
                    Is.False);
                Assert.That(packed, Is.Null);
            }
            finally
            {
                Object.DestroyImmediate(y);
                Object.DestroyImmediate(u);
                Object.DestroyImmediate(v);
            }
        }
    }
}

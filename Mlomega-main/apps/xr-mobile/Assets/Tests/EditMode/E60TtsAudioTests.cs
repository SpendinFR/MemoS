using System;
using System.IO;
using System.Text;
using MLOmega.XR.UI;
using NUnit.Framework;

namespace MLOmega.XR.Tests.EditMode
{
    public sealed class E60TtsAudioTests
    {
        [Test]
        public void TtsPlayer_DecodesPcm16WavContract()
        {
            byte[] pcm = { 0, 0, 255, 127, 0, 128 };
            byte[] wav;
            using (var ms = new MemoryStream())
            using (var w = new BinaryWriter(ms, Encoding.ASCII, true))
            {
                w.Write(Encoding.ASCII.GetBytes("RIFF")); w.Write(36 + pcm.Length);
                w.Write(Encoding.ASCII.GetBytes("WAVEfmt ")); w.Write(16);
                w.Write((short)1); w.Write((short)1); w.Write(16000);
                w.Write(32000); w.Write((short)2); w.Write((short)16);
                w.Write(Encoding.ASCII.GetBytes("data")); w.Write(pcm.Length); w.Write(pcm);
                wav = ms.ToArray();
            }

            Assert.IsTrue(TtsAudioPlayer.TryDecodePcm16Wav(
                wav, out float[] samples, out int channels, out int rate));
            Assert.AreEqual(1, channels);
            Assert.AreEqual(16000, rate);
            Assert.AreEqual(3, samples.Length);
            Assert.Greater(samples[1], 0.99f);
            Assert.LessOrEqual(samples[2], -1f);
        }

        [Test]
        public void TtsPlayer_RejectsNonWavAndTruncation()
        {
            Assert.IsFalse(TtsAudioPlayer.TryDecodePcm16Wav(
                Encoding.ASCII.GetBytes("not wav"), out _, out _, out _));
            byte[] truncated = new byte[44];
            Array.Copy(Encoding.ASCII.GetBytes("RIFF"), truncated, 4);
            Array.Copy(Encoding.ASCII.GetBytes("WAVE"), 0, truncated, 8, 4);
            Assert.IsFalse(TtsAudioPlayer.TryDecodePcm16Wav(truncated, out _, out _, out _));
        }
    }
}

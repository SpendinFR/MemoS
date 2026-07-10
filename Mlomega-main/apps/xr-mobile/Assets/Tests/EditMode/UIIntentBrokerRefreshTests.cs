using System.Collections.Generic;
using System.Linq;
using MLOmega.Contracts.V19;
using MLOmega.XR.UI;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class UIIntentBrokerRefreshTests
    {
        private GameObject _go;

        [TearDown]
        public void TearDown()
        {
            if (_go != null) Object.DestroyImmediate(_go);
        }

        [Test]
        public void SameId_NotifiesRendererWithRefreshedPayload()
        {
            _go = new GameObject("broker-refresh");
            UIIntentBroker broker = _go.AddComponent<UIIntentBroker>();
            int admissions = 0;
            broker.IntentAdmitted += _ => admissions++;

            broker.Submit(Intent("stable-panel", "first"));
            broker.Tick(10);
            broker.Submit(Intent("stable-panel", "second"));
            broker.Tick(20);

            Assert.AreEqual(2, admissions, "refresh must reach UIRuntime");
            ActiveIntent active = broker.ActiveIntents.Single();
            Assert.AreEqual("second", active.Intent.Content["title"]);
        }

        private static UIIntent Intent(string id, string title) => new UIIntent
        {
            ContractsVersion = "v19.0",
            UiIntentId = id,
            Producer = "ultralive",
            Component = "task_panel",
            TruthLevel = "inferred",
            Confidence = 0.8,
            Priority = 0.55,
            TtlMs = 60000,
            Content = new Dictionary<string, object> { { "title", title } },
        };
    }
}

using System;
using System.Collections.Generic;
using MLOmega.XR.Core;
using MLOmega.XR.UI;
using MLOmega.XR.UI.Components;
using NUnit.Framework;
using UnityEngine;

namespace MLOmega.XR.Tests
{
    public sealed class AugmentedRealityFoundationTests
    {
        private readonly List<GameObject> _spawned = new List<GameObject>();

        [SetUp]
        public void SetUp() => ClearPreferences();

        [TearDown]
        public void TearDown()
        {
            foreach (GameObject go in _spawned)
                if (go != null) UnityEngine.Object.DestroyImmediate(go);
            _spawned.Clear();
            ClearPreferences();
        }

        [Test]
        public void DeviceHandlerCreatesRegistryWithEveryFeatureOff()
        {
            var root = NewObject("handler");
            var handler = root.AddComponent<DeviceCommandHandler>();
            InvokePrivate(handler, "Awake");
            var registry = root.GetComponent<AugmentedRealityFeatureRegistry>();

            Assert.IsNotNull(registry);
            Assert.IsFalse(registry.MasterEnabled);
            foreach (string feature in AugmentedRealityFeatureRegistry.FeatureIds)
            {
                Assert.IsFalse(registry.IsSelected(feature));
                Assert.IsFalse(registry.IsEffective(feature));
            }
            Assert.IsNull(root.GetComponent<AugmentedRealityCapabilityProbe>(),
                "the capability probe must not even be created while AR is off");
        }

        [Test]
        public void KnownFeatureTogglesLocallyAndUnknownFeatureIsRejected()
        {
            var root = NewObject("registry");
            var registry = root.AddComponent<AugmentedRealityFeatureRegistry>();

            Assert.IsTrue(registry.SetFeature(
                AugmentedRealityFeatureRegistry.SemanticSound, true));
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.SemanticSound));
            Assert.IsFalse(registry.IsEffective(
                AugmentedRealityFeatureRegistry.SemanticSound),
                "child selection remains dormant until the master switch is on");
            Assert.AreEqual("ARMÉ", registry.DisplayState(
                AugmentedRealityFeatureRegistry.SemanticSound));
            Assert.IsTrue(registry.SetFeature(
                AugmentedRealityFeatureRegistry.Master, true));
            Assert.IsTrue(registry.IsEffective(
                AugmentedRealityFeatureRegistry.SemanticSound));
            Assert.IsFalse(registry.SetFeature("unknown_feature", true));
            Assert.IsNotNull(root.GetComponent<AugmentedRealityCapabilityProbe>());
        }

        [Test]
        public void FreeGuyPresetIsAtomicAndLeavesIndependentFeaturesUntouched()
        {
            var root = NewObject("preset");
            var registry = root.AddComponent<AugmentedRealityFeatureRegistry>();
            registry.SetFeature(
                AugmentedRealityFeatureRegistry.TrajectoryForecast, true);

            Assert.IsTrue(registry.SetPreset("freeguy", true));
            Assert.IsTrue(registry.MasterEnabled);
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.WorldStyling));
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.AutomaticWorldFx));
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.TrajectoryForecast),
                "crowd trajectories may coexist with the FreeGuy preset");

            Assert.IsTrue(registry.SetPreset("freeguy", false));
            Assert.IsFalse(registry.IsSelected(
                AugmentedRealityFeatureRegistry.WorldStyling));
            Assert.IsFalse(registry.IsSelected(
                AugmentedRealityFeatureRegistry.AutomaticWorldFx));
            Assert.IsTrue(registry.MasterEnabled,
                "turning off one preset must not kill other selected AR features");
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.TrajectoryForecast));
        }

        [Test]
        public void MenuExposesMasterAndPerFeatureSettingsWithoutClosing()
        {
            var root = NewObject("root");
            var handler = root.AddComponent<DeviceCommandHandler>();
            InvokePrivate(handler, "Awake");
            var registry = root.GetComponent<AugmentedRealityFeatureRegistry>();
            var menuObject = NewObject("menu");
            var menu = menuObject.AddComponent<MenuPanel>();
            SetPrivate(menu, "_commandHandler", handler);
            SetPrivate(menu, "_augmentedReality", registry);
            menu.BuildDefaultActions();

            int settings = Find(menu, "Réglages AR");
            Assert.GreaterOrEqual(settings, 0);
            menu.Open();
            Assert.IsTrue(menu.Select(settings));
            Assert.IsTrue(menu.IsOpen, "settings navigation must keep the glass menu open");

            int sound = Find(menu, "Sons : OFF");
            Assert.GreaterOrEqual(sound, 0);
            Assert.IsTrue(menu.Select(sound));
            Assert.IsTrue(registry.IsSelected(
                AugmentedRealityFeatureRegistry.SemanticSound));
            Assert.IsTrue(menu.IsOpen, "a toggle must not close the settings page");
            Assert.GreaterOrEqual(Find(menu, "Sons : ARMÉ"), 0);
        }

        [Test]
        public void MenuLateBindsRegistryRegardlessOfAwakeOrder()
        {
            var menuObject = NewObject("menu-first");
            var menu = menuObject.AddComponent<MenuPanel>();
            menu.BuildDefaultActions();

            var handlerObject = NewObject("handler-second");
            var handler = handlerObject.AddComponent<DeviceCommandHandler>();
            InvokePrivate(handler, "Awake");
            SetPrivate(menu, "_commandHandler", handler);

            menu.BuildAugmentedActions();
            int sound = Find(menu, "Sons : OFF");
            Assert.GreaterOrEqual(sound, 0);
            Assert.IsTrue(menu.Select(sound));
            Assert.IsTrue(handlerObject
                .GetComponent<AugmentedRealityFeatureRegistry>()
                .IsSelected(AugmentedRealityFeatureRegistry.SemanticSound));
        }

        [Test]
        public void AugmentedSettingsArePagedAndEveryFeatureRemainsReachable()
        {
            var root = NewObject("paged-root");
            var handler = root.AddComponent<DeviceCommandHandler>();
            InvokePrivate(handler, "Awake");
            var menuObject = NewObject("paged-menu");
            var menu = menuObject.AddComponent<MenuPanel>();
            SetPrivate(menu, "_commandHandler", handler);
            SetPrivate(menu, "_augmentedReality",
                root.GetComponent<AugmentedRealityFeatureRegistry>());

            menu.BuildAugmentedActions();
            Assert.LessOrEqual(menu.Actions.Count, 9,
                "a physical glass page must stay readable/selectable");
            Assert.GreaterOrEqual(Find(menu, "Page suivante"), 0);
            Assert.IsTrue(menu.Select(Find(menu, "Page suivante")));
            Assert.IsTrue(menu.Select(Find(menu, "Page suivante")));
            Assert.IsTrue(menu.Select(Find(menu, "Page suivante")));
            Assert.GreaterOrEqual(Find(menu, "Aura pouls (exp.) : OFF"), 0);
            Assert.GreaterOrEqual(Find(menu, "Page précédente"), 0);
            Assert.LessOrEqual(menu.Actions.Count, 9);
        }

        [Test]
        public void ProbeReportsSingleLoaderBoundaryNeverPackageCoexistence()
        {
            var root = NewObject("probe");
            var probe = root.AddComponent<AugmentedRealityCapabilityProbe>();
            AugmentedRealityCapabilityProbe.Report report = probe.Probe();

            Assert.AreEqual(
                "single_active_loader_architecture",
                report.CoexistenceVerdict);
            Assert.LessOrEqual(report.SimultaneousActiveLoaderCount, 1);
            Assert.IsNotNull(report.ConfiguredLoaderCandidates);
            Assert.IsNotNull(report.RunningArSubsystems);
            Assert.IsNotNull(report.DeviceModel);
            Assert.IsNotNull(report.ActiveXrLoader);
        }

        private GameObject NewObject(string name)
        {
            var go = new GameObject(name);
            _spawned.Add(go);
            return go;
        }

        private static int Find(MenuPanel menu, string label)
        {
            for (int i = 0; i < menu.Actions.Count; i++)
                if (string.Equals(menu.Actions[i].Label, label, StringComparison.Ordinal))
                    return i;
            return -1;
        }

        private static void SetPrivate(object target, string name, object value) =>
            target.GetType()
                .GetField(name,
                    System.Reflection.BindingFlags.NonPublic |
                    System.Reflection.BindingFlags.Instance)
                ?.SetValue(target, value);

        private static void InvokePrivate(object target, string name) =>
            target.GetType()
                .GetMethod(name,
                    System.Reflection.BindingFlags.NonPublic |
                    System.Reflection.BindingFlags.Instance)
                ?.Invoke(target, null);

        private static void ClearPreferences()
        {
            PlayerPrefs.DeleteKey("mlomega.augmented_reality.master");
            foreach (string feature in AugmentedRealityFeatureRegistry.FeatureIds)
                PlayerPrefs.DeleteKey("mlomega.augmented_reality." + feature);
            PlayerPrefs.Save();
        }
    }
}

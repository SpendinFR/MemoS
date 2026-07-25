using System;
using System.Reflection;
using UnityEngine;

namespace MLOmega.XR.Core
{
    /// <summary>
    /// Additive, on-demand probe for the future augmented-reality service.
    ///
    /// It deliberately imports neither AR Foundation nor ARCore. The product APK
    /// keeps its current XR provider untouched; reflection only reports what is
    /// already loaded when the user explicitly enables augmented reality.
    /// </summary>
    public sealed class AugmentedRealityCapabilityProbe : MonoBehaviour
    {
        [Serializable]
        public sealed class Report
        {
            public string DeviceModel { get; set; }
            public string OperatingSystem { get; set; }
            public string ActiveXrLoader { get; set; }
            public bool XrealSdkCompiled { get; set; }
            public bool ArFoundationLoaded { get; set; }
            public bool ArcorePluginLoaded { get; set; }
            public bool ArcoreExtensionsLoaded { get; set; }
            public string CoexistenceVerdict { get; set; }
        }

        public Report LastReport { get; private set; }

        public Report Probe()
        {
            bool xrealCompiled = false;
#if XREAL_SDK_PRESENT
            xrealCompiled = true;
#endif
            LastReport = new Report
            {
                DeviceModel = SystemInfo.deviceModel ?? string.Empty,
                OperatingSystem = SystemInfo.operatingSystem ?? string.Empty,
                ActiveXrLoader = ResolveActiveLoader(),
                XrealSdkCompiled = xrealCompiled,
                ArFoundationLoaded = HasAssembly("Unity.XR.ARFoundation"),
                ArcorePluginLoaded = HasAssembly("Unity.XR.ARCore"),
                ArcoreExtensionsLoaded = HasAssembly("Google.XR.ARCoreExtensions"),
                // A package or assembly is not evidence that both providers and
                // their camera sessions coexist on the physical S24.
                CoexistenceVerdict = "unproven_physical_gate",
            };
            return LastReport;
        }

        private static bool HasAssembly(string fragment)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name = assembly.GetName().Name ?? string.Empty;
                if (name.IndexOf(fragment, StringComparison.OrdinalIgnoreCase) >= 0)
                    return true;
            }
            return false;
        }

        private static string ResolveActiveLoader()
        {
            try
            {
                Type settingsType = FindType(
                    "UnityEngine.XR.Management.XRGeneralSettings",
                    "Unity.XR.Management");
                object settings = settingsType?
                    .GetProperty("Instance", BindingFlags.Public | BindingFlags.Static)?
                    .GetValue(null);
                object manager = settingsType?
                    .GetProperty("Manager", BindingFlags.Public | BindingFlags.Instance)?
                    .GetValue(settings);
                object loader = manager?.GetType()
                    .GetProperty("activeLoader", BindingFlags.Public | BindingFlags.Instance)?
                    .GetValue(manager);
                return loader == null ? "none" : loader.GetType().FullName;
            }
            catch (Exception ex)
            {
                return "probe_error:" + ex.GetType().Name;
            }
        }

        private static Type FindType(string fullName, string assemblyFragment)
        {
            foreach (Assembly assembly in AppDomain.CurrentDomain.GetAssemblies())
            {
                string name = assembly.GetName().Name ?? string.Empty;
                if (name.IndexOf(assemblyFragment, StringComparison.OrdinalIgnoreCase) < 0)
                    continue;
                Type found = assembly.GetType(fullName, false);
                if (found != null) return found;
            }
            return null;
        }
    }
}

using UnityEngine;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Dependency-free boundary between the common PhoneOnly/UI assemblies and
    /// the optional XREAL spatial assembly. Implementations exist only in a
    /// glasses build; PhoneOnly never references AR Foundation or XR Hands.
    /// </summary>
    public interface IXrealSpatialProvider
    {
        bool TryProjectImagePoint(Vector2 imagePoint, out Vector3 worldPoint);
        bool CaptureMeasurementPoint(Vector2 viewport);
        bool PressKeyboard(Vector2 viewport, bool pinchBegin);
        bool PersistAnchorAtViewport(Vector2 viewport);
        bool SetBallisticTarget(Vector2 viewport);
        bool StartNavigation(string destination);
        bool NameCurrentIndoorPlace(string label);
        bool ImportAnchoredWorld();
    }

    /// <summary>Creator-only surface; production code never calls these methods.</summary>
    public interface IWorldCreatorSpatialProvider
    {
        bool CreatorReady { get; }
        WorldMapStore CreatorMap { get; }
        void EnableCreatorMode();
        bool TryCreatorPlacement(
            Vector2 viewport,
            out Vector3 position,
            out Quaternion rotation);
        bool PersistCreatorContent(
            Vector2 viewport,
            WorldCreatorCatalog.Entry preset,
            string label,
            string subtitle,
            Vector3 scale,
            float yawDegrees,
            string assetId);
        bool PrepareCreatorExport(out string error);
        bool RemoveCreatorContent(string worldContentId);
        event System.Action<string, bool, string> CreatorOperationCompleted;
    }
}

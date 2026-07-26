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
        bool CaptureMeasurementPoint(Vector2 viewport);
        bool PressKeyboard(Vector2 viewport, bool pinchBegin);
        bool PersistAnchorAtViewport(Vector2 viewport);
        bool SetBallisticTarget(Vector2 viewport);
        bool StartNavigation(string destination);
    }
}

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Assembly-neutral control surface used by the Atelier settings panel.
    /// The XREAL implementation owns Reflex and pointer details; the UI never
    /// acquires a reverse dependency on those platform assemblies.
    /// </summary>
    public interface IWorldCreatorInteractionSettings
    {
        bool IsGestureStandby { get; }
        bool IsRayVisible { get; }
        string TrackingStatus { get; }
        string GlassesTemperatureStatus { get; }
        void SetGestureStandby(bool standby);
        void ToggleRayVisible();
    }
}

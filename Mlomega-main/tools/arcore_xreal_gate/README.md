# AR provider gate (isolated)

This gate never runs inside the committed PhoneOnly/XREAL product scenes.

Build the disposable XREAL + AR Foundation player:

```powershell
.\scripts\BUILD_XREAL_ASSISTED.ps1 -ProviderGate -PcHost 192.168.1.199
```

The wrapper snapshots and restores the package manifest, package lock, XR
settings, generated scenes and configs. It injects AR Foundation 6.0.6 only
inside the two-pass gate build. The normal command without `-ProviderGate`
remains the unchanged XREAL product build.

Install the generated `build\android\mlomega-xreal-provider-gate.apk`, connect
the XREAL One Pro/Eye and run a paired session. The gate measures one minute of:

- the single active XR loader and running AR subsystems;
- Eye frame progress and pose tracking;
- WebRTC connection;
- render FPS, allocated memory and Android thermal status.

Pull the JSON evidence:

```powershell
adb pull /sdcard/Android/data/com.mlomega.xr.glasses/files/mlomega-ar-gates .\ar-gate-reports
.\.venv\Scripts\python.exe -m tools.arcore_xreal_gate.validate_report .\ar-gate-reports\ar-gate-*.json
```

Configured loaders are never treated as simultaneously active. XREAL is the
only provider inside the glasses player; Google ARCore/Geospatial remains an
optional, separately gated sensor boundary.

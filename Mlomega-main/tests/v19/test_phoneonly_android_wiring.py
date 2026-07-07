from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[2]
XR = ROOT / "apps/xr-mobile"


def read(relative: str) -> str:
    return (XR / relative).read_text(encoding="utf-8")


def test_unity_exports_contract_metadata_and_has_cpu_i420_fallback():
    bridge = read("Assets/Scripts/Transport/LiveTransportBridge.cs")
    assert 'sendContractMessage", JsonConvert.SerializeObject(envelope)' in bridge
    assert "PushCpuI420(texture" in bridge
    assert "pushI420Frame" in bridge
    assert "private bool _textureBacked = false" in bridge


def test_android_auth_ice_and_teardown_are_refreshable():
    plugin = read("android/livetransport/src/main/java/com/mlomega/xr/livetransport/LiveTransportPlugin.kt")
    assert "fun updateCredentials" in plugin
    assert "iceGatheringComplete.await()" in plugin
    assert "pc.localDescription ?: localDesc" in plugin
    assert 'teardownPeer("peer terminated")' in plugin
    assert 'scope.launch { teardownPeer("stopped") }' not in plugin


def test_phoneonly_project_opens_without_proprietary_xreal_tarball():
    manifest = json.loads(read("Packages/manifest.json"))
    assert "com.xreal.xr" not in manifest["dependencies"]


def test_android_network_and_plugin_export_are_explicit():
    manifest = read("Assets/Plugins/Android/AndroidManifest.xml")
    assert 'android:usesCleartextTraffic="true"' in manifest
    assert (ROOT / "scripts/BUILD_ANDROID_PLUGINS.ps1").exists()
    for module in ("livetransport", "reflexvision"):
        assert '"exportUnityRelease"' in read(f"android/{module}/build.gradle.kts")


def test_phoneonly_scene_is_separate_from_xreal_g1_gate():
    g1 = read("Assets/Scripts/Editor/G1SceneBuilder.cs")
    phone = read("Assets/Scripts/Editor/PhoneOnlySceneBuilder.cs")
    assert "PhoneOnlySessionCoordinator" not in g1
    assert "LoadOrCreatePhoneConfig" not in g1
    assert 'ScenePath = "Assets/Scenes/PhoneOnly.unity"' in phone
    assert "XrAdapterKind.PhoneOnly" in phone
    assert "PhoneOnlySessionCoordinator" in phone
    for component in (
        "PhoneCameraPreview", "SceneCache", "LocalTrackStore", "UIIntentBroker",
        "TransportIntentSource", "UIReceiptTransportSink", "UIRuntime", "StatusBar",
        "EntityHotUpdateHandler", "SceneDeltaTransportHandler", "DeviceCommandHandler",
    ):
        assert component in phone


def test_raw_scene_messages_are_not_misparsed_as_ui_intents():
    bridge = read("Assets/Scripts/Transport/LiveTransportBridge.cs")
    handler = read("Assets/Scripts/UI/SceneDeltaTransportHandler.cs")
    assert 'json.IndexOf("\\\"ui_intent_id\\\""' in bridge
    assert 'json.IndexOf("\\\"scene_delta\\\""' in handler
    assert "_sceneCache?.SubmitSceneDelta(delta);" in handler
    assert "_tracks?.SubmitSceneDelta(delta);" in handler


def test_android_session_credentials_survive_process_loss_but_clear_after_close_day():
    pairing = read("Assets/Scripts/Core/SessionPairing.cs")
    coordinator = read("Assets/Scripts/Transport/PhoneOnlySessionCoordinator.cs")
    store = read(
        "android/livetransport/src/main/java/com/mlomega/xr/livetransport/SessionCredentialStore.kt"
    )
    assert "AndroidKeyStore" in store
    assert "AES/GCM/NoPadding" in store
    assert "RestorePersistedCredentials();" in pairing
    assert "_hub.RenewToken(SessionId, Token" in pairing
    assert "_pairing.ClearPersistedSession();" in coordinator

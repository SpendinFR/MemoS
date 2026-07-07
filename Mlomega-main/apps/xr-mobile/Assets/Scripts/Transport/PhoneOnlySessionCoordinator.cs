using System;
using System.Collections;
using System.Text;
using MLOmega.XR.Core;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using UnityEngine;
using UnityEngine.Networking;

namespace MLOmega.XR.Transport
{
    /// <summary>Coordinates the real Android phone-only capture/transport lifecycle.</summary>
    public sealed class PhoneOnlySessionCoordinator : MonoBehaviour
    {
        [SerializeField] private SessionPairing _pairing;
        [SerializeField] private LiveTransportBridge _transport;
        [SerializeField] private XrSessionController _session;
        [Tooltip("Show a small maintenance button. Disable when another menu calls EndSessionAndCloseDay().")]
        [SerializeField] private bool _showMaintenanceButton = true;

        public bool EndRequested { get; private set; }
        public string EndStatus { get; private set; }
        public bool ConnectedConfirmed { get; private set; }

        private void Awake()
        {
            if (_pairing == null) _pairing = FindAnyObjectByType<SessionPairing>();
            if (_transport == null) _transport = FindAnyObjectByType<LiveTransportBridge>();
            if (_session == null) _session = FindAnyObjectByType<XrSessionController>();
        }

        private void OnEnable()
        {
            if (_pairing != null) _pairing.StateChanged += OnPairingStateChanged;
            if (_session != null) _session.SessionStateChanged += OnSessionStateChanged;
            if (_transport != null) _transport.StateChanged += OnTransportStateChanged;
            TryStartTransport();
        }

        private void OnDisable()
        {
            if (_pairing != null) _pairing.StateChanged -= OnPairingStateChanged;
            if (_session != null) _session.SessionStateChanged -= OnSessionStateChanged;
            if (_transport != null) _transport.StateChanged -= OnTransportStateChanged;
            // Lifecycle loss is not an explicit end: never call /session/end here.
        }

        private void OnPairingStateChanged(PairingState state)
        {
            if (state == PairingState.Paired) TryStartTransport();
        }

        private void OnSessionStateChanged(XrSessionState state)
        {
            if (state == XrSessionState.Running) TryStartTransport();
        }

        private void OnTransportStateChanged(LiveTransportState state, string detail)
        {
            ConnectedConfirmed = state == LiveTransportState.Connected || state == LiveTransportState.Degraded;
            EndStatus = EndRequested ? EndStatus : $"transport:{state} {detail}";
        }

        private void TryStartTransport()
        {
#if UNITY_ANDROID && !UNITY_EDITOR
            if (!EndRequested && _pairing != null && _pairing.State == PairingState.Paired &&
                _session != null && _session.Adapter is PhoneOnlyAdapter)
            {
                if (_session.State == XrSessionState.Running && _session.Adapter.IsEyeActive)
                    _transport?.StartTransport();
            }
#endif
        }

        public void EndSessionAndCloseDay()
        {
            if (EndRequested || _pairing == null || !_pairing.TryGetActiveSession(out var sid, out var token))
                return;
            EndRequested = true;
            StartCoroutine(EndExplicitly(sid, token));
        }

        private IEnumerator EndExplicitly(string sessionId, string token)
        {
            EndStatus = "requesting";
            string url = _pairing.ActiveBaseUrl.TrimEnd('/') + "/session/end";
            byte[] body = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(new { session_id = sessionId, token }));
            using var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST);
            req.uploadHandler = new UploadHandlerRaw(body);
            req.downloadHandler = new DownloadHandlerBuffer();
            req.SetRequestHeader("Content-Type", "application/json");
            var operation = req.SendWebRequest();
            // The authenticated request is now in flight; stop capture/audio so
            // the PC's bounded drain can finish before end_session + CloseDay.
            yield return null;
            _transport?.StopTransport();
            _session?.StopSession();
            yield return operation;
            if (req.result == UnityWebRequest.Result.Success)
            {
                EndStatus = req.downloadHandler.text;
                yield return PollCloseDay(sessionId);
            }
            else
            {
                EndStatus = $"error {req.responseCode}: {req.error}";
                EndRequested = false; // authenticated request can be retried explicitly
                Debug.LogError("[PhoneOnly] " + EndStatus);
            }
        }

        private IEnumerator PollCloseDay(string sessionId)
        {
            while (true)
            {
                yield return new WaitForSecondsRealtime(2f);
                if (_pairing == null || string.IsNullOrEmpty(_pairing.Token)) yield break;
                string url = _pairing.ActiveBaseUrl.TrimEnd('/') + "/session/status";
                byte[] body = Encoding.UTF8.GetBytes(JsonConvert.SerializeObject(new
                {
                    session_id = sessionId,
                    token = _pairing.Token
                }));
                using var req = new UnityWebRequest(url, UnityWebRequest.kHttpVerbPOST);
                req.uploadHandler = new UploadHandlerRaw(body);
                req.downloadHandler = new DownloadHandlerBuffer();
                req.SetRequestHeader("Content-Type", "application/json");
                yield return req.SendWebRequest();
                if (req.result != UnityWebRequest.Result.Success)
                {
                    EndStatus = $"status retry: {req.responseCode} {req.error}";
                    continue;
                }
                EndStatus = req.downloadHandler.text;
                var status = JObject.Parse(EndStatus).Value<string>("close_day");
                if (status == "completed")
                {
                    _pairing.ClearPersistedSession();
                    Debug.Log("[PhoneOnly] CloseDay completed: " + EndStatus);
                    yield break;
                }
                if (status == "error" || status == "blocked")
                {
                    EndRequested = false; // expose the button for an explicit retry
                    Debug.LogError("[PhoneOnly] CloseDay requires retry: " + EndStatus);
                    yield break;
                }
            }
        }

        private void OnGUI()
        {
            if (!_showMaintenanceButton || EndRequested) return;
            if (GUI.Button(new Rect(16, Screen.height - 64, 300, 48), "Terminer la session et lancer CloseDay"))
                EndSessionAndCloseDay();
        }
    }
}

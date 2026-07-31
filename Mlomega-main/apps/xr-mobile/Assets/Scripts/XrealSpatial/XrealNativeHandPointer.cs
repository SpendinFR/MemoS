using System.Collections.Generic;
using MLOmega.XR.Core;
using MLOmega.XR.Reflex;
using MLOmega.XR.UI.Components;
using Unity.XR.XREAL;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.XR.Hands;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Native XREAL/XR Hands pointer for the product menu and the isolated
    /// World Atelier deck. On One Pro + Eye, where the SDK exposes no native
    /// hand subsystem, the existing gaze ray remains the pointer and the
    /// on-device MediaPipe pinch becomes its select/grab button.
    ///
    /// Point with the index and pinch thumb-to-index to click. Two thresholds
    /// provide hysteresis so a noisy pinch cannot emit repeated clicks. Touch
    /// input remains active as a fallback.
    /// </summary>
    public sealed class XrealNativeHandPointer :
        MonoBehaviour,
        IWorldCreatorInteractionSettings
    {
        [SerializeField] private Camera _camera;
        [SerializeField] private WorldCreatorController _creator;
        [SerializeField] private GestureBridge _eyeGestures;
        [SerializeField] private StreamingAssetsModelInstaller _modelInstaller;
        [SerializeField] private bool _activateEyeGesturesContinuously;
        [SerializeField] private bool _allowPhoneController = true;

        private readonly List<XRHandSubsystem> _subsystems =
            new List<XRHandSubsystem>();
        private readonly List<RaycastResult> _uiHits =
            new List<RaycastResult>(16);
        private readonly RaycastHit[] _physicalUiHits = new RaycastHit[64];
        private XROrigin _origin;
        private MenuPanel _menu;
        private EventSystem _events;
        private PointerEventData _pointer;
        private GameObject _hover;
        private GameObject _pressed;
        private LineRenderer _laser;
        private Transform _cursor;
        private bool _pinching;
        private bool _hasSmoothedRay;
        private bool _loggedRunningSubsystem;
        private bool _loggedTrackedHand;
        private bool _phoneControllerSubscribed;
        private bool _phoneTouchActive;
        private bool _phoneTriggerPressed;
        private bool _eyePinching;
        private bool _deckPinchClaimed;
        private Vector2 _eyeGesturePoint = new Vector2(-1f, -1f);
        private float _eyeGestureZoom = 1f;
        private Vector2 _phonePointerViewport = new Vector2(.5f, .5f);
        private XREALVirtualController _phoneController;
        private Vector3 _smoothedOrigin;
        private Vector3 _smoothedDirection;
        private float _nextSubsystemLookupAt;
        private bool _rayVisible;
        private const string RayVisiblePreference =
            "mlomega.atelier.eye_ray_visible.v1";

        public bool IsRayVisible => _rayVisible;
        public bool IsGestureStandby =>
            _eyeGestures != null && _eyeGestures.IsInteractionStandby;

        private void Awake()
        {
            if (_camera == null) _camera = Camera.main;
            if (_creator == null)
                _creator = FindAnyObjectByType<WorldCreatorController>();
            _menu = FindAnyObjectByType<MenuPanel>();
            _origin = FindAnyObjectByType<XROrigin>();
            if (_eyeGestures == null)
                _eyeGestures = FindAnyObjectByType<GestureBridge>();
            if (_modelInstaller == null)
                _modelInstaller = FindAnyObjectByType<StreamingAssetsModelInstaller>();
            // A point cursor is enough for precise gaze+pinch selection. Keep the
            // long Eye ray opt-in because it is visually intrusive in OST lenses.
            _rayVisible = PlayerPrefs.GetInt(RayVisiblePreference, 0) == 1;
            EnsurePointerInfrastructure();
            BuildCursor();
        }

        public void SetRayVisible(bool visible)
        {
            _rayVisible = visible;
            PlayerPrefs.SetInt(RayVisiblePreference, visible ? 1 : 0);
            PlayerPrefs.Save();
            if (_laser != null && !visible) _laser.enabled = false;
        }

        public void ToggleRayVisible() => SetRayVisible(!_rayVisible);

        public void SetGestureStandby(bool standby)
        {
            if (_eyeGestures == null)
                _eyeGestures = FindAnyObjectByType<GestureBridge>();
            if (_eyeGestures == null) return;
            _eyeGestures.SetInteractionStandby(standby);
            _eyePinching = false;
            if (_deckPinchClaimed && _creator != null)
                _creator.EndDeckManipulation();
            _deckPinchClaimed = false;
            ReleasePointer(false);
            if (_creator != null) _creator.SetGestureStandby(standby);
        }

        private void OnEnable()
        {
            if (_eyeGestures == null)
                _eyeGestures = FindAnyObjectByType<GestureBridge>();
            if (_eyeGestures != null)
                _eyeGestures.GestureRecognized += OnEyeGesture;
            if (!_activateEyeGesturesContinuously || _eyeGestures == null) return;
            if (_modelInstaller == null)
                _modelInstaller = FindAnyObjectByType<StreamingAssetsModelInstaller>();
            if (_modelInstaller == null || _modelInstaller.Done)
                ActivateEyeGestures();
            else
                _modelInstaller.Completed += ActivateEyeGestures;
        }

        private void OnDisable()
        {
            if (_modelInstaller != null)
                _modelInstaller.Completed -= ActivateEyeGestures;
            if (_eyeGestures != null)
            {
                _eyeGestures.GestureRecognized -= OnEyeGesture;
                if (_activateEyeGesturesContinuously)
                    _eyeGestures.Deactivate();
            }
            _eyePinching = false;
            if (_deckPinchClaimed && _creator != null)
                _creator.EndDeckManipulation();
            _deckPinchClaimed = false;
            UnsubscribePhoneController();
            ReleasePointer(false);
            SetCursorVisible(false);
        }

        private void OnDestroy()
        {
            if (_laser != null && _laser.material != null)
                Destroy(_laser.material);
            if (_cursor != null)
            {
                var renderer = _cursor.GetComponent<Renderer>();
                if (renderer != null && renderer.material != null)
                    Destroy(renderer.material);
            }
        }

        private void Update()
        {
            EnsurePointerInfrastructure();
            if (_allowPhoneController)
                EnsurePhoneController();
            else if (_phoneControllerSubscribed)
                UnsubscribePhoneController();
            // A closed Atelier must be optically empty. The palm callback still
            // runs through GestureBridge and can reopen it without a cursor.
            if (_creator != null && _creator.IsDeckClosed)
            {
                ReleasePointer(false);
                SetCursorVisible(false);
                _hasSmoothedRay = false;
                return;
            }
            // In low-power gesture standby, hide the Eye ray/cursor completely.
            // A deliberate S24 touch remains an available independent fallback.
            if (
                _eyeGestures != null &&
                _eyeGestures.IsInteractionStandby &&
                (!_allowPhoneController ||
                 (!_phoneTouchActive && !_phoneTriggerPressed)))
            {
                ReleasePointer(false);
                SetCursorVisible(false);
                _hasSmoothedRay = false;
                return;
            }
            bool hasPointer = TryGetHandRay(
                out Ray handRay,
                out bool pinching);
            // A subscribed XREALVirtualController exists even while the S24
            // touch surface is idle.  Treating that idle singleton as a live
            // pointer made it permanently win over head gaze, so Eye pinches
            // clicked the last phone coordinate instead of what the user was
            // looking at.  Phone input still takes priority while it is
            // actively touched/pressed, then gaze resumes automatically.
            if (
                _allowPhoneController &&
                !hasPointer &&
                (_phoneTouchActive || _phoneTriggerPressed))
                hasPointer = TryGetPhonePointer(out handRay, out pinching);
            if (!hasPointer)
                hasPointer = TryGetGazePointer(out handRay, out pinching);
            if (!hasPointer && _allowPhoneController)
                hasPointer = TryGetPhonePointer(out handRay, out pinching);
            if (
                _camera == null ||
                _events == null ||
                !hasPointer)
            {
                ReleasePointer(false);
                SetCursorVisible(false);
                _hasSmoothedRay = false;
                return;
            }

            float blend = 1f - Mathf.Exp(-20f * Time.unscaledDeltaTime);
            if (!_hasSmoothedRay)
            {
                _smoothedOrigin = handRay.origin;
                _smoothedDirection = handRay.direction;
                _hasSmoothedRay = true;
            }
            else
            {
                _smoothedOrigin = Vector3.Lerp(
                    _smoothedOrigin, handRay.origin, blend);
                _smoothedDirection = Vector3.Slerp(
                    _smoothedDirection, handRay.direction, blend).normalized;
            }
            handRay = new Ray(_smoothedOrigin, _smoothedDirection);

            Vector2 screenPoint = default;
            Vector3 worldHit = default;
            GameObject physicalTarget = null;
            bool physicalHit = TryGetPhysicalUiTarget(
                handRay,
                out worldHit,
                out physicalTarget);
            bool deckHit = physicalHit;
            if (physicalHit)
            {
                screenPoint = RectTransformUtility.WorldToScreenPoint(
                    _camera,
                    worldHit);
            }
            else
            {
                deckHit =
                    _creator != null &&
                    _creator.TryProjectDeckPointer(
                        handRay,
                        out screenPoint,
                        out worldHit);
            }
            if (!deckHit)
            {
                Vector3 projected =
                    _camera.WorldToScreenPoint(handRay.GetPoint(2.5f));
                if (projected.z <= 0f)
                {
                    ReleasePointer(false);
                    SetCursorVisible(false);
                    return;
                }
                screenPoint = new Vector2(projected.x, projected.y);
                worldHit = handRay.GetPoint(1.25f);
            }

            UpdateEventPointer(
                screenPoint,
                deckHit,
                worldHit,
                physicalTarget);
            UpdateProductMenu(screenPoint, pinching);
            if (_creator != null)
                _creator.UpdateDeckManipulationHover(worldHit, deckHit);
            SetCursor(
                handRay.origin,
                worldHit,
                deckHit || (_menu != null && _menu.IsOpen));

            if (pinching && !_pinching)
            {
                Debug.Log(
                    "[XrealNativeHandPointer] pinch press: " +
                    $"deckHit={deckHit}, hover={(_hover != null ? _hover.name : "<none>")}, " +
                    $"gaze={_eyePinching}, phone={_phoneTriggerPressed}");
                _deckPinchClaimed =
                    _eyePinching &&
                    _creator != null &&
                    _creator.TryBeginDeckManipulation(
                        worldHit,
                        _eyeGesturePoint,
                        _eyeGestureZoom);
                if (!_deckPinchClaimed) PressPointer();
            }
            else if (pinching && _pinching && _deckPinchClaimed)
            {
                _creator.UpdateDeckManipulation(
                    _eyeGesturePoint,
                    _eyeGestureZoom);
            }
            else if (!pinching && _pinching)
            {
                if (_deckPinchClaimed)
                    _creator.EndDeckManipulation();
                else
                    ReleasePointer(true);
                _deckPinchClaimed = false;
            }
            _pinching = pinching;
        }

        private void ActivateEyeGestures()
        {
            if (_modelInstaller != null)
                _modelInstaller.Completed -= ActivateEyeGestures;
            if (_activateEyeGesturesContinuously && _eyeGestures != null)
            {
                _eyeGestures.Activate();
                Debug.Log(
                    "[XrealNativeHandPointer] Eye MediaPipe armed: " +
                    "head gaze aims, physical hand pinch selects.");
            }
        }

        private void OnEyeGesture(GestureEvent ev)
        {
            if (ev.ScreenPoint.x >= 0f && ev.ScreenPoint.y >= 0f)
                _eyeGesturePoint = ev.ScreenPoint;
            if (ev.ZoomFactor > 0f) _eyeGestureZoom = ev.ZoomFactor;
            switch (ev.Kind)
            {
                case GestureKind.PinchBegin:
                case GestureKind.PinchUpdate:
                    _eyePinching = true;
                    break;
                case GestureKind.PinchEnd:
                    _eyePinching = false;
                    break;
                case GestureKind.OpenPalmMenu:
                    if (_creator != null)
                        _creator.OpenDeckFromPalm();
                    break;
                case GestureKind.TwoPalmMenu:
                    if (_creator != null)
                        _creator.OpenWindowDockFromTwoPalms();
                    break;
                case GestureKind.FistToggle:
                    _eyePinching = false;
                    if (_deckPinchClaimed && _creator != null)
                        _creator.EndDeckManipulation();
                    _deckPinchClaimed = false;
                    ReleasePointer(false);
                    if (_creator != null && _eyeGestures != null)
                        _creator.SetGestureStandby(
                            _eyeGestures.IsInteractionStandby);
                    break;
            }
        }

        private void EnsurePointerInfrastructure()
        {
            _events = EventSystem.current;
            if (_pointer == null && _events != null)
                _pointer = new PointerEventData(_events)
                {
                    pointerId = -22001,
                    button = PointerEventData.InputButton.Left,
                };
        }

        private bool TryGetHandRay(out Ray ray, out bool pinching)
        {
            ray = default;
            pinching = false;
            if (Time.unscaledTime >= _nextSubsystemLookupAt)
            {
                _nextSubsystemLookupAt = Time.unscaledTime + 1f;
                _subsystems.Clear();
                SubsystemManager.GetSubsystems(_subsystems);
            }
            foreach (XRHandSubsystem subsystem in _subsystems)
            {
                if (subsystem == null || !subsystem.running) continue;
                if (!_loggedRunningSubsystem)
                {
                    Debug.Log(
                        "[XrealNativeHandPointer] XR Hands subsystem running; " +
                        "point with an index and pinch to select.");
                    _loggedRunningSubsystem = true;
                }
                if (TryGetHandRay(subsystem.rightHand, out ray, out pinching))
                {
                    LogTrackedHandOnce("right");
                    return true;
                }
                if (TryGetHandRay(subsystem.leftHand, out ray, out pinching))
                {
                    LogTrackedHandOnce("left");
                    return true;
                }
            }
            return false;
        }

        private void EnsurePhoneController()
        {
            if (
                _phoneControllerSubscribed &&
                _phoneController == XREALVirtualController.Singleton)
                return;
            UnsubscribePhoneController();
            _phoneController = XREALVirtualController.Singleton;
            if (_phoneController == null) return;
            _phoneController.pointerDown += OnPhonePointerDown;
            _phoneController.pointerUp += OnPhonePointerUp;
            _phoneController.pointerDrag += OnPhonePointerDrag;
            _phoneController.pointerEndDrag += OnPhonePointerEndDrag;
            _phoneControllerSubscribed = true;
            Debug.Log(
                "[XrealNativeHandPointer] S24 touchpad fallback ready; " +
                "drag to aim and tap to select.");
        }

        private void UnsubscribePhoneController()
        {
            if (_phoneController != null && _phoneControllerSubscribed)
            {
                _phoneController.pointerDown -= OnPhonePointerDown;
                _phoneController.pointerUp -= OnPhonePointerUp;
                _phoneController.pointerDrag -= OnPhonePointerDrag;
                _phoneController.pointerEndDrag -= OnPhonePointerEndDrag;
            }
            _phoneControllerSubscribed = false;
            _phoneController = null;
            _phoneTouchActive = false;
            _phoneTriggerPressed = false;
        }

        private void OnPhonePointerDown(
            XREALButtonType type,
            GameObject target,
            PointerEventData eventData)
        {
            if (type == XREALButtonType.TriggerButton)
                _phoneTriggerPressed = true;
            if (type == XREALButtonType.Primary2DAxis)
            {
                _phoneTouchActive = true;
                UpdatePhoneViewport(target, eventData);
            }
        }

        private void OnPhonePointerUp(
            XREALButtonType type,
            GameObject target,
            PointerEventData eventData)
        {
            if (type == XREALButtonType.TriggerButton)
                _phoneTriggerPressed = false;
        }

        private void OnPhonePointerDrag(
            XREALButtonType type,
            GameObject target,
            PointerEventData eventData)
        {
            if (type != XREALButtonType.Primary2DAxis) return;
            _phoneTouchActive = true;
            UpdatePhoneViewport(target, eventData);
        }

        private void OnPhonePointerEndDrag(
            XREALButtonType type,
            GameObject target,
            PointerEventData eventData)
        {
            if (type == XREALButtonType.Primary2DAxis)
                _phoneTouchActive = false;
        }

        private void UpdatePhoneViewport(
            GameObject target,
            PointerEventData eventData)
        {
            if (
                target == null ||
                eventData == null ||
                !(target.transform is RectTransform rect) ||
                !RectTransformUtility.ScreenPointToLocalPointInRectangle(
                    rect,
                    eventData.position,
                    eventData.pressEventCamera,
                    out Vector2 local))
                return;
            Rect bounds = rect.rect;
            float x = Mathf.InverseLerp(bounds.xMin, bounds.xMax, local.x);
            float y = Mathf.InverseLerp(bounds.yMin, bounds.yMax, local.y);
            // Leave a small comfort margin so the cursor cannot disappear
            // behind the optical display's edge.
            _phonePointerViewport = new Vector2(
                Mathf.Lerp(.06f, .94f, x),
                Mathf.Lerp(.06f, .94f, y));
        }

        private bool TryGetPhonePointer(out Ray ray, out bool pressing)
        {
            ray = default;
            pressing = false;
            if (_camera == null || !_phoneControllerSubscribed) return false;
            ray = _camera.ViewportPointToRay(new Vector3(
                _phonePointerViewport.x,
                _phonePointerViewport.y,
                0f));
            pressing = _phoneTriggerPressed || _eyePinching;
            // Keep the cursor visible at its last position so the user always
            // knows what a tap will select, even between touch movements.
            return true;
        }

        private bool TryGetGazePointer(out Ray ray, out bool pressing)
        {
            ray = default;
            pressing = false;
            if (
                _camera == null ||
                _eyeGestures == null ||
                !_eyeGestures.IsRunning ||
                _eyeGestures.IsInteractionStandby)
                return false;
            ray = _camera.ViewportPointToRay(new Vector3(.5f, .5f, 0f));
            pressing = _eyePinching;
            return true;
        }

        private bool TryGetPhysicalUiTarget(
            Ray ray,
            out Vector3 worldPoint,
            out GameObject target)
        {
            worldPoint = default;
            target = null;
            int count = Physics.RaycastNonAlloc(
                ray,
                _physicalUiHits,
                4f,
                ~0,
                QueryTriggerInteraction.Collide);
            float nearest = float.MaxValue;
            for (int i = 0; i < count; i++)
            {
                RaycastHit hit = _physicalUiHits[i];
                if (hit.collider == null || hit.distance >= nearest) continue;
                GameObject handler =
                    ExecuteEvents.GetEventHandler<IPointerClickHandler>(
                        hit.collider.gameObject);
                if (handler == null) continue;
                nearest = hit.distance;
                worldPoint = hit.point;
                target = handler;
            }
            return target != null;
        }

        private void LogTrackedHandOnce(string handedness)
        {
            if (_loggedTrackedHand) return;
            Debug.Log(
                "[XrealNativeHandPointer] Native " + handedness +
                " hand tracked; pinch interaction is active.");
            _loggedTrackedHand = true;
        }

        private bool TryGetHandRay(
            XRHand hand,
            out Ray ray,
            out bool pinching)
        {
            ray = default;
            pinching = false;
            if (!hand.isTracked) return false;
            if (
                !TryWorldJoint(
                    hand, XRHandJointID.IndexProximal, out Vector3 indexBase) ||
                !TryWorldJoint(
                    hand, XRHandJointID.IndexTip, out Vector3 indexTip) ||
                !TryWorldJoint(
                    hand, XRHandJointID.ThumbTip, out Vector3 thumbTip) ||
                !TryWorldJoint(
                    hand, XRHandJointID.Wrist, out Vector3 wrist) ||
                !TryWorldJoint(
                    hand, XRHandJointID.MiddleProximal, out Vector3 middleBase))
                return false;
            Vector3 direction = indexTip - indexBase;
            if (direction.sqrMagnitude < .0001f) return false;

            float handScale = Mathf.Clamp(
                Vector3.Distance(wrist, middleBase), .055f, .11f);
            float engage = Mathf.Clamp(handScale * .32f, .018f, .031f);
            float release = Mathf.Clamp(engage * 1.45f, .027f, .045f);
            float pinchDistance = Vector3.Distance(indexTip, thumbTip);
            pinching = _pinching
                ? pinchDistance <= release
                : pinchDistance <= engage;
            ray = new Ray(indexBase, direction.normalized);
            return true;
        }

        private bool TryWorldJoint(
            XRHand hand,
            XRHandJointID id,
            out Vector3 world)
        {
            world = default;
            XRHandJoint joint = hand.GetJoint(id);
            if (!joint.TryGetPose(out Pose pose)) return false;
            Transform tracking =
                _origin != null ? _origin.TrackablesParent : null;
            world = tracking != null
                ? tracking.TransformPoint(pose.position)
                : pose.position;
            return true;
        }

        private void UpdateEventPointer(
            Vector2 screenPoint,
            bool raycastUi,
            Vector3 worldPoint,
            GameObject physicalTarget)
        {
            if (_pointer == null) return;
            _pointer.delta = screenPoint - _pointer.position;
            _pointer.position = screenPoint;
            GameObject next = physicalTarget;
            if (raycastUi)
            {
                if (next == null)
                {
                    _uiHits.Clear();
                    _events.RaycastAll(_pointer, _uiHits);
                    foreach (RaycastResult hit in _uiHits)
                    {
                        if (hit.gameObject == null) continue;
                        next = hit.gameObject;
                        _pointer.pointerCurrentRaycast = hit;
                        break;
                    }
                }
                if (
                    next == null &&
                    _creator != null &&
                    _creator.TryResolveDeckTarget(worldPoint, out next))
                {
                    _pointer.pointerCurrentRaycast = new RaycastResult
                    {
                        gameObject = next,
                        screenPosition = screenPoint,
                        worldPosition = worldPoint,
                    };
                }
                else if (physicalTarget != null)
                {
                    _pointer.pointerCurrentRaycast = new RaycastResult
                    {
                        gameObject = physicalTarget,
                        screenPosition = screenPoint,
                        worldPosition = worldPoint,
                    };
                }
            }
            SetHover(next);
        }

        private void SetHover(GameObject rawTarget)
        {
            GameObject next = rawTarget == null
                ? null
                : ExecuteEvents.GetEventHandler<IPointerEnterHandler>(
                    rawTarget);
            if (next == _hover) return;
            if (_hover != null)
                ExecuteEvents.Execute(
                    _hover, _pointer, ExecuteEvents.pointerExitHandler);
            _hover = next;
            _pointer.pointerEnter = next;
            if (_hover != null)
                ExecuteEvents.Execute(
                    _hover, _pointer, ExecuteEvents.pointerEnterHandler);
        }

        private void PressPointer()
        {
            if (_hover == null || _pointer == null) return;
            _pointer.pressPosition = _pointer.position;
            _pointer.pointerPressRaycast = _pointer.pointerCurrentRaycast;
            _pointer.eligibleForClick = true;
            _pressed = ExecuteEvents.ExecuteHierarchy(
                _hover, _pointer, ExecuteEvents.pointerDownHandler);
            if (_pressed == null)
                _pressed =
                    ExecuteEvents.GetEventHandler<IPointerClickHandler>(_hover);
            _pointer.pointerPress = _pressed;
            _pointer.rawPointerPress = _hover;
            if (_pressed != null)
                _events.SetSelectedGameObject(_pressed, _pointer);
        }

        private void ReleasePointer(bool allowClick)
        {
            if (_pointer != null && _pressed != null)
            {
                ExecuteEvents.Execute(
                    _pressed, _pointer, ExecuteEvents.pointerUpHandler);
                GameObject click =
                    _hover == null
                        ? null
                        : ExecuteEvents.GetEventHandler<IPointerClickHandler>(
                            _hover);
                if (
                    allowClick &&
                    _pointer.eligibleForClick &&
                    click == _pressed)
                {
                    ExecuteEvents.Execute(
                        _pressed,
                        _pointer,
                        ExecuteEvents.pointerClickHandler);
                }
            }
            if (_pointer != null)
            {
                _pointer.eligibleForClick = false;
                _pointer.pointerPress = null;
                _pointer.rawPointerPress = null;
            }
            _pressed = null;
            _pinching = false;
        }

        private void UpdateProductMenu(
            Vector2 screenPoint,
            bool pinching)
        {
            if (_menu == null || !_menu.IsOpen || _camera == null) return;
            Vector2 viewport = new Vector2(
                Mathf.Clamp01(screenPoint.x / Mathf.Max(1f, Screen.width)),
                Mathf.Clamp01(screenPoint.y / Mathf.Max(1f, Screen.height)));
            _menu.HoverAtViewport(viewport);
            if (_pinching && !pinching) _menu.PinchCommit();
        }

        private void BuildCursor()
        {
            var line = new GameObject("XREAL Hand Ray");
            line.transform.SetParent(transform, false);
            _laser = line.AddComponent<LineRenderer>();
            _laser.useWorldSpace = true;
            _laser.positionCount = 2;
            _laser.widthMultiplier = .004f;
            _laser.numCapVertices = 5;
            _laser.startColor = new Color(.1f, 1f, .9f, .75f);
            _laser.endColor = new Color(.7f, .2f, 1f, .95f);
            Shader shader = Shader.Find("Sprites/Default");
            if (shader != null) _laser.material = new Material(shader);

            GameObject cursor = GameObject.CreatePrimitive(
                PrimitiveType.Sphere);
            cursor.name = "XREAL Hand Cursor";
            cursor.transform.SetParent(transform, false);
            cursor.transform.localScale = Vector3.one * .018f;
            Collider collider = cursor.GetComponent<Collider>();
            if (collider != null) Destroy(collider);
            Renderer renderer = cursor.GetComponent<Renderer>();
            Shader unlit = Shader.Find("MLOmega/XREAL Runtime Unlit") ??
                Shader.Find("Unlit/Color");
            if (renderer != null && unlit != null)
            {
                renderer.material = new Material(unlit);
                renderer.material.color = new Color(.2f, 1f, .88f, .95f);
            }
            _cursor = cursor.transform;
            SetCursorVisible(false);
        }

        private void SetCursor(
            Vector3 origin,
            Vector3 hit,
            bool visible)
        {
            SetCursorVisible(visible);
            if (!visible) return;
            _laser.SetPosition(0, origin);
            _laser.SetPosition(1, hit);
            _cursor.position = hit;
            float pulse = .016f +
                .004f * Mathf.Sin(Time.unscaledTime * 6f);
            _cursor.localScale = Vector3.one * pulse;
        }

        private void SetCursorVisible(bool visible)
        {
            if (_laser != null) _laser.enabled = visible && _rayVisible;
            if (_cursor != null) _cursor.gameObject.SetActive(visible);
        }
    }
}

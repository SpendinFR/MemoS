using System.Collections.Generic;
using MLOmega.XR.UI.Components;
using Unity.XR.CoreUtils;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.XR.Hands;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Native XREAL/XR Hands pointer for the product menu and the isolated
    /// World Atelier deck. It does not consume Eye RGB frames and therefore
    /// remains independent from the MediaPipe/transport gesture path.
    ///
    /// Point with the index and pinch thumb-to-index to click. Two thresholds
    /// provide hysteresis so a noisy pinch cannot emit repeated clicks. Touch
    /// input remains active as a fallback.
    /// </summary>
    public sealed class XrealNativeHandPointer : MonoBehaviour
    {
        [SerializeField] private Camera _camera;
        [SerializeField] private WorldCreatorController _creator;

        private readonly List<XRHandSubsystem> _subsystems =
            new List<XRHandSubsystem>();
        private readonly List<RaycastResult> _uiHits =
            new List<RaycastResult>(16);
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
        private Vector3 _smoothedOrigin;
        private Vector3 _smoothedDirection;
        private float _nextSubsystemLookupAt;

        private void Awake()
        {
            if (_camera == null) _camera = Camera.main;
            if (_creator == null)
                _creator = FindAnyObjectByType<WorldCreatorController>();
            _menu = FindAnyObjectByType<MenuPanel>();
            _origin = FindAnyObjectByType<XROrigin>();
            EnsurePointerInfrastructure();
            BuildCursor();
        }

        private void OnDisable()
        {
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
            if (
                _camera == null ||
                _events == null ||
                !TryGetHandRay(
                    out Ray handRay,
                    out bool pinching))
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
            bool deckHit =
                _creator != null &&
                _creator.TryProjectDeckPointer(
                    handRay,
                    out screenPoint,
                    out worldHit);
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

            UpdateEventPointer(screenPoint, deckHit);
            UpdateProductMenu(screenPoint, pinching);
            SetCursor(
                handRay.origin,
                worldHit,
                deckHit || (_menu != null && _menu.IsOpen));

            if (pinching && !_pinching)
                PressPointer();
            else if (!pinching && _pinching)
                ReleasePointer(true);
            _pinching = pinching;
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
                if (TryGetHandRay(subsystem.rightHand, out ray, out pinching))
                    return true;
                if (TryGetHandRay(subsystem.leftHand, out ray, out pinching))
                    return true;
            }
            return false;
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

        private void UpdateEventPointer(Vector2 screenPoint, bool raycastUi)
        {
            if (_pointer == null) return;
            _pointer.delta = screenPoint - _pointer.position;
            _pointer.position = screenPoint;
            GameObject next = null;
            if (raycastUi)
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
            Shader unlit = Shader.Find("Universal Render Pipeline/Unlit") ??
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
            if (_laser != null) _laser.enabled = visible;
            if (_cursor != null) _cursor.gameObject.SetActive(visible);
        }
    }
}

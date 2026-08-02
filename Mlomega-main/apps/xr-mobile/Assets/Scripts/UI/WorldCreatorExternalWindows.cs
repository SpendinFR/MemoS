using System;
using System.Collections.Generic;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Optional spatial surfaces hosted by the proven Atelier window system.
    /// With no registered surface every Product/Atelier branch is unchanged.
    /// The Browser Lab uses this seam instead of maintaining a second pointer,
    /// grab, smoothing or chrome implementation.
    /// </summary>
    public sealed partial class WorldCreatorController
    {
        private sealed class ExternalSpatialWindowState
        {
            public string Id;
            public string LayoutPrefix;
            public RectTransform Rect;
            public Action Close;
            public Action<Vector2, bool> Resize;
            public readonly List<Graphic> HitGraphics = new List<Graphic>();
            public Image Move;
            public Image ResizeLeft;
            public Image ResizeRight;
            public Image Depth;
            public Image Tilt;
            public Image FreeResize;
            public TextMeshProUGUI CloseHandle;
        }

        private readonly List<ExternalSpatialWindowState> _externalSpatialWindows =
            new List<ExternalSpatialWindowState>();
        private ExternalSpatialWindowState _hoverExternalWindow;
        private ExternalSpatialWindowState _activeExternalWindow;
        private ExternalSpatialWindowState _lastExternalWindow;
        private ExternalSpatialWindowState _externalAffordanceWindow;

        public void RegisterExternalSpatialWindow(
            RectTransform rect,
            string id,
            Action close,
            Action<Vector2, bool> resize = null)
        {
            if (rect == null) throw new ArgumentNullException(nameof(rect));
            ExternalSpatialWindowState existing = ExternalWindowFor(rect);
            if (existing != null)
            {
                existing.Close = close;
                existing.Resize = resize;
                FocusExternalSpatialWindow(rect);
                return;
            }

            var state = new ExternalSpatialWindowState
            {
                Id = string.IsNullOrWhiteSpace(id) ? rect.name : id.Trim(),
                Rect = rect,
                Close = close,
                Resize = resize,
            };
            state.LayoutPrefix =
                "mlomega.atelier.external." + SanitizeLayoutId(state.Id) + ".v1.";
            BuildExternalWindowHandles(state);
            state.Rect.GetComponentsInChildren(true, state.HitGraphics);
            _externalSpatialWindows.Add(state);
            RestoreExternalWindowLayout(state);
            _activeExternalWindow = state;
            _lastExternalWindow = state;
            _lastWindow = DeckWindowKind.External;
            RevealExternalWindowAffordances(state);
        }

        public void RefreshExternalSpatialWindow(RectTransform rect)
        {
            ExternalSpatialWindowState state = ExternalWindowFor(rect);
            if (state == null) return;
            // The browser can change its footprint when entering/leaving XR.
            // Keep the shared Atelier affordances attached to the new outer
            // bounds before rebuilding the hit list.
            LayoutExternalWindowHandles(state);
            state.HitGraphics.Clear();
            rect.GetComponentsInChildren(true, state.HitGraphics);
        }

        public void FocusExternalSpatialWindow(RectTransform rect)
        {
            ExternalSpatialWindowState state = ExternalWindowFor(rect);
            if (state == null) return;
            _activeExternalWindow = state;
            _lastExternalWindow = state;
            _lastWindow = DeckWindowKind.External;
            DismissWindowDock();
        }

        public void UnregisterExternalSpatialWindow(RectTransform rect)
        {
            ExternalSpatialWindowState state = ExternalWindowFor(rect);
            if (state == null) return;
            if (_activeExternalWindow == state && IsDeckManipulating)
                EndDeckManipulation();
            _externalSpatialWindows.Remove(state);
            if (_hoverExternalWindow == state) _hoverExternalWindow = null;
            if (_activeExternalWindow == state) _activeExternalWindow = null;
            if (_lastExternalWindow == state)
                _lastExternalWindow = LastVisibleExternalWindow();
            if (_externalAffordanceWindow == state)
                _externalAffordanceWindow = null;
        }

        public void DismissWindowDock()
        {
            if (_windowDock != null) _windowDock.gameObject.SetActive(false);
        }

        private bool HasVisibleExternalSpatialWindows()
        {
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
                if (IsExternalWindowVisible(_externalSpatialWindows[i])) return true;
            return false;
        }

        private ExternalSpatialWindowState LastVisibleExternalWindow()
        {
            for (int i = _externalSpatialWindows.Count - 1; i >= 0; i--)
                if (IsExternalWindowVisible(_externalSpatialWindows[i]))
                    return _externalSpatialWindows[i];
            return null;
        }

        private static bool IsExternalWindowVisible(ExternalSpatialWindowState state) =>
            state?.Rect != null && state.Rect.gameObject.activeInHierarchy;

        private ExternalSpatialWindowState ExternalWindowFor(RectTransform rect)
        {
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
                if (_externalSpatialWindows[i].Rect == rect)
                    return _externalSpatialWindows[i];
            return null;
        }

        private bool TryProjectExternalWindows(
            Ray ray,
            ref float bestDistance,
            ref Vector3 worldPoint)
        {
            bool hit = false;
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
            {
                ExternalSpatialWindowState state = _externalSpatialWindows[i];
                if (!IsExternalWindowVisible(state)) continue;
                hit |= TryProjectWindow(
                    ray,
                    state.Rect,
                    ref bestDistance,
                    ref worldPoint);
            }
            return hit;
        }

        private void ResolveExternalWindowTargets(
            Vector3 worldPoint,
            ref GameObject target,
            ref float smallestArea)
        {
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
            {
                ExternalSpatialWindowState state = _externalSpatialWindows[i];
                if (!IsExternalWindowVisible(state)) continue;
                ResolveTargetInGraphics(
                    state.HitGraphics,
                    worldPoint,
                    ref target,
                    ref smallestArea);
            }
        }

        /// <summary>
        /// Resolve Lab-only content before the screen-space GraphicRaycaster.
        /// XREAL eye coordinates and the S24 display coordinates differ, so a
        /// screen-space hit can suppress the exact world-space result. With no
        /// external window this is a strict no-op for Product and Atelier.
        /// </summary>
        public bool TryResolveExternalSpatialTarget(
            Vector3 worldPoint,
            out GameObject target)
        {
            target = null;
            float smallestArea = float.MaxValue;
            ResolveExternalWindowTargets(
                worldPoint,
                ref target,
                ref smallestArea);
            return target != null;
        }

        private DeckManipulationMode ClassifyExternalWindowHandle(
            Vector3 worldPoint,
            out ExternalSpatialWindowState state)
        {
            state = null;
            for (int i = _externalSpatialWindows.Count - 1; i >= 0; i--)
            {
                ExternalSpatialWindowState candidate = _externalSpatialWindows[i];
                if (IsPointInsideExternalHandle(candidate.FreeResize, worldPoint))
                {
                    state = candidate;
                    return DeckManipulationMode.ResizeFree;
                }
                DeckManipulationMode mode = ClassifyWindowHandle(
                    candidate.Rect,
                    IsExternalWindowVisible(candidate),
                    worldPoint);
                if (mode == DeckManipulationMode.None) continue;
                state = candidate;
                return mode;
            }
            return DeckManipulationMode.None;
        }

        private void BuildExternalWindowHandles(ExternalSpatialWindowState state)
        {
            Rect rect = state.Rect.rect;
            float bottom = rect.yMin + 17f;
            state.Move = MakeImage(
                state.Rect, "Gaze move handle", new Vector2(-70f, bottom),
                new Vector2(104f, 5f), new Color(.76f, .78f, .82f, .78f));
            state.Move.raycastTarget = false;
            AddVisionHandleDot(state.Move, false);
            state.ResizeLeft = MakeImage(
                state.Rect, "Gaze resize handle", new Vector2(rect.xMin + 13f, rect.yMin + 13f),
                new Vector2(24f, 32f), new Color(.76f, .78f, .82f, .78f));
            ConfigureVisionResizeHandle(state.ResizeLeft, false);
            state.ResizeLeft.raycastTarget = false;
            state.ResizeRight = MakeImage(
                state.Rect, "Gaze resize handle right", new Vector2(rect.xMax - 13f, rect.yMin + 13f),
                new Vector2(24f, 32f), new Color(.76f, .78f, .82f, .78f));
            ConfigureVisionResizeHandle(state.ResizeRight, true);
            state.ResizeRight.raycastTarget = false;
            state.Depth = MakeImage(
                state.Rect, "Gaze depth handle", new Vector2(72f, bottom),
                new Vector2(52f, 34f), new Color(.76f, .78f, .82f, .78f));
            ConfigureVisionDepthHandle(state.Depth);
            state.Depth.raycastTarget = false;
            state.Tilt = MakeImage(
                state.Rect, "Gaze tilt handle", new Vector2(136f, bottom),
                new Vector2(52f, 34f), new Color(.76f, .78f, .82f, .78f));
            ConfigureVisionTiltHandle(state.Tilt);
            state.Tilt.raycastTarget = false;
            if (state.Resize != null)
            {
                state.FreeResize = MakeVisionFreeResizeHandle(
                    state.Rect,
                    new Vector2(rect.xMin + 96f, bottom));
            }
            state.CloseHandle = MakeText(
                state.Rect, "×", new Vector2(rect.xMax - 17f, rect.yMax - 17f),
                new Vector2(34f, 34f), 24f,
                new Color(.82f, .84f, .88f, .90f));
            state.CloseHandle.raycastTarget = false;
            LayoutExternalWindowHandles(state);
            SetExternalHandlesActive(state, false);
        }

        private void SetExternalHandlesActive(
            ExternalSpatialWindowState state,
            bool active)
        {
            if (state == null) return;
            if (state.Move != null) state.Move.gameObject.SetActive(active);
            if (state.ResizeLeft != null) state.ResizeLeft.gameObject.SetActive(active);
            if (state.ResizeRight != null) state.ResizeRight.gameObject.SetActive(active);
            if (state.Depth != null) state.Depth.gameObject.SetActive(active);
            if (state.Tilt != null) state.Tilt.gameObject.SetActive(active);
            if (state.FreeResize != null) state.FreeResize.gameObject.SetActive(active);
            if (state.CloseHandle != null) state.CloseHandle.gameObject.SetActive(active);
        }

        private void SetExternalWindowHandleVisuals(
            DeckManipulationMode mode,
            DeckWindowKind window)
        {
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
            {
                ExternalSpatialWindowState state = _externalSpatialWindows[i];
                bool reveal =
                    state == _externalAffordanceWindow &&
                    Time.unscaledTime < _deckAffordanceRevealUntil &&
                    _deckAffordanceRevealWindow == DeckWindowKind.External;
                SetExternalVisionHandle(state.Move, reveal, mode, window,
                    DeckManipulationMode.Move, state);
                SetExternalVisionHandle(state.ResizeLeft, reveal, mode, window,
                    DeckManipulationMode.ResizeLeft, state);
                SetExternalVisionHandle(state.ResizeRight, reveal, mode, window,
                    DeckManipulationMode.ResizeRight, state);
                SetExternalVisionHandle(state.Depth, reveal, mode, window,
                    DeckManipulationMode.Depth, state);
                SetExternalVisionHandle(state.Tilt, reveal, mode, window,
                    DeckManipulationMode.Tilt, state);
                SetExternalVisionHandle(state.FreeResize, reveal, mode, window,
                    DeckManipulationMode.ResizeFree, state);
                SetExternalVisionHandle(state.CloseHandle, reveal, mode, window,
                    DeckManipulationMode.Minimize, state);
            }
        }

        private void SetExternalVisionHandle(
            Graphic handle,
            bool reveal,
            DeckManipulationMode mode,
            DeckWindowKind window,
            DeckManipulationMode ownMode,
            ExternalSpatialWindowState owner)
        {
            if (handle == null) return;
            bool targeted = window == DeckWindowKind.External &&
                _hoverExternalWindow == owner && mode == ownMode;
            bool engaged = _activeExternalWindow == owner &&
                _deckManipulationMode == ownMode;
            handle.gameObject.SetActive(reveal || targeted || engaged);
            if (!handle.gameObject.activeSelf) return;
            if (handle == owner.FreeResize)
            {
                handle.color = engaged
                    ? new Color(.48f, .51f, .59f, .98f)
                    : (targeted
                        ? new Color(.36f, .38f, .44f, .96f)
                        : new Color(.22f, .23f, .27f, .88f));
                Graphic[] freeResizeGraphics =
                    handle.GetComponentsInChildren<Graphic>(true);
                for (int i = 0; i < freeResizeGraphics.Length; i++)
                    if (freeResizeGraphics[i] != handle)
                        freeResizeGraphics[i].color = Color.white;
                return;
            }
            Color color = engaged
                ? Color.white
                : (targeted
                    ? new Color(.94f, .95f, .98f, .98f)
                    : new Color(.72f, .74f, .79f, .72f));
            Graphic[] graphics = handle.GetComponentsInChildren<Graphic>(true);
            for (int i = 0; i < graphics.Length; i++)
            {
                if (
                    (ownMode == DeckManipulationMode.Depth ||
                     ownMode == DeckManipulationMode.Tilt) &&
                    graphics[i] == handle)
                    graphics[i].color = new Color(
                        color.r,
                        color.g,
                        color.b,
                        engaged ? .18f : (targeted ? .14f : .06f));
                else
                    graphics[i].color = color;
            }
        }

        private void RevealExternalWindowAffordances(
            ExternalSpatialWindowState state,
            float seconds = 4f)
        {
            _externalAffordanceWindow = state;
            _deckAffordanceRevealWindow = DeckWindowKind.External;
            _deckAffordanceRevealUntil = Time.unscaledTime + seconds;
            SetExternalWindowHandleVisuals(
                DeckManipulationMode.None,
                DeckWindowKind.External);
        }

        private string LayoutPrefixForWindow(DeckWindowKind window)
        {
            if (window == DeckWindowKind.Settings) return SettingsLayoutPrefix;
            if (window == DeckWindowKind.External && _activeExternalWindow != null)
                return _activeExternalWindow.LayoutPrefix;
            return DeckLayoutPrefix;
        }

        private void RestoreExternalWindowLayout(ExternalSpatialWindowState state)
        {
            if (state?.Rect == null || _camera == null ||
                !PlayerPrefs.HasKey(state.LayoutPrefix + "x")) return;
            Vector3 local = new Vector3(
                PlayerPrefs.GetFloat(state.LayoutPrefix + "x"),
                PlayerPrefs.GetFloat(state.LayoutPrefix + "y"),
                PlayerPrefs.GetFloat(state.LayoutPrefix + "z", 1.1f));
            Vector3 position = _camera.transform.TransformPoint(local);
            Vector3 forward = (position - _camera.transform.position).normalized;
            state.Rect.SetPositionAndRotation(
                position,
                BuildWindowRotation(
                    forward,
                    PlayerPrefs.GetFloat(state.LayoutPrefix + "tilt", 0f),
                    PlayerPrefs.GetFloat(state.LayoutPrefix + "turn", 0f)));
            float scale = PlayerPrefs.GetFloat(
                state.LayoutPrefix + "scale",
                state.Rect.localScale.x);
            state.Rect.localScale = Vector3.one * Mathf.Clamp(
                scale,
                .00038f,
                .00108f);
            if (PlayerPrefs.HasKey(state.LayoutPrefix + "width"))
            {
                state.Rect.sizeDelta = new Vector2(
                    Mathf.Clamp(
                        PlayerPrefs.GetFloat(state.LayoutPrefix + "width"),
                        360f,
                        1800f),
                    Mathf.Clamp(
                        PlayerPrefs.GetFloat(state.LayoutPrefix + "height"),
                        260f,
                        1200f));
            }
            LayoutExternalWindowHandles(state);
            state.Resize?.Invoke(state.Rect.sizeDelta, true);
        }

        private void SaveExternalWindowLayouts()
        {
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
            {
                ExternalSpatialWindowState state = _externalSpatialWindows[i];
                if (!IsExternalWindowVisible(state)) continue;
                _activeExternalWindow = state;
                SaveWindowLayout(
                    DeckWindowKind.External,
                    state.Rect.position,
                    state.Rect.localScale.x);
                SaveExternalWindowSize(state);
            }
        }

        private void RecenterExternalWindows()
        {
            int visible = 0;
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
                if (IsExternalWindowVisible(_externalSpatialWindows[i])) visible++;
            if (visible == 0 || _camera == null) return;
            int slot = 0;
            for (int i = 0; i < _externalSpatialWindows.Count; i++)
            {
                ExternalSpatialWindowState state = _externalSpatialWindows[i];
                if (!IsExternalWindowVisible(state)) continue;
                float x = (slot - (visible - 1) * .5f) * .58f;
                PlaceWindowAtCameraLocal(state.Rect, new Vector3(x, .05f, 1.12f));
                slot++;
            }
        }

        private void CloseAllExternalWindows()
        {
            ExternalSpatialWindowState[] states = _externalSpatialWindows.ToArray();
            for (int i = 0; i < states.Length; i++)
                if (IsExternalWindowVisible(states[i])) states[i].Close?.Invoke();
        }

        private static string SanitizeLayoutId(string value)
        {
            char[] chars = value.ToLowerInvariant().ToCharArray();
            for (int i = 0; i < chars.Length; i++)
                if (!char.IsLetterOrDigit(chars[i])) chars[i] = '_';
            return new string(chars);
        }

        private static bool IsPointInsideExternalHandle(
            Graphic graphic,
            Vector3 worldPoint)
        {
            if (graphic == null) return false;
            RectTransform rect = graphic.rectTransform;
            Vector3 local = rect.InverseTransformPoint(worldPoint);
            return Mathf.Abs(local.z) <= 45f && rect.rect.Contains(local);
        }

        private void LayoutExternalWindowHandles(ExternalSpatialWindowState state)
        {
            if (state?.Rect == null) return;
            Rect rect = state.Rect.rect;
            float bottom = rect.yMin + 17f;
            LayoutHandle(state.Move, new Vector2(-70f, bottom), new Vector2(104f, 5f));
            LayoutHandle(state.Depth, new Vector2(72f, bottom), new Vector2(52f, 34f));
            LayoutHandle(state.Tilt, new Vector2(136f, bottom), new Vector2(52f, 34f));
            LayoutHandle(state.FreeResize,
                new Vector2(rect.xMin + 96f, bottom), new Vector2(52f, 32f));
            LayoutHandle(state.ResizeLeft,
                new Vector2(rect.xMin + 18f, rect.yMin + 20f), Vector2.one * 48f);
            LayoutHandle(state.ResizeRight,
                new Vector2(rect.xMax - 18f, rect.yMin + 20f), Vector2.one * 48f);
            LayoutRect(state.CloseHandle,
                new Vector2(rect.xMax - 17f, rect.yMax - 17f), new Vector2(34f, 34f));
        }

        private void ApplyExternalWindowSize(Vector2 size, bool final)
        {
            ExternalSpatialWindowState state = _activeExternalWindow;
            if (state?.Rect == null || state.Resize == null) return;
            state.Rect.sizeDelta = size;
            LayoutExternalWindowHandles(state);
            state.Resize.Invoke(size, final);
        }

        private void SaveExternalWindowSize(ExternalSpatialWindowState state)
        {
            if (state?.Rect == null || state.Resize == null) return;
            PlayerPrefs.SetFloat(state.LayoutPrefix + "width", state.Rect.sizeDelta.x);
            PlayerPrefs.SetFloat(state.LayoutPrefix + "height", state.Rect.sizeDelta.y);
        }
    }
}

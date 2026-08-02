using System;
using TMPro;
using UnityEngine;
using UnityEngine.UI;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Lab-only actions hosted by the proven Atelier control centre. Product
    /// and Atelier do not register these delegates, so this remains a no-op in
    /// their builds.
    /// </summary>
    public sealed partial class WorldCreatorController
    {
        private const string LabVrPreference = "mlomega.xr.lab.vr_mode.v1";
        private Action _labQuitAction;
        private Action _labKeyboardAction;
        private Func<bool> _labKeyboardVisible;
        private Action<bool> _labVrChanged;
        private Button _labQuitButton;
        private Button _labVrButton;
        private Button _labKeyboardButton;
        private TextMeshProUGUI _labVrLabel;
        private TextMeshProUGUI _labKeyboardLabel;
        private Image _labQuitConfirmPanel;

        public void RegisterLabSettingsActions(
            Action quit,
            Action toggleKeyboard,
            Func<bool> keyboardVisible,
            Action<bool> vrChanged)
        {
            _labQuitAction = quit;
            _labKeyboardAction = toggleKeyboard;
            _labKeyboardVisible = keyboardVisible;
            _labVrChanged = vrChanged;
            if (_settingsDeck == null) BuildSettingsDeck();
            if (_settingsDeckRect == null) return;
            BuildOptionalLabSettingsActions();
            Vector2 size = _settingsDeckRect.sizeDelta;
            if (size.x >= size.y)
                size = new Vector2(
                    Mathf.Max(size.x, 1040f),
                    Mathf.Max(size.y, 760f));
            else
                size = new Vector2(
                    Mathf.Max(size.x, 620f),
                    Mathf.Max(size.y, 1060f));
            _settingsDeckRect.sizeDelta = size;
            LayoutSettingsDeck();
            RefreshOptionalLabSettingsActions();
            _settingsHitGraphics.Clear();
            _settingsDeckRect.GetComponentsInChildren(true, _settingsHitGraphics);
        }

        public void SaveLabWindowLayoutsForExit()
        {
            SaveVisibleWindowLayouts();
            PlayerPrefs.Save();
        }

        private bool HasOptionalLabSettingsActions() => _labVrButton != null;

        private void BuildOptionalLabSettingsActions()
        {
            if (_labQuitButton != null || _settingsDeckRect == null) return;

            _labQuitButton = MakeVisionControlButton(
                _settingsDeckRect,
                "LAB POWER",
                VisionIconKind.Power,
                string.Empty,
                Vector2.zero,
                ToggleOptionalLabQuitConfirmation,
                56f);
            TextMeshProUGUI quitCaption = CaptionFor(_labQuitButton);
            if (quitCaption != null) quitCaption.gameObject.SetActive(false);

            _labVrButton = MakeVisionControlButton(
                _settingsDeckRect,
                "LAB VR MODE",
                VisionIconKind.Vr,
                "Mode VR",
                Vector2.zero,
                ToggleOptionalLabVr,
                64f);
            _labVrLabel = CaptionFor(_labVrButton);

            _labKeyboardButton = MakeVisionControlButton(
                _settingsDeckRect,
                "LAB KEYBOARD",
                VisionIconKind.Keyboard,
                "Clavier",
                Vector2.zero,
                () =>
                {
                    _labKeyboardAction?.Invoke();
                    RefreshOptionalLabSettingsActions();
                },
                64f);
            _labKeyboardLabel = CaptionFor(_labKeyboardButton);

            _labQuitConfirmPanel = MakeImage(
                _settingsDeckRect,
                "Lab quit confirmation glass",
                Vector2.zero,
                new Vector2(250f, 116f),
                new Color(.055f, .060f, .075f, .96f));
            _labQuitConfirmPanel.raycastTarget = false;
            MakeText(
                _labQuitConfirmPanel.transform,
                "Quitter l'application ?",
                new Vector2(0f, 29f),
                new Vector2(220f, 28f),
                15f,
                VisionText,
                FontStyles.Normal);
            Button yes = MakeButton(
                _labQuitConfirmPanel.transform,
                "Oui",
                new Vector2(-58f, -24f),
                new Vector2(98f, 40f),
                ConfirmOptionalLabQuit);
            Button no = MakeButton(
                _labQuitConfirmPanel.transform,
                "Non",
                new Vector2(58f, -24f),
                new Vector2(98f, 40f),
                () => SetOptionalLabQuitConfirmation(false));
            StyleConfirmationButton(yes);
            StyleConfirmationButton(no);
            _labQuitConfirmPanel.gameObject.SetActive(false);
        }

        private static void StyleConfirmationButton(Button button)
        {
            if (button == null) return;
            Image image = button.GetComponent<Image>();
            if (image != null)
            {
                image.sprite = GetVisionRoundedSprite();
                image.type = Image.Type.Sliced;
                image.color = new Color(.20f, .21f, .25f, .92f);
            }
            TextMeshProUGUI label = button.GetComponentInChildren<TextMeshProUGUI>();
            if (label != null)
            {
                label.fontSize = 14f;
                label.fontStyle = FontStyles.Normal;
            }
        }

        private void ToggleOptionalLabQuitConfirmation()
        {
            SetOptionalLabQuitConfirmation(
                _labQuitConfirmPanel == null ||
                !_labQuitConfirmPanel.gameObject.activeSelf);
        }

        private void SetOptionalLabQuitConfirmation(bool visible)
        {
            if (_labQuitConfirmPanel == null) return;
            _labQuitConfirmPanel.gameObject.SetActive(visible);
            if (visible) _labQuitConfirmPanel.transform.SetAsLastSibling();
        }

        private void ConfirmOptionalLabQuit()
        {
            SetOptionalLabQuitConfirmation(false);
            _labQuitAction?.Invoke();
        }

        private void ToggleOptionalLabVr()
        {
            bool enabled = PlayerPrefs.GetInt(LabVrPreference, 0) != 1;
            PlayerPrefs.SetInt(LabVrPreference, enabled ? 1 : 0);
            PlayerPrefs.Save();
            _labVrChanged?.Invoke(enabled);
            RefreshOptionalLabSettingsActions();
            ShowGestureToast(
                enabled ? "MODE VR PRET" : "MODE VR COUPE",
                enabled ? new Color(.55f, .78f, 1f) : VisionSecondary);
        }

        private void RefreshOptionalLabSettingsActions()
        {
            if (_labVrButton == null) return;
            bool vr = PlayerPrefs.GetInt(LabVrPreference, 0) == 1;
            bool keyboard = _labKeyboardVisible?.Invoke() == true;
            if (_labVrLabel != null) _labVrLabel.text = vr ? "VR actif" : "Mode VR";
            if (_labKeyboardLabel != null)
                _labKeyboardLabel.text = keyboard ? "Fermer clavier" : "Clavier";
            SetControlCenterState(_labVrButton, vr, VisionPressed);
            SetControlCenterState(_labKeyboardButton, keyboard, VisionPressed);
        }

        private Vector2 AdjustOptionalLabSettingsOrientation(Vector2 target)
        {
            if (!HasOptionalLabSettingsActions()) return target;
            return target.x >= target.y
                ? new Vector2(
                    Mathf.Max(target.x, 1040f),
                    Mathf.Max(target.y, 760f))
                : new Vector2(
                    Mathf.Max(target.x, 620f),
                    Mathf.Max(target.y, 1060f));
        }

        private void LayoutOptionalLabSettingsActions(
            float surfaceWidth,
            float surfaceBottom,
            bool compact)
        {
            if (!HasOptionalLabSettingsActions()) return;
            float surfaceTop = _settingsDeckRect.sizeDelta.y * .5f - 48f;
            float surfaceRight = surfaceWidth * .5f;
            LayoutScaledButton(
                _labQuitButton,
                new Vector2(surfaceRight - 27f, surfaceTop - 27f),
                56f,
                .76f);

            float rowScale = compact ? .76f : .88f;
            float step = Mathf.Min(104f, surfaceWidth * .22f);
            float y = surfaceBottom + 55f;
            LayoutScaledButton(_labVrButton, new Vector2(-step * .5f, y), 64f, rowScale);
            LayoutScaledButton(_labKeyboardButton, new Vector2(step * .5f, y), 64f, rowScale);

            if (_labQuitConfirmPanel != null)
                LayoutSurface(
                    _labQuitConfirmPanel,
                    new Vector2(surfaceRight - 137f, surfaceTop - 102f),
                    new Vector2(250f, 116f));
        }
    }
}

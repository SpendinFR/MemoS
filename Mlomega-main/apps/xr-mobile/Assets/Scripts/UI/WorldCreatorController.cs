using System;
using System.Collections.Generic;
using MLOmega.Contracts.V19;
using MLOmega.XR.Core;
using MLOmega.XR.UI.Components;
using TMPro;
using UnityEngine;
using UnityEngine.EventSystems;
using UnityEngine.InputSystem.UI;
using UnityEngine.UI;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Isolated Atelier UI. The phone is the dense editing surface while the
    /// glasses show the spatial preview. It never pairs, records or opens Memory.
    /// </summary>
    public sealed class WorldCreatorController : MonoBehaviour
    {
        private static readonly string[] Categories =
        {
            "cinematic", "urban", "commerce", "home",
            "navigation", "mobility", "information",
        };

        [SerializeField] private MonoBehaviour _spatialBehaviour;
        [SerializeField] private Camera _camera;
        [SerializeField] private WorldMapDocumentExchange _exchange;

        private IWorldCreatorSpatialProvider Spatial =>
            _spatialBehaviour as IWorldCreatorSpatialProvider;
        private List<WorldCreatorCatalog.Entry> _visible =
            new List<WorldCreatorCatalog.Entry>();
        private WorldCreatorCatalog.Entry _selected;
        private WorldHologram _preview;
        private UIComponentContext _previewContext;
        private string _category = "cinematic";
        private string _label = "HOLOGRAMME";
        private string _subtitle = "ATELIER // MONDE AUGMENTÉ";
        private string _status = "INITIALISATION DU MESH…";
        private string _lastCreatedId;
        private string _pendingAssetId;
        private int _page;
        private float _uniformScale = 1f;
        private float _yaw;
        private float _nextPreviewAt;
        private Vector3 _previewPosition;
        private Quaternion _previewRotation;
        private bool _hasPreviewPose;
        private Vector2 _scroll;
        private GUIStyle _title;
        private GUIStyle _panel;
        private GUIStyle _button;
        private GUIStyle _selectedButton;
        private GUIStyle _labelStyle;
        private GUIStyle _field;
        private Canvas _spatialDeck;
        private RectTransform _spatialDeckRect;
        private TextMeshProUGUI _deckStatus;
        private TMP_InputField _deckLabel;
        private TMP_InputField _deckSubtitle;
        private readonly List<Button> _deckPresetButtons =
            new List<Button>();
        private readonly List<TextMeshProUGUI> _deckPresetLabels =
            new List<TextMeshProUGUI>();
        private readonly List<Button> _deckCategoryButtons =
            new List<Button>();
        private TextMeshProUGUI _deckPage;
        private TextMeshProUGUI _deckScale;
        private TextMeshProUGUI _deckAsset;
        private static Material _deckDepthMaterial;
        private static Material _deckPrimaryDepthMaterial;

        private void Awake()
        {
            if (_camera == null) _camera = Camera.main;
            if (_exchange == null)
                _exchange =
                    GetComponent<WorldMapDocumentExchange>() ??
                    gameObject.AddComponent<WorldMapDocumentExchange>();
            if (_spatialBehaviour == null)
            {
                foreach (MonoBehaviour behaviour in FindObjectsByType<MonoBehaviour>(
                    FindObjectsSortMode.None))
                {
                    if (behaviour is IWorldCreatorSpatialProvider)
                    {
                        _spatialBehaviour = behaviour;
                        break;
                    }
                }
            }
            if (Spatial != null)
            {
                Spatial.CreatorOperationCompleted += OnCreatorOperation;
                Spatial.EnableCreatorMode();
            }
            _exchange.Exported += path =>
                _status = "MONDE EXPORTÉ // " + path;
            _exchange.ImageImported += OnImageImported;
            _exchange.Failed += error =>
                _status = "ERREUR DOCUMENT // " + error;
            SelectCategory(_category);
            BuildSpatialDeck();
        }

        private void OnDestroy()
        {
            if (Spatial != null)
                Spatial.CreatorOperationCompleted -= OnCreatorOperation;
            if (_exchange != null)
                _exchange.ImageImported -= OnImageImported;
            if (_spatialDeck != null)
                Destroy(_spatialDeck.gameObject);
        }

        private void Update()
        {
            if (
                Spatial == null ||
                Time.unscaledTime < _nextPreviewAt)
                return;
            _nextPreviewAt = Time.unscaledTime + 0.12f;
            _hasPreviewPose = Spatial.TryCreatorPlacement(
                new Vector2(0.5f, 0.5f),
                out _previewPosition,
                out _previewRotation);
            if (_hasPreviewPose)
            {
                EnsurePreview();
                RefreshPreview();
                _status = Spatial.CreatorReady
                    ? "ANCRAGE PRÊT // VISE UNE SURFACE"
                    : "MESH TROUVÉ // ANCRE EN ATTENTE";
            }
            else if (_preview != null)
            {
                _preview.gameObject.SetActive(false);
            }
            RefreshSpatialDeck();
        }

        private void OnGUI()
        {
#if !UNITY_EDITOR
            return;
#endif
            EnsureStyles();
            float scale = Mathf.Clamp(Screen.dpi / 220f, 0.85f, 1.45f);
            float width = Mathf.Min(560f * scale, Screen.width * 0.48f);
            GUILayout.BeginArea(
                new Rect(18f, 18f, width, Screen.height - 36f),
                _panel);
            GUILayout.Label("MLOMEGA // WORLD ATELIER", _title);
            GUILayout.Label(
                "FREEGUY × BLADE RUNNER  •  " +
                WorldCreatorCatalog.Entries.Count +
                " PRESETS PROCÉDURAUX",
                _labelStyle);

            GUILayout.BeginHorizontal();
            foreach (string category in Categories)
            {
                if (GUILayout.Button(
                        category.ToUpperInvariant(),
                        _category == category ? _selectedButton : _button,
                        GUILayout.Height(38f)))
                    SelectCategory(category);
            }
            GUILayout.EndHorizontal();

            _scroll = GUILayout.BeginScrollView(
                _scroll,
                GUILayout.Height(Mathf.Min(310f, Screen.height * 0.34f)));
            int start = _page * 12;
            int end = Mathf.Min(start + 12, _visible.Count);
            for (int i = start; i < end; i += 2)
            {
                GUILayout.BeginHorizontal();
                DrawPresetButton(_visible[i]);
                if (i + 1 < end) DrawPresetButton(_visible[i + 1]);
                GUILayout.EndHorizontal();
            }
            GUILayout.EndScrollView();

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("◀", _button)) _page = Mathf.Max(0, _page - 1);
            GUILayout.Label(
                $"{_page + 1}/{Mathf.Max(1, Mathf.CeilToInt(_visible.Count / 12f))}",
                _labelStyle,
                GUILayout.Width(72f));
            if (GUILayout.Button("▶", _button))
                _page = Mathf.Min(
                    Mathf.Max(0, Mathf.CeilToInt(_visible.Count / 12f) - 1),
                    _page + 1);
            GUILayout.EndHorizontal();

            GUILayout.Label("TEXTE LIBRE", _labelStyle);
            _label = GUILayout.TextField(_label, 120, _field);
            _subtitle = GUILayout.TextField(_subtitle, 240, _field);

            GUILayout.BeginHorizontal();
            if (GUILayout.Button("TAILLE −", _button))
                _uniformScale = Mathf.Max(.25f, _uniformScale - .1f);
            GUILayout.Label(_uniformScale.ToString("0.0×"), _labelStyle);
            if (GUILayout.Button("TAILLE +", _button))
                _uniformScale = Mathf.Min(2.5f, _uniformScale + .1f);
            if (GUILayout.Button("↺ 15°", _button)) _yaw -= 15f;
            if (GUILayout.Button("↻ 15°", _button)) _yaw += 15f;
            GUILayout.EndHorizontal();

            GUI.enabled =
                Spatial != null &&
                Spatial.CreatorReady &&
                _selected != null &&
                _hasPreviewPose;
            if (GUILayout.Button(
                    "ANCRER DANS LE MONDE",
                    _selectedButton,
                    GUILayout.Height(58f)))
            {
                Vector3 scale3 =
                    _selected.defaultScale * _uniformScale;
                if (Spatial.PersistCreatorContent(
                        new Vector2(.5f, .5f),
                        _selected,
                        _label,
                        _subtitle,
                        scale3,
                        _yaw,
                        _pendingAssetId))
                    _status = "SAUVEGARDE ANCRE NATIVE…";
            }
            GUI.enabled = true;

            GUILayout.BeginHorizontal();
            if (GUILayout.Button(
                    string.IsNullOrEmpty(_pendingAssetId)
                        ? "IMPORTER LOGO PNG/JPEG"
                        : "LOGO PRÊT ✓",
                    string.IsNullOrEmpty(_pendingAssetId)
                        ? _button
                        : _selectedButton))
                _exchange.BeginImageImport();
            if (!string.IsNullOrEmpty(_pendingAssetId) &&
                GUILayout.Button("RETIRER LOGO", _button))
                _pendingAssetId = string.Empty;
            GUILayout.EndHorizontal();

            GUILayout.BeginHorizontal();
            GUI.enabled = !string.IsNullOrEmpty(_lastCreatedId);
            if (GUILayout.Button("ANNULER DERNIER", _button))
                Spatial?.RemoveCreatorContent(_lastCreatedId);
            GUI.enabled = Spatial?.CreatorMap != null &&
                Spatial.CreatorMap.Contents.Count > 0;
            if (GUILayout.Button("EXPORTER LE MONDE", _button))
            {
                if (Spatial.PrepareCreatorExport(out string exportError))
                    _exchange.BeginExport(
                        Spatial.CreatorMap,
                        "mlomega-" + Spatial.CreatorMap.WorldMapId);
                else
                    _status = "EXPORT REFUSÉ // " + exportError;
            }
            GUI.enabled = true;
            GUILayout.EndHorizontal();

            GUILayout.FlexibleSpace();
            GUILayout.Label(_status, _labelStyle);
            GUILayout.Label(
                "AUCUNE CAMÉRA, VOIX OU MÉMOIRE N'EST ARCHIVÉE",
                _labelStyle);
            GUILayout.EndArea();

            // Precision reticle in the glasses view.
            Color old = GUI.color;
            GUI.color = _hasPreviewPose
                ? new Color(.15f, 1f, .88f, .95f)
                : new Color(1f, .28f, .45f, .85f);
            GUI.Label(
                new Rect(
                    Screen.width * .5f - 16f,
                    Screen.height * .5f - 16f,
                    32f,
                    32f),
                "◎",
                _title);
            GUI.color = old;
        }

        private void SelectCategory(string category)
        {
            _category = category;
            _visible = WorldCreatorCatalog.ForCategory(category);
            _page = 0;
            if (_visible.Count > 0) SelectPreset(_visible[0]);
            RefreshSpatialDeck();
        }

        private void DrawPresetButton(WorldCreatorCatalog.Entry entry)
        {
            bool selected =
                _selected != null &&
                _selected.presetId == entry.presetId;
            if (GUILayout.Button(
                    entry.label + "\n" + entry.archetypeId.Replace("-", " "),
                    selected ? _selectedButton : _button,
                    GUILayout.Height(54f)))
                SelectPreset(entry);
        }

        private void SelectPreset(WorldCreatorCatalog.Entry entry)
        {
            _selected = entry;
            _label = entry.label;
            _subtitle = entry.subtitle;
            _uniformScale = 1f;
            if (_hasPreviewPose) RefreshPreview();
            RefreshSpatialDeck();
        }

        private void BuildSpatialDeck()
        {
            if (_spatialDeck != null || _camera == null) return;
            if (FindAnyObjectByType<EventSystem>() == null)
            {
                var eventGo = new GameObject("Atelier Spatial EventSystem");
                eventGo.AddComponent<EventSystem>();
                var input = eventGo.AddComponent<InputSystemUIInputModule>();
                input.AssignDefaultActions();
            }

            var deckGo = new GameObject("Atelier Holographic Control Deck");
            _spatialDeck = deckGo.AddComponent<Canvas>();
            _spatialDeck.renderMode = RenderMode.WorldSpace;
            _spatialDeck.worldCamera = _camera;
            _spatialDeck.sortingOrder = 80;
            deckGo.AddComponent<GraphicRaycaster>();
            _spatialDeckRect = deckGo.GetComponent<RectTransform>();
            _spatialDeckRect.sizeDelta = new Vector2(920f, 1050f);
            _spatialDeckRect.localScale = Vector3.one * .00105f;
            SetDeckPose();
            MakeSpatialPlate(
                _spatialDeckRect,
                "Deck physical glass volume",
                Vector2.zero,
                new Vector2(920f, 1050f),
                22f,
                false);

            Image glass = MakeImage(
                _spatialDeckRect,
                "Glass",
                Vector2.zero,
                new Vector2(920f, 1050f),
                new Color(.008f, .018f, .05f, .86f));
            glass.raycastTarget = false;
            MakeImage(
                _spatialDeckRect,
                "InnerGlow",
                new Vector2(0f, 4f),
                new Vector2(892f, 1022f),
                new Color(.02f, .2f, .26f, .18f)).raycastTarget = false;
            MakeNeonFrame(deckGo.transform);

            MakeText(
                _spatialDeckRect,
                "MLOMEGA // WORLD ATELIER",
                new Vector2(0f, 475f),
                new Vector2(850f, 60f),
                34f,
                new Color(.35f, 1f, .94f),
                FontStyles.Bold);
            MakeText(
                _spatialDeckRect,
                "VOLUMES 3D • ANCRES XREAL • AUCUNE CAPTURE MÉMOIRE",
                new Vector2(0f, 433f),
                new Vector2(850f, 34f),
                17f,
                new Color(.62f, .82f, 1f));

            for (int i = 0; i < Categories.Length; i++)
            {
                int categoryIndex = i;
                float x = -330f + (i % 4) * 220f;
                float y = 378f - (i / 4) * 52f;
                Button button = MakeButton(
                    _spatialDeckRect,
                    Categories[i].ToUpperInvariant(),
                    new Vector2(x, y),
                    new Vector2(205f, 42f),
                    () => SelectCategory(Categories[categoryIndex]));
                _deckCategoryButtons.Add(button);
            }

            for (int i = 0; i < 12; i++)
            {
                int presetIndex = i;
                float x = -290f + (i % 3) * 290f;
                float y = 252f - (i / 3) * 72f;
                Button button = MakeButton(
                    _spatialDeckRect,
                    "PRESET",
                    new Vector2(x, y),
                    new Vector2(270f, 60f),
                    () => SelectVisiblePreset(presetIndex));
                _deckPresetButtons.Add(button);
                _deckPresetLabels.Add(
                    button.GetComponentInChildren<TextMeshProUGUI>());
            }

            MakeButton(
                _spatialDeckRect,
                "◀",
                new Vector2(-170f, -18f),
                new Vector2(90f, 42f),
                () =>
                {
                    _page = Mathf.Max(0, _page - 1);
                    RefreshSpatialDeck();
                });
            _deckPage = MakeText(
                _spatialDeckRect,
                "1/1",
                new Vector2(0f, -18f),
                new Vector2(200f, 42f),
                18f,
                new Color(.72f, .94f, 1f));
            MakeButton(
                _spatialDeckRect,
                "▶",
                new Vector2(170f, -18f),
                new Vector2(90f, 42f),
                () =>
                {
                    _page = Mathf.Min(PageCount - 1, _page + 1);
                    RefreshSpatialDeck();
                });

            _deckLabel = MakeInput(
                _spatialDeckRect,
                "Titre holographique",
                new Vector2(0f, -78f),
                new Vector2(850f, 48f),
                value => _label = value);
            _deckSubtitle = MakeInput(
                _spatialDeckRect,
                "Sous-titre / annotation libre",
                new Vector2(0f, -135f),
                new Vector2(850f, 48f),
                value => _subtitle = value);

            MakeButton(
                _spatialDeckRect,
                "TAILLE −",
                new Vector2(-310f, -198f),
                new Vector2(170f, 46f),
                () =>
                {
                    _uniformScale = Mathf.Max(.25f, _uniformScale - .1f);
                    RefreshPreview();
                });
            _deckScale = MakeText(
                _spatialDeckRect,
                "1.0×",
                new Vector2(-105f, -198f),
                new Vector2(110f, 46f),
                18f,
                new Color(.32f, 1f, .88f),
                FontStyles.Bold);
            MakeButton(
                _spatialDeckRect,
                "TAILLE +",
                new Vector2(105f, -198f),
                new Vector2(170f, 46f),
                () =>
                {
                    _uniformScale = Mathf.Min(2.5f, _uniformScale + .1f);
                    RefreshPreview();
                });
            MakeButton(
                _spatialDeckRect,
                "ROTATION ↻",
                new Vector2(310f, -198f),
                new Vector2(170f, 46f),
                () =>
                {
                    _yaw += 15f;
                    RefreshPreview();
                });

            MakeButton(
                _spatialDeckRect,
                "IMPORTER LOGO",
                new Vector2(-285f, -258f),
                new Vector2(250f, 48f),
                () => _exchange.BeginImageImport());
            _deckAsset = MakeText(
                _spatialDeckRect,
                "AUCUN LOGO",
                new Vector2(0f, -258f),
                new Vector2(230f, 48f),
                15f,
                new Color(.7f, .85f, 1f));
            MakeButton(
                _spatialDeckRect,
                "RETIRER",
                new Vector2(285f, -258f),
                new Vector2(250f, 48f),
                () =>
                {
                    _pendingAssetId = string.Empty;
                    RefreshPreview();
                });

            MakeButton(
                _spatialDeckRect,
                "ANCRER DANS LE MONDE",
                new Vector2(0f, -332f),
                new Vector2(850f, 66f),
                AnchorFromSpatialDeck,
                true);
            MakeButton(
                _spatialDeckRect,
                "ANNULER DERNIER",
                new Vector2(-285f, -408f),
                new Vector2(250f, 48f),
                () =>
                {
                    if (!string.IsNullOrEmpty(_lastCreatedId))
                        Spatial?.RemoveCreatorContent(_lastCreatedId);
                });
            MakeButton(
                _spatialDeckRect,
                "EXPORTER MONDE",
                new Vector2(0f, -408f),
                new Vector2(250f, 48f),
                ExportFromSpatialDeck);
            MakeButton(
                _spatialDeckRect,
                "RECENTRER PUPITRE",
                new Vector2(285f, -408f),
                new Vector2(250f, 48f),
                SetDeckPose);
            _deckStatus = MakeText(
                _spatialDeckRect,
                _status,
                new Vector2(0f, -472f),
                new Vector2(850f, 62f),
                17f,
                new Color(.25f, 1f, .9f),
                FontStyles.Bold);
            RefreshSpatialDeck();
        }

        private void AnchorFromSpatialDeck()
        {
            if (
                Spatial == null ||
                !Spatial.CreatorReady ||
                _selected == null ||
                !_hasPreviewPose)
            {
                _status = "ANCRAGE INDISPONIBLE // VISE UNE SURFACE MAPPÉE";
                return;
            }
            Vector3 scale = _selected.defaultScale * _uniformScale;
            if (Spatial.PersistCreatorContent(
                    new Vector2(.5f, .5f),
                    _selected,
                    _label,
                    _subtitle,
                    scale,
                    _yaw,
                    _pendingAssetId))
                _status = "SAUVEGARDE DE L'ANCRE NATIVE…";
        }

        private void ExportFromSpatialDeck()
        {
            if (Spatial?.CreatorMap == null) return;
            if (!Spatial.PrepareCreatorExport(out string error))
            {
                _status = "EXPORT REFUSÉ // " + error;
                return;
            }
            _exchange.BeginExport(
                Spatial.CreatorMap,
                "mlomega-" + Spatial.CreatorMap.WorldMapId);
        }

        private void SelectVisiblePreset(int slot)
        {
            int index = _page * 12 + slot;
            if (index >= 0 && index < _visible.Count)
                SelectPreset(_visible[index]);
        }

        private int PageCount =>
            Mathf.Max(1, Mathf.CeilToInt(_visible.Count / 12f));

        private void RefreshSpatialDeck()
        {
            if (_spatialDeck == null) return;
            if (_deckStatus != null) _deckStatus.text = _status;
            if (_deckScale != null)
                _deckScale.text = _uniformScale.ToString("0.0×");
            if (_deckPage != null)
                _deckPage.text = (_page + 1) + "/" + PageCount;
            if (_deckAsset != null)
                _deckAsset.text = string.IsNullOrEmpty(_pendingAssetId)
                    ? "AUCUN LOGO"
                    : "LOGO 3D PRÊT ✓";
            if (_deckLabel != null && !_deckLabel.isFocused)
                _deckLabel.SetTextWithoutNotify(_label);
            if (_deckSubtitle != null && !_deckSubtitle.isFocused)
                _deckSubtitle.SetTextWithoutNotify(_subtitle);
            for (int i = 0; i < _deckCategoryButtons.Count; i++)
                TintButton(
                    _deckCategoryButtons[i],
                    Categories[i] == _category);
            for (int i = 0; i < _deckPresetButtons.Count; i++)
            {
                int index = _page * 12 + i;
                bool available = index < _visible.Count;
                _deckPresetButtons[i].gameObject.SetActive(available);
                if (!available) continue;
                WorldCreatorCatalog.Entry entry = _visible[index];
                _deckPresetLabels[i].text =
                    entry.label.ToUpperInvariant() + "\n<size=65%>" +
                    entry.archetypeId.Replace("-", " ") + "</size>";
                TintButton(
                    _deckPresetButtons[i],
                    _selected != null &&
                    _selected.presetId == entry.presetId);
            }
        }

        private void SetDeckPose()
        {
            if (_spatialDeckRect == null || _camera == null) return;
            Vector3 forward = Vector3.ProjectOnPlane(
                _camera.transform.forward,
                Vector3.up);
            if (forward.sqrMagnitude < .001f)
                forward = _camera.transform.forward;
            forward.Normalize();
            _spatialDeckRect.position =
                _camera.transform.position +
                forward * 1.25f -
                Vector3.up * .05f;
            _spatialDeckRect.rotation =
                Quaternion.LookRotation(forward, Vector3.up);
        }

        private static Image MakeImage(
            Transform parent,
            string name,
            Vector2 position,
            Vector2 size,
            Color color)
        {
            var go = new GameObject(name);
            go.transform.SetParent(parent, false);
            Image image = go.AddComponent<Image>();
            image.color = color;
            RectTransform rect = image.rectTransform;
            rect.anchorMin = rect.anchorMax = new Vector2(.5f, .5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            return image;
        }

        private static TextMeshProUGUI MakeText(
            Transform parent,
            string text,
            Vector2 position,
            Vector2 size,
            float fontSize,
            Color color,
            FontStyles style = FontStyles.Normal)
        {
            var go = new GameObject("Text " + text);
            go.transform.SetParent(parent, false);
            var label = go.AddComponent<TextMeshProUGUI>();
            label.text = text;
            label.fontSize = fontSize;
            label.fontStyle = style;
            label.color = color;
            label.alignment = TextAlignmentOptions.Center;
            label.enableWordWrapping = true;
            label.raycastTarget = false;
            RectTransform rect = label.rectTransform;
            rect.anchorMin = rect.anchorMax = new Vector2(.5f, .5f);
            rect.anchoredPosition = position;
            rect.sizeDelta = size;
            return label;
        }

        private static Button MakeButton(
            Transform parent,
            string label,
            Vector2 position,
            Vector2 size,
            UnityEngine.Events.UnityAction action,
            bool primary = false)
        {
            MakeSpatialPlate(
                parent,
                "Button depth " + label,
                position,
                size,
                primary ? 30f : 18f,
                primary);
            Image image = MakeImage(
                parent,
                "Button " + label,
                position,
                size,
                primary
                    ? new Color(.02f, .45f, .42f, .92f)
                    : new Color(.025f, .11f, .2f, .9f));
            Button button = image.gameObject.AddComponent<Button>();
            ColorBlock colors = button.colors;
            colors.normalColor = Color.white;
            colors.highlightedColor =
                new Color(.35f, 1f, .92f, 1f);
            colors.pressedColor =
                new Color(.18f, .7f, .76f, 1f);
            button.colors = colors;
            button.onClick.AddListener(action);
            MakeText(
                image.transform,
                label,
                Vector2.zero,
                size - new Vector2(12f, 8f),
                primary ? 21f : 16f,
                Color.white,
                primary ? FontStyles.Bold : FontStyles.Normal);
            return button;
        }

        private static void MakeSpatialPlate(
            Transform parent,
            string name,
            Vector2 position,
            Vector2 size,
            float depth,
            bool primary)
        {
            GameObject plate =
                GameObject.CreatePrimitive(PrimitiveType.Cube);
            plate.name = name;
            plate.transform.SetParent(parent, false);
            plate.transform.localPosition =
                new Vector3(position.x, position.y, depth * .5f + 8f);
            plate.transform.localScale =
                new Vector3(size.x, size.y, depth);
            Collider collider = plate.GetComponent<Collider>();
            if (collider != null) UnityEngine.Object.Destroy(collider);
            MeshRenderer renderer = plate.GetComponent<MeshRenderer>();
            renderer.sharedMaterial = GetDeckDepthMaterial(primary);
        }

        private static Material GetDeckDepthMaterial(bool primary)
        {
            Material cached =
                primary ? _deckPrimaryDepthMaterial : _deckDepthMaterial;
            if (cached != null) return cached;
            Shader shader =
                Shader.Find("Universal Render Pipeline/Unlit") ??
                Shader.Find("Unlit/Color") ??
                Shader.Find("Sprites/Default");
            var material = new Material(shader);
            Color color = primary
                ? new Color(.04f, .38f, .42f, .9f)
                : new Color(.01f, .045f, .1f, .94f);
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
            if (primary)
                _deckPrimaryDepthMaterial = material;
            else
                _deckDepthMaterial = material;
            return material;
        }

        private static TMP_InputField MakeInput(
            Transform parent,
            string placeholder,
            Vector2 position,
            Vector2 size,
            UnityEngine.Events.UnityAction<string> changed)
        {
            Image image = MakeImage(
                parent,
                "Input " + placeholder,
                position,
                size,
                new Color(.02f, .07f, .14f, .94f));
            TMP_InputField input =
                image.gameObject.AddComponent<TMP_InputField>();
            TextMeshProUGUI text = MakeText(
                image.transform,
                string.Empty,
                Vector2.zero,
                size - new Vector2(28f, 8f),
                18f,
                Color.white);
            text.alignment = TextAlignmentOptions.MidlineLeft;
            TextMeshProUGUI hint = MakeText(
                image.transform,
                placeholder,
                Vector2.zero,
                size - new Vector2(28f, 8f),
                17f,
                new Color(.38f, .55f, .67f));
            hint.alignment = TextAlignmentOptions.MidlineLeft;
            input.textComponent = text;
            input.placeholder = hint;
            input.lineType = TMP_InputField.LineType.SingleLine;
            input.characterLimit =
                placeholder.StartsWith("Titre", StringComparison.Ordinal)
                    ? 120
                    : 240;
            input.onValueChanged.AddListener(changed);
            return input;
        }

        private static void TintButton(Button button, bool selected)
        {
            if (button == null) return;
            Image image = button.GetComponent<Image>();
            if (image != null)
                image.color = selected
                    ? new Color(.05f, .55f, .48f, .96f)
                    : new Color(.025f, .11f, .2f, .9f);
        }

        private static void MakeNeonFrame(Transform parent)
        {
            var go = new GameObject("Volumetric Neon Frame");
            go.transform.SetParent(parent, false);
            var line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = false;
            line.loop = true;
            line.positionCount = 4;
            line.SetPosition(0, new Vector3(-458f, -523f, -5f));
            line.SetPosition(1, new Vector3(-458f, 523f, -5f));
            line.SetPosition(2, new Vector3(458f, 523f, -5f));
            line.SetPosition(3, new Vector3(458f, -523f, -5f));
            line.widthMultiplier = 5f;
            line.numCornerVertices = 6;
            line.startColor = new Color(.1f, 1f, .9f, .95f);
            line.endColor = new Color(.55f, .2f, 1f, .95f);
            Shader shader = Shader.Find("Sprites/Default");
            if (shader != null)
                line.material = new Material(shader);
        }

        private void EnsurePreview()
        {
            if (_preview != null) return;
            var go = new GameObject("Atelier Hologram Preview");
            _preview = go.AddComponent<WorldHologram>();
            _previewContext = new UIComponentContext(null, null, _camera);
            _preview.Configure(_previewContext, null);
            _preview.Admit(BuildPreviewIntent(), null, _ => { });
        }

        private void RefreshPreview()
        {
            if (_preview == null || _selected == null) return;
            _preview.gameObject.SetActive(true);
            _preview.transform.rotation =
                _previewRotation * Quaternion.Euler(0f, _yaw, 0f);
            _preview.transform.localScale = Vector3.one;
            _preview.Refresh(BuildPreviewIntent());
        }

        private UIIntent BuildPreviewIntent()
        {
            WorldMapStore.WorldAsset asset =
                string.IsNullOrEmpty(_pendingAssetId)
                    ? null
                    : Spatial?.CreatorMap?.FindAsset(_pendingAssetId);
            return new UIIntent
            {
            Type = "ui_intent",
            ContractsVersion = ContractDefaults.Version,
            UiIntentId = "atelier-preview",
            Producer = "world-atelier",
            Component = "world_hologram",
            Anchor = new Dictionary<string, object>
            {
                { "coordinate_space", "tracking_local" },
                {
                    "position",
                    new Dictionary<string, object>
                    {
                        { "x", _previewPosition.x },
                        { "y", _previewPosition.y },
                        { "z", _previewPosition.z },
                    }
                },
            },
            Content = new Dictionary<string, object>
            {
                { "pose_valid", true },
                { "depth_valid", true },
                { "calibration_id", "xreal-eye-tracking-local-v1" },
                { "anchor_quality", .94f },
                { "marker_id", "atelier-preview" },
                { "template_id", _selected?.templateId ?? "neon_sign" },
                { "archetype_id", _selected?.archetypeId ?? "preview" },
                { "style_id", _selected?.styleId ?? "cyan-violet" },
                { "animation_id", _selected?.animationId ?? "soft_pulse" },
                { "accent_hex", _selected?.accentHex ?? "18E8FF" },
                { "secondary_hex", _selected?.secondaryHex ?? "7B3CFF" },
                { "asset_id", asset?.assetId ?? string.Empty },
                { "asset_mime", asset?.mimeType ?? string.Empty },
                { "asset_sha256", asset?.sha256 ?? string.Empty },
                { "asset_base64", asset?.base64Data ?? string.Empty },
                {
                    "local_euler",
                    new Dictionary<string, object>
                    {
                        { "x", _previewRotation.eulerAngles.x },
                        { "y", _previewRotation.eulerAngles.y + _yaw },
                        { "z", _previewRotation.eulerAngles.z },
                    }
                },
                {
                    "scale",
                    new Dictionary<string, object>
                    {
                        {
                            "x",
                            (_selected?.defaultScale.x ?? 1f) * _uniformScale
                        },
                        {
                            "y",
                            (_selected?.defaultScale.y ?? 1f) * _uniformScale
                        },
                        {
                            "z",
                            (_selected?.defaultScale.z ?? 1f) * _uniformScale
                        },
                    }
                },
                { "label", _label },
                { "subtitle", _subtitle },
                { "kind", "atelier_preview" },
            },
            TruthLevel = "observed",
            Confidence = .94,
            TtlMs = 86400000,
            EvidenceRefs = new List<string>
            {
                "depth:xreal-mesh", "creator:user-confirmed",
            },
            };
        }

        private void OnCreatorOperation(
            string contentId,
            bool success,
            string detail)
        {
            if (success)
            {
                _lastCreatedId = contentId;
                _status = "ANCRE SAUVEGARDÉE // " +
                    (Spatial?.CreatorMap?.Contents.Count ?? 0) +
                    " ÉLÉMENT(S)";
            }
            else
            {
                _status = "ÉCHEC ANCRE // " + detail;
            }
        }

        private void OnImageImported(string path)
        {
            string error = string.Empty;
            if (
                Spatial?.CreatorMap != null &&
                Spatial.CreatorMap.TryAddImageAsset(
                    path,
                    out string assetId,
                    out error))
            {
                _pendingAssetId = assetId;
                _status = "LOGO HOLOGRAPHIQUE PRÊT // " + assetId;
            }
            else
            {
                _status = "LOGO REFUSÉ // " + (error ?? "unknown");
            }
        }

        private void EnsureStyles()
        {
            if (_title != null) return;
            Texture2D panelTexture = SolidTexture(
                new Color(.015f, .025f, .065f, .92f));
            Texture2D buttonTexture = SolidTexture(
                new Color(.04f, .09f, .16f, .94f));
            Texture2D selectedTexture = SolidTexture(
                new Color(.04f, .32f, .38f, .96f));
            _panel = new GUIStyle(GUI.skin.box)
            {
                padding = new RectOffset(18, 18, 16, 16),
                normal = { background = panelTexture },
            };
            _title = new GUIStyle(GUI.skin.label)
            {
                fontSize = 24,
                fontStyle = FontStyle.Bold,
                alignment = TextAnchor.MiddleCenter,
                normal = { textColor = new Color(.25f, 1f, .93f) },
            };
            _labelStyle = new GUIStyle(GUI.skin.label)
            {
                fontSize = 13,
                alignment = TextAnchor.MiddleCenter,
                normal = { textColor = new Color(.72f, .9f, 1f) },
            };
            _button = new GUIStyle(GUI.skin.button)
            {
                fontSize = 12,
                wordWrap = true,
                normal =
                {
                    background = buttonTexture,
                    textColor = new Color(.72f, .92f, 1f),
                },
                hover =
                {
                    background = selectedTexture,
                    textColor = Color.white,
                },
            };
            _selectedButton = new GUIStyle(_button)
            {
                fontStyle = FontStyle.Bold,
                normal =
                {
                    background = selectedTexture,
                    textColor = new Color(.95f, 1f, 1f),
                },
            };
            _field = new GUIStyle(GUI.skin.textField)
            {
                fontSize = 15,
                normal =
                {
                    background = buttonTexture,
                    textColor = Color.white,
                },
            };
        }

        private static Texture2D SolidTexture(Color color)
        {
            var texture = new Texture2D(1, 1, TextureFormat.RGBA32, false);
            texture.SetPixel(0, 0, color);
            texture.Apply();
            return texture;
        }
    }
}

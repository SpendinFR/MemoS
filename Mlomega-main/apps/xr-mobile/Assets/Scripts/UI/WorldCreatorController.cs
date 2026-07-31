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
        private bool _dynamicMode;
        private string _dynamicTargetLabel = string.Empty;
        private int _dynamicKindIndex;
        private int _attachmentIndex;
        private int _motionIndex;
        private int _managedIndex;
        private int _mapIndex;
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
        private bool _deckPoseInitialized;
        private TextMeshProUGUI _deckStatus;
        private TMP_InputField _deckLabel;
        private TMP_InputField _deckSubtitle;
        private readonly List<Button> _deckPresetButtons =
            new List<Button>();
        private readonly List<TextMeshProUGUI> _deckPresetLabels =
            new List<TextMeshProUGUI>();
        private readonly List<Button> _deckCategoryButtons =
            new List<Button>();
        private readonly List<Graphic> _deckHitGraphics =
            new List<Graphic>();
        private readonly List<GameObject> _deckExpandedRoots =
            new List<GameObject>();
        private TextMeshProUGUI _deckPage;
        private TextMeshProUGUI _deckScale;
        private TextMeshProUGUI _deckAsset;
        private TextMeshProUGUI _deckCommitLabel;
        private TextMeshProUGUI _deckModeLabel;
        private TextMeshProUGUI _deckKindLabel;
        private TextMeshProUGUI _deckAttachmentLabel;
        private TextMeshProUGUI _deckManagedLabel;
        private TextMeshProUGUI _deckMapLabel;
        private TextMeshProUGUI _deckMotionLabel;
        private TMP_InputField _deckTarget;
        private Image _deckMoveHandle;
        private Image _deckResizeHandle;
        private Image _deckMinimizeHandle;
        private Button _deckRestoreChip;
        private bool _deckMinimized;
        private DeckManipulationMode _deckHoverMode;
        private DeckManipulationMode _deckManipulationMode;
        private Vector2 _deckManipulationStartHand;
        private Vector3 _deckManipulationStartPosition;
        private Vector3 _deckManipulationStartCameraPosition;
        private Vector3 _deckManipulationStartDirection;
        private Vector3 _deckManipulationStartRight;
        private Vector3 _deckManipulationStartUp;
        private float _deckManipulationStartDistance;
        private float _deckManipulationStartScale;
        private float _deckManipulationStartZoom;
        private Vector3 _deckManipulationTargetPosition;
        private float _deckManipulationTargetScale;
        private bool _deckManipulationSmoothing;
        private static Material _deckDepthMaterial;
        private static Material _deckPrimaryDepthMaterial;
        private static readonly string[] DynamicKinds =
        {
            "object", "vehicle", "storefront", "sign", "building", "person",
        };
        private static readonly string[] Attachments =
        {
            "above", "center", "front", "rear", "left", "right", "below",
        };
        private static readonly string[] MotionPaths =
        {
            "static", "orbit", "patrol", "figure8", "vertical",
        };

        private enum DeckManipulationMode
        {
            None = 0,
            Move = 1,
            Resize = 2,
            Minimize = 3,
        }

        public bool IsDeckManipulating =>
            _deckManipulationMode != DeckManipulationMode.None;

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
            _exchange.GlbImported += OnGlbImported;
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
            {
                _exchange.ImageImported -= OnImageImported;
                _exchange.GlbImported -= OnGlbImported;
            }
            if (_spatialDeck != null)
                Destroy(_spatialDeck.gameObject);
        }

        private void Update()
        {
            SmoothDeckManipulation();
            if (
                Spatial == null ||
                Time.unscaledTime < _nextPreviewAt)
                return;
            _nextPreviewAt = Time.unscaledTime + 0.12f;
            _hasPreviewPose = Spatial.TryCreatorPlacement(
                new Vector2(0.5f, 0.5f),
                out _previewPosition,
                out _previewRotation);
            if (
                _hasPreviewPose &&
                _camera != null &&
                Vector3.Distance(
                    _camera.transform.position,
                    _previewPosition) < 0.55f)
            {
                // XREAL depth meshes can briefly expose a triangle at the XR
                // origin while they settle. Rendering the selected preset on
                // that hit makes its LineRenderers cross the stereo near plane
                // and cover both eyes. Never preview an unsafe placement.
                _hasPreviewPose = false;
            }
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
                _uniformScale = Mathf.Max(.1f, _uniformScale / 1.25f);
            GUILayout.Label(_uniformScale.ToString("0.0×"), _labelStyle);
            if (GUILayout.Button("TAILLE +", _button))
                _uniformScale = Mathf.Min(
                    WorldMapStore.MaxWorldScale,
                    _uniformScale * 1.25f);
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
                        _pendingAssetId,
                        MotionPaths[_motionIndex],
                        MotionRadius(),
                        .8f,
                        MotionHeight()))
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
            _spatialDeckRect.sizeDelta = new Vector2(920f, 1220f);
            // Optical see-through glasses must never receive a screen-sized
            // opaque slab.  Keep the editor within a comfortable ~28 degree
            // field of view and let the real world remain visible around and
            // through the controls.
            _spatialDeckRect.localScale = Vector3.one * .00062f;
            SetDeckPose();

            // Optical see-through means the real world is the background.
            // A screen-sized "glass" image still becomes a coloured veil once
            // emitted by the micro-OLED panels, even at low alpha. Keep only
            // the floating controls and their neon contour.
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
                new Vector2(-380f, -198f),
                new Vector2(110f, 46f),
                () =>
                {
                    _uniformScale = Mathf.Max(.1f, _uniformScale / 1.25f);
                    RefreshPreview();
                });
            _deckScale = MakeText(
                _spatialDeckRect,
                "1.0×",
                new Vector2(-260f, -198f),
                new Vector2(100f, 46f),
                18f,
                new Color(.32f, 1f, .88f),
                FontStyles.Bold);
            MakeButton(
                _spatialDeckRect,
                "TAILLE +",
                new Vector2(-145f, -198f),
                new Vector2(110f, 46f),
                () =>
                {
                    _uniformScale = Mathf.Min(
                        WorldMapStore.MaxWorldScale,
                        _uniformScale * 1.25f);
                    RefreshPreview();
                });
            MakeButton(
                _spatialDeckRect,
                "ROTATION ↻",
                new Vector2(-10f, -198f),
                new Vector2(130f, 46f),
                () =>
                {
                    _yaw += 15f;
                    RefreshPreview();
                });
            Button motion = MakeButton(
                _spatialDeckRect,
                "MOUV: STATIC",
                new Vector2(245f, -198f),
                new Vector2(340f, 46f),
                () =>
                {
                    _motionIndex = (_motionIndex + 1) % MotionPaths.Length;
                    RefreshSpatialDeck();
                    RefreshPreview();
                });
            _deckMotionLabel =
                motion.GetComponentInChildren<TextMeshProUGUI>();

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

            Button commit = MakeButton(
                _spatialDeckRect,
                "ANCRER DANS LE MONDE",
                new Vector2(0f, -332f),
                new Vector2(850f, 66f),
                AnchorFromSpatialDeck,
                true);
            _deckCommitLabel = commit.GetComponentInChildren<TextMeshProUGUI>();
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
            MakeButton(
                _spatialDeckRect,
                "IMPORTER GLB",
                new Vector2(-350f, -474f),
                new Vector2(170f, 44f),
                () => _exchange.BeginGlbImport());
            Button mode = MakeButton(
                _spatialDeckRect,
                "MODE ANCRÉ",
                new Vector2(-165f, -474f),
                new Vector2(170f, 44f),
                () =>
                {
                    _dynamicMode = !_dynamicMode;
                    RefreshSpatialDeck();
                });
            _deckModeLabel = mode.GetComponentInChildren<TextMeshProUGUI>();
            _deckTarget = MakeInput(
                _spatialDeckRect,
                "Cible précise (optionnel)",
                new Vector2(45f, -474f),
                new Vector2(225f, 44f),
                value => _dynamicTargetLabel = value);
            Button kind = MakeButton(
                _spatialDeckRect,
                "CIBLE: OBJECT",
                new Vector2(260f, -474f),
                new Vector2(180f, 44f),
                () =>
                {
                    _dynamicKindIndex =
                        (_dynamicKindIndex + 1) % DynamicKinds.Length;
                    RefreshSpatialDeck();
                });
            _deckKindLabel = kind.GetComponentInChildren<TextMeshProUGUI>();
            Button attachment = MakeButton(
                _spatialDeckRect,
                "POS: ABOVE",
                new Vector2(385f, -474f),
                new Vector2(110f, 44f),
                () =>
                {
                    _attachmentIndex =
                        (_attachmentIndex + 1) % Attachments.Length;
                    RefreshSpatialDeck();
                });
            _deckAttachmentLabel =
                attachment.GetComponentInChildren<TextMeshProUGUI>();

            MakeButton(
                _spatialDeckRect,
                "◀",
                new Vector2(-405f, -528f),
                new Vector2(65f, 44f),
                () => MoveManaged(-1));
            _deckManagedLabel = MakeText(
                _spatialDeckRect,
                "AUCUN ÉLÉMENT",
                new Vector2(-270f, -528f),
                new Vector2(190f, 44f),
                13f,
                new Color(.72f, .94f, 1f));
            MakeButton(
                _spatialDeckRect,
                "▶",
                new Vector2(-145f, -528f),
                new Vector2(65f, 44f),
                () => MoveManaged(1));
            MakeButton(
                _spatialDeckRect,
                "SUPPRIMER",
                new Vector2(-45f, -528f),
                new Vector2(125f, 44f),
                DeleteManaged);
            MakeButton(
                _spatialDeckRect,
                "NOUVELLE MAP",
                new Vector2(115f, -528f),
                new Vector2(175f, 44f),
                CreateMap);
            Button map = MakeButton(
                _spatialDeckRect,
                "MAP ▶",
                new Vector2(310f, -528f),
                new Vector2(200f, 44f),
                NextMap);
            _deckMapLabel = map.GetComponentInChildren<TextMeshProUGUI>();
            _deckStatus = MakeText(
                _spatialDeckRect,
                _status,
                new Vector2(0f, -586f),
                new Vector2(850f, 62f),
                17f,
                new Color(.25f, 1f, .9f),
                FontStyles.Bold);

            // Vision-Pro-style affordances: invisible until the existing gaze
            // ray reaches their zone. They are ordinary UGUI quads (never a
            // LineRenderer, which is unsafe under XREAL single-pass stereo).
            _deckMoveHandle = MakeImage(
                _spatialDeckRect,
                "Gaze move handle",
                new Vector2(0f, -603f),
                new Vector2(150f, 10f),
                new Color(.25f, 1f, .92f, .92f));
            _deckMoveHandle.raycastTarget = false;
            _deckMoveHandle.gameObject.SetActive(false);
            _deckResizeHandle = MakeImage(
                _spatialDeckRect,
                "Gaze resize handle",
                new Vector2(-447f, -587f),
                new Vector2(22f, 22f),
                new Color(.72f, .36f, 1f, .94f));
            _deckResizeHandle.rectTransform.localRotation =
                Quaternion.Euler(0f, 0f, 45f);
            _deckResizeHandle.raycastTarget = false;
            _deckResizeHandle.gameObject.SetActive(false);

            // The top-right affordance is intentionally gaze-revealed like the
            // move/resize handles. A pinch minimizes the dense deck; the compact
            // restore chip and the open-palm gesture can bring it back.
            _deckMinimizeHandle = MakeImage(
                _spatialDeckRect,
                "Gaze minimize handle",
                new Vector2(438f, 592f),
                new Vector2(34f, 8f),
                new Color(.35f, 1f, .94f, .94f));
            _deckMinimizeHandle.raycastTarget = false;
            _deckMinimizeHandle.gameObject.SetActive(false);

            _deckExpandedRoots.Clear();
            for (int i = 0; i < _spatialDeckRect.childCount; i++)
                _deckExpandedRoots.Add(
                    _spatialDeckRect.GetChild(i).gameObject);

            Image restore = MakeImage(
                _spatialDeckRect,
                "Atelier minimized restore chip",
                Vector2.zero,
                new Vector2(270f, 58f),
                new Color(.02f, .22f, .25f, .46f));
            _deckRestoreChip = restore.gameObject.AddComponent<Button>();
            var restoreCollider = restore.gameObject.AddComponent<BoxCollider>();
            restoreCollider.center = Vector3.zero;
            restoreCollider.size = new Vector3(270f, 58f, 14f);
            _deckRestoreChip.onClick.AddListener(() => SetDeckMinimized(false));
            MakeText(
                restore.transform,
                "ATELIER  â–´",
                Vector2.zero,
                new Vector2(250f, 48f),
                19f,
                new Color(.62f, 1f, .96f),
                FontStyles.Bold);
            _deckRestoreChip.gameObject.SetActive(false);

            _deckHitGraphics.Clear();
            _spatialDeckRect.GetComponentsInChildren(
                true,
                _deckHitGraphics);
            RefreshSpatialDeck();
        }

        private void AnchorFromSpatialDeck()
        {
            if (_dynamicMode)
            {
                if (Spatial == null || _selected == null)
                {
                    _status = "RÈGLE DYNAMIQUE INDISPONIBLE";
                    return;
                }
                Vector3 dynamicScale = _selected.defaultScale * _uniformScale;
                if (Spatial.SaveCreatorDynamicBinding(
                        _selected,
                        _dynamicTargetLabel,
                        DynamicKinds[_dynamicKindIndex],
                        Attachments[_attachmentIndex],
                        _label,
                        _subtitle,
                        dynamicScale,
                        _pendingAssetId))
                    _status = "RÈGLE DYNAMIQUE SAUVEGARDÉE";
                return;
            }
            if (
                Spatial == null ||
                !Spatial.CreatorReady ||
                _selected == null ||
                !_hasPreviewPose)
            {
                Spatial?.BeginCreatorSpatialMapping();
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
                    _pendingAssetId,
                    MotionPaths[_motionIndex],
                    MotionRadius(),
                    .8f,
                    MotionHeight()))
                _status = "SAUVEGARDE DE L'ANCRE NATIVE…";
        }

        private int ManagedCount =>
            (Spatial?.CreatorMap?.Contents.Count ?? 0) +
            (Spatial?.CreatorMap?.DynamicBindings.Count ?? 0);

        private void MoveManaged(int direction)
        {
            int count = ManagedCount;
            if (count <= 0)
            {
                _managedIndex = 0;
                return;
            }
            _managedIndex = (_managedIndex + direction + count) % count;
            RefreshSpatialDeck();
        }

        private void DeleteManaged()
        {
            WorldMapStore map = Spatial?.CreatorMap;
            if (map == null || ManagedCount == 0) return;
            _managedIndex = Mathf.Clamp(_managedIndex, 0, ManagedCount - 1);
            if (_managedIndex < map.Contents.Count)
                Spatial.RemoveCreatorContent(
                    map.Contents[_managedIndex].worldContentId);
            else
                Spatial.RemoveCreatorDynamicBinding(
                    map.DynamicBindings[
                        _managedIndex - map.Contents.Count].bindingId);
            _managedIndex = Mathf.Max(0, _managedIndex - 1);
        }

        private void CreateMap()
        {
            if (Spatial == null) return;
            string name = string.IsNullOrWhiteSpace(_label)
                ? "Nouveau monde"
                : _label;
            if (Spatial.CreateCreatorMap(name))
            {
                _lastCreatedId = string.Empty;
                _pendingAssetId = string.Empty;
                _managedIndex = 0;
                _status = "NOUVELLE MAP // " + name;
            }
        }

        private void NextMap()
        {
            IReadOnlyList<WorldMapSelection> maps = Spatial?.CreatorMaps;
            if (maps == null || maps.Count == 0) return;
            _mapIndex = (_mapIndex + 1) % maps.Count;
            if (Spatial.SwitchCreatorMap(maps[_mapIndex].mapId))
            {
                _lastCreatedId = string.Empty;
                _pendingAssetId = string.Empty;
                _managedIndex = 0;
                _status = "MAP ACTIVE // " + maps[_mapIndex].displayName;
            }
        }

        /// <summary>
        /// Intersect a native XR-hand ray with the actual world-space deck.
        /// The caller still drives EventSystem pointer events, so touch remains
        /// available as a parallel fallback without a second UI implementation.
        /// </summary>
        public bool TryProjectDeckPointer(
            Ray ray,
            out Vector2 screenPoint,
            out Vector3 worldPoint)
        {
            screenPoint = default;
            worldPoint = default;
            if (
                _spatialDeckRect == null ||
                _camera == null ||
                ray.direction.sqrMagnitude < .5f)
                return false;
            var plane = new Plane(
                _spatialDeckRect.forward,
                _spatialDeckRect.position);
            if (
                !plane.Raycast(ray, out float distance) ||
                distance < .03f ||
                distance > 4f)
                return false;
            worldPoint = ray.GetPoint(distance);
            Vector3 local =
                _spatialDeckRect.InverseTransformPoint(worldPoint);
            if (!_spatialDeckRect.rect.Contains(new Vector2(local.x, local.y)))
                return false;
            screenPoint =
                RectTransformUtility.WorldToScreenPoint(_camera, worldPoint);
            // WorldToScreenPoint uses the active XR eye target, whereas
            // Screen.width/height can still describe the S24 portrait display.
            // The RectTransform hit above already validates the deck bounds;
            // comparing these unrelated coordinate spaces rejected valid XR
            // hits while leaving the visual cursor alive.
            return true;
        }

        /// <summary>
        /// Resolve an interactive UGUI target directly in the world-space
        /// deck's local coordinates. XREAL's eye render target and the S24
        /// display do not share a screen coordinate system, so GraphicRaycaster
        /// can legitimately return no hit even after the 3D ray has intersected
        /// the correct control. This fallback never guesses a target: the
        /// world point must be inside the actual raycastable Graphic rect and
        /// that graphic must have a real click handler in its parent chain.
        /// </summary>
        public bool TryResolveDeckTarget(
            Vector3 worldPoint,
            out GameObject target)
        {
            target = null;
            float smallestArea = float.MaxValue;
            for (int i = 0; i < _deckHitGraphics.Count; i++)
            {
                Graphic graphic = _deckHitGraphics[i];
                if (
                    graphic == null ||
                    !graphic.isActiveAndEnabled ||
                    !graphic.raycastTarget)
                    continue;
                var rect = graphic.rectTransform;
                Vector3 local = rect.InverseTransformPoint(worldPoint);
                if (!rect.rect.Contains(new Vector2(local.x, local.y)))
                    continue;
                GameObject handler =
                    ExecuteEvents.GetEventHandler<IPointerClickHandler>(
                        graphic.gameObject);
                if (handler == null) continue;
                float area = Mathf.Abs(rect.rect.width * rect.rect.height);
                if (area >= smallestArea) continue;
                smallestArea = area;
                target = handler;
            }
            return target != null;
        }

        /// <summary>
        /// Reveal only the manipulation affordance currently targeted by the
        /// already-working gaze ray. No hand coordinates are used for aiming.
        /// </summary>
        public void UpdateDeckManipulationHover(
            Vector3 worldPoint,
            bool deckHit)
        {
            if (
                _deckManipulationMode != DeckManipulationMode.None ||
                _deckMinimized)
                return;
            _deckHoverMode = deckHit
                ? ClassifyDeckManipulationHandle(worldPoint)
                : DeckManipulationMode.None;
            SetDeckHandleVisuals(_deckHoverMode);
        }

        /// <summary>
        /// Claim a physical hand pinch only when gaze was on the bottom move
        /// handle or bottom-left resize handle. Normal buttons remain clicks.
        /// </summary>
        public bool TryBeginDeckManipulation(
            Vector3 gazeWorldPoint,
            Vector2 handAnchor,
            float zoomFactor)
        {
            if (
                _spatialDeckRect == null ||
                _camera == null ||
                handAnchor.x < 0f ||
                handAnchor.y < 0f)
                return false;
            DeckManipulationMode mode =
                ClassifyDeckManipulationHandle(gazeWorldPoint);
            if (mode == DeckManipulationMode.None) return false;
            if (mode == DeckManipulationMode.Minimize)
            {
                SetDeckMinimized(true);
                return true;
            }
            _deckManipulationMode = mode;
            _deckManipulationStartHand = handAnchor;
            _deckManipulationStartPosition = _spatialDeckRect.position;
            _deckManipulationStartCameraPosition =
                _camera.transform.position;
            _deckManipulationStartDistance = Mathf.Clamp(
                Vector3.Distance(
                    _camera.transform.position,
                    _deckManipulationStartPosition),
                .45f,
                2.8f);
            _deckManipulationStartDirection =
                (_deckManipulationStartPosition -
                 _deckManipulationStartCameraPosition)
                .normalized;
            // Freeze the viewing plane at grab time. Head-pose changes must not
            // rotate or drag an already world-anchored panel while the user is
            // moving their hand.
            _deckManipulationStartRight = _camera.transform.right.normalized;
            _deckManipulationStartUp = _camera.transform.up.normalized;
            _deckManipulationStartScale = _spatialDeckRect.localScale.x;
            _deckManipulationStartZoom = Mathf.Max(.1f, zoomFactor);
            _deckManipulationTargetPosition = _deckManipulationStartPosition;
            _deckManipulationTargetScale = _deckManipulationStartScale;
            _deckManipulationSmoothing = true;
            SetDeckHandleVisuals(mode);
            return true;
        }

        /// <summary>
        /// Hand motion manipulates the gaze-selected handle. X/Y move in the
        /// viewing plane; pinch aperture provides a bounded monocular depth
        /// adjustment. The resize handle preserves the deck aspect ratio.
        /// </summary>
        public void UpdateDeckManipulation(
            Vector2 handAnchor,
            float zoomFactor)
        {
            if (
                _deckManipulationMode == DeckManipulationMode.None ||
                _spatialDeckRect == null ||
                _camera == null ||
                handAnchor.x < 0f ||
                handAnchor.y < 0f)
                return;
            Vector2 delta = handAnchor - _deckManipulationStartHand;
            delta.x = Mathf.Clamp(delta.x, -.75f, .75f);
            delta.y = Mathf.Clamp(delta.y, -.65f, .65f);
            if (_deckManipulationMode == DeckManipulationMode.Move)
            {
                float span = _deckManipulationStartDistance * 1.15f;
                Vector3 planar =
                    _deckManipulationStartRight * (delta.x * span) +
                    _deckManipulationStartUp * (-delta.y * span * .8f);
                float depth = Mathf.Clamp(
                    _deckManipulationStartDistance -
                    (zoomFactor - _deckManipulationStartZoom) * .16f,
                    .45f,
                    2.8f);
                _deckManipulationTargetPosition =
                    _deckManipulationStartCameraPosition +
                    _deckManipulationStartDirection * depth +
                    planar;
            }
            else
            {
                // Dragging the bottom-left handle outwards (left/down in the
                // Eye image) grows the deck; inward motion shrinks it.
                float gesture = -delta.x + delta.y;
                float factor = Mathf.Clamp(1f + gesture * 1.35f, .58f, 1.75f);
                float scale = Mathf.Clamp(
                    _deckManipulationStartScale * factor,
                    .00038f,
                    .00108f);
                _deckManipulationTargetScale = scale;
            }
            _deckManipulationSmoothing = true;
        }

        public void EndDeckManipulation()
        {
            _deckManipulationMode = DeckManipulationMode.None;
            _deckHoverMode = DeckManipulationMode.None;
            SetDeckHandleVisuals(DeckManipulationMode.None);
        }

        private DeckManipulationMode ClassifyDeckManipulationHandle(
            Vector3 worldPoint)
        {
            if (_spatialDeckRect == null) return DeckManipulationMode.None;
            Vector3 local3 = _spatialDeckRect.InverseTransformPoint(worldPoint);
            Vector2 local = new Vector2(local3.x, local3.y);
            Rect rect = _spatialDeckRect.rect;
            if (!rect.Contains(local)) return DeckManipulationMode.None;
            if (
                local.x <= rect.xMin + 95f &&
                local.y <= rect.yMin + 85f)
                return DeckManipulationMode.Resize;
            if (
                local.x >= rect.xMax - 95f &&
                local.y >= rect.yMax - 85f)
                return DeckManipulationMode.Minimize;
            if (
                Mathf.Abs(local.x) <= 175f &&
                local.y <= rect.yMin + 58f)
                return DeckManipulationMode.Move;
            return DeckManipulationMode.None;
        }

        private void SetDeckHandleVisuals(DeckManipulationMode mode)
        {
            if (_deckMoveHandle != null)
                _deckMoveHandle.gameObject.SetActive(
                    mode == DeckManipulationMode.Move);
            if (_deckResizeHandle != null)
                _deckResizeHandle.gameObject.SetActive(
                    mode == DeckManipulationMode.Resize);
            if (_deckMinimizeHandle != null)
                _deckMinimizeHandle.gameObject.SetActive(
                    mode == DeckManipulationMode.Minimize);
        }

        /// <summary>
        /// Restore the deck from a held open palm. This is intentionally open-
        /// only rather than a toggle so a repeated/late palm classification can
        /// never make the controls disappear again.
        /// </summary>
        public void OpenDeckFromPalm()
        {
            if (!_deckMinimized) return;
            SetDeckMinimized(false);
            SetDeckPose();
            _status = "PUPITRE OUVERT // PAUME";
            RefreshSpatialDeck();
        }

        private void SetDeckMinimized(bool minimized)
        {
            if (_deckMinimized == minimized) return;
            if (minimized) EndDeckManipulation();
            _deckMinimized = minimized;
            for (int i = 0; i < _deckExpandedRoots.Count; i++)
            {
                GameObject root = _deckExpandedRoots[i];
                if (root != null) root.SetActive(!minimized);
            }
            if (_deckRestoreChip != null)
                _deckRestoreChip.gameObject.SetActive(minimized);
            if (!minimized)
            {
                SetDeckHandleVisuals(DeckManipulationMode.None);
                SetDeckPose();
            }
        }

        /// <summary>
        /// MediaPipe produces hand anchors slower than the 60 Hz display. Keep
        /// the latest hand-derived target, then interpolate the world-space deck
        /// every rendered frame so sparse inference never becomes visible steps.
        /// </summary>
        private void SmoothDeckManipulation()
        {
            if (!_deckManipulationSmoothing || _spatialDeckRect == null) return;
            float blend = 1f - Mathf.Exp(-18f * Time.unscaledDeltaTime);
            _spatialDeckRect.position = Vector3.Lerp(
                _spatialDeckRect.position,
                _deckManipulationTargetPosition,
                blend);
            float scale = Mathf.Lerp(
                _spatialDeckRect.localScale.x,
                _deckManipulationTargetScale,
                blend);
            _spatialDeckRect.localScale = Vector3.one * scale;

            if (
                _deckManipulationMode == DeckManipulationMode.None &&
                Vector3.Distance(
                    _spatialDeckRect.position,
                    _deckManipulationTargetPosition) < .001f &&
                Mathf.Abs(scale - _deckManipulationTargetScale) < .000002f)
            {
                _spatialDeckRect.position = _deckManipulationTargetPosition;
                _spatialDeckRect.localScale =
                    Vector3.one * _deckManipulationTargetScale;
                _deckManipulationSmoothing = false;
            }
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
            if (_deckMotionLabel != null)
                _deckMotionLabel.text =
                    "MOUV: " + MotionPaths[_motionIndex].ToUpperInvariant();
            if (_deckPage != null)
                _deckPage.text = (_page + 1) + "/" + PageCount;
            if (_deckAsset != null)
                _deckAsset.text = string.IsNullOrEmpty(_pendingAssetId)
                    ? "AUCUN ASSET"
                    : (Spatial?.CreatorMap?.FindAsset(_pendingAssetId)?.kind ==
                        "glb_model"
                        ? "MODÈLE GLB PRÊT ✓"
                        : "LOGO 3D PRÊT ✓");
            if (_deckCommitLabel != null)
                _deckCommitLabel.text = _dynamicMode
                    ? "LIER AU FLUX DYNAMIQUE"
                    : "ANCRER DANS LE MONDE";
            if (_deckModeLabel != null)
                _deckModeLabel.text = _dynamicMode
                    ? "MODE DYNAMIQUE"
                    : "MODE ANCRÉ";
            if (_deckKindLabel != null)
                _deckKindLabel.text =
                    "CIBLE: " + DynamicKinds[_dynamicKindIndex].ToUpperInvariant();
            if (_deckAttachmentLabel != null)
                _deckAttachmentLabel.text =
                    "POS: " + Attachments[_attachmentIndex].ToUpperInvariant();
            if (_deckTarget != null && !_deckTarget.isFocused)
                _deckTarget.SetTextWithoutNotify(_dynamicTargetLabel);
            if (_deckManagedLabel != null)
                _deckManagedLabel.text = ManagedLabel();
            if (_deckMapLabel != null)
            {
                string mapName = Spatial?.CreatorMap?.Document.displayName ??
                    "MAP";
                _deckMapLabel.text = mapName.ToUpperInvariant() + " ▶";
            }
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
            _deckManipulationSmoothing = false;
            FollowSpatialDeck(true);
            if (_spatialDeckRect != null)
            {
                _deckManipulationTargetPosition = _spatialDeckRect.position;
                _deckManipulationTargetScale = _spatialDeckRect.localScale.x;
            }
        }

        private void FollowSpatialDeck(bool snap)
        {
            if (_spatialDeckRect == null || _camera == null) return;
            Vector3 forward = _camera.transform.forward.normalized;
            Vector3 up = Mathf.Abs(Vector3.Dot(forward, Vector3.up)) > .96f
                ? _camera.transform.up
                : Vector3.up;
            Vector3 targetPosition =
                _camera.transform.position +
                forward * 1.12f -
                _camera.transform.up * .035f;
            Quaternion targetRotation = Quaternion.LookRotation(forward, up);

            if (snap || !_deckPoseInitialized)
            {
                _spatialDeckRect.SetPositionAndRotation(
                    targetPosition,
                    targetRotation);
                _deckPoseInitialized = true;
                return;
            }

            // Keep the editor deck world-stable inside a comfort dead-zone.
            // Following every sub-millimetre head-pose update made the dense UI
            // visibly swim even though the official XREAL rig itself was stable.
            float positionError = Vector3.Distance(
                _spatialDeckRect.position,
                targetPosition);
            float rotationError = Quaternion.Angle(
                _spatialDeckRect.rotation,
                targetRotation);
            if (positionError < .065f && rotationError < 4.5f)
                return;

            float blend = 1f - Mathf.Exp(-7f * Time.unscaledDeltaTime);
            _spatialDeckRect.position = Vector3.Lerp(
                _spatialDeckRect.position,
                targetPosition,
                blend);
            _spatialDeckRect.rotation = Quaternion.Slerp(
                _spatialDeckRect.rotation,
                targetRotation,
                blend);
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
                    ? new Color(.02f, .45f, .42f, .42f)
                    : new Color(.025f, .11f, .2f, .30f));
            Button button = image.gameObject.AddComponent<Button>();
            var collider = image.gameObject.AddComponent<BoxCollider>();
            collider.center = Vector3.zero;
            collider.size = new Vector3(size.x, size.y, 14f);
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
                Shader.Find("Sprites/Default") ??
                Shader.Find("Unlit/Transparent") ??
                Shader.Find("MLOmega/XREAL Runtime Unlit");
            var material = new Material(shader);
            Color color = primary
                ? new Color(.04f, .38f, .42f, .16f)
                : new Color(.01f, .045f, .1f, .08f);
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
            material.renderQueue = 3000;
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
                new Color(.02f, .07f, .14f, .34f));
            TMP_InputField input =
                image.gameObject.AddComponent<TMP_InputField>();
            var collider = image.gameObject.AddComponent<BoxCollider>();
            collider.center = Vector3.zero;
            collider.size = new Vector3(size.x, size.y, 14f);
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
            input.textViewport = image.rectTransform;
            input.targetGraphic = image;
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
                    ? new Color(.05f, .55f, .48f, .48f)
                    : new Color(.025f, .11f, .2f, .30f);
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
                { "asset_file_path", asset?.localFilePath ?? string.Empty },
                { "motion_path", MotionPaths[_motionIndex] },
                { "motion_radius_m", MotionRadius() },
                { "motion_speed", .8f },
                { "motion_height_m", MotionHeight() },
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
                if (detail == "saved")
                {
                    _lastCreatedId = contentId;
                    _status = "ANCRE SAUVEGARDÉE // " +
                        (Spatial?.CreatorMap?.Contents.Count ?? 0) +
                        " ÉLÉMENT(S)";
                }
                else if (detail == "dynamic_saved")
                    _status = "RÈGLE DYNAMIQUE SAUVEGARDÉE // " +
                        (Spatial?.CreatorMap?.DynamicBindings.Count ?? 0);
                else if (detail == "dynamic_removed" || detail == string.Empty)
                    _status = "ÉLÉMENT SUPPRIMÉ";
                else if (detail.StartsWith("map_", StringComparison.Ordinal))
                    _status = "MAP // " + detail.Replace("_", " ").ToUpperInvariant();
            }
            else
            {
                _status = "ÉCHEC ANCRE // " + detail;
            }
        }

        private float MotionRadius() =>
            Mathf.Clamp(
                Mathf.Max(1.5f, _uniformScale * 1.2f),
                .1f,
                40f);

        private float MotionHeight() =>
            MotionPaths[_motionIndex] == "static"
                ? 0f
                : Mathf.Clamp(_uniformScale * .35f, 0f, 20f);

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

        private void OnGlbImported(string path)
        {
            string error = string.Empty;
            if (
                Spatial?.CreatorMap != null &&
                Spatial.CreatorMap.TryAddGlbAsset(
                    path,
                    out string assetId,
                    out error))
            {
                _pendingAssetId = assetId;
                _status = "MODÈLE GLB VALIDÉ // " + assetId;
                RefreshPreview();
            }
            else
            {
                _status = "GLB REFUSÉ // " + (error ?? "unknown");
            }
        }

        private string ManagedLabel()
        {
            WorldMapStore map = Spatial?.CreatorMap;
            int count = ManagedCount;
            if (map == null || count == 0) return "AUCUN ÉLÉMENT";
            _managedIndex = Mathf.Clamp(_managedIndex, 0, count - 1);
            if (_managedIndex < map.Contents.Count)
            {
                WorldMapStore.WorldContent item = map.Contents[_managedIndex];
                return "A // " +
                    (string.IsNullOrWhiteSpace(item.label)
                        ? item.templateId
                        : item.label);
            }
            WorldMapStore.WorldDynamicBinding binding =
                map.DynamicBindings[_managedIndex - map.Contents.Count];
            return "D // " +
                (string.IsNullOrWhiteSpace(binding.targetLabel)
                    ? binding.targetKind
                    : binding.targetLabel);
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

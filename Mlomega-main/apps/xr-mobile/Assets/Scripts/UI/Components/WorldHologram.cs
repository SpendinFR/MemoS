using System;
using System.Collections.Generic;
using MLOmega.Contracts.V19;
using TMPro;
using UnityEngine;
using UnityEngine.Rendering;

namespace MLOmega.XR.UI.Components
{
    /// <summary>
    /// Bounded procedural FreeGuy decoration attached to geometry proven by the
    /// XREAL pose/depth provider. It deliberately uses no opaque screen-space quad:
    /// every primitive lives in tracking-local space and disappears with its intent.
    /// </summary>
    public sealed class WorldHologram : UIComponentBase
    {
        public sealed class Hologram
        {
            public Vector3 Position;
            public string Id;
            public string CalibrationId;
            public string TemplateId;
            public string Label;
            public string Subtitle;
            public float Quality;
            public bool DepthValid;
        }

        private readonly List<LineRenderer> _lines = new List<LineRenderer>();
        private Material _lineMaterial;
        private Material _panelMaterial;
        private MeshRenderer _panel;
        private TextMeshPro _label;
        private Hologram _hologram;
        private bool _qualified;
        private Color _accent;

        public override string ComponentKey => "world_hologram";
        public bool IsQualified => _qualified;
        public string TemplateId => _hologram?.TemplateId ?? string.Empty;

        protected override void OnConfigured()
        {
            Shader shader = Shader.Find("Universal Render Pipeline/Unlit") ??
                Shader.Find("Sprites/Default") ??
                Shader.Find("Unlit/Color");
            if (shader != null)
            {
                _lineMaterial = TransparentMaterial(shader);
                _panelMaterial = TransparentMaterial(shader);
            }

            for (int i = 0; i < 5; i++)
                _lines.Add(MakeLine("HoloLine" + i, i == 0 ? 0.022f : 0.012f));

            var panelGo = GameObject.CreatePrimitive(PrimitiveType.Quad);
            panelGo.name = "HoloPanel";
            panelGo.transform.SetParent(transform, false);
            Collider collider = panelGo.GetComponent<Collider>();
            if (collider != null) Destroy(collider);
            _panel = panelGo.GetComponent<MeshRenderer>();
            if (_panelMaterial != null) _panel.sharedMaterial = _panelMaterial;

            var labelGo = new GameObject("HoloLabel");
            labelGo.transform.SetParent(transform, false);
            _label = labelGo.AddComponent<TextMeshPro>();
            _label.alignment = TextAlignmentOptions.Center;
            _label.fontStyle = FontStyles.Bold;
            _label.fontSize = 0.065f;
            _label.enableWordWrapping = false;
        }

        protected override void Bind(UIIntent intent)
        {
            _qualified = TryReadHologram(intent, out _hologram, out _);
            SetEnabled(_qualified);
            if (!_qualified) return;

            _accent = TemplateColor(_hologram.TemplateId);
            _label.text =
                $"<color=#{ColorUtility.ToHtmlStringRGB(_accent)}>" +
                CleanLabel(_hologram.Label).ToUpperInvariant() +
                "</color>" +
                (string.IsNullOrWhiteSpace(_hologram.Subtitle)
                    ? string.Empty
                    : "\n<size=56%><color=#C8E8F2>" +
                      CleanLabel(_hologram.Subtitle) +
                      "</color></size>");
        }

        protected override void OnTruth(TruthDescriptor truth)
        {
            // Admission is fail-closed in TryReadHologram. Colour denotes the
            // visual template rather than attempting to hide truth state.
        }

        protected override void Update()
        {
            base.Update();
            if (Phase == UIComponentPhase.Idle || !_qualified) return;
            Draw(Time.unscaledTime);
        }

        protected override void ApplyVisual() =>
            ApplyColor(CurrentAlpha, 1f);

        private void Draw(float now)
        {
            Camera cam = Context != null ? Context.Camera : Camera.main;
            Vector3 origin = _hologram.Position;
            Vector3 toCamera = cam == null
                ? Vector3.back
                : cam.transform.position - origin;
            Vector3 flatForward = Vector3.ProjectOnPlane(toCamera, Vector3.up);
            if (flatForward.sqrMagnitude < 0.0001f) flatForward = Vector3.back;
            flatForward.Normalize();
            Vector3 right = Vector3.Cross(Vector3.up, flatForward).normalized;
            float pulse = 0.75f + 0.25f * Mathf.Sin(now * 3.1f);

            switch (_hologram.TemplateId)
            {
                case "holo_billboard":
                    DrawBillboard(origin, right, flatForward, now);
                    break;
                case "vehicle_fx":
                    DrawVehicleFx(origin, right, flatForward, now);
                    break;
                case "poi_beacon":
                    DrawBeacon(origin, right, flatForward, now);
                    break;
                case "memory_echo":
                    DrawMemoryEcho(origin, right, flatForward, now);
                    break;
                default:
                    DrawNeonSign(origin, right, flatForward, now);
                    break;
            }
            ApplyColor(CurrentAlpha, pulse);
        }

        private void DrawNeonSign(
            Vector3 origin, Vector3 right, Vector3 forward, float now)
        {
            float hover = 0.62f + Mathf.Sin(now * 2.2f) * 0.025f;
            Vector3 center = origin + Vector3.up * hover;
            Rectangle(_lines[0], center, right, Vector3.up, 0.48f, 0.16f);
            Rectangle(_lines[1], center, right, Vector3.up, 0.43f, 0.125f);
            Ring(_lines[2], origin + Vector3.up * 0.025f, right, forward, 0.16f, 32);
            SetLine(_lines[3], origin, center - right * 0.48f, center + right * 0.48f);
            SetLine(_lines[4], center - Vector3.up * 0.16f, center + Vector3.up * 0.16f);
            PlacePanel(center, right, Vector3.up, 0.88f, 0.25f, forward);
            PlaceLabel(center, forward);
        }

        private void DrawBillboard(
            Vector3 origin, Vector3 right, Vector3 forward, float now)
        {
            Vector3 center =
                origin + Vector3.up * (0.48f + Mathf.Sin(now * 1.7f) * 0.02f);
            Rectangle(_lines[0], center, right, Vector3.up, 0.58f, 0.28f);
            Rectangle(_lines[1], center, right, Vector3.up, 0.53f, 0.23f);
            for (int i = 2; i < _lines.Count; i++)
            {
                float x = Mathf.Lerp(-0.48f, 0.48f, (i - 1) / 4f);
                SetLine(
                    _lines[i],
                    center + right * x - Vector3.up * 0.2f,
                    center + right * x + Vector3.up * 0.2f);
            }
            PlacePanel(center, right, Vector3.up, 1.04f, 0.45f, forward);
            PlaceLabel(center, forward);
        }

        private void DrawVehicleFx(
            Vector3 origin, Vector3 right, Vector3 forward, float now)
        {
            Vector3 basePoint = origin + Vector3.up * 0.12f;
            for (int i = 0; i < _lines.Count; i++)
            {
                float lane = (i - 2f) * 0.07f;
                float phase = Mathf.Repeat(now * 0.9f + i * 0.17f, 1f);
                float length = Mathf.Lerp(0.16f, 0.62f, phase);
                Vector3 start = basePoint + right * lane;
                Vector3 end =
                    start + forward * length +
                    Vector3.up * (0.04f + Mathf.Sin(now * 4f + i) * 0.035f);
                SetLine(_lines[i], start, Vector3.Lerp(start, end, 0.48f), end);
            }
            _panel.enabled = false;
            _label.transform.position = basePoint + Vector3.up * 0.34f;
            PlaceLabel(_label.transform.position, forward);
        }

        private void DrawBeacon(
            Vector3 origin, Vector3 right, Vector3 forward, float now)
        {
            float height = 1.15f + Mathf.Sin(now * 2.1f) * 0.08f;
            Vector3 top = origin + Vector3.up * height;
            SetLine(_lines[0], origin, top);
            Ring(_lines[1], origin + Vector3.up * 0.03f, right, forward, 0.26f, 36);
            Ring(_lines[2], origin + Vector3.up * 0.05f, right, forward,
                0.42f + Mathf.Sin(now * 2f) * 0.04f, 36);
            Ring(_lines[3], top, right, Vector3.up, 0.18f, 32);
            SetLine(_lines[4], top - right * 0.22f, top + right * 0.22f);
            PlacePanel(top, right, Vector3.up, 0.62f, 0.22f, forward);
            PlaceLabel(top, forward);
        }

        private void DrawMemoryEcho(
            Vector3 origin, Vector3 right, Vector3 forward, float now)
        {
            for (int i = 0; i < _lines.Count; i++)
            {
                float radius = 0.13f + i * 0.075f +
                    Mathf.Sin(now * 1.7f + i) * 0.015f;
                Ring(
                    _lines[i],
                    origin + Vector3.up * (0.08f + i * 0.06f),
                    right,
                    forward,
                    radius,
                    32);
            }
            _panel.enabled = false;
            _label.transform.position = origin + Vector3.up * 0.62f;
            PlaceLabel(_label.transform.position, forward);
        }

        private void PlacePanel(
            Vector3 center,
            Vector3 right,
            Vector3 up,
            float width,
            float height,
            Vector3 forward)
        {
            _panel.enabled = true;
            _panel.transform.position = center + forward * 0.008f;
            _panel.transform.rotation = Quaternion.LookRotation(-forward, up);
            _panel.transform.localScale = new Vector3(width, height, 1f);
        }

        private void PlaceLabel(Vector3 center, Vector3 forward)
        {
            _label.transform.position = center - forward * 0.012f;
            _label.transform.rotation = Quaternion.LookRotation(-forward, Vector3.up);
        }

        private void ApplyColor(float alpha, float pulse)
        {
            Color edge = _accent;
            edge.a = Mathf.Clamp01(alpha) * Mathf.Lerp(0.62f, 0.98f, pulse);
            Color fill = _accent;
            fill.a = Mathf.Clamp01(alpha) * 0.13f;
            foreach (LineRenderer line in _lines)
            {
                line.startColor = edge;
                line.endColor = edge;
            }
            SetMaterialColor(_lineMaterial, edge);
            SetMaterialColor(_panelMaterial, fill);
            if (_label != null)
            {
                Color label = Color.white;
                label.a = Mathf.Clamp01(alpha);
                _label.color = label;
            }
        }

        private LineRenderer MakeLine(string name, float width)
        {
            var go = new GameObject(name);
            go.transform.SetParent(transform, false);
            var line = go.AddComponent<LineRenderer>();
            line.useWorldSpace = true;
            line.widthMultiplier = width;
            line.alignment = LineAlignment.View;
            line.numCornerVertices = 4;
            if (_lineMaterial != null) line.sharedMaterial = _lineMaterial;
            return line;
        }

        private static void SetLine(LineRenderer line, params Vector3[] points)
        {
            line.loop = false;
            line.positionCount = points.Length;
            line.SetPositions(points);
        }

        private static void Rectangle(
            LineRenderer line,
            Vector3 center,
            Vector3 right,
            Vector3 up,
            float halfWidth,
            float halfHeight)
        {
            line.loop = true;
            line.positionCount = 4;
            line.SetPosition(0, center - right * halfWidth - up * halfHeight);
            line.SetPosition(1, center - right * halfWidth + up * halfHeight);
            line.SetPosition(2, center + right * halfWidth + up * halfHeight);
            line.SetPosition(3, center + right * halfWidth - up * halfHeight);
        }

        private static void Ring(
            LineRenderer line,
            Vector3 center,
            Vector3 axisA,
            Vector3 axisB,
            float radius,
            int count)
        {
            line.loop = true;
            line.positionCount = count;
            for (int i = 0; i < count; i++)
            {
                float angle = i / (float)count * Mathf.PI * 2f;
                line.SetPosition(
                    i,
                    center +
                    axisA * (Mathf.Cos(angle) * radius) +
                    axisB * (Mathf.Sin(angle) * radius));
            }
        }

        private void SetEnabled(bool enabled)
        {
            foreach (LineRenderer line in _lines) line.enabled = enabled;
            if (_panel != null) _panel.enabled = enabled;
            if (_label != null) _label.enabled = enabled;
        }

        private void OnDestroy()
        {
            if (_lineMaterial != null) Destroy(_lineMaterial);
            if (_panelMaterial != null) Destroy(_panelMaterial);
        }

        public static bool TryReadHologram(
            UIIntent intent,
            out Hologram hologram,
            out string error)
        {
            hologram = null;
            if (!WorldSemanticMarker.TryReadMarker(
                    intent,
                    out WorldSemanticMarker.Marker marker,
                    out error))
                return false;
            string template = IntentRead.Content(
                intent, "template_id", "").Trim().ToLowerInvariant();
            if (!AllowedTemplate(template))
            {
                error = "hologram_template_invalid";
                return false;
            }
            hologram = new Hologram
            {
                Position = marker.Position,
                Id = marker.MarkerId,
                CalibrationId = marker.CalibrationId,
                TemplateId = template,
                Label = marker.Label,
                Subtitle = marker.Subtitle,
                Quality = marker.AnchorQuality,
                DepthValid = marker.DepthValid,
            };
            error = null;
            return true;
        }

        private static bool AllowedTemplate(string template)
        {
            switch (template)
            {
                case "neon_sign":
                case "holo_billboard":
                case "vehicle_fx":
                case "poi_beacon":
                case "memory_echo":
                case "annotation":
                    return true;
                default:
                    return false;
            }
        }

        private static string CleanLabel(string value)
        {
            string clean = (value ?? string.Empty).Replace("<", "‹").Replace(">", "›");
            return clean.Length <= 80 ? clean : clean.Substring(0, 80);
        }

        private static Color TemplateColor(string template)
        {
            switch (template)
            {
                case "holo_billboard": return new Color(1f, 0.24f, 0.78f, 1f);
                case "vehicle_fx": return new Color(1f, 0.34f, 0.1f, 1f);
                case "poi_beacon": return new Color(0.2f, 1f, 0.62f, 1f);
                case "memory_echo": return new Color(0.65f, 0.38f, 1f, 1f);
                default: return new Color(0.15f, 0.92f, 1f, 1f);
            }
        }

        private static Material TransparentMaterial(Shader shader)
        {
            var material = new Material(shader);
            if (material.HasProperty("_Surface")) material.SetFloat("_Surface", 1f);
            if (material.HasProperty("_SrcBlend"))
                material.SetFloat("_SrcBlend", (float)BlendMode.SrcAlpha);
            if (material.HasProperty("_DstBlend"))
                material.SetFloat("_DstBlend", (float)BlendMode.OneMinusSrcAlpha);
            if (material.HasProperty("_ZWrite")) material.SetFloat("_ZWrite", 0f);
            material.EnableKeyword("_SURFACE_TYPE_TRANSPARENT");
            material.renderQueue = (int)RenderQueue.Transparent;
            return material;
        }

        private static void SetMaterialColor(Material material, Color color)
        {
            if (material == null) return;
            if (material.HasProperty("_BaseColor"))
                material.SetColor("_BaseColor", color);
            if (material.HasProperty("_Color"))
                material.SetColor("_Color", color);
        }
    }
}

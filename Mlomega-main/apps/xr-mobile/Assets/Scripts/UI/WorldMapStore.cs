using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace MLOmega.XR.UI
{
    /// <summary>
    /// Durable, device-local catalogue for externally-authored FreeGuy content.
    ///
    /// The production APK is a load-only consumer; a separate future Atelier APK
    /// may export the same versioned document. This store contains only presentation
    /// and spatial provenance. It never opens memory.db and its identifiers are
    /// deliberately independent from WebRTC, BrainLive and CloseDay identifiers.
    /// </summary>
    public sealed class WorldMapStore
    {
        public const int CurrentSchemaVersion = 1;
        private const double EarthRadiusM = 6378137.0;

        [Serializable]
        public sealed class MapDocument
        {
            public int schemaVersion = CurrentSchemaVersion;
            public string worldMapId;
            public string calibrationId;
            public long createdAtUnixMs;
            public long updatedAtUnixMs;
            public bool geoOriginValid;
            public double originLatitude;
            public double originLongitude;
            public double originAltitudeM;
            public float originAccuracyM;
            public float worldNorthYawDeg;
            public StoredVector3 localOrigin;
            public List<WorldContent> contents = new List<WorldContent>();
        }

        [Serializable]
        public sealed class WorldContent
        {
            public string worldContentId;
            public string anchorGuid;
            public string templateId;
            public string label;
            public string subtitle;
            public string targetTrackId;
            public string author;
            public string provenance;
            public string state;
            public float quality;
            public bool geoPoseValid;
            public double latitude;
            public double longitude;
            public double altitudeM;
            public long createdAtUnixMs;
            public long updatedAtUnixMs;
            public StoredVector3 localPosition;
            public StoredVector3 localEuler;
            public StoredVector3 localScale;
        }

        [Serializable]
        public struct StoredVector3
        {
            public float x;
            public float y;
            public float z;

            public StoredVector3(Vector3 value)
            {
                x = value.x;
                y = value.y;
                z = value.z;
            }

            public Vector3 Value => new Vector3(x, y, z);
        }

        private readonly string _path;
        private MapDocument _document;

        public WorldMapStore(string directory, string calibrationId)
        {
            if (string.IsNullOrWhiteSpace(directory))
                throw new ArgumentException("world map directory is required", nameof(directory));
            Directory.CreateDirectory(directory);
            _path = Path.Combine(directory, "world-map-v1.json");
            _document = LoadDocument(calibrationId);
        }

        public string FilePath => _path;
        public MapDocument Document => _document;
        public string WorldMapId => _document.worldMapId;
        public IReadOnlyList<WorldContent> Contents => _document.contents;
        public bool HasGeoOrigin => _document.geoOriginValid;

        /// <summary>
        /// Fix the Earth-to-XREAL transform. A noisy fix never replaces a materially
        /// better one unless the caller explicitly starts a new calibration.
        /// </summary>
        public bool SetGeoOrigin(
            double latitude,
            double longitude,
            double altitudeM,
            float accuracyM,
            float worldNorthYawDeg,
            Vector3 localOrigin,
            bool force = false)
        {
            if (!Finite(latitude) || !Finite(longitude) || !Finite(altitudeM) ||
                !Finite(accuracyM) || accuracyM <= 0f ||
                latitude < -90d || latitude > 90d ||
                longitude < -180d || longitude > 180d)
                return false;
            if (
                !force &&
                _document.geoOriginValid &&
                accuracyM >= _document.originAccuracyM * 0.8f)
                return false;

            _document.geoOriginValid = true;
            _document.originLatitude = latitude;
            _document.originLongitude = longitude;
            _document.originAltitudeM = altitudeM;
            _document.originAccuracyM = accuracyM;
            _document.worldNorthYawDeg = NormaliseYaw(worldNorthYawDeg);
            _document.localOrigin = new StoredVector3(localOrigin);
            Touch();
            Save();
            return true;
        }

        /// <summary>Convert WGS84 coordinates to XREAL tracking-local metres.</summary>
        public bool TryGeoToLocal(
            double latitude,
            double longitude,
            double altitudeM,
            out Vector3 local)
        {
            local = default;
            if (!_document.geoOriginValid ||
                !Finite(latitude) || !Finite(longitude) || !Finite(altitudeM))
                return false;

            double lat0 = _document.originLatitude * Math.PI / 180d;
            double northM =
                (latitude - _document.originLatitude) * Math.PI / 180d * EarthRadiusM;
            double eastM =
                (longitude - _document.originLongitude) * Math.PI / 180d *
                EarthRadiusM * Math.Cos(lat0);
            double upM = altitudeM - _document.originAltitudeM;
            if (
                Math.Abs(eastM) > 20000d ||
                Math.Abs(northM) > 20000d ||
                Math.Abs(upM) > 2000d)
                return false;

            Quaternion northRotation = Quaternion.Euler(
                0f, _document.worldNorthYawDeg, 0f);
            Vector3 offset =
                northRotation * Vector3.right * (float)eastM +
                northRotation * Vector3.forward * (float)northM +
                Vector3.up * (float)upM;
            local = _document.localOrigin.Value + offset;
            return Finite(local.x) && Finite(local.y) && Finite(local.z);
        }

        public WorldContent Upsert(
            string worldContentId,
            string anchorGuid,
            string templateId,
            string label,
            string subtitle,
            string targetTrackId,
            string author,
            string provenance,
            Vector3 position,
            Quaternion rotation,
            Vector3 scale,
            float quality,
            string state = "tracking",
            bool geoPoseValid = false,
            double latitude = 0d,
            double longitude = 0d,
            double altitudeM = 0d)
        {
            string id = CleanId(worldContentId);
            if (string.IsNullOrEmpty(id))
                id = "world-" + Guid.NewGuid().ToString("N");
            WorldContent record = FindById(id);
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (record == null)
            {
                record = new WorldContent
                {
                    worldContentId = id,
                    createdAtUnixMs = now,
                };
                _document.contents.Add(record);
            }
            record.anchorGuid = CleanId(anchorGuid);
            record.templateId = CleanTemplate(templateId);
            record.label = CleanText(label, 120);
            record.subtitle = CleanText(subtitle, 240);
            record.targetTrackId = CleanId(targetTrackId);
            record.author = author == "automatic" ? "automatic" : "manual";
            record.provenance = CleanText(provenance, 240);
            record.state = state == "tracking" ? "tracking" : "unresolved";
            record.quality = Mathf.Clamp01(quality);
            record.geoPoseValid =
                geoPoseValid &&
                Finite(latitude) &&
                Finite(longitude) &&
                Finite(altitudeM) &&
                latitude >= -90d && latitude <= 90d &&
                longitude >= -180d && longitude <= 180d;
            record.latitude = record.geoPoseValid ? latitude : 0d;
            record.longitude = record.geoPoseValid ? longitude : 0d;
            record.altitudeM = record.geoPoseValid ? altitudeM : 0d;
            record.updatedAtUnixMs = now;
            record.localPosition = new StoredVector3(position);
            record.localEuler = new StoredVector3(rotation.eulerAngles);
            record.localScale = new StoredVector3(new Vector3(
                Mathf.Clamp(scale.x, 0.1f, 4f),
                Mathf.Clamp(scale.y, 0.1f, 4f),
                Mathf.Clamp(scale.z, 0.1f, 4f)));
            Touch();
            Save();
            return record;
        }

        public WorldContent FindById(string id)
        {
            string clean = CleanId(id);
            if (string.IsNullOrEmpty(clean)) return null;
            return _document.contents.Find(item =>
                item != null &&
                string.Equals(item.worldContentId, clean, StringComparison.Ordinal));
        }

        public WorldContent FindByAnchor(string anchorGuid)
        {
            string clean = CleanId(anchorGuid);
            if (string.IsNullOrEmpty(clean)) return null;
            return _document.contents.Find(item =>
                item != null &&
                string.Equals(item.anchorGuid, clean, StringComparison.Ordinal));
        }

        public bool Remove(string worldContentId)
        {
            WorldContent found = FindById(worldContentId);
            if (found == null) return false;
            _document.contents.Remove(found);
            Touch();
            Save();
            return true;
        }

        public void MarkUnresolved(string anchorGuid)
        {
            WorldContent found = FindByAnchor(anchorGuid);
            if (found == null || found.state == "unresolved") return;
            found.state = "unresolved";
            found.updatedAtUnixMs = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            Touch();
            Save();
        }

        public void Save()
        {
            string json = JsonUtility.ToJson(_document, true);
            string temp = _path + ".tmp";
            File.WriteAllText(temp, json);
            try
            {
                if (File.Exists(_path))
                    File.Replace(temp, _path, null);
                else
                    File.Move(temp, _path);
            }
            catch (PlatformNotSupportedException)
            {
                File.Copy(temp, _path, true);
                File.Delete(temp);
            }
            catch (IOException)
            {
                File.Copy(temp, _path, true);
                File.Delete(temp);
            }
        }

        private MapDocument LoadDocument(string calibrationId)
        {
            MapDocument loaded = null;
            if (File.Exists(_path))
            {
                try
                {
                    loaded = JsonUtility.FromJson<MapDocument>(
                        File.ReadAllText(_path));
                }
                catch (Exception ex)
                {
                    Debug.LogWarning(
                        "[WorldMapStore] corrupt map ignored: " +
                        ex.GetType().Name);
                }
            }
            long now = DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();
            if (
                loaded == null ||
                loaded.schemaVersion != CurrentSchemaVersion ||
                string.IsNullOrWhiteSpace(loaded.worldMapId))
            {
                loaded = new MapDocument
                {
                    schemaVersion = CurrentSchemaVersion,
                    worldMapId = "worldmap-" + Guid.NewGuid().ToString("N"),
                    calibrationId = CleanId(calibrationId),
                    createdAtUnixMs = now,
                    updatedAtUnixMs = now,
                    contents = new List<WorldContent>(),
                    localOrigin = new StoredVector3(Vector3.zero),
                };
            }
            if (loaded.contents == null)
                loaded.contents = new List<WorldContent>();
            loaded.contents.RemoveAll(item =>
                item == null || string.IsNullOrWhiteSpace(item.worldContentId));
            return loaded;
        }

        private void Touch() =>
            _document.updatedAtUnixMs =
                DateTimeOffset.UtcNow.ToUnixTimeMilliseconds();

        private static string CleanTemplate(string value)
        {
            string clean = CleanId(value);
            switch (clean)
            {
                case "neon_sign":
                case "holo_billboard":
                case "vehicle_fx":
                case "poi_beacon":
                case "memory_echo":
                case "annotation":
                    return clean;
                default:
                    return "neon_sign";
            }
        }

        private static string CleanId(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return string.Empty;
            var chars = new char[Math.Min(value.Length, 160)];
            int count = 0;
            foreach (char c in value.Trim())
            {
                if (count >= chars.Length) break;
                if (char.IsLetterOrDigit(c) || c == '-' || c == '_' || c == ':' || c == '.')
                    chars[count++] = c;
            }
            return new string(chars, 0, count);
        }

        private static string CleanText(string value, int limit)
        {
            string clean = string.Join(
                " ",
                (value ?? string.Empty).Split(
                    (char[])null,
                    StringSplitOptions.RemoveEmptyEntries));
            return clean.Length <= limit ? clean : clean.Substring(0, limit);
        }

        private static float NormaliseYaw(float yaw)
        {
            if (!Finite(yaw)) return 0f;
            return Mathf.Repeat(yaw + 180f, 360f) - 180f;
        }

        private static bool Finite(float value) =>
            !float.IsNaN(value) && !float.IsInfinity(value);

        private static bool Finite(double value) =>
            !double.IsNaN(value) && !double.IsInfinity(value);
    }
}

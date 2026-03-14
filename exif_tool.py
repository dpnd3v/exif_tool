"""
EXIF Tool - OSINT Tool
Extracts and analyzes EXIF metadata from images.
Recovers device info, GPS location, timestamps, software, and more.

Dependencies:
    pip install Pillow piexif requests

Supported formats: JPEG, TIFF, PNG, HEIC (partial), WebP

Python >= 3.11 recommended.
"""

import sys
import argparse
import json
import math
import os
import struct
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from PIL import Image
    from PIL.ExifTags import TAGS, GPSTAGS
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import piexif
    HAS_PIEXIF = True
except ImportError:
    HAS_PIEXIF = False

DEVICE_TAGS = {
    "Make", "Model", "LensMake", "LensModel", "LensSpecification",
    "BodySerialNumber", "CameraOwnerName", "Software",
    "MakerNote",
}

CAPTURE_TAGS = {
    "DateTime", "DateTimeOriginal", "DateTimeDigitized",
    "SubSecTime", "SubSecTimeOriginal", "SubSecTimeDigitized",
    "ExposureTime", "FNumber", "ISOSpeedRatings", "ShutterSpeedValue",
    "ApertureValue", "BrightnessValue", "ExposureBiasValue",
    "MaxApertureValue", "MeteringMode", "LightSource", "Flash",
    "FocalLength", "FocalLengthIn35mmFilm", "ExposureProgram",
    "ExposureMode", "WhiteBalance", "SceneCaptureType",
    "DigitalZoomRatio", "Contrast", "Saturation", "Sharpness",
    "SubjectDistance", "SubjectDistanceRange",
    "SensingMethod", "FileSource", "SceneType",
}

IMAGE_TAGS = {
    "ImageWidth", "ImageLength", "BitsPerSample", "Compression",
    "PhotometricInterpretation", "Orientation", "SamplesPerPixel",
    "XResolution", "YResolution", "ResolutionUnit",
    "ColorSpace", "PixelXDimension", "PixelYDimension",
    "ExifImageWidth", "ExifImageHeight",
    "ImageDescription", "ImageUniqueID",
}

AUTHOR_TAGS = {
    "Artist", "Copyright", "XPAuthor", "XPComment",
    "XPTitle", "XPSubject", "XPKeywords",
    "UserComment", "CameraOwnerName",
}

TECHNICAL_TAGS = {
    "ExifVersion", "FlashPixVersion", "ComponentsConfiguration",
    "CompressedBitsPerPixel", "InteroperabilityIndex",
    "RelatedImageWidth", "RelatedImageLength",
    "CFAPattern", "CustomRendered", "GainControl",
    "SpectralSensitivity", "OECF", "SpatialFrequencyResponse",
    "Gamma", "PrintImageMatching",
}

def _dms_to_decimal(dms, ref: str) -> float | None:
    try:
        if isinstance(dms[0], tuple):
            deg = dms[0][0] / dms[0][1]
            mn  = dms[1][0] / dms[1][1]
            sec = dms[2][0] / dms[2][1]
        else:
            deg, mn, sec = float(dms[0]), float(dms[1]), float(dms[2])
        decimal = deg + mn / 60.0 + sec / 3600.0
        if ref in ("S", "W"):
            decimal = -decimal
        return round(decimal, 7)
    except Exception:
        return None

def parse_gps(gps_info: dict) -> dict:
    result = {}
    lat = lon = alt = None

    lat_val = gps_info.get("GPSLatitude")
    lat_ref = gps_info.get("GPSLatitudeRef", "N")
    if lat_val:
        lat = _dms_to_decimal(lat_val, lat_ref)

    lon_val = gps_info.get("GPSLongitude")
    lon_ref = gps_info.get("GPSLongitudeRef", "E")
    if lon_val:
        lon = _dms_to_decimal(lon_val, lon_ref)

    alt_val = gps_info.get("GPSAltitude")
    alt_ref = gps_info.get("GPSAltitudeRef", 0)
    if alt_val:
        try:
            if isinstance(alt_val, tuple):
                alt = round(alt_val[0] / alt_val[1], 2)
            else:
                alt = round(float(alt_val), 2)
            if alt_ref == 1:
                alt = -alt
        except Exception:
            pass

    if lat is not None:
        result["Latitudine"]  = lat
    if lon is not None:
        result["Longitudine"] = lon
    if alt is not None:
        result["Altitudine"]  = f"{alt} m"
    if lat is not None and lon is not None:
        result["Google Maps"] = f"https://maps.google.com/?q={lat},{lon}"
        result["OpenStreetMap"] = f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}&zoom=15"

    speed = gps_info.get("GPSSpeed")
    speed_ref = gps_info.get("GPSSpeedRef", "K")
    if speed:
        try:
            v = speed[0] / speed[1] if isinstance(speed, tuple) else float(speed)
            unit = {"K": "km/h", "M": "mph", "N": "knots"}.get(speed_ref, speed_ref)
            result["Velocità GPS"] = f"{v} {unit}"
        except Exception:
            pass

    direction = gps_info.get("GPSImgDirection")
    dir_ref   = gps_info.get("GPSImgDirectionRef", "T")
    if direction:
        try:
            d = direction[0] / direction[1] if isinstance(direction, tuple) else float(direction)
            result["Direzione"] = f"{d:.1f}° ({'True' if dir_ref == 'T' else 'Magnetic'})"
        except Exception:
            pass

    timestamp = gps_info.get("GPSTimeStamp")
    datestamp = gps_info.get("GPSDateStamp")
    if timestamp:
        try:
            h = timestamp[0][0] // timestamp[0][1] if isinstance(timestamp[0], tuple) else int(timestamp[0])
            m = timestamp[1][0] // timestamp[1][1] if isinstance(timestamp[1], tuple) else int(timestamp[1])
            s = timestamp[2][0] // timestamp[2][1] if isinstance(timestamp[2], tuple) else int(timestamp[2])
            ts = f"{h:02d}:{m:02d}:{s:02d} UTC"
            if datestamp:
                ts = f"{datestamp} {ts}"
            result["GPS Timestamp"] = ts
        except Exception:
            pass

    for key, val in gps_info.items():
        if key not in ("GPSLatitude","GPSLatitudeRef","GPSLongitude","GPSLongitudeRef",
                       "GPSAltitude","GPSAltitudeRef","GPSSpeed","GPSSpeedRef",
                       "GPSImgDirection","GPSImgDirectionRef","GPSTimeStamp","GPSDateStamp"):
            result[f"GPS {key}"] = str(val)

    return result

def reverse_geocode(lat: float, lon: float) -> str:
    try:
        url = (f"https://nominatim.openstreetmap.org/reverse"
               f"?lat={lat}&lon={lon}&format=json")
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "EXIFTool-OSINT/1.0")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            return data.get("display_name", "-")
    except Exception:
        return "-"

ORIENTATION_MAP = {
    1: "Normal (0°)",
    2: "Mirrored horizontal",
    3: "Rotated 180°",
    4: "Mirrored vertical",
    5: "Mirrored horizontal + rotated 90° CW",
    6: "Rotated 90° CW",
    7: "Mirrored horizontal + rotated 90° CCW",
    8: "Rotated 90° CCW",
}

EXPOSURE_PROGRAM_MAP = {
    0: "Not defined", 1: "Manual", 2: "Normal program",
    3: "Aperture priority", 4: "Shutter priority",
    5: "Creative program", 6: "Action program",
    7: "Portrait mode", 8: "Landscape mode",
}

METERING_MAP = {
    0: "Unknown", 1: "Average", 2: "Center-weighted",
    3: "Spot", 4: "Multi-spot", 5: "Pattern", 6: "Partial",
}

FLASH_MAP = {
    0x00: "No flash", 0x01: "Flash fired",
    0x05: "Flash fired, no strobe return",
    0x07: "Flash fired, strobe return",
    0x09: "Flash fired, compulsory",
    0x0D: "Flash fired, compulsory, no strobe return",
    0x0F: "Flash fired, compulsory, strobe return",
    0x10: "Flash did not fire, compulsory",
    0x18: "Flash did not fire, auto",
    0x19: "Flash fired, auto",
    0x1D: "Flash fired, auto, no strobe return",
    0x1F: "Flash fired, auto, strobe return",
    0x20: "No flash function",
    0x41: "Flash fired, red-eye reduction",
    0x45: "Flash fired, red-eye reduction, no strobe return",
    0x47: "Flash fired, red-eye reduction, strobe return",
    0x49: "Flash fired, compulsory, red-eye reduction",
    0x4F: "Flash fired, compulsory, red-eye reduction, strobe return",
    0x59: "Flash fired, auto, red-eye reduction",
    0x5F: "Flash fired, auto, red-eye reduction, strobe return",
}

WHITE_BALANCE_MAP = {0: "Auto", 1: "Manual"}
SCENE_CAPTURE_MAP = {0: "Standard", 1: "Landscape", 2: "Portrait", 3: "Night scene"}
CONTRAST_MAP      = {0: "Normal", 1: "Soft", 2: "Hard"}
SATURATION_MAP    = {0: "Normal", 1: "Low", 2: "High"}
SHARPNESS_MAP     = {0: "Normal", 1: "Soft", 2: "Hard"}
EXPOSURE_MODE_MAP = {0: "Auto", 1: "Manual", 2: "Auto bracket"}
LIGHT_SOURCE_MAP  = {
    0: "Unknown", 1: "Daylight", 2: "Fluorescent", 3: "Tungsten",
    4: "Flash", 9: "Fine weather", 10: "Cloudy", 11: "Shade",
    12: "Daylight fluorescent", 13: "Day white fluorescent",
    14: "Cool white fluorescent", 15: "White fluorescent",
    17: "Standard A", 18: "Standard B", 19: "Standard C",
    20: "D55", 21: "D65", 22: "D75", 23: "D50",
    24: "ISO studio tungsten", 255: "Other",
}

def fmt_value(tag: str, value) -> str:
    if tag == "Orientation":
        return ORIENTATION_MAP.get(value, str(value))
    if tag == "ExposureProgram":
        return EXPOSURE_PROGRAM_MAP.get(value, str(value))
    if tag == "MeteringMode":
        return METERING_MAP.get(value, str(value))
    if tag == "Flash":
        return FLASH_MAP.get(value, str(value))
    if tag == "WhiteBalance":
        return WHITE_BALANCE_MAP.get(value, str(value))
    if tag == "SceneCaptureType":
        return SCENE_CAPTURE_MAP.get(value, str(value))
    if tag == "Contrast":
        return CONTRAST_MAP.get(value, str(value))
    if tag == "Saturation":
        return SATURATION_MAP.get(value, str(value))
    if tag == "Sharpness":
        return SHARPNESS_MAP.get(value, str(value))
    if tag == "ExposureMode":
        return EXPOSURE_MODE_MAP.get(value, str(value))
    if tag == "LightSource":
        return LIGHT_SOURCE_MAP.get(value, str(value))
    if tag == "ExposureTime":
        try:
            if isinstance(value, tuple):
                n, d = value
                if n == 0: return "0"
                if d / n >= 1:
                    return f"1/{int(d/n)} s"
                return f"{n/d:.4f} s"
            return f"{float(value):.4f} s"
        except Exception:
            pass
    if tag == "FNumber":
        try:
            if isinstance(value, tuple):
                return f"f/{value[0]/value[1]:.1f}"
            return f"f/{float(value):.1f}"
        except Exception:
            pass
    if tag == "FocalLength":
        try:
            if isinstance(value, tuple):
                return f"{value[0]/value[1]:.1f} mm"
            return f"{float(value):.1f} mm"
        except Exception:
            pass
    if tag in ("XResolution", "YResolution"):
        try:
            if isinstance(value, tuple):
                return f"{int(value[0]/value[1])} dpi"
            return f"{int(value)} dpi"
        except Exception:
            pass
    if tag == "ResolutionUnit":
        return {1: "No absolute unit", 2: "inch", 3: "centimeter"}.get(value, str(value))
    if tag == "ColorSpace":
        return {1: "sRGB", 65535: "Uncalibrated"}.get(value, str(value))
    if tag == "Compression":
        return {1: "Uncompressed", 6: "JPEG", 34892: "Lossy JPEG"}.get(value, str(value))
    if isinstance(value, bytes):
        try:
            decoded = value.decode("utf-8").strip("\x00").strip()
            if decoded and decoded.isprintable():
                return decoded
        except Exception:
            pass
        return f"<binary {len(value)} bytes>"
    if isinstance(value, tuple) and len(value) == 2:
        try:
            return f"{value[0]/value[1]:.4f}".rstrip("0").rstrip(".")
        except Exception:
            pass
    return str(value)

def extract_exif(path: Path) -> dict:
    if not HAS_PIL:
        print("[!] Pillow not installed. Run: pip install Pillow piexif requests")
        sys.exit(1)

    result = {
        "file":      {},
        "device":    {},
        "capture":   {},
        "image":     {},
        "gps":       {},
        "location":  {},
        "author":    {},
        "technical": {},
        "raw":       {},
    }

    stat = path.stat()
    result["file"] = {
        "Filename":  path.name,
        "Path":      str(path.resolve()),
        "Size":      f"{stat.st_size:,} bytes ({stat.st_size / 1024:.1f} KB)",
        "Modified":  datetime.fromtimestamp(stat.st_mtime).strftime("%Y:%m:%d %H:%M:%S"),
        "Extension": path.suffix.upper(),
    }

    try:
        img = Image.open(path)
    except Exception as e:
        print(f"[!] Cannot open image: {e}")
        sys.exit(1)

    result["image"]["Format"]  = img.format or path.suffix.upper().lstrip(".")
    result["image"]["Mode"]    = img.mode
    result["image"]["Width"]   = f"{img.width} px"
    result["image"]["Height"]  = f"{img.height} px"
    result["image"]["Megapixels"] = f"{img.width * img.height / 1_000_000:.2f} MP"

    raw_exif = img._getexif() if hasattr(img, "_getexif") else None
    if raw_exif is None:
        try:
            info = img.info or {}
            raw_exif = info.get("exif")
            if raw_exif and isinstance(raw_exif, bytes) and HAS_PIEXIF:
                raw_exif = piexif.load(raw_exif)
                flat = {}
                for ifd in ("0th", "Exif", "GPS", "1st"):
                    for tag, val in raw_exif.get(ifd, {}).items():
                        name = TAGS.get(tag, str(tag))
                        flat[name] = val
                raw_exif = flat
        except Exception:
            raw_exif = None

    if raw_exif is None:
        result["raw"]["note"] = "No EXIF data found in this image."
        return result

    gps_data = {}

    for tag_id, value in raw_exif.items():
        tag = TAGS.get(tag_id, str(tag_id)) if isinstance(tag_id, int) else str(tag_id)

        if tag == "GPSInfo" and isinstance(value, dict):
            for gps_tag_id, gps_val in value.items():
                gps_name = GPSTAGS.get(gps_tag_id, str(gps_tag_id))
                gps_data[gps_name] = gps_val
            continue

        if tag in ("MakerNote", "PrintImageMatching", "JPEGThumbnail"):
            continue

        formatted = fmt_value(tag, value)

        if tag in DEVICE_TAGS:
            result["device"][tag] = formatted
        elif tag in CAPTURE_TAGS:
            result["capture"][tag] = formatted
        elif tag in IMAGE_TAGS:
            result["image"][tag] = formatted
        elif tag in AUTHOR_TAGS:
            result["author"][tag] = formatted
        elif tag in TECHNICAL_TAGS:
            result["technical"][tag] = formatted
        else:
            result["raw"][tag] = formatted

    if gps_data:
        result["gps"] = parse_gps(gps_data)
        lat = result["gps"].get("Latitudine")
        lon = result["gps"].get("Longitudine")
        if lat is not None and lon is not None:
            print("[*] GPS coordinates found — reverse geocoding ...")
            address = reverse_geocode(lat, lon)
            if address != "-":
                result["location"]["Indirizzo"] = address

    return result

SECTION_LABELS = {
    "file":      "FILE INFO",
    "device":    "DISPOSITIVO",
    "capture":   "SCATTO",
    "image":     "IMMAGINE",
    "gps":       "GPS",
    "location":  "POSIZIONE",
    "author":    "AUTORE / COPYRIGHT",
    "technical": "TECNICO",
    "raw":       "ALTRI DATI",
}

def print_section(title: str, data: dict, pad: int = 30):
    if not data:
        return
    print(f"\n  {'─' * 50}")
    print(f"  {title}")
    print(f"  {'─' * 50}")
    for key, val in data.items():
        print(f"  {key:<{pad}} {val}")

def print_results(data: dict, path: Path):
    print(f"\n{'═' * 60}")
    print(f"  EXIF ANALYSIS  —  {path.name}")
    print(f"{'═' * 60}")

    for section, label in SECTION_LABELS.items():
        print_section(label, data.get(section, {}))

    print(f"\n{'═' * 60}\n")

def save_results(data: dict, output_file: Path):
    lines = []
    for section, label in SECTION_LABELS.items():
        d = data.get(section, {})
        if not d:
            continue
        lines.append(f"\n{'─' * 50}")
        lines.append(f"{label}")
        lines.append(f"{'─' * 50}")
        for key, val in d.items():
            lines.append(f"{key:<30} {val}")
    output_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"[*] Saved : {output_file}")

def main() -> None:
    parser = argparse.ArgumentParser(
        description="EXIF Tool — OSINT Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Extracts:
  Device     Make, model, lens, serial number, software
  Capture    Date/time, shutter, aperture, ISO, flash, focal length
  Image      Resolution, dimensions, color space, orientation
  GPS        Coordinates, altitude, speed, direction + Maps links
  Location   Reverse geocoded address (OpenStreetMap)
  Author     Artist, copyright, XP tags, user comment
  Technical  EXIF version, color components, interoperability

Examples:
  python exif_tool.py photo.jpg
  python exif_tool.py photo.jpg -o report.txt
  python exif_tool.py photo.jpg --no-geo
  python exif_tool.py *.jpg
        """,
    )
    parser.add_argument("images", nargs="+",
        help="Image file(s) to analyze (JPEG, TIFF, PNG, WebP)")
    parser.add_argument("-o", "--output", default=None,
        help="Save results to text file")
    parser.add_argument("--no-geo", action="store_true",
        help="Skip reverse geocoding (faster, no network request)")
    parser.add_argument("--json", action="store_true",
        help="Output raw JSON instead of formatted text")

    args = parser.parse_args()

    if not HAS_PIL:
        print("[!] Pillow not installed.")
        print("[!] Run: pip install Pillow piexif")
        sys.exit(1)

    for img_path_str in args.images:
        path = Path(img_path_str)
        if not path.is_file():
            print(f"[!] File not found: {path}")
            continue

        print(f"[*] Analyzing: {path}")
        data = extract_exif(path)

        if args.no_geo:
            data.pop("location", None)

        if args.json:
            print(json.dumps(data, indent=2, default=str))
        else:
            print_results(data, path)
            if args.output:
                out = Path(args.output)
                if len(args.images) > 1:
                    out = out.with_stem(f"{out.stem}_{path.stem}")
                save_results(data, out)

if __name__ == "__main__":
    main()

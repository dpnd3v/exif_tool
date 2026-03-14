# EXIF Tool

EXIF metadata extractor for OSINT. Recovers device info, GPS coordinates,
capture settings, author data and more from image files.

## Requirements

```
pip install Pillow piexif
```

## Usage

```bash
python exif_tool.py photo.jpg
python exif_tool.py photo.jpg -o report.txt
python exif_tool.py photo.jpg --no-geo
python exif_tool.py *.jpg
python exif_tool.py photo.jpg --json
```

## Options

| Flag | Description |
|---|---|
| `-o` | Save output to text file |
| `--no-geo` | Skip reverse geocoding (no network request) |
| `--json` | Output raw JSON |

## Output sections

| Section | Content |
|---|---|
| FILE INFO | Filename, path, size, modification date |
| DISPOSITIVO | Make, model, lens, serial number, software |
| SCATTO | Date/time, shutter, aperture, ISO, flash, focal length, exposure mode |
| IMMAGINE | Dimensions, megapixels, resolution, color space, orientation |
| GPS | Coordinates, altitude, speed, direction + Google Maps / OpenStreetMap links |
| POSIZIONE | Reverse geocoded address via OpenStreetMap (no API key required) |
| AUTORE | Artist, copyright, user comment, XP tags |
| TECNICO | EXIF version, color components, interoperability |

## Note

Most social platforms (WhatsApp, Instagram, Facebook, Twitter, Pinterest)
strip EXIF before delivery. Use original files from the device's camera roll,
or platforms that preserve metadata: Flickr, 500px, Glass.photo, VSCO,
direct image URLs from personal blogs, email attachments.

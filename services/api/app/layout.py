"""Scene-aware layout analysis. Uncertain geometry always preserves the source."""

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import cv2
import numpy as np

LAYOUT_VERSION = 5


def camera_tiles(frame, faces) -> list[list[int]]:
    """Require rectangular camera boundaries and distinct simultaneous faces."""
    height, width = frame.shape[:2]
    if len(faces) < 2:
        return []
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 40, 100)
    edges = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, perimeter * 0.025, True)
        if len(polygon) != 4 or not cv2.isContourConvex(polygon):
            continue
        boxes.append(cv2.boundingRect(polygon))
    # Camera tiles often have interrupted borders (microphones, low contrast).
    # Match long horizontal edges and verify both vertical sides as well.
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, 35,
                            minLineLength=width * 0.22, maxLineGap=8)
    horizontals = []
    if lines is not None:
        horizontals = [tuple(line[0]) for line in lines
                       if abs(int(line[0][1]) - int(line[0][3])) <= 2]
    for x1, y1, x2, _ in horizontals:
        expected_height = round((x2 - x1) * 9 / 16)
        if x2 - x1 >= width * 0.3:
            for top in (y1, y1 - expected_height):
                bottom = top + expected_height
                if top < 0 or bottom >= height:
                    continue
                if all(np.mean(np.any(edges[top:bottom, max(0, x - 3):min(width, x + 4)],
                                      axis=1)) >= 0.5 for x in (x1, x2)):
                    boxes.append((x1, top, x2 - x1, expected_height))
        for bx1, by1, bx2, _ in horizontals:
            if by1 - y1 < height * 0.24 or abs(x1 - bx1) > 8 or abs(x2 - bx2) > 8:
                continue
            left, right = min(x1, bx1), max(x2, bx2)
            supported = all(
                np.mean(np.any(edges[y1:by1, max(0, x - 3):min(width, x + 4)], axis=1))
                >= 0.65 for x in (left, right)
            )
            if supported:
                boxes.append((left, y1, right - left, by1 - y1))
    candidates = []
    for x, y, w, h in boxes:
        if w < width * 0.24 or h < height * 0.24 or not 1.15 < w / h < 2.5:
            continue
        if w * h > width * height * 0.65:
            continue
        enclosed = [index for index, (fx, fy, fw, fh) in enumerate(faces)
                    if x <= fx and y <= fy and fx + fw <= x + w and fy + fh <= y + h]
        if len(enclosed) == 1:
            candidates.append((w * h, [x, y, w, h], enclosed[0]))
    tiles: list[list[int]] = []
    used_faces: set[int] = set()
    for _, tile, face_index in sorted(candidates, reverse=True):
        if face_index in used_faces:
            continue
        x, y, w, h = tile
        overlaps = any(
            max(0, min(x + w, tx + tw) - max(x, tx))
            * max(0, min(y + h, ty + th) - max(y, ty)) > min(w * h, tw * th) * 0.1
            for tx, ty, tw, th in tiles
        )
        if not overlaps:
            tiles.append(tile)
            used_faces.add(face_index)
    return [[int(value) for value in tile] for tile in
            sorted(tiles, key=lambda tile: (tile[1], tile[0]))] if len(tiles) >= 2 else []


def classify_layout(frame, faces) -> dict:
    height, width = frame.shape[:2]
    tiles = camera_tiles(frame, faces)
    if tiles:
        return {"kind": "camera_grid", "confidence": 0.9, "tiles": tiles,
                "people": len(tiles), "composition": "duo"}
    if len(faces) >= 2:
        return {"kind": "shared_camera", "confidence": 0.75, "tiles": [],
                "people": len(faces), "composition": "source"}
    if len(faces) == 1:
        _, _, fw, fh = faces[0]
        if fw * fh / (width * height) >= 0.018:
            return {"kind": "single_speaker", "confidence": 0.8, "tiles": [],
                    "people": 1, "composition": "single"}
        return {"kind": "presentation", "confidence": 0.5, "tiles": [],
                "people": 1, "composition": "source"}
    return {"kind": "scene_or_graphics", "confidence": 0.4, "tiles": [],
            "people": 0, "composition": "source"}


def _scene_changed(before, after) -> bool:
    # Pixel difference catches camera edits; histogram distance distinguishes
    # those edits from normal hand/head movement within one composition.
    first = cv2.cvtColor(before, cv2.COLOR_BGR2GRAY)
    second = cv2.cvtColor(after, cv2.COLOR_BGR2GRAY)
    difference = float(np.mean(cv2.absdiff(first, second)))
    histograms = [cv2.calcHist([image], [0], None, [32], [0, 256])
                  for image in (first, second)]
    for histogram in histograms:
        cv2.normalize(histogram, histogram)
    correlation = cv2.compareHist(*histograms, cv2.HISTCMP_CORREL)
    return difference > 38 or (difference > 19 and correlation < 0.7)


def _same_tiles(first, second) -> bool:
    if len(first) != len(second):
        return False
    return all(abs(a - b) <= 10 for left, right in zip(first, second, strict=True)
               for a, b in zip(left, right, strict=True))


def _summarize_scene(samples: list[dict], start: float, end: float) -> dict:
    # Never carry a face/camera position from one shot into a different shot.
    grids = [sample for sample in samples if sample["kind"] == "camera_grid"]
    tile_evidence: list[list[list[int]]] = []
    for sample in grids:
        for tile in sample["tiles"]:
            match = next((group for group in tile_evidence
                          if _same_tiles([group[0]], [tile])), None)
            if match is None:
                tile_evidence.append([tile])
            else:
                match.append(tile)
    stable_tiles = [group[0] for group in tile_evidence if len(group) >= max(2, len(grids) * 0.25)]
    disjoint = all(
        max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
        * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
        < min(a[2] * a[3], b[2] * b[3]) * 0.1
        for index, a in enumerate(stable_tiles) for b in stable_tiles[index + 1:]
    )
    stable_grid = bool(
        len(grids) >= 2 and len(grids) / len(samples) >= 0.75
        and len(stable_tiles) >= 2 and disjoint
    )
    if stable_grid:
        chosen = {**grids[0], "tiles": stable_tiles, "people": len(stable_tiles)}
    elif all(sample["kind"] == "single_speaker" for sample in samples):
        chosen = samples[0]
    else:
        chosen = {"kind": "mixed_or_uncertain", "confidence": 0.4,
                  "composition": "source", "tiles": [],
                  "people": max(sample["people"] for sample in samples)}
        if all(sample["kind"] == samples[0]["kind"] for sample in samples):
            chosen = {**samples[0], "composition": "source", "tiles": []}
    return {**chosen, "start": round(start, 3), "end": round(end, 3)}


def analyze_layout(source: Path, start: float, end: float) -> dict:
    """Cache a layout map before composition; timestamps are relative to this cut."""
    stat = source.stat()
    fingerprint = hashlib.sha256(
        f"{LAYOUT_VERSION}:{stat.st_size}:{stat.st_mtime_ns}:{start:.3f}:{end:.3f}".encode()
    ).hexdigest()[:24]
    cache = source.parent / "layout-cache" / f"{fingerprint}.json"
    if cache.exists():
        try:
            cached = json.loads(cache.read_text(encoding="utf-8"))
            if cached.get("version") == LAYOUT_VERSION:
                return cached
        except (ValueError, OSError):
            pass
    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        capture.release()
        raise ValueError("Source video cannot be analyzed")
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cascade = cv2.CascadeClassifier(
        cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
    )
    duration = end - start
    if duration <= 0 or width <= 0 or height <= 0:
        capture.release()
        raise ValueError("Invalid source geometry or clip duration")
    scale = min(1, 640 / width)
    scenes: list[dict] = []
    samples: list[dict] = []
    previous = None
    scene_start = 0.0
    offset = 0.0
    try:
        while offset < duration:
            capture.set(cv2.CAP_PROP_POS_MSEC, (start + offset) * 1000)
            ok, frame = capture.read()
            if not ok:
                break
            small = cv2.resize(frame, (round(width * scale), round(height * scale)))
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            faces = cascade.detectMultiScale(gray, 1.1, 5, minSize=(22, 22))
            classified = classify_layout(small, list(faces))
            changed = previous is not None and _scene_changed(previous, small)
            if changed and samples:
                # Refine the cut inside the sampling window instead of keeping
                # the previous composition for up to half a second after it.
                low, high = max(scene_start, offset - 0.5), offset
                for _ in range(4):
                    middle = (low + high) / 2
                    capture.set(cv2.CAP_PROP_POS_MSEC, (start + middle) * 1000)
                    middle_ok, middle_frame = capture.read()
                    if not middle_ok:
                        break
                    middle_small = cv2.resize(middle_frame, (small.shape[1], small.shape[0]))
                    if _scene_changed(previous, middle_small):
                        high = middle
                    else:
                        low = middle
                scenes.append(_summarize_scene(samples, scene_start, high))
                scene_start = high
                samples = []
            samples.append(classified)
            previous = small
            offset += 0.5
    finally:
        capture.release()
    if samples:
        scenes.append(_summarize_scene(samples, scene_start, duration))
    if not scenes:
        scenes = [{"start": 0.0, "end": duration, "kind": "unavailable",
                   "composition": "source", "confidence": 0, "tiles": [], "people": 0}]
    if len(scenes) >= 3 and duration / len(scenes) < 5:
        for scene in scenes:
            if scene["composition"] != "duo":
                scene.update(kind="edited_sequence", composition="source", confidence=0.6)
    for scene in scenes:
        scene["tiles"] = [[round(value / scale) for value in tile]
                          for tile in scene["tiles"]]
    report = {"version": LAYOUT_VERSION, "width": width, "height": height,
              "scenes": scenes, "source_start": start, "source_end": end,
              "note": "Layout and scene detection use visual evidence. Uncertain shots preserve "
                      "the complete source; camera grids require simultaneous visible people."}
    cache.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache.with_suffix(f".{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(report), encoding="utf-8")
    temporary.replace(cache)
    return report

import os
import sys
import re
import cv2
import json
import logging
import warnings
import argparse
import numpy as np

# PaddleOCR deprecation aur verbose logs suppress karein
os.environ["GLOG_minloglevel"] = "3"
warnings.filterwarnings("ignore", category=DeprecationWarning)
logging.getLogger("ppocr").setLevel(logging.ERROR)

from paddleocr import PaddleOCR

INDIAN_STATES = (
    "AN", "AP", "AR", "AS", "BR", "CH", "CG", "DD", "DL", "DN",
    "GA", "GJ", "HR", "HP", "JH", "JK", "KA", "KL", "LA", "LD",
    "MH", "ML", "MN", "MP", "MZ", "NL", "OD", "PB", "PY", "RJ",
    "SK", "TN", "TR", "TS", "UK", "UP", "WB", "BH"
)

DIGIT_TO_ALPHA = {'0': 'D', '1': 'I', '2': 'Z', '8': 'B', '5': 'S'}
ALPHA_TO_DIGIT = {'O': '0', 'I': '1', 'Z': '2', 'B': '8', 'S': '5', 'D': '0'}


class DynamicANPR:
    def __init__(self):
        print("[INFO] Initializing Dynamic OCR Engine...")
        self.ocr = PaddleOCR(use_angle_cls=True, lang='en')

    def _extract_results(self, ocr_result):
        items = []
        if not ocr_result:
            return items

        root = ocr_result
        if isinstance(root, list) and len(root) > 0 and isinstance(root[0], list):
            if len(root[0]) > 0 and isinstance(root[0][0], list):
                root = root[0]

        for item in root:
            if isinstance(item, list) and len(item) == 2:
                box, txt_meta = item[0], item[1]
                pts = np.array(box, dtype=np.int32)
                min_x = int(np.min(pts[:, 0]))
                min_y = int(np.min(pts[:, 1]))
                text = txt_meta[0] if isinstance(txt_meta, (tuple, list)) else str(txt_meta)
                items.append((min_y, min_x, text))
            elif isinstance(item, dict):
                texts = item.get('rec_texts', item.get('text', []))
                polys = item.get('dt_polys', item.get('boxes', []))
                if isinstance(texts, list):
                    for idx, t in enumerate(texts):
                        y_val, x_val = 0, 0
                        if isinstance(polys, list) and idx < len(polys):
                            pts = np.array(polys[idx])
                            if pts.ndim == 2:
                                x_val = int(np.min(pts[:, 0]))
                                y_val = int(np.min(pts[:, 1]))
                        items.append((y_val, x_val, str(t)))
        return items

    def _clean_token(self, text):
        clean = re.sub(r'[^A-Z0-9]', '', str(text).upper())
        clean = re.sub(r'^(IND|1ND|LND|INO|LNO|100)', '', clean)
        clean = re.sub(r'(IND|1ND|LND|INO|LNO|100)$', '', clean)
        return clean

    def _normalize_plate(self, s):
        if not s or len(s) < 6:
            return None

        s = re.sub(r'[^A-Z0-9]', '', str(s).upper())

        # Duplicate concatenation filter
        half = len(s) // 2
        if half >= 6 and s[:half] == s[half:]:
            s = s[:half]

        # Fix ghost '1' / 'I' created by blue IND strip / hologram (e.g. UP116 -> UP16)
        for st in INDIAN_STATES:
            if s.startswith(st):
                rem = s[len(st):]
                m_ghost = re.match(r'^(1)([0-9]{2})([A-Z0-9]+)', rem)
                if m_ghost:
                    s = st + m_ghost.group(2) + m_ghost.group(3)
                break

        # 1. Standard Indian Plates: SS NN [A-Z]{0,3} NNNN
        # Non-greedy series capture ensures 4-digit tail is never swallowed
        for match in re.finditer(r'([A-Z]{2})([0-9]{1,2})([A-Z0-9]{0,3}?)(\d{4})(?![0-9])', s):
            st, rto, ser, num = match.groups()
            if st in INDIAN_STATES:
                ser_fixed = "".join(DIGIT_TO_ALPHA.get(ch, ch) for ch in ser)
                rto_fixed = "".join(ALPHA_TO_DIGIT.get(ch, ch) for ch in rto)
                num_fixed = "".join(ALPHA_TO_DIGIT.get(ch, ch) for ch in num)
                return f"{st} {rto_fixed} {ser_fixed} {num_fixed}".replace("  ", " ").strip()

        # 2. Commercial / 3-Wheeler Auto Plates (e.g. MP 91 P A026X)
        m_auto = re.search(r'([A-Z]{2})([0-9]{1,2})([A-Z])([A-Z0-9]{4,5})', s)
        if m_auto:
            st, rto, p_code, serial = m_auto.groups()
            if st in INDIAN_STATES:
                rto_fixed = "".join(ALPHA_TO_DIGIT.get(ch, ch) for ch in rto)
                return f"{st} {rto_fixed} {p_code} {serial}"

        # 3. BH-Series: YY BH NNNN AA
        bh = re.search(r'([0-9]{2})(BH)([0-9]{4})([A-Z]{1,2})', s)
        if bh:
            yr, code, num, ser = bh.groups()
            return f"{yr} {code} {num} {ser}"

        return None

    def _get_candidate_crops(self, img):
        h, w = img.shape[:2]
        return [
            # 1. Full Image
            img,
            # 2. Lower Bumper (Front / Rear)
            img[int(h * 0.40):int(h * 0.95), int(w * 0.05):int(w * 0.95)],
            # 3. Off-center / Left-heavy crops (Tilted cars & Auto rickshaw front plate)
            img[int(h * 0.45):int(h * 0.85), int(w * 0.10):int(w * 0.50)],
            # 4. Right-heavy crops (Auto rickshaw rear plate)
            img[int(h * 0.50):int(h * 0.85), int(w * 0.60):int(w * 0.98)]
        ]

    def recognize(self, image_source):
        if isinstance(image_source, str):
            if not os.path.exists(image_source):
                return {"file": image_source, "plate": "File Not Found", "status": False}
            img = cv2.imread(image_source)
            filename = os.path.basename(image_source)
        else:
            img = image_source
            filename = "frame_memory"

        if img is None:
            return {"file": filename, "plate": "Image Read Error", "status": False}

        for region in self._get_candidate_crops(img):
            rh, rw = region.shape[:2]
            if rh < 30 or rw < 30:
                continue

            if rh < 350:
                scale = max(2.0, 350.0 / rh)
                region = cv2.resize(region, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

            # High-pass contrast enhancement (CLAHE)
            gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8))
            enhanced = cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR)

            for feed in [region, enhanced]:
                try:
                    results = self.ocr.ocr(feed, cls=True)
                except Exception:
                    results = getattr(self.ocr, 'predict', self.ocr.ocr)(feed)

                raw_boxes = self._extract_results(results)
                if not raw_boxes:
                    continue

                # Multi-line clustering: group boxes vertically within 40px
                raw_boxes.sort(key=lambda item: (item[0] // 40, item[1]))

                tokens = [self._clean_token(t[2]) for t in raw_boxes]
                tokens = [t for t in tokens if len(t) >= 2]

                # 1. Full merged string check
                merged = "".join(tokens)
                plate = self._normalize_plate(merged)
                if plate:
                    return {"file": filename, "plate": plate, "status": True}

                # 2. Individual tokens check
                for t in tokens:
                    plate = self._normalize_plate(t)
                    if plate:
                        return {"file": filename, "plate": plate, "status": True}

        return {"file": filename, "plate": "Not Detected", "status": False}

    def process_folder(self, folder_path=".", extensions=(".jpg", ".jpeg", ".png", ".webp")):
        files = [
            os.path.join(folder_path, f) for f in os.listdir(folder_path)
            if f.lower().endswith(extensions) and not f.startswith(("crop", "debug", "yolo"))
        ]

        results = []
        print("\n" + "=" * 60)
        print("           DYNAMIC PLATE RECOGNITION REPORT")
        print("=" * 60)

        for filepath in sorted(files):
            res = self.recognize(filepath)
            results.append(res)
            mark = "✔" if res["status"] else "✖"
            print(f"[{mark}] {res['file']:<30} -> {res['plate']}")

        print("=" * 60 + "\n")
        return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Dynamic Multi-Plate ANPR Engine")
    parser.add_argument("-i", "--image", type=str, help="Single image file path")
    parser.add_argument("-d", "--dir", type=str, default=".", help="Directory path")
    parser.add_argument("-o", "--output", type=str, help="Save output to JSON file")
    args = parser.parse_args()

    engine = DynamicANPR()

    if args.image:
        result = engine.recognize(args.image)
        print(json.dumps(result, indent=2))
        final_data = [result]
    else:
        final_data = engine.process_folder(args.dir)

    if args.output:
        with open(args.output, "w") as f:
            json.dump(final_data, f, indent=4)
        print(f"[INFO] Results saved to '{args.output}'")
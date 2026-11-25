from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE, MSO_CONNECTOR
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.util import Inches, Pt

OUT = "DRISHTI_DRIVE_PROJECT_WORKFLOW.pptx"
prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

BLACK = RGBColor(0, 0, 0)
PANEL = RGBColor(12, 12, 12)
WHITE = RGBColor(255, 255, 255)
YELLOW = RGBColor(255, 242, 0)
GOLD = RGBColor(255, 204, 0)
AMBER = RGBColor(255, 166, 0)
ORANGE = RGBColor(255, 128, 0)
MUTED = RGBColor(190, 190, 190)
BLUE = RGBColor(33, 150, 243)
RED = RGBColor(244, 67, 54)
GREEN = RGBColor(16, 185, 129)


def add_bg(slide, number=None):
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = BLACK
    band = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(.12))
    band.fill.solid(); band.fill.fore_color.rgb = ORANGE; band.line.fill.background()
    if number is not None:
        add_text(slide, f"DRISHTI DRIVE  /  {number:02d}", 11.35, .22, 1.65, .25, 9, MUTED, bold=True, align=PP_ALIGN.RIGHT)


def add_text(slide, text, x, y, w, h, size=16, color=WHITE, bold=False, align=PP_ALIGN.LEFT, font="Aptos", valign=MSO_ANCHOR.TOP):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True; tf.vertical_anchor = valign
    p = tf.paragraphs[0]; p.alignment = align
    run = p.add_run(); run.text = text; run.font.name = font; run.font.size = Pt(size); run.font.bold = bold; run.font.color.rgb = color
    return box


def title(slide, heading, sub=None):
    add_text(slide, heading, .65, .45, 9.8, .55, 27, YELLOW, bold=True, font="Aptos Display")
    if sub: add_text(slide, sub, .68, 1.05, 11.8, .38, 11, MUTED)


def card(slide, text, x, y, w, h, fill=PANEL, line=GOLD, color=WHITE, size=14, bold=False):
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    shape.fill.solid(); shape.fill.fore_color.rgb = fill; shape.line.color.rgb = line; shape.line.width = Pt(1.2)
    add_text(slide, text, x+.12, y+.08, w-.24, h-.16, size, color, bold, PP_ALIGN.CENTER, valign=MSO_ANCHOR.MIDDLE)
    return shape


def arrow(slide, x1, y1, x2, y2, color=AMBER):
    line = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    line.line.color.rgb = color; line.line.width = Pt(2.2); line.line.end_arrowhead = True


def bullet_list(slide, items, x, y, w, h, size=14, color=WHITE, accent=GOLD):
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame; tf.clear(); tf.word_wrap = True
    for index, item in enumerate(items):
        p = tf.paragraphs[0] if index == 0 else tf.add_paragraph()
        p.text = f"• {item}"; p.font.name = "Aptos"; p.font.size = Pt(size); p.font.color.rgb = color; p.space_after = Pt(8)
    return box

# 1 Title
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide)
add_text(slide, "DRISHTI", .75, 1.05, 5.2, .85, 48, WHITE, True, font="Aptos Display")
add_text(slide, "DRIVE", 5.0, 1.05, 4.4, .85, 48, YELLOW, True, font="Aptos Display")
add_text(slide, "Vehicle Surveillance Project", .82, 2.05, 7.5, .55, 26, ORANGE, True)
add_text(slide, "End-to-end workflow of the Home, ANPR, Tracking/OCR, and Traffic pages", .85, 2.75, 8.5, .42, 16, WHITE)
card(slide, "FASTAPI  •  YOLO  •  PADDLEOCR  •  LEAFLET", .85, 4.55, 5.7, .58, fill=BLACK, line=AMBER, color=GOLD, size=14, bold=True)
add_text(slide, "Presentation generated from the active project structure", .85, 6.65, 6.5, .3, 10, MUTED)

# 2 architecture
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 2); title(slide, "System Architecture", "One integrated FastAPI entrypoint mounts the three operational pages")
card(slide, "Browser", .6, 2.55, 1.45, .65, fill=PANEL, line=WHITE, size=16, bold=True)
card(slide, "menu/app.py\nFastAPI", 2.75, 2.35, 2.25, 1.05, fill=PANEL, line=GOLD, color=YELLOW, size=16, bold=True)
arrow(slide, 2.1, 2.88, 2.72, 2.88)
for i, (label, x, color) in enumerate([("Home\n/", 6.0, WHITE), ("ANPR\n/anpr", 8.05, ORANGE), ("Tracking/OCR\n/tracking", 10.1, YELLOW)]):
    card(slide, label, x, 1.72 + (i % 2) * 1.55, 1.75, 1.0, fill=PANEL, line=color, color=color, size=14, bold=True)
    arrow(slide, 5.05, 2.88, x-.08, 2.22 if i == 0 else 3.77)
card(slide, "Traffic\n/traffic", 6.0, 5.25, 1.75, .85, fill=PANEL, line=RED, color=RED, size=14, bold=True)
arrow(slide, 5.05, 2.88, 6.0, 5.67)
add_text(slide, "Mounted sub-applications", 8.15, 5.55, 3.7, .3, 12, MUTED)

# 3 Home
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 3); title(slide, "Page 1  /  Home Menu", "Entry point and navigation surface")
card(slide, "GET /", .65, 2.45, 1.55, .7, line=WHITE, color=WHITE, bold=True)
arrow(slide, 2.2, 2.8, 3.05, 2.8)
card(slide, "menu/app.py\nserve_menu()", 3.1, 2.25, 2.2, 1.05, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 5.3, 2.8, 6.1, 2.8)
card(slide, "menu_frontend\nindex.html", 6.15, 2.25, 2.1, 1.05, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 8.3, 2.8, 9.1, 2.8)
card(slide, "ANPR", 9.2, 1.5, 1.15, .55, line=ORANGE, color=ORANGE, bold=True)
card(slide, "Tracking/OCR", 9.2, 2.45, 1.65, .55, line=YELLOW, color=YELLOW, bold=True)
card(slide, "Traffic", 9.2, 3.4, 1.15, .55, line=RED, color=RED, bold=True)
add_text(slide, "Assets: /assets  •  /navbar", .8, 5.25, 4.5, .35, 14, WHITE)
add_text(slide, "Purpose: route users into the three operational tools.", .8, 5.75, 6.4, .35, 14, MUTED)

# 4 ANPR
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 4); title(slide, "Page 2  /  ANPR Live Surveillance", "Video feeds, detection activity, and owner compliance")
card(slide, "Video footage\nvideo1..video4.mp4", .55, 2.55, 1.95, .9, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 2.5, 3.0, 3.25, 3.0)
card(slide, "YOLO\nobject detection", 3.3, 2.55, 1.75, .9, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 5.05, 3.0, 5.85, 3.0)
card(slide, "latest-detection\nAPI", 5.9, 2.55, 1.7, .9, line=WHITE, color=WHITE, bold=True)
arrow(slide, 7.6, 3.0, 8.55, 3.0)
card(slide, "ANPR UI\nactivity + profile", 8.6, 2.55, 2.0, .9, line=ORANGE, color=ORANGE, bold=True)
card(slide, "vehicle_data.csv\nowner registry", 4.1, 4.8, 2.0, .85, line=GOLD, color=WHITE, bold=True)
arrow(slide, 6.75, 3.9, 5.95, 4.8)
add_text(slide, "Refresh: every 3 seconds", 8.7, 4.95, 3.2, .35, 14, YELLOW, True)
add_text(slide, "Camera locations: Vishesh Tyagi Chowk • Maharishi Ashram Chowk • Bhangel • Metro Sec 76", .75, 6.25, 11.5, .35, 12, WHITE, False, PP_ALIGN.CENTER)

# 5 tracking
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 5); title(slide, "Page 3  /  Tracking + OCR", "Search a plate, validate it against camera sightings, and draw its route")
card(slide, "Manual plate\nor image upload", .55, 2.55, 1.75, .9, line=WHITE, color=WHITE, bold=True)
arrow(slide, 2.3, 3.0, 3.05, 3.0)
card(slide, "PaddleOCR\nDynamicANPR", 3.1, 2.55, 1.8, .9, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 4.9, 3.0, 5.65, 3.0)
card(slide, "Normalize\nplate", 5.7, 2.55, 1.4, .9, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 7.1, 3.0, 7.9, 3.0)
card(slide, "C1.csv..C4.csv\nexistence check", 7.95, 2.35, 1.85, 1.3, line=WHITE, color=WHITE, bold=True)
arrow(slide, 9.8, 3.0, 10.55, 3.0)
card(slide, "Leaflet map\nroute points", 10.6, 2.55, 1.75, .9, line=YELLOW, color=YELLOW, bold=True)
card(slide, "owner_details.csv", 4.6, 4.9, 2.0, .7, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 8.85, 3.7, 6.6, 4.9)
add_text(slide, "Outputs: camera locations, start/end times, owner status, route polyline, exportable CSV", .85, 6.2, 11.6, .35, 13, WHITE, False, PP_ALIGN.CENTER)

# 6 traffic
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 6); title(slide, "Page 4  /  Traffic Monitoring", "YOLO writes runtime vehicle IDs; the map turns recent CSV activity into traffic colors")
card(slide, "Rotating video\nfeeds", .5, 2.6, 1.55, .8, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 2.05, 3.0, 2.8, 3.0)
card(slide, "YOLO\nvehicle boxes", 2.85, 2.6, 1.65, .8, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 4.5, 3.0, 5.2, 3.0)
card(slide, "CAMn-V###\nCSV writer", 5.25, 2.6, 1.75, .8, line=WHITE, color=WHITE, bold=True)
arrow(slide, 7.0, 3.0, 7.75, 3.0)
card(slide, "60-second\nrolling window", 7.8, 2.6, 1.8, .8, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 9.6, 3.0, 10.15, 3.0)
card(slide, "Heatmap\nrefresh 5 sec", 10.2, 2.6, 1.7, .8, line=RED, color=RED, bold=True)
card(slide, "0-10  BLUE", .85, 4.7, 2.2, .65, line=BLUE, color=BLUE, bold=True)
card(slide, "11-15  ORANGE", 3.4, 4.7, 2.5, .65, line=ORANGE, color=ORANGE, bold=True)
card(slide, "16+  RED", 6.25, 4.7, 2.0, .65, line=RED, color=RED, bold=True)
add_text(slide, "Camera slots show runtime vehicle IDs, not license plates, because this path uses YOLO detection without OCR.", .8, 6.15, 11.8, .38, 12, MUTED, False, PP_ALIGN.CENTER)

# 7 data
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 7); title(slide, "Data and Module Map", "How files, models, and libraries support the pages")
card(slide, "Camera sighting CSVs\nC1.csv • C2.csv • C3.csv • C4.csv", .6, 1.65, 3.1, .9, line=WHITE, color=WHITE, bold=True)
card(slide, "Owner registries\nowner_details.csv\nvehicle_data.csv", .6, 3.05, 3.1, .9, line=ORANGE, color=ORANGE, bold=True)
card(slide, "Traffic runtime CSVs\ncam1..cam4_traffic.csv", .6, 4.45, 3.1, .9, line=RED, color=RED, bold=True)
card(slide, "menu/app.py\nFastAPI + mounts", 5.05, 2.75, 2.2, .95, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 3.75, 2.1, 5.05, 3.0); arrow(slide, 3.75, 3.5, 5.05, 3.2); arrow(slide, 3.75, 4.9, 5.05, 3.45)
card(slide, "YOLO\nOpenCV • NumPy\nPaddleOCR • Pandas", 8.2, 2.75, 2.5, .95, line=ORANGE, color=ORANGE, bold=True)
arrow(slide, 7.25, 3.2, 8.2, 3.2)
add_text(slide, "Frontend: HTML/CSS/JavaScript, Leaflet, Routing Machine, MarkerCluster, Font Awesome", .75, 6.2, 11.8, .4, 13, WHITE, False, PP_ALIGN.CENTER)

# 8 deployment
slide = prs.slides.add_slide(prs.slide_layouts[6]); add_bg(slide, 8); title(slide, "Run and Deployment Flow", "Local development and Docker entrypoints")
card(slide, "Local\nvenv", .75, 2.55, 1.55, .8, line=WHITE, color=WHITE, bold=True)
arrow(slide, 2.3, 2.95, 3.35, 2.95)
card(slide, "python menu/app.py\n127.0.0.1:8000", 3.4, 2.35, 2.25, 1.2, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 5.65, 2.95, 6.6, 2.95)
card(slide, "Integrated pages\nHome • ANPR • Tracking • Traffic", 6.65, 2.35, 2.7, 1.2, line=ORANGE, color=ORANGE, bold=True)
card(slide, "Dockerfile\npython:3.10-slim", .75, 4.75, 1.55, .8, line=WHITE, color=WHITE, bold=True)
arrow(slide, 2.3, 5.15, 3.35, 5.15)
card(slide, "docker-compose.yml\nport 8000:8000", 3.4, 4.75, 2.25, .8, line=GOLD, color=YELLOW, bold=True)
arrow(slide, 5.65, 5.15, 6.6, 5.15)
card(slide, "uvicorn main:app\ncontainer service", 6.65, 4.75, 2.7, .8, line=ORANGE, color=ORANGE, bold=True)
add_text(slide, "Key operational note: menu/app.py is the active integrated entrypoint used during local development.", .8, 6.55, 11.8, .3, 12, WHITE, False, PP_ALIGN.CENTER)

prs.save(OUT)
print(OUT)

"""
Lecture Notes -> Handwritten Notes
------------------------------------
Run: python app.py
Then open http://localhost:5000
Requires: pip install flask openai PyMuPDF Pillow
Put Caveat-VariableFont_wght.ttf in the same folder.
"""

import os, random, math, io, base64, traceback
from flask import Flask, request, jsonify, render_template_string
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import fitz  # PyMuPDF
from openai import OpenAI

# ── CONFIG ────────────────────────────────────────────────────────────────────
from dotenv import load_dotenv
load_dotenv()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
#os.environ.get("OPENAI_API_KEY", "YOUR_API_KEY_HERE")
FONT_PATH      = "Caveat-VariableFont_wght.ttf"

PAGE_W, PAGE_H      = 2550, 3300   # 300dpi letter (8.5x11in)
MARGIN_LEFT         = 380          # left red margin line x
MARGIN_RIGHT        = 2170         # faded right margin line x (~380px from right edge)
LINE_SPACING        = 60           # real lined paper spacing at 300dpi
FIRST_LINE_Y        = 320
FONT_SIZE           = 72
HEADING_SIZE        = 90
SUB_SIZE            = 76
INK                 = (30, 30, 30)
PAPER_BG            = (255, 255, 255)   # pure white
LINE_COLOR          = (173, 206, 225)   # blue ruled lines
MARGIN_COLOR        = (205, 80,  80)    # red left margin
MARGIN_RIGHT_COLOR  = (225, 170, 170)   # faded red right margin
CHAR_ROTATION_RANGE = 0.8
BASELINE_NOISE      = 0.6
SIZE_VARIATION      = 0.10
SPACING_VARIATION   = 0.12
INK_VARIATION       = 22
WORD_SPACING_JITTER = 6

# ── RENDERING PIPELINE ────────────────────────────────────────────────────────

def create_paper(draw):
    y = FIRST_LINE_Y
    while y < PAGE_H:
        draw.line([(0, y), (PAGE_W, y)], fill=LINE_COLOR, width=2)
        y += LINE_SPACING
    # Left red margin
    draw.line([(MARGIN_LEFT, 0), (MARGIN_LEFT, PAGE_H)], fill=MARGIN_COLOR, width=4)
    # Right faded red margin
    draw.line([(MARGIN_RIGHT, 0), (MARGIN_RIGHT, PAGE_H)], fill=MARGIN_RIGHT_COLOR, width=3)

def render_char(canvas, char, cx, cy, base_size, drift_y=0):
    size_delta = int(base_size * random.uniform(-SIZE_VARIATION, SIZE_VARIATION))
    char_size  = max(10, base_size + size_delta)
    try:
        font = ImageFont.truetype(FONT_PATH, char_size)
    except:
        font = ImageFont.load_default()
    bbox   = font.getbbox(char)
    char_w = max(1, bbox[2] - bbox[0])
    char_h = max(4, bbox[3] - bbox[1])
    pad    = 20
    tile   = Image.new("RGBA", (max(4, char_w + pad*2), max(4, char_h + pad*2)), (0,0,0,0))
    td     = ImageDraw.Draw(tile)
    v      = random.randint(-INK_VARIATION, INK_VARIATION // 2)
    ink    = (max(0,min(255,INK[0]+v)), max(0,min(255,INK[1]+v)),
              max(0,min(255,INK[2]+v)), random.randint(210, 255))
    td.text((pad - bbox[0], pad - bbox[1]), char, font=font, fill=ink)
    angle  = random.uniform(-CHAR_ROTATION_RANGE, CHAR_ROTATION_RANGE)
    tile   = tile.rotate(angle, expand=True, resample=Image.BICUBIC)
    y_noise = random.uniform(-BASELINE_NOISE, BASELINE_NOISE)
    canvas.paste(tile, (int(cx)-pad, int(cy + drift_y + y_noise)-pad), tile)
    advance = char_w + int(char_w * random.uniform(-SPACING_VARIATION, SPACING_VARIATION))
    return max(4, advance)

def render_text_line(canvas, text, x_start, y_baseline, base_size):
    x = x_start
    for char in text:
        if char == " ":
            x += int(base_size * 0.28) + random.randint(-WORD_SPACING_JITTER, WORD_SPACING_JITTER)
            continue
        x += render_char(canvas, char, x, y_baseline, base_size)
        if x > MARGIN_RIGHT - 30:
            break

def draw_underline(draw_canvas, x_start, y, text, size):
    try:
        font = ImageFont.truetype(FONT_PATH, size)
    except:
        return
    bbox   = font.getbbox(text)
    text_w = bbox[2] - bbox[0]
    uy     = y + (bbox[3] - bbox[1]) + 5
    px     = x_start
    while px < x_start + text_w:
        seg_len = random.randint(6, 14)
        end_x   = min(px + seg_len, x_start + text_w)
        y1 = uy + random.uniform(-1.5, 1.5)
        y2 = uy + random.uniform(-1.5, 1.5)
        v  = random.randint(-15, 5)
        draw_canvas.line([(px, y1), (end_x, y2)],
                         fill=(max(0,INK[0]+v), max(0,INK[1]+v), max(0,INK[2]+v)),
                         width=random.randint(1, 2))
        px = end_x + random.randint(0, 2)

def measure_text_width(text, font_size):
    """Measure how wide a string will render at a given font size."""
    try:
        font = ImageFont.truetype(FONT_PATH, font_size)
    except:
        return len(text) * font_size * 0.6
    total = 0
    for char in text:
        if char == " ":
            total += int(font_size * 0.28)
        else:
            bbox = font.getbbox(char)
            total += max(4, bbox[2] - bbox[0])
    return total

def wrap_text(text, x_start, font_size, max_x):
    """Break text into lines that fit within max_x, returning list of strings."""
    max_width = max_x - x_start
    words = text.split(" ")
    lines = []
    current = ""
    for word in words:
        test = (current + " " + word).strip()
        if measure_text_width(test, font_size) <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines if lines else [text]


def render_page(lines):
    img    = Image.new("RGB",  (PAGE_W, PAGE_H), PAPER_BG)
    canvas = Image.new("RGBA", (PAGE_W, PAGE_H), (0,0,0,0))
    draw_bg     = ImageDraw.Draw(img)
    draw_canvas = ImageDraw.Draw(canvas)
    create_paper(draw_bg)

    y      = FIRST_LINE_Y - 16
    margin = MARGIN_LEFT + 30

    i = 0
    while i < len(lines):
        raw = lines[i].rstrip()

        if raw.startswith("# "):
            text = raw[2:]
            x    = margin + random.randint(-4, 8)
            wrapped_lines = wrap_text(text, x, HEADING_SIZE, MARGIN_RIGHT - 20)
            if y + int(LINE_SPACING * 1.5) * len(wrapped_lines) > PAGE_H - 150:
                break
            for j, wrapped in enumerate(wrapped_lines):
                render_text_line(canvas, wrapped, x, y, HEADING_SIZE)
                if j == 0:
                    draw_underline(draw_canvas, x, y, wrapped, HEADING_SIZE)
                y += int(LINE_SPACING * 1.5)

        elif raw.startswith("## "):
            text = raw[3:]
            x    = margin + random.randint(-2, 6)
            wrapped_lines = wrap_text(text, x, SUB_SIZE, MARGIN_RIGHT - 20)
            if y + int(LINE_SPACING * 1.1) * len(wrapped_lines) > PAGE_H - 150:
                break
            for wrapped in wrapped_lines:
                render_text_line(canvas, wrapped, x, y, SUB_SIZE)
                y += int(LINE_SPACING * 1.1)

        elif raw.startswith("  - "):
            text = "- " + raw[4:]
            x    = margin + 120 + random.randint(-4, 6)
            cont = margin + 160
            wrapped_lines = wrap_text(text, x, FONT_SIZE - 2, MARGIN_RIGHT - 20)
            if y + LINE_SPACING * len(wrapped_lines) > PAGE_H - 150:
                break
            for j, wrapped in enumerate(wrapped_lines):
                render_text_line(canvas, wrapped, x if j == 0 else cont, y, FONT_SIZE - 2)
                y += LINE_SPACING

        elif raw.startswith("- "):
            text = "- " + raw[2:]
            x    = margin + 30 + random.randint(-4, 6)
            cont = margin + 60
            wrapped_lines = wrap_text(text, x, FONT_SIZE, MARGIN_RIGHT - 20)
            if y + LINE_SPACING * len(wrapped_lines) > PAGE_H - 150:
                break
            for j, wrapped in enumerate(wrapped_lines):
                render_text_line(canvas, wrapped, x if j == 0 else cont, y, FONT_SIZE)
                y += LINE_SPACING

        elif raw == "":
            y += int(LINE_SPACING * 0.55)

        else:
            x = margin + random.randint(-4, 10)
            wrapped_lines = wrap_text(raw, x, FONT_SIZE, MARGIN_RIGHT - 20)
            if y + LINE_SPACING * len(wrapped_lines) > PAGE_H - 150:
                break
            for wrapped in wrapped_lines:
                render_text_line(canvas, wrapped, x, y, FONT_SIZE)
                y += LINE_SPACING

        i += 1

    img.paste(
        Image.alpha_composite(Image.new("RGBA",(PAGE_W,PAGE_H),(0,0,0,0)), canvas).convert("RGB"),
        mask=canvas.split()[3]
    )
    img = img.filter(ImageFilter.GaussianBlur(radius=1.2))
    return img, lines[i:]  # return image and any remaining lines that didn't fit


def render_notes_to_b64(notes_text):
    remaining = notes_text.strip().split("\n")
    images    = []
    while remaining:
        img, remaining = render_page(remaining)
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        images.append(base64.b64encode(buf.getvalue()).decode())
        if not remaining:
            break
    return images

# ── GPT CALL ─────────────────────────────────────────────────────────────────

def generate_notes(raw_text):
    # Cap input to ~6000 words to control costs (~8k tokens)
    words = raw_text.split()
    if len(words) > 6000:
        raw_text = " ".join(words[:6000]) + "\n[truncated]"

    client   = OpenAI(api_key=OPENAI_API_KEY)
    response = client.chat.completions.create(
        model="gpt-4o-mini",  # ~15x cheaper than gpt-4o, plenty good for notes
        messages=[{
            "role": "user",
            "content": f"""Rewrite these lecture slides as detailed handwritten student notes.

Rules:
- Include specific terms, definitions, formulas, mechanisms, processes, and examples
- For each concept include a brief explanation, not just the name
- SKIP overview slides, learning objectives, and generic filler sentences
- Use only ASCII characters - no unicode, use -> instead of arrows
- Do NOT use ** for bold, * for italic, or any markdown formatting whatsoever
- Do NOT wrap output in code blocks or markdown fences
- Structure with these exact formats:
    # Main topic heading
    ## Sub heading
    - bullet point with enough detail to be useful
      - sub bullet (2 spaces then dash)
    plain paragraph text for explanations that need a few sentences
- Abbreviations are fine (w/, b/c, approx, etc.)
- Aim for the level of detail a diligent student would write, not a quick summary

Lecture content:
{raw_text}"""
        }]
    )
    text = response.choices[0].message.content
    import re
    # Strip code fences
    text = re.sub(r'^```[a-zA-Z]*\n?', '', text.strip())
    text = re.sub(r'\n?```$', '', text.strip())
    # Strip bold/italic markers
    text = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    text = re.sub(r'\*(.+?)\*', r'\1', text)
    # Strip ### and #### down to ## (keep # and ## for our renderer)
    text = re.sub(r'^#{3,}\s*', '## ', text, flags=re.MULTILINE)
    return text.strip()

# ── FLASK APP ─────────────────────────────────────────────────────────────────

app = Flask(__name__)

HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lecture Notes -> Handwritten</title>
<style>
  @import url('https://fonts.googleapis.com/css2?family=Lora:ital@0;1&family=Space+Mono&display=swap');

  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --cream:  #faf8f2;
    --paper:  #fff9ee;
    --ink:    #1a1a2e;
    --red:    #c94040;
    --blue:   #3a5a8c;
    --line:   #b8c8d8;
    --shadow: rgba(0,0,0,0.08);
  }

  body {
    background: var(--cream);
    font-family: 'Lora', Georgia, serif;
    color: var(--ink);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 48px 24px;
  }

  header {
    text-align: center;
    margin-bottom: 40px;
  }

  header h1 {
    font-size: 2rem;
    font-weight: 400;
    letter-spacing: -0.02em;
    color: var(--ink);
  }

  header p {
    margin-top: 8px;
    font-style: italic;
    color: #666;
    font-size: 0.95rem;
  }

  .card {
    background: white;
    border: 1px solid #e8e0d0;
    border-radius: 4px;
    padding: 32px;
    width: 100%;
    max-width: 620px;
    box-shadow: 0 2px 12px var(--shadow);
  }

  .drop-zone {
    border: 2px dashed #c8bfaa;
    border-radius: 4px;
    padding: 40px 24px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    background: var(--paper);
    position: relative;
  }

  .drop-zone:hover, .drop-zone.drag-over {
    border-color: var(--blue);
    background: #f0f5fa;
  }

  .drop-zone input[type="file"] {
    position: absolute; inset: 0;
    opacity: 0; cursor: pointer; width: 100%; height: 100%;
  }

  .drop-icon {
    font-size: 2.5rem;
    margin-bottom: 12px;
    display: block;
  }

  .drop-zone p {
    color: #888;
    font-size: 0.9rem;
  }

  .drop-zone .file-name {
    margin-top: 10px;
    font-family: 'Space Mono', monospace;
    font-size: 0.8rem;
    color: var(--blue);
    font-weight: bold;
  }

  .btn {
    display: block;
    width: 100%;
    margin-top: 20px;
    padding: 14px;
    background: var(--ink);
    color: white;
    border: none;
    border-radius: 4px;
    font-family: 'Lora', serif;
    font-size: 1rem;
    cursor: pointer;
    letter-spacing: 0.02em;
    transition: background 0.2s;
  }

  .btn:hover:not(:disabled) { background: #2d2d4a; }
  .btn:disabled { background: #aaa; cursor: not-allowed; }

  .status {
    margin-top: 16px;
    font-size: 0.88rem;
    color: #666;
    font-style: italic;
    text-align: center;
    min-height: 20px;
  }

  .status.error { color: var(--red); font-style: normal; }

  /* Progress steps */
  .steps {
    display: flex;
    justify-content: space-between;
    margin-top: 20px;
    gap: 8px;
  }

  .step {
    flex: 1;
    text-align: center;
    font-size: 0.72rem;
    color: #bbb;
    font-family: 'Space Mono', monospace;
    padding: 6px 4px;
    border-top: 2px solid #e0d8cc;
    transition: all 0.3s;
  }

  .step.active { color: var(--blue); border-top-color: var(--blue); }
  .step.done   { color: #5a8a5a; border-top-color: #5a8a5a; }

  /* Pages output */
  .pages {
    margin-top: 40px;
    width: 100%;
    max-width: 900px;
    display: flex;
    flex-direction: column;
    gap: 24px;
  }

  .page-wrap {
    position: relative;
    box-shadow: 0 4px 24px rgba(0,0,0,0.12), 0 1px 4px rgba(0,0,0,0.08);
    border-radius: 2px;
    overflow: hidden;
  }

  .page-wrap img {
    display: block;
    width: 100%;
    height: auto;
  }

  .page-label {
    position: absolute;
    top: 10px;
    right: 14px;
    font-family: 'Space Mono', monospace;
    font-size: 0.7rem;
    color: #aaa;
    background: rgba(255,255,255,0.8);
    padding: 2px 6px;
    border-radius: 2px;
  }

  .download-bar {
    margin-top: 20px;
    display: flex;
    gap: 12px;
    justify-content: center;
    flex-wrap: wrap;
  }

  .dl-btn {
    padding: 10px 20px;
    background: var(--paper);
    border: 1px solid #c8bfaa;
    border-radius: 4px;
    font-family: 'Lora', serif;
    font-size: 0.88rem;
    cursor: pointer;
    color: var(--ink);
    text-decoration: none;
    transition: all 0.2s;
  }

  .dl-btn:hover { background: #f0ece0; border-color: var(--blue); color: var(--blue); }

  .spinner {
    display: inline-block;
    width: 14px; height: 14px;
    border: 2px solid rgba(255,255,255,0.3);
    border-top-color: white;
    border-radius: 50%;
    animation: spin 0.7s linear infinite;
    vertical-align: middle;
    margin-right: 8px;
  }

  @keyframes spin { to { transform: rotate(360deg); } }

  .hidden { display: none !important; }
</style>
</head>
<body>

<header>
  <h1>Lecture Notes</h1>
  <p>Upload a PDF — get back handwritten notes</p>
</header>

<div class="card">
  <div class="drop-zone" id="dropZone">
    <input type="file" id="fileInput" accept=".pdf">
    <span class="drop-icon">📄</span>
    <p>Drop a PDF here or click to browse</p>
    <div class="file-name" id="fileName"></div>
  </div>

  <button class="btn" id="generateBtn" disabled>Generate Notes</button>

  <div class="steps">
    <div class="step" id="step1">1. Extract</div>
    <div class="step" id="step2">2. GPT</div>
    <div class="step" id="step3">3. Render</div>
  </div>

  <div class="status" id="status"></div>
</div>

<div class="pages hidden" id="pagesContainer"></div>
<div class="download-bar hidden" id="downloadBar"></div>

<script>
  const fileInput     = document.getElementById('fileInput');
  const dropZone      = document.getElementById('dropZone');
  const fileName      = document.getElementById('fileName');
  const generateBtn   = document.getElementById('generateBtn');
  const status        = document.getElementById('status');
  const pagesContainer = document.getElementById('pagesContainer');
  const downloadBar   = document.getElementById('downloadBar');

  let selectedFile = null;
  let renderedPages = [];

  // Drag and drop
  dropZone.addEventListener('dragover', e => { e.preventDefault(); dropZone.classList.add('drag-over'); });
  dropZone.addEventListener('dragleave', () => dropZone.classList.remove('drag-over'));
  dropZone.addEventListener('drop', e => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    const f = e.dataTransfer.files[0];
    if (f && f.type === 'application/pdf') setFile(f);
  });

  fileInput.addEventListener('change', () => {
    if (fileInput.files[0]) setFile(fileInput.files[0]);
  });

  function setFile(f) {
    selectedFile = f;
    fileName.textContent = f.name;
    generateBtn.disabled = false;
    setStatus('');
    setSteps(-1);
  }

  function setStatus(msg, isError = false) {
    status.textContent = msg;
    status.className = 'status' + (isError ? ' error' : '');
  }

  function setSteps(activeIndex) {
    ['step1','step2','step3'].forEach((id, i) => {
      const el = document.getElementById(id);
      el.className = 'step' + (i < activeIndex ? ' done' : i === activeIndex ? ' active' : '');
    });
  }

  generateBtn.addEventListener('click', async () => {
    if (!selectedFile) return;

    generateBtn.disabled = true;
    generateBtn.innerHTML = '<span class="spinner"></span>Working...';
    pagesContainer.classList.add('hidden');
    downloadBar.classList.add('hidden');
    renderedPages = [];

    try {
      const formData = new FormData();
      formData.append('pdf', selectedFile);

      setStatus('Extracting text from PDF...'); setSteps(0);
      const res = await fetch('/generate', { method: 'POST', body: formData });
      const data = await res.json();

      if (!res.ok || data.error) throw new Error(data.error || 'Server error');

      renderedPages = data.pages;
      showPages(data.pages);

    } catch (err) {
      setStatus('Error: ' + err.message, true);
      setSteps(-1);
    } finally {
      generateBtn.disabled = false;
      generateBtn.innerHTML = 'Generate Notes';
    }
  });

  function showPages(pages) {
    setSteps(3);
    setStatus(`Done! ${pages.length} page${pages.length > 1 ? 's' : ''} generated.`);

    pagesContainer.innerHTML = '';
    pagesContainer.classList.remove('hidden');

    pages.forEach((b64, i) => {
      const wrap  = document.createElement('div');
      wrap.className = 'page-wrap';
      const img   = document.createElement('img');
      img.src     = 'data:image/png;base64,' + b64;
      img.alt     = `Page ${i+1}`;
      const label = document.createElement('div');
      label.className = 'page-label';
      label.textContent = `p.${i+1}`;
      wrap.appendChild(img);
      wrap.appendChild(label);
      pagesContainer.appendChild(wrap);
    });

    // Download button - single zip of all pages
    downloadBar.innerHTML = '';
    downloadBar.classList.remove('hidden');
    const dlBtn = document.createElement('button');
    dlBtn.className = 'dl-btn';
    dlBtn.textContent = 'Download all pages';
    dlBtn.onclick = () => downloadAll(pages);
    downloadBar.appendChild(dlBtn);
  }

  async function downloadAll(pages) {
    // Send pages back to server to bundle as PDF
    const res  = await fetch('/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pages })
    });
    const blob = await res.blob();
    const url  = URL.createObjectURL(blob);
    const a    = document.createElement('a');
    a.href     = url;
    a.download = 'handwritten_notes.pdf';
    a.click();
    URL.revokeObjectURL(url);
  }

  // SSE progress updates
  const evtSource = new EventSource('/progress');
  evtSource.onmessage = e => {
    const d = JSON.parse(e.data);
    if (d.step !== undefined) setSteps(d.step);
    if (d.msg)  setStatus(d.msg);
  };
</script>
</body>
</html>"""

# Simple SSE progress via a shared dict (single-user dev tool)
progress_data = {"step": -1, "msg": ""}

def set_progress(step, msg):
    progress_data["step"] = step
    progress_data["msg"]  = msg

@app.route("/")
def index():
    return render_template_string(HTML)

@app.route("/progress")
def progress():
    def stream():
        import json, time
        last = None
        for _ in range(300):
            cur = dict(progress_data)
            if cur != last:
                yield f"data: {json.dumps(cur)}\n\n"
                last = dict(cur)
            time.sleep(0.3)
    from flask import Response
    return Response(stream(), mimetype="text/event-stream")

@app.route("/download", methods=["POST"])
def download():
    import json
    data  = request.get_json()
    pages_b64 = data.get("pages", [])
    images = []
    for b64 in pages_b64:
        img_bytes = base64.b64decode(b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        images.append(img)
    buf = io.BytesIO()
    if images:
        images[0].save(buf, format="PDF", save_all=True, append_images=images[1:])
    buf.seek(0)
    from flask import send_file
    return send_file(buf, mimetype="application/pdf",
                     as_attachment=True, download_name="handwritten_notes.pdf")

@app.route("/generate", methods=["POST"])
def generate():
    try:
        pdf_file = request.files.get("pdf")
        if not pdf_file:
            return jsonify({"error": "No PDF uploaded"}), 400

        # Step 1: Extract text
        set_progress(0, "Extracting text from PDF...")
        pdf_bytes = pdf_file.read()
        doc       = fitz.open(stream=pdf_bytes, filetype="pdf")
        raw_text  = "\n\n".join(page.get_text() for page in doc)
        if not raw_text.strip():
            return jsonify({"error": "Could not extract text from PDF (might be scanned/image-based)"}), 400

        # Step 2: GPT
        set_progress(1, "Sending to GPT-4o...")
        notes = generate_notes(raw_text)

        # Step 3: Render
        set_progress(2, "Rendering handwritten pages...")
        pages_b64 = render_notes_to_b64(notes)

        set_progress(3, "Done!")
        return jsonify({"pages": pages_b64})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    print("Starting server at http://localhost:5000")
    print(f"Font: {FONT_PATH}")
    if OPENAI_API_KEY == "YOUR_API_KEY_HERE":
        print("WARNING: Set your OpenAI API key in app.py or via OPENAI_API_KEY env var")
    app.run(debug=True, port=5000)
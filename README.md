```markdown
# Computer Control Agent

Military-grade stateless vision-language model (VLM) computer control system for Windows 11.

## System Requirements

### Operating System
- **Windows 11** (build 22000 or higher)
- DPI-aware desktop environment
- Desktop Window Manager (DWM) enabled

### Python Environment
- **Python 3.12+** (tested on 3.12.0)
- **Standard library only** - zero external dependencies
- Windows-native ctypes bindings for Win32 API

### Hardware
- Minimum 8GB RAM (16GB recommended for VLM inference)
- Screen resolution: Any (tested up to 4K, downsampled to 1536x864 for VLM processing)
- CPU: Modern x64 processor with AVX2 support

### VLM Backend
- **LM Studio** or compatible OpenAI-style API endpoint
- Default: `http://localhost:1234/v1/chat/completions`
- Tested models:
  - `qwen2-vl-7b-instruct`
  - `qwen3-vl-2b-instruct`
  - Any vision-capable model with function calling support

## Architecture

### Stateless Design

The agent operates in a **pure stateless loop**:

1. **Capture**: Full screen + cursor → BGRA buffer
2. **Downsample**: Nearest-neighbor to 1536x864 (configurable)
3. **Encode**: PNG RGB24 format
4. **Overlay Render**: HUD text composited onto screen
5. **Send**: Base64-encoded PNG + system prompt → VLM API
6. **Parse**: Tool call response (JSON schema validated)
7. **Execute**: Input action via Win32 SendInput
8. **Settle Wait**: Screen stabilization detection (optional)
9. **Repeat**: Loop continues until `done` tool called

**No persistent memory** between iterations - the VLM sees only the current visual state plus overlay text.

## Workflow

### Agent Mode (Default)

```bash
python agent.py
```

**Execution Flow:**

```
┌─────────────────────────────────────────────────┐
│ 1. CAPTURE SCREEN WITH CURSOR                   │
│    - Win32 BitBlt from desktop DC              │
│    - Cursor composited via DrawIconEx          │
│    - BGRA32 raw pixel buffer                   │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 2. DOWNSAMPLE (Nearest-Neighbor)                │
│    - Source: Native resolution (e.g., 1920x1080)│
│    - Target: 1536x864 (SCREEN_W x SCREEN_H)    │
│    - Cached coordinate mapping for performance  │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 3. ENCODE PNG                                   │
│    - BGRA → RGB conversion                     │
│    - Zlib compression (stdlib)                  │
│    - PNG chunk structure (IHDR/IDAT/IEND)       │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 4. OVERLAY RENDER (HUD)                         │
│    - Current reason text from previous action   │
│    - Layered window with per-pixel alpha        │
│    - White text + black outline for readability │
│    - Word-wrapped paragraphs with line numbers  │
│    - TOPMOST z-order enforcement               │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 5. VLM API CALL (Stateless)                     │
│    - POST /v1/chat/completions                  │
│    - System prompt: Computer control agent      │
│    - User message: PNG base64 image            │
│    - Tools: observe, click, type, scroll, done  │
│    - Temperature: 0.7 (configurable)            │
│    - Max tokens: 2000                          │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 6. PARSE TOOL CALL                              │
│    - Extract function name + arguments          │
│    - Validate coordinate range (0-1000)         │
│    - Extract reason field for HUD display       │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 7. EXECUTE ACTION                               │
│    - click: SendInput mouse move + down + up    │
│    - type: SendInput Unicode keyboard events    │
│    - scroll: SendInput mouse wheel events       │
│    - observe: Wait only (no input)              │
│    - done: Exit loop                           │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 8. SCREEN SETTLE DETECTION (Optional)           │
│    - Capture 256x144 sample frames             │
│    - Compare pixel differences (threshold 0.6%) │
│    - Require 2 consecutive stable frames        │
│    - Timeout after 2.5 seconds                 │
└─────────────────┬───────────────────────────────┘
                  │
┌─────────────────▼───────────────────────────────┐
│ 9. UPDATE HUD TEXT                              │
│    - Store reason from current tool call        │
│    - Will appear in NEXT iteration screenshot   │
│    - VLM sees its own previous reasoning        │
└─────────────────┬───────────────────────────────┘
                  │
                  └──► LOOP TO STEP 1
```

### Test Mode

```bash
python agent.py --test
```

**Interactive manual control for debugging:**

```
Available commands:
  observe [reason]              - Capture screen, optional reason text
  click <x> <y> [reason]        - Click at normalized coords (0-1000)
  type <text>                   - Type Unicode text
  scroll <dy> [reason]          - Scroll wheel (positive=up, negative=down)
  done [reason]                 - Exit test session
  quit                          - Immediate exit

Example:
> click 500 300 Clicking center-left area
> type Hello World
> scroll -240 Scrolling down two ticks
> done Test complete
```

**Test mode workflow:**
1. Captures initial screenshot → `dump/test_TIMESTAMP/test000.png`
2. Waits for user command input
3. Executes action via same input functions as agent mode
4. Applies screen settle detection (if enabled)
5. Renders reason text on HUD overlay
6. Captures post-action screenshot → `test001.png`, `test002.png`, etc.
7. Repeats until `done` or `quit`

**Purpose**: Validate input execution, overlay rendering, and screenshot pipeline without VLM dependency.

## Memory Mechanism (HUD System)

### Design Principle: "What Human Sees, VLM Sees"

The agent has **no internal memory** - all context must be visual. The HUD overlay is the memory system.

### How It Works

#### 1. Message Accumulation
- **Source**: `reason` field from VLM tool call responses
- **Storage**: `current_text` variable (string, overwritten each iteration)
- **Lifecycle**: Single iteration only (no history accumulation)
- **Display**: Rendered on next screen capture as overlay

#### 2. HUD Rendering Pipeline

```python
class OverlayManager:
    text: str = ""  # Current reason from last action
```

**Rendering stages:**

```
Text Input (reason field)
    ↓
Split into paragraphs (newline separated)
    ↓
Limit to 8 paragraphs (HUD_MAX_LINES)
    ↓
Add line numbers: "01| ", "02| ", etc.
    ↓
Word-wrap each paragraph to 700px width (HUD_MAX_WIDTH)
    ↓
Continuation lines indented: "    " (4 spaces)
    ↓
Measure text width (GetTextExtentPoint32W)
    ↓
Draw outline pass (black, 1px offset in 8 directions)
    ↓
Draw foreground pass (white text)
    ↓
Composite onto 32-bit BGRA bitmap
    ↓
UpdateLayeredWindow with per-pixel alpha
    ↓
SetWindowPos HWND_TOPMOST (2 pulses, 50ms apart)
```

#### 3. Visual Feedback Loop

```
Iteration N:
  VLM sees: Screen content + HUD showing reason from iteration N-1
  VLM outputs: Tool call with new reason text
  Execute action
  Update HUD: Display new reason
  
Iteration N+1:
  VLM sees: Updated screen + HUD showing reason from iteration N
  (VLM can reference its own previous reasoning visually)
```

**Example:**
```
Iteration 1:
  HUD: "" (empty)
  VLM: click(500, 300, reason="Opening start menu to launch browser")
  
Iteration 2:
  HUD: "01| Opening start menu to launch browser"
  VLM sees this text overlaid on screenshot
  VLM: type("firefox", reason="Typing browser name in search box")
  
Iteration 3:
  HUD: "01| Typing browser name in search box"
  VLM sees updated HUD reflecting its last action
```

### Why This Design?

1. **Stateless API**: VLM has no conversation history - must encode all context in image
2. **Grounding**: Agent sees exactly what it previously decided (prevents hallucination)
3. **Debugging**: Human operators see agent reasoning in real-time
4. **Self-correction**: VLM can visually observe if previous action achieved intended goal

### HUD Configuration

```python
HUD_MAX_WIDTH = 700          # Maximum text width in pixels
HUD_FONT_SIZE = -18          # Font height (negative = character height)
HUD_FONT_WEIGHT = 400        # Normal weight (700 = bold)
HUD_FONT_NAME = "Segoe UI"   # System font
HUD_LINE_SPACING = 2         # Pixels between lines
HUD_TEXT_COLOR = 0x00FFFFFF  # White RGB
HUD_OUTLINE_COLOR = 0x00000000  # Black RGB
HUD_OUTLINE_PX = 1           # Outline thickness
HUD_MARGIN = 10              # Screen edge padding
HUD_MAX_LINES = 8            # Maximum paragraphs displayed
```

### Overlay Window Properties

- **Window Style**: `WS_POPUP` (no chrome/borders)
- **Extended Style**: 
  - `WS_EX_LAYERED` - Per-pixel alpha blending
  - `WS_EX_TOPMOST` - Always on top
  - `WS_EX_TRANSPARENT` - Click-through (no input capture)
  - `WS_EX_NOACTIVATE` - Does not steal focus
  - `WS_EX_TOOLWINDOW` - Hidden from taskbar/Alt+Tab
- **Z-Order**: Reasserted every render (2 pulses via `SetWindowPos`)
- **Alpha**: 255 (fully opaque text, transparent background)

### Message Truncation

```python
paragraphs = [p.strip() for p in self.text.split("\n") if p.strip()][:HUD_MAX_LINES]
```

- Input split on newlines
- Empty lines filtered
- Maximum 8 paragraphs displayed
- Oldest paragraphs dropped first (simple slice)

**Rationale**: Prevent HUD from obscuring too much screen area while maintaining readability.

## Tool Schema

### Available Tools

#### 1. observe
```json
{
  "name": "observe",
  "parameters": {
    "reason": "string (required)"
  }
}
```
**Purpose**: Wait and observe screen state (no input action)  
**Use case**: After screen changes, before deciding next action  
**Delay**: 1.5 seconds (DELAY_AFTER_OBSERVE_S)

#### 2. click
```json
{
  "name": "click",
  "parameters": {
    "x": "number (0-1000, required)",
    "y": "number (0-1000, required)",
    "reason": "string (required)"
  }
}
```
**Purpose**: Left mouse click at normalized coordinates  
**Coordinate system**: 0,0 = top-left, 1000,1000 = bottom-right  
**Execution**: Move → MouseDown → MouseUp via SendInput  
**Delay**: 0.85 seconds post-action

#### 3. type
```json
{
  "name": "type",
  "parameters": {
    "text": "string (required)",
    "reason": "string (required)"
  }
}
```
**Purpose**: Type Unicode text into focused element  
**Encoding**: UTF-16LE converted to KEYBDINPUT scan codes  
**Execution**: KeyDown → KeyUp pairs for each character  
**Delay**: 0.85 seconds post-action

#### 4. scroll
```json
{
  "name": "scroll",
  "parameters": {
    "dy": "number (required)",
    "reason": "string (required)"
  }
}
```
**Purpose**: Vertical scroll wheel input  
**Direction**: Positive = scroll up, Negative = scroll down  
**Units**: Multiples of 120 (WHEEL_DELTA standard)  
**Example**: dy=240 → 2 ticks up, dy=-120 → 1 tick down  
**Delay**: 0.85 seconds post-action

#### 5. done
```json
{
  "name": "done",
  "parameters": {
    "reason": "string (required)"
  }
}
```
**Purpose**: Signal task completion and exit loop  
**Effect**: Agent loop terminates gracefully

## Screen Settle Detection

### Purpose
Wait for UI animations/transitions to complete before next VLM inference.

### Algorithm

```python
SETTLE_ENABLED = True              # Feature toggle
SETTLE_MAX_S = 2.5                 # Maximum wait time
SETTLE_SAMPLE_W = 256              # Sample resolution width
SETTLE_SAMPLE_H = 144              # Sample resolution height
SETTLE_CHECK_INTERVAL_S = 0.10     # Polling frequency
SETTLE_REQUIRED_STABLE = 2         # Consecutive stable frames needed
SETTLE_CHANGE_RATIO_THRESHOLD = 0.006  # 0.6% pixel change threshold
```

**Process:**
1. Capture full screen (no cursor) → BGRA buffer
2. Downsample to 256x144 sample
3. Compare with previous sample:
   - Extract RGB values every 16 pixels (stride)
   - Count changed pixels
   - Calculate ratio: changed / total_samples
4. If ratio ≤ 0.6%: increment stable counter
5. If ratio > 0.6%: reset stable counter
6. If stable counter ≥ 2: return (settled)
7. If elapsed time > 2.5s: return (timeout)
8. Sleep 100ms and repeat

**Rationale**: Prevents VLM from analyzing mid-animation frames, improving decision quality.

## Configuration

### API Settings
```python
API_URL = "http://localhost:1234/v1/chat/completions"
REQUEST_TIMEOUT_S = 120
TEMPERATURE = 0.7
TOP_P = 0.9
MAX_TOKENS = 2000
```

### Input Timing
```python
INPUT_DELAY_S = 0.10              # Delay after each SendInput batch
DELAY_AFTER_ACTION_S = 0.85       # Wait after click/type/scroll
DELAY_AFTER_OBSERVE_S = 1.5       # Wait after observe tool
```

### Screenshot Dumps
```python
DUMP_FOLDER = Path("dump")
DUMP_SCREENSHOTS = True
```

**Output structure:**
```
dump/
├── run_20240315_143022/
│   ├── step001.png
│   ├── step002.png
│   └── ...
└── test_20240315_143530/
    ├── test000.png
    ├── test001.png
    └── ...
```

## Command Line Interface

### Basic Usage
```bash
python agent.py              # Agent mode with default model
python agent.py --test       # Test mode (manual control)
python agent.py --model qwen3-vl-2b-instruct  # Specify model
```

### Environment Variables
None required - all configuration in code constants.

## Error Handling

### VLM API Failures
- **HTTP errors**: Log status code + response body (max 4KB)
- **Network errors**: Log exception message
- **Timeout**: 120 second request deadline
- **Consecutive failures**: Exit after 3 errors

### Tool Execution Failures
- **Invalid coordinates**: Clamped to 0-1000 range
- **SendInput failure**: Raise WinError with last error code
- **Screen capture failure**: Raise WinError, cleanup DCs/bitmaps

### Overlay Failures
- **Window creation**: Raise WinError, cleanup resources
- **UpdateLayeredWindow**: Raise WinError
- **SetWindowPos**: Silent failure (z-order not critical)

## Performance Characteristics

### Timing Budget (per iteration)
```
Screen capture:        ~50ms   (1920x1080 BitBlt + cursor composite)
Downsample:           ~20ms   (nearest-neighbor to 1536x864)
PNG encode:           ~100ms  (zlib compression)
Overlay render:       ~10ms   (text measurement + drawing)
VLM inference:        ~2-5s   (model-dependent, network latency)
Input execution:      ~100ms  (SendInput + delays)
Screen settle:        ~0-2.5s (optional, animation-dependent)

Total: ~3-8 seconds per action
```

### Memory Usage
- **Screen buffer**: 1920×1080×4 = 8.3 MB (max native resolution)
- **Downsampled buffer**: 1536×864×4 = 5.3 MB
- **PNG encoded**: ~500 KB - 2 MB (depends on screen content)
- **Overlay bitmap**: Native resolution × 4 bytes
- **Python overhead**: ~50 MB baseline

**Peak RAM**: ~100 MB (excluding VLM backend)

## Troubleshooting

### VLM not responding
1. Verify LM Studio is running: `http://localhost:1234/v1/models`
2. Check model supports vision input (image_url content type)
3. Check model supports function calling (tools parameter)
4. Increase `REQUEST_TIMEOUT_S` for slow models

### Overlay not visible
1. Ensure DWM is enabled (Windows 11 default)
2. Check z-order: Overlay should be HWND_TOPMOST
3. Verify `OVERLAY_REASSERT_PULSES > 0`
4. Check if other topmost windows are blocking

### Input not executing
1. Run as Administrator (some apps require elevated privileges)
2. Check `INPUT_DELAY_S` is sufficient for application responsiveness
3. Verify coordinates are within 0-1000 range
4. Test with `--test` mode to isolate VLM vs input issues

### Screen settle timeout
1. Increase `SETTLE_MAX_S` for slow animations
2. Decrease `SETTLE_CHANGE_RATIO_THRESHOLD` for stricter detection
3. Disable: `SETTLE_ENABLED = False` (not recommended)

## Development

### Code Structure
```
agent.py (single file, ~800 lines)
├── Win32 API bindings (ctypes structures)
├── Screen capture (BitBlt, cursor compositing)
├── Image processing (downsampling, PNG encoding)
├── Overlay rendering (layered window, text drawing)
├── Input injection (SendInput wrappers)
├── VLM API client (urllib stateless HTTP)
├── Screen settle detection (frame difference)
├── Test mode (interactive CLI)
└── Agent mode (main control loop)
```

### Adding New Tools

1. Define JSON schema in `TOOLS` list
2. Add case in `_execute_tool()` function
3. Implement Win32 input via `SendInput`
4. Update `SYSTEM_PROMPT` with tool description

### Modifying HUD

1. Edit constants: `HUD_*` variables
2. Adjust `_draw_text_outlined()` for styling
3. Modify `OverlayManager.render()` for layout
4. Test with `--test` mode before agent runs

## Security Considerations

- **Input injection**: Agent can control entire desktop (run in isolated VM recommended)
- **API credentials**: No authentication implemented (use localhost or VPN tunnel)
- **Screen content**: Screenshots may contain sensitive information (dump files not encrypted)
- **Code execution**: VLM cannot execute arbitrary code (limited to defined tool schema)

## License

This is a research prototype. Use at your own risk in controlled environments only.

## Future Enhancements

- [ ] Multi-monitor support (currently captures primary display only)
- [ ] Right-click / middle-click tools
- [ ] Keyboard modifiers (Ctrl, Alt, Shift + click)
- [ ] OCR integration for text extraction (if VLM struggles with small fonts)
- [ ] Bounding box annotations (draw regions of interest on HUD)
- [ ] Session replay (execute tool sequence from JSON log)

---

**Version**: 1.0.0  
**Last Updated**: 2024-03-15  
**Python**: 3.12+  
**Platform**: Windows 11 (Build 22000+)  
**Dependencies**: Python stdlib only
```

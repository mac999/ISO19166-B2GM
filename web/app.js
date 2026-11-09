/* B2GM web view: panels, splitters, theme, language and the WebGL canvas. */
(() => {
'use strict';

const $ = (id) => document.getElementById(id);
const api = async (url, options) => {
  const response = await fetch(url, options);
  const data = await response.json();
  if (data.error) throw new Error(data.error);
  return data;
};

/* --- language ------------------------------------------------------------- */
const TEXT = {
  en: {
    subtitle: 'BIM to GIS conceptual mapping',
    run: 'Run pipeline', running: 'Running...',
    inputPanel: 'Input', inputFiles: 'Input files', pipeline: 'Pipeline stages',
    outputPanel: 'Output', outputFiles: 'Output files',
    canvas: '3D view', preview: 'File preview', previewEmpty: 'Select a file',
    log: 'Log', logEmpty: 'Drop an .ifc on the canvas, or press Run pipeline',
    hint: 'Drag to orbit, wheel to zoom, right drag to pan',
    loading: 'Loading model...', empty: 'No geometry in this file',
    features: 'features', triangles: 'triangles', selectIfc: 'Select an .ifc file first',
    legend: 'Feature classes', toggle: 'Click to show or hide',
    dropTitle: 'Drop to convert', dropHint: 'an .ifc model, optionally with a pipeline .json',
    converting: 'Converting...', needIfc: 'Attach an .ifc file',
    opacity: 'Opacity', resetView: 'Reset view',
    applyConfig: 'Apply & run', needInput: 'Select an .ifc in the input tree first',
    trueScale: 'drawn at true ground scale',
    theme: 'Dark', themeLight: 'Light',
    saveJson: 'Save JSON', versionPipeline: 'CityGML: pipeline',
    modeShaded: 'Shaded', modeEdges: 'Shaded + edges', modeWire: 'Wireframe',
    modeXray: 'X-ray', modeFlat: 'Flat + edges', modeHidden: 'Hidden line',
    binary: 'binary file', truncated: 'preview cut at 64 KB',
    chipHint: 'click to open the stage and show its output',
    shown: 'shown in the 3D view',
    table: 'form', json: 'json', rule: 'rule', addRule: '+ rule', removeRule: 'remove rule',
    gizmoHint: 'Click an axis to look along it; click again for the other side',
    pipelineLoaded: 'pipeline loaded:',
    runFolder: 'Run every building folder in here and merge the result',
    viewFolder: 'Show every CityGML in this folder together, in its own coordinates',
    crsMixed: 'files use different CRSs:',
    stop: 'Stop', stopped: 'stopped', files: '{n} files',
  },
  ko: {
    subtitle: 'BIM-GIS 개념 매핑',
    run: '파이프라인 실행', running: '실행 중...',
    inputPanel: '입력', inputFiles: '입력 파일', pipeline: '파이프라인 단계',
    outputPanel: '출력', outputFiles: '출력 파일',
    canvas: '3차원 뷰', preview: '파일 미리보기', previewEmpty: '파일을 선택하세요',
    log: '로그', logEmpty: '캔버스에 .ifc 를 놓거나 파이프라인 실행을 누르세요',
    hint: '드래그 회전, 휠 확대, 우클릭 드래그 이동',
    loading: '모델 읽는 중...', empty: '이 파일에는 형상이 없습니다',
    features: '피처', triangles: '삼각형', selectIfc: '먼저 .ifc 파일을 선택하세요',
    legend: '피처 클래스', toggle: '클릭하면 표시/숨김',
    dropTitle: '놓으면 변환합니다', dropHint: '.ifc 모델, 원하면 파이프라인 .json 함께',
    converting: '변환 중...', needIfc: '.ifc 파일이 필요합니다',
    opacity: '투명도', resetView: '뷰 초기화',
    applyConfig: '적용 후 실행', needInput: '입력 트리에서 .ifc 를 먼저 선택하세요',
    trueScale: '실제 지상 비율로 표시',
    theme: '다크', themeLight: '라이트',
    saveJson: 'JSON 저장', versionPipeline: 'CityGML: 파이프라인 설정',
    modeShaded: '음영', modeEdges: '음영 + 모서리', modeWire: '와이어프레임',
    modeXray: '엑스레이', modeFlat: '단색 + 모서리', modeHidden: '은선 제거',
    binary: '이진 파일', truncated: '미리보기는 64 KB에서 잘림',
    chipHint: '클릭하면 단계를 열고 산출물을 3차원 뷰에 표시',
    shown: '3차원 뷰에 표시 중',
    table: '폼', json: 'json', rule: '규칙', addRule: '+ 규칙', removeRule: '규칙 삭제',
    gizmoHint: '축을 클릭하면 그 방향에서 봅니다. 다시 클릭하면 반대쪽',
    pipelineLoaded: '파이프라인 불러옴:',
    runFolder: '이 폴더의 건물 폴더를 모두 실행하고 하나로 합칩니다',
    viewFolder: '이 폴더의 CityGML을 각자의 좌표 그대로 한 화면에 모아 봅니다',
    crsMixed: '좌표계가 서로 다른 파일이 있습니다:',
    stop: '중지', stopped: '중지됨', files: '파일 {n}개',
  },
};

// ?lang=ko&theme=light&mode=wireframe&opacity=45&lod=LOD1&select=city.gml (or &folder=teheran-ro) makes a view shareable and scriptable
const params = new URLSearchParams(location.search);
let lang = params.get('lang') || localStorage.getItem('b2gm.lang') || 'en';
const t = (key) => (TEXT[lang][key] ?? TEXT.en[key] ?? key);

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $('lang').textContent = lang.toUpperCase();
  $('gizmo').title = t('gizmoHint');
  updateThemeLabel();
  renderPipeline();
  renderLegend();
  updateStats();
}

$('lang').onclick = () => {
  lang = lang === 'en' ? 'ko' : 'en';
  localStorage.setItem('b2gm.lang', lang);
  applyLanguage();
};

/* --- theme ---------------------------------------------------------------- */
function updateThemeLabel() {
  const dark = document.documentElement.dataset.theme === 'dark';
  $('theme').textContent = dark ? t('theme') : t('themeLight');
}

function setTheme(name) {
  document.documentElement.dataset.theme = name;
  localStorage.setItem('b2gm.theme', name);
  updateThemeLabel();
  renderer.readThemeColors();
  renderer.draw();
}

$('theme').onclick = () => {
  setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
};

/* --- splitters ------------------------------------------------------------ */
document.querySelectorAll('.splitter').forEach((splitter) => {
  splitter.addEventListener('pointerdown', (event) => {
    const side = splitter.dataset.target;
    const panel = $(side);
    const startX = event.clientX;
    const startWidth = panel.getBoundingClientRect().width;
    splitter.classList.add('active');
    splitter.setPointerCapture(event.pointerId);

    const onMove = (moveEvent) => {
      const delta = moveEvent.clientX - startX;
      const width = side === 'left' ? startWidth + delta : startWidth - delta;
      panel.style.width = `${Math.max(160, Math.min(window.innerWidth - 340, width))}px`;
      renderer.resize();
    };
    const onUp = () => {
      splitter.classList.remove('active');
      splitter.removeEventListener('pointermove', onMove);
      splitter.removeEventListener('pointerup', onUp);
      localStorage.setItem(`b2gm.w.${side}`, panel.style.width);
    };
    splitter.addEventListener('pointermove', onMove);
    splitter.addEventListener('pointerup', onUp);
  });
});

['left', 'right'].forEach((side) => {
  const width = localStorage.getItem(`b2gm.w.${side}`);
  if (width) $(side).style.width = width;
});

/* --- WebGL renderer ------------------------------------------------------- */
const VERTEX_SHADER = `
attribute vec3 aPos;
attribute vec3 aNormal;
attribute vec3 aColor;
uniform mat4 uMVP;
uniform mat4 uModel;
varying vec3 vNormal;
varying vec3 vColor;
void main() {
  vNormal = mat3(uModel) * aNormal;
  vColor = aColor;
  gl_Position = uMVP * vec4(aPos, 1.0);
}`;

const FRAGMENT_SHADER = `
precision mediump float;
varying vec3 vNormal;
varying vec3 vColor;
uniform vec3 uLight;
uniform float uAlpha;
uniform float uPaint;      // 0 shaded, 1 vertex colour (mixed), 2 one uniform colour
uniform vec3 uPaintColor;
uniform float uMix;        // how far a paint-1 colour leans towards uPaintColor
void main() {
  if (uPaint > 1.5) {
    gl_FragColor = vec4(uPaintColor, uAlpha);
    return;
  }
  if (uPaint > 0.5) {
    gl_FragColor = vec4(mix(vColor, uPaintColor, uMix), uAlpha);
    return;
  }
  vec3 n = normalize(vNormal);
  // IFC meshes do not wind consistently, so a back-facing normal must not
  // turn a wall black: light both sides
  float diffuse = abs(dot(n, normalize(uLight)));
  float ambient = 0.38;
  gl_FragColor = vec4(vColor * (ambient + 0.72 * diffuse), uAlpha);
}`;

const mat4 = {
  identity: () => new Float32Array([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]),
  multiply(a, b) {
    const out = new Float32Array(16);
    for (let i = 0; i < 4; i++) {
      for (let j = 0; j < 4; j++) {
        let sum = 0;
        for (let k = 0; k < 4; k++) sum += a[k * 4 + j] * b[i * 4 + k];
        out[i * 4 + j] = sum;
      }
    }
    return out;
  },
  perspective(fovy, aspect, near, far) {
    const f = 1 / Math.tan(fovy / 2);
    const out = new Float32Array(16);
    out[0] = f / aspect; out[5] = f; out[11] = -1;
    out[10] = (far + near) / (near - far);
    out[14] = (2 * far * near) / (near - far);
    return out;
  },
  lookAt(eye, center, up) {
    const z = vec.norm(vec.sub(eye, center));
    const x = vec.norm(vec.cross(up, z));
    const y = vec.cross(z, x);
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -vec.dot(x, eye), -vec.dot(y, eye), -vec.dot(z, eye), 1,
    ]);
  },
};

const vec = {
  sub: (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]],
  dot: (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2],
  cross: (a, b) => [
    a[1] * b[2] - a[2] * b[1],
    a[2] * b[0] - a[0] * b[2],
    a[0] * b[1] - a[1] * b[0],
  ],
  norm(v) {
    const l = Math.hypot(v[0], v[1], v[2]) || 1;
    return [v[0] / l, v[1] / l, v[2] / l];
  },
};

const PITCH_LIMIT = 1.55;

class Renderer {
  constructor(canvas) {
    this.canvas = canvas;
    this.gl = canvas.getContext('webgl', { antialias: true, alpha: false });
    this.model = null;
    this.center = [0, 0, 0];
    this.radius = 10;
    this.yaw = -0.9;
    this.pitch = 0.5;
    this.distance = 30;
    this.alpha = 1;
    this.mode = 'shaded';
    this.count = 0;
    this.edgeCount = 0;
    this.onDraw = null;
    if (!this.gl) return;
    this.initProgram();
    this.readThemeColors();
    this.bindInput();
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.resize();
  }

  initProgram() {
    const gl = this.gl;
    const compile = (type, source) => {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
        throw new Error(gl.getShaderInfoLog(shader));
      }
      return shader;
    };
    const program = gl.createProgram();
    gl.attachShader(program, compile(gl.VERTEX_SHADER, VERTEX_SHADER));
    gl.attachShader(program, compile(gl.FRAGMENT_SHADER, FRAGMENT_SHADER));
    gl.linkProgram(program);
    gl.useProgram(program);
    this.program = program;
    this.attr = {
      pos: gl.getAttribLocation(program, 'aPos'),
      normal: gl.getAttribLocation(program, 'aNormal'),
      color: gl.getAttribLocation(program, 'aColor'),
    };
    this.uniform = {
      mvp: gl.getUniformLocation(program, 'uMVP'),
      model: gl.getUniformLocation(program, 'uModel'),
      light: gl.getUniformLocation(program, 'uLight'),
      alpha: gl.getUniformLocation(program, 'uAlpha'),
      paint: gl.getUniformLocation(program, 'uPaint'),
      paintColor: gl.getUniformLocation(program, 'uPaintColor'),
      mix: gl.getUniformLocation(program, 'uMix'),
    };
    gl.enable(gl.DEPTH_TEST);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    this.buffer = gl.createBuffer();
    this.edgeBuffer = gl.createBuffer();
  }

  readThemeColors() {
    const style = getComputedStyle(document.documentElement);
    this.background = parseColor(style.getPropertyValue('--canvas-bottom')) || [0.1, 0.1, 0.1];
    this.edgeColor = parseColor(style.getPropertyValue('--muted')) || [0.5, 0.5, 0.5];
  }

  /* Camera basis in world space: where the screen's right and up point. */
  viewAxes() {
    const forward = [
      -Math.cos(this.pitch) * Math.cos(this.yaw),
      -Math.cos(this.pitch) * Math.sin(this.yaw),
      -Math.sin(this.pitch),
    ];
    const right = vec.norm(vec.cross(forward, [0, 0, 1]));
    const up = vec.cross(right, forward);
    return { forward, right, up };
  }

  bindInput() {
    const canvas = this.canvas;
    let mode = null;
    let last = [0, 0];
    canvas.addEventListener('contextmenu', (event) => event.preventDefault());
    canvas.addEventListener('pointerdown', (event) => {
      mode = event.button === 0 && !event.shiftKey ? 'orbit' : 'pan';
      last = [event.clientX, event.clientY];
      canvas.setPointerCapture(event.pointerId);
    });
    canvas.addEventListener('pointermove', (event) => {
      if (!mode) return;
      const dx = event.clientX - last[0];
      const dy = event.clientY - last[1];
      last = [event.clientX, event.clientY];
      if (mode === 'orbit') {
        this.yaw -= dx * 0.008;
        this.pitch = Math.max(-PITCH_LIMIT, Math.min(PITCH_LIMIT, this.pitch + dy * 0.008));
        this.snapped = null;
      } else {
        // the model follows the pointer: move the pivot along the screen axes,
        // so a later orbit still turns around what is in the middle of the view
        const scale = this.distance * 0.0016;
        const { right, up } = this.viewAxes();
        for (let k = 0; k < 3; k++) {
          this.center[k] += up[k] * dy * scale - right[k] * dx * scale;
        }
      }
      this.draw();
    });
    const stop = () => { mode = null; };
    canvas.addEventListener('pointerup', stop);
    canvas.addEventListener('pointercancel', stop);
    canvas.addEventListener('wheel', (event) => {
      event.preventDefault();
      this.distance *= event.deltaY > 0 ? 1.12 : 1 / 1.12;
      this.distance = Math.max(this.radius * 0.05, Math.min(this.radius * 60, this.distance));
      this.draw();
    }, { passive: false });
  }

  /* Build one interleaved buffer (position, face normal, colour) for the model. */
  load(model, hiddenClasses, hiddenLods) {
    if (!this.gl) return;
    const skip = hiddenClasses || new Set();
    const skipLod = hiddenLods || new Set();
    const features = model.features.filter(
      (f) => f.faces.length >= 3 && !skip.has(f.gis_class) && !skipLod.has(f.lod || ''));
    const triangles = features.reduce((sum, f) => sum + f.faces.length / 3, 0);
    // Georeferenced coordinates run to 1e7, past float32 precision, so the
    // buffer holds offsets from the model centre and the camera works there too.
    const { min, max } = model.bounds;
    const origin = [0, 1, 2].map((k) => (min[k] + max[k]) / 2);
    // Web Mercator stretches x and y but not z, so the model is drawn at true
    // ground proportions; the header says which CRS it came from
    const sx = model.xy_scale || 1;
    const data = new Float32Array(triangles * 3 * 9);
    let at = 0;
    for (const feature of features) {
      const { verts, faces, color } = feature;
      for (let i = 0; i < faces.length; i += 3) {
        const p = [0, 1, 2].map((k) => {
          const index = faces[i + k] * 3;
          return [(verts[index] - origin[0]) * sx,
                  (verts[index + 1] - origin[1]) * sx,
                  verts[index + 2] - origin[2]];
        });
        const u = [p[1][0] - p[0][0], p[1][1] - p[0][1], p[1][2] - p[0][2]];
        const v = [p[2][0] - p[0][0], p[2][1] - p[0][1], p[2][2] - p[0][2]];
        let n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]];
        const length = Math.hypot(n[0], n[1], n[2]);
        n = length ? [n[0] / length, n[1] / length, n[2] / length] : [0, 0, 1];
        for (let k = 0; k < 3; k++) {
          data[at++] = p[k][0]; data[at++] = p[k][1]; data[at++] = p[k][2];
          data[at++] = n[0]; data[at++] = n[1]; data[at++] = n[2];
          data[at++] = color[0]; data[at++] = color[1]; data[at++] = color[2];
        }
      }
    }
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    gl.bufferData(gl.ARRAY_BUFFER, data, gl.STATIC_DRAW);
    this.count = triangles * 3;
    this.vertexData = data;
    this.edgeCount = 0;   // rebuilt on demand for the edge modes

    const keepView = this.model === model;
    this.origin = origin;
    this.center = [0, 0, 0];   // the buffer is already centred on `origin`
    this.radius = Math.max(1e-3, Math.hypot((max[0] - min[0]) * sx,
                                            (max[1] - min[1]) * sx,
                                            max[2] - min[2]) / 2);
    this.model = model;
    if (keepView) this.draw(); else this.resetView();
  }

  /* Every triangle as three line segments, in the same vertex layout so the
     one program draws both. Built only when an edge mode asks for it. */
  buildEdges() {
    const src = this.vertexData;
    if (!src || !this.count) return;
    const out = new Float32Array(this.count * 2 * 9);
    let at = 0;
    for (let v = 0; v < this.count; v += 3) {
      for (let k = 0; k < 3; k++) {
        const a = (v + k) * 9;
        const b = (v + (k + 1) % 3) * 9;
        for (let j = 0; j < 9; j++) out[at++] = src[a + j];
        for (let j = 0; j < 9; j++) out[at++] = src[b + j];
      }
    }
    const gl = this.gl;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.edgeBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, out, gl.STATIC_DRAW);
    this.edgeCount = this.count * 2;
  }

  resetView() {
    this.distance = this.radius * 2.8;
    this.yaw = -0.9;
    this.pitch = 0.5;
    this.center = [0, 0, 0];
    this.snapped = null;
    this.draw();
  }

  /* Look straight along a world axis; the gizmo calls this. */
  snapTo(axis, sign) {
    if (axis === 'x') { this.yaw = sign > 0 ? 0 : Math.PI; this.pitch = 0; }
    if (axis === 'y') { this.yaw = sign > 0 ? Math.PI / 2 : -Math.PI / 2; this.pitch = 0; }
    if (axis === 'z') { this.pitch = sign > 0 ? PITCH_LIMIT : -PITCH_LIMIT; }
    this.snapped = { axis, sign };
    this.draw();
  }

  resize() {
    if (!this.gl) return;
    const ratio = window.devicePixelRatio || 1;
    const rect = this.canvas.parentElement.getBoundingClientRect();
    this.canvas.width = Math.max(1, Math.round(rect.width * ratio));
    this.canvas.height = Math.max(1, Math.round(rect.height * ratio));
    this.gl.viewport(0, 0, this.canvas.width, this.canvas.height);
    this.draw();
  }

  draw() {
    const gl = this.gl;
    if (!gl) return;
    gl.clearColor(this.background[0], this.background[1], this.background[2], 1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (this.onDraw) this.onDraw();
    if (!this.count) return;

    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    // Z-up model space: orbit around the pivot.
    const offset = [
      this.distance * Math.cos(this.pitch) * Math.cos(this.yaw),
      this.distance * Math.cos(this.pitch) * Math.sin(this.yaw),
      this.distance * Math.sin(this.pitch),
    ];
    const eye = [0, 1, 2].map((k) => this.center[k] + offset[k]);
    const view = mat4.lookAt(eye, this.center, [0, 0, 1]);
    const projection = mat4.perspective(Math.PI / 4, aspect, this.radius * 0.01, this.radius * 200);
    const model = mat4.identity();
    // a headlight a little above the camera keeps the lit side facing the viewer
    const light = vec.norm([offset[0], offset[1], offset[2] + this.distance * 0.5]);

    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uniform.mvp, false, mat4.multiply(projection, view));
    gl.uniformMatrix4fv(this.uniform.model, false, model);
    gl.uniform3f(this.uniform.light, light[0], light[1], light[2]);
    const mode = this.mode;
    if (this.alpha <= 0.005) return;   // fully transparent: nothing to draw
    // x-ray keeps the faces faint however far the slider goes; the edges follow it
    const alpha = mode === 'xray' ? Math.min(this.alpha, 0.22) : this.alpha;
    gl.uniform1f(this.uniform.alpha, alpha);
    // a translucent model must not write depth, or the faces behind vanish
    const translucent = alpha < 0.999;
    if (translucent) { gl.enable(gl.BLEND); gl.depthMask(false); }
    else { gl.disable(gl.BLEND); gl.depthMask(true); }
    const paint = (kind, color, mixAmount) => {
      gl.uniform1f(this.uniform.paint, kind);
      gl.uniform1f(this.uniform.mix, mixAmount || 0);
      if (color) gl.uniform3f(this.uniform.paintColor, color[0], color[1], color[2]);
    };

    const stride = 9 * 4;
    const bindAll = (buffer) => {
      gl.bindBuffer(gl.ARRAY_BUFFER, buffer);
      const bind = (location, offset) => {
        gl.enableVertexAttribArray(location);
        gl.vertexAttribPointer(location, 3, gl.FLOAT, false, stride, offset);
      };
      bind(this.attr.pos, 0);
      bind(this.attr.normal, 12);
      bind(this.attr.color, 24);
    };

    const edges = mode !== 'shaded';
    if (mode !== 'wireframe') {
      // hidden line: faces in the background colour only block what is behind them
      if (mode === 'hidden') paint(2, this.background);
      else if (mode === 'flat') paint(1);
      else paint(0);
      // push the faces back a little so the edges drawn over them win the depth test
      if (edges) { gl.enable(gl.POLYGON_OFFSET_FILL); gl.polygonOffset(1, 1); }
      bindAll(this.buffer);
      gl.drawArrays(gl.TRIANGLES, 0, this.count);
      if (edges) gl.disable(gl.POLYGON_OFFSET_FILL);
    }
    if (edges) {
      if (!this.edgeCount) this.buildEdges();
      // edges keep the class colour; over a face of the same colour they lean
      // towards the theme grey so they still read as lines
      const overFaces = mode === 'edges' || mode === 'flat';
      paint(1, this.edgeColor, overFaces ? 0.55 : 0);
      if (mode === 'xray') { gl.uniform1f(this.uniform.alpha, this.alpha); gl.enable(gl.BLEND); }
      bindAll(this.edgeBuffer);
      gl.drawArrays(gl.LINES, 0, this.edgeCount);
    }
    gl.depthMask(true);
  }
}

function parseColor(value) {
  const hex = value.trim();
  const match = /^#([0-9a-f]{6})$/i.exec(hex);
  if (!match) return null;
  const n = parseInt(match[1], 16);
  return [(n >> 16 & 255) / 255, (n >> 8 & 255) / 255, (n & 255) / 255];
}

const renderer = new Renderer($('scene'));

/* --- axis gizmo ----------------------------------------------------------- */
const AXES = [
  { name: 'x', dir: [1, 0, 0], color: '#e5484d' },
  { name: 'y', dir: [0, 1, 0], color: '#46a758' },
  { name: 'z', dir: [0, 0, 1], color: '#3e82f7' },
];
const gizmo = $('gizmo');
let gizmoTips = [];

function drawGizmo() {
  const ctx = gizmo.getContext('2d');
  const size = gizmo.width;
  const mid = size / 2;
  const reach = size * 0.36;
  ctx.clearRect(0, 0, size, size);
  const { forward, right, up } = renderer.viewAxes();
  const muted = getComputedStyle(document.documentElement).getPropertyValue('--muted').trim();
  // draw the axes pointing away from the viewer first so the near ones sit on top
  const tips = AXES.map((axis) => ({
    ...axis,
    x: mid + vec.dot(axis.dir, right) * reach,
    y: mid - vec.dot(axis.dir, up) * reach,
    depth: vec.dot(axis.dir, forward),
  })).sort((a, b) => b.depth - a.depth);
  ctx.lineWidth = 2;
  ctx.font = 'bold 11px system-ui, sans-serif';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  for (const tip of tips) {
    ctx.globalAlpha = tip.depth > 0.3 ? 0.45 : 1;
    ctx.strokeStyle = tip.color;
    ctx.beginPath();
    ctx.moveTo(mid, mid);
    ctx.lineTo(tip.x, tip.y);
    ctx.stroke();
    ctx.fillStyle = tip.color;
    ctx.beginPath();
    ctx.arc(tip.x, tip.y, 8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = '#fff';
    ctx.fillText(tip.name.toUpperCase(), tip.x, tip.y + 0.5);
  }
  ctx.globalAlpha = 1;
  ctx.fillStyle = muted || '#888';
  ctx.beginPath();
  ctx.arc(mid, mid, 2.5, 0, Math.PI * 2);
  ctx.fill();
  gizmoTips = tips;
}

gizmo.addEventListener('click', (event) => {
  const rect = gizmo.getBoundingClientRect();
  const x = (event.clientX - rect.left) * (gizmo.width / rect.width);
  const y = (event.clientY - rect.top) * (gizmo.height / rect.height);
  const hit = gizmoTips.find((tip) => Math.hypot(tip.x - x, tip.y - y) <= 11);
  if (!hit) return;
  const snapped = renderer.snapped;
  // a second click on the same axis looks from the other side
  const sign = snapped && snapped.axis === hit.name ? -snapped.sign : 1;
  renderer.snapTo(hit.name, sign);
});

renderer.onDraw = drawGizmo;
drawGizmo();

/* --- narrow screens: one panel at a time ---------------------------------- */
function showView(name) {
  const workspace = $('workspace');
  workspace.classList.remove('show-left', 'show-middle', 'show-right');
  workspace.classList.add(`show-${name}`);
  document.querySelectorAll('.mtab').forEach((tab) => {
    tab.classList.toggle('on', tab.dataset.view === name);
  });
  // the canvas was display:none, so it needs its size back
  if (name === 'middle') requestAnimationFrame(() => renderer.resize());
}

document.querySelectorAll('.mtab').forEach((tab) => {
  tab.onclick = () => showView(tab.dataset.view);
});
showView(params.get('view') || 'middle');

const isNarrow = () => window.matchMedia('(max-width: 900px)').matches;

// during boot the trees auto-select a file; jumping to the canvas then would
// override an explicit ?view=, so the automatic switch waits until boot is done
let booted = false;

/* --- right panel tabs ----------------------------------------------------- */
document.querySelectorAll('.tabs .tab').forEach((tab) => {
  tab.onclick = () => showPanel(tab.dataset.panel);
});

function showPanel(name) {
  document.querySelectorAll('.tabs .tab').forEach((tab) => {
    tab.classList.toggle('on', tab.dataset.panel === name);
  });
  $('preview').hidden = name !== 'preview';
  $('runlog').hidden = name !== 'runlog';
}

/* Write the stage log where the user can see it, and bring it to the front. */
function writeLog(lines) {
  $('runlog').textContent = Array.isArray(lines) ? lines.join('\n') : String(lines);
  showPanel('runlog');
}

/* --- view tools ----------------------------------------------------------- */
$('opacity').addEventListener('input', (event) => {
  const percent = Number(event.target.value);
  $('opacity-val').textContent = `${percent}%`;
  renderer.alpha = percent / 100;
  renderer.draw();
});

$('reset-view').onclick = () => renderer.resetView();

// ?opacity=45 presets the slider, so a translucent view can be shared as a link
if (params.get('opacity')) {
  $('opacity').value = params.get('opacity');
  $('opacity').dispatchEvent(new Event('input'));
}

$('mode').value = params.get('mode') || localStorage.getItem('b2gm.mode') || 'shaded';
renderer.mode = $('mode').value;
$('mode').onchange = () => {
  renderer.mode = $('mode').value;
  localStorage.setItem('b2gm.mode', renderer.mode);
  renderer.draw();
};

/* --- run options: the pipeline CLI flags that make sense in a browser ------ */
$('version').value = params.get('version') || localStorage.getItem('b2gm.version') || '';
$('save-json').checked = localStorage.getItem('b2gm.saveJson') === '1';
$('version').onchange = () => localStorage.setItem('b2gm.version', $('version').value);
$('save-json').onchange = () => localStorage.setItem('b2gm.saveJson', $('save-json').checked ? '1' : '0');

function runOptions() {
  return {
    version: $('version').value || pipelineVersion() || '',
    save_json: $('save-json').checked,
  };
}

/* --- trees ---------------------------------------------------------------- */
let selectedInput = null;
let selectedPipeline = null;   // a .json picked in the input tree, else the default

function renderTree(node, container, side) {
  container.innerHTML = '';
  const walk = (item, parent, depth) => {
    const li = document.createElement('li');
    const row = document.createElement('div');
    row.className = 'node';
    if (item.type === 'file' && !item.viewable && side === 'output') row.classList.add('dim');
    row.innerHTML = `<span class="tw">${item.type === 'dir' ? '▾' : ''}</span>`
      + `<span class="nm">${item.name}</span>`
      + (item.size !== undefined ? `<span class="sz">${formatSize(item.size)}</span>` : '');
    row.dataset.path = item.path || '';
    li.appendChild(row);
    parent.appendChild(li);

    if (item.type === 'dir') {
      const children = document.createElement('ul');
      item.children.forEach((child) => walk(child, children, depth + 1));
      li.appendChild(children);
      row.onclick = () => {
        const open = children.style.display !== 'none';
        children.style.display = open ? 'none' : '';
        row.querySelector('.tw').textContent = open ? '▸' : '▾';
      };
      // an input folder of building folders runs as one district
      if (side === 'input' && depth > 0) {
        const run = document.createElement('button');
        run.type = 'button';
        run.className = 'runfolder';
        run.textContent = '▶';
        run.title = t('runFolder');
        run.onclick = (event) => { event.stopPropagation(); runFolder(item.path, item.name); };
        row.appendChild(run);
      }
      if (side === 'output' && depth > 0 && folderModels(item).length) {
        const view = document.createElement('button');
        view.type = 'button';
        view.className = 'runfolder';
        view.textContent = '◫';
        view.title = t('viewFolder');
        view.onclick = (event) => {
          event.stopPropagation();
          container.querySelectorAll('.node.on').forEach((n) => n.classList.remove('on'));
          row.classList.add('on');
          loadFolder(item);
          if (booted && isNarrow()) showView('middle');
        };
        row.appendChild(view);
      }
      return;
    }
    row.onclick = () => {
      container.querySelectorAll('.node.on').forEach((n) => n.classList.remove('on'));
      row.classList.add('on');
      if (side === 'input') selectedInput = item.path;
      loadPreview(side, item.path);
      if (side === 'input' && item.name.toLowerCase().endsWith('.json')) {
        loadPipelineFile(item.path, item.name);
      }
      if (item.viewable) {
        loadModel(side, item.path, item.name);
      } else {
        showDocument(side, item.path, item.name);
      }
      if (booted && isNarrow()) showView('middle');
    };
  };
  walk(node, container, 0);
}

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

/* A .json in the input tree that holds a pipeline replaces the one in the
   panel, which is the browser's form of the --pipeline flag. */
async function loadPipelineFile(path, name) {
  try {
    const described = await api(`/api/pipeline?path=${encodeURIComponent(path)}`);
    if (!described.stages.length) return;   // some other config, just previewed
    pipeline = described;
    selectedPipeline = path;
    pipelineEdited = false;
    renderPipeline();
    $('pipeline-name').textContent = name;
    $('runlog').textContent = `${t('pipelineLoaded')} ${name}`;
  } catch (error) {
    writeLog(error.message);
  }
}

/* --- pipeline panel ------------------------------------------------------- */
let pipeline = { stages: [] };

function renderPipeline() {
  const host = $('stage-list');
  const chips = $('stage-chips');
  if (!host) return;
  host.innerHTML = '';
  chips.innerHTML = '';
  pipeline.stages.forEach((stage, index) => {
    const title = lang === 'ko' ? stage.title_ko : stage.title_en;
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip';
    chip.textContent = stage.type;
    chip.dataset.title = `${title}${stage.output ? ` (${stage.output})` : ''}: ${t('chipHint')}`;
    chip.title = chip.dataset.title;
    chips.appendChild(chip);

    const box = document.createElement('div');
    box.className = 'stage' + (index === 0 ? ' open' : '');
    box.innerHTML = `<div class="stage-head"><span class="tag">${stage.type}</span>`
      + `<span class="stage-name">${title}</span></div><div class="stage-body"></div>`;
    const body = box.querySelector('.stage-body');
    stage.properties.forEach((property) => {
      body.appendChild(buildProperty(property, index));
    });
    box.querySelector('.stage-head').onclick = () => box.classList.toggle('open');
    host.appendChild(box);

    // the chip opens its stage in the panel and puts the stage's output on the canvas
    chip.onclick = () => {
      host.querySelectorAll('.stage').forEach((b, i) => b.classList.toggle('open', i === index));
      box.scrollIntoView({ block: 'nearest' });
      if (stage.output) selectOutput(stage.output);
    };
  });
  updateApplyState();
}

/* One editable property. A scalar is a text field. A rule set is a list of
   flat records, so it becomes a table with a json toggle; anything else stays
   json, which is the shape the standard defines. */
function buildProperty(property, stageIndex) {
  const row = document.createElement('div');
  row.className = 'prop';
  row.dataset.stage = stageIndex;
  row.dataset.key = property.key;
  const head = document.createElement('div');
  head.className = 'prop-head';
  const key = document.createElement('label');
  key.className = 'prop-key';
  key.textContent = property.key;
  head.appendChild(key);
  row.appendChild(head);

  if (property.scalar) {
    const field = document.createElement('input');
    field.className = 'prop-input';
    field.type = 'text';
    field.value = property.value;
    field.oninput = () => { property.value = field.value; markEdited(row); };
    row.appendChild(field);
    row.readValue = () => {
      const raw = field.value;
      const asNumber = raw.trim() !== '' && !Number.isNaN(Number(raw));
      return asNumber ? Number(raw) : raw;
    };
    return row;
  }

  let value = null;
  try { value = JSON.parse(property.value); } catch (error) { value = null; }
  const tabular = isRecordList(value) || isRecord(value) || (Array.isArray(value) && value.length === 0 && (property.fields || []).length > 0);
  let mode = tabular ? 'table' : 'json';
  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'sw';
  toggle.hidden = !tabular;
  head.appendChild(toggle);
  const holder = document.createElement('div');
  row.appendChild(holder);
  let textarea = null;

  const remember = () => { property.value = JSON.stringify(value, null, 1); };

  const render = () => {
    holder.innerHTML = '';
    toggle.textContent = mode === 'table' ? t('json') : t('table');
    if (mode === 'table') {
      holder.appendChild(buildInspector(value, property.fields || [], () => { remember(); markEdited(row); }, render));
      textarea = null;
    } else {
      textarea = document.createElement('textarea');
      textarea.className = 'prop-val';
      textarea.value = property.value;
      textarea.oninput = () => { property.value = textarea.value; markEdited(row); };
      holder.appendChild(textarea);
    }
  };

  toggle.onclick = () => {
    if (mode === 'json') {
      try { value = JSON.parse(textarea.value); } catch (error) {
        textarea.classList.add('bad');
        writeLog(`${property.key}: ${error.message}`);
        return;
      }
      if (!isRecordList(value) && !isRecord(value) && !Array.isArray(value)) return;
      remember();
    }
    mode = mode === 'table' ? 'json' : 'table';
    render();
  };

  row.readValue = () => {
    if (mode === 'table') return cleanRecords(value, property.key);
    try { return JSON.parse(textarea.value); } catch (error) {
      throw new Error(`${property.key}: ${error.message}`);
    }
  };
  render();
  return row;
}

const isRecord = (v) => v !== null && typeof v === 'object' && !Array.isArray(v);
const isRecordList = (v) => Array.isArray(v) && v.length > 0 && v.every(isRecord);

/* Records edit in place as a property grid: every key the standard defines for
   this rule is listed, filled or not, so the user picks from what exists rather
   than typing key names. A nested value keeps its json in the field. */
function buildInspector(value, fields, changed, rerender) {
  const wrap = document.createElement('div');
  wrap.className = 'rules';
  const list = Array.isArray(value);
  const records = list ? value : [value];
  const known = fields.map((f) => f.key);

  const control = (record, field) => {
    const current = record[field.key];
    const nested = current !== null && typeof current === 'object';
    const kind = nested && field.kind !== 'json' ? 'json' : field.kind;
    const text = current === undefined ? '' : nested ? JSON.stringify(current) : String(current);
    let input;
    if (kind === 'enum' || kind === 'bool') {
      input = document.createElement('select');
      const options = kind === 'bool' ? ['true', 'false'] : field.options || [];
      ['', ...options].forEach((option) => {
        const node = document.createElement('option');
        node.value = option;
        node.textContent = option;
        input.appendChild(node);
      });
      if (text !== '' && ![...input.options].some((o) => o.value === text)) {
        const node = document.createElement('option');
        node.value = text;
        node.textContent = text;
        input.appendChild(node);
      }
      input.value = text;
    } else {
      input = document.createElement('input');
      input.type = 'text';
      input.value = text;
      if (kind === 'choice' && field.options) {
        const id = `dl-${field.key}-${Math.random().toString(36).slice(2, 7)}`;
        const datalist = document.createElement('datalist');
        datalist.id = id;
        field.options.forEach((option) => {
          const node = document.createElement('option');
          node.value = option;
          datalist.appendChild(node);
        });
        wrap.appendChild(datalist);
        input.setAttribute('list', id);
      }
    }
    if (kind === 'json') input.classList.add('nested');
    if (field.hint) input.placeholder = field.hint;
    input.title = field.hint || field.key;
    input.oninput = input.onchange = () => {
      const raw = input.value;
      if (kind === 'json' || /^[[{]/.test(raw.trim())) {
        try { record[field.key] = raw.trim() === '' ? '' : JSON.parse(raw); input.classList.remove('bad'); }
        catch (error) { record[field.key] = { __invalid: raw }; input.classList.add('bad'); }
      } else {
        record[field.key] = cellValue(raw);
      }
      changed();
    };
    return input;
  };

  const card = (record, index) => {
    const box = document.createElement('div');
    box.className = 'rule';
    if (list) {
      const head = document.createElement('div');
      head.className = 'rule-head';
      head.innerHTML = `<span>${t('rule')} ${index + 1}</span>`;
      const remove = document.createElement('button');
      remove.type = 'button';
      remove.className = 'rm';
      remove.textContent = '×';
      remove.title = t('removeRule');
      remove.onclick = () => { value.splice(index, 1); changed(); rerender(); };
      head.appendChild(remove);
      box.appendChild(head);
    }
    const grid = document.createElement('div');
    grid.className = 'kv';
    // standard keys first, in their order; anything else the file carries after
    const extra = Object.keys(record).filter((k) => !known.includes(k))
      .map((k) => ({ key: k, kind: 'text' }));
    [...fields, ...extra].forEach((field) => {
      const key = document.createElement('span');
      key.className = 'k';
      key.textContent = field.key;
      key.title = field.hint || field.key;
      grid.appendChild(key);
      grid.appendChild(control(record, field));
    });
    box.appendChild(grid);
    return box;
  };

  records.forEach((record, index) => wrap.appendChild(card(record, index)));
  if (list) {
    const add = document.createElement('button');
    add.type = 'button';
    add.className = 'add';
    add.textContent = t('addRule');
    add.onclick = () => { value.push({}); changed(); rerender(); };
    wrap.appendChild(add);
  }
  return wrap;
}

/* "true"/"false" and numbers come back typed; everything else is a string. */
function cellValue(text) {
  const raw = text.trim();
  if (raw === '') return '';
  if (raw === 'true') return true;
  if (raw === 'false') return false;
  if (!Number.isNaN(Number(raw))) return Number(raw);
  return text;
}

/* Blank cells are dropped so an added row only carries what was filled in. */
function cleanRecords(value, key) {
  const clean = (record) => {
    const out = {};
    for (const [k, v] of Object.entries(record)) {
      if (v === '' || v === undefined) continue;
      if (v && typeof v === 'object' && '__invalid' in v) {
        throw new Error(`${key}.${k}: invalid JSON`);
      }
      out[k] = v;
    }
    return out;
  };
  return Array.isArray(value) ? value.map(clean) : clean(value);
}

let pipelineEdited = false;

function markEdited(row) {
  row.classList.add('edited');
  pipelineEdited = true;
  updateApplyState();
}

function updateApplyState() {
  const apply = $('apply-config');
  if (apply) apply.disabled = !pipelineEdited;
}

/* Rebuild the pipeline document from the fields, so an edit is sent as a whole
   config rather than a patch. */
function editedPipeline() {
  const document_ = JSON.parse(JSON.stringify(pipeline.document || {}));
  const stages = document_['BIM_GIS_mapping.pipeline'] || [];
  document.querySelectorAll('#stage-list .prop').forEach((row) => {
    const stage = stages[Number(row.dataset.stage)];
    if (!stage) return;
    stage[row.dataset.key] = row.readValue();
  });
  return document_;
}

function markStage(type) {
  [...$('stage-chips').children].forEach((chip) => {
    const on = chip.textContent === type;
    chip.classList.toggle('on', on);
    chip.title = (on ? `${t('shown')}. ` : '') + (chip.dataset.title || '');
  });
}

/* Which stage wrote this file: its output name in the pipeline, else a guess. */
function stageFor(path) {
  const name = path.split('/').pop();
  const hit = (pipeline.stages || []).find((stage) => stage.output === name);
  if (hit) return hit.type;
  return /LoD/i.test(name) ? 'LM' : /city/i.test(name) ? 'EM' : null;
}

/* --- model + preview ------------------------------------------------------ */
const hiddenClasses = new Set((params.get('hide') || '').split(',').filter(Boolean));
// ?lod=LOD1,LOD2 shows only those levels; the chips above the canvas toggle them
const hiddenLods = new Set();
const wantedLods = (params.get('lod') || '').split(',').filter(Boolean);

function renderLods() {
  const host = $('lod-chips');
  const model = renderer.model;
  host.innerHTML = '';
  if (!model) return;
  const levels = [...new Set(model.features.map((f) => f.lod).filter(Boolean))].sort();
  if (!levels.length) return;
  if (wantedLods.length) {
    levels.forEach((level) => { if (!wantedLods.includes(level)) hiddenLods.add(level); });
    wantedLods.length = 0;   // applied once, then the chips own the state
  }
  levels.forEach((level) => {
    const chip = document.createElement('button');
    chip.type = 'button';
    chip.className = 'chip' + (hiddenLods.has(level) ? ' off' : '');
    chip.textContent = level;
    chip.title = t('toggle');
    chip.onclick = () => {
      if (hiddenLods.has(level)) hiddenLods.delete(level);
      else hiddenLods.add(level);
      renderer.load(renderer.model, hiddenClasses, hiddenLods);
      renderLods();
    };
    host.appendChild(chip);
  });
}

function renderLegend() {
  const legend = $('legend');
  if (!renderer.model) { legend.innerHTML = ''; return; }
  const counts = new Map();
  renderer.model.features.forEach((feature) => {
    const entry = counts.get(feature.gis_class) || { n: 0, color: feature.color };
    entry.n += 1;
    counts.set(feature.gis_class, entry);
  });
  legend.innerHTML = `<div class="legend-head">${t('legend')}</div>`
    + [...counts.entries()].sort((a, b) => b[1].n - a[1].n).map(([name, entry]) => {
      const rgb = entry.color.map((c) => Math.round(c * 255)).join(',');
      const off = hiddenClasses.has(name) ? ' off' : '';
      return `<div class="legend-row${off}" data-class="${name}" title="${t('toggle')}">`
        + `<span class="swatch" style="background:rgb(${rgb})"></span>`
        + `<span>${name || '-'}</span><span class="n">${entry.n}</span></div>`;
    }).join('');
  legend.querySelectorAll('.legend-row[data-class]').forEach((row) => {
    row.onclick = () => {
      const name = row.dataset.class;
      if (hiddenClasses.has(name)) hiddenClasses.delete(name);
      else hiddenClasses.add(name);
      renderer.load(renderer.model, hiddenClasses, hiddenLods);
      renderLegend();
    };
  });
}

function updateStats() {
  const model = renderer.model;
  if (!model) { $('model-stats').textContent = ''; return; }
  const parts = [`${model.features.length} ${t('features')}`,
                 `${model.triangles} ${t('triangles')}`];
  if (model.crs) {
    parts.push(model.xy_scale && Math.abs(model.xy_scale - 1) > 1e-6
      ? `${model.crs} (${t('trueScale')})` : model.crs);
  }
  $('model-stats').textContent = parts.join(' / ');
}

function busy(on, message) {
  $('overlay').hidden = !on;
  $('overlay-text').textContent = message || '';
}

let loadSeq = 0;

async function loadModel(side, path, label) {
  // two files can be requested in a row at boot; only the last one may land
  const token = ++loadSeq;
  if (folderAbort) folderAbort.abort();
  $('progress').hidden = true;
  busy(true, t('loading'));
  try {
    const model = await api(`/api/model?side=${side}&path=${encodeURIComponent(path)}`);
    if (token !== loadSeq) return;
    $('model-title').textContent = label || path;
    if (!model.features.length) {
      renderer.model = null;
      renderer.count = 0;
      renderer.draw();
      $('legend').innerHTML = `<div class="legend-row">${t('empty')}</div>`;
      $('lod-chips').innerHTML = '';
      await showDocument(side, path, label);
    } else {
      hideDocument();
      // the lod filter applies before the first draw, so ?lod= lands directly
      renderer.model = model;
      renderLods();
      renderer.model = null;
      renderer.load(model, hiddenClasses, hiddenLods);
      renderLegend();
    }
    updateStats();
    markStage(side === 'output' ? stageFor(path) : null);
  } catch (error) {
    $('legend').innerHTML = `<div class="legend-row err">${error.message}</div>`;
  } finally {
    if (token === loadSeq) busy(false);
  }
}

/* The CityGML files a folder view draws. A run folder holds every stage's
   CityGML and the stage that ran last wrote the result, so the newest file
   stands for the run; a folder whose subfolders hold runs is a district, and
   its own .gml is their merge. */
function folderModels(item) {
  const gml = (n) => n.type === 'file' && n.name.toLowerCase().endsWith('.gml');
  const nested = item.children.filter((n) => n.type === 'dir').flatMap(folderModels);
  if (nested.length) return nested;
  const files = item.children.filter(gml);
  if (!files.length) return [];
  return [files.reduce((a, b) => ((b.mtime || 0) > (a.mtime || 0) ? b : a))];
}

function findDir(node, path) {
  if (!node || node.type !== 'dir') return null;
  if (node.path === path) return node;
  for (const child of node.children) {
    const hit = findDir(child, path);
    if (hit) return hit;
  }
  return null;
}

/* Read the files one after another into one scene. Coordinates are kept as
   written, so a building placed by CM shows where CM put it. The canvas stays
   usable while files land, and Stop keeps whatever has been read. */
let folderAbort = null;

async function loadFolder(item) {
  const token = ++loadSeq;
  if (folderAbort) folderAbort.abort();
  const abort = new AbortController();
  folderAbort = abort;
  const files = folderModels(item);
  const merged = { features: [], bounds: null, crs: null, xy_scale: 1, triangles: 0 };
  const crss = new Set();
  let read = 0;
  let drawnAt = 0;
  const show = () => {
    // a fresh object each time so the view refits to what has landed so far
    const shown = { ...merged, features: merged.features.slice() };
    renderer.model = shown;
    renderLods();
    renderer.model = null;
    renderer.load(shown, hiddenClasses, hiddenLods);
    renderLegend();
    updateStats();
    drawnAt = performance.now();
  };
  const progress = (text) => {
    $('progress-text').textContent = text;
    $('progress-bar').style.width = `${(100 * read) / files.length}%`;
  };
  hideDocument();
  busy(false);
  $('progress').hidden = false;
  $('progress-stop').onclick = () => abort.abort();
  try {
    for (const file of files) {
      progress(`${read + 1}/${files.length}  ${file.path}`);
      const model = await api(`/api/model?side=output&path=${encodeURIComponent(file.path)}`,
                              { signal: abort.signal });
      if (token !== loadSeq) return;
      read += 1;
      $('model-title').textContent = `${item.path}/ (${read}/${files.length})`;
      if (!model.features.length) continue;
      if (!merged.bounds) {
        merged.bounds = { min: [...model.bounds.min], max: [...model.bounds.max] };
        merged.crs = model.crs;
        merged.xy_scale = model.xy_scale;
      }
      for (let k = 0; k < 3; k++) {
        merged.bounds.min[k] = Math.min(merged.bounds.min[k], model.bounds.min[k]);
        merged.bounds.max[k] = Math.max(merged.bounds.max[k], model.bounds.max[k]);
      }
      crss.add(model.crs || '-');
      merged.features.push(...model.features);
      merged.triangles += model.triangles;
      // rebuilding the buffer per file grows with the scene, so a long folder
      // redraws about once a second and once more at the end
      if (!drawnAt || performance.now() - drawnAt > 1000) show();
    }
    $('model-title').textContent = `${item.path}/ (${t('files').replace('{n}', files.length)})`;
  } catch (error) {
    if (error.name !== 'AbortError') {
      $('legend').innerHTML = `<div class="legend-row err">${error.message}</div>`;
    } else if (token === loadSeq) {
      $('model-title').textContent = `${item.path}/ (${read}/${files.length}, ${t('stopped')})`;
      writeLog(`${item.path}: ${t('stopped')} ${read}/${files.length}`);
    }
  } finally {
    if (token === loadSeq) {
      if (merged.features.length) show();
      if (crss.size > 1) writeLog(`${t('crsMixed')} ${[...crss].join(', ')}`);
      markStage(null);
      $('progress').hidden = true;
      folderAbort = null;
    }
  }
}

/* A file with nothing to draw shows its text in the middle panel instead of
   leaving an empty canvas; json is reformatted so a one-line file reads. */
async function showDocument(side, path, label) {
  const view = $('docview');
  $('model-title').textContent = label || path;
  $('model-stats').textContent = '';
  $('lod-chips').innerHTML = '';
  canvasWrap.classList.add('doc');
  view.hidden = false;
  view.textContent = '';
  try {
    const file = await api(`/api/file?side=${side}&path=${encodeURIComponent(path)}`);
    if (file.binary) {
      view.textContent = `${path}\n${t('binary')}, ${formatSize(file.size)}`;
      return;
    }
    let text = file.text;
    if (/\.json$/i.test(path) && !file.truncated) {
      try { text = JSON.stringify(JSON.parse(text), null, 2); } catch (error) { /* shown as is */ }
    }
    view.textContent = text + (file.truncated ? `\n...\n(${t('truncated')})` : '');
  } catch (error) {
    view.textContent = error.message;
  }
}

function hideDocument() {
  $('docview').hidden = true;
  canvasWrap.classList.remove('doc');
}

async function loadPreview(side, path) {
  const preview = $('preview');
  try {
    const file = await api(`/api/file?side=${side}&path=${encodeURIComponent(path)}`);
    preview.textContent = file.binary
      ? `${path} (${formatSize(file.size)})`
      : file.text + (file.truncated ? '\n...' : '');
  } catch (error) {
    preview.textContent = error.message;
  }
}

/* --- drop an ifc (and optionally a pipeline config) to convert ------------ */
const canvasWrap = document.querySelector('.canvas-wrap');
let dragDepth = 0;

['dragenter', 'dragover'].forEach((type) => {
  canvasWrap.addEventListener(type, (event) => {
    event.preventDefault();
    if (type === 'dragenter') dragDepth += 1;
    $('dropzone').hidden = false;
  });
});
['dragleave', 'drop'].forEach((type) => {
  canvasWrap.addEventListener(type, (event) => {
    event.preventDefault();
    dragDepth = type === 'drop' ? 0 : Math.max(0, dragDepth - 1);
    if (!dragDepth) $('dropzone').hidden = true;
  });
});

function appendOptions(body) {
  const options = runOptions();
  if (options.version) body.append('version', options.version);
  if (options.save_json) body.append('save_json', '1');
}

canvasWrap.addEventListener('drop', async (event) => {
  const files = [...event.dataTransfer.files];
  const ifc = files.find((f) => f.name.toLowerCase().endsWith('.ifc'));
  const config = files.find((f) => f.name.toLowerCase().endsWith('.json'));
  if (!ifc) {
    writeLog(t('needIfc'));
    return;
  }

  const body = new FormData();
  body.append('ifc', ifc, ifc.name);
  if (config) body.append('pipeline', config, config.name);
  appendOptions(body);

  busy(true, `${t('converting')} ${ifc.name}`);
  writeLog(`${t('converting')} ${ifc.name}${config ? ' + ' + config.name : ''}`);
  try {
    const result = await api('/api/convert', { method: 'POST', body });
    writeLog(result.log);
    if (!result.ok) return;
    await showConverted(result);
  } catch (error) {
    writeLog(error.message);
  } finally {
    busy(false);
  }
});

/* The upload and its result live in the workspace, so both trees are reloaded
   and the produced CityGML is selected. */
async function showConverted(result) {
  if (isNarrow()) showView('middle');
  $('model-title').textContent = result.path;
  hideDocument();
  hiddenClasses.clear();
  hiddenLods.clear();
  renderer.load(result.model, hiddenClasses, hiddenLods);
  renderLegend();
  renderLods();
  updateStats();
  markStage(stageFor(result.path));
  renderTree(await api('/api/tree?side=input'), $('input-tree'), 'input');
  renderTree(await api('/api/tree?side=output'), $('output-tree'), 'output');
  if (result.input) selectedInput = result.input;
  // mark the produced file in the output tree without fetching it again
  const row = [...$('output-tree').querySelectorAll('.node[data-path]')]
    .find((r) => r.dataset.path === result.path);
  if (row) row.classList.add('on');
  markStage(stageFor(result.path));
}

/* Send the edited config together with the selected input, so a rule change is
   visible in the canvas straight away. */
$('apply-config').onclick = async () => {
  if (!selectedInput || !selectedInput.toLowerCase().endsWith('.ifc')) {
    writeLog(t('needInput'));
    return;
  }
  let edited;
  try {
    edited = editedPipeline();
  } catch (error) {
    writeLog(`invalid JSON in ${error.message}`);
    return;
  }

  const body = new FormData();
  body.append('input', selectedInput);
  body.append('pipeline', new Blob([JSON.stringify(edited, null, 2)],
                                   { type: 'application/json' }), 'pipeline.json');
  appendOptions(body);

  busy(true, t('converting'));
  writeLog(t('converting'));
  try {
    const result = await api('/api/convert', { method: 'POST', body });
    writeLog(result.log);
    if (!result.ok) return;
    await showConverted(result);
  } catch (error) {
    writeLog(error.message);
  } finally {
    busy(false);
  }
};

/* The CityGML version the loaded pipeline asks for, if it says. */
function pipelineVersion() {
  for (const stage of pipeline.stages || []) {
    const hit = (stage.properties || []).find((p) => p.key === 'citygml_version');
    if (hit) return String(hit.value).replace(/"/g, '').trim();
  }
  const document_ = pipeline.document || {};
  return document_.citygml_version ? String(document_.citygml_version) : null;
}

/* Every building folder under the folder, each with its own pipeline, then
   the merged city model on the canvas. */
async function runFolder(path, name) {
  busy(true, `${t('running')} ${name}`);
  writeLog(`${t('running')} ${name}`);
  try {
    const options = runOptions();
    const result = await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder: path, version: options.version || undefined,
                             save_json: options.save_json }),
    });
    writeLog(result.log);
    if (!result.ok) return;
    await showConverted(result);
  } catch (error) {
    writeLog(error.message);
  } finally {
    busy(false);
  }
}

/* --- run ------------------------------------------------------------------ */
$('run').onclick = async () => {
  if (!selectedInput || !selectedInput.toLowerCase().endsWith('.ifc')) {
    writeLog(t('selectIfc'));
    return;
  }
  const button = $('run');
  button.disabled = true;
  button.textContent = t('running');
  writeLog('');
  try {
    const options = runOptions();
    const result = await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        path: selectedInput,
        pipeline: selectedPipeline || undefined,
        version: options.version || undefined,
        save_json: options.save_json,
      }),
    });
    writeLog(result.log);
    if (!result.ok) return;
    await showConverted(result);
  } catch (error) {
    writeLog(error.message);
  } finally {
    button.disabled = false;
    button.textContent = t('run');
  }
};

let outputTree = null;

async function refreshOutputs(autoSelect) {
  const tree = await api('/api/tree?side=output');
  outputTree = tree;
  renderTree(tree, $('output-tree'), 'output');
  const wanted = autoSelect || (renderer.model ? $('model-title').textContent : null);
  if (wanted) selectOutput(wanted);
}

/* Click the named output file so the canvas shows the pipeline result. A file
   at the top of the output folder wins over a copy in a subfolder. */
function selectOutput(name) {
  const rows = [...$('output-tree').querySelectorAll('.node[data-path]')];
  const row = rows.find((r) => r.dataset.path === name)
    || rows.find((r) => r.querySelector('.nm').textContent === name);
  if (row) row.click();
  return Boolean(row);
}

/* The LM stage output is the finished model, so show it first. */
function lodOutput(spec) {
  const lm = (spec.stages || []).find((stage) => stage.type === 'LM');
  return lm && lm.output ? lm.output : null;
}

function selectInput(name) {
  if (!name) return;
  const rows = [...$('input-tree').querySelectorAll('.node')];
  const row = rows.find((r) => r.querySelector('.nm').textContent === name);
  if (row) row.click();
}

/* --- boot ----------------------------------------------------------------- */
(async function start() {
  setTheme(params.get('theme') || localStorage.getItem('b2gm.theme') || 'dark');
  applyLanguage();
  try {
    const config = await api('/api/config');
    $('input-path').textContent = config.input_dir;
    $('output-path').textContent = config.output_dir;
    $('pipeline-name').textContent = config.pipeline_name || '';
    pipeline = await api('/api/pipeline');
    renderPipeline();
    renderTree(await api('/api/tree?side=input'), $('input-tree'), 'input');
    await refreshOutputs(lodOutput(pipeline) || config.output);
    // ?select=<file> opens that file from the output tree, else the input tree
    const wanted = params.get('select');
    const folder = params.get('folder') && findDir(outputTree, params.get('folder'));
    if (folder) loadFolder(folder);
    else if (wanted && selectOutput(wanted)) { /* shown */ }
    else selectInput(wanted || config.input_default);
    booted = true;
  } catch (error) {
    writeLog(error.message);
  }
})();

})();

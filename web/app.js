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
    log: 'Log', hint: 'Drag to orbit, wheel to zoom, right drag to pan',
    loading: 'Loading model...', empty: 'No geometry in this file',
    features: 'features', triangles: 'triangles', selectIfc: 'Select an .ifc file first',
    legend: 'Feature classes', toggle: 'Click to show or hide',
    theme: 'Dark', themeLight: 'Light',
  },
  ko: {
    subtitle: 'BIM-GIS 개념 매핑',
    run: '파이프라인 실행', running: '실행 중...',
    inputPanel: '입력', inputFiles: '입력 파일', pipeline: '파이프라인 단계',
    outputPanel: '출력', outputFiles: '출력 파일',
    canvas: '3차원 뷰', preview: '파일 미리보기', previewEmpty: '파일을 선택하세요',
    log: '로그', hint: '드래그 회전, 휠 확대, 우클릭 드래그 이동',
    loading: '모델 읽는 중...', empty: '이 파일에는 형상이 없습니다',
    features: '피처', triangles: '삼각형', selectIfc: '먼저 .ifc 파일을 선택하세요',
    legend: '피처 클래스', toggle: '클릭하면 표시/숨김',
    theme: '다크', themeLight: '라이트',
  },
};

// ?lang=ko&theme=light makes a view shareable and scriptable
const params = new URLSearchParams(location.search);
let lang = params.get('lang') || localStorage.getItem('b2gm.lang') || 'en';
const t = (key) => (TEXT[lang][key] ?? TEXT.en[key] ?? key);

function applyLanguage() {
  document.documentElement.lang = lang;
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  $('lang').textContent = lang.toUpperCase();
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
void main() {
  vec3 n = normalize(vNormal);
  float diffuse = max(dot(n, normalize(uLight)), 0.0);
  float ambient = 0.42;
  gl_FragColor = vec4(vColor * (ambient + 0.75 * diffuse), 1.0);
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
    const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
    const norm = (v) => {
      const l = Math.hypot(v[0], v[1], v[2]) || 1;
      return [v[0] / l, v[1] / l, v[2] / l];
    };
    const cross = (a, b) => [
      a[1] * b[2] - a[2] * b[1],
      a[2] * b[0] - a[0] * b[2],
      a[0] * b[1] - a[1] * b[0],
    ];
    const z = norm(sub(eye, center));
    const x = norm(cross(up, z));
    const y = cross(z, x);
    const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
    return new Float32Array([
      x[0], y[0], z[0], 0,
      x[1], y[1], z[1], 0,
      x[2], y[2], z[2], 0,
      -dot(x, eye), -dot(y, eye), -dot(z, eye), 1,
    ]);
  },
  translation(x, y, z) {
    const out = mat4.identity();
    out[12] = x; out[13] = y; out[14] = z;
    return out;
  },
};

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
    this.pan = [0, 0];
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
    };
    gl.enable(gl.DEPTH_TEST);
    this.buffer = gl.createBuffer();
  }

  readThemeColors() {
    const style = getComputedStyle(document.documentElement);
    this.background = parseColor(style.getPropertyValue('--canvas-bottom')) || [0.1, 0.1, 0.1];
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
        this.pitch = Math.max(-1.5, Math.min(1.5, this.pitch + dy * 0.008));
      } else {
        const scale = this.distance * 0.0016;
        this.pan[0] -= dx * scale;
        this.pan[1] += dy * scale;
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
  load(model, hiddenClasses) {
    if (!this.gl) return;
    const skip = hiddenClasses || new Set();
    const features = model.features.filter(
      (f) => f.faces.length >= 3 && !skip.has(f.gis_class));
    const triangles = features.reduce((sum, f) => sum + f.faces.length / 3, 0);
    // Georeferenced coordinates run to 1e7, past float32 precision, so the
    // buffer holds offsets from the model centre and the camera works there too.
    const { min, max } = model.bounds;
    const origin = [0, 1, 2].map((k) => (min[k] + max[k]) / 2);
    const data = new Float32Array(triangles * 3 * 9);
    let at = 0;
    for (const feature of features) {
      const { verts, faces, color } = feature;
      for (let i = 0; i < faces.length; i += 3) {
        const p = [0, 1, 2].map((k) => {
          const index = faces[i + k] * 3;
          return [verts[index] - origin[0], verts[index + 1] - origin[1],
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

    const keepView = this.model === model;
    this.origin = origin;
    this.center = [0, 0, 0];   // the buffer is already centred on `origin`
    this.radius = Math.max(1e-3, Math.hypot(max[0] - min[0], max[1] - min[1], max[2] - min[2]) / 2);
    this.model = model;
    if (keepView) this.draw(); else this.resetView();
  }

  resetView() {
    this.distance = this.radius * 2.8;
    this.yaw = -0.9;
    this.pitch = 0.5;
    this.pan = [0, 0];
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
    if (!this.count) return;

    const aspect = this.canvas.width / Math.max(1, this.canvas.height);
    // Z-up model space: orbit around the model centre.
    const eye = [
      this.center[0] + this.distance * Math.cos(this.pitch) * Math.cos(this.yaw),
      this.center[1] + this.distance * Math.cos(this.pitch) * Math.sin(this.yaw),
      this.center[2] + this.distance * Math.sin(this.pitch),
    ];
    const view = mat4.lookAt(eye, this.center, [0, 0, 1]);
    const panned = mat4.multiply(mat4.translation(this.pan[0], this.pan[1], 0), view);
    const projection = mat4.perspective(Math.PI / 4, aspect, this.radius * 0.01, this.radius * 200);
    const model = mat4.identity();

    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uniform.mvp, false, mat4.multiply(projection, panned));
    gl.uniformMatrix4fv(this.uniform.model, false, model);
    gl.uniform3f(this.uniform.light, 0.4, 0.6, 0.9);

    const stride = 9 * 4;
    gl.bindBuffer(gl.ARRAY_BUFFER, this.buffer);
    const bind = (location, offset) => {
      gl.enableVertexAttribArray(location);
      gl.vertexAttribPointer(location, 3, gl.FLOAT, false, stride, offset);
    };
    bind(this.attr.pos, 0);
    bind(this.attr.normal, 12);
    bind(this.attr.color, 24);
    gl.drawArrays(gl.TRIANGLES, 0, this.count);
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

/* --- trees ---------------------------------------------------------------- */
let selectedInput = null;

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
      return;
    }
    row.onclick = () => {
      container.querySelectorAll('.node.on').forEach((n) => n.classList.remove('on'));
      row.classList.add('on');
      if (side === 'input') {
        selectedInput = item.path;
        loadPreview(side, item.path);
      } else {
        loadPreview(side, item.path);
        if (item.viewable) loadModel(side, item.path, item.name);
      }
    };
  };
  walk(node, container, 0);
}

const formatSize = (bytes) => {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
};

/* --- pipeline panel ------------------------------------------------------- */
let pipeline = { stages: [] };

function renderPipeline() {
  const host = $('stage-list');
  const chips = $('stage-chips');
  if (!host) return;
  host.innerHTML = '';
  chips.innerHTML = '';
  pipeline.stages.forEach((stage, index) => {
    const chip = document.createElement('span');
    chip.className = 'chip';
    chip.textContent = stage.type;
    chip.title = lang === 'ko' ? stage.title_ko : stage.title_en;
    chips.appendChild(chip);

    const box = document.createElement('div');
    box.className = 'stage' + (index === 0 ? ' open' : '');
    const title = lang === 'ko' ? stage.title_ko : stage.title_en;
    box.innerHTML = `<div class="stage-head"><span class="tag">${stage.type}</span>`
      + `<span class="stage-name">${title}</span></div><div class="stage-body"></div>`;
    const body = box.querySelector('.stage-body');
    stage.properties.forEach((property) => {
      const row = document.createElement('div');
      row.className = 'prop';
      row.innerHTML = `<div class="prop-key">${property.key}</div>`;
      const value = document.createElement('pre');
      value.className = 'prop-val';
      value.textContent = property.value;
      row.appendChild(value);
      body.appendChild(row);
    });
    box.querySelector('.stage-head').onclick = () => box.classList.toggle('open');
    host.appendChild(box);
  });
}

function markStage(type) {
  [...$('stage-chips').children].forEach((chip) => {
    chip.classList.toggle('on', chip.textContent === type);
  });
}

/* --- model + preview ------------------------------------------------------ */
const hiddenClasses = new Set((params.get('hide') || '').split(',').filter(Boolean));

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
      renderer.load(renderer.model, hiddenClasses);
      renderLegend();
    };
  });
}

function updateStats() {
  const model = renderer.model;
  $('model-stats').textContent = model
    ? `${model.features.length} ${t('features')} / ${model.triangles} ${t('triangles')}`
    : '';
}

function busy(on, message) {
  $('overlay').hidden = !on;
  $('overlay-text').textContent = message || '';
}

async function loadModel(side, path, label) {
  busy(true, t('loading'));
  try {
    const model = await api(`/api/model?side=${side}&path=${encodeURIComponent(path)}`);
    $('model-title').textContent = label || path;
    if (!model.features.length) {
      renderer.model = null;
      renderer.count = 0;
      renderer.draw();
      $('legend').innerHTML = `<div class="legend-row">${t('empty')}</div>`;
    } else {
      renderer.load(model, hiddenClasses);
      renderLegend();
    }
    updateStats();
    const stage = /LoD/i.test(path) ? 'LM' : /city/i.test(path) ? 'EM' : null;
    if (stage) markStage(stage);
  } catch (error) {
    $('legend').innerHTML = `<div class="legend-row err">${error.message}</div>`;
  } finally {
    busy(false);
  }
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

/* --- run ------------------------------------------------------------------ */
$('close-log').onclick = () => { $('console').hidden = true; renderer.resize(); };

$('run').onclick = async () => {
  if (!selectedInput || !selectedInput.toLowerCase().endsWith('.ifc')) {
    $('console').hidden = false;
    $('log').textContent = t('selectIfc');
    return;
  }
  const button = $('run');
  button.disabled = true;
  button.textContent = t('running');
  $('console').hidden = false;
  $('log').textContent = '';
  renderer.resize();
  try {
    const result = await api('/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: selectedInput }),
    });
    $('log').textContent = result.log.join('\n');
    await refreshOutputs(lodOutput(pipeline) || null);
  } catch (error) {
    $('log').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = t('run');
  }
};

async function refreshOutputs(autoSelect) {
  const tree = await api('/api/tree?side=output');
  renderTree(tree, $('output-tree'), 'output');
  const wanted = autoSelect || (renderer.model ? $('model-title').textContent : null);
  if (wanted) selectOutput(wanted);
}

/* Click the named output file so the canvas shows the pipeline result. */
function selectOutput(name) {
  const rows = [...$('output-tree').querySelectorAll('.node')];
  const row = rows.find((r) => r.querySelector('.nm').textContent === name);
  if (row) row.click();
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
    pipeline = await api('/api/pipeline');
    renderPipeline();
    renderTree(await api('/api/tree?side=input'), $('input-tree'), 'input');
    await refreshOutputs(lodOutput(pipeline) || config.output);
    selectInput(config.input_default);
  } catch (error) {
    $('log').textContent = error.message;
    $('console').hidden = false;
  }
})();

})();

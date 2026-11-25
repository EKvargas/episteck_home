import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';

const css = readFileSync(new URL('./tokens.css', import.meta.url), 'utf8');

const THEMES = ['warm-household', 'ambient-future', 'premium-hardware', 'editorial-ledger', 'colorful-canvas', 'organic-calm'];
const STATUS = ['--olin-status-success', '--olin-status-caution', '--olin-status-unknown', '--olin-status-progress'];

type Rgba = { r: number; g: number; b: number; a: number };

const themes: Record<string, Record<string, string>> = {};
for (const match of css.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
  const id = /\[data-olin-theme="([a-z-]+)"\]/.exec(match[1])?.[1];
  if (!id) continue;
  const vars: Record<string, string> = {};
  for (const decl of match[2].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/g)) vars[decl[1]] = decl[2].trim();
  themes[id] = vars;
}

function parse(value: string): Rgba {
  const hex = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value);
  if (hex) {
    const h = hex[1].length === 3 ? [...hex[1]].map((c) => c + c).join('') : hex[1];
    return { r: parseInt(h.slice(0, 2), 16), g: parseInt(h.slice(2, 4), 16), b: parseInt(h.slice(4, 6), 16), a: 1 };
  }
  const rgba = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+)\s*)?\)$/.exec(value);
  if (rgba) return { r: +rgba[1], g: +rgba[2], b: +rgba[3], a: rgba[4] === undefined ? 1 : +rgba[4] };
  throw new Error(`unparseable colour: ${value}`);
}

function over(top: Rgba, bottom: Rgba): Rgba {
  const mix = (t: number, b: number) => t * top.a + b * (1 - top.a);
  return { r: mix(top.r, bottom.r), g: mix(top.g, bottom.g), b: mix(top.b, bottom.b), a: 1 };
}

function luminance({ r, g, b }: Rgba): number {
  const lin = (v: number) => {
    const c = v / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
}

function contrast(a: Rgba, b: Rgba): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

function token(theme: string, name: string): Rgba {
  const value = themes[theme]?.[name];
  assert.ok(value, `${theme} defines ${name}`);
  return parse(value);
}

function surfaces(theme: string) {
  const canvas = token(theme, '--olin-bg-canvas');
  const card = over(token(theme, '--olin-surface-card'), canvas);
  const track = over(token(theme, '--olin-badge-bg'), card);
  return { canvas, card, track };
}

const fmt = (n: number) => n.toFixed(2);

test('all six themes are defined', () => assert.deepEqual(Object.keys(themes).sort(), [...THEMES].sort()));

test('every status colour reads at 4.5:1 on the card, in every theme', () => {
  for (const theme of THEMES) {
    const { card } = surfaces(theme);
    for (const name of STATUS) {
      const ratio = contrast(token(theme, name), card);
      assert.ok(ratio >= 4.5, `${theme} ${name} on card is ${fmt(ratio)}:1`);
    }
  }
});

test('status fills keep 3:1 against the bar track and the card', () => {
  for (const theme of THEMES) {
    const { card, track } = surfaces(theme);
    for (const name of STATUS) {
      const colour = token(theme, name);
      assert.ok(contrast(colour, track) >= 3, `${theme} ${name} on track is ${fmt(contrast(colour, track))}:1`);
      assert.ok(contrast(colour, card) >= 3, `${theme} ${name} on card is ${fmt(contrast(colour, card))}:1`);
    }
  }
});

test('the four status colours differ within each theme, in hue and in lightness', () => {
  for (const theme of THEMES) {
    const colours = STATUS.map((name) => ({ name, rgb: token(theme, name) }));
    for (let i = 0; i < colours.length; i += 1) {
      for (let j = i + 1; j < colours.length; j += 1) {
        const a = colours[i];
        const b = colours[j];
        assert.notDeepEqual(a.rgb, b.rgb, `${theme} ${a.name} equals ${b.name}`);
        const ratio = contrast(a.rgb, b.rgb);
        assert.ok(ratio >= 1.15, `${theme} ${a.name} vs ${b.name} differ by only ${fmt(ratio)}:1 in lightness`);
      }
    }
  }
});

test('text-main reads at 4.5:1 on the canvas (tabs, header, Actualizado)', () => {
  for (const theme of THEMES) {
    const ratio = contrast(token(theme, '--olin-text-main'), surfaces(theme).canvas);
    assert.ok(ratio >= 4.5, `${theme} text-main on canvas is ${fmt(ratio)}:1`);
  }
});

test('person chips: badge-text on badge-bg and text-muted on the card read at 4.5:1', () => {
  for (const theme of THEMES) {
    const { card, track } = surfaces(theme);
    const active = contrast(token(theme, '--olin-badge-text'), track);
    const inactive = contrast(token(theme, '--olin-text-muted'), card);
    assert.ok(active >= 4.5, `${theme} badge-text on badge-bg is ${fmt(active)}:1`);
    assert.ok(inactive >= 4.5, `${theme} text-muted on card is ${fmt(inactive)}:1`);
  }
});

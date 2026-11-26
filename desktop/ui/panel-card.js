// V2: the savings card, drawn on a canvas in the panel (nothing leaves the
// computer until the user copies or posts it). Layout math lives in
// panel-lib.js (cardLayout); this only paints.
import { cardLayout } from "./panel-lib.js";

export const CARD_W = 1200;
export const CARD_H = 630;
const FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif';

function loadImage(src) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = src;
  });
}

export async function drawCard(canvas, text) {
  canvas.width = CARD_W;
  canvas.height = CARD_H;
  const ctx = canvas.getContext("2d");
  const font = (size, weight) => `${weight} ${size}px ${FONT}`;
  const measureWith = (weight) => (t, size) => {
    ctx.font = font(size, weight);
    return ctx.measureText(t).width;
  };
  // Measure each line in the weight it's drawn in.
  const measure = (t, size) => Math.max(measureWith(700)(t, size), measureWith(500)(t, size));
  const L = cardLayout(measure, text, { width: CARD_W, height: CARD_H });

  const bg = ctx.createLinearGradient(0, 0, CARD_W, CARD_H);
  bg.addColorStop(0, "#1B5FCC");
  bg.addColorStop(0.55, "#2D7FF9");
  bg.addColorStop(1, "#6AA6FF");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, CARD_W, CARD_H);
  // A soft light in the top-right corner, like the panel's header wash.
  const glow = ctx.createRadialGradient(CARD_W * 0.9, 0, 0, CARD_W * 0.9, 0, CARD_W * 0.6);
  glow.addColorStop(0, "rgba(255,255,255,0.18)");
  glow.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = glow;
  ctx.fillRect(0, 0, CARD_W, CARD_H);

  ctx.textBaseline = "alphabetic";
  ctx.fillStyle = "rgba(255,255,255,0.88)";
  ctx.font = font(L.kicker.size, 500);
  ctx.fillText(L.kicker.text, L.kicker.x, L.kicker.y);

  ctx.fillStyle = "#FFFFFF";
  ctx.font = font(L.headline.size, 700);
  ctx.fillText(L.headline.text, L.headline.x, L.headline.y);
  if (L.sub.text) {
    ctx.font = font(L.sub.size, 700);
    ctx.fillText(L.sub.text, L.sub.x, L.sub.y);
  }

  const logo = await loadImage("assets/orca.png");
  if (logo) ctx.drawImage(logo, L.logo.x, L.logo.y, L.logo.size, L.logo.size);
  ctx.font = font(L.brand.size, 700);
  ctx.fillText(L.brand.text, L.brand.x, L.brand.y);
  ctx.font = font(L.footer.size, 600);
  ctx.fillStyle = "rgba(255,255,255,0.92)";
  ctx.fillText(L.footer.text, L.footer.x, L.footer.y);
  return canvas;
}

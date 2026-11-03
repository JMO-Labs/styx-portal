// Renders each hero variant frame-by-frame (blue logo, reveal intro, dark) to PNGs.
// Usage: cd e2e && node ../scripts/brand/export.cjs <outdir> [fps]   (playwright resolves from e2e/)
// Then per variant v (shared palette + no dither keeps frames diffable; per-frame dither ~3x size):
//   magick $v/f0000.png $v/f0060.png $v/f0120.png +append -colors 96 -unique-colors pal.png
//   magick -delay 1x15 -loop 0 $v/f*.png +dither -remap pal.png -layers OptimizeTransparency $v.gif
// README uses hero frames resized to 900x300 as GIF (styx-banner.gif). Docs use VP9 WebM + JPEG poster (frame 90) per variant
// (hero→styx-hero, slim→styx-header, wide→styx-wide). Playwright's bundled ffmpeg only decodes MJPEG:
//   for f in $v/f*.png; do magick $f -quality 97 jpg:-; done | ffmpeg-linux -f image2pipe -c:v mjpeg \
//     -framerate 15 -i pipe:0 -c:v libvpx-vp9 -b:v 0 -crf 34 -pix_fmt yuv420p -row-mt 1 -an $name.webm
// social-preview.png = wide frame 90 (upload in GitHub Settings → Social preview).
const { chromium } = require(require.resolve("playwright", { paths: [process.cwd()] }));
const fs = require("fs"), path = require("path");
(async () => {
  const out = process.argv[2], fps = +(process.argv[3] || 15), L = 12;
  const b = await chromium.launch(), p = await b.newPage({ viewport: { width: 1400, height: 900 } });
  await p.goto("file://" + path.resolve(__dirname, "hero.html"));
  await p.evaluate(() => document.fonts.load("800 40px Commissioner"));
  await p.evaluate(() => { window.requestAnimationFrame = () => 0; }); // stop live loop; we drive frames
  for (const id of ["hero", "slim", "wide", "sq"]) {
    fs.mkdirSync(path.join(out, id), { recursive: true });
    for (let i = 0; i < L * fps; i++) {
      const url = await p.evaluate(([id, t]) => { window.renderAt(id, t); return document.getElementById(id).toDataURL(); }, [id, i / fps]);
      fs.writeFileSync(path.join(out, id, `f${String(i).padStart(4, "0")}.png`), Buffer.from(url.split(",")[1], "base64"));
    }
  }
  await b.close();
})();

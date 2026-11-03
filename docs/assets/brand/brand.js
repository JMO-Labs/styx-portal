// Brand banner videos: honour reduced motion (poster frame stays), click toggles play/pause (WCAG 2.2.2).
document.addEventListener("DOMContentLoaded", () => document.querySelectorAll("video.styx-brand").forEach((v) => {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) { v.removeAttribute("autoplay"); v.pause(); }
  v.addEventListener("click", () => (v.paused ? v.play() : v.pause()));
}));
